from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline15m, FuturesKline1h, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import utcnow


ATR_MULTIPLIERS = (Decimal("0.75"), Decimal("1.00"), Decimal("1.25"), Decimal("1.50"))
RR_VALUES = (Decimal("1.0"), Decimal("1.5"), Decimal("2.0"))
TIMEOUT_MINUTES = (60, 120, 240, 480, 1440)
STAGES = ("EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT")
TIMEFRAMES = ("15m", "1h", "4h", "24h")
COMPLETED_RESULTS = {"TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE", "TIMEOUT_CLOSE"}


@dataclass(frozen=True)
class StrategySignal:
    signal_id: str
    symbol: str
    timeframe: str
    signal_timestamp: datetime
    direction: str
    stage: str
    entry: Decimal


@dataclass(frozen=True)
class StrategyCandle:
    open_time: datetime
    close_time: datetime
    high: Decimal
    low: Decimal
    close: Decimal


class StrategyOptimizationLabService:
    """Read-only RR/ATR/timeout optimizer over logged Signal Factory candidates."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        stage: str | None = None,
        timeframe: str | None = None,
        min_sample: int = 20,
        limit: int = 80,
    ) -> dict[str, Any]:
        signals = self._load_signals(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
        )
        symbols = {signal.symbol for signal in signals}
        min_time = min((signal.signal_timestamp for signal in signals), default=None)
        candles_15m = self._load_15m_candles(symbols, min_time)
        candles_1h = self._load_1h_candles(symbols)
        open_times_15m = {symbol: [candle.open_time for candle in rows] for symbol, rows in candles_15m.items()}
        close_times_1h = {symbol: [candle.close_time for candle in rows] for symbol, rows in candles_1h.items()}

        rows: list[dict[str, Any]] = []
        lanes = _group_by_lane(signals)
        for lane_key, lane_signals in lanes.items():
            lane_stage, lane_timeframe = lane_key
            for atr_mult in ATR_MULTIPLIERS:
                for rr in RR_VALUES:
                    for timeout in TIMEOUT_MINUTES:
                        rows.append(
                            _grid_row(
                                lane_stage=lane_stage,
                                lane_timeframe=lane_timeframe,
                                signals=lane_signals,
                                candles_15m=candles_15m,
                                candles_1h=candles_1h,
                                open_times_15m=open_times_15m,
                                close_times_1h=close_times_1h,
                                atr_mult=atr_mult,
                                rr=rr,
                                timeout_minutes=timeout,
                                min_sample=min_sample,
                                position_lock=position_lock,
                            )
                        )

        ready_rows = [row for row in rows if row["sample_count"] >= min_sample]
        sorted_rows = sorted(ready_rows, key=_row_sort_key, reverse=True)
        best_by_lane = _best_by_lane(ready_rows)
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": stage,
                "timeframe": timeframe,
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "study_scope": "read_only_strategy_optimization_rr_atr_timeout",
            "entry_market": "futures",
            "entry_model": "signal_forward_return_logs.price_at_signal",
            "atr_model": "ATR14 futures_klines_1h closed before or at signal",
            "outcome_model": "futures_klines_15m after signal; timeout closes at latest timeout candle close",
            "grid": {
                "atr_multipliers": [str(value) for value in ATR_MULTIPLIERS],
                "rr_values": [str(value) for value in RR_VALUES],
                "timeout_minutes": list(TIMEOUT_MINUTES),
            },
            "summary": {
                "signals_loaded": len(signals),
                "lane_count": len(lanes),
                "grid_rows": len(rows),
                "ready_rows": len(ready_rows),
                "promising_rows": sum(1 for row in ready_rows if row["verdict"] == "PROMISING_TIMEOUT_MODEL"),
                "best_row": sorted_rows[0] if sorted_rows else None,
            },
            "lanes": best_by_lane,
            "rows": sorted_rows[:limit],
            "guardrails": [
                "No Signal Factory rule changed.",
                "No scanner behavior changed.",
                "No live signal, order, leverage, or execution created.",
                "This is a paper/read-only strategy parameter study.",
            ],
        }

    def _load_signals(
        self,
        *,
        epoch: str,
        include_watch_only: bool,
        stage: str | None,
        timeframe: str | None,
    ) -> list[StrategySignal]:
        query = (
            select(SignalForwardReturnLog)
            .where(
                SignalForwardReturnLog.candidate_status == "SIGNAL_CANDIDATE",
                SignalForwardReturnLog.observation_epoch == epoch,
                SignalForwardReturnLog.price_at_signal.is_not(None),
            )
            .order_by(asc(SignalForwardReturnLog.signal_timestamp), asc(SignalForwardReturnLog.symbol))
        )
        if not include_watch_only:
            query = query.where(
                (SignalForwardReturnLog.execution_flag.is_(None))
                | (SignalForwardReturnLog.execution_flag != "WATCH_ONLY")
            )
        if stage:
            query = query.where(SignalForwardReturnLog.stage == stage)
        if timeframe:
            query = query.where(SignalForwardReturnLog.timeframe == timeframe)
        output: list[StrategySignal] = []
        for row in self.db.scalars(query).all():
            if row.direction not in {"LONG", "SHORT"}:
                continue
            output.append(
                StrategySignal(
                    signal_id=row.signal_id,
                    symbol=row.symbol,
                    timeframe=row.timeframe,
                    signal_timestamp=_naive(row.signal_timestamp),
                    direction=row.direction,
                    stage=row.stage,
                    entry=Decimal(row.price_at_signal),
                )
            )
        return output

    def _load_15m_candles(
        self,
        symbols: set[str],
        start_time: datetime | None,
    ) -> dict[str, list[StrategyCandle]]:
        if not symbols:
            return {}
        query = (
            select(FuturesKline15m)
            .where(
                FuturesKline15m.symbol.in_(symbols),
                FuturesKline15m.aggregation_status == "AGG_READY",
            )
            .order_by(asc(FuturesKline15m.symbol), asc(FuturesKline15m.open_time))
        )
        if start_time:
            query = query.where(FuturesKline15m.open_time >= start_time)
        return _candle_map(self.db.scalars(query).all())

    def _load_1h_candles(self, symbols: set[str]) -> dict[str, list[StrategyCandle]]:
        if not symbols:
            return {}
        query = (
            select(FuturesKline1h)
            .where(
                FuturesKline1h.symbol.in_(symbols),
                FuturesKline1h.aggregation_status == "AGG_READY",
            )
            .order_by(asc(FuturesKline1h.symbol), asc(FuturesKline1h.open_time))
        )
        return _candle_map(self.db.scalars(query).all())


def _grid_row(
    *,
    lane_stage: str,
    lane_timeframe: str,
    signals: list[StrategySignal],
    candles_15m: dict[str, list[StrategyCandle]],
    candles_1h: dict[str, list[StrategyCandle]],
    open_times_15m: dict[str, list[datetime]],
    close_times_1h: dict[str, list[datetime]],
    atr_mult: Decimal,
    rr: Decimal,
    timeout_minutes: int,
    min_sample: int,
    position_lock: bool,
) -> dict[str, Any]:
    result_counts: Counter[str] = Counter()
    skipped_counts: Counter[str] = Counter()
    realized_values: list[Decimal] = []
    ordered_results: list[dict[str, Any]] = []
    locked_until: dict[str, datetime | None] = {}
    timeout_count = max(1, timeout_minutes // 15)
    for signal in signals:
        lock_time = locked_until.get(signal.symbol)
        if position_lock and signal.symbol in locked_until and (lock_time is None or signal.signal_timestamp < lock_time):
            skipped_counts["ACTIVE_POSITION_LOCK"] += 1
            continue
        atr = _atr_at(
            candles_1h.get(signal.symbol, []),
            close_times_1h.get(signal.symbol, []),
            signal.signal_timestamp,
        )
        if atr is None:
            skipped_counts["MISSING_ATR_1H"] += 1
            continue
        future = _future_window(
            candles_15m.get(signal.symbol, []),
            open_times_15m.get(signal.symbol, []),
            signal.signal_timestamp,
            timeout_count,
        )
        if not future:
            skipped_counts["MISSING_FORWARD_15M"] += 1
            continue
        result = _evaluate_timeout_path(signal, future, risk=atr * atr_mult, rr=rr, expected_count=timeout_count)
        result_counts[result["result_status"]] += 1
        if result["realized_r"] is not None:
            realized = Decimal(result["realized_r"])
            realized_values.append(realized)
            ordered_results.append({**result, "symbol": signal.symbol})
        if position_lock:
            if result["result_status"] in COMPLETED_RESULTS and result.get("result_time_utc"):
                locked_until[signal.symbol] = result["result_time_utc"]
            else:
                locked_until[signal.symbol] = None

    sample_count = sum(result_counts.values())
    closed_count = len(realized_values)
    total_r = sum(realized_values, Decimal("0"))
    avg_r = total_r / Decimal(closed_count) if closed_count else None
    median_r = Decimal(str(median(realized_values))) if realized_values else None
    winrate_denominator = result_counts["TP_HIT"] + result_counts["SL_HIT"]
    winrate = (Decimal(result_counts["TP_HIT"]) / Decimal(winrate_denominator) * Decimal("100")) if winrate_denominator else None
    drawdown = _drawdown(ordered_results)
    positive_timeout = sum(1 for row in ordered_results if row["result_status"] == "TIMEOUT_CLOSE" and Decimal(row["realized_r"]) > 0)
    negative_timeout = sum(1 for row in ordered_results if row["result_status"] == "TIMEOUT_CLOSE" and Decimal(row["realized_r"]) < 0)
    return {
        "stage": lane_stage,
        "timeframe": lane_timeframe,
        "atr_mult": atr_mult,
        "rr": rr,
        "timeout_minutes": timeout_minutes,
        "sample_count": sample_count,
        "closed_count": closed_count,
        "tp_count": result_counts["TP_HIT"],
        "sl_count": result_counts["SL_HIT"],
        "both_hit_count": result_counts["BOTH_HIT_SAME_CANDLE"],
        "timeout_count": result_counts["TIMEOUT_CLOSE"],
        "waiting_count": result_counts["WAITING_DATA"],
        "positive_timeout_count": positive_timeout,
        "negative_timeout_count": negative_timeout,
        "total_r": total_r,
        "avg_r": avg_r,
        "median_r": median_r,
        "winrate_pct": winrate,
        "max_drawdown_r": drawdown["max_drawdown_r"],
        "current_drawdown_r": drawdown["current_drawdown_r"],
        "skipped_counts": dict(skipped_counts),
        "verdict": _strategy_verdict(sample_count=sample_count, total_r=total_r, avg_r=avg_r, median_r=median_r, min_sample=min_sample),
    }


def _evaluate_timeout_path(
    signal: StrategySignal,
    future: list[StrategyCandle],
    *,
    risk: Decimal,
    rr: Decimal,
    expected_count: int,
) -> dict[str, Any]:
    if risk <= 0:
        return {"result_status": "INVALID_RISK", "result_time_utc": None, "realized_r": None}
    if signal.direction == "LONG":
        stop = signal.entry - risk
        target = signal.entry + (rr * risk)
    else:
        stop = signal.entry + risk
        target = signal.entry - (rr * risk)
    for candle in future:
        if signal.direction == "LONG":
            tp_hit = candle.high >= target
            sl_hit = candle.low <= stop
        else:
            tp_hit = candle.low <= target
            sl_hit = candle.high >= stop
        if tp_hit and sl_hit:
            return {"result_status": "BOTH_HIT_SAME_CANDLE", "result_time_utc": candle.close_time, "realized_r": Decimal("0")}
        if tp_hit:
            return {"result_status": "TP_HIT", "result_time_utc": candle.close_time, "realized_r": rr}
        if sl_hit:
            return {"result_status": "SL_HIT", "result_time_utc": candle.close_time, "realized_r": Decimal("-1")}
    if len(future) < expected_count:
        return {"result_status": "WAITING_DATA", "result_time_utc": None, "realized_r": None}
    latest = future[-1]
    close_r = (latest.close - signal.entry) / risk if signal.direction == "LONG" else (signal.entry - latest.close) / risk
    return {"result_status": "TIMEOUT_CLOSE", "result_time_utc": latest.close_time, "realized_r": close_r}


def _future_window(
    candles: list[StrategyCandle],
    open_times: list[datetime],
    signal_time: datetime,
    expected_count: int,
) -> list[StrategyCandle]:
    position = bisect_left(open_times, signal_time)
    window = candles[position : position + expected_count]
    if not window:
        return []
    expected = signal_time
    contiguous: list[StrategyCandle] = []
    for candle in window:
        if candle.open_time != expected:
            break
        contiguous.append(candle)
        expected += timedelta(minutes=15)
    return contiguous


def _atr_at(candles: list[StrategyCandle], close_times: list[datetime], signal_time: datetime, period: int = 14) -> Decimal | None:
    position = bisect_right(close_times, signal_time) - 1
    if position < period:
        return None
    window = candles[position - period : position + 1]
    ranges: list[Decimal] = []
    for index in range(1, len(window)):
        candle = window[index]
        previous = window[index - 1]
        ranges.append(max(candle.high - candle.low, abs(candle.high - previous.close), abs(candle.low - previous.close)))
    if len(ranges) != period:
        return None
    atr = sum(ranges, Decimal("0")) / Decimal(period)
    return atr if atr > 0 else None


def _candle_map(rows: list[Any]) -> dict[str, list[StrategyCandle]]:
    output: dict[str, list[StrategyCandle]] = defaultdict(list)
    for row in rows:
        if row.high is None or row.low is None or row.close is None:
            continue
        output[row.symbol].append(
            StrategyCandle(
                open_time=_naive(row.open_time),
                close_time=_naive(row.close_time),
                high=Decimal(row.high),
                low=Decimal(row.low),
                close=Decimal(row.close),
            )
        )
    return dict(output)


def _group_by_lane(signals: list[StrategySignal]) -> dict[tuple[str, str], list[StrategySignal]]:
    grouped: dict[tuple[str, str], list[StrategySignal]] = {}
    for signal in signals:
        if signal.stage not in STAGES or signal.timeframe not in TIMEFRAMES:
            continue
        grouped.setdefault((signal.stage, signal.timeframe), []).append(signal)
    return grouped


def _best_by_lane(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["stage"], row["timeframe"])].append(row)
    best = [sorted(items, key=_row_sort_key, reverse=True)[0] for items in grouped.values()]
    return sorted(best, key=_row_sort_key, reverse=True)


def _row_sort_key(row: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, int]:
    return (
        Decimal(row["total_r"]),
        Decimal(row["avg_r"]) if row["avg_r"] is not None else Decimal("-999"),
        Decimal(row["median_r"]) if row["median_r"] is not None else Decimal("-999"),
        int(row["sample_count"]),
    )


def _strategy_verdict(
    *,
    sample_count: int,
    total_r: Decimal,
    avg_r: Decimal | None,
    median_r: Decimal | None,
    min_sample: int,
) -> str:
    if sample_count < min_sample:
        return "INSUFFICIENT_SAMPLE"
    if total_r > 0 and avg_r is not None and avg_r > Decimal("0.05") and median_r is not None and median_r > Decimal("-0.10"):
        return "PROMISING_TIMEOUT_MODEL"
    if total_r > 0 and avg_r is not None and avg_r > 0:
        return "MONITOR_MORE"
    if total_r < 0 and median_r is not None and median_r < 0:
        return "NOISY_OR_WEAK"
    return "MIXED"


def _drawdown(rows: list[dict[str, Any]]) -> dict[str, Decimal]:
    rows = sorted(rows, key=lambda row: row["result_time_utc"] or datetime.min)
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for row in rows:
        cumulative += Decimal(row["realized_r"])
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return {"max_drawdown_r": max_drawdown, "current_drawdown_r": cumulative - peak}


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)
