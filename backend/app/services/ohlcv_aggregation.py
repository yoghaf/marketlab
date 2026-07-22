from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import (
    BinanceSpotSymbol,
    FuturesKline1h,
    FuturesKline1m,
    FuturesKline4h,
    FuturesKline15m,
    FuturesKline24h,
    MarketlabActiveUniverse,
    SignalForwardReturnLog,
    SpotKline1h,
    SpotKline1m,
    SpotKline4h,
    SpotKline15m,
    SpotKline24h,
)
from app.services.utils import utcnow


TIMEFRAMES = {
    "15m": {"minutes": 15, "model": {"futures": FuturesKline15m, "spot": SpotKline15m}},
    "1h": {"minutes": 60, "model": {"futures": FuturesKline1h, "spot": SpotKline1h}},
    "4h": {"minutes": 240, "model": {"futures": FuturesKline4h, "spot": SpotKline4h}},
    "24h": {"minutes": 1440, "model": {"futures": FuturesKline24h, "spot": SpotKline24h}},
}
MARKETS = {"futures": FuturesKline1m, "spot": SpotKline1m}
AGG_STATUSES = ("AGG_READY", "AGG_INCOMPLETE", "AGG_WARMUP", "AGG_STALE", "AGG_MISSING_SPOT")
SIGNAL_KLINE_LOOKBACK_HOURS = 168


@dataclass
class AggregationResult:
    market: str
    timeframe: str
    symbols: int
    inserted_count: int
    updated_count: int
    status_counts: dict[str, int]


class OhlcvAggregationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def run(
        self,
        timeframes: list[str],
        markets: list[str],
        symbols: list[str] | None = None,
        limit_windows: int | None = None,
        dry_run: bool = False,
    ) -> list[AggregationResult]:
        cleaned_timeframes = [timeframe for timeframe in timeframes if timeframe in TIMEFRAMES]
        cleaned_markets = [market for market in markets if market in MARKETS]
        results: list[AggregationResult] = []
        for market in cleaned_markets:
            market_symbols = self._symbols_for_market(market, symbols)
            valid_spot = self._valid_spot_symbols(market_symbols) if market == "spot" else set(market_symbols)
            for timeframe in cleaned_timeframes:
                results.append(
                    self._aggregate_market_timeframe(
                        market,
                        timeframe,
                        market_symbols,
                        valid_spot,
                        limit_windows,
                        dry_run,
                    )
                )
        if not dry_run:
            self.db.commit()
        return results

    def status_summary(self) -> dict[str, Any]:
        latest = {}
        counts = {status: 0 for status in AGG_STATUSES}
        tables = {}
        for timeframe in TIMEFRAMES:
            for market in MARKETS:
                model = TIMEFRAMES[timeframe]["model"][market]
                key = f"{timeframe}_{market}"
                rows = self.db.execute(
                    select(
                        model.aggregation_status,
                        func.count(),
                        func.max(model.close_time),
                    ).group_by(model.aggregation_status)
                ).all()
                table_counts = {status: 0 for status in AGG_STATUSES}
                latest_times = []
                for status, count, latest_time in rows:
                    table_counts[status] = count
                    if latest_time is not None:
                        latest_times.append(latest_time)
                latest[f"latest_{timeframe}_{market}"] = max(latest_times, default=None)
                tables[key] = table_counts
                for status, count in table_counts.items():
                    counts[status.lower().replace("agg_", "") + "_count"] = counts.get(
                        status.lower().replace("agg_", "") + "_count", 0
                    ) + count
        return {"latest": latest, "counts": _public_counts(counts), "tables": tables}

    def _aggregate_market_timeframe(
        self,
        market: str,
        timeframe: str,
        active_symbols: list[str],
        valid_spot: set[str],
        limit_windows: int | None,
        dry_run: bool,
    ) -> AggregationResult:
        source_model = MARKETS[market]
        target_model = TIMEFRAMES[timeframe]["model"][market]
        expected = int(TIMEFRAMES[timeframe]["minutes"])
        now = utcnow()
        inserted = 0
        updated = 0
        status_counts = {status: 0 for status in AGG_STATUSES}

        for symbol in active_symbols:
            if market == "spot" and symbol not in valid_spot:
                row = self._empty_row(symbol, timeframe, expected, "AGG_MISSING_SPOT", now)
                action = self._upsert(target_model, row, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts["AGG_MISSING_SPOT"] += 1
                continue

            statement = select(source_model).where(source_model.symbol == symbol)
            if limit_windows is not None and limit_windows > 0:
                latest_window_close = _latest_closed_boundary(now, expected)
                latest_window_open = latest_window_close - timedelta(minutes=expected)
                earliest_window_open = latest_window_open - timedelta(minutes=expected * (limit_windows - 1))
                statement = statement.where(source_model.open_time >= earliest_window_open)
            rows = self.db.scalars(statement.order_by(source_model.open_time.asc())).all()
            closed_rows = [row for row in rows if _as_utc(row.close_time) < now]
            grouped: dict[datetime, list[Any]] = defaultdict(list)
            for row in closed_rows:
                window_open = _window_open(_as_utc(row.open_time), expected)
                window_close = window_open + timedelta(minutes=expected)
                if window_close <= now:
                    grouped[window_open].append(row)

            if not grouped:
                row = self._empty_row(symbol, timeframe, expected, "AGG_WARMUP", now)
                action = self._upsert(target_model, row, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts["AGG_WARMUP"] += 1
                continue

            window_opens = sorted(grouped)
            if limit_windows is not None and limit_windows > 0:
                window_opens = window_opens[-limit_windows:]

            for window_open in window_opens:
                window_rows = grouped[window_open]
                window_rows.sort(key=lambda item: item.open_time)
                payload = self._aggregate_window(symbol, timeframe, expected, window_open, window_rows, now)
                action = self._upsert(target_model, payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts[payload["aggregation_status"]] += 1

        return AggregationResult(
            market=market,
            timeframe=timeframe,
            symbols=len(active_symbols),
            inserted_count=inserted,
            updated_count=updated,
            status_counts=status_counts,
        )

    def _aggregate_window(
        self,
        symbol: str,
        timeframe: str,
        expected: int,
        window_open: datetime,
        rows: list[Any],
        now: datetime,
    ) -> dict[str, Any]:
        unique_rows = {row.open_time: row for row in rows}
        sorted_rows = [unique_rows[key] for key in sorted(unique_rows)]
        actual = len(sorted_rows)
        missing = max(0, expected - actual)
        all_closed = all(_as_utc(row.close_time) < now for row in sorted_rows)
        status = "AGG_READY" if actual == expected and missing == 0 and all_closed else "AGG_INCOMPLETE"
        volume = _sum_decimal(row.volume for row in sorted_rows)
        quote_volume = _sum_decimal(row.quote_volume for row in sorted_rows)
        taker_buy_base = _sum_decimal(row.taker_buy_base_volume for row in sorted_rows)
        taker_buy_quote = _sum_decimal(row.taker_buy_quote_volume for row in sorted_rows)
        return {
            "symbol": symbol,
            "open_time": window_open,
            "close_time": window_open + timedelta(minutes=expected),
            "open": sorted_rows[0].open_price,
            "high": max(row.high_price for row in sorted_rows),
            "low": min(row.low_price for row in sorted_rows),
            "close": sorted_rows[-1].close_price,
            "volume": volume,
            "quote_volume": quote_volume,
            "number_of_trades": sum(row.trade_count or 0 for row in sorted_rows),
            "taker_buy_base_volume": taker_buy_base,
            "taker_buy_quote_volume": taker_buy_quote,
            "taker_sell_base_volume": volume - taker_buy_base,
            "taker_sell_quote_volume": quote_volume - taker_buy_quote,
            "source_interval": "1m",
            "expected_1m_count": expected,
            "actual_1m_count": actual,
            "missing_1m_count": missing,
            "aggregation_status": status,
            "created_at": now,
            "updated_at": now,
        }

    def _empty_row(self, symbol: str, timeframe: str, expected: int, status: str, now: datetime) -> dict[str, Any]:
        window_close = _latest_closed_boundary(now, expected)
        return {
            "symbol": symbol,
            "open_time": window_close - timedelta(minutes=expected),
            "close_time": window_close,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": None,
            "quote_volume": None,
            "number_of_trades": None,
            "taker_buy_base_volume": None,
            "taker_buy_quote_volume": None,
            "taker_sell_base_volume": None,
            "taker_sell_quote_volume": None,
            "source_interval": "1m",
            "expected_1m_count": expected,
            "actual_1m_count": 0,
            "missing_1m_count": expected,
            "aggregation_status": status,
            "created_at": now,
            "updated_at": now,
        }

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

    def _active_symbols(self, symbols: list[str] | None) -> list[str]:
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
        if not symbols:
            return active
        requested = {symbol.upper() for symbol in symbols}
        return [symbol for symbol in active if symbol in requested]

    def _symbols_for_market(self, market: str, symbols: list[str] | None) -> list[str]:
        active = self._active_symbols(symbols)
        if market != "futures":
            return active
        signal_symbols = self._recent_signal_symbols()
        seen: set[str] = set()
        output: list[str] = []
        for symbol in [*active, *signal_symbols]:
            if symbol not in seen:
                output.append(symbol)
                seen.add(symbol)
        if symbols:
            requested = {symbol.upper() for symbol in symbols}
            return [symbol for symbol in output if symbol in requested]
        return output

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
        return sorted({symbol for symbol in rows if symbol})

    def _valid_spot_symbols(self, active_symbols: list[str]) -> set[str]:
        rows = self.db.scalars(
            select(BinanceSpotSymbol.symbol).where(
                BinanceSpotSymbol.status == "TRADING",
                BinanceSpotSymbol.is_spot_trading_allowed.is_(True),
                BinanceSpotSymbol.symbol.in_(active_symbols),
            )
        ).all()
        return set(rows)

    def _status_counts(self, model) -> dict[str, int]:
        rows = self.db.execute(
            select(model.aggregation_status, func.count()).group_by(model.aggregation_status)
        ).all()
        return {status: count for status, count in rows}


def _public_counts(counts: dict[str, int]) -> dict[str, int]:
    return {
        "ready_count": counts.get("ready_count", 0),
        "incomplete_count": counts.get("incomplete_count", 0),
        "warmup_count": counts.get("warmup_count", 0),
        "stale_count": counts.get("stale_count", 0),
        "missing_spot_count": counts.get("missing_spot_count", 0),
    }


def _window_open(value: datetime, minutes: int) -> datetime:
    value = _as_utc(value)
    if minutes == 1440:
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    total_minutes = value.hour * 60 + value.minute
    bucket = (total_minutes // minutes) * minutes
    return value.replace(hour=bucket // 60, minute=bucket % 60, second=0, microsecond=0)


def _latest_closed_boundary(now: datetime, minutes: int) -> datetime:
    boundary = _window_open(now, minutes)
    if boundary >= now:
        boundary -= timedelta(minutes=minutes)
    return boundary


def _sum_decimal(values) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is not None:
            total += value
    return total


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
