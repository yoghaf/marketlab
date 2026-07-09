from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import asc, or_, select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline1m, FuturesKline15m, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import utcnow


COMPLETED_OUTCOMES = {"TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE"}

EVIDENCE_FIELDS = [
    ("price_return", "Price return %"),
    ("volume_ratio_vs_lookback", "Volume vs avg"),
    ("range_ratio_vs_atr", "Range / ATR"),
    ("atr_extension_normalized", "ATR extension"),
    ("price_atr_multiple", "Price ATR multiple"),
    ("kline_taker_buy_ratio", "Taker buy ratio"),
    ("kline_taker_sell_ratio", "Taker sell ratio"),
    ("oi_change_pct", "OI change %"),
    ("oi_zscore", "OI z-score"),
    ("funding_percentile_30d", "Funding percentile"),
    ("futures_spread_pct", "Futures spread %"),
    ("spot_spread_pct", "Spot spread %"),
    ("global_long_short_ratio", "Global L/S ratio"),
    ("top_trader_position_ratio", "Top trader position"),
    ("top_trader_account_ratio", "Top trader account"),
    ("core_score", "Core score"),
    ("evidence_score", "Evidence score"),
    ("evidence_data_completeness", "Evidence completeness"),
]


@dataclass(frozen=True)
class PerfCandle:
    open_time: datetime
    close_time: datetime
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class FilterStudySpec:
    filter_id: str
    label: str
    expression: str
    family: str
    required_fields: tuple[str, ...]
    predicate: Callable[[dict[str, Any]], bool]


class SignalCandidatePerformanceService:
    """Read-only live-style performance view for logged Signal Factory candidates."""

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
        symbol: str | None = None,
        result_status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            symbol=symbol,
            position_lock=position_lock,
        )
        evaluated = _filter_by_result_status(evaluated, result_status)
        aggregate = self._aggregate(evaluated, skipped)
        items = sorted(evaluated, key=lambda item: item["signal_timestamp"] or datetime.min, reverse=True)[:limit]
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": stage,
                "timeframe": timeframe,
                "symbol": symbol,
                "result_status": result_status,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "entry_market": "futures",
            "entry_price_source": "signal_forward_return_logs.price_at_signal",
            "evaluation_candle_interval": "15m_closed_plus_1m_tail",
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "aggregate": aggregate,
            "items": items,
        }

    def detail(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        signal_id: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        include_watch_only: bool = True,
    ) -> dict[str, Any] | None:
        signals = self._load_signals(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=None,
            timeframe=timeframe,
            symbol=symbol,
            signal_id=signal_id,
        )
        if not signals:
            return None
        signal = signals[0] if signal_id else signals[-1]
        signal_time = _naive(signal.signal_timestamp)
        symbols = {signal.symbol}
        base_candles = self._load_15m_candles(symbols, start_time=signal_time)
        latest_base_time = max(
            (candle.close_time for rows in base_candles.values() for candle in rows),
            default=None,
        )
        tail_candles = self._load_1m_candles(symbols, start_time=latest_base_time or signal_time)
        candles = _merge_candle_maps(base_candles, tail_candles)
        item = self._evaluate_signal(
            signal,
            candles.get(signal.symbol, []),
            [candle.open_time for candle in candles.get(signal.symbol, [])],
        )
        latest_candle_time = max(
            (candle.close_time for rows in candles.values() for candle in rows),
            default=None,
        )
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "entry_market": "futures",
            "entry_price_source": "signal_forward_return_logs.price_at_signal",
            "evaluation_candle_interval": "15m_closed_plus_1m_tail",
            "latest_evaluation_candle_time": latest_candle_time,
            "item": item,
            "raw_signal": {
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "timeframe": signal.timeframe,
                "signal_timestamp": signal.signal_timestamp,
                "window_open_time": signal.window_open_time,
                "window_close_time": signal.window_close_time,
                "direction": signal.direction,
                "stage": signal.stage,
                "candidate_status": signal.candidate_status,
                "confidence_tier": signal.confidence_tier,
                "execution_flag": signal.execution_flag,
                "source_artifact_generated_at": signal.source_artifact_generated_at,
                "observation_epoch": signal.observation_epoch,
                "created_at": signal.created_at,
                "updated_at": signal.updated_at,
            },
            "evidence": signal.evidence or {},
        }

    def quality_lab(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        stage: str | None = None,
        timeframe: str | None = None,
        min_sample: int = 5,
        limit: int = 25,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            symbol=None,
            position_lock=position_lock,
        )
        aggregate = self._aggregate(evaluated, skipped)
        closed = [item for item in evaluated if item["result_status"] in COMPLETED_OUTCOMES and item.get("realized_r") is not None]
        best = sorted(closed, key=lambda item: Decimal(item["realized_r"]), reverse=True)[:limit]
        worst = sorted(closed, key=lambda item: Decimal(item["realized_r"]))[:limit]
        open_items = sorted(
            [item for item in evaluated if item["result_status"] == "OPEN" and item.get("unrealized_r") is not None],
            key=lambda item: Decimal(item["unrealized_r"]),
            reverse=True,
        )[:limit]

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
            "evaluation_candle_interval": "15m_closed_plus_1m_tail",
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "aggregate": aggregate,
            "drawdown": _drawdown_summary(evaluated),
            "by_stage": _bucket_rows(evaluated, key="stage", min_sample=min_sample),
            "by_confidence": _bucket_rows(evaluated, key="confidence_tier", min_sample=min_sample),
            "by_timeframe": _bucket_rows(evaluated, key="timeframe", min_sample=min_sample),
            "evidence_fields": _evidence_field_rows(evaluated, min_sample=min_sample),
            "top_symbols": _bucket_rows(evaluated, key="symbol", min_sample=min_sample, limit=limit, reverse=True),
            "weak_symbols": _bucket_rows(evaluated, key="symbol", min_sample=min_sample, limit=limit, reverse=False),
            "best_signals": best,
            "worst_signals": worst,
            "open_signals": open_items,
        }

    def filter_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        stage: str = "MID_SHORT",
        timeframe: str = "1h",
        min_sample: int = 20,
        limit: int = 40,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            symbol=None,
            position_lock=position_lock,
        )
        baseline = _filter_study_row(
            filter_id="BASELINE",
            label=f"Baseline {timeframe} {stage}",
            expression="no additional filter",
            family="BASELINE",
            items=evaluated,
            source_count=len(evaluated),
            missing_data_count=0,
            required_fields=(),
            baseline_perf=None,
            min_sample=min_sample,
        )
        rows = [baseline]
        for spec in _filter_study_specs():
            passed: list[dict[str, Any]] = []
            missing_data_count = 0
            for item in evaluated:
                evidence = item.get("evidence_snapshot") or {}
                if any(evidence.get(field) is None for field in spec.required_fields):
                    missing_data_count += 1
                    continue
                if spec.predicate(item):
                    passed.append(item)
            rows.append(
                _filter_study_row(
                    filter_id=spec.filter_id,
                    label=spec.label,
                    expression=spec.expression,
                    family=spec.family,
                    items=passed,
                    source_count=len(evaluated),
                    missing_data_count=missing_data_count,
                    required_fields=spec.required_fields,
                    baseline_perf=baseline,
                    min_sample=min_sample,
                )
            )
        rows = [rows[0], *_sort_filter_rows(rows[1:])[:limit]]
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
            "study_scope": "read_only_filter_study",
            "evaluation_candle_interval": "15m_closed_plus_1m_tail",
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "baseline": baseline,
            "rows": rows,
        }

    def calibration_lab(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 5,
        limit: int = 30,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=None,
            timeframe=None,
            symbol=None,
            position_lock=position_lock,
        )
        lanes: list[dict[str, Any]] = []
        for stage in ("EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"):
            for timeframe in ("15m", "1h", "4h", "24h"):
                lane_items = [
                    item
                    for item in evaluated
                    if item.get("stage") == stage and item.get("timeframe") == timeframe
                ]
                lanes.append(
                    _calibration_lane(
                        stage=stage,
                        timeframe=timeframe,
                        items=lane_items,
                        min_sample=min_sample,
                        limit=limit,
                    )
                )
        candidates = [
            {**candidate, "stage": lane["stage"], "timeframe": lane["timeframe"]}
            for lane in lanes
            for candidate in lane["filter_candidates"]
        ]
        candidates.sort(key=_calibration_candidate_sort_key, reverse=True)
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "study_scope": "read_only_signal_calibration_train_validation",
            "method": "Static filter candidates over logged Signal results with 70/30 chronological split.",
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "aggregate": self._aggregate(evaluated, skipped),
            "lanes": lanes,
            "top_candidates": candidates[:limit],
            "guardrails": [
                "No Signal Factory rule changed.",
                "No scanner behavior changed.",
                "No outcome calculation changed.",
                "No TP/SL formula, order, execution, leverage, or position sizing is created.",
                "Promising filters are research-only until enough forward validation exists.",
            ],
        }

    def _evaluated_context(
        self,
        *,
        epoch: str,
        include_watch_only: bool,
        stage: str | None,
        timeframe: str | None,
        symbol: str | None,
        position_lock: bool,
    ) -> tuple[list[dict[str, Any]], Counter[str], datetime | None]:
        signals = self._load_signals(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            symbol=symbol,
            signal_id=None,
        )
        min_signal_time = min((_naive(row.signal_timestamp) for row in signals), default=None)
        symbols = {row.symbol for row in signals}
        base_candles = self._load_15m_candles(symbols, start_time=min_signal_time)
        latest_base_time = max(
            (candle.close_time for rows in base_candles.values() for candle in rows),
            default=None,
        )
        tail_start = latest_base_time or min_signal_time
        tail_candles = self._load_1m_candles(symbols, start_time=tail_start)
        candles = _merge_candle_maps(base_candles, tail_candles)
        evaluated, skipped = self._evaluate(signals, candles, position_lock=position_lock)
        latest_candle_time = max(
            (candle.close_time for rows in candles.values() for candle in rows),
            default=None,
        )
        return evaluated, skipped, latest_candle_time

    def _load_signals(
        self,
        *,
        epoch: str,
        include_watch_only: bool,
        stage: str | None,
        timeframe: str | None,
        symbol: str | None = None,
        signal_id: str | None = None,
    ) -> list[SignalForwardReturnLog]:
        query = (
            select(SignalForwardReturnLog)
            .where(
                SignalForwardReturnLog.candidate_status == "SIGNAL_CANDIDATE",
                SignalForwardReturnLog.observation_epoch == epoch,
                SignalForwardReturnLog.price_at_signal.is_not(None),
                SignalForwardReturnLog.sl_ref.is_not(None),
                SignalForwardReturnLog.tp_ref.is_not(None),
            )
            .order_by(asc(SignalForwardReturnLog.signal_timestamp), asc(SignalForwardReturnLog.symbol))
        )
        if not include_watch_only:
            query = query.where(
                or_(
                    SignalForwardReturnLog.execution_flag.is_(None),
                    SignalForwardReturnLog.execution_flag != "WATCH_ONLY",
                )
            )
        if stage:
            query = query.where(SignalForwardReturnLog.stage == stage)
        if timeframe:
            query = query.where(SignalForwardReturnLog.timeframe == timeframe)
        if symbol:
            query = query.where(SignalForwardReturnLog.symbol == symbol.upper())
        if signal_id:
            query = query.where(SignalForwardReturnLog.signal_id == signal_id)
        return list(self.db.scalars(query).all())

    def _load_15m_candles(self, symbols: set[str], *, start_time: datetime | None) -> dict[str, list[PerfCandle]]:
        if not symbols:
            return {}
        query = (
            select(
                FuturesKline15m.symbol,
                FuturesKline15m.open_time,
                FuturesKline15m.close_time,
                FuturesKline15m.high,
                FuturesKline15m.low,
                FuturesKline15m.close,
            )
            .where(
                FuturesKline15m.symbol.in_(symbols),
                FuturesKline15m.aggregation_status == "AGG_READY",
            )
            .order_by(asc(FuturesKline15m.symbol), asc(FuturesKline15m.open_time))
        )
        if start_time is not None:
            query = query.where(FuturesKline15m.open_time >= start_time)
        rows = self.db.execute(query).all()
        output: dict[str, list[PerfCandle]] = defaultdict(list)
        for row in rows:
            output[row.symbol].append(
                PerfCandle(
                    open_time=_naive(row.open_time),
                    close_time=_naive(row.close_time),
                    high=Decimal(row.high),
                    low=Decimal(row.low),
                    close=Decimal(row.close),
                )
            )
        return dict(output)

    def _load_1m_candles(self, symbols: set[str], *, start_time: datetime | None) -> dict[str, list[PerfCandle]]:
        if not symbols or start_time is None:
            return {}
        query = (
            select(
                FuturesKline1m.symbol,
                FuturesKline1m.open_time,
                FuturesKline1m.close_time,
                FuturesKline1m.high_price,
                FuturesKline1m.low_price,
                FuturesKline1m.close_price,
            )
            .where(
                FuturesKline1m.symbol.in_(symbols),
                FuturesKline1m.open_time >= start_time,
            )
            .order_by(asc(FuturesKline1m.symbol), asc(FuturesKline1m.open_time))
        )
        rows = self.db.execute(query).all()
        output: dict[str, list[PerfCandle]] = defaultdict(list)
        for row in rows:
            output[row.symbol].append(
                PerfCandle(
                    open_time=_naive(row.open_time),
                    close_time=_naive(row.close_time),
                    high=Decimal(row.high_price),
                    low=Decimal(row.low_price),
                    close=Decimal(row.close_price),
                )
            )
        return dict(output)

    def _evaluate(
        self,
        signals: list[SignalForwardReturnLog],
        candles: dict[str, list[PerfCandle]],
        *,
        position_lock: bool,
    ) -> tuple[list[dict[str, Any]], Counter[str]]:
        items: list[dict[str, Any]] = []
        skipped: Counter[str] = Counter()
        locked_until: dict[str, datetime | None] = {}
        open_times_by_symbol = {symbol: [candle.open_time for candle in rows] for symbol, rows in candles.items()}
        for signal in signals:
            signal_time = _naive(signal.signal_timestamp)
            lock_time = locked_until.get(signal.symbol)
            if position_lock and signal.symbol in locked_until and (lock_time is None or signal_time < lock_time):
                skipped["ACTIVE_POSITION_LOCK"] += 1
                continue
            item = self._evaluate_signal(
                signal,
                candles.get(signal.symbol, []),
                open_times_by_symbol.get(signal.symbol, []),
            )
            items.append(item)
            if position_lock:
                if item["result_status"] in COMPLETED_OUTCOMES and item.get("result_time_utc"):
                    locked_until[signal.symbol] = _parse_dt(item["result_time_utc"])
                else:
                    locked_until[signal.symbol] = None
        return items, skipped

    def _evaluate_signal(
        self,
        signal: SignalForwardReturnLog,
        candles: list[PerfCandle],
        open_times: list[datetime],
    ) -> dict[str, Any]:
        entry = Decimal(signal.price_at_signal)
        stop = Decimal(signal.sl_ref)
        target = Decimal(signal.tp_ref)
        risk = abs(entry - stop)
        signal_time = _naive(signal.signal_timestamp)
        direction = signal.direction
        position = bisect_left(open_times, signal_time)
        future = candles[position:]
        base = {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "signal_timestamp": signal_time,
            "signal_time_wib": _wib_string(signal_time),
            "stage": signal.stage,
            "direction": direction,
            "candidate_status": signal.candidate_status,
            "confidence_tier": signal.confidence_tier,
            "execution_flag": signal.execution_flag,
            "core_score": signal.core_score,
            "evidence_score": signal.evidence_score,
            "evidence_data_completeness": signal.evidence_data_completeness,
            "evidence_snapshot": _evidence_snapshot(signal),
            "entry": entry,
            "stop_loss": stop,
            "take_profit": target,
            "risk": risk,
            "rr": abs(target - entry) / risk if risk > 0 else None,
            "result_status": "WAITING_DATA",
            "result_time_utc": None,
            "result_time_wib": None,
            "exit_price": None,
            "realized_r": None,
            "unrealized_r": None,
            "mfe_r": None,
            "mae_r": None,
            "candles_seen": 0,
            "not_live_signal": True,
            "not_execution_instruction": True,
        }
        if risk <= 0:
            return {**base, "result_status": "INVALID_RISK"}
        if direction not in {"LONG", "SHORT"}:
            return {**base, "result_status": "NON_DIRECTIONAL"}
        if not future:
            return base

        mfe = Decimal("0")
        mae = Decimal("0")
        for index, candle in enumerate(future, start=1):
            if direction == "LONG":
                tp_hit = candle.high >= target
                sl_hit = candle.low <= stop
                mfe = max(mfe, (candle.high - entry) / risk)
                mae = min(mae, (candle.low - entry) / risk)
            else:
                tp_hit = candle.low <= target
                sl_hit = candle.high >= stop
                mfe = max(mfe, (entry - candle.low) / risk)
                mae = min(mae, (entry - candle.high) / risk)
            if tp_hit and sl_hit:
                return {
                    **base,
                    "result_status": "BOTH_HIT_SAME_CANDLE",
                    "result_time_utc": candle.close_time,
                    "result_time_wib": _wib_string(candle.close_time),
                    "exit_price": candle.close,
                    "realized_r": Decimal("0"),
                    "unrealized_r": None,
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": index,
                }
            if tp_hit:
                return {
                    **base,
                    "result_status": "TP_HIT",
                    "result_time_utc": candle.close_time,
                    "result_time_wib": _wib_string(candle.close_time),
                    "exit_price": target,
                    "realized_r": abs(target - entry) / risk,
                    "unrealized_r": None,
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": index,
                }
            if sl_hit:
                return {
                    **base,
                    "result_status": "SL_HIT",
                    "result_time_utc": candle.close_time,
                    "result_time_wib": _wib_string(candle.close_time),
                    "exit_price": stop,
                    "realized_r": Decimal("-1"),
                    "unrealized_r": None,
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": index,
                }

        latest = future[-1]
        unrealized = (latest.close - entry) / risk if direction == "LONG" else (entry - latest.close) / risk
        return {
            **base,
            "result_status": "OPEN",
            "result_time_utc": latest.close_time,
            "result_time_wib": _wib_string(latest.close_time),
            "exit_price": latest.close,
            "unrealized_r": unrealized,
            "mfe_r": mfe,
            "mae_r": mae,
            "candles_seen": len(future),
        }

    def _aggregate(self, items: list[dict[str, Any]], skipped: Counter[str]) -> dict[str, Any]:
        status_counts = Counter(str(item["result_status"]) for item in items)
        by_stage = Counter(str(item["stage"]) for item in items)
        by_timeframe = Counter(str(item["timeframe"]) for item in items)
        by_confidence = Counter(str(item.get("confidence_tier") or "UNKNOWN") for item in items)
        total_perf = _performance_summary(items)
        timeframe_perf = {
            timeframe: _performance_summary([item for item in items if item.get("timeframe") == timeframe])
            for timeframe in ("15m", "1h", "4h", "24h")
        }
        return {
            "signals_skipped": sum(skipped.values()),
            "skip_reasons": dict(skipped),
            **total_perf,
            "status_counts": dict(status_counts),
            "by_stage": dict(by_stage),
            "by_timeframe": dict(by_timeframe),
            "by_timeframe_performance": timeframe_perf,
            "by_confidence": dict(by_confidence),
        }


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _naive(value)
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _wib_string(value: datetime | None) -> str | None:
    if not value:
        return None
    wib = _naive(value) + timedelta(hours=7)
    return f"{wib:%Y-%m-%d %H:%M:%S} WIB"


def _performance_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(item["result_status"]) for item in items)
    closed = [item for item in items if item["result_status"] in COMPLETED_OUTCOMES]
    wins = [item for item in closed if item["result_status"] == "TP_HIT"]
    losses = [item for item in closed if item["result_status"] == "SL_HIT"]
    realized_values = [Decimal(item["realized_r"]) for item in closed if item.get("realized_r") is not None]
    open_values = [
        Decimal(item["unrealized_r"])
        for item in items
        if item["result_status"] == "OPEN" and item.get("unrealized_r") is not None
    ]
    completed_for_winrate = len(wins) + len(losses)
    total_r_closed = sum(realized_values, Decimal("0"))
    total_unrealized_r = sum(open_values, Decimal("0"))
    return {
        "signals_evaluated": len(items),
        "open_count": status_counts.get("OPEN", 0),
        "waiting_count": status_counts.get("WAITING_DATA", 0),
        "tp_count": status_counts.get("TP_HIT", 0),
        "sl_count": status_counts.get("SL_HIT", 0),
        "both_hit_count": status_counts.get("BOTH_HIT_SAME_CANDLE", 0),
        "closed_count": len(closed),
        "winrate_pct": (Decimal(len(wins)) / Decimal(completed_for_winrate) * Decimal("100")) if completed_for_winrate else None,
        "total_r_closed": total_r_closed,
        "open_unrealized_r": total_unrealized_r,
        "total_r_with_open": total_r_closed + total_unrealized_r,
        "fixed_risk_return_pct_1pct_closed": total_r_closed,
        "fixed_risk_return_pct_1pct_with_open": total_r_closed + total_unrealized_r,
        "avg_r_closed": total_r_closed / Decimal(len(realized_values)) if realized_values else None,
    }


def _filter_by_result_status(items: list[dict[str, Any]], result_status: str | None) -> list[dict[str, Any]]:
    if not result_status:
        return items
    normalized = result_status.upper()
    if normalized in {"CLOSED", "COMPLETED"}:
        return [item for item in items if item.get("result_status") in COMPLETED_OUTCOMES]
    if normalized == "OPEN":
        return [item for item in items if item.get("result_status") == "OPEN"]
    if normalized == "TP_SL":
        return [item for item in items if item.get("result_status") in {"TP_HIT", "SL_HIT"}]
    statuses = {part.strip() for part in normalized.split(",") if part.strip()}
    return [item for item in items if item.get("result_status") in statuses]


def _merge_candle_maps(
    base_candles: dict[str, list[PerfCandle]],
    tail_candles: dict[str, list[PerfCandle]],
) -> dict[str, list[PerfCandle]]:
    symbols = set(base_candles) | set(tail_candles)
    merged: dict[str, list[PerfCandle]] = {}
    for symbol in symbols:
        by_open_time = {candle.open_time: candle for candle in base_candles.get(symbol, [])}
        for candle in tail_candles.get(symbol, []):
            by_open_time[candle.open_time] = candle
        merged[symbol] = [by_open_time[key] for key in sorted(by_open_time)]
    return merged


def _evidence_snapshot(signal: SignalForwardReturnLog) -> dict[str, Decimal | None]:
    raw_evidence = signal.evidence if isinstance(signal.evidence, dict) else {}
    evidence = raw_evidence.get("evidence") if isinstance(raw_evidence.get("evidence"), dict) else raw_evidence
    snapshot: dict[str, Decimal | None] = {}
    for field, _label in EVIDENCE_FIELDS:
        if field == "core_score":
            value = signal.core_score
        elif field == "evidence_score":
            value = signal.evidence_score
        elif field == "evidence_data_completeness":
            value = signal.evidence_data_completeness
        else:
            value = evidence.get(field)
        snapshot[field] = _decimal_or_none(value)
    return snapshot


def _evidence_field_rows(items: list[dict[str, Any]], *, min_sample: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, label in EVIDENCE_FIELDS:
        values_by_result: dict[str, list[Decimal]] = defaultdict(list)
        missing = 0
        for item in items:
            value = (item.get("evidence_snapshot") or {}).get(field)
            if value is None:
                missing += 1
                continue
            result = str(item.get("result_status") or "UNKNOWN")
            if result == "BOTH_HIT_SAME_CANDLE":
                result = "BOTH"
            values_by_result[result].append(Decimal(value))

        available_count = sum(len(values) for values in values_by_result.values())
        tp_values = values_by_result.get("TP_HIT", [])
        sl_values = values_by_result.get("SL_HIT", [])
        open_values = values_by_result.get("OPEN", [])
        waiting_values = values_by_result.get("WAITING_DATA", [])
        both_values = values_by_result.get("BOTH", [])
        tp_median = _median_decimal(tp_values)
        sl_median = _median_decimal(sl_values)
        delta = tp_median - sl_median if tp_median is not None and sl_median is not None else None
        rows.append(
            {
                "field": field,
                "label": label,
                "quality_flag": _evidence_quality_flag(
                    tp_count=len(tp_values),
                    sl_count=len(sl_values),
                    delta=delta,
                    min_sample=min_sample,
                ),
                "available_count": available_count,
                "missing_count": missing,
                "available_pct": (Decimal(available_count) / Decimal(len(items)) * Decimal("100")) if items else None,
                "tp_count": len(tp_values),
                "sl_count": len(sl_values),
                "open_count": len(open_values),
                "waiting_count": len(waiting_values),
                "both_count": len(both_values),
                "tp_median": tp_median,
                "sl_median": sl_median,
                "open_median": _median_decimal(open_values),
                "waiting_median": _median_decimal(waiting_values),
                "tp_avg": _avg_decimal(tp_values),
                "sl_avg": _avg_decimal(sl_values),
                "tp_q1": _percentile_decimal(tp_values, Decimal("0.25")),
                "tp_q3": _percentile_decimal(tp_values, Decimal("0.75")),
                "sl_q1": _percentile_decimal(sl_values, Decimal("0.25")),
                "sl_q3": _percentile_decimal(sl_values, Decimal("0.75")),
                "delta_tp_minus_sl": delta,
            }
        )
    rows.sort(
        key=lambda row: (
            row["quality_flag"] != "SAMPLE_TOO_SMALL",
            abs(Decimal(row["delta_tp_minus_sl"])) if row["delta_tp_minus_sl"] is not None else Decimal("-1"),
            row["available_count"],
        ),
        reverse=True,
    )
    return rows


def _evidence_quality_flag(*, tp_count: int, sl_count: int, delta: Decimal | None, min_sample: int) -> str:
    if tp_count < min_sample or sl_count < min_sample or delta is None:
        return "SAMPLE_TOO_SMALL"
    if abs(delta) < Decimal("0.0001"):
        return "NO_CLEAR_GAP"
    if delta > 0:
        return "TP_HIGHER"
    return "SL_HIGHER"


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _avg_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _percentile_decimal(values: list[Decimal], pct: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = pct * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _bucket_rows(
    items: list[dict[str, Any]],
    *,
    key: str,
    min_sample: int,
    limit: int | None = None,
    reverse: bool = True,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[str(item.get(key) or "UNKNOWN")].append(item)

    rows = [_bucket_summary(bucket, bucket_items, min_sample=min_sample) for bucket, bucket_items in grouped.items()]
    rows.sort(
        key=lambda row: (
            Decimal(row["total_r_closed"]),
            Decimal(row["median_r_closed"]) if row["median_r_closed"] is not None else Decimal("-999"),
            row["signals_evaluated"],
        ),
        reverse=reverse,
    )
    return rows[:limit] if limit is not None else rows


def _bucket_summary(bucket: str, items: list[dict[str, Any]], *, min_sample: int) -> dict[str, Any]:
    perf = _performance_summary(items)
    closed = [item for item in items if item["result_status"] in COMPLETED_OUTCOMES and item.get("realized_r") is not None]
    realized_values = [Decimal(item["realized_r"]) for item in closed]
    mfe_values = [Decimal(item["mfe_r"]) for item in items if item.get("mfe_r") is not None]
    mae_values = [Decimal(item["mae_r"]) for item in items if item.get("mae_r") is not None]
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    top_symbol, top_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    closed_count = int(perf["closed_count"])
    total_r = Decimal(perf["total_r_closed"])
    median_r = _median_decimal(realized_values)
    winrate = perf["winrate_pct"]
    quality_flag = _quality_flag(
        sample_size=len(items),
        closed_count=closed_count,
        total_r=total_r,
        median_r=median_r,
        winrate=winrate,
        min_sample=min_sample,
    )
    return {
        "bucket": bucket,
        "quality_flag": quality_flag,
        "signals_evaluated": len(items),
        "symbol_count": len(symbols),
        "top_symbol": top_symbol,
        "top_symbol_share_pct": (Decimal(top_count) / Decimal(len(items)) * Decimal("100")) if items else None,
        "median_r_closed": median_r,
        "median_mfe_r": _median_decimal(mfe_values),
        "median_mae_r": _median_decimal(mae_values),
        "best_r": max(realized_values) if realized_values else None,
        "worst_r": min(realized_values) if realized_values else None,
        **perf,
    }


def _filter_study_specs() -> list[FilterStudySpec]:
    return [
        FilterStudySpec(
            "CONF_MEDIUM_HIGH",
            "Confidence medium/high",
            "confidence_tier in MEDIUM_CONF,HIGH_CONF",
            "confidence",
            (),
            lambda item: str(item.get("confidence_tier") or "") in {"MEDIUM_CONF", "HIGH_CONF", "MEDIUM", "HIGH"},
        ),
        FilterStudySpec(
            "FUNDING_GE_75",
            "Funding percentile tinggi",
            "funding_percentile_30d >= 75",
            "funding",
            ("funding_percentile_30d",),
            lambda item: (_evidence_value(item, "funding_percentile_30d") or Decimal("-999")) >= Decimal("75"),
        ),
        FilterStudySpec(
            "GLOBAL_LS_GE_1_20",
            "Global L/S crowded long",
            "global_long_short_ratio >= 1.20",
            "positioning",
            ("global_long_short_ratio",),
            lambda item: (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "TOP_POSITION_GE_1_10",
            "Top trader position long bias",
            "top_trader_position_ratio >= 1.10",
            "positioning",
            ("top_trader_position_ratio",),
            lambda item: (_evidence_value(item, "top_trader_position_ratio") or Decimal("-999")) >= Decimal("1.10"),
        ),
        FilterStudySpec(
            "TOP_ACCOUNT_GE_1_10",
            "Top trader account long bias",
            "top_trader_account_ratio >= 1.10",
            "positioning",
            ("top_trader_account_ratio",),
            lambda item: (_evidence_value(item, "top_trader_account_ratio") or Decimal("-999")) >= Decimal("1.10"),
        ),
        FilterStudySpec(
            "VOLUME_LE_1_50",
            "Volume tidak ekstrem",
            "volume_ratio_vs_lookback <= 1.50",
            "volume",
            ("volume_ratio_vs_lookback",),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "VOLUME_BETWEEN_0_80_1_50",
            "Volume normal-tinggi",
            "0.80 <= volume_ratio_vs_lookback <= 1.50",
            "volume",
            ("volume_ratio_vs_lookback",),
            lambda item: Decimal("0.80") <= (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("-999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "OI_Z_LE_1_80",
            "OI belum terlalu spike",
            "oi_zscore <= 1.80",
            "open_interest",
            ("oi_zscore",),
            lambda item: (_evidence_value(item, "oi_zscore") or Decimal("999")) <= Decimal("1.80"),
        ),
        FilterStudySpec(
            "OI_CHANGE_LE_0_50",
            "OI change tidak ekstrem",
            "oi_change_pct <= 0.50",
            "open_interest",
            ("oi_change_pct",),
            lambda item: (_evidence_value(item, "oi_change_pct") or Decimal("999")) <= Decimal("0.50"),
        ),
        FilterStudySpec(
            "ATR_EXTENSION_LE_0_90",
            "ATR extension rendah",
            "atr_extension_normalized <= 0.90",
            "extension",
            ("atr_extension_normalized",),
            lambda item: (_evidence_value(item, "atr_extension_normalized") or Decimal("999")) <= Decimal("0.90"),
        ),
        FilterStudySpec(
            "PRICE_ATR_LE_1_25",
            "Price/ATR tidak terlalu jauh",
            "price_atr_multiple <= 1.25",
            "extension",
            ("price_atr_multiple",),
            lambda item: (_evidence_value(item, "price_atr_multiple") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "SPOT_SPREAD_LE_0_03",
            "Spot spread rendah",
            "spot_spread_pct <= 0.03",
            "spread",
            ("spot_spread_pct",),
            lambda item: (_evidence_value(item, "spot_spread_pct") or Decimal("999")) <= Decimal("0.03"),
        ),
        FilterStudySpec(
            "FUTURES_SPREAD_LE_0_03",
            "Futures spread rendah",
            "futures_spread_pct <= 0.03",
            "spread",
            ("futures_spread_pct",),
            lambda item: (_evidence_value(item, "futures_spread_pct") or Decimal("999")) <= Decimal("0.03"),
        ),
        FilterStudySpec(
            "FUNDING_GE_75_AND_GLOBAL_LS_GE_1_20",
            "Funding tinggi + global L/S crowded",
            "funding_percentile_30d >= 75 AND global_long_short_ratio >= 1.20",
            "combo",
            ("funding_percentile_30d", "global_long_short_ratio"),
            lambda item: (_evidence_value(item, "funding_percentile_30d") or Decimal("-999")) >= Decimal("75")
            and (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "FUNDING_GE_75_AND_VOLUME_LE_1_50",
            "Funding tinggi + volume tidak ekstrem",
            "funding_percentile_30d >= 75 AND volume_ratio_vs_lookback <= 1.50",
            "combo",
            ("funding_percentile_30d", "volume_ratio_vs_lookback"),
            lambda item: (_evidence_value(item, "funding_percentile_30d") or Decimal("-999")) >= Decimal("75")
            and (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "GLOBAL_LS_GE_1_20_AND_VOLUME_LE_1_50",
            "Global L/S crowded + volume tidak ekstrem",
            "global_long_short_ratio >= 1.20 AND volume_ratio_vs_lookback <= 1.50",
            "combo",
            ("global_long_short_ratio", "volume_ratio_vs_lookback"),
            lambda item: (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20")
            and (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "VOLUME_LE_1_50_AND_OI_Z_LE_1_80",
            "Volume tidak ekstrem + OI z-score terkendali",
            "volume_ratio_vs_lookback <= 1.50 AND oi_zscore <= 1.80",
            "combo",
            ("volume_ratio_vs_lookback", "oi_zscore"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "oi_zscore") or Decimal("999")) <= Decimal("1.80"),
        ),
        FilterStudySpec(
            "ATR_EXTENSION_LE_0_90_AND_VOLUME_LE_1_50",
            "ATR extension rendah + volume tidak ekstrem",
            "atr_extension_normalized <= 0.90 AND volume_ratio_vs_lookback <= 1.50",
            "combo",
            ("atr_extension_normalized", "volume_ratio_vs_lookback"),
            lambda item: (_evidence_value(item, "atr_extension_normalized") or Decimal("999")) <= Decimal("0.90")
            and (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "FUNDING_VOLUME_SPOTSPREAD",
            "Funding tinggi + volume terkendali + spot spread rendah",
            "funding_percentile_30d >= 75 AND volume_ratio_vs_lookback <= 1.50 AND spot_spread_pct <= 0.03",
            "combo",
            ("funding_percentile_30d", "volume_ratio_vs_lookback", "spot_spread_pct"),
            lambda item: (_evidence_value(item, "funding_percentile_30d") or Decimal("-999")) >= Decimal("75")
            and (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "spot_spread_pct") or Decimal("999")) <= Decimal("0.03"),
        ),
    ]


def _filter_study_row(
    *,
    filter_id: str,
    label: str,
    expression: str,
    family: str,
    items: list[dict[str, Any]],
    source_count: int,
    missing_data_count: int,
    required_fields: tuple[str, ...],
    baseline_perf: dict[str, Any] | None,
    min_sample: int,
) -> dict[str, Any]:
    perf = _performance_summary(items)
    closed = [item for item in items if item["result_status"] in COMPLETED_OUTCOMES and item.get("realized_r") is not None]
    realized_values = [Decimal(item["realized_r"]) for item in closed]
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    top_symbol, top_symbol_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    drawdown = _drawdown_summary(items, point_limit=1)
    winrate = perf["winrate_pct"]
    sl_share = _sl_share(perf)
    avg_r = perf["avg_r_closed"]
    baseline_avg = baseline_perf.get("avg_r_closed") if baseline_perf else None
    baseline_winrate = baseline_perf.get("winrate_pct") if baseline_perf else None
    baseline_sl_share = baseline_perf.get("sl_share_pct") if baseline_perf else None
    row = {
        "filter_id": filter_id,
        "label": label,
        "expression": expression,
        "family": family,
        "required_fields": list(required_fields),
        "source_count": source_count,
        "sample_count": len(items),
        "sample_retention_pct": (Decimal(len(items)) / Decimal(source_count) * Decimal("100")) if source_count else None,
        "missing_data_count": missing_data_count,
        "missing_data_pct": (Decimal(missing_data_count) / Decimal(source_count) * Decimal("100")) if source_count else None,
        "median_r_closed": _median_decimal(realized_values),
        "max_drawdown_r": drawdown["max_drawdown_r"],
        "top_symbol": top_symbol,
        "top_symbol_count": top_symbol_count,
        "top_symbol_share_pct": (Decimal(top_symbol_count) / Decimal(len(items)) * Decimal("100")) if items else None,
        "avg_r_delta_vs_baseline": (Decimal(avg_r) - Decimal(baseline_avg)) if avg_r is not None and baseline_avg is not None else None,
        "winrate_delta_vs_baseline": (Decimal(winrate) - Decimal(baseline_winrate)) if winrate is not None and baseline_winrate is not None else None,
        "sl_share_pct": sl_share,
        "sl_share_delta_vs_baseline": (Decimal(sl_share) - Decimal(baseline_sl_share)) if sl_share is not None and baseline_sl_share is not None else None,
        **perf,
    }
    row["verdict"] = _filter_study_verdict(row, min_sample=min_sample)
    row["note"] = _filter_study_note(row)
    return row


def _sort_filter_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    verdict_rank = {
        "PROMISING_FILTER": 4,
        "REDUCES_DAMAGE": 3,
        "NOISY_FILTER": 2,
        "WORSE_THAN_BASELINE": 1,
        "SAMPLE_TOO_SMALL": 0,
    }
    return sorted(
        rows,
        key=lambda row: (
            verdict_rank.get(str(row.get("verdict")), -1),
            Decimal(row["avg_r_delta_vs_baseline"]) if row.get("avg_r_delta_vs_baseline") is not None else Decimal("-999"),
            Decimal(row["total_r_closed"]),
            row["sample_count"],
        ),
        reverse=True,
    )


def _calibration_lane(
    *,
    stage: str,
    timeframe: str,
    items: list[dict[str, Any]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    sorted_items = sorted(
        items,
        key=lambda item: (_parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol"))),
    )
    if len(sorted_items) >= 2:
        split_index = max(1, min(len(sorted_items) - 1, int(Decimal(len(sorted_items)) * Decimal("0.70"))))
    else:
        split_index = len(sorted_items)
    train_items = sorted_items[:split_index]
    validation_items = sorted_items[split_index:]
    baseline_all = _calibration_perf(sorted_items)
    baseline_train = _calibration_perf(train_items)
    baseline_validation = _calibration_perf(validation_items)
    candidates = [
        _calibration_candidate(
            spec=spec,
            all_items=sorted_items,
            train_items=train_items,
            validation_items=validation_items,
            baseline_all=baseline_all,
            baseline_train=baseline_train,
            baseline_validation=baseline_validation,
            min_sample=min_sample,
        )
        for spec in _filter_study_specs()
    ]
    candidates.sort(key=_calibration_candidate_sort_key, reverse=True)
    return {
        "lane": f"{stage}_{timeframe}",
        "stage": stage,
        "timeframe": timeframe,
        "sample_count": len(sorted_items),
        "train_count": len(train_items),
        "validation_count": len(validation_items),
        "split_method": "chronological_70_30",
        "status": _calibration_lane_status(baseline_train, baseline_validation, min_sample=min_sample),
        "baseline_all": baseline_all,
        "baseline_train": baseline_train,
        "baseline_validation": baseline_validation,
        "filter_candidates": candidates[:limit],
    }


def _calibration_candidate(
    *,
    spec: FilterStudySpec,
    all_items: list[dict[str, Any]],
    train_items: list[dict[str, Any]],
    validation_items: list[dict[str, Any]],
    baseline_all: dict[str, Any],
    baseline_train: dict[str, Any],
    baseline_validation: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    all_selected, all_missing = _apply_filter_spec(all_items, spec)
    train_selected, train_missing = _apply_filter_spec(train_items, spec)
    validation_selected, validation_missing = _apply_filter_spec(validation_items, spec)
    train = _calibration_perf(train_selected, baseline=baseline_train)
    validation = _calibration_perf(validation_selected, baseline=baseline_validation)
    all_perf = _calibration_perf(all_selected, baseline=baseline_all)
    verdict = _calibration_verdict(train, validation, min_sample=min_sample)
    return {
        "filter_id": spec.filter_id,
        "label": spec.label,
        "expression": spec.expression,
        "family": spec.family,
        "required_fields": list(spec.required_fields),
        "missing_data": {
            "all": all_missing,
            "train": train_missing,
            "validation": validation_missing,
        },
        "all": all_perf,
        "train": train,
        "validation": validation,
        "verdict": verdict,
        "note": _calibration_note(verdict),
    }


def _apply_filter_spec(items: list[dict[str, Any]], spec: FilterStudySpec) -> tuple[list[dict[str, Any]], int]:
    passed: list[dict[str, Any]] = []
    missing = 0
    for item in items:
        evidence = item.get("evidence_snapshot") or {}
        if any(evidence.get(field) is None for field in spec.required_fields):
            missing += 1
            continue
        if spec.predicate(item):
            passed.append(item)
    return passed, missing


def _calibration_perf(items: list[dict[str, Any]], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    perf = _performance_summary(items)
    closed = [item for item in items if item["result_status"] in COMPLETED_OUTCOMES and item.get("realized_r") is not None]
    realized_values = [Decimal(item["realized_r"]) for item in closed]
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    top_symbol, top_symbol_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    drawdown = _drawdown_summary(items, point_limit=1)
    row = {
        **perf,
        "sample_count": len(items),
        "median_r_closed": _median_decimal(realized_values),
        "max_drawdown_r": drawdown["max_drawdown_r"],
        "sl_share_pct": _sl_share(perf),
        "top_symbol": top_symbol,
        "top_symbol_count": top_symbol_count,
        "top_symbol_share_pct": (Decimal(top_symbol_count) / Decimal(len(items)) * Decimal("100")) if items else None,
    }
    if baseline is not None:
        row.update(
            {
                "sample_delta_vs_baseline": int(row["sample_count"]) - int(baseline.get("sample_count") or 0),
                "avg_r_delta_vs_baseline": _decimal_delta(row.get("avg_r_closed"), baseline.get("avg_r_closed")),
                "total_r_delta_vs_baseline": _decimal_delta(row.get("total_r_closed"), baseline.get("total_r_closed")),
                "winrate_delta_vs_baseline": _decimal_delta(row.get("winrate_pct"), baseline.get("winrate_pct")),
                "sl_share_delta_vs_baseline": _decimal_delta(row.get("sl_share_pct"), baseline.get("sl_share_pct")),
                "max_drawdown_delta_vs_baseline": _decimal_delta(row.get("max_drawdown_r"), baseline.get("max_drawdown_r")),
            }
        )
    return row


def _decimal_delta(value: Any, baseline: Any) -> Decimal | None:
    if value is None or baseline is None:
        return None
    return Decimal(value) - Decimal(baseline)


def _calibration_lane_status(train: dict[str, Any], validation: dict[str, Any], *, min_sample: int) -> str:
    if int(train["closed_count"]) < min_sample:
        return "TRAIN_SAMPLE_TOO_SMALL"
    if int(validation["closed_count"]) < min_sample:
        return "VALIDATION_SAMPLE_TOO_SMALL"
    return "READY_FOR_CALIBRATION"


def _calibration_verdict(train: dict[str, Any], validation: dict[str, Any], *, min_sample: int) -> str:
    if int(train["closed_count"]) < min_sample or int(validation["closed_count"]) < min_sample:
        return "NEED_MORE_SAMPLE"
    train_good = _calibration_is_good(train)
    validation_good = _calibration_is_good(validation)
    validation_reduces_damage = _calibration_reduces_damage(validation)
    if train_good and validation_good:
        return "VALIDATION_PROMISING"
    if train_good and not validation_good:
        return "TRAIN_ONLY_OVERFIT"
    if validation_reduces_damage:
        return "REDUCES_DAMAGE"
    if validation.get("avg_r_delta_vs_baseline") is not None and Decimal(validation["avg_r_delta_vs_baseline"]) < 0:
        return "VALIDATION_WORSE"
    return "NO_CLEAR_EDGE"


def _calibration_is_good(row: dict[str, Any]) -> bool:
    avg_delta = row.get("avg_r_delta_vs_baseline")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    top_share = row.get("top_symbol_share_pct")
    concentration_ok = (
        int(row.get("sample_count") or 0) < 10
        or top_share is None
        or Decimal(top_share) <= Decimal("35")
    )
    return (
        avg_delta is not None
        and Decimal(avg_delta) >= Decimal("0.05")
        and Decimal(row["total_r_closed"]) > 0
        and (sl_delta is None or Decimal(sl_delta) <= 0)
        and concentration_ok
    )


def _calibration_reduces_damage(row: dict[str, Any]) -> bool:
    avg_delta = row.get("avg_r_delta_vs_baseline")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    return (
        (avg_delta is not None and Decimal(avg_delta) > 0)
        or (sl_delta is not None and Decimal(sl_delta) < 0)
    )


def _calibration_note(verdict: str) -> str:
    if verdict == "VALIDATION_PROMISING":
        return "Filter membaik di train dan tetap membaik di validation. Kandidat riset, belum rule produksi."
    if verdict == "TRAIN_ONLY_OVERFIT":
        return "Bagus di train tapi tidak bertahan di validation. Jangan dipromosikan."
    if verdict == "REDUCES_DAMAGE":
        return "Ada tanda mengurangi kerusakan, tapi belum cukup kuat."
    if verdict == "VALIDATION_WORSE":
        return "Validation lebih buruk dari baseline."
    if verdict == "NEED_MORE_SAMPLE":
        return "Train/validation belum punya closed sample cukup."
    return "Belum ada edge separation yang jelas."


def _calibration_candidate_sort_key(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, int]:
    verdict_rank = {
        "VALIDATION_PROMISING": 5,
        "REDUCES_DAMAGE": 4,
        "NO_CLEAR_EDGE": 3,
        "TRAIN_ONLY_OVERFIT": 2,
        "VALIDATION_WORSE": 1,
        "NEED_MORE_SAMPLE": 0,
    }
    validation = row.get("validation", {})
    avg_delta = validation.get("avg_r_delta_vs_baseline")
    total_r = validation.get("total_r_closed")
    closed_count = int(validation.get("closed_count") or 0)
    return (
        verdict_rank.get(str(row.get("verdict")), -1),
        Decimal(avg_delta) if avg_delta is not None else Decimal("-999"),
        Decimal(total_r) if total_r is not None else Decimal("-999"),
        closed_count,
    )


def _filter_study_verdict(row: dict[str, Any], *, min_sample: int) -> str:
    if int(row["sample_count"]) < min_sample or int(row["closed_count"]) < min_sample:
        return "SAMPLE_TOO_SMALL"
    avg_delta = row.get("avg_r_delta_vs_baseline")
    win_delta = row.get("winrate_delta_vs_baseline")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    total_r = Decimal(row["total_r_closed"])
    top_share = row.get("top_symbol_share_pct")
    if (
        avg_delta is not None
        and Decimal(avg_delta) >= Decimal("0.10")
        and win_delta is not None
        and Decimal(win_delta) >= Decimal("3")
        and total_r > 0
        and (top_share is None or Decimal(top_share) <= Decimal("25"))
    ):
        return "PROMISING_FILTER"
    if avg_delta is not None and Decimal(avg_delta) > 0 and sl_delta is not None and Decimal(sl_delta) < 0:
        return "REDUCES_DAMAGE"
    if avg_delta is not None and Decimal(avg_delta) < 0:
        return "WORSE_THAN_BASELINE"
    return "NOISY_FILTER"


def _filter_study_note(row: dict[str, Any]) -> str:
    verdict = str(row.get("verdict") or "")
    if verdict == "PROMISING_FILTER":
        return "Filter memperbaiki avg R dan winrate dibanding baseline, tetap perlu forward validation."
    if verdict == "REDUCES_DAMAGE":
        return "Filter menurunkan sisi rugi atau memperbaiki avg R, tapi belum cukup kuat jadi rule."
    if verdict == "WORSE_THAN_BASELINE":
        return "Filter lebih buruk dari baseline saat ini."
    if verdict == "SAMPLE_TOO_SMALL":
        return "Sample belum cukup untuk disimpulkan."
    return "Belum ada separation yang bersih."


def _evidence_value(item: dict[str, Any], field: str) -> Decimal | None:
    value = (item.get("evidence_snapshot") or {}).get(field)
    return Decimal(value) if value is not None else None


def _sl_share(perf: dict[str, Any]) -> Decimal | None:
    tp_count = int(perf["tp_count"])
    sl_count = int(perf["sl_count"])
    denominator = tp_count + sl_count
    if denominator <= 0:
        return None
    return Decimal(sl_count) / Decimal(denominator) * Decimal("100")


def _quality_flag(
    *,
    sample_size: int,
    closed_count: int,
    total_r: Decimal,
    median_r: Decimal | None,
    winrate: Decimal | None,
    min_sample: int,
) -> str:
    if sample_size < min_sample or closed_count < min_sample:
        return "SAMPLE_TOO_SMALL"
    if total_r > 0 and median_r is not None and median_r > 0:
        return "QUALITY_POSITIVE"
    if total_r > 0 and winrate is not None and winrate >= Decimal("45"):
        return "TOTAL_R_POSITIVE_MEDIAN_WEAK"
    if total_r < 0 and median_r is not None and median_r < 0:
        return "QUALITY_WEAK"
    return "NOISY_MIXED"


def _median_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _drawdown_summary(items: list[dict[str, Any]], *, point_limit: int = 160) -> dict[str, Any]:
    closed = [
        item
        for item in items
        if item["result_status"] in COMPLETED_OUTCOMES and item.get("realized_r") is not None
    ]
    closed.sort(key=lambda item: (_parse_dt(item.get("result_time_utc")) or _parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol"))))

    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    points: list[dict[str, Any]] = []
    for item in closed:
        realized = Decimal(item["realized_r"])
        cumulative += realized
        peak = max(peak, cumulative)
        drawdown = cumulative - peak
        max_drawdown = min(max_drawdown, drawdown)
        points.append(
            {
                "signal_id": item.get("signal_id"),
                "symbol": item.get("symbol"),
                "stage": item.get("stage"),
                "timeframe": item.get("timeframe"),
                "result_status": item.get("result_status"),
                "result_time_utc": item.get("result_time_utc"),
                "result_time_wib": item.get("result_time_wib"),
                "realized_r": realized,
                "cumulative_r": cumulative,
                "drawdown_r": drawdown,
            }
        )

    return {
        "closed_count": len(closed),
        "total_r_closed": cumulative,
        "peak_r": peak,
        "max_drawdown_r": max_drawdown,
        "current_drawdown_r": cumulative - peak,
        "points": points[-point_limit:],
    }
