from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import (
    FuturesGlobalLongShortAccountRatio,
    FuturesOpenInterestHistory,
    FuturesTakerBuySellVolume,
    FuturesTopTraderAccountRatio,
    FuturesTopTraderPositionRatio,
    MarketlabActiveUniverse,
    RichFutures5mAlignment,
)
from app.services.utils import utcnow

RICH_TIMEFRAMES = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}
ALIGNMENT_STATUSES = ("ALIGNED", "INCOMPLETE", "WARMUP", "STALE", "NO_DATA")
RICH_PERIOD = "5m"
FIVE_MINUTES = timedelta(minutes=5)
STALE_AFTER = timedelta(minutes=30)


@dataclass
class RichAlignmentResult:
    timeframe: str
    symbols: int
    inserted_count: int
    updated_count: int
    status_counts: dict[str, int]


class Rich5mAlignmentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def run(
        self,
        timeframes: list[str],
        symbols: list[str] | None = None,
        limit_windows: int | None = None,
        dry_run: bool = False,
    ) -> list[RichAlignmentResult]:
        active_symbols = self._active_symbols(symbols)
        return [self._run_timeframe(timeframe, active_symbols, limit_windows, dry_run) for timeframe in timeframes]

    def status_summary(self) -> dict[str, Any]:
        latest = {f"latest_{timeframe}": None for timeframe in RICH_TIMEFRAMES}
        counts = {
            "aligned_count": 0,
            "incomplete_count": 0,
            "warmup_count": 0,
            "stale_count": 0,
            "no_data_count": 0,
        }
        tables = {}
        rows = self.db.execute(
            select(
                RichFutures5mAlignment.timeframe,
                RichFutures5mAlignment.alignment_status,
                func.count(),
                func.max(RichFutures5mAlignment.window_close_time),
            ).group_by(RichFutures5mAlignment.timeframe, RichFutures5mAlignment.alignment_status)
        ).all()
        for timeframe, status, count, latest_time in rows:
            tables.setdefault(timeframe, {})[status] = count
            latest_key = f"latest_{timeframe}"
            if latest_time is not None and (latest[latest_key] is None or latest_time > latest[latest_key]):
                latest[latest_key] = latest_time
            key = {
                "ALIGNED": "aligned_count",
                "INCOMPLETE": "incomplete_count",
                "WARMUP": "warmup_count",
                "STALE": "stale_count",
                "NO_DATA": "no_data_count",
            }[status]
            counts[key] += count
        return {"latest": latest, "counts": counts, "tables": tables}

    def _run_timeframe(
        self,
        timeframe: str,
        active_symbols: list[str],
        limit_windows: int | None,
        dry_run: bool,
    ) -> RichAlignmentResult:
        minutes = RICH_TIMEFRAMES[timeframe]
        expected = minutes // 5
        inserted = 0
        updated = 0
        status_counts = {status: 0 for status in ALIGNMENT_STATUSES}
        now = utcnow()

        for symbol in active_symbols:
            window_range = self._window_range(symbol, minutes)
            if window_range is None:
                payload = self._empty_row(symbol, timeframe, expected, "NO_DATA", now)
                action = self._upsert(payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts[payload["alignment_status"]] += 1
                continue

            first_open, latest_open = window_range
            if limit_windows is not None and limit_windows > 0:
                first_open = max(first_open, latest_open - timedelta(minutes=minutes * (limit_windows - 1)))
            window_open = first_open
            while window_open <= latest_open:
                payload = self._align_window(symbol, timeframe, expected, window_open, now)
                action = self._upsert(payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts[payload["alignment_status"]] += 1
                window_open += timedelta(minutes=minutes)

            latest_any = self._latest_any_timestamp(symbol)
            if latest_any is not None and now - latest_any > STALE_AFTER:
                payload = self._empty_row(symbol, timeframe, expected, "STALE", now)
                action = self._upsert(payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts[payload["alignment_status"]] += 1

        return RichAlignmentResult(
            timeframe=timeframe,
            symbols=len(active_symbols),
            inserted_count=inserted,
            updated_count=updated,
            status_counts=status_counts,
        )

    def _align_window(
        self,
        symbol: str,
        timeframe: str,
        expected: int,
        window_open: datetime,
        now: datetime,
    ) -> dict[str, Any]:
        window_close = window_open + timedelta(minutes=expected * 5)
        expected_times = [window_open + (FIVE_MINUTES * offset) for offset in range(expected)]
        datasets = self._dataset_rows(symbol, window_open, window_close)
        complete_times = [
            ts
            for ts in expected_times
            if all(ts in rows for rows in datasets.values())
        ]
        any_rows = any(rows for rows in datasets.values())
        actual = len(complete_times)
        missing_times = [ts for ts in expected_times if ts not in complete_times]
        if actual == expected:
            status = "ALIGNED"
        elif not any_rows:
            status = "NO_DATA"
        elif self._is_warmup_window(symbol, window_open):
            status = "WARMUP"
        else:
            status = "INCOMPLETE"

        oi_rows = [datasets["oi"][ts] for ts in expected_times if ts in datasets["oi"]]
        global_rows = [datasets["global"][ts] for ts in expected_times if ts in datasets["global"]]
        top_position_rows = [datasets["top_position"][ts] for ts in expected_times if ts in datasets["top_position"]]
        top_account_rows = [datasets["top_account"][ts] for ts in expected_times if ts in datasets["top_account"]]
        taker_rows = [datasets["taker"][ts] for ts in expected_times if ts in datasets["taker"]]
        oi_open = oi_rows[0].sum_open_interest if oi_rows else None
        oi_close = oi_rows[-1].sum_open_interest if oi_rows else None
        oi_value_open = oi_rows[0].sum_open_interest_value if oi_rows else None
        oi_value_close = oi_rows[-1].sum_open_interest_value if oi_rows else None
        oi_change = oi_close - oi_open if oi_open is not None and oi_close is not None else None
        oi_change_pct = (
            (oi_change / oi_open) if oi_change is not None and oi_open not in (None, Decimal("0")) else None
        )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "window_open_time": window_open,
            "window_close_time": window_close,
            "expected_5m_count": expected,
            "actual_5m_count": actual,
            "missing_5m_count": max(0, expected - actual),
            "alignment_status": status,
            "oi_open": oi_open,
            "oi_close": oi_close,
            "oi_change": oi_change,
            "oi_change_pct": oi_change_pct,
            "oi_value_open": oi_value_open,
            "oi_value_close": oi_value_close,
            "global_long_short_ratio_avg": _avg(row.long_short_ratio for row in global_rows),
            "global_long_account_avg": _avg(row.long_account for row in global_rows),
            "global_short_account_avg": _avg(row.short_account for row in global_rows),
            "top_trader_position_ratio_avg": _avg(row.long_short_ratio for row in top_position_rows),
            "top_trader_long_position_avg": _avg(row.long_position for row in top_position_rows),
            "top_trader_short_position_avg": _avg(row.short_position for row in top_position_rows),
            "top_trader_account_ratio_avg": _avg(row.long_short_ratio for row in top_account_rows),
            "top_trader_long_account_avg": _avg(row.long_account for row in top_account_rows),
            "top_trader_short_account_avg": _avg(row.short_account for row in top_account_rows),
            "taker_buy_volume_sum": _sum(row.buy_volume for row in taker_rows),
            "taker_sell_volume_sum": _sum(row.sell_volume for row in taker_rows),
            "taker_buy_sell_ratio_avg": _avg(row.buy_sell_ratio for row in taker_rows),
            "source_timestamps_json": [_iso(ts) for ts in complete_times],
            "missing_timestamps_json": [_iso(ts) for ts in missing_times],
            "created_at": now,
            "updated_at": now,
        }

    def _dataset_rows(self, symbol: str, window_open: datetime, window_close: datetime) -> dict[str, dict[datetime, Any]]:
        return {
            "oi": self._rows_by_timestamp(FuturesOpenInterestHistory, symbol, window_open, window_close),
            "global": self._rows_by_timestamp(FuturesGlobalLongShortAccountRatio, symbol, window_open, window_close),
            "top_position": self._rows_by_timestamp(FuturesTopTraderPositionRatio, symbol, window_open, window_close),
            "top_account": self._rows_by_timestamp(FuturesTopTraderAccountRatio, symbol, window_open, window_close),
            "taker": self._rows_by_timestamp(FuturesTakerBuySellVolume, symbol, window_open, window_close),
        }

    def _rows_by_timestamp(self, model, symbol: str, window_open: datetime, window_close: datetime) -> dict[datetime, Any]:
        rows = self.db.scalars(
            select(model)
            .where(
                model.symbol == symbol,
                model.period == RICH_PERIOD,
                model.timestamp >= window_open,
                model.timestamp < window_close,
            )
            .order_by(model.timestamp.asc())
        ).all()
        return {_as_utc(row.timestamp): row for row in rows}

    def _window_range(self, symbol: str, timeframe_minutes: int) -> tuple[datetime, datetime] | None:
        bounds = []
        for model in (
            FuturesOpenInterestHistory,
            FuturesGlobalLongShortAccountRatio,
            FuturesTopTraderPositionRatio,
            FuturesTopTraderAccountRatio,
            FuturesTakerBuySellVolume,
        ):
            row = self.db.execute(
                select(func.min(model.timestamp), func.max(model.timestamp)).where(
                    model.symbol == symbol,
                    model.period == RICH_PERIOD,
                )
            ).one()
            if row[0] is not None and row[1] is not None:
                bounds.append((_as_utc(row[0]), _as_utc(row[1])))
        if not bounds:
            return None
        earliest = min(bound[0] for bound in bounds)
        latest = max(bound[1] for bound in bounds)
        first_open = _floor_boundary(earliest, timeframe_minutes)
        latest_open = _floor_boundary(latest, timeframe_minutes)
        return first_open, latest_open

    def _latest_any_timestamp(self, symbol: str) -> datetime | None:
        values = []
        for model in (
            FuturesOpenInterestHistory,
            FuturesGlobalLongShortAccountRatio,
            FuturesTopTraderPositionRatio,
            FuturesTopTraderAccountRatio,
            FuturesTakerBuySellVolume,
        ):
            value = self.db.scalar(
                select(func.max(model.timestamp)).where(
                    model.symbol == symbol,
                    model.period == RICH_PERIOD,
                )
            )
            if value is not None:
                values.append(_as_utc(value))
        return max(values) if values else None

    def _is_warmup_window(self, symbol: str, window_open: datetime) -> bool:
        first_values = []
        for model in (
            FuturesOpenInterestHistory,
            FuturesGlobalLongShortAccountRatio,
            FuturesTopTraderPositionRatio,
            FuturesTopTraderAccountRatio,
            FuturesTakerBuySellVolume,
        ):
            value = self.db.scalar(
                select(func.min(model.timestamp)).where(
                    model.symbol == symbol,
                    model.period == RICH_PERIOD,
                )
            )
            if value is not None:
                first_values.append(_as_utc(value))
        return bool(first_values and window_open <= min(first_values))

    def _empty_row(
        self,
        symbol: str,
        timeframe: str,
        expected: int,
        status: str,
        now: datetime,
    ) -> dict[str, Any]:
        window_close = _floor_boundary(now, RICH_TIMEFRAMES[timeframe])
        window_open = window_close - timedelta(minutes=expected * 5)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "window_open_time": window_open,
            "window_close_time": window_close,
            "expected_5m_count": expected,
            "actual_5m_count": 0,
            "missing_5m_count": expected,
            "alignment_status": status,
            "oi_open": None,
            "oi_close": None,
            "oi_change": None,
            "oi_change_pct": None,
            "oi_value_open": None,
            "oi_value_close": None,
            "global_long_short_ratio_avg": None,
            "global_long_account_avg": None,
            "global_short_account_avg": None,
            "top_trader_position_ratio_avg": None,
            "top_trader_long_position_avg": None,
            "top_trader_short_position_avg": None,
            "top_trader_account_ratio_avg": None,
            "top_trader_long_account_avg": None,
            "top_trader_short_account_avg": None,
            "taker_buy_volume_sum": None,
            "taker_sell_volume_sum": None,
            "taker_buy_sell_ratio_avg": None,
            "source_timestamps_json": [],
            "missing_timestamps_json": [_iso(window_open + (FIVE_MINUTES * offset)) for offset in range(expected)],
            "created_at": now,
            "updated_at": now,
        }

    def _upsert(self, payload: dict[str, Any], dry_run: bool) -> str:
        for pending in self.db.new:
            if (
                isinstance(pending, RichFutures5mAlignment)
                and pending.symbol == payload["symbol"]
                and pending.timeframe == payload["timeframe"]
                and pending.window_open_time == payload["window_open_time"]
            ):
                if dry_run:
                    return "updated"
                for key, value in payload.items():
                    if key != "created_at":
                        setattr(pending, key, value)
                return "updated"
        row = self.db.scalar(
            select(RichFutures5mAlignment).where(
                RichFutures5mAlignment.symbol == payload["symbol"],
                RichFutures5mAlignment.timeframe == payload["timeframe"],
                RichFutures5mAlignment.window_open_time == payload["window_open_time"],
            )
        )
        if dry_run:
            return "updated" if row else "inserted"
        if row:
            for key, value in payload.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        self.db.add(RichFutures5mAlignment(**payload))
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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _floor_boundary(value: datetime, timeframe_minutes: int) -> datetime:
    value = _as_utc(value).replace(second=0, microsecond=0)
    if timeframe_minutes == 1440:
        return value.replace(hour=0, minute=0)
    total_minutes = value.hour * 60 + value.minute
    floored = (total_minutes // timeframe_minutes) * timeframe_minutes
    return value.replace(hour=floored // 60, minute=floored % 60)


def _avg(values) -> Decimal | None:
    items = [value for value in values if value is not None]
    if not items:
        return None
    return sum(items, Decimal("0")) / Decimal(len(items))


def _sum(values) -> Decimal | None:
    items = [value for value in values if value is not None]
    if not items:
        return None
    return sum(items, Decimal("0"))


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()
