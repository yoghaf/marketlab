from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.market import (
    BinanceSpotSymbol,
    CollectorError,
    CollectorRun,
    FuturesKline4h,
    FuturesKline24h,
    MarketlabActiveUniverse,
    SpotKline4h,
    SpotKline24h,
)
from app.services.binance_client import BinanceClient, BinanceClientError
from app.services.rate_limit import RateLimitManager
from app.services.utils import decimal_or_none, duration_seconds, json_safe, ms_to_utc, utcnow


TIMEFRAME_CONFIG = {
    "4h": {"minutes": 240, "interval": "4h", "models": {"futures": FuturesKline4h, "spot": SpotKline4h}},
    "24h": {"minutes": 1440, "interval": "1d", "models": {"futures": FuturesKline24h, "spot": SpotKline24h}},
}
MARKETS = {"futures", "spot"}
MAX_BINANCE_KLINE_LIMIT = 1500


@dataclass(frozen=True)
class NativeBackfillResult:
    market: str
    timeframe: str
    symbols: int
    fetched_count: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    error_count: int
    latest_close_time: datetime | None


class NativeOhlcvBackfillService:
    """Backfill higher timeframe OHLCV from native Binance klines.

    This intentionally does not build trading rules. It only stores closed native
    Binance candles into the existing aggregate tables so ATR/lookback can warm up.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.rate_limit_manager = RateLimitManager()

    async def run(
        self,
        timeframes: list[str],
        markets: list[str],
        days: int,
        symbols: list[str] | None = None,
        limit_symbols: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        cleaned_timeframes = [timeframe for timeframe in timeframes if timeframe in TIMEFRAME_CONFIG]
        cleaned_markets = [market for market in markets if market in MARKETS]
        active_symbols = symbols or self._active_symbols(limit_symbols)
        results: list[NativeBackfillResult] = []
        for market in cleaned_markets:
            market_symbols = self._market_symbols(market, active_symbols)
            for timeframe in cleaned_timeframes:
                results.append(await self._run_market_timeframe(market, timeframe, market_symbols, days, dry_run))
        return {
            "results": [
                {
                    "market": item.market,
                    "timeframe": item.timeframe,
                    "symbols": item.symbols,
                    "fetched_count": item.fetched_count,
                    "inserted_count": item.inserted_count,
                    "updated_count": item.updated_count,
                    "skipped_count": item.skipped_count,
                    "error_count": item.error_count,
                    "latest_close_time": item.latest_close_time,
                }
                for item in results
            ],
            "inserted_count": sum(item.inserted_count for item in results),
            "updated_count": sum(item.updated_count for item in results),
            "fetched_count": sum(item.fetched_count for item in results),
            "error_count": sum(item.error_count for item in results),
            "dry_run": dry_run,
        }

    async def _run_market_timeframe(
        self,
        market: str,
        timeframe: str,
        symbols: list[str],
        days: int,
        dry_run: bool,
    ) -> NativeBackfillResult:
        config = TIMEFRAME_CONFIG[timeframe]
        interval = str(config["interval"])
        minutes = int(config["minutes"])
        model = config["models"][market]
        latest_close = _latest_closed_boundary(utcnow(), minutes)
        start = latest_close - timedelta(days=max(1, days))
        limit = min(MAX_BINANCE_KLINE_LIMIT, max(1, days + 2))
        fetched = 0
        inserted = 0
        updated = 0
        skipped = 0
        errors = 0

        async with BinanceClient(self.db, f"native_{market}_ohlcv_{timeframe}", None, self.rate_limit_manager) as client:
            for symbol in symbols:
                try:
                    payload = await self._fetch(client, market, symbol, interval, limit, start, latest_close)
                except BinanceClientError as exc:
                    errors += 1
                    self._record_error(f"native_{market}_ohlcv_{timeframe}", symbol, exc)
                    continue

                fetched += len(payload)
                for row in payload:
                    values = native_kline_to_aggregate_values(symbol, row, timeframe, interval, minutes, utcnow())
                    if values is None:
                        skipped += 1
                        continue
                    action = self._upsert(model, values, dry_run)
                    inserted += int(action == "inserted")
                    updated += int(action == "updated")
                if not dry_run:
                    self.db.commit()

        return NativeBackfillResult(
            market=market,
            timeframe=timeframe,
            symbols=len(symbols),
            fetched_count=fetched,
            inserted_count=inserted,
            updated_count=updated,
            skipped_count=skipped,
            error_count=errors,
            latest_close_time=latest_close,
        )

    async def _fetch(
        self,
        client: BinanceClient,
        market: str,
        symbol: str,
        interval: str,
        limit: int,
        start: datetime,
        end: datetime,
    ) -> list[list[Any]]:
        start_ms = _datetime_to_ms(start)
        end_ms = _datetime_to_ms(end) - 1
        if market == "futures":
            return await client.futures_klines(symbol, interval, limit=limit, start_time_ms=start_ms, end_time_ms=end_ms)
        return await client.spot_klines(symbol, interval, limit=limit, start_time_ms=start_ms, end_time_ms=end_ms)

    def _upsert(self, model, values: dict[str, Any], dry_run: bool) -> str:
        row = self.db.scalar(
            select(model).where(model.symbol == values["symbol"], model.open_time == values["open_time"])
        )
        if dry_run:
            return "updated" if row else "inserted"
        if row:
            for key, value in values.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        self.db.add(model(**values))
        return "inserted"

    def _active_symbols(self, limit_symbols: int | None) -> list[str]:
        query = (
            select(MarketlabActiveUniverse.symbol)
            .where(
                MarketlabActiveUniverse.is_active.is_(True),
                MarketlabActiveUniverse.collection_tier == "FULL_ACTIVE",
                MarketlabActiveUniverse.is_full_active.is_(True),
            )
            .order_by(MarketlabActiveUniverse.rank.asc())
        )
        if limit_symbols:
            query = query.limit(limit_symbols)
        return list(self.db.scalars(query).all())

    def _market_symbols(self, market: str, symbols: list[str]) -> list[str]:
        if market == "futures":
            return symbols
        valid_spot = set(
            self.db.scalars(
                select(BinanceSpotSymbol.symbol).where(
                    BinanceSpotSymbol.symbol.in_(symbols),
                    BinanceSpotSymbol.status == "TRADING",
                    BinanceSpotSymbol.is_spot_trading_allowed.is_(True),
                )
            ).all()
        )
        return [symbol for symbol in symbols if symbol in valid_spot]

    def _record_error(self, collector_name: str, symbol: str, exc: BinanceClientError) -> None:
        self.db.rollback()
        self.db.add(
            CollectorError(
                collector_run_id=None,
                collector_name=collector_name,
                symbol=symbol,
                endpoint=None,
                status_code=exc.status_code,
                error_type=type(exc).__name__,
                message=str(exc),
                raw_json=exc.payload if isinstance(exc.payload, dict) else {"payload": str(exc.payload)} if exc.payload else None,
                created_at=utcnow(),
            )
        )
        self.db.commit()


def native_kline_to_aggregate_values(
    symbol: str,
    item: list[Any],
    timeframe: str,
    source_interval: str,
    minutes: int,
    now: datetime,
) -> dict[str, Any] | None:
    open_time = ms_to_utc(item[0])
    if open_time is None:
        return None
    close_time = open_time + timedelta(minutes=minutes)
    if close_time > now:
        return None

    volume = decimal_or_none(item[5])
    quote_volume = decimal_or_none(item[7])
    taker_buy_base = decimal_or_none(item[9])
    taker_buy_quote = decimal_or_none(item[10])
    return {
        "symbol": symbol,
        "open_time": open_time,
        "close_time": close_time,
        "open": decimal_or_none(item[1]),
        "high": decimal_or_none(item[2]),
        "low": decimal_or_none(item[3]),
        "close": decimal_or_none(item[4]),
        "volume": volume,
        "quote_volume": quote_volume,
        "number_of_trades": int(item[8]) if item[8] is not None else None,
        "taker_buy_base_volume": taker_buy_base,
        "taker_buy_quote_volume": taker_buy_quote,
        "taker_sell_base_volume": volume - taker_buy_base if volume is not None and taker_buy_base is not None else None,
        "taker_sell_quote_volume": quote_volume - taker_buy_quote if quote_volume is not None and taker_buy_quote is not None else None,
        "source_interval": source_interval,
        "expected_1m_count": 1,
        "actual_1m_count": 1,
        "missing_1m_count": 0,
        "aggregation_status": "AGG_READY",
        "created_at": now,
        "updated_at": now,
    }


def start_collector_run(db: Session, collector_name: str, target: str) -> CollectorRun:
    run = CollectorRun(
        collector_name=collector_name,
        status="RUNNING",
        started_at=utcnow(),
        finished_at=None,
        target=target,
        request_count=0,
        inserted_count=0,
        updated_count=0,
        error_count=0,
        duration_seconds=None,
        details_json=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_collector_run(db: Session, run: CollectorRun, payload: dict[str, Any], status: str = "SUCCESS") -> None:
    run.status = status
    run.finished_at = utcnow()
    run.duration_seconds = duration_seconds(run.started_at, run.finished_at)
    run.inserted_count = int(payload.get("inserted_count") or 0)
    run.updated_count = int(payload.get("updated_count") or 0)
    run.error_count = int(payload.get("error_count") or 0)
    run.details_json = json_safe(payload)
    db.commit()


def _latest_closed_boundary(now: datetime, minutes: int) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_minutes = int((now - day_start).total_seconds() // 60)
    boundary_minutes = elapsed_minutes - (elapsed_minutes % minutes)
    boundary = day_start + timedelta(minutes=boundary_minutes)
    if boundary >= now:
        boundary -= timedelta(minutes=minutes)
    return boundary


def _datetime_to_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return int(value.timestamp() * 1000)
