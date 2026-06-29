import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import (
    CollectorError,
    CollectorRun,
    FuturesFundingHistory,
    FuturesGlobalLongShortAccountRatio,
    FuturesOpenInterestHistory,
    FuturesTakerBuySellVolume,
    FuturesTopTraderAccountRatio,
    FuturesTopTraderPositionRatio,
    MarketlabActiveUniverse,
    RateLimitUsage,
)
from app.services.binance_client import BinanceClient, BinanceClientError
from app.services.rate_limit import RateLimitManager
from app.services.utils import decimal_or_none, duration_seconds, ms_to_utc, utcnow

logger = logging.getLogger(__name__)

RICH_PERIODS = ("5m", "15m", "1h", "4h", "1d")
RICH_PERIOD_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
RICH_REQUEST_LIMIT = 200
RICH_GAP_LOOKBACK_PERIODS = 144
FUNDING_REQUEST_LIMIT = 1000
FUNDING_GAP_LOOKBACK_DAYS = 7
RICH_COLLECTOR_NAMES = (
    "rich_futures_taker_buy_sell_volume",
    "rich_futures_global_long_short_account_ratio",
    "rich_futures_top_trader_position_ratio",
    "rich_futures_top_trader_account_ratio",
    "rich_futures_open_interest_history",
    "rich_futures_funding_history",
)


class RichFuturesCollector:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.rate_limit_manager = RateLimitManager()

    async def run_periods(self, periods: list[str], include_funding: bool = False, symbols_limit: int | None = None) -> list[CollectorRun]:
        cleaned_periods = [period for period in periods if period in RICH_PERIODS]
        runs: list[CollectorRun] = []
        for period in cleaned_periods:
            runs.append(await self.collect_taker_buy_sell_volume(period, symbols_limit))
            runs.append(await self.collect_global_long_short_account_ratio(period, symbols_limit))
            runs.append(await self.collect_top_trader_position_ratio(period, symbols_limit))
            runs.append(await self.collect_top_trader_account_ratio(period, symbols_limit))
            runs.append(await self.collect_open_interest_history(period, symbols_limit))
        if include_funding:
            runs.append(await self.collect_funding_history(symbols_limit))
        return runs

    async def collect_taker_buy_sell_volume(self, period: str, symbols_limit: int | None = None) -> CollectorRun:
        return await self._collect_symbol_period_series(
            "rich_futures_taker_buy_sell_volume",
            period,
            FuturesTakerBuySellVolume,
            lambda client, symbol, start_ms, end_ms: client.futures_taker_buy_sell_volume(
                symbol,
                period,
                limit=RICH_REQUEST_LIMIT,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            ),
            lambda symbol, item: self._store_taker_buy_sell_volume(symbol, period, item),
            symbols_limit,
        )

    async def collect_global_long_short_account_ratio(self, period: str, symbols_limit: int | None = None) -> CollectorRun:
        return await self._collect_symbol_period_series(
            "rich_futures_global_long_short_account_ratio",
            period,
            FuturesGlobalLongShortAccountRatio,
            lambda client, symbol, start_ms, end_ms: client.futures_global_long_short_account_ratio(
                symbol,
                period,
                limit=RICH_REQUEST_LIMIT,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            ),
            lambda symbol, item: self._store_global_long_short_account_ratio(symbol, period, item),
            symbols_limit,
        )

    async def collect_top_trader_position_ratio(self, period: str, symbols_limit: int | None = None) -> CollectorRun:
        return await self._collect_symbol_period_series(
            "rich_futures_top_trader_position_ratio",
            period,
            FuturesTopTraderPositionRatio,
            lambda client, symbol, start_ms, end_ms: client.futures_top_trader_position_ratio(
                symbol,
                period,
                limit=RICH_REQUEST_LIMIT,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            ),
            lambda symbol, item: self._store_top_trader_position_ratio(symbol, period, item),
            symbols_limit,
        )

    async def collect_top_trader_account_ratio(self, period: str, symbols_limit: int | None = None) -> CollectorRun:
        return await self._collect_symbol_period_series(
            "rich_futures_top_trader_account_ratio",
            period,
            FuturesTopTraderAccountRatio,
            lambda client, symbol, start_ms, end_ms: client.futures_top_trader_account_ratio(
                symbol,
                period,
                limit=RICH_REQUEST_LIMIT,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            ),
            lambda symbol, item: self._store_top_trader_account_ratio(symbol, period, item),
            symbols_limit,
        )

    async def collect_open_interest_history(self, period: str, symbols_limit: int | None = None) -> CollectorRun:
        return await self._collect_symbol_period_series(
            "rich_futures_open_interest_history",
            period,
            FuturesOpenInterestHistory,
            lambda client, symbol, start_ms, end_ms: client.futures_open_interest_history(
                symbol,
                period,
                limit=RICH_REQUEST_LIMIT,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            ),
            lambda symbol, item: self._store_open_interest_history(symbol, period, item),
            symbols_limit,
        )

    async def collect_funding_history(self, symbols_limit: int | None = None) -> CollectorRun:
        async def work(run: CollectorRun) -> dict[str, Any]:
            symbols = self._active_symbols(symbols_limit)
            counts = _counts()
            fetched_row_count = 0
            skipped_symbols = 0
            gap_ranges: list[dict[str, Any]] = []
            latest_target_ms = self._datetime_to_ms(utcnow())
            async with self._client("rich_futures_funding_history", run.id) as client:
                for symbol in symbols:
                    try:
                        start_ms = self._funding_backfill_start_ms(symbol, latest_target_ms)
                        if start_ms is None or start_ms > latest_target_ms:
                            skipped_symbols += 1
                            continue
                        rows = await client.futures_funding_history(
                            symbol,
                            limit=FUNDING_REQUEST_LIMIT,
                            start_time_ms=start_ms,
                            end_time_ms=latest_target_ms,
                        )
                        fetched_row_count += len(rows)
                        if rows:
                            for item in rows:
                                _merge_counts(counts, self._store_funding_history(symbol, item))
                        gap_ranges.append(
                            {
                                "symbol": symbol,
                                "start_time": ms_to_utc(start_ms).isoformat(),
                                "end_time": ms_to_utc(latest_target_ms).isoformat(),
                                "fetched_row_count": len(rows),
                            }
                        )
                    except BinanceClientError as exc:
                        counts["error_count"] += 1
                        self._record_error(run, "rich_futures_funding_history", symbol, exc)
            counts["details_json"] = {
                "target_symbols": len(symbols),
                "fetched_row_count": fetched_row_count,
                "inserted_count": counts["inserted_count"],
                "updated_or_skipped_count": counts["updated_count"] + skipped_symbols,
                "skipped_symbol_count": skipped_symbols,
                "latest_target_time": ms_to_utc(latest_target_ms).isoformat(),
                "gap_range_count": len(gap_ranges),
                "gap_ranges_sample": gap_ranges[:10],
            }
            return counts

        return await self._run("rich_futures_funding_history", work, "funding")

    async def _collect_symbol_period_series(
        self,
        collector_name: str,
        period: str,
        model,
        fetcher: Callable[[BinanceClient, str, int, int], Any],
        storer: Callable[[str, dict[str, Any]], dict[str, int]],
        symbols_limit: int | None,
    ) -> CollectorRun:
        async def work(run: CollectorRun) -> dict[str, Any]:
            symbols = self._active_symbols(symbols_limit)
            counts = _counts()
            fetched_row_count = 0
            skipped_symbols = 0
            gap_ranges: list[dict[str, Any]] = []
            latest_target_ms = self._latest_closed_period_ms(period)
            period_ms = RICH_PERIOD_MINUTES[period] * 60_000
            async with self._client(collector_name, run.id) as client:
                for symbol in symbols:
                    try:
                        start_ms = self._rich_backfill_start_ms(model, symbol, period, latest_target_ms)
                        if start_ms is None or start_ms > latest_target_ms:
                            skipped_symbols += 1
                            continue
                        symbol_fetched = 0
                        request_start_ms = start_ms
                        while request_start_ms <= latest_target_ms:
                            request_end_ms = min(
                                latest_target_ms,
                                request_start_ms + ((RICH_REQUEST_LIMIT - 1) * period_ms),
                            )
                            rows = await fetcher(client, symbol, request_start_ms, request_end_ms)
                            fetched_row_count += len(rows)
                            symbol_fetched += len(rows)
                            for item in rows:
                                _merge_counts(counts, storer(symbol, item))
                            request_start_ms = request_end_ms + period_ms
                        gap_ranges.append(
                            {
                                "symbol": symbol,
                                "start_time": ms_to_utc(start_ms).isoformat(),
                                "end_time": ms_to_utc(latest_target_ms).isoformat(),
                                "fetched_row_count": symbol_fetched,
                            }
                        )
                    except BinanceClientError as exc:
                        counts["error_count"] += 1
                        self._record_error(run, collector_name, symbol, exc)
            counts["details_json"] = {
                "period": period,
                "target_symbols": len(symbols),
                "fetched_row_count": fetched_row_count,
                "inserted_count": counts["inserted_count"],
                "updated_or_skipped_count": counts["updated_count"] + skipped_symbols,
                "skipped_symbol_count": skipped_symbols,
                "latest_closed_period": ms_to_utc(latest_target_ms).isoformat(),
                "gap_range_count": len(gap_ranges),
                "gap_ranges_sample": gap_ranges[:10],
            }
            return counts

        return await self._run(collector_name, work, period)

    def _store_taker_buy_sell_volume(self, symbol: str, period: str, item: dict[str, Any]) -> dict[str, int]:
        return self._store_row(
            FuturesTakerBuySellVolume,
            {"symbol": symbol, "period": period, "timestamp": ms_to_utc(item.get("timestamp"))},
            {
                "buy_sell_ratio": decimal_or_none(item.get("buySellRatio")),
                "buy_volume": decimal_or_none(item.get("buyVol")),
                "sell_volume": decimal_or_none(item.get("sellVol")),
                "collected_at": utcnow(),
                "raw_json": item,
            },
        )

    def _store_global_long_short_account_ratio(self, symbol: str, period: str, item: dict[str, Any]) -> dict[str, int]:
        return self._store_row(
            FuturesGlobalLongShortAccountRatio,
            {"symbol": symbol, "period": period, "timestamp": ms_to_utc(item.get("timestamp"))},
            {
                "long_short_ratio": decimal_or_none(item.get("longShortRatio")),
                "long_account": decimal_or_none(item.get("longAccount")),
                "short_account": decimal_or_none(item.get("shortAccount")),
                "collected_at": utcnow(),
                "raw_json": item,
            },
        )

    def _store_top_trader_position_ratio(self, symbol: str, period: str, item: dict[str, Any]) -> dict[str, int]:
        return self._store_row(
            FuturesTopTraderPositionRatio,
            {"symbol": symbol, "period": period, "timestamp": ms_to_utc(item.get("timestamp"))},
            {
                "long_short_ratio": decimal_or_none(item.get("longShortRatio")),
                "long_position": decimal_or_none(item.get("longPosition") or item.get("longAccount")),
                "short_position": decimal_or_none(item.get("shortPosition") or item.get("shortAccount")),
                "collected_at": utcnow(),
                "raw_json": item,
            },
        )

    def _store_top_trader_account_ratio(self, symbol: str, period: str, item: dict[str, Any]) -> dict[str, int]:
        return self._store_row(
            FuturesTopTraderAccountRatio,
            {"symbol": symbol, "period": period, "timestamp": ms_to_utc(item.get("timestamp"))},
            {
                "long_short_ratio": decimal_or_none(item.get("longShortRatio")),
                "long_account": decimal_or_none(item.get("longAccount")),
                "short_account": decimal_or_none(item.get("shortAccount")),
                "collected_at": utcnow(),
                "raw_json": item,
            },
        )

    def _store_open_interest_history(self, symbol: str, period: str, item: dict[str, Any]) -> dict[str, int]:
        return self._store_row(
            FuturesOpenInterestHistory,
            {"symbol": symbol, "period": period, "timestamp": ms_to_utc(item.get("timestamp"))},
            {
                "sum_open_interest": decimal_or_none(item.get("sumOpenInterest")),
                "sum_open_interest_value": decimal_or_none(item.get("sumOpenInterestValue")),
                "collected_at": utcnow(),
                "raw_json": item,
            },
        )

    def _store_funding_history(self, symbol: str, item: dict[str, Any]) -> dict[str, int]:
        return self._store_row(
            FuturesFundingHistory,
            {"symbol": symbol, "funding_time": ms_to_utc(item.get("fundingTime"))},
            {
                "funding_rate": decimal_or_none(item.get("fundingRate")),
                "mark_price": decimal_or_none(item.get("markPrice")),
                "collected_at": utcnow(),
                "raw_json": item,
            },
        )

    def _store_row(self, model, keys: dict[str, Any], values: dict[str, Any]) -> dict[str, int]:
        counts = _counts()
        if any(value is None for value in keys.values()):
            counts["error_count"] += 1
            return counts
        row = self.db.scalar(select(model).filter_by(**keys))
        if row:
            for key, value in values.items():
                setattr(row, key, value)
            counts["updated_count"] += 1
        else:
            self.db.add(model(**keys, **values))
            counts["inserted_count"] += 1
        return counts

    def _rich_backfill_start_ms(self, model, symbol: str, period: str, latest_target_ms: int) -> int | None:
        period_ms = RICH_PERIOD_MINUTES[period] * 60_000
        lookback_start_ms = latest_target_ms - ((RICH_GAP_LOOKBACK_PERIODS - 1) * period_ms)
        lookback_start = ms_to_utc(lookback_start_ms)
        latest_open = self.db.scalar(
            select(func.max(model.timestamp)).where(
                model.symbol == symbol,
                model.period == period,
            )
        )
        if latest_open is None:
            return lookback_start_ms

        latest_open_ms = self._datetime_to_ms(latest_open)
        sequential_start_ms = latest_open_ms + period_ms if latest_open_ms < latest_target_ms else latest_target_ms + period_ms
        existing_times = set(
            self._datetime_to_ms(value)
            for value in self.db.scalars(
                select(model.timestamp).where(
                    model.symbol == symbol,
                    model.period == period,
                    model.timestamp >= lookback_start,
                    model.timestamp <= ms_to_utc(latest_target_ms),
                )
            ).all()
        )
        missing_start_ms = None
        cursor = lookback_start_ms
        while cursor <= latest_target_ms:
            if cursor not in existing_times:
                missing_start_ms = cursor
                break
            cursor += period_ms

        if missing_start_ms is None and sequential_start_ms > latest_target_ms:
            return None
        if missing_start_ms is None:
            return sequential_start_ms
        return min(missing_start_ms, sequential_start_ms)

    def _funding_backfill_start_ms(self, symbol: str, latest_target_ms: int) -> int | None:
        lookback_start_ms = latest_target_ms - (FUNDING_GAP_LOOKBACK_DAYS * 24 * 60 * 60 * 1000)
        latest_funding_time = self.db.scalar(
            select(func.max(FuturesFundingHistory.funding_time)).where(FuturesFundingHistory.symbol == symbol)
        )
        if latest_funding_time is None:
            return lookback_start_ms
        latest_funding_ms = self._datetime_to_ms(latest_funding_time)
        next_start_ms = latest_funding_ms + 1
        if next_start_ms > latest_target_ms:
            return None
        return max(lookback_start_ms, next_start_ms)

    def _latest_closed_period_ms(self, period: str) -> int:
        minutes = RICH_PERIOD_MINUTES[period]
        now = utcnow().astimezone(UTC).replace(second=0, microsecond=0)
        if minutes == 1440:
            current_start = now.replace(hour=0, minute=0)
        else:
            total_minutes = now.hour * 60 + now.minute
            floored = (total_minutes // minutes) * minutes
            current_start = now.replace(hour=floored // 60, minute=floored % 60)
        latest_closed = current_start - timedelta(minutes=minutes)
        return self._datetime_to_ms(latest_closed)

    @staticmethod
    def _datetime_to_ms(value: datetime) -> int:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        else:
            value = value.astimezone(UTC)
        return int(value.timestamp() * 1000)

    async def _run(self, collector_name: str, work: Callable[[CollectorRun], Any], target: str | None = None) -> CollectorRun:
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
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        try:
            result = await work(run)
            run.status = "SUCCESS" if not result.get("error_count") else "PARTIAL"
            run.inserted_count = result.get("inserted_count", 0)
            run.updated_count = result.get("updated_count", 0)
            run.error_count = result.get("error_count", 0)
            run.details_json = result.get("details_json")
        except Exception as exc:
            run.status = "ERROR"
            run.error_count += 1
            self.db.add(
                CollectorError(
                    collector_run_id=run.id,
                    collector_name=collector_name,
                    symbol=None,
                    endpoint=None,
                    status_code=getattr(exc, "status_code", None),
                    error_type=type(exc).__name__,
                    message=str(exc),
                    raw_json=getattr(exc, "payload", None) if isinstance(getattr(exc, "payload", None), dict) else None,
                    created_at=utcnow(),
                )
            )
            logger.exception("rich futures collector failed: %s", collector_name)
        finally:
            run.finished_at = utcnow()
            run.duration_seconds = duration_seconds(run.started_at, run.finished_at)
            run.request_count = self._request_count(run.id)
            self.db.commit()
        return run

    def _active_symbols(self, symbols_limit: int | None = None) -> list[str]:
        query = (
            select(MarketlabActiveUniverse.symbol)
            .where(
                MarketlabActiveUniverse.is_active.is_(True),
                MarketlabActiveUniverse.collection_tier == "FULL_ACTIVE",
                MarketlabActiveUniverse.is_full_active.is_(True),
            )
            .order_by(MarketlabActiveUniverse.rank.asc())
        )
        if symbols_limit:
            query = query.limit(symbols_limit)
        return self.db.scalars(query).all()

    def _client(self, collector_name: str, run_id: int | None) -> BinanceClient:
        return BinanceClient(self.db, collector_name, run_id, self.rate_limit_manager)

    def _request_count(self, run_id: int) -> int:
        return self.db.scalar(select(func.count()).select_from(RateLimitUsage).where(RateLimitUsage.collector_run_id == run_id)) or 0

    def _record_error(self, run: CollectorRun, collector_name: str, symbol: str, exc: Exception) -> None:
        self.db.add(
            CollectorError(
                collector_run_id=run.id,
                collector_name=collector_name,
                symbol=symbol,
                endpoint=None,
                status_code=getattr(exc, "status_code", None),
                error_type=type(exc).__name__,
                message=str(exc),
                raw_json=getattr(exc, "payload", None) if isinstance(getattr(exc, "payload", None), dict) else None,
                created_at=utcnow(),
            )
        )
        self.db.commit()


def _counts() -> dict[str, int]:
    return {"inserted_count": 0, "updated_count": 0, "error_count": 0}


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    target["inserted_count"] += source.get("inserted_count", 0)
    target["updated_count"] += source.get("updated_count", 0)
    target["error_count"] += source.get("error_count", 0)
