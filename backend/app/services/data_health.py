from datetime import UTC, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import (
    DataHealthSnapshot,
    FuturesKline1m,
    FuturesMarkFunding,
    FuturesOpenInterest,
    MarketlabActiveUniverse,
    SpotKline1m,
)
from app.services.utils import json_safe, utcnow


def refresh_data_health(db: Session) -> list[dict]:
    now = utcnow()
    rows: list[dict] = []
    universe_rows = db.scalars(
        select(MarketlabActiveUniverse)
        .where(MarketlabActiveUniverse.is_active.is_(True))
        .order_by(MarketlabActiveUniverse.rank.asc())
    ).all()

    for universe_row in universe_rows:
        symbol = universe_row.symbol
        latest_futures = _latest(db, FuturesKline1m, symbol, FuturesKline1m.close_time)
        latest_spot = _latest(db, SpotKline1m, symbol, SpotKline1m.close_time)
        latest_oi = _latest(db, FuturesOpenInterest, symbol, FuturesOpenInterest.event_time)
        latest_funding = _latest(db, FuturesMarkFunding, symbol, FuturesMarkFunding.event_time)
        futures_count = _count(db, FuturesKline1m, symbol)
        spot_count = _count(db, SpotKline1m, symbol)
        if universe_row.collection_tier == "FULL_ACTIVE":
            status, reason = _status(
                now,
                latest_futures,
                latest_spot,
                latest_oi,
                latest_funding,
                futures_count,
                spot_count,
            )
        else:
            status, reason = "NOT_ACTIVE", "not in current top universe"
        universe_row.is_signal_eligible = status == "READY"
        universe_row.updated_at = now
        payload = {
            "symbol": symbol,
            "snapshot_time": now,
            "status": status,
            "collection_tier": universe_row.collection_tier,
            "rank": universe_row.rank,
            "latest_futures_candle_time": latest_futures,
            "latest_spot_candle_time": latest_spot,
            "latest_open_interest_time": latest_oi,
            "latest_funding_time": latest_funding,
            "futures_candle_count": futures_count,
            "spot_candle_count": spot_count,
            "reason": reason,
        }
        db.add(
            DataHealthSnapshot(
                symbol=symbol,
                snapshot_time=now,
                status=status,
                latest_futures_candle_time=latest_futures,
                latest_spot_candle_time=latest_spot,
                latest_open_interest_time=latest_oi,
                latest_funding_time=latest_funding,
                latest_futures_book_time=None,
                latest_spot_book_time=None,
                reason=reason,
                raw_json=json_safe(payload),
                created_at=now,
                updated_at=now,
            )
        )
        rows.append(json_safe(payload))

    db.commit()
    return rows


def _latest(db: Session, model, symbol: str, column):
    return db.scalar(select(func.max(column)).where(model.symbol == symbol))


def _count(db: Session, model, symbol: str) -> int:
    return db.scalar(select(func.count()).where(model.symbol == symbol)) or 0


def _status(
    now,
    latest_futures,
    latest_spot,
    latest_oi,
    latest_funding,
    futures_count: int,
    spot_count: int,
) -> tuple[str, str]:
    latest_futures = _as_utc(latest_futures)
    latest_spot = _as_utc(latest_spot)
    latest_oi = _as_utc(latest_oi)
    latest_funding = _as_utc(latest_funding)

    if latest_futures is None:
        return "MISSING_FUTURES", "missing futures 1m candles"
    if latest_oi is None:
        return "MISSING_OI", "missing futures open interest"
    if latest_funding is None:
        return "MISSING_FUNDING", "missing futures mark/funding"
    if latest_spot is None:
        return "MISSING_SPOT", "missing spot 1m candles"

    stale = []
    checks = [
        ("futures candle", latest_futures, timedelta(minutes=5)),
        ("spot candle", latest_spot, timedelta(minutes=5)),
        ("open interest", latest_oi, timedelta(minutes=10)),
        ("mark/funding", latest_funding, timedelta(minutes=10)),
    ]
    for label, value, max_age in checks:
        if now - value > max_age:
            stale.append(label)

    if stale:
        return "STALE", "stale: " + ", ".join(stale)
    if futures_count < 5:
        return "WARMUP", f"warming up futures candles: {futures_count}/5"
    if 0 < spot_count < 5:
        return "WARMUP", f"warming up spot candles: {spot_count}/5"
    return "READY", "all required datasets fresh"


def _as_utc(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
