import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.market import (
    BinanceFuturesSymbol,
    BinanceSpotSymbol,
    CollectorError,
    CollectorRun,
    Futures24hTicker,
    FuturesBookTicker,
    FuturesKline1m,
    FuturesMarkFunding,
    FuturesOpenInterest,
    MarketlabActiveUniverse,
    MarketlabUniverseSnapshot,
    SignalForwardReturnLog,
    Spot24hTicker,
    SpotBookTicker,
    SpotKline1m,
)
from app.services.binance_client import BinanceClient, BinanceClientError
from app.services.data_health import refresh_data_health
from app.services.rate_limit import RateLimitManager
from app.services.utils import current_minute_start_ms, decimal_or_none, duration_seconds, ms_to_utc, utcnow

logger = logging.getLogger(__name__)

KLINE_INTERVAL_MS = 60_000
KLINE_REQUEST_LIMIT = 500
KLINE_GAP_LOOKBACK_MINUTES = 180
SIGNAL_KLINE_LOOKBACK_HOURS = 168


class MarketCollector:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.rate_limit_manager = RateLimitManager()

    async def run_all_once(self) -> None:
        await self.collect_futures_exchange_info()
        await self.collect_spot_exchange_info()
        await self.collect_futures_24h_tickers()
        await self.collect_spot_24h_tickers()
        await self.collect_active_top_150()
        await self.collect_futures_klines_1m()
        await self.collect_spot_klines_1m()
        await self.collect_futures_open_interest()
        await self.collect_futures_mark_funding()
        await self.collect_futures_book_tickers()
        await self.collect_spot_book_tickers()
        self.run_data_health_snapshot()

    async def collect_futures_exchange_info(self) -> CollectorRun:
        async def work(run: CollectorRun):
            async with self._client("futures_exchange_info", run.id) as client:
                data = await client.futures_exchange_info()
            now = utcnow()
            counts = _counts()
            for item in data.get("symbols", []):
                action = self._upsert(
                    BinanceFuturesSymbol,
                    {"symbol": item.get("symbol")},
                    {
                        "base_asset": item.get("baseAsset"),
                        "quote_asset": item.get("quoteAsset"),
                        "margin_asset": item.get("marginAsset"),
                        "contract_type": item.get("contractType"),
                        "status": item.get("status"),
                        "onboard_date": ms_to_utc(item.get("onboardDate")),
                        "delivery_date": ms_to_utc(item.get("deliveryDate")),
                        "raw_json": item,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                counts[action + "_count"] += 1
            return counts

        return await self._run("futures_exchange_info", work)

    async def collect_spot_exchange_info(self) -> CollectorRun:
        async def work(run: CollectorRun):
            async with self._client("spot_exchange_info", run.id) as client:
                data = await client.spot_exchange_info()
            now = utcnow()
            counts = _counts()
            for item in data.get("symbols", []):
                action = self._upsert(
                    BinanceSpotSymbol,
                    {"symbol": item.get("symbol")},
                    {
                        "base_asset": item.get("baseAsset"),
                        "quote_asset": item.get("quoteAsset"),
                        "status": item.get("status"),
                        "is_spot_trading_allowed": item.get("isSpotTradingAllowed"),
                        "raw_json": item,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                counts[action + "_count"] += 1
            return counts

        return await self._run("spot_exchange_info", work)

    async def collect_futures_24h_tickers(self) -> list[dict[str, Any]]:
        tickers: list[dict[str, Any]] = []

        async def work(run: CollectorRun):
            nonlocal tickers
            async with self._client("futures_24h_ticker", run.id) as client:
                tickers = await client.futures_ticker_24h()
            return self._store_24h_tickers(Futures24hTicker, tickers)

        await self._run("futures_24h_ticker", work)
        return tickers

    async def collect_spot_24h_tickers(self) -> list[dict[str, Any]]:
        tickers: list[dict[str, Any]] = []

        async def work(run: CollectorRun):
            nonlocal tickers
            async with self._client("spot_24h_ticker", run.id) as client:
                tickers = await client.spot_ticker_24h()
            return self._store_24h_tickers(Spot24hTicker, tickers)

        await self._run("spot_24h_ticker", work)
        return tickers

    async def collect_active_top_150(self) -> CollectorRun:
        async def work(run: CollectorRun):
            async with self._client("active_top_150", run.id) as client:
                tickers = await client.futures_ticker_24h()
            ticker_counts = self._store_24h_tickers(Futures24hTicker, tickers)

            tradable = set(
                self.db.scalars(
                    select(BinanceFuturesSymbol.symbol).where(
                        BinanceFuturesSymbol.quote_asset == "USDT",
                        BinanceFuturesSymbol.contract_type == "PERPETUAL",
                        BinanceFuturesSymbol.status == "TRADING",
                    )
                ).all()
            )
            filtered = [
                item for item in tickers
                if item.get("symbol") in tradable and decimal_or_none(item.get("quoteVolume")) is not None
            ]
            filtered.sort(key=lambda item: decimal_or_none(item.get("quoteVolume")) or 0, reverse=True)
            active_limit = min(settings.universe_limit, settings.active_full_limit)
            top = filtered[:active_limit]
            now = utcnow()
            active_symbols = {item["symbol"] for item in top}
            counts = _counts()
            _merge_counts(counts, ticker_counts)

            for rank, item in enumerate(top, start=1):
                symbol = item["symbol"]
                quote_volume = decimal_or_none(item.get("quoteVolume"))
                tier = "FULL_ACTIVE"
                is_full_active = True
                is_light_watch = False
                self.db.add(
                    MarketlabUniverseSnapshot(
                        run_id=run.id,
                        snapshot_time=now,
                        symbol=symbol,
                        rank=rank,
                        quote_volume=quote_volume,
                        raw_json=item,
                        created_at=now,
                        updated_at=now,
                    )
                )
                counts["inserted_count"] += 1
                existing = self.db.scalar(select(MarketlabActiveUniverse).where(MarketlabActiveUniverse.symbol == symbol))
                if existing:
                    existing.rank = rank
                    existing.quote_volume = quote_volume
                    existing.price_change_percent = decimal_or_none(item.get("priceChangePercent"))
                    existing.last_price = decimal_or_none(item.get("lastPrice"))
                    existing.high_price = decimal_or_none(item.get("highPrice"))
                    existing.low_price = decimal_or_none(item.get("lowPrice"))
                    existing.volume = decimal_or_none(item.get("volume"))
                    existing.trade_count_24h = int(item.get("count")) if item.get("count") is not None else None
                    existing.collection_tier = tier
                    existing.is_full_active = is_full_active
                    existing.is_light_watch = is_light_watch
                    existing.is_active = True
                    existing.exited_at = None
                    existing.last_seen_at = now
                    existing.updated_at = now
                    counts["updated_count"] += 1
                else:
                    self.db.add(
                        MarketlabActiveUniverse(
                            symbol=symbol,
                            rank=rank,
                            quote_volume=quote_volume,
                            price_change_percent=decimal_or_none(item.get("priceChangePercent")),
                            last_price=decimal_or_none(item.get("lastPrice")),
                            high_price=decimal_or_none(item.get("highPrice")),
                            low_price=decimal_or_none(item.get("lowPrice")),
                            volume=decimal_or_none(item.get("volume")),
                            trade_count_24h=int(item.get("count")) if item.get("count") is not None else None,
                            collection_tier=tier,
                            is_full_active=is_full_active,
                            is_light_watch=is_light_watch,
                            is_signal_eligible=False,
                            is_active=True,
                            entered_at=now,
                            exited_at=None,
                            last_seen_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    counts["inserted_count"] += 1

            exited = self.db.scalars(
                select(MarketlabActiveUniverse).where(
                    MarketlabActiveUniverse.is_active.is_(True),
                    MarketlabActiveUniverse.symbol.not_in(active_symbols),
                )
            ).all()
            for row in exited:
                row.is_active = False
                row.collection_tier = "NOT_ACTIVE"
                row.is_full_active = False
                row.is_light_watch = False
                row.is_signal_eligible = False
                row.exited_at = now
                row.updated_at = now
                counts["updated_count"] += 1
            counts["details_json"] = {
                "universe_count": len(top),
                "active_universe_count": len(top),
                "full_active_count": len(top),
                "light_watch_count": 0,
                "exited_count": len(exited),
            }
            return counts

        return await self._run("active_top_150", work)

    async def collect_futures_klines_1m(self) -> CollectorRun:
        return await self._collect_gap_safe_klines(
            "futures_klines_1m",
            FuturesKline1m,
            lambda client, symbol, start_ms, end_ms: client.futures_klines_1m(
                symbol,
                limit=KLINE_REQUEST_LIMIT,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            ),
            self._futures_kline_symbols,
        )

    async def collect_spot_klines_1m(self) -> CollectorRun:
        return await self._collect_gap_safe_klines(
            "spot_klines_1m",
            SpotKline1m,
            lambda client, symbol, start_ms, end_ms: client.spot_klines_1m(
                symbol,
                limit=KLINE_REQUEST_LIMIT,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            ),
            self._active_spot_symbols,
        )

    async def collect_futures_open_interest(self) -> CollectorRun:
        return await self._collect_symbol_series(
            "futures_open_interest",
            lambda client, symbol: client.futures_open_interest(symbol),
            self._store_open_interest,
        )

    async def collect_futures_mark_funding(self) -> CollectorRun:
        return await self._collect_symbol_series(
            "futures_mark_funding",
            lambda client, symbol: client.futures_mark_funding(symbol),
            self._store_mark_funding,
        )

    async def collect_futures_book_tickers(self) -> CollectorRun:
        return await self._collect_symbol_series(
            "futures_book_tickers",
            lambda client, symbol: client.futures_book_ticker(symbol),
            lambda symbol, payload: self._store_book_ticker(FuturesBookTicker, symbol, payload),
        )

    async def collect_spot_book_tickers(self) -> CollectorRun:
        return await self._collect_symbol_series(
            "spot_book_tickers",
            lambda client, symbol: client.spot_book_ticker(symbol),
            lambda symbol, payload: self._store_book_ticker(SpotBookTicker, symbol, payload),
            self._active_spot_symbols,
        )

    def run_data_health_snapshot(self) -> list[dict]:
        rows = refresh_data_health(self.db)
        return rows

    async def _collect_symbol_series(
        self,
        collector_name: str,
        fetcher: Callable[[BinanceClient, str], Any],
        storer: Callable[[str, Any], int],
        symbol_loader: Callable[[], list[str]] | None = None,
    ) -> CollectorRun:
        async def work(run: CollectorRun):
            symbols = symbol_loader() if symbol_loader else self._active_symbols()
            counts = _counts()
            errors = 0
            async with self._client(collector_name, run.id) as client:
                for symbol in symbols:
                    try:
                        payload = await fetcher(client, symbol)
                        _merge_counts(counts, storer(symbol, payload))
                    except BinanceClientError as exc:
                        errors += 1
                        self._record_error(run, collector_name, symbol, exc)
            counts["error_count"] = errors
            counts["details_json"] = {"symbols": len(symbols)}
            return counts

        return await self._run(collector_name, work)

    async def _collect_gap_safe_klines(
        self,
        collector_name: str,
        model,
        fetcher: Callable[[BinanceClient, str, int, int], Any],
        symbol_loader: Callable[[], list[str]] | None = None,
    ) -> CollectorRun:
        async def work(run: CollectorRun):
            symbols = symbol_loader() if symbol_loader else self._active_symbols()
            latest_target_ms = current_minute_start_ms() - KLINE_INTERVAL_MS
            counts = _counts()
            errors = 0
            fetched_candle_count = 0
            skipped_symbols = 0
            gap_ranges: list[dict[str, Any]] = []

            async with self._client(collector_name, run.id) as client:
                for symbol in symbols:
                    try:
                        start_ms = self._kline_backfill_start_ms(model, symbol, latest_target_ms)
                        if start_ms is None or start_ms > latest_target_ms:
                            skipped_symbols += 1
                            continue

                        symbol_fetched = 0
                        request_start_ms = start_ms
                        while request_start_ms <= latest_target_ms:
                            request_end_ms = min(
                                latest_target_ms,
                                request_start_ms + ((KLINE_REQUEST_LIMIT - 1) * KLINE_INTERVAL_MS),
                            )
                            payload = await fetcher(client, symbol, request_start_ms, request_end_ms)
                            fetched_candle_count += len(payload)
                            symbol_fetched += len(payload)
                            _merge_counts(counts, self._store_kline(model, symbol, payload))
                            request_start_ms = request_end_ms + KLINE_INTERVAL_MS

                        gap_ranges.append(
                            {
                                "symbol": symbol,
                                "start_time": ms_to_utc(start_ms).isoformat(),
                                "end_time": ms_to_utc(latest_target_ms).isoformat(),
                                "fetched_candle_count": symbol_fetched,
                            }
                        )
                    except BinanceClientError as exc:
                        errors += 1
                        self._record_error(run, collector_name, symbol, exc)

            counts["error_count"] = errors
            counts["details_json"] = {
                "target_symbols": len(symbols),
                "fetched_candle_count": fetched_candle_count,
                "inserted_count": counts["inserted_count"],
                "updated_or_skipped_count": counts["updated_count"] + skipped_symbols,
                "skipped_symbol_count": skipped_symbols,
                "latest_closed_1m": ms_to_utc(latest_target_ms).isoformat(),
                "gap_range_count": len(gap_ranges),
                "gap_ranges_sample": gap_ranges[:10],
            }
            return counts

        return await self._run(collector_name, work)

    def _store_24h_tickers(self, model, tickers: list[dict[str, Any]]) -> dict[str, Any]:
        now = utcnow()
        counts = _counts()
        for item in tickers:
            symbol = item.get("symbol")
            close_time = ms_to_utc(item.get("closeTime")) or now
            action = self._upsert(
                model,
                {"symbol": symbol, "event_time": close_time},
                {
                    "price_change": decimal_or_none(item.get("priceChange")),
                    "price_change_percent": decimal_or_none(item.get("priceChangePercent")),
                    "weighted_avg_price": decimal_or_none(item.get("weightedAvgPrice")),
                    "last_price": decimal_or_none(item.get("lastPrice")),
                    "volume": decimal_or_none(item.get("volume")),
                    "quote_volume": decimal_or_none(item.get("quoteVolume")),
                    "open_time": ms_to_utc(item.get("openTime")),
                    "close_time": close_time,
                    "raw_json": item,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            counts[action + "_count"] += 1
        return counts

    def _store_kline(self, model, symbol: str, rows: list[list[Any]]) -> dict[str, Any]:
        now = utcnow()
        current_open = current_minute_start_ms()
        counts = _counts()
        for item in rows:
            open_ms = int(item[0])
            if open_ms >= current_open:
                continue
            action = self._upsert(
                model,
                {"symbol": symbol, "open_time": ms_to_utc(item[0])},
                {
                    "close_time": ms_to_utc(item[6]),
                    "open_price": decimal_or_none(item[1]),
                    "high_price": decimal_or_none(item[2]),
                    "low_price": decimal_or_none(item[3]),
                    "close_price": decimal_or_none(item[4]),
                    "volume": decimal_or_none(item[5]),
                    "quote_volume": decimal_or_none(item[7]),
                    "trade_count": int(item[8]) if item[8] is not None else None,
                    "taker_buy_base_volume": decimal_or_none(item[9]),
                    "taker_buy_quote_volume": decimal_or_none(item[10]),
                    "raw_json": item,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            counts[action + "_count"] += 1
        return counts

    def _kline_backfill_start_ms(self, model, symbol: str, latest_target_ms: int) -> int | None:
        latest_open = self.db.scalar(select(func.max(model.open_time)).where(model.symbol == symbol))
        lookback_start = ms_to_utc(latest_target_ms) - timedelta(minutes=KLINE_GAP_LOOKBACK_MINUTES - 1)
        if latest_open is None:
            return self._datetime_to_ms(lookback_start)

        latest_open_ms = self._datetime_to_ms(latest_open)
        if latest_open_ms < latest_target_ms:
            sequential_start_ms = latest_open_ms + KLINE_INTERVAL_MS
        else:
            sequential_start_ms = latest_target_ms + KLINE_INTERVAL_MS

        existing_times = set(
            self._datetime_to_ms(value)
            for value in self.db.scalars(
                select(model.open_time).where(
                    model.symbol == symbol,
                    model.open_time >= lookback_start,
                    model.open_time <= ms_to_utc(latest_target_ms),
                )
            ).all()
        )
        missing_start_ms = None
        cursor = self._datetime_to_ms(lookback_start)
        while cursor <= latest_target_ms:
            if cursor not in existing_times:
                missing_start_ms = cursor
                break
            cursor += KLINE_INTERVAL_MS

        if missing_start_ms is None and sequential_start_ms > latest_target_ms:
            return None
        if missing_start_ms is None:
            return sequential_start_ms
        return min(missing_start_ms, sequential_start_ms)

    @staticmethod
    def _datetime_to_ms(value: datetime) -> int:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        else:
            value = value.astimezone(UTC)
        return int(value.timestamp() * 1000)

    def _store_open_interest(self, symbol: str, item: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        event_time = ms_to_utc(item.get("time")) or now
        action = self._upsert(
            FuturesOpenInterest,
            {"symbol": symbol, "event_time": event_time},
            {
                "open_interest": decimal_or_none(item.get("openInterest")),
                "raw_json": item,
                "created_at": now,
                "updated_at": now,
            },
        )
        counts = _counts()
        counts[action + "_count"] += 1
        return counts

    def _store_mark_funding(self, symbol: str, item: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        event_time = ms_to_utc(item.get("time")) or now
        action = self._upsert(
            FuturesMarkFunding,
            {"symbol": symbol, "event_time": event_time},
            {
                "mark_price": decimal_or_none(item.get("markPrice")),
                "index_price": decimal_or_none(item.get("indexPrice")),
                "estimated_settle_price": decimal_or_none(item.get("estimatedSettlePrice")),
                "last_funding_rate": decimal_or_none(item.get("lastFundingRate")),
                "next_funding_time": ms_to_utc(item.get("nextFundingTime")),
                "raw_json": item,
                "created_at": now,
                "updated_at": now,
            },
        )
        counts = _counts()
        counts[action + "_count"] += 1
        return counts

    def _store_book_ticker(self, model, symbol: str, item: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        event_time = ms_to_utc(item.get("time") or item.get("transactionTime")) or now
        action = self._upsert(
            model,
            {"symbol": symbol, "event_time": event_time},
            {
                "bid_price": decimal_or_none(item.get("bidPrice")),
                "bid_qty": decimal_or_none(item.get("bidQty")),
                "ask_price": decimal_or_none(item.get("askPrice")),
                "ask_qty": decimal_or_none(item.get("askQty")),
                "raw_json": item,
                "created_at": now,
                "updated_at": now,
            },
        )
        counts = _counts()
        counts[action + "_count"] += 1
        return counts

    def _upsert(self, model, keys: dict[str, Any], values: dict[str, Any]) -> str:
        row = self.db.scalar(select(model).filter_by(**keys))
        if row:
            for key, value in values.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        row = model(**keys, **values)
        self.db.add(row)
        return "inserted"

    def _active_symbols(self) -> list[str]:
        return self.db.scalars(
            select(MarketlabActiveUniverse.symbol)
            .where(
                MarketlabActiveUniverse.is_active.is_(True),
                MarketlabActiveUniverse.collection_tier == "FULL_ACTIVE",
                MarketlabActiveUniverse.is_full_active.is_(True),
            )
            .order_by(MarketlabActiveUniverse.rank.asc())
        ).all()

    def _futures_kline_symbols(self) -> list[str]:
        active = self._active_symbols()
        signal_symbols = self._recent_signal_symbols()
        seen: set[str] = set()
        symbols: list[str] = []
        for symbol in [*active, *signal_symbols]:
            if symbol not in seen:
                symbols.append(symbol)
                seen.add(symbol)
        return symbols

    def _recent_signal_symbols(self) -> list[str]:
        cutoff = utcnow() - timedelta(hours=SIGNAL_KLINE_LOOKBACK_HOURS)
        rows = self.db.scalars(
            select(SignalForwardReturnLog.symbol)
            .where(
                SignalForwardReturnLog.candidate_status == "SIGNAL_CANDIDATE",
                SignalForwardReturnLog.signal_timestamp >= cutoff,
                SignalForwardReturnLog.price_at_signal.is_not(None),
                SignalForwardReturnLog.sl_ref.is_not(None),
                SignalForwardReturnLog.tp_ref.is_not(None),
            )
            .distinct()
        ).all()
        symbols = sorted({symbol for symbol in rows if symbol})
        tradable = set(
            self.db.scalars(
                select(BinanceFuturesSymbol.symbol).where(
                    BinanceFuturesSymbol.status == "TRADING",
                    BinanceFuturesSymbol.contract_type == "PERPETUAL",
                )
            ).all()
        )
        if tradable:
            symbols = [symbol for symbol in symbols if symbol in tradable]
        return symbols

    def _active_spot_symbols(self) -> list[str]:
        active = self._active_symbols()
        spot = self.db.scalars(
            select(BinanceSpotSymbol.symbol).where(
                BinanceSpotSymbol.status == "TRADING",
                BinanceSpotSymbol.is_spot_trading_allowed.is_(True),
            )
        ).all()
        spot_set = set(spot)
        return [symbol for symbol in active if symbol in spot_set]

    def _client(self, collector_name: str, run_id: int | None) -> BinanceClient:
        return BinanceClient(self.db, collector_name, run_id, self.rate_limit_manager)

    async def _run(self, collector_name: str, work: Callable[[CollectorRun], Any], target: str | None = None) -> CollectorRun:
        run = CollectorRun(
            collector_name=collector_name,
            status="RUNNING",
            started_at=utcnow(),
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
            run.updated_count = result.get("updated_count", 0)
            run.inserted_count = result.get("inserted_count", 0)
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
            logger.exception("collector failed: %s", collector_name)
        finally:
            run.finished_at = utcnow()
            run.duration_seconds = duration_seconds(run.started_at, run.finished_at)
            run.request_count = self._request_count(run.id)
            self.db.commit()
        return run

    def _request_count(self, run_id: int) -> int:
        from app.models.market import RateLimitUsage

        return len(self.db.scalars(select(RateLimitUsage.id).where(RateLimitUsage.collector_run_id == run_id)).all())

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


def _counts() -> dict[str, Any]:
    return {"inserted_count": 0, "updated_count": 0, "error_count": 0}


def _merge_counts(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["inserted_count"] += source.get("inserted_count", 0)
    target["updated_count"] += source.get("updated_count", 0)
    target["error_count"] += source.get("error_count", 0)
