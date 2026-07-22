from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import (
    BinanceSpotSymbol,
    FuturesBookTicker,
    FuturesFundingHistory,
    FuturesKline1h,
    FuturesKline4h,
    FuturesKline15m,
    FuturesKline24h,
    FuturesMarkFunding,
    FuturesOpenInterest,
    MarketStateAlignment,
    MarketlabActiveUniverse,
    SpotBookTicker,
)
from app.services.utils import utcnow

MARKET_STATE_TIMEFRAMES = {
    "15m": {"minutes": 15, "model": FuturesKline15m},
    "1h": {"minutes": 60, "model": FuturesKline1h},
    "4h": {"minutes": 240, "model": FuturesKline4h},
    "24h": {"minutes": 1440, "model": FuturesKline24h},
}
SNAPSHOT_STATUSES = ("FRESH", "STALE", "MISSING", "NOT_APPLICABLE")
FUNDING_STATUSES = ("FUNDING_ALIGNED", "FUNDING_CARRIED_FORWARD", "FUNDING_STALE", "FUNDING_MISSING")


@dataclass(frozen=True)
class MarketStateAlignmentConfig:
    current_oi_max_age_seconds: int = 5 * 60
    mark_max_age_seconds: int = 5 * 60
    futures_book_max_age_seconds: int = 10 * 60
    spot_book_max_age_seconds: int = 10 * 60
    funding_max_carry_forward_seconds: int = 9 * 60 * 60


@dataclass
class MarketStateAlignmentResult:
    timeframe: str
    symbols: int
    inserted_count: int
    updated_count: int
    snapshot_status_counts: dict[str, int]
    funding_status_counts: dict[str, int]


class SnapshotFundingAlignmentService:
    def __init__(self, db: Session, config: MarketStateAlignmentConfig | None = None) -> None:
        self.db = db
        self.config = config or MarketStateAlignmentConfig()

    def run(
        self,
        timeframes: list[str],
        symbols: list[str] | None = None,
        limit_windows: int | None = None,
        dry_run: bool = False,
    ) -> list[MarketStateAlignmentResult]:
        active_symbols = self._active_symbols(symbols)
        valid_spot_symbols = self._valid_spot_symbols(active_symbols)
        results = [
            self._run_timeframe(timeframe, active_symbols, valid_spot_symbols, limit_windows, dry_run)
            for timeframe in timeframes
            if timeframe in MARKET_STATE_TIMEFRAMES
        ]
        if not dry_run:
            self.db.commit()
        return results

    def status_summary(self) -> dict[str, Any]:
        latest = {f"latest_{timeframe}": None for timeframe in MARKET_STATE_TIMEFRAMES}
        counts = {
            "fresh_count": 0,
            "stale_count": 0,
            "missing_count": 0,
            "not_applicable_count": 0,
            "funding_aligned_count": 0,
            "funding_carried_forward_count": 0,
            "funding_stale_count": 0,
            "funding_missing_count": 0,
        }
        tables: dict[str, dict[str, dict[str, int]]] = {}
        rows = self.db.execute(
            select(
                MarketStateAlignment.timeframe,
                MarketStateAlignment.snapshot_alignment_status,
                MarketStateAlignment.funding_alignment_status,
                func.count(),
                func.max(MarketStateAlignment.window_close_time),
            ).group_by(
                MarketStateAlignment.timeframe,
                MarketStateAlignment.snapshot_alignment_status,
                MarketStateAlignment.funding_alignment_status,
            )
        ).all()
        for timeframe, snapshot_status, funding_status, count, latest_time in rows:
            latest_key = f"latest_{timeframe}"
            if latest_time is not None and (latest[latest_key] is None or latest_time > latest[latest_key]):
                latest[latest_key] = latest_time
            snapshot_table = tables.setdefault(timeframe, {}).setdefault("snapshot", {})
            snapshot_table[snapshot_status] = snapshot_table.get(snapshot_status, 0) + count
            snapshot_key = {
                "FRESH": "fresh_count",
                "STALE": "stale_count",
                "MISSING": "missing_count",
                "NOT_APPLICABLE": "not_applicable_count",
            }[snapshot_status]
            counts[snapshot_key] += count
            funding_table = tables.setdefault(timeframe, {}).setdefault("funding", {})
            funding_table[funding_status] = funding_table.get(funding_status, 0) + count
            funding_key = {
                "FUNDING_ALIGNED": "funding_aligned_count",
                "FUNDING_CARRIED_FORWARD": "funding_carried_forward_count",
                "FUNDING_STALE": "funding_stale_count",
                "FUNDING_MISSING": "funding_missing_count",
            }[funding_status]
            counts[funding_key] += count

        return {
            "latest": latest,
            "counts": counts,
            "tables": tables,
            "thresholds": {
                "current_oi_max_age_seconds": self.config.current_oi_max_age_seconds,
                "mark_max_age_seconds": self.config.mark_max_age_seconds,
                "futures_book_max_age_seconds": self.config.futures_book_max_age_seconds,
                "spot_book_max_age_seconds": self.config.spot_book_max_age_seconds,
                "funding_max_carry_forward_seconds": self.config.funding_max_carry_forward_seconds,
            },
        }

    def _run_timeframe(
        self,
        timeframe: str,
        active_symbols: list[str],
        valid_spot_symbols: set[str],
        limit_windows: int | None,
        dry_run: bool,
    ) -> MarketStateAlignmentResult:
        target_model = MARKET_STATE_TIMEFRAMES[timeframe]["model"]
        inserted = 0
        updated = 0
        snapshot_counts = {status: 0 for status in SNAPSHOT_STATUSES}
        funding_counts = {status: 0 for status in FUNDING_STATUSES}
        now = utcnow()

        for symbol in active_symbols:
            statement = (
                select(target_model)
                .where(target_model.symbol == symbol, target_model.aggregation_status == "AGG_READY")
                .order_by(target_model.open_time.desc())
            )
            if limit_windows is not None and limit_windows > 0:
                statement = statement.limit(limit_windows)
            windows = list(reversed(self.db.scalars(statement).all()))
            for window in windows:
                payload = self._align_window(
                    symbol=symbol,
                    timeframe=timeframe,
                    window_open=_as_utc(window.open_time),
                    window_close=_as_utc(window.close_time),
                    spot_applicable=symbol in valid_spot_symbols,
                    now=now,
                )
                action = self._upsert(payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                snapshot_counts[payload["snapshot_alignment_status"]] += 1
                funding_counts[payload["funding_alignment_status"]] += 1

        return MarketStateAlignmentResult(
            timeframe=timeframe,
            symbols=len(active_symbols),
            inserted_count=inserted,
            updated_count=updated,
            snapshot_status_counts=snapshot_counts,
            funding_status_counts=funding_counts,
        )

    def _align_window(
        self,
        symbol: str,
        timeframe: str,
        window_open: datetime,
        window_close: datetime,
        spot_applicable: bool,
        now: datetime,
    ) -> dict[str, Any]:
        current_oi = self._latest_row(FuturesOpenInterest, symbol, FuturesOpenInterest.event_time, window_close)
        mark = self._latest_row(FuturesMarkFunding, symbol, FuturesMarkFunding.event_time, window_close)
        futures_book = self._latest_row(FuturesBookTicker, symbol, FuturesBookTicker.event_time, window_close)
        spot_book = (
            self._latest_row(SpotBookTicker, symbol, SpotBookTicker.event_time, window_close)
            if spot_applicable
            else None
        )
        funding = self._latest_row(FuturesFundingHistory, symbol, FuturesFundingHistory.funding_time, window_close)

        current_oi_age = _age_seconds(window_close, current_oi.event_time) if current_oi else None
        mark_age = _age_seconds(window_close, mark.event_time) if mark else None
        futures_book_age = _age_seconds(window_close, futures_book.event_time) if futures_book else None
        spot_book_age = _age_seconds(window_close, spot_book.event_time) if spot_book else None
        funding_age = _age_seconds(window_close, funding.funding_time) if funding else None

        current_oi_status = _freshness_status(current_oi_age, self.config.current_oi_max_age_seconds)
        mark_status = _freshness_status(mark_age, self.config.mark_max_age_seconds)
        futures_book_status = _freshness_status(futures_book_age, self.config.futures_book_max_age_seconds)
        spot_book_status = (
            _freshness_status(spot_book_age, self.config.spot_book_max_age_seconds)
            if spot_applicable
            else "NOT_APPLICABLE"
        )
        snapshot_status = _combined_snapshot_status(
            [current_oi_status, mark_status, futures_book_status, spot_book_status]
        )
        funding_status, carry_status = self._funding_status(funding, mark, window_open, window_close)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "window_open_time": window_open,
            "window_close_time": window_close,
            "snapshot_alignment_status": snapshot_status,
            "funding_alignment_status": funding_status,
            "current_oi_status": current_oi_status,
            "mark_status": mark_status,
            "futures_book_status": futures_book_status,
            "spot_book_status": spot_book_status,
            "current_oi": current_oi.open_interest if current_oi else None,
            "current_oi_event_time": current_oi.event_time if current_oi else None,
            "current_oi_age_seconds": current_oi_age,
            "mark_price": mark.mark_price if mark else None,
            "index_price": mark.index_price if mark else None,
            "last_funding_rate": mark.last_funding_rate if mark else None,
            "next_funding_time": mark.next_funding_time if mark else None,
            "mark_event_time": mark.event_time if mark else None,
            "mark_age_seconds": mark_age,
            "futures_bid_price": futures_book.bid_price if futures_book else None,
            "futures_ask_price": futures_book.ask_price if futures_book else None,
            "futures_spread_pct": _spread_pct(futures_book.bid_price, futures_book.ask_price) if futures_book else None,
            "futures_book_event_time": futures_book.event_time if futures_book else None,
            "futures_book_age_seconds": futures_book_age,
            "spot_bid_price": spot_book.bid_price if spot_book else None,
            "spot_ask_price": spot_book.ask_price if spot_book else None,
            "spot_spread_pct": _spread_pct(spot_book.bid_price, spot_book.ask_price) if spot_book else None,
            "spot_book_event_time": spot_book.event_time if spot_book else None,
            "spot_book_age_seconds": spot_book_age,
            "latest_funding_rate": funding.funding_rate if funding else None,
            "latest_funding_time": funding.funding_time if funding else None,
            "latest_funding_mark_price": funding.mark_price if funding else None,
            "funding_age_seconds": funding_age,
            "funding_carry_forward_status": carry_status,
            "details_json": {
                "spot_applicable": spot_applicable,
                "thresholds": {
                    "current_oi_max_age_seconds": self.config.current_oi_max_age_seconds,
                    "mark_max_age_seconds": self.config.mark_max_age_seconds,
                    "futures_book_max_age_seconds": self.config.futures_book_max_age_seconds,
                    "spot_book_max_age_seconds": self.config.spot_book_max_age_seconds,
                    "funding_max_carry_forward_seconds": self.config.funding_max_carry_forward_seconds,
                },
            },
            "created_at": now,
            "updated_at": now,
        }

    def _funding_status(
        self,
        funding: FuturesFundingHistory | None,
        mark: FuturesMarkFunding | None,
        window_open: datetime,
        window_close: datetime,
    ) -> tuple[str, str]:
        if funding is None:
            return "FUNDING_MISSING", "MISSING"
        funding_time = _as_utc(funding.funding_time)
        if window_open <= funding_time < window_close:
            return "FUNDING_ALIGNED", "IN_WINDOW"

        max_deadline = funding_time + timedelta(seconds=self.config.funding_max_carry_forward_seconds)
        if mark is not None and mark.next_funding_time is not None:
            next_funding_time = _as_utc(mark.next_funding_time)
            if next_funding_time > funding_time:
                max_deadline = min(max_deadline, next_funding_time)

        if window_close <= max_deadline:
            return "FUNDING_CARRIED_FORWARD", "CARRIED_FORWARD"
        return "FUNDING_STALE", "STALE"

    def _latest_row(self, model, symbol: str, time_column, window_close: datetime):
        return self.db.scalar(
            select(model)
            .where(model.symbol == symbol, time_column <= window_close)
            .order_by(desc(time_column))
            .limit(1)
        )

    def _upsert(self, payload: dict[str, Any], dry_run: bool) -> str:
        row = self.db.scalar(
            select(MarketStateAlignment).where(
                MarketStateAlignment.symbol == payload["symbol"],
                MarketStateAlignment.timeframe == payload["timeframe"],
                MarketStateAlignment.window_open_time == payload["window_open_time"],
            )
        )
        if dry_run:
            return "updated" if row else "inserted"
        if row:
            for key, value in payload.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        self.db.add(MarketStateAlignment(**payload))
        return "inserted"

    def _active_symbols(self, requested: list[str] | None) -> list[str]:
        query = (
            select(MarketlabActiveUniverse.symbol)
            .where(
                MarketlabActiveUniverse.is_active.is_(True),
                MarketlabActiveUniverse.collection_tier == "FULL_ACTIVE",
                MarketlabActiveUniverse.is_full_active.is_(True),
            )
            .order_by(MarketlabActiveUniverse.rank.asc())
        )
        active = self.db.scalars(query).all()
        if not requested:
            return active
        requested_set = {symbol.upper() for symbol in requested}
        return [symbol for symbol in active if symbol in requested_set]

    def _valid_spot_symbols(self, active_symbols: list[str]) -> set[str]:
        rows = self.db.scalars(
            select(BinanceSpotSymbol.symbol).where(
                BinanceSpotSymbol.status == "TRADING",
                BinanceSpotSymbol.is_spot_trading_allowed.is_(True),
                BinanceSpotSymbol.symbol.in_(active_symbols),
            )
        ).all()
        return set(rows)


def _freshness_status(age_seconds: int | None, max_age_seconds: int) -> str:
    if age_seconds is None:
        return "MISSING"
    return "FRESH" if age_seconds <= max_age_seconds else "STALE"


def _combined_snapshot_status(statuses: list[str]) -> str:
    applicable = [status for status in statuses if status != "NOT_APPLICABLE"]
    if not applicable:
        return "NOT_APPLICABLE"
    if any(status == "MISSING" for status in applicable):
        return "MISSING"
    if any(status == "STALE" for status in applicable):
        return "STALE"
    return "FRESH"


def _age_seconds(window_close: datetime, event_time: datetime) -> int:
    return max(0, int((_as_utc(window_close) - _as_utc(event_time)).total_seconds()))


def _spread_pct(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is None or ask is None:
        return None
    midpoint = (bid + ask) / Decimal("2")
    if midpoint == 0:
        return None
    return ((ask - bid) / midpoint) * Decimal("100")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
