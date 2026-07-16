from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from time import monotonic
from typing import Any, Callable

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline1m, FuturesKline15m, MarketlabActiveUniverse, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import utcnow


COMPLETED_OUTCOMES = {"TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE"}
LIVE_STRATEGY_VERSION = "SIGNAL_FACTORY_V2_LIVE"
SHADOW_STRATEGY_VERSION = "SIGNAL_FACTORY_V3_SHADOW_CALIBRATION"
FORWARD_DATA_STALE_MINUTES = 30
REALISTIC_MODEL_VERSION = "REALISTIC_PAPER_EXECUTION_V1"
REALISTIC_FEE_MODEL = "BINANCE_USDS_M_FUTURES_VIP0_TAKER_TAKER"
REALISTIC_FEE_SOURCE = "Binance USDⓈ-M Futures regular user taker fee"
REALISTIC_BINANCE_FUTURES_MAKER_FEE_PCT_PER_SIDE = Decimal("0.02")
REALISTIC_BINANCE_FUTURES_TAKER_FEE_PCT_PER_SIDE = Decimal("0.05")
REALISTIC_FEE_PCT_PER_SIDE = REALISTIC_BINANCE_FUTURES_TAKER_FEE_PCT_PER_SIDE
REALISTIC_SLIPPAGE_PCT_PER_SIDE = Decimal("0.02")
REALISTIC_FILL_GOOD_MAX_COST_R = Decimal("0.15")
REALISTIC_FILL_ACCEPTABLE_MAX_COST_R = Decimal("0.35")
QUALITY_LAB_CACHE_TTL_SECONDS = 120
_QUALITY_LAB_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
MID_SHORT_1H_QUALITY_SHADOW_FILTER_ID = "MID_SHORT_1H_FILL_GOOD_RANGE_OK"
MID_SHORT_1H_QUALITY_SHADOW_FILTER_LABEL = "MID_SHORT 1h fill good + range/ATR <= 1.25"
MID_SHORT_1H_QUALITY_SHADOW_FILTER_EXPRESSION = (
    "stage == MID_SHORT AND timeframe == 1h AND realistic_fill_quality == FILL_GOOD "
    "AND range_ratio_vs_atr <= 1.25"
)
MID_SHORT_1H_QUALITY_RANGE_ATR_MAX = Decimal("1.25")

EVIDENCE_FIELDS = [
    ("price_return", "Price return %"),
    ("close_position_in_range", "Close position"),
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
    ("one_hour_return_pct", "Logged 1h return %"),
    ("spot_futures_volume_ratio", "Spot / futures volume"),
    ("body_pct", "Body %"),
    ("upper_wick_pct", "Upper wick %"),
    ("lower_wick_pct", "Lower wick %"),
    ("core_score", "Core score"),
    ("evidence_score", "Evidence score"),
    ("evidence_data_completeness", "Evidence completeness"),
]


@dataclass(frozen=True)
class PerfCandle:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    source_interval: str = "15m"


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
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
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
        latest_candle_time = max(
            (candle.close_time for rows in candles.values() for candle in rows),
            default=None,
        )
        global_latest_candle_time = self._global_latest_candle_time()
        item = self._evaluate_signal(
            signal,
            candles.get(signal.symbol, []),
            [candle.open_time for candle in candles.get(signal.symbol, [])],
            global_latest_candle_time=global_latest_candle_time or latest_candle_time,
        )
        item.update(
            _v3_shadow_result_for_item(
                item,
                self.v3_shadow_filter_map(
                    epoch=epoch,
                    include_watch_only=include_watch_only,
                    position_lock=True,
                    min_sample=5,
                    limit=100,
                ),
            )
        )
        chart_start_time = signal_time - timedelta(hours=24)
        chart_result_time = _parse_dt(item.get("result_time_utc"))
        chart_end_time = chart_result_time + timedelta(hours=2) if chart_result_time else None
        chart_base_candles = self._load_15m_candles(
            symbols,
            start_time=chart_start_time,
            end_time=chart_end_time,
        )
        latest_chart_base_time = max(
            (candle.close_time for rows in chart_base_candles.values() for candle in rows),
            default=None,
        )
        chart_tail_candles = self._load_1m_candles(
            symbols,
            start_time=latest_chart_base_time or chart_start_time,
            end_time=chart_end_time,
        )
        chart_candles = _merge_candle_maps(chart_base_candles, chart_tail_candles).get(signal.symbol, [])
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
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
                "strategy_version": _signal_strategy_version(signal),
                "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
                "v3_shadow_status": item.get("v3_shadow_status"),
                "v3_shadow_filter_id": item.get("v3_shadow_filter_id"),
                "v3_shadow_filter_label": item.get("v3_shadow_filter_label"),
                "source_artifact_generated_at": signal.source_artifact_generated_at,
                "observation_epoch": signal.observation_epoch,
                "created_at": signal.created_at,
                "updated_at": signal.updated_at,
            },
            "chart": _signal_chart_payload(signal, item, chart_candles),
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
        cache_key = (
            id(self.db.get_bind()),
            epoch,
            include_watch_only,
            position_lock,
            stage,
            timeframe,
            int(min_sample),
            int(limit),
        )
        cached = _quality_lab_cache_get(cache_key)
        if cached is not None:
            return cached

        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            symbol=None,
            position_lock=position_lock,
            with_shadow=False,
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

        payload = {
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
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "evaluation_candle_interval": "15m_closed_plus_1m_tail",
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "aggregate": aggregate,
            "drawdown": _drawdown_summary(evaluated),
            "by_stage": _bucket_rows(evaluated, key="stage", min_sample=min_sample),
            "by_confidence": _bucket_rows(evaluated, key="confidence_tier", min_sample=min_sample),
            "by_timeframe": _bucket_rows(evaluated, key="timeframe", min_sample=min_sample),
            "by_volume_rank": _volume_rank_rows(evaluated, min_sample=min_sample),
            "evidence_fields": _evidence_field_rows(evaluated, min_sample=min_sample),
            "profit_loss_research": _v2_profit_loss_research(evaluated, min_sample=min_sample, limit=limit),
            "mid_short_1h_refinement": _v2_mid_short_1h_refinement(evaluated, min_sample=min_sample, limit=limit),
            "top_symbols": _bucket_rows(evaluated, key="symbol", min_sample=min_sample, limit=limit, reverse=True),
            "weak_symbols": _bucket_rows(evaluated, key="symbol", min_sample=min_sample, limit=limit, reverse=False),
            "best_signals": best,
            "worst_signals": worst,
            "open_signals": open_items,
        }
        _quality_lab_cache_set(cache_key, payload)
        return payload

    def mid_short_1h_shadow_forward_log(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        result_status: str | None = None,
        limit: int = 100,
        min_sample: int = 20,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage="MID_SHORT",
            timeframe="1h",
            symbol=None,
            position_lock=position_lock,
            with_shadow=False,
        )
        evaluated = _filter_by_result_status(evaluated, result_status)
        baseline = _walk_forward_perf(evaluated)
        pass_items = [item for item in evaluated if item.get("quality_shadow_status") == "SHADOW_PASS"]
        fail_items = [item for item in evaluated if item.get("quality_shadow_status") == "SHADOW_FAIL"]
        unavailable_items = [item for item in evaluated if item.get("quality_shadow_status") == "SHADOW_UNAVAILABLE"]
        not_applicable_items = [
            item for item in evaluated if item.get("quality_shadow_status") == "SHADOW_NOT_APPLICABLE"
        ]
        pass_perf = _walk_forward_perf(pass_items)
        fail_perf = _walk_forward_perf(fail_items)
        by_status = _quality_shadow_status_rows(
            {
                "SHADOW_PASS": pass_items,
                "SHADOW_FAIL": fail_items,
                "SHADOW_UNAVAILABLE": unavailable_items,
                "SHADOW_NOT_APPLICABLE": not_applicable_items,
            },
            baseline=baseline,
            min_sample=min_sample,
        )
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": "MID_SHORT",
                "timeframe": "1h",
                "result_status": result_status,
                "limit": limit,
                "min_sample": min_sample,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_shadow_forward_log",
            "study_scope": "read_only_mid_short_1h_quality_shadow_forward_monitor",
            "source_table": "signal_forward_return_logs",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "shadow_filter": {
                "filter_id": MID_SHORT_1H_QUALITY_SHADOW_FILTER_ID,
                "label": MID_SHORT_1H_QUALITY_SHADOW_FILTER_LABEL,
                "expression": MID_SHORT_1H_QUALITY_SHADOW_FILTER_EXPRESSION,
                "range_atr_max": MID_SHORT_1H_QUALITY_RANGE_ATR_MAX,
                "status_meaning": "SHADOW_PASS means this logged MID_SHORT 1h signal matched the read-only quality gate.",
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "source_count": len(evaluated),
                "pass_count": len(pass_items),
                "fail_count": len(fail_items),
                "unavailable_count": len(unavailable_items),
                "not_applicable_count": len(not_applicable_items),
                "pass_retention_pct": _retention(len(pass_items), len(evaluated)),
                "fail_retention_pct": _retention(len(fail_items), len(evaluated)),
                "realistic_total_r_delta_pass_vs_fail": _decimal_delta(
                    pass_perf.get("realistic_total_r_closed"),
                    fail_perf.get("realistic_total_r_closed"),
                ),
                "realistic_avg_r_delta_pass_vs_fail": _decimal_delta(
                    pass_perf.get("realistic_avg_r_closed"),
                    fail_perf.get("realistic_avg_r_closed"),
                ),
                "read": _quality_shadow_forward_read(
                    baseline=baseline,
                    pass_perf=pass_perf,
                    fail_perf=fail_perf,
                    min_sample=min_sample,
                ),
            },
            "baseline": baseline,
            "by_shadow_status": by_status,
            "latest_pass_signals": _sorted_signal_rows(pass_items, limit=limit),
            "latest_fail_signals": _sorted_signal_rows(fail_items, limit=limit),
            "latest_unavailable_signals": _sorted_signal_rows(unavailable_items, limit=limit),
            "items": _sorted_signal_rows(evaluated, limit=limit),
            "guardrails": [
                "Shadow Forward Log is derived from logged Signal Factory V2 signals.",
                "SHADOW_PASS is research-only and does not change the live scanner decision.",
                "Signal Factory rules, TP/SL formula, outcome logic, and execution stay unchanged.",
                "Use this page to observe whether MID_SHORT 1h quality filtering keeps improving forward results.",
            ],
        }

    def mid_short_1h_failure_anatomy(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        shadow_status: str = "SHADOW_PASS",
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status = self._mid_short_1h_anatomy_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            shadow_status=shadow_status,
        )
        baseline = _walk_forward_perf(annotated)
        closed = [item for item in annotated if item.get("result_status") in COMPLETED_OUTCOMES]
        tp_items = [item for item in closed if item.get("result_status") == "TP_HIT"]
        sl_items = [item for item in closed if item.get("result_status") == "SL_HIT"]
        both_items = [item for item in closed if item.get("result_status") == "BOTH_HIT_SAME_CANDLE"]
        improvement_candidates = _mid_short_failure_improvement_candidates(
            annotated,
            baseline=baseline,
            min_sample=min_sample,
            limit=limit,
        )
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": "MID_SHORT",
                "timeframe": "1h",
                "shadow_status": normalized_shadow_status,
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_failure_anatomy",
            "study_scope": "read_only_mid_short_1h_failure_anatomy",
            "source_table": "signal_forward_return_logs",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "shadow_filter": {
                "filter_id": MID_SHORT_1H_QUALITY_SHADOW_FILTER_ID,
                "label": MID_SHORT_1H_QUALITY_SHADOW_FILTER_LABEL,
                "expression": MID_SHORT_1H_QUALITY_SHADOW_FILTER_EXPRESSION,
                "status_meaning": "Default scope is SHADOW_PASS, meaning logged V2 MID_SHORT 1h signals that matched the read-only quality gate.",
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "source_count": len(annotated),
                "closed_count": len(closed),
                "tp_count": len(tp_items),
                "sl_count": len(sl_items),
                "both_hit_count": len(both_items),
                "open_count": sum(1 for item in annotated if item.get("result_status") == "OPEN"),
                "sl_then_would_tp_count": sum(1 for item in sl_items if item.get("after_sl_would_hit_tp")),
                "tp_near_then_sl_count": sum(1 for item in sl_items if item.get("tp_near_before_sl")),
                "sl_direct_count": sum(1 for item in sl_items if item.get("path_type") == "SL_DIRECT"),
                "wrong_direction_1h_count": sum(1 for item in annotated if item.get("direction_1h") == "WRONG_DIRECTION"),
                "correct_direction_1h_count": sum(1 for item in annotated if item.get("direction_1h") == "CORRECT_DIRECTION"),
                "read": _mid_short_failure_summary_read(annotated, min_sample=min_sample),
            },
            "baseline": baseline,
            "mfe_mae_summary": _mid_short_mfe_mae_summary(annotated),
            "outcome_path_rows": _anatomy_bucket_rows(annotated, key="path_type", min_sample=min_sample, baseline=baseline),
            "direction_rows": _direction_correctness_rows(annotated, baseline=baseline, min_sample=min_sample),
            "regime_rows": _mid_short_regime_rows(annotated, baseline=baseline, min_sample=min_sample),
            "session_rows": _anatomy_bucket_rows(annotated, key="wib_session", min_sample=min_sample, baseline=baseline),
            "symbol_rows": _anatomy_bucket_rows(annotated, key="symbol", min_sample=1, baseline=baseline, limit=limit),
            "evidence_tp_vs_sl": _evidence_field_rows(closed, min_sample=max(3, min_sample // 2)),
            "improvement_candidates": improvement_candidates,
            "latest_sl_signals": _sorted_signal_rows(sl_items, limit=limit),
            "latest_tp_signals": _sorted_signal_rows(tp_items, limit=limit),
            "latest_open_signals": _sorted_signal_rows(
                [item for item in annotated if item.get("result_status") == "OPEN"],
                limit=limit,
            ),
            "guardrails": [
                "Failure anatomy only reads logged V2 MID_SHORT 1h signals and local futures candles.",
                "Path labels explain why TP/SL happened; they do not change Signal Factory rules.",
                "Improvement candidates are research-only filters, not live scanner rules.",
                "No TP/SL formula, execution, order, leverage, or position sizing is created.",
            ],
        }

    def mid_short_1h_second_filter_shadow(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        shadow_status: str = "SHADOW_PASS",
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status = self._mid_short_1h_anatomy_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            shadow_status=shadow_status,
        )
        baseline = _walk_forward_perf(annotated)
        filter_rows = _mid_short_second_filter_shadow_rows(
            annotated,
            baseline=baseline,
            min_sample=min_sample,
            limit=limit,
        )
        top_filter = filter_rows[0] if filter_rows else None
        top_items = _apply_named_second_filter(annotated, str(top_filter.get("filter_id"))) if top_filter else []
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": "MID_SHORT",
                "timeframe": "1h",
                "shadow_status": normalized_shadow_status,
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_second_filter_shadow",
            "study_scope": "read_only_mid_short_1h_second_filter_shadow",
            "source_table": "signal_forward_return_logs",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "shadow_filter": {
                "filter_id": MID_SHORT_1H_QUALITY_SHADOW_FILTER_ID,
                "label": MID_SHORT_1H_QUALITY_SHADOW_FILTER_LABEL,
                "expression": MID_SHORT_1H_QUALITY_SHADOW_FILTER_EXPRESSION,
                "status_meaning": "Second filters are evaluated inside the selected quality shadow scope, usually SHADOW_PASS.",
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "source_count": len(annotated),
                "baseline": baseline,
                "filter_count": len(filter_rows),
                "monitor_count": sum(1 for row in filter_rows if row.get("read") == "SECOND_FILTER_MONITOR"),
                "damage_reduction_count": sum(1 for row in filter_rows if row.get("read") == "SECOND_FILTER_REDUCES_DAMAGE"),
                "top_filter_id": top_filter.get("filter_id") if top_filter else None,
                "top_filter_label": top_filter.get("label") if top_filter else None,
                "read": _mid_short_second_filter_summary_read(filter_rows, min_sample=min_sample),
            },
            "filter_rows": filter_rows,
            "top_filter_items": _sorted_signal_rows(top_items, limit=limit),
            "baseline_path_rows": _anatomy_bucket_rows(annotated, key="path_type", min_sample=min_sample, baseline=baseline),
            "guardrails": [
                "Second filter shadow only reads logged V2 MID_SHORT 1h signals and local futures candles.",
                "SECOND_FILTER_MONITOR means research-only improvement candidate, not a live rule.",
                "Signal Factory rules, scanner behavior, TP/SL formula, outcome logic, and execution stay unchanged.",
                "Use this page to decide what should be forward-observed next, not to force promotion.",
            ],
        }

    def mid_short_1h_taker_sell_deep_dive(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status = self._mid_short_1h_anatomy_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            shadow_status="SHADOW_PASS",
        )
        taker_scope = _apply_named_second_filter(annotated, "TAKER_SELL_GE_52")
        baseline = _walk_forward_perf(taker_scope)
        filter_rows = _mid_short_taker_sell_deep_filter_rows(
            taker_scope,
            baseline=baseline,
            min_sample=min_sample,
            limit=limit,
        )
        top_filter = filter_rows[0] if filter_rows else None
        top_items = _apply_named_taker_sell_deep_filter(taker_scope, str(top_filter.get("filter_id"))) if top_filter else []
        closed = [item for item in taker_scope if item.get("result_status") in COMPLETED_OUTCOMES]
        sl_items = [item for item in closed if item.get("result_status") == "SL_HIT"]
        tp_items = [item for item in closed if item.get("result_status") == "TP_HIT"]
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": "MID_SHORT",
                "timeframe": "1h",
                "shadow_status": normalized_shadow_status,
                "base_filter_id": "TAKER_SELL_GE_52",
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_taker_sell_deep_dive",
            "study_scope": "read_only_mid_short_1h_taker_sell_ge_52_deep_dive",
            "source_table": "signal_forward_return_logs",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "base_filter": {
                "filter_id": "TAKER_SELL_GE_52",
                "label": "Taker sell >= 52%",
                "expression": "kline_taker_sell_ratio >= 0.52 inside MID_SHORT 1h SHADOW_PASS",
                "status_meaning": "Deep dive only studies signals that already pass the strongest second-filter candidate.",
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "source_shadow_pass_count": len(annotated),
                "scope_count": len(taker_scope),
                "closed_count": len(closed),
                "tp_count": len(tp_items),
                "sl_count": len(sl_items),
                "open_count": sum(1 for item in taker_scope if item.get("result_status") == "OPEN"),
                "sl_then_would_tp_count": sum(1 for item in sl_items if item.get("after_sl_would_hit_tp")),
                "tp_near_then_sl_count": sum(1 for item in sl_items if item.get("tp_near_before_sl")),
                "wrong_direction_1h_count": sum(1 for item in taker_scope if item.get("direction_1h") == "WRONG_DIRECTION"),
                "correct_direction_1h_count": sum(1 for item in taker_scope if item.get("direction_1h") == "CORRECT_DIRECTION"),
                "baseline": baseline,
                "filter_count": len(filter_rows),
                "promising_count": sum(1 for row in filter_rows if row.get("read") == "TAKER_DEEP_FILTER_PROMISING"),
                "damage_reduction_count": sum(1 for row in filter_rows if row.get("read") == "TAKER_DEEP_FILTER_REDUCES_DAMAGE"),
                "top_filter_id": top_filter.get("filter_id") if top_filter else None,
                "top_filter_label": top_filter.get("label") if top_filter else None,
                "read": _mid_short_taker_sell_deep_summary_read(filter_rows, min_sample=min_sample),
            },
            "filter_rows": filter_rows,
            "outcome_path_rows": _anatomy_bucket_rows(taker_scope, key="path_type", min_sample=min_sample, baseline=baseline),
            "direction_rows": _direction_correctness_rows(taker_scope, baseline=baseline, min_sample=min_sample),
            "regime_rows": _mid_short_regime_rows(taker_scope, baseline=baseline, min_sample=min_sample),
            "session_rows": _anatomy_bucket_rows(taker_scope, key="wib_session", min_sample=min_sample, baseline=baseline),
            "symbol_rows": _anatomy_bucket_rows(taker_scope, key="symbol", min_sample=1, baseline=baseline, limit=limit),
            "evidence_tp_vs_sl": _evidence_field_rows(closed, min_sample=max(3, min_sample // 2)),
            "top_filter_items": _sorted_signal_rows(top_items, limit=limit),
            "latest_sl_signals": _sorted_signal_rows(sl_items, limit=limit),
            "latest_tp_signals": _sorted_signal_rows(tp_items, limit=limit),
            "latest_open_signals": _sorted_signal_rows(
                [item for item in taker_scope if item.get("result_status") == "OPEN"],
                limit=limit,
            ),
            "guardrails": [
                "Taker Sell Deep Dive only reads logged V2 MID_SHORT 1h SHADOW_PASS signals with kline_taker_sell_ratio >= 0.52.",
                "Candidate filters are research-only and do not change Signal Factory rules or scanner behavior.",
                "TP/SL formula, outcome logic, execution, leverage, order placement, and position sizing stay unchanged.",
                "Promising filters must be forward-observed before any rule promotion discussion.",
            ],
        }

    def mid_short_1h_wrong_direction_deep_dive(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status = self._mid_short_1h_anatomy_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            shadow_status="SHADOW_PASS",
        )
        taker_scope = [
            _annotate_mid_short_wrong_direction(item)
            for item in _apply_named_second_filter(annotated, "TAKER_SELL_GE_52")
        ]
        baseline = _walk_forward_perf(taker_scope)
        wrong_items = [item for item in taker_scope if item.get("direction_1h") == "WRONG_DIRECTION"]
        correct_items = [item for item in taker_scope if item.get("direction_1h") == "CORRECT_DIRECTION"]
        neutral_items = [
            item
            for item in taker_scope
            if item.get("direction_1h") not in {"WRONG_DIRECTION", "CORRECT_DIRECTION"}
        ]
        filter_rows = _mid_short_wrong_direction_filter_rows(
            taker_scope,
            baseline=baseline,
            min_sample=min_sample,
            limit=limit,
        )
        top_filter = filter_rows[0] if filter_rows else None
        top_items = _apply_named_wrong_direction_filter(taker_scope, str(top_filter.get("filter_id"))) if top_filter else []
        direction_baseline = _mid_short_direction_summary(taker_scope)
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": "MID_SHORT",
                "timeframe": "1h",
                "shadow_status": normalized_shadow_status,
                "base_filter_id": "TAKER_SELL_GE_52",
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_wrong_direction_deep_dive",
            "study_scope": "read_only_mid_short_1h_taker_sell_wrong_direction_deep_dive",
            "source_table": "signal_forward_return_logs",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "base_filter": {
                "filter_id": "TAKER_SELL_GE_52",
                "label": "MID_SHORT 1h SHADOW_PASS + taker sell >= 52%",
                "expression": "stage == MID_SHORT AND timeframe == 1h AND SHADOW_PASS AND kline_taker_sell_ratio >= 0.52",
                "status_meaning": "Wrong-direction deep dive starts from the current strongest research subset and asks why some shorts still moved upward.",
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "source_shadow_pass_count": len(annotated),
                "scope_count": len(taker_scope),
                "closed_count": int(baseline.get("closed_count") or 0),
                "tp_count": int(baseline.get("tp_count") or 0),
                "sl_count": int(baseline.get("sl_count") or 0),
                "open_count": int(baseline.get("open_count") or 0),
                "wrong_direction_1h_count": len(wrong_items),
                "correct_direction_1h_count": len(correct_items),
                "neutral_direction_1h_count": len(neutral_items),
                "wrong_direction_1h_share_pct": direction_baseline.get("wrong_direction_1h_share_pct"),
                "correct_direction_1h_share_pct": direction_baseline.get("correct_direction_1h_share_pct"),
                "baseline": baseline,
                "wrong_direction_perf": _walk_forward_perf(wrong_items),
                "correct_direction_perf": _walk_forward_perf(correct_items),
                "filter_count": len(filter_rows),
                "promising_count": sum(1 for row in filter_rows if row.get("read") == "WRONG_DIR_FILTER_PROMISING"),
                "damage_reduction_count": sum(1 for row in filter_rows if row.get("read") == "WRONG_DIR_FILTER_REDUCES_DAMAGE"),
                "top_filter_id": top_filter.get("filter_id") if top_filter else None,
                "top_filter_label": top_filter.get("label") if top_filter else None,
                "read": _mid_short_wrong_direction_summary_read(filter_rows, min_sample=min_sample),
            },
            "wrong_direction_taxonomy_rows": _anatomy_bucket_rows(
                wrong_items,
                key="wrong_direction_type",
                min_sample=max(1, min_sample // 2),
                baseline=_walk_forward_perf(wrong_items),
                limit=limit,
            ),
            "followthrough_rows": _mid_short_wrong_direction_followthrough_rows(
                taker_scope,
                baseline=baseline,
                min_sample=max(1, min_sample // 2),
            ),
            "evidence_correct_vs_wrong": _direction_evidence_field_rows(
                correct_items,
                wrong_items,
                min_sample=max(3, min_sample // 2),
            ),
            "anti_wrong_direction_filter_rows": filter_rows,
            "regime_rows": _mid_short_regime_rows(taker_scope, baseline=baseline, min_sample=min_sample),
            "symbol_wrong_rows": _anatomy_bucket_rows(
                wrong_items,
                key="symbol",
                min_sample=1,
                baseline=_walk_forward_perf(wrong_items),
                limit=limit,
            ),
            "top_filter_items": _sorted_signal_rows(top_items, limit=limit),
            "latest_wrong_direction_signals": _sorted_signal_rows(wrong_items, limit=limit),
            "latest_correct_direction_signals": _sorted_signal_rows(correct_items, limit=limit),
            "guardrails": [
                "Wrong Direction Deep Dive only reads logged V2 MID_SHORT 1h SHADOW_PASS signals with taker sell >= 52%.",
                "Wrong direction means a SHORT signal had positive 1h forward return from the futures entry reference.",
                "Candidate filters are diagnostic only and do not change Signal Factory rules, scanner behavior, TP/SL formula, or execution.",
                "Future-return buckets explain historical path behavior and must not be used as live input.",
            ],
        }

    def mid_short_1h_volume_safe_shadow(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status = self._mid_short_1h_anatomy_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            shadow_status="SHADOW_PASS",
        )
        taker_scope = [
            _annotate_mid_short_wrong_direction(item)
            for item in _apply_named_second_filter(annotated, "TAKER_SELL_GE_52")
        ]
        spec = _filter_spec_by_id(_mid_short_wrong_direction_filter_specs(), "VOLUME_LE_1_50")
        pass_items, fail_items, missing_items = _split_filter_spec(taker_scope, spec)
        baseline = _walk_forward_perf(taker_scope)
        pass_perf = _walk_forward_perf(pass_items, baseline=baseline)
        fail_perf = _walk_forward_perf(fail_items, baseline=baseline)
        missing_perf = _walk_forward_perf(missing_items, baseline=baseline)
        status_rows = _mid_short_volume_safe_status_rows(
            pass_items=pass_items,
            fail_items=fail_items,
            missing_items=missing_items,
            baseline=baseline,
        )
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": "MID_SHORT",
                "timeframe": "1h",
                "shadow_status": normalized_shadow_status,
                "base_filter_id": "TAKER_SELL_GE_52",
                "shadow_filter_id": "MID_SHORT_1H_TAKER_SELL_VOLUME_SAFE",
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_volume_safe_shadow",
            "study_scope": "read_only_mid_short_1h_taker_sell_volume_safe_shadow",
            "source_table": "signal_forward_return_logs",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "base_filter": {
                "filter_id": "TAKER_SELL_GE_52",
                "label": "MID_SHORT 1h SHADOW_PASS + taker sell >= 52%",
                "expression": "stage == MID_SHORT AND timeframe == 1h AND SHADOW_PASS AND kline_taker_sell_ratio >= 0.52",
                "status_meaning": "This is the current research scope before the volume-safe shadow split.",
            },
            "shadow_filter": {
                "filter_id": "MID_SHORT_1H_TAKER_SELL_VOLUME_SAFE",
                "label": "Volume safe: volume <= 1.50x lookback",
                "expression": "volume_ratio_vs_lookback <= 1.50 inside MID_SHORT 1h + taker sell >= 52%",
                "status_meaning": "Signals passing this shadow filter are monitored as a candidate mitigation for wrong-direction shorts. This does not alter live scanner rules.",
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "scope_count": len(taker_scope),
                "pass_count": len(pass_items),
                "fail_count": len(fail_items),
                "missing_count": len(missing_items),
                "pass_retention_pct": _retention(len(pass_items), len(taker_scope)),
                "baseline": baseline,
                "pass": pass_perf,
                "fail": fail_perf,
                "missing": missing_perf,
                "pass_direction": _mid_short_direction_summary(pass_items, baseline=_mid_short_direction_summary(taker_scope)),
                "fail_direction": _mid_short_direction_summary(fail_items, baseline=_mid_short_direction_summary(taker_scope)),
                "read": _mid_short_volume_safe_read(
                    pass_perf,
                    fail_perf,
                    _mid_short_direction_summary(pass_items, baseline=_mid_short_direction_summary(taker_scope)),
                    min_sample=min_sample,
                ),
            },
            "status_rows": status_rows,
            "pass_taxonomy_rows": _anatomy_bucket_rows(
                pass_items,
                key="wrong_direction_type",
                min_sample=max(1, min_sample // 2),
                baseline=pass_perf,
                limit=limit,
            ),
            "fail_taxonomy_rows": _anatomy_bucket_rows(
                fail_items,
                key="wrong_direction_type",
                min_sample=max(1, min_sample // 2),
                baseline=fail_perf,
                limit=limit,
            ),
            "pass_evidence_tp_vs_sl": _evidence_field_rows(
                [item for item in pass_items if item.get("result_status") in COMPLETED_OUTCOMES],
                min_sample=max(3, min_sample // 2),
            ),
            "latest_pass_signals": _sorted_signal_rows(pass_items, limit=limit),
            "latest_fail_signals": _sorted_signal_rows(fail_items, limit=limit),
            "latest_missing_signals": _sorted_signal_rows(missing_items, limit=limit),
            "guardrails": [
                "Volume Safe Shadow is read-only and only compares existing logged V2 MID_SHORT 1h signals.",
                "PASS means volume_ratio_vs_lookback <= 1.50 inside the Taker Sell >= 52% research scope.",
                "FAIL means the signal is not removed from production; it only failed this research split.",
                "Signal Factory rules, scanner behavior, TP/SL formula, outcome logic, threshold, and execution stay unchanged.",
            ],
        }

    def mid_short_1h_filter_combination_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status = self._mid_short_1h_anatomy_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            shadow_status="SHADOW_PASS",
        )
        taker_scope = [
            _annotate_mid_short_wrong_direction(item)
            for item in _apply_named_second_filter(annotated, "TAKER_SELL_GE_52")
        ]
        baseline = _walk_forward_perf(taker_scope)
        baseline_direction = _mid_short_direction_summary(taker_scope)
        baseline_path = _mid_short_path_count_summary(taker_scope)
        rows = _mid_short_filter_combination_rows(
            taker_scope,
            baseline=baseline,
            baseline_direction=baseline_direction,
            baseline_path=baseline_path,
            min_sample=min_sample,
            limit=limit,
        )
        candidate_rows = [
            row
            for row in rows
            if row.get("read") in {"COMBO_SHADOW_CANDIDATE", "COMBO_REDUCES_DAMAGE"}
        ]
        top_candidate = candidate_rows[0] if candidate_rows else (rows[0] if rows else None)
        decision_panel = _mid_short_filter_combination_decision_panel(
            rows,
            baseline=baseline,
            baseline_direction=baseline_direction,
            min_sample=min_sample,
        )
        top_items: list[dict[str, Any]] = []
        top_fail_items: list[dict[str, Any]] = []
        top_missing_items: list[dict[str, Any]] = []
        if top_candidate is not None:
            spec = _filter_spec_by_id(_mid_short_filter_combination_specs(), str(top_candidate.get("filter_id")))
            top_items, top_fail_items, top_missing_items = _split_filter_spec(taker_scope, spec)

        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": "MID_SHORT",
                "timeframe": "1h",
                "shadow_status": normalized_shadow_status,
                "base_filter_id": "TAKER_SELL_GE_52",
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_filter_combination_study",
            "study_scope": "read_only_mid_short_1h_v2_1_filter_combination_study",
            "source_table": "signal_forward_return_logs",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "base_filter": {
                "filter_id": "TAKER_SELL_GE_52",
                "label": "MID_SHORT 1h SHADOW_PASS + taker sell >= 52%",
                "expression": "stage == MID_SHORT AND timeframe == 1h AND SHADOW_PASS AND kline_taker_sell_ratio >= 0.52",
                "status_meaning": "Combination Study starts from the current strongest MID_SHORT 1h research scope and asks which extra filters reduce SL/wrong-direction.",
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "scope_count": len(taker_scope),
                "closed_count": int(baseline.get("closed_count") or 0),
                "tp_count": int(baseline.get("tp_count") or 0),
                "sl_count": int(baseline.get("sl_count") or 0),
                "wrong_direction_1h_count": int(baseline_direction.get("wrong_direction_1h_count") or 0),
                "correct_direction_1h_count": int(baseline_direction.get("correct_direction_1h_count") or 0),
                "baseline": baseline,
                "baseline_direction": baseline_direction,
                "combo_count": len(rows),
                "shadow_candidate_count": sum(1 for row in rows if row.get("read") == "COMBO_SHADOW_CANDIDATE"),
                "damage_reduction_count": sum(1 for row in rows if row.get("read") == "COMBO_REDUCES_DAMAGE"),
                "reject_count": sum(1 for row in rows if row.get("read") == "COMBO_REJECT"),
                "top_filter_id": top_candidate.get("filter_id") if top_candidate else None,
                "top_filter_label": top_candidate.get("label") if top_candidate else None,
                "read": _mid_short_filter_combination_summary_read(rows, min_sample=min_sample),
            },
            "decision_panel": decision_panel,
            "combination_rows": rows,
            "candidate_rows": candidate_rows[:limit],
            "baseline_path_rows": _anatomy_bucket_rows(
                taker_scope,
                key="wrong_direction_type",
                min_sample=max(1, min_sample // 2),
                baseline=baseline,
                limit=limit,
            ),
            "top_filter": top_candidate,
            "top_filter_pass": _walk_forward_perf(top_items, baseline=baseline),
            "top_filter_fail": _walk_forward_perf(top_fail_items, baseline=baseline),
            "top_filter_missing": _walk_forward_perf(top_missing_items, baseline=baseline),
            "top_filter_pass_direction": _mid_short_direction_summary(top_items, baseline=baseline_direction),
            "top_filter_fail_direction": _mid_short_direction_summary(top_fail_items, baseline=baseline_direction),
            "top_filter_pass_taxonomy": _anatomy_bucket_rows(
                top_items,
                key="wrong_direction_type",
                min_sample=max(1, min_sample // 2),
                baseline=_walk_forward_perf(top_items),
                limit=limit,
            ),
            "top_filter_fail_taxonomy": _anatomy_bucket_rows(
                top_fail_items,
                key="wrong_direction_type",
                min_sample=max(1, min_sample // 2),
                baseline=_walk_forward_perf(top_fail_items),
                limit=limit,
            ),
            "top_filter_pass_signals": _sorted_signal_rows(top_items, limit=limit),
            "top_filter_fail_signals": _sorted_signal_rows(top_fail_items, limit=limit),
            "top_filter_missing_signals": _sorted_signal_rows(top_missing_items, limit=limit),
            "guardrails": [
                "Filter Combination Study is read-only and only compares existing logged V2 MID_SHORT 1h signals.",
                "Every row starts from MID_SHORT 1h SHADOW_PASS + taker sell >= 52%; combinations only add extra evidence gates.",
                "COMBO_SHADOW_CANDIDATE means worth monitoring as V2.1 shadow; it is not a live rule promotion.",
                "Signal Factory rules, scanner behavior, TP/SL formula, outcome logic, threshold, and execution stay unchanged.",
            ],
        }

    def misidentification_audit(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = False,
        timeframe: str = "1h",
        stages: tuple[str, ...] = ("MID_LONG", "MID_SHORT"),
        min_sample: int = 20,
        limit: int = 50,
        max_signals_per_stage: int = 120,
    ) -> dict[str, Any]:
        lanes: list[dict[str, Any]] = []
        latest_times: list[datetime] = []
        skipped_total: Counter[str] = Counter()
        for stage in stages:
            annotated, skipped, latest_candle_time = self._anatomy_dataset(
                epoch=epoch,
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                stage=stage,
                timeframe=timeframe,
                max_signals=max_signals_per_stage,
            )
            skipped_total.update(skipped)
            if latest_candle_time:
                latest_times.append(latest_candle_time)
            lanes.append(
                _misidentification_lane(
                    stage=stage,
                    timeframe=timeframe,
                    items=annotated,
                    min_sample=min_sample,
                    limit=limit,
                )
            )

        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "timeframe": timeframe,
                "stages": list(stages),
                "min_sample": min_sample,
                "limit": limit,
                "max_signals_per_stage": max_signals_per_stage,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "strategy_version": LIVE_STRATEGY_VERSION,
            "study_scope": "signal_misidentification_audit_read_only",
            "method": (
                "Classifies closed Signal losses using path anatomy, 1h forward direction, MFE/MAE, "
                "extension/fill evidence, and a conservative reverse-direction proxy. It does not change live rules."
            ),
            "latest_evaluation_candle_time": max(latest_times, default=None),
            "latest_futures_15m_close_time": max(latest_times, default=None),
            "skipped_by_position_lock": dict(skipped_total),
            "lanes": lanes,
            "summary": _misidentification_summary(lanes),
            "guardrails": [
                "No Signal Factory rule changed.",
                "No scanner behavior changed.",
                "No TP/SL formula or outcome calculation changed.",
                "Reverse analysis is a conservative proxy from the same paper-live path, not a new signal rule.",
                "A reverse candidate means worth researching, not permission to flip live direction.",
            ],
        }

    def _anatomy_dataset(
        self,
        *,
        epoch: str,
        include_watch_only: bool,
        position_lock: bool,
        stage: str,
        timeframe: str,
        max_signals: int,
    ) -> tuple[list[dict[str, Any]], Counter[str], datetime | None]:
        signals = self._load_signals(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            symbol=None,
            signal_id=None,
            limit_latest=max_signals,
        )
        min_signal_time = min((_naive(row.signal_timestamp) for row in signals), default=None)
        max_signal_time = max((_naive(row.signal_timestamp) for row in signals), default=None)
        source_symbols = {row.symbol for row in signals}
        candle_symbols = set(source_symbols) | {"BTCUSDT", "ETHUSDT"}
        candle_start = min_signal_time - timedelta(hours=5) if min_signal_time is not None else None
        candle_end = max_signal_time + timedelta(hours=4) if max_signal_time is not None else None
        base_candles = self._load_15m_candles(candle_symbols, start_time=candle_start, end_time=candle_end)
        latest_base_time = max(
            (candle.close_time for rows in base_candles.values() for candle in rows),
            default=None,
        )
        tail_start = latest_base_time or candle_start
        tail_candles = self._load_1m_candles(candle_symbols, start_time=tail_start, end_time=candle_end)
        candles = _merge_candle_maps(base_candles, tail_candles)
        latest_candle_time = max(
            (candle.close_time for rows in candles.values() for candle in rows),
            default=None,
        )
        evaluated, skipped = self._evaluate(
            signals,
            candles,
            position_lock=position_lock,
            global_latest_candle_time=self._global_latest_candle_time() or latest_candle_time,
        )
        self._apply_universe_context(evaluated, source_symbols)
        return _annotate_mid_short_failure_anatomy(evaluated, candles), skipped, latest_candle_time

    def _mid_short_1h_anatomy_dataset(
        self,
        *,
        epoch: str,
        include_watch_only: bool,
        position_lock: bool,
        shadow_status: str,
    ) -> tuple[list[dict[str, Any]], Counter[str], datetime | None, str]:
        signals = self._load_signals(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage="MID_SHORT",
            timeframe="1h",
            symbol=None,
            signal_id=None,
        )
        min_signal_time = min((_naive(row.signal_timestamp) for row in signals), default=None)
        source_symbols = {row.symbol for row in signals}
        candle_symbols = set(source_symbols) | {"BTCUSDT", "ETHUSDT"}
        candle_start = min_signal_time - timedelta(hours=5) if min_signal_time is not None else None
        base_candles = self._load_15m_candles(candle_symbols, start_time=candle_start)
        latest_base_time = max(
            (candle.close_time for rows in base_candles.values() for candle in rows),
            default=None,
        )
        tail_start = latest_base_time or candle_start
        tail_candles = self._load_1m_candles(candle_symbols, start_time=tail_start)
        candles = _merge_candle_maps(base_candles, tail_candles)
        latest_candle_time = max(
            (candle.close_time for rows in candles.values() for candle in rows),
            default=None,
        )
        evaluated, skipped = self._evaluate(
            signals,
            candles,
            position_lock=position_lock,
            global_latest_candle_time=self._global_latest_candle_time() or latest_candle_time,
        )
        self._apply_universe_context(evaluated, source_symbols)
        normalized_shadow_status = (shadow_status or "SHADOW_PASS").upper()
        if normalized_shadow_status != "ALL":
            evaluated = [
                item
                for item in evaluated
                if str(item.get("quality_shadow_status") or "").upper() == normalized_shadow_status
            ]
        return _annotate_mid_short_failure_anatomy(evaluated, candles), skipped, latest_candle_time, normalized_shadow_status

    def forward_integrity(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        stage: str | None = None,
        timeframe: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            symbol=None,
            position_lock=position_lock,
            with_shadow=False,
        )
        tracked_statuses = {"OPEN", "WAITING_DATA", "STALE_FORWARD_DATA"}
        tracked = [item for item in evaluated if item.get("result_status") in tracked_statuses]
        tracked = sorted(
            tracked,
            key=lambda item: (
                item.get("result_status") == "STALE_FORWARD_DATA",
                Decimal(item.get("freshness_gap_minutes") or item.get("stale_gap_minutes") or 0),
                item.get("signal_timestamp") or datetime.min,
            ),
            reverse=True,
        )
        status_counts = Counter(str(item.get("result_status")) for item in evaluated)
        stale_items = [item for item in tracked if item.get("result_status") == "STALE_FORWARD_DATA"]
        waiting_items = [item for item in tracked if item.get("result_status") == "WAITING_DATA"]
        fresh_open_items = [item for item in tracked if item.get("result_status") == "OPEN"]
        global_latest = max(
            (
                _parse_dt(item.get("global_latest_evaluation_candle_time"))
                for item in evaluated
                if item.get("global_latest_evaluation_candle_time")
            ),
            default=latest_candle_time,
        )
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": stage,
                "timeframe": timeframe,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "stale_after_minutes": FORWARD_DATA_STALE_MINUTES,
            "latest_evaluation_candle_time": latest_candle_time,
            "global_latest_evaluation_candle_time": global_latest,
            "global_latest_evaluation_candle_time_wib": _wib_string(global_latest),
            "summary": {
                "integrity_status": "STALE_FOUND" if stale_items else "WAITING_DATA" if waiting_items else "PASS",
                "signals_evaluated": len(evaluated),
                "signals_skipped": sum(skipped.values()),
                "fresh_open_count": len(fresh_open_items),
                "stale_forward_count": len(stale_items),
                "waiting_data_count": len(waiting_items),
                "active_or_pending_count": len(tracked),
                "closed_count": sum(status_counts.get(status, 0) for status in COMPLETED_OUTCOMES),
                "tp_count": status_counts.get("TP_HIT", 0),
                "sl_count": status_counts.get("SL_HIT", 0),
                "both_hit_count": status_counts.get("BOTH_HIT_SAME_CANDLE", 0),
                "status_counts": dict(status_counts),
                "skip_reasons": dict(skipped),
                "fresh_symbol_count": len({item.get("symbol") for item in fresh_open_items}),
                "stale_symbol_count": len({item.get("symbol") for item in stale_items}),
                "waiting_symbol_count": len({item.get("symbol") for item in waiting_items}),
            },
            "items": tracked[:limit],
            "stale_items": stale_items[:limit],
            "guardrails": [
                "This audit only checks local futures candle freshness and paper TP/SL state.",
                "OPEN is valid only when the symbol candle is close to the global latest futures candle.",
                "STALE_FORWARD_DATA means paper R is a last-known value and should not be trusted as live current R.",
                "This is read-only and does not create orders or execution instructions.",
            ],
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
            with_shadow=False,
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
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "study_scope": "read_only_filter_study",
            "evaluation_candle_interval": "15m_closed_plus_1m_tail",
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "baseline": baseline,
            "rows": rows,
        }

    def one_hour_filter_candidate_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 12,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=None,
            timeframe="1h",
            symbol=None,
            position_lock=position_lock,
            with_shadow=False,
        )
        return build_one_hour_filter_candidate_study_payload(
            evaluated=evaluated,
            skipped=skipped,
            latest_candle_time=latest_candle_time,
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=min_sample,
            limit=limit,
        )

    def one_hour_walk_forward_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 12,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=None,
            timeframe="1h",
            symbol=None,
            position_lock=position_lock,
            with_shadow=False,
        )
        return build_one_hour_walk_forward_payload(
            evaluated=evaluated,
            skipped=skipped,
            latest_candle_time=latest_candle_time,
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=min_sample,
            limit=limit,
        )

    def one_hour_v4_shadow_monitor(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 20,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=None,
            timeframe="1h",
            symbol=None,
            position_lock=position_lock,
            with_shadow=False,
        )
        return build_one_hour_v4_shadow_monitor_payload(
            evaluated=evaluated,
            skipped=skipped,
            latest_candle_time=latest_candle_time,
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=min_sample,
            limit=limit,
        )

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
            with_shadow=False,
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
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
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

    def v3_shadow_filter_map(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 5,
        limit: int = 100,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        evaluated, _skipped, _latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=None,
            timeframe=None,
            symbol=None,
            position_lock=position_lock,
            with_shadow=False,
        )
        return _v3_shadow_filter_map(evaluated, min_sample=min_sample, limit=limit)

    def v3_shadow_comparison(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        stage: str | None = None,
        timeframe: str | None = None,
        min_sample: int = 5,
        limit: int = 50,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            symbol=None,
            position_lock=position_lock,
            with_shadow=True,
        )
        v2 = _performance_summary(evaluated)
        pass_items = [item for item in evaluated if item.get("v3_shadow_status") == "V3_SHADOW_PASS"]
        fail_items = [item for item in evaluated if item.get("v3_shadow_status") == "V3_SHADOW_FAIL"]
        unavailable_items = [item for item in evaluated if item.get("v3_shadow_status") == "V3_SHADOW_UNAVAILABLE"]
        no_filter_items = [item for item in evaluated if item.get("v3_shadow_status") == "V3_SHADOW_NO_FILTER"]
        not_evaluated_items = [
            item
            for item in evaluated
            if item.get("v3_shadow_status")
            not in {"V3_SHADOW_PASS", "V3_SHADOW_FAIL", "V3_SHADOW_UNAVAILABLE", "V3_SHADOW_NO_FILTER"}
        ]
        v3_pass = _performance_summary(pass_items)
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
            "study_scope": "read_only_v3_shadow_comparison",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "v2_live": v2,
                "v3_shadow_pass": v3_pass,
                "v3_pass_count": len(pass_items),
                "v3_fail_count": len(fail_items),
                "v3_unavailable_count": len(unavailable_items),
                "v3_no_filter_count": len(no_filter_items),
                "v3_not_evaluated_count": len(not_evaluated_items),
                "sample_retention_pct": (Decimal(len(pass_items)) / Decimal(len(evaluated)) * Decimal("100")) if evaluated else None,
                "total_r_delta_v3_pass_vs_v2": _decimal_delta(v3_pass.get("total_r_closed"), v2.get("total_r_closed")),
                "avg_r_delta_v3_pass_vs_v2": _decimal_delta(v3_pass.get("avg_r_closed"), v2.get("avg_r_closed")),
                "winrate_delta_v3_pass_vs_v2": _decimal_delta(v3_pass.get("winrate_pct"), v2.get("winrate_pct")),
                "sl_share_delta_v3_pass_vs_v2": _decimal_delta(_sl_share(v3_pass), _sl_share(v2)),
                "read": _v3_comparison_read(v2, v3_pass, len(pass_items), min_sample=min_sample),
            },
            "by_v3_status": _v3_status_rows(
                {
                    "V3_SHADOW_PASS": pass_items,
                    "V3_SHADOW_FAIL": fail_items,
                    "V3_SHADOW_UNAVAILABLE": unavailable_items,
                    "V3_SHADOW_NO_FILTER": no_filter_items,
                    "V3_SHADOW_OTHER": not_evaluated_items,
                },
                baseline=v2,
                min_sample=min_sample,
            ),
            "by_lane": _v3_lane_rows(evaluated, min_sample=min_sample),
            "by_filter": _v3_filter_rows(pass_items, baseline=v2, min_sample=min_sample, limit=limit),
            "latest_pass_signals": _sorted_signal_rows(pass_items, limit=limit),
            "latest_fail_signals": _sorted_signal_rows(fail_items, limit=min(limit, 25)),
            "guardrails": [
                "Signal Factory V2 live rules are unchanged.",
                "V3 shadow filters are comparison-only and do not block or promote live signals.",
                "No TP/SL formula, outcome logic, scanner behavior, order, leverage, or execution is changed.",
            ],
        }

    def v3_shadow_forward_log(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        stage: str | None = None,
        timeframe: str | None = None,
        min_sample: int = 5,
        limit: int = 50,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            symbol=None,
            position_lock=position_lock,
            with_shadow=True,
        )
        v3_items = [item for item in evaluated if item.get("v3_shadow_status") == "V3_SHADOW_PASS"]
        v3_closed = [item for item in v3_items if item.get("result_status") in COMPLETED_OUTCOMES]
        v3_open = [item for item in v3_items if item.get("result_status") == "OPEN"]
        v2_summary = _forward_lane_summary(evaluated, min_sample=min_sample)
        v3_summary = _forward_lane_summary(v3_items, min_sample=min_sample)
        v2_perf = v2_summary["performance"]
        v3_perf = v3_summary["performance"]
        latest_v3_time = max((_parse_dt(item.get("signal_timestamp")) for item in v3_items), default=None)
        lane_rows = _v3_forward_lane_rows(evaluated, min_sample=min_sample)
        filter_rows = _v3_filter_rows(v3_items, baseline=v2_perf, min_sample=min_sample, limit=limit)
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
            "artifact_type": "v3_shadow_forward_log",
            "study_scope": "read_only_v3_shadow_forward_monitor",
            "source_table": "signal_forward_return_logs",
            "logging_model": "derived_shadow_lane_from_v2_signal_forward_log",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "latest_v3_signal_time": latest_v3_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "v2_live": v2_summary,
                "v3_shadow_signal": v3_summary,
                "v3_shadow_signal_count": len(v3_items),
                "v3_shadow_closed_count": len(v3_closed),
                "v3_shadow_open_count": len(v3_open),
                "v3_sample_retention_pct": _retention(len(v3_items), len(evaluated)),
                "total_r_delta_v3_vs_v2": _decimal_delta(v3_perf.get("total_r_closed"), v2_perf.get("total_r_closed")),
                "avg_r_delta_v3_vs_v2": _decimal_delta(v3_perf.get("avg_r_closed"), v2_perf.get("avg_r_closed")),
                "winrate_delta_v3_vs_v2": _decimal_delta(v3_perf.get("winrate_pct"), v2_perf.get("winrate_pct")),
                "max_drawdown_delta_v3_vs_v2": _decimal_delta(
                    v3_summary["drawdown"].get("max_drawdown_r"),
                    v2_summary["drawdown"].get("max_drawdown_r"),
                ),
                "read": _v3_forward_read(v2_summary, v3_summary, min_sample=min_sample),
            },
            "audit": _v3_forward_audit(
                v2_summary=v2_summary,
                v3_summary=v3_summary,
                lane_rows=lane_rows,
                filter_rows=filter_rows,
                min_sample=min_sample,
            ),
            "failure_analysis": _v3_failure_analysis(
                v2_items=evaluated,
                v3_items=v3_items,
                min_sample=min_sample,
                limit=limit,
            ),
            "higher_timeframe_quality_audit": _v3_higher_timeframe_quality_audit(
                v2_items=evaluated,
                v3_items=v3_items,
                min_sample=min_sample,
                limit=limit,
            ),
            "by_stage_timeframe": lane_rows,
            "by_filter": filter_rows,
            "latest_v3_open_signals": _sorted_signal_rows(v3_open, limit=limit),
            "latest_v3_closed_signals": _sorted_signal_rows(v3_closed, limit=limit),
            "latest_v3_signals": _sorted_signal_rows(v3_items, limit=limit),
            "guardrails": [
                "V3 Shadow Forward Log is derived from logged V2 Signal candidates.",
                "V3_SHADOW_SIGNAL means a V2 signal also passed the V3 shadow filter; it is not a live order.",
                "Signal Factory V2 rules, scanner behavior, TP/SL formula, and execution stay unchanged.",
                "Use this page for forward validation before any future promotion decision.",
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
        with_shadow: bool = True,
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
        latest_candle_time = max(
            (candle.close_time for rows in candles.values() for candle in rows),
            default=None,
        )
        global_latest_candle_time = self._global_latest_candle_time()
        evaluated, skipped = self._evaluate(
            signals,
            candles,
            position_lock=position_lock,
            global_latest_candle_time=global_latest_candle_time or latest_candle_time,
        )
        self._apply_universe_context(evaluated, symbols)
        if with_shadow:
            _apply_v3_shadow(evaluated, min_sample=5)
        return evaluated, skipped, latest_candle_time

    def _global_latest_candle_time(self) -> datetime | None:
        latest_15m = self.db.scalar(
            select(func.max(FuturesKline15m.close_time)).where(FuturesKline15m.aggregation_status == "AGG_READY")
        )
        latest_1m = self.db.scalar(select(func.max(FuturesKline1m.close_time)))
        values = [_naive(value) for value in (latest_15m, latest_1m) if value is not None]
        return max(values, default=None)

    def _apply_universe_context(self, items: list[dict[str, Any]], symbols: set[str]) -> None:
        if not items or not symbols:
            return
        rows = self.db.execute(
            select(
                MarketlabActiveUniverse.symbol,
                MarketlabActiveUniverse.rank,
                MarketlabActiveUniverse.quote_volume,
                MarketlabActiveUniverse.collection_tier,
                MarketlabActiveUniverse.is_active,
            ).where(MarketlabActiveUniverse.symbol.in_(symbols))
        ).all()
        universe_by_symbol = {
            row.symbol: {
                "universe_rank": row.rank,
                "universe_quote_volume": row.quote_volume,
                "collection_tier": row.collection_tier,
                "is_active": row.is_active,
            }
            for row in rows
        }
        for item in items:
            item.update(
                universe_by_symbol.get(
                    item.get("symbol"),
                    {
                        "universe_rank": None,
                        "universe_quote_volume": None,
                        "collection_tier": "UNKNOWN",
                        "is_active": None,
                    },
                )
            )

    def _load_signals(
        self,
        *,
        epoch: str,
        include_watch_only: bool,
        stage: str | None,
        timeframe: str | None,
        symbol: str | None = None,
        signal_id: str | None = None,
        limit_latest: int | None = None,
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
        if limit_latest is not None and limit_latest > 0:
            rows = list(
                self.db.scalars(
                    query.order_by(desc(SignalForwardReturnLog.signal_timestamp), desc(SignalForwardReturnLog.symbol)).limit(limit_latest)
                ).all()
            )
            return list(reversed(rows))
        return list(
            self.db.scalars(
                query.order_by(asc(SignalForwardReturnLog.signal_timestamp), asc(SignalForwardReturnLog.symbol))
            ).all()
        )

    def _load_15m_candles(
        self,
        symbols: set[str],
        *,
        start_time: datetime | None,
        end_time: datetime | None = None,
    ) -> dict[str, list[PerfCandle]]:
        if not symbols:
            return {}
        query = (
            select(
                FuturesKline15m.symbol,
                FuturesKline15m.open_time,
                FuturesKline15m.close_time,
                FuturesKline15m.open,
                FuturesKline15m.high,
                FuturesKline15m.low,
                FuturesKline15m.close,
                FuturesKline15m.volume,
            )
            .where(
                FuturesKline15m.symbol.in_(symbols),
                FuturesKline15m.aggregation_status == "AGG_READY",
            )
            .order_by(asc(FuturesKline15m.symbol), asc(FuturesKline15m.open_time))
        )
        if start_time is not None:
            query = query.where(FuturesKline15m.open_time >= start_time)
        if end_time is not None:
            query = query.where(FuturesKline15m.open_time <= end_time)
        rows = self.db.execute(query).all()
        output: dict[str, list[PerfCandle]] = defaultdict(list)
        for row in rows:
            output[row.symbol].append(
                PerfCandle(
                    open_time=_naive(row.open_time),
                    close_time=_naive(row.close_time),
                    open=Decimal(row.open),
                    high=Decimal(row.high),
                    low=Decimal(row.low),
                    close=Decimal(row.close),
                    volume=Decimal(row.volume) if row.volume is not None else None,
                    source_interval="15m",
                )
            )
        return dict(output)

    def _load_1m_candles(
        self,
        symbols: set[str],
        *,
        start_time: datetime | None,
        end_time: datetime | None = None,
    ) -> dict[str, list[PerfCandle]]:
        if not symbols or start_time is None:
            return {}
        query = (
            select(
                FuturesKline1m.symbol,
                FuturesKline1m.open_time,
                FuturesKline1m.close_time,
                FuturesKline1m.open_price,
                FuturesKline1m.high_price,
                FuturesKline1m.low_price,
                FuturesKline1m.close_price,
                FuturesKline1m.volume,
            )
            .where(
                FuturesKline1m.symbol.in_(symbols),
                FuturesKline1m.open_time >= start_time,
            )
            .order_by(asc(FuturesKline1m.symbol), asc(FuturesKline1m.open_time))
        )
        if end_time is not None:
            query = query.where(FuturesKline1m.open_time <= end_time)
        rows = self.db.execute(query).all()
        output: dict[str, list[PerfCandle]] = defaultdict(list)
        for row in rows:
            output[row.symbol].append(
                PerfCandle(
                    open_time=_naive(row.open_time),
                    close_time=_naive(row.close_time),
                    open=Decimal(row.open_price),
                    high=Decimal(row.high_price),
                    low=Decimal(row.low_price),
                    close=Decimal(row.close_price),
                    volume=Decimal(row.volume) if row.volume is not None else None,
                    source_interval="1m",
                )
            )
        return dict(output)

    def _evaluate(
        self,
        signals: list[SignalForwardReturnLog],
        candles: dict[str, list[PerfCandle]],
        *,
        position_lock: bool,
        global_latest_candle_time: datetime | None,
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
                global_latest_candle_time=global_latest_candle_time,
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
        *,
        global_latest_candle_time: datetime | None = None,
    ) -> dict[str, Any]:
        entry = Decimal(signal.price_at_signal)
        stop = Decimal(signal.sl_ref)
        target = Decimal(signal.tp_ref)
        risk = abs(entry - stop)
        signal_time = _naive(signal.signal_timestamp)
        direction = signal.direction
        position = bisect_left(open_times, signal_time)
        future = candles[position:]
        evidence_snapshot = _evidence_snapshot(signal)
        realistic_assumptions = _realistic_assumptions(entry=entry, risk=risk, evidence_snapshot=evidence_snapshot)
        quality_shadow = mid_short_1h_quality_shadow_filter(
            stage=signal.stage,
            timeframe=signal.timeframe,
            evidence_snapshot=evidence_snapshot,
            entry=entry,
            stop=stop,
            realistic_fill_quality=str(realistic_assumptions.get("realistic_fill_quality") or ""),
        )
        base = {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "signal_timestamp": signal_time,
            "signal_time_wib": _wib_string(signal_time),
            "stage": signal.stage,
            "direction": direction,
            "candidate_status": signal.candidate_status,
            "strategy_version": _signal_strategy_version(signal),
            "strategy_family": "Signal Factory V2",
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "v3_shadow_status": "V3_SHADOW_NOT_EVALUATED",
            "v3_shadow_filter_id": None,
            "v3_shadow_filter_label": None,
            "v3_shadow_filter_expression": None,
            "v3_shadow_promotion_score": None,
            "v3_shadow_reason": "V3 shadow evaluation has not been applied.",
            "confidence_tier": signal.confidence_tier,
            "execution_flag": signal.execution_flag,
            "core_score": signal.core_score,
            "evidence_score": signal.evidence_score,
            "evidence_data_completeness": signal.evidence_data_completeness,
            "evidence_snapshot": evidence_snapshot,
            "entry": entry,
            "stop_loss": stop,
            "take_profit": target,
            "risk": risk,
            "rr": abs(target - entry) / risk if risk > 0 else None,
            **realistic_assumptions,
            **quality_shadow,
            "result_status": "WAITING_DATA",
            "result_time_utc": None,
            "result_time_wib": None,
            "exit_price": None,
            "realized_r": None,
            "unrealized_r": None,
            "realistic_result_status": "WAITING_DATA",
            "realistic_entry_price": None,
            "realistic_exit_price": None,
            "realistic_realized_r": None,
            "realistic_unrealized_r": None,
            "realism_penalty_r": None,
            "mfe_r": None,
            "mae_r": None,
            "candles_seen": 0,
            "stale_forward_data": False,
            "stale_reason": None,
            "stale_gap_minutes": None,
            "freshness_gap_minutes": None,
            "latest_symbol_candle_time": None,
            "latest_symbol_candle_time_wib": None,
            "global_latest_evaluation_candle_time": global_latest_candle_time,
            "global_latest_evaluation_candle_time_wib": _wib_string(global_latest_candle_time),
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
                realistic_fields = _realistic_result_fields(
                    base,
                    entry=entry,
                    exit_reference=stop,
                    risk=risk,
                    direction=direction,
                    ideal_status="BOTH_HIT_SAME_CANDLE",
                    ideal_r=Decimal("0"),
                    conservative_status="SL_HIT_CONSERVATIVE",
                )
                return {
                    **base,
                    "result_status": "BOTH_HIT_SAME_CANDLE",
                    "result_time_utc": candle.close_time,
                    "result_time_wib": _wib_string(candle.close_time),
                    "exit_price": candle.close,
                    "realized_r": Decimal("0"),
                    "unrealized_r": None,
                    **realistic_fields,
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": index,
                }
            if tp_hit:
                ideal_r = abs(target - entry) / risk
                realistic_fields = _realistic_result_fields(
                    base,
                    entry=entry,
                    exit_reference=target,
                    risk=risk,
                    direction=direction,
                    ideal_status="TP_HIT",
                    ideal_r=ideal_r,
                )
                return {
                    **base,
                    "result_status": "TP_HIT",
                    "result_time_utc": candle.close_time,
                    "result_time_wib": _wib_string(candle.close_time),
                    "exit_price": target,
                    "realized_r": ideal_r,
                    "unrealized_r": None,
                    **realistic_fields,
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": index,
                }
            if sl_hit:
                realistic_fields = _realistic_result_fields(
                    base,
                    entry=entry,
                    exit_reference=stop,
                    risk=risk,
                    direction=direction,
                    ideal_status="SL_HIT",
                    ideal_r=Decimal("-1"),
                )
                return {
                    **base,
                    "result_status": "SL_HIT",
                    "result_time_utc": candle.close_time,
                    "result_time_wib": _wib_string(candle.close_time),
                    "exit_price": stop,
                    "realized_r": Decimal("-1"),
                    "unrealized_r": None,
                    **realistic_fields,
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": index,
                }

        latest = future[-1]
        unrealized = (latest.close - entry) / risk if direction == "LONG" else (entry - latest.close) / risk
        realistic_open_fields = _realistic_result_fields(
            base,
            entry=entry,
            exit_reference=latest.close,
            risk=risk,
            direction=direction,
            ideal_status="OPEN",
            ideal_r=unrealized,
            realized=False,
        )
        freshness_gap_minutes = None
        if global_latest_candle_time is not None:
            stale_gap = _naive(global_latest_candle_time) - _naive(latest.close_time)
            freshness_gap_minutes = Decimal(stale_gap.total_seconds()) / Decimal("60")
            if stale_gap > timedelta(minutes=FORWARD_DATA_STALE_MINUTES):
                return {
                    **base,
                    "result_status": "STALE_FORWARD_DATA",
                    "result_time_utc": latest.close_time,
                    "result_time_wib": _wib_string(latest.close_time),
                    "exit_price": latest.close,
                    "unrealized_r": unrealized,
                    **{**realistic_open_fields, "realistic_result_status": "STALE_FORWARD_DATA"},
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": len(future),
                    "stale_forward_data": True,
                    "stale_reason": "Symbol futures candles are behind the global evaluation candle.",
                    "stale_gap_minutes": freshness_gap_minutes,
                    "freshness_gap_minutes": freshness_gap_minutes,
                    "latest_symbol_candle_time": latest.close_time,
                    "latest_symbol_candle_time_wib": _wib_string(latest.close_time),
                }
        return {
            **base,
            "result_status": "OPEN",
            "result_time_utc": latest.close_time,
            "result_time_wib": _wib_string(latest.close_time),
            "exit_price": latest.close,
            "unrealized_r": unrealized,
            **realistic_open_fields,
            "mfe_r": mfe,
            "mae_r": mae,
            "candles_seen": len(future),
            "freshness_gap_minutes": freshness_gap_minutes,
            "latest_symbol_candle_time": latest.close_time,
            "latest_symbol_candle_time_wib": _wib_string(latest.close_time),
        }

    def _aggregate(self, items: list[dict[str, Any]], skipped: Counter[str]) -> dict[str, Any]:
        return aggregate_signal_performance_items(items, skipped)


def aggregate_signal_performance_items(items: list[dict[str, Any]], skipped: Counter[str] | dict[str, int] | None = None) -> dict[str, Any]:
    skipped_counter = Counter(skipped or {})
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
        "signals_skipped": sum(skipped_counter.values()),
        "skip_reasons": dict(skipped_counter),
        **total_perf,
        "status_counts": dict(status_counts),
        "by_stage": dict(by_stage),
        "by_timeframe": dict(by_timeframe),
        "by_timeframe_performance": timeframe_perf,
        "by_confidence": dict(by_confidence),
    }


def build_one_hour_filter_candidate_study_payload(
    *,
    evaluated: list[dict[str, Any]],
    skipped: Counter[str] | dict[str, int] | None,
    latest_candle_time: Any,
    epoch: str,
    include_watch_only: bool,
    position_lock: bool,
    min_sample: int,
    limit: int,
    source: str = "live_compute",
) -> dict[str, Any]:
    latest_dt = _parse_dt(latest_candle_time)
    lanes = [
        _one_hour_filter_lane(
            stage="MID_LONG",
            direction="LONG",
            items=[item for item in evaluated if item.get("stage") == "MID_LONG"],
            min_sample=min_sample,
            limit=limit,
        ),
        _one_hour_filter_lane(
            stage="MID_SHORT",
            direction="SHORT",
            items=[item for item in evaluated if item.get("stage") == "MID_SHORT"],
            min_sample=min_sample,
            limit=limit,
        ),
    ]
    candidates = [
        candidate
        for lane in lanes
        for candidate in lane["filter_candidates"]
        if candidate["action"] in {"PROMOTE_TO_SHADOW", "MONITOR_MORE"}
    ]
    candidates.sort(key=_one_hour_filter_candidate_sort_key, reverse=True)
    return {
        "generated_at_utc": utcnow(),
        "epoch": epoch,
        "filters": {
            "include_watch_only": include_watch_only,
            "position_lock": position_lock,
            "timeframe": "1h",
            "stages": ["MID_LONG", "MID_SHORT"],
            "min_sample": min_sample,
            "limit": limit,
        },
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
        "strategy_version": LIVE_STRATEGY_VERSION,
        "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
        "study_scope": "one_hour_filter_candidate_study_read_only",
        "source": source,
        "method": "Existing filter specs ranked against 1h MID_LONG and MID_SHORT closed paper outcomes.",
        "latest_evaluation_candle_time": latest_dt,
        "latest_futures_15m_close_time": latest_dt,
        "skipped_by_position_lock": dict(Counter(skipped or {})),
        "aggregate": aggregate_signal_performance_items(evaluated, skipped),
        "lanes": lanes,
        "top_candidates": candidates[:limit],
        "guardrails": [
            "No Signal Factory rule changed.",
            "No scanner behavior changed.",
            "No TP/SL formula or outcome calculation changed.",
            "PROMOTE_TO_SHADOW means research-only shadow monitoring, not live execution.",
        ],
    }


def build_one_hour_walk_forward_payload(
    *,
    evaluated: list[dict[str, Any]],
    skipped: Counter[str] | dict[str, int] | None,
    latest_candle_time: Any,
    epoch: str,
    include_watch_only: bool,
    position_lock: bool,
    min_sample: int,
    limit: int,
    source: str = "live_compute",
) -> dict[str, Any]:
    latest_dt = _parse_dt(latest_candle_time)
    closed = [
        item
        for item in evaluated
        if item.get("result_status") in COMPLETED_OUTCOMES and item.get("realistic_realized_r") is not None
    ]
    lanes = [
        _one_hour_walk_forward_lane(
            stage="MID_LONG",
            direction="LONG",
            items=[item for item in closed if item.get("stage") == "MID_LONG"],
            min_sample=min_sample,
            limit=limit,
        ),
        _one_hour_walk_forward_lane(
            stage="MID_SHORT",
            direction="SHORT",
            items=[item for item in closed if item.get("stage") == "MID_SHORT"],
            min_sample=min_sample,
            limit=limit,
        ),
    ]
    candidates = [
        candidate
        for lane in lanes
        for candidate in lane["filter_candidates"]
        if candidate["verdict"] in {"WF_PROMISING", "WF_REDUCES_DAMAGE"}
    ]
    candidates.sort(key=_one_hour_walk_forward_sort_key, reverse=True)
    return {
        "generated_at_utc": utcnow(),
        "epoch": epoch,
        "filters": {
            "include_watch_only": include_watch_only,
            "position_lock": position_lock,
            "timeframe": "1h",
            "stages": ["MID_LONG", "MID_SHORT"],
            "min_sample": min_sample,
            "limit": limit,
        },
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
        "strategy_version": LIVE_STRATEGY_VERSION,
        "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
        "study_scope": "one_hour_walk_forward_optimization_read_only",
        "source": source,
        "method": "Chronological 70/30 train-validation split over closed 1h Signal outcomes using realistic R.",
        "split_method": "chronological_70_30",
        "latest_evaluation_candle_time": latest_dt,
        "latest_futures_15m_close_time": latest_dt,
        "skipped_by_position_lock": dict(Counter(skipped or {})),
        "aggregate": aggregate_signal_performance_items(closed, skipped),
        "lanes": lanes,
        "top_candidates": candidates[:limit],
        "guardrails": [
            "No Signal Factory rule changed.",
            "No scanner behavior changed.",
            "No TP/SL formula or outcome calculation changed.",
            "Walk-forward candidates are research-only and not execution instructions.",
        ],
    }


def build_one_hour_v4_shadow_monitor_payload(
    *,
    evaluated: list[dict[str, Any]],
    skipped: Counter[str] | dict[str, int] | None,
    latest_candle_time: Any,
    epoch: str,
    include_watch_only: bool,
    position_lock: bool,
    min_sample: int,
    limit: int,
    source: str = "live_compute",
) -> dict[str, Any]:
    latest_dt = _parse_dt(latest_candle_time)
    one_hour_items = [
        item
        for item in evaluated
        if item.get("timeframe") == "1h" and item.get("stage") in {"MID_LONG", "MID_SHORT"}
    ]
    walk_forward = build_one_hour_walk_forward_payload(
        evaluated=one_hour_items,
        skipped=skipped,
        latest_candle_time=latest_dt,
        epoch=epoch,
        include_watch_only=include_watch_only,
        position_lock=position_lock,
        min_sample=min_sample,
        limit=max(limit, 1),
        source=source,
    )
    selected_filters = _one_hour_v4_selected_filters(walk_forward.get("top_candidates") or [], limit=limit)
    annotated = _one_hour_v4_apply_shadow(one_hour_items, selected_filters)
    pass_items = [item for item in annotated if item.get("v4_shadow_status") == "V4_SHADOW_PASS"]
    fail_items = [item for item in annotated if item.get("v4_shadow_status") == "V4_SHADOW_FAIL"]
    unavailable_items = [item for item in annotated if item.get("v4_shadow_status") == "V4_SHADOW_UNAVAILABLE"]
    no_filter_items = [item for item in annotated if item.get("v4_shadow_status") == "V4_SHADOW_NO_FILTER"]
    baseline = _walk_forward_perf(one_hour_items)
    v4_pass = _walk_forward_perf(pass_items, baseline=baseline)
    v4_fail = _walk_forward_perf(fail_items, baseline=baseline)
    return {
        "generated_at_utc": utcnow(),
        "epoch": epoch,
        "filters": {
            "include_watch_only": include_watch_only,
            "position_lock": position_lock,
            "timeframe": "1h",
            "stages": ["MID_LONG", "MID_SHORT"],
            "min_sample": min_sample,
            "limit": limit,
        },
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
        "strategy_version": LIVE_STRATEGY_VERSION,
        "shadow_strategy_version": "SIGNAL_FACTORY_V4_SHADOW_WALK_FORWARD_1H",
        "study_scope": "one_hour_v4_shadow_forward_monitor_read_only",
        "source": source,
        "method": "Applies 1h walk-forward filters to logged 1h Signal outcomes as shadow-only V4 labels.",
        "filter_source": "one_hour_walk_forward_optimization_read_only",
        "latest_evaluation_candle_time": latest_dt,
        "latest_futures_15m_close_time": latest_dt,
        "skipped_by_position_lock": dict(Counter(skipped or {})),
        "selected_filters": selected_filters,
        "walk_forward_summary": {
            "lane_count": len(walk_forward.get("lanes") or []),
            "top_candidate_count": len(walk_forward.get("top_candidates") or []),
        },
        "summary": {
            "v2_baseline": baseline,
            "v4_shadow_pass": v4_pass,
            "v4_shadow_fail": v4_fail,
            "v4_shadow_pass_count": len(pass_items),
            "v4_shadow_fail_count": len(fail_items),
            "v4_shadow_unavailable_count": len(unavailable_items),
            "v4_shadow_no_filter_count": len(no_filter_items),
            "sample_retention_pct": _retention(len(pass_items), len(one_hour_items)),
            "realistic_total_r_delta_v4_vs_v2": _decimal_delta(
                v4_pass.get("realistic_total_r_closed"),
                baseline.get("realistic_total_r_closed"),
            ),
            "realistic_avg_r_delta_v4_vs_v2": _decimal_delta(
                v4_pass.get("realistic_avg_r_closed"),
                baseline.get("realistic_avg_r_closed"),
            ),
            "winrate_delta_v4_vs_v2": _decimal_delta(v4_pass.get("winrate_pct"), baseline.get("winrate_pct")),
            "sl_share_delta_v4_vs_v2": _decimal_delta(_sl_share(v4_pass), _sl_share(baseline)),
            "read": _one_hour_v4_read(
                baseline=baseline,
                v4_pass=v4_pass,
                selected_filter_count=len(selected_filters),
                min_sample=min_sample,
            ),
        },
        "by_stage": _one_hour_v4_stage_rows(annotated, selected_filters=selected_filters, min_sample=min_sample),
        "latest_v4_pass_signals": _sorted_signal_rows(pass_items, limit=limit),
        "latest_v4_fail_signals": _sorted_signal_rows(fail_items, limit=min(limit, 20)),
        "guardrails": [
            "No Signal Factory rule changed.",
            "No scanner behavior changed.",
            "No TP/SL formula or outcome calculation changed.",
            "V4 shadow status is research-only and not an execution instruction.",
        ],
        }


def _quality_lab_cache_get(cache_key: tuple[Any, ...]) -> dict[str, Any] | None:
    cached = _QUALITY_LAB_CACHE.get(cache_key)
    if cached is None:
        return None
    created_at, payload = cached
    if monotonic() - created_at > QUALITY_LAB_CACHE_TTL_SECONDS:
        _QUALITY_LAB_CACHE.pop(cache_key, None)
        return None
    return deepcopy(payload)


def _quality_lab_cache_set(cache_key: tuple[Any, ...], payload: dict[str, Any]) -> None:
    if len(_QUALITY_LAB_CACHE) > 32:
        oldest_key = min(_QUALITY_LAB_CACHE, key=lambda key: _QUALITY_LAB_CACHE[key][0])
        _QUALITY_LAB_CACHE.pop(oldest_key, None)
    _QUALITY_LAB_CACHE[cache_key] = (monotonic(), deepcopy(payload))


def mid_short_1h_quality_shadow_filter(
    *,
    stage: str | None,
    timeframe: str | None,
    evidence_snapshot: dict[str, Any] | None,
    entry: Decimal | None = None,
    stop: Decimal | None = None,
    realistic_fill_quality: str | None = None,
) -> dict[str, Any]:
    evidence = evidence_snapshot or {}
    output = {
        "quality_shadow_filter_id": None,
        "quality_shadow_filter_label": None,
        "quality_shadow_filter_expression": None,
        "quality_shadow_status": "SHADOW_NOT_APPLICABLE",
        "quality_shadow_pass": False,
        "quality_shadow_reason": "Only applies to MID_SHORT 1h.",
        "quality_shadow_range_ratio_vs_atr": None,
        "quality_shadow_fill_quality": realistic_fill_quality,
    }
    if str(stage or "").upper() != "MID_SHORT" or str(timeframe or "") != "1h":
        return output

    range_ratio = _decimal_or_none(evidence.get("range_ratio_vs_atr"))
    fill_quality = realistic_fill_quality
    if fill_quality is None and entry is not None and stop is not None:
        risk = abs(Decimal(entry) - Decimal(stop))
        if risk > 0:
            fill_quality = str(_realistic_assumptions(entry=Decimal(entry), risk=risk, evidence_snapshot=evidence)["realistic_fill_quality"])

    output.update(
        {
            "quality_shadow_filter_id": MID_SHORT_1H_QUALITY_SHADOW_FILTER_ID,
            "quality_shadow_filter_label": MID_SHORT_1H_QUALITY_SHADOW_FILTER_LABEL,
            "quality_shadow_filter_expression": MID_SHORT_1H_QUALITY_SHADOW_FILTER_EXPRESSION,
            "quality_shadow_status": "SHADOW_UNAVAILABLE",
            "quality_shadow_reason": "Missing fill quality or range/ATR evidence.",
            "quality_shadow_range_ratio_vs_atr": range_ratio,
            "quality_shadow_fill_quality": fill_quality,
        }
    )
    if not fill_quality or range_ratio is None:
        return output

    if fill_quality == "FILL_GOOD" and range_ratio <= MID_SHORT_1H_QUALITY_RANGE_ATR_MAX:
        output.update(
            {
                "quality_shadow_status": "SHADOW_PASS",
                "quality_shadow_pass": True,
                "quality_shadow_reason": "Fill quality is good and range/ATR is not overextended.",
            }
        )
        return output

    reasons: list[str] = []
    if fill_quality != "FILL_GOOD":
        reasons.append(f"fill={fill_quality}")
    if range_ratio > MID_SHORT_1H_QUALITY_RANGE_ATR_MAX:
        reasons.append(f"range/ATR {range_ratio} > {MID_SHORT_1H_QUALITY_RANGE_ATR_MAX}")
    output.update(
        {
            "quality_shadow_status": "SHADOW_FAIL",
            "quality_shadow_reason": "; ".join(reasons) or "Filter conditions not met.",
        }
    )
    return output


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


def _realistic_assumptions(
    *,
    entry: Decimal,
    risk: Decimal,
    evidence_snapshot: dict[str, Decimal | None],
) -> dict[str, Any]:
    spread_pct_raw = evidence_snapshot.get("futures_spread_pct")
    spread_pct = Decimal(spread_pct_raw) if spread_pct_raw is not None else None
    used_spread_pct = spread_pct if spread_pct is not None else Decimal("0")
    round_trip_pct = (REALISTIC_FEE_PCT_PER_SIDE * Decimal("2")) + (
        REALISTIC_SLIPPAGE_PCT_PER_SIDE * Decimal("2")
    ) + used_spread_pct
    cost_r = (entry * (round_trip_pct / Decimal("100")) / risk) if risk > 0 else None
    if spread_pct is None:
        fill_quality = "SPREAD_UNKNOWN"
    elif cost_r is None:
        fill_quality = "FILL_UNKNOWN"
    elif cost_r <= REALISTIC_FILL_GOOD_MAX_COST_R:
        fill_quality = "FILL_GOOD"
    elif cost_r <= REALISTIC_FILL_ACCEPTABLE_MAX_COST_R:
        fill_quality = "FILL_ACCEPTABLE"
    else:
        fill_quality = "FILL_BAD"
    return {
        "realistic_model_version": REALISTIC_MODEL_VERSION,
        "realistic_fee_model": REALISTIC_FEE_MODEL,
        "realistic_fee_source": REALISTIC_FEE_SOURCE,
        "realistic_fee_pct_per_side": REALISTIC_FEE_PCT_PER_SIDE,
        "realistic_taker_fee_pct_per_side": REALISTIC_BINANCE_FUTURES_TAKER_FEE_PCT_PER_SIDE,
        "realistic_maker_fee_pct_per_side": REALISTIC_BINANCE_FUTURES_MAKER_FEE_PCT_PER_SIDE,
        "realistic_slippage_pct_per_side": REALISTIC_SLIPPAGE_PCT_PER_SIDE,
        "realistic_futures_spread_pct": spread_pct,
        "realistic_spread_source": "signal_evidence.futures_spread_pct" if spread_pct is not None else "missing",
        "realistic_round_trip_cost_pct_estimate": round_trip_pct,
        "realistic_cost_r_estimate": cost_r,
        "realistic_fill_quality": fill_quality,
    }


def _realistic_result_fields(
    base: dict[str, Any],
    *,
    entry: Decimal,
    exit_reference: Decimal,
    risk: Decimal,
    direction: str,
    ideal_status: str,
    ideal_r: Decimal,
    conservative_status: str | None = None,
    realized: bool = True,
) -> dict[str, Any]:
    entry_price = _realistic_entry_price(entry, direction, base)
    exit_price = _realistic_exit_price(exit_reference, direction, base)
    if entry_price is None or exit_price is None or risk <= 0:
        realistic_r = None
    else:
        gross_r = (exit_price - entry_price) / risk if direction == "LONG" else (entry_price - exit_price) / risk
        fee_r = ((entry_price + exit_price) * (REALISTIC_FEE_PCT_PER_SIDE / Decimal("100"))) / risk
        realistic_r = gross_r - fee_r
    fields = {
        "realistic_result_status": conservative_status or ideal_status,
        "realistic_entry_price": entry_price,
        "realistic_exit_price": exit_price,
        "realism_penalty_r": (ideal_r - realistic_r) if realistic_r is not None else None,
    }
    if realized:
        fields["realistic_realized_r"] = realistic_r
        fields["realistic_unrealized_r"] = None
    else:
        fields["realistic_realized_r"] = None
        fields["realistic_unrealized_r"] = realistic_r
    return fields


def _realistic_entry_price(entry: Decimal, direction: str, base: dict[str, Any]) -> Decimal | None:
    impact_pct = _realistic_price_impact_pct(base)
    if impact_pct is None:
        return None
    if direction == "LONG":
        return entry * (Decimal("1") + impact_pct)
    if direction == "SHORT":
        return entry * (Decimal("1") - impact_pct)
    return None


def _realistic_exit_price(exit_reference: Decimal, direction: str, base: dict[str, Any]) -> Decimal | None:
    impact_pct = _realistic_price_impact_pct(base)
    if impact_pct is None:
        return None
    if direction == "LONG":
        return exit_reference * (Decimal("1") - impact_pct)
    if direction == "SHORT":
        return exit_reference * (Decimal("1") + impact_pct)
    return None


def _realistic_price_impact_pct(base: dict[str, Any]) -> Decimal | None:
    spread_pct = base.get("realistic_futures_spread_pct")
    used_spread_pct = Decimal(spread_pct) if spread_pct is not None else Decimal("0")
    half_spread_pct = used_spread_pct / Decimal("2")
    total_pct = half_spread_pct + REALISTIC_SLIPPAGE_PCT_PER_SIDE
    return total_pct / Decimal("100")


def build_misidentification_audit_payload(
    *,
    evaluated: list[dict[str, Any]],
    skipped: dict[str, int] | Counter[str],
    latest_candle_time: datetime | str | None,
    epoch: str,
    include_watch_only: bool,
    position_lock: bool,
    timeframe: str,
    stages: tuple[str, ...],
    min_sample: int,
    limit: int,
    max_signals_per_stage: int,
    source: str,
) -> dict[str, Any]:
    lanes: list[dict[str, Any]] = []
    latest_times = [_parse_dt(latest_candle_time)]
    for stage in stages:
        stage_items = [
            dict(item)
            for item in evaluated
            if str(item.get("stage") or "").upper() == stage and str(item.get("timeframe") or "") == timeframe
        ]
        stage_items.sort(key=lambda item: (_parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol") or "")))
        if max_signals_per_stage > 0:
            stage_items = stage_items[-max_signals_per_stage:]
        latest_times.extend(_parse_dt(item.get("signal_timestamp")) for item in stage_items)
        lanes.append(
            _misidentification_lane(
                stage=stage,
                timeframe=timeframe,
                items=stage_items,
                min_sample=min_sample,
                limit=limit,
            )
        )

    latest_time = max((value for value in latest_times if value is not None), default=None)
    return {
        "generated_at_utc": utcnow(),
        "epoch": epoch,
        "filters": {
            "include_watch_only": include_watch_only,
            "position_lock": position_lock,
            "timeframe": timeframe,
            "stages": list(stages),
            "min_sample": min_sample,
            "limit": limit,
            "max_signals_per_stage": max_signals_per_stage,
        },
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
        "strategy_version": LIVE_STRATEGY_VERSION,
        "study_scope": "signal_misidentification_audit_read_only",
        "source": source,
        "method": (
            "Classifies logged Signal outcomes using available path/evidence fields, MFE/MAE, "
            "extension/fill evidence, and a conservative reverse-direction proxy. It does not change live rules."
        ),
        "latest_evaluation_candle_time": latest_time,
        "latest_futures_15m_close_time": latest_time,
        "skipped_by_position_lock": dict(skipped),
        "lanes": lanes,
        "summary": _misidentification_summary(lanes),
        "guardrails": [
            "No Signal Factory rule changed.",
            "No scanner behavior changed.",
            "No TP/SL formula or outcome calculation changed.",
            "Reverse analysis is a conservative proxy from the same paper-live path, not a new signal rule.",
            "A reverse candidate means worth researching, not permission to flip live direction.",
        ],
    }


def _performance_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(item["result_status"]) for item in items)
    closed = [item for item in items if item["result_status"] in COMPLETED_OUTCOMES]
    wins = [item for item in closed if item["result_status"] == "TP_HIT"]
    losses = [item for item in closed if item["result_status"] == "SL_HIT"]
    realized_values = [Decimal(item["realized_r"]) for item in closed if item.get("realized_r") is not None]
    realistic_realized_values = [
        Decimal(item["realistic_realized_r"])
        for item in closed
        if item.get("realistic_realized_r") is not None
    ]
    open_values = [
        Decimal(item["unrealized_r"])
        for item in items
        if item["result_status"] == "OPEN" and item.get("unrealized_r") is not None
    ]
    realistic_open_values = [
        Decimal(item["realistic_unrealized_r"])
        for item in items
        if item["result_status"] == "OPEN" and item.get("realistic_unrealized_r") is not None
    ]
    completed_for_winrate = len(wins) + len(losses)
    total_r_closed = sum(realized_values, Decimal("0"))
    realistic_total_r_closed = sum(realistic_realized_values, Decimal("0"))
    total_unrealized_r = sum(open_values, Decimal("0"))
    realistic_total_unrealized_r = sum(realistic_open_values, Decimal("0"))
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
        "realistic_total_r_closed": realistic_total_r_closed,
        "realistic_open_unrealized_r": realistic_total_unrealized_r,
        "realistic_total_r_with_open": realistic_total_r_closed + realistic_total_unrealized_r,
        "realism_penalty_r_closed": total_r_closed - realistic_total_r_closed,
        "realism_penalty_r_with_open": (
            (total_r_closed + total_unrealized_r)
            - (realistic_total_r_closed + realistic_total_unrealized_r)
        ),
        "fixed_risk_return_pct_1pct_closed": total_r_closed,
        "fixed_risk_return_pct_1pct_with_open": total_r_closed + total_unrealized_r,
        "avg_r_closed": total_r_closed / Decimal(len(realized_values)) if realized_values else None,
        "realistic_avg_r_closed": realistic_total_r_closed / Decimal(len(realistic_realized_values))
        if realistic_realized_values
        else None,
    }


def _v3_status_rows(
    groups: dict[str, list[dict[str, Any]]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    rows = []
    for status, items in groups.items():
        perf = _performance_summary(items)
        row = {
            "bucket": status,
            "sample_count": len(items),
            "sample_retention_pct": _retention(len(items), int(baseline.get("signals_evaluated") or 0)),
            "sl_share_pct": _sl_share(perf),
            "avg_r_delta_vs_v2": _decimal_delta(perf.get("avg_r_closed"), baseline.get("avg_r_closed")),
            "total_r_delta_vs_v2": _decimal_delta(perf.get("total_r_closed"), baseline.get("total_r_closed")),
            "winrate_delta_vs_v2": _decimal_delta(perf.get("winrate_pct"), baseline.get("winrate_pct")),
            "sl_share_delta_vs_v2": _decimal_delta(_sl_share(perf), _sl_share(baseline)),
            **perf,
        }
        row["verdict"] = _v3_bucket_verdict(row, min_sample=min_sample)
        rows.append(row)
    return sorted(rows, key=lambda row: (int(row.get("sample_count") or 0), Decimal(row.get("total_r_closed") or 0)), reverse=True)


def _v3_lane_rows(items: list[dict[str, Any]], *, min_sample: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[(str(item.get("stage") or "UNKNOWN"), str(item.get("timeframe") or "UNKNOWN"))].append(item)
    rows = []
    for (stage, timeframe), lane_items in groups.items():
        baseline = _performance_summary(lane_items)
        pass_items = [item for item in lane_items if item.get("v3_shadow_status") == "V3_SHADOW_PASS"]
        v3_pass = _performance_summary(pass_items)
        row = {
            "stage": stage,
            "timeframe": timeframe,
            "v2_live": baseline,
            "v3_shadow_pass": v3_pass,
            "v3_pass_count": len(pass_items),
            "v3_fail_count": sum(1 for item in lane_items if item.get("v3_shadow_status") == "V3_SHADOW_FAIL"),
            "v3_unavailable_count": sum(1 for item in lane_items if item.get("v3_shadow_status") == "V3_SHADOW_UNAVAILABLE"),
            "v3_no_filter_count": sum(1 for item in lane_items if item.get("v3_shadow_status") == "V3_SHADOW_NO_FILTER"),
            "sample_retention_pct": _retention(len(pass_items), len(lane_items)),
            "avg_r_delta_v3_pass_vs_v2": _decimal_delta(v3_pass.get("avg_r_closed"), baseline.get("avg_r_closed")),
            "total_r_delta_v3_pass_vs_v2": _decimal_delta(v3_pass.get("total_r_closed"), baseline.get("total_r_closed")),
            "winrate_delta_v3_pass_vs_v2": _decimal_delta(v3_pass.get("winrate_pct"), baseline.get("winrate_pct")),
            "sl_share_delta_v3_pass_vs_v2": _decimal_delta(_sl_share(v3_pass), _sl_share(baseline)),
        }
        row["verdict"] = _v3_comparison_read(baseline, v3_pass, len(pass_items), min_sample=min_sample)
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            Decimal(row.get("avg_r_delta_v3_pass_vs_v2") or Decimal("-999")),
            Decimal(row.get("v3_shadow_pass", {}).get("total_r_closed") or 0),
            int(row.get("v3_pass_count") or 0),
        ),
        reverse=True,
    )


def _v3_filter_rows(
    pass_items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
    limit: int,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, str] = {}
    expressions: dict[str, str] = {}
    for item in pass_items:
        filter_id = str(item.get("v3_shadow_filter_id") or "UNKNOWN_FILTER")
        groups[filter_id].append(item)
        labels[filter_id] = str(item.get("v3_shadow_filter_label") or filter_id)
        expressions[filter_id] = str(item.get("v3_shadow_filter_expression") or "")
    rows = []
    for filter_id, items in groups.items():
        perf = _performance_summary(items)
        row = {
            "filter_id": filter_id,
            "label": labels.get(filter_id, filter_id),
            "expression": expressions.get(filter_id, ""),
            "sample_count": len(items),
            "sample_retention_pct": _retention(len(items), int(baseline.get("signals_evaluated") or 0)),
            "avg_r_delta_vs_v2": _decimal_delta(perf.get("avg_r_closed"), baseline.get("avg_r_closed")),
            "winrate_delta_vs_v2": _decimal_delta(perf.get("winrate_pct"), baseline.get("winrate_pct")),
            "sl_share_delta_vs_v2": _decimal_delta(_sl_share(perf), _sl_share(baseline)),
            **perf,
        }
        row["verdict"] = _v3_bucket_verdict(row, min_sample=min_sample)
        rows.append(row)
    rows.sort(
        key=lambda row: (
            int(row.get("sample_count") or 0) >= min_sample,
            Decimal(row.get("avg_r_delta_vs_v2") or Decimal("-999")),
            Decimal(row.get("total_r_closed") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _forward_lane_summary(items: list[dict[str, Any]], *, min_sample: int) -> dict[str, Any]:
    perf = _performance_summary(items)
    drawdown = _drawdown_summary(items, point_limit=80)
    bucket = _bucket_summary("FORWARD_LANE", items, min_sample=min_sample)
    return {
        "performance": perf,
        "drawdown": {
            key: value
            for key, value in drawdown.items()
            if key != "points"
        },
        "quality": {
            "quality_flag": bucket.get("quality_flag"),
            "median_r_closed": bucket.get("median_r_closed"),
            "median_mfe_r": bucket.get("median_mfe_r"),
            "median_mae_r": bucket.get("median_mae_r"),
            "best_r": bucket.get("best_r"),
            "worst_r": bucket.get("worst_r"),
            "top_symbol": bucket.get("top_symbol"),
            "top_symbol_share_pct": bucket.get("top_symbol_share_pct"),
            "symbol_count": bucket.get("symbol_count"),
        },
    }


def _v3_forward_lane_rows(items: list[dict[str, Any]], *, min_sample: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[(str(item.get("stage") or "UNKNOWN"), str(item.get("timeframe") or "UNKNOWN"))].append(item)

    rows: list[dict[str, Any]] = []
    for (stage, timeframe), lane_items in groups.items():
        v2 = _forward_lane_summary(lane_items, min_sample=min_sample)
        v3_items = [item for item in lane_items if item.get("v3_shadow_status") == "V3_SHADOW_PASS"]
        v3 = _forward_lane_summary(v3_items, min_sample=min_sample)
        v2_perf = v2["performance"]
        v3_perf = v3["performance"]
        row = {
            "stage": stage,
            "timeframe": timeframe,
            "v2_live": v2,
            "v3_shadow_signal": v3,
            "v3_shadow_signal_count": len(v3_items),
            "v3_sample_retention_pct": _retention(len(v3_items), len(lane_items)),
            "total_r_delta_v3_vs_v2": _decimal_delta(v3_perf.get("total_r_closed"), v2_perf.get("total_r_closed")),
            "avg_r_delta_v3_vs_v2": _decimal_delta(v3_perf.get("avg_r_closed"), v2_perf.get("avg_r_closed")),
            "winrate_delta_v3_vs_v2": _decimal_delta(v3_perf.get("winrate_pct"), v2_perf.get("winrate_pct")),
            "max_drawdown_delta_v3_vs_v2": _decimal_delta(
                v3["drawdown"].get("max_drawdown_r"),
                v2["drawdown"].get("max_drawdown_r"),
            ),
        }
        row["read"] = _v3_forward_read(v2, v3, min_sample=min_sample)
        rows.append(row)
    rows.sort(
        key=lambda row: (
            Decimal(row.get("v3_shadow_signal", {}).get("performance", {}).get("total_r_closed") or 0),
            int(row.get("v3_shadow_signal_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _v3_forward_read(v2_summary: dict[str, Any], v3_summary: dict[str, Any], *, min_sample: int) -> str:
    v2_perf = v2_summary["performance"]
    v3_perf = v3_summary["performance"]
    v3_closed = int(v3_perf.get("closed_count") or 0)
    if v3_closed < min_sample:
        return "V3_FORWARD_WAITING_SAMPLE"
    total_delta = _decimal_delta(v3_perf.get("total_r_closed"), v2_perf.get("total_r_closed"))
    avg_delta = _decimal_delta(v3_perf.get("avg_r_closed"), v2_perf.get("avg_r_closed"))
    dd_delta = _decimal_delta(v3_summary["drawdown"].get("max_drawdown_r"), v2_summary["drawdown"].get("max_drawdown_r"))
    v3_total = Decimal(v3_perf.get("total_r_closed") or 0)
    if v3_total > 0 and avg_delta is not None and avg_delta > 0 and (dd_delta is None or dd_delta >= 0):
        return "V3_FORWARD_HEALTHY_SHADOW"
    if total_delta is not None and total_delta > 0 and v3_total > 0:
        return "V3_FORWARD_MONITOR_MORE"
    if v3_total < 0:
        return "V3_FORWARD_WEAK"
    return "V3_FORWARD_INCONCLUSIVE"


def _v3_forward_audit(
    *,
    v2_summary: dict[str, Any],
    v3_summary: dict[str, Any],
    lane_rows: list[dict[str, Any]],
    filter_rows: list[dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    stage_decisions = [_v3_stage_decision(row, min_sample=min_sample) for row in lane_rows]
    filter_decisions = [_v3_filter_decision(row, min_sample=min_sample) for row in filter_rows]
    stage_decisions.sort(
        key=lambda row: (
            row["decision"] in {"CALIBRATION_CANDIDATE", "MONITOR_MORE"},
            _decimal_or_zero(row.get("v3_realistic_total_r_closed")),
            _decimal_or_zero(row.get("v3_total_r_closed")),
            int(row.get("v3_closed_count") or 0),
        ),
        reverse=True,
    )
    filter_decisions.sort(
        key=lambda row: (
            row["decision"] in {"V4_FILTER_CANDIDATE", "MONITOR_MORE"},
            _decimal_or_zero(row.get("avg_r_delta_vs_v2")),
            _decimal_or_zero(row.get("total_r_closed")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )

    v2_perf = v2_summary["performance"]
    v3_perf = v3_summary["performance"]
    v3_closed = int(v3_perf.get("closed_count") or 0)
    v3_total = _decimal_or_zero(v3_perf.get("total_r_closed"))
    v3_realistic = _decimal_or_zero(v3_perf.get("realistic_total_r_closed"))
    promising_stage_count = sum(1 for row in stage_decisions if row["decision"] == "CALIBRATION_CANDIDATE")
    monitor_stage_count = sum(1 for row in stage_decisions if row["decision"] == "MONITOR_MORE")
    promising_filter_count = sum(1 for row in filter_decisions if row["decision"] == "V4_FILTER_CANDIDATE")
    risk_flags = _v3_audit_risk_flags(stage_decisions, filter_decisions, v3_summary)

    if v3_closed < min_sample:
        executive_verdict = "WAIT_MORE_SAMPLE"
        promotion_readiness = "V3_MONITOR_ONLY"
        next_recommendation = "Lanjut collect sample; V3 belum punya closed sample cukup untuk dibandingkan."
    elif promising_stage_count > 0 and promising_filter_count > 0 and v3_realistic > 0:
        executive_verdict = "HAS_CALIBRATION_CANDIDATE"
        promotion_readiness = "V4_FILTER_STUDY_READY"
        next_recommendation = "Gunakan lane/filter kandidat ini untuk studi V4 read-only, bukan langsung mengganti rule live."
    elif v3_total > 0 or monitor_stage_count > 0:
        executive_verdict = "MONITOR_MORE"
        promotion_readiness = "V3_MONITOR_ONLY"
        next_recommendation = "V3 punya sinyal positif campuran; tunggu sample tambahan dan cek realistic R."
    else:
        executive_verdict = "NO_PROMOTION_YET"
        promotion_readiness = "KEEP_V2_LIVE_RULES"
        next_recommendation = "Jangan promosikan V3; cari filter baru atau tunggu data live tambahan."

    best_stage = next((row for row in stage_decisions if row["decision"] in {"CALIBRATION_CANDIDATE", "MONITOR_MORE"}), None)
    best_filter = next((row for row in filter_decisions if row["decision"] in {"V4_FILTER_CANDIDATE", "MONITOR_MORE"}), None)
    main_findings = [
        f"V3 closed {v3_closed} dari {int(v2_perf.get('closed_count') or 0)} closed V2; ideal {v3_total}R, realistic {v3_realistic}R.",
        (
            f"Lane terbaik: {best_stage['stage']} {best_stage['timeframe']} ({best_stage['decision']})."
            if best_stage
            else "Belum ada lane V3 yang cukup bersih untuk dipromosikan."
        ),
        (
            f"Filter terbaik: {best_filter['filter_label']} ({best_filter['decision']})."
            if best_filter
            else "Belum ada filter V3 yang layak jadi kandidat studi V4."
        ),
    ]

    return {
        "executive_verdict": executive_verdict,
        "promotion_readiness": promotion_readiness,
        "main_findings": main_findings,
        "next_recommendation": next_recommendation,
        "promising_stage_count": promising_stage_count,
        "monitor_stage_count": monitor_stage_count,
        "promising_filter_count": promising_filter_count,
        "risk_flags": risk_flags,
        "stage_decisions": stage_decisions,
        "filter_decisions": filter_decisions,
        "guardrails": [
            "Audit ini hanya membaca hasil V2 live log dan V3 shadow filter.",
            "CALIBRATION_CANDIDATE bukan live signal dan bukan approval execution.",
            "Rule Signal Factory V2, scanner behavior, TP/SL reference, dan outcome logic tidak berubah.",
        ],
    }


def _v3_stage_decision(row: dict[str, Any], *, min_sample: int) -> dict[str, Any]:
    v2 = row.get("v2_live", {})
    v3 = row.get("v3_shadow_signal", {})
    v2_perf = v2.get("performance", {})
    v3_perf = v3.get("performance", {})
    v3_quality = v3.get("quality", {})
    v3_closed = int(v3_perf.get("closed_count") or 0)
    v3_total = _decimal_or_zero(v3_perf.get("total_r_closed"))
    v3_realistic = _decimal_or_zero(v3_perf.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_none_any(row.get("avg_r_delta_v3_vs_v2"))
    dd_delta = _decimal_or_none_any(row.get("max_drawdown_delta_v3_vs_v2"))
    concentration = _decimal_or_none_any(v3_quality.get("top_symbol_share_pct"))

    if v3_closed < min_sample:
        decision = "WAIT_SAMPLE"
        quality_flag = "SAMPLE_TOO_SMALL"
        reason = f"Closed sample {v3_closed} masih di bawah minimum {min_sample}."
    elif v3_realistic > 0 and v3_total > 0 and avg_delta is not None and avg_delta > 0 and (dd_delta is None or dd_delta >= 0) and (concentration is None or concentration <= Decimal("35")):
        decision = "CALIBRATION_CANDIDATE"
        quality_flag = "PROMISING_SHADOW"
        reason = "Ideal R dan realistic R positif, avg R membaik vs V2, drawdown tidak memburuk, dan konsentrasi symbol tidak berlebihan."
    elif v3_total > 0 and (avg_delta is None or avg_delta >= 0):
        decision = "MONITOR_MORE"
        quality_flag = "MIXED_POSITIVE"
        reason = "Total R positif, tapi realistic/drawdown/concentration belum cukup bersih untuk kandidat kalibrasi."
    elif v3_total < 0:
        decision = "DO_NOT_PROMOTE"
        quality_flag = "WEAK_SHADOW"
        reason = "Total R V3 masih negatif."
    else:
        decision = "INCONCLUSIVE"
        quality_flag = "NO_CLEAR_EDGE"
        reason = "Belum ada gap kualitas yang jelas terhadap V2."

    return {
        "stage": row.get("stage"),
        "timeframe": row.get("timeframe"),
        "decision": decision,
        "quality_flag": quality_flag,
        "reason": reason,
        "v2_evaluated": int(v2_perf.get("signals_evaluated") or 0),
        "v2_closed_count": int(v2_perf.get("closed_count") or 0),
        "v2_total_r_closed": v2_perf.get("total_r_closed"),
        "v2_realistic_total_r_closed": v2_perf.get("realistic_total_r_closed"),
        "v2_max_drawdown_r": v2.get("drawdown", {}).get("max_drawdown_r"),
        "v3_signal_count": int(row.get("v3_shadow_signal_count") or 0),
        "v3_closed_count": v3_closed,
        "v3_total_r_closed": v3_perf.get("total_r_closed"),
        "v3_realistic_total_r_closed": v3_perf.get("realistic_total_r_closed"),
        "v3_avg_r_closed": v3_perf.get("avg_r_closed"),
        "v3_realistic_avg_r_closed": v3_perf.get("realistic_avg_r_closed"),
        "v3_winrate_pct": v3_perf.get("winrate_pct"),
        "v3_max_drawdown_r": v3.get("drawdown", {}).get("max_drawdown_r"),
        "v3_top_symbol": v3_quality.get("top_symbol"),
        "v3_top_symbol_share_pct": v3_quality.get("top_symbol_share_pct"),
        "v3_symbol_count": v3_quality.get("symbol_count"),
        "retention_pct": row.get("v3_sample_retention_pct"),
        "total_r_delta_vs_v2": row.get("total_r_delta_v3_vs_v2"),
        "avg_r_delta_vs_v2": row.get("avg_r_delta_v3_vs_v2"),
        "realistic_total_r_delta_vs_v2": _decimal_delta(
            v3_perf.get("realistic_total_r_closed"),
            v2_perf.get("realistic_total_r_closed"),
        ),
        "max_drawdown_delta_vs_v2": row.get("max_drawdown_delta_v3_vs_v2"),
        "read": row.get("read"),
    }


def _v3_filter_decision(row: dict[str, Any], *, min_sample: int) -> dict[str, Any]:
    closed = int(row.get("closed_count") or 0)
    total_r = _decimal_or_zero(row.get("total_r_closed"))
    realistic_total = _decimal_or_zero(row.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_none_any(row.get("avg_r_delta_vs_v2"))
    sl_delta = _decimal_or_none_any(row.get("sl_share_delta_vs_v2"))
    if closed < min_sample:
        decision = "WAIT_SAMPLE"
        reason = f"Closed sample {closed} masih di bawah minimum {min_sample}."
    elif total_r > 0 and realistic_total > 0 and avg_delta is not None and avg_delta > 0 and (sl_delta is None or sl_delta <= 0):
        decision = "V4_FILTER_CANDIDATE"
        reason = "Filter punya ideal/realistic R positif, avg R membaik, dan SL share tidak naik."
    elif total_r > 0 and avg_delta is not None and avg_delta >= 0:
        decision = "MONITOR_MORE"
        reason = "Filter positif, tapi belum cukup bersih dari sisi realistic R atau SL share."
    elif total_r < 0:
        decision = "DO_NOT_PROMOTE"
        reason = "Filter menghasilkan total R negatif."
    else:
        decision = "INCONCLUSIVE"
        reason = "Belum ada pemisahan TP/SL yang jelas."
    return {
        "filter_id": row.get("filter_id"),
        "filter_label": row.get("label"),
        "expression": row.get("expression"),
        "decision": decision,
        "reason": reason,
        "sample_count": int(row.get("sample_count") or 0),
        "closed_count": closed,
        "tp_count": int(row.get("tp_count") or 0),
        "sl_count": int(row.get("sl_count") or 0),
        "open_count": int(row.get("open_count") or 0),
        "total_r_closed": row.get("total_r_closed"),
        "realistic_total_r_closed": row.get("realistic_total_r_closed"),
        "avg_r_closed": row.get("avg_r_closed"),
        "realistic_avg_r_closed": row.get("realistic_avg_r_closed"),
        "winrate_pct": row.get("winrate_pct"),
        "avg_r_delta_vs_v2": row.get("avg_r_delta_vs_v2"),
        "sl_share_delta_vs_v2": row.get("sl_share_delta_vs_v2"),
        "verdict": row.get("verdict"),
    }


def _v3_audit_risk_flags(
    stage_decisions: list[dict[str, Any]],
    filter_decisions: list[dict[str, Any]],
    v3_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    v3_perf = v3_summary["performance"]
    penalty = _decimal_or_zero(v3_perf.get("realism_penalty_r_closed"))
    if penalty > Decimal("5"):
        flags.append(
            {
                "flag": "REALISTIC_COST_DRAG",
                "severity": "WARN",
                "detail": f"Realistic R turun {penalty}R dari ideal; spread/fee/slippage perlu tetap dipantau.",
            }
        )
    for decision in stage_decisions:
        share = _decimal_or_none_any(decision.get("v3_top_symbol_share_pct"))
        if share is not None and share > Decimal("35") and int(decision.get("v3_signal_count") or 0) > 0:
            flags.append(
                {
                    "flag": "HIGH_SYMBOL_CONCENTRATION",
                    "severity": "WARN",
                    "detail": f"{decision.get('stage')} {decision.get('timeframe')} didominasi {decision.get('v3_top_symbol')} ({share}%).",
                }
            )
    if not any(decision["decision"] == "V4_FILTER_CANDIDATE" for decision in filter_decisions):
        flags.append(
            {
                "flag": "NO_FILTER_CANDIDATE_YET",
                "severity": "INFO",
                "detail": "Belum ada filter V3 yang cukup bersih untuk studi V4.",
            }
        )
    return flags


def _v3_failure_analysis(
    *,
    v2_items: list[dict[str, Any]],
    v3_items: list[dict[str, Any]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    v3_closed = [item for item in v3_items if item.get("result_status") in COMPLETED_OUTCOMES]
    v3_tp = [item for item in v3_closed if item.get("result_status") == "TP_HIT"]
    v3_sl = [item for item in v3_closed if item.get("result_status") == "SL_HIT"]
    v3_both = [item for item in v3_closed if item.get("result_status") == "BOTH_HIT_SAME_CANDLE"]
    v2_closed = [item for item in v2_items if item.get("result_status") in COMPLETED_OUTCOMES]
    v3_perf = _performance_summary(v3_items)
    v2_perf = _performance_summary(v2_items)
    evidence_rows = _evidence_field_rows(v3_closed, min_sample=max(3, min_sample))
    useful_evidence = [
        row
        for row in evidence_rows
        if row.get("quality_flag") not in {"SAMPLE_TOO_SMALL", "NO_CLEAR_GAP"}
    ][:limit]
    filter_rows = _v3_failure_bucket_rows(
        v3_items,
        key="v3_shadow_filter_id",
        label_key="v3_shadow_filter_label",
        min_sample=min_sample,
        limit=limit,
    )
    symbol_loss_rows = _v3_failure_bucket_rows(
        v3_sl,
        key="symbol",
        label_key=None,
        min_sample=1,
        limit=limit,
        sort_by_loss=True,
    )
    lane_rows = _v3_failure_lane_rows(v3_items, min_sample=min_sample)
    return {
        "scope": "v3_failure_analysis_read_only",
        "readiness_verdict": _v3_failure_readiness(v2_perf=v2_perf, v3_perf=v3_perf, min_sample=min_sample),
        "failure_read": _v3_failure_read(v3_perf=v3_perf, useful_evidence=useful_evidence, filter_rows=filter_rows),
        "summary": {
            "v2_closed_count": len(v2_closed),
            "v3_closed_count": len(v3_closed),
            "v3_tp_count": len(v3_tp),
            "v3_sl_count": len(v3_sl),
            "v3_both_count": len(v3_both),
            "v3_open_count": int(v3_perf.get("open_count") or 0),
            "v3_total_r_closed": v3_perf.get("total_r_closed"),
            "v3_realistic_total_r_closed": v3_perf.get("realistic_total_r_closed"),
            "v3_winrate_pct": v3_perf.get("winrate_pct"),
            "v3_sl_share_pct": _sl_share(v3_perf),
            "v3_retention_closed_pct": _retention(len(v3_closed), len(v2_closed)),
            "realistic_total_r_delta_vs_v2": _decimal_delta(
                v3_perf.get("realistic_total_r_closed"),
                v2_perf.get("realistic_total_r_closed"),
            ),
        },
        "evidence_tp_vs_sl": evidence_rows,
        "top_evidence_gaps": useful_evidence,
        "loss_by_filter": filter_rows,
        "loss_by_symbol": symbol_loss_rows,
        "loss_by_lane": lane_rows,
        "latest_v3_sl_signals": _sorted_signal_rows(v3_sl, limit=min(limit, 25)),
        "latest_v3_tp_signals": _sorted_signal_rows(v3_tp, limit=min(limit, 25)),
        "guardrails": [
            "Failure analysis only reads V3 shadow pass outcomes.",
            "It does not create V4, change V2 rules, change scanner behavior, change TP/SL, or execute orders.",
            "Use this analysis to decide whether V3 is complete or still needs refinement.",
        ],
    }


def _v3_higher_timeframe_quality_audit(
    *,
    v2_items: list[dict[str, Any]],
    v3_items: list[dict[str, Any]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    higher_timeframes = ("1h", "4h", "24h")
    stages = ("MID_LONG", "MID_SHORT", "EARLY_LONG", "EARLY_SHORT")
    lane_rows: list[dict[str, Any]] = []
    timeframe_rows: list[dict[str, Any]] = []

    for timeframe in higher_timeframes:
        timeframe_v2 = [item for item in v2_items if item.get("timeframe") == timeframe]
        timeframe_v3 = [item for item in v3_items if item.get("timeframe") == timeframe]
        timeframe_perf = _performance_summary(timeframe_v3)
        timeframe_v2_perf = _performance_summary(timeframe_v2)
        timeframe_rows.append(
            {
                "timeframe": timeframe,
                "v2_signal_count": len(timeframe_v2),
                "v3_signal_count": len(timeframe_v3),
                "v3_closed_count": int(timeframe_perf.get("closed_count") or 0),
                "v3_tp_count": int(timeframe_perf.get("tp_count") or 0),
                "v3_sl_count": int(timeframe_perf.get("sl_count") or 0),
                "v3_total_r_closed": timeframe_perf.get("total_r_closed"),
                "v3_realistic_total_r_closed": timeframe_perf.get("realistic_total_r_closed"),
                "v3_winrate_pct": timeframe_perf.get("winrate_pct"),
                "v3_sl_share_pct": _sl_share(timeframe_perf),
                "realistic_avg_delta_vs_v2": _decimal_delta(
                    timeframe_perf.get("realistic_avg_r_closed"),
                    timeframe_v2_perf.get("realistic_avg_r_closed"),
                ),
                "verdict": _v3_higher_timeframe_verdict(timeframe_perf, timeframe_v2_perf, min_sample=min_sample),
                "read": _v3_higher_timeframe_read(timeframe, "ALL", timeframe_perf, timeframe_v2_perf, None, None, None, min_sample=min_sample),
            }
        )

        for stage in stages:
            lane_v2 = [item for item in timeframe_v2 if item.get("stage") == stage]
            lane_v3 = [item for item in timeframe_v3 if item.get("stage") == stage]
            lane_closed = [item for item in lane_v3 if item.get("result_status") in COMPLETED_OUTCOMES]
            lane_sl = [item for item in lane_closed if item.get("result_status") == "SL_HIT"]
            lane_perf = _performance_summary(lane_v3)
            lane_v2_perf = _performance_summary(lane_v2)
            evidence_rows = _evidence_field_rows(lane_closed, min_sample=max(3, min_sample))
            evidence_gap = next(
                (
                    row
                    for row in evidence_rows
                    if row.get("quality_flag") not in {"SAMPLE_TOO_SMALL", "NO_CLEAR_GAP"}
                ),
                None,
            )
            worst_filter = next(
                (
                    row
                    for row in _v3_failure_bucket_rows(
                        lane_v3,
                        key="v3_shadow_filter_id",
                        label_key="v3_shadow_filter_label",
                        min_sample=1,
                        limit=limit,
                    )
                    if int(row.get("sl_count") or 0) > 0
                ),
                None,
            )
            worst_symbol = next(
                (
                    row
                    for row in _v3_failure_bucket_rows(
                        lane_sl,
                        key="symbol",
                        label_key=None,
                        min_sample=1,
                        limit=limit,
                        sort_by_loss=True,
                    )
                    if int(row.get("sl_count") or 0) > 0
                ),
                None,
            )
            verdict = _v3_higher_timeframe_verdict(lane_perf, lane_v2_perf, min_sample=min_sample)
            lane_rows.append(
                {
                    "stage": stage,
                    "timeframe": timeframe,
                    "v2_signal_count": len(lane_v2),
                    "v3_signal_count": len(lane_v3),
                    "v3_closed_count": int(lane_perf.get("closed_count") or 0),
                    "v3_tp_count": int(lane_perf.get("tp_count") or 0),
                    "v3_sl_count": int(lane_perf.get("sl_count") or 0),
                    "v3_both_count": int(lane_perf.get("both_hit_count") or 0),
                    "v3_open_count": int(lane_perf.get("open_count") or 0),
                    "v3_total_r_closed": lane_perf.get("total_r_closed"),
                    "v3_realistic_total_r_closed": lane_perf.get("realistic_total_r_closed"),
                    "v3_avg_r_closed": lane_perf.get("avg_r_closed"),
                    "v3_realistic_avg_r_closed": lane_perf.get("realistic_avg_r_closed"),
                    "v3_winrate_pct": lane_perf.get("winrate_pct"),
                    "v3_sl_share_pct": _sl_share(lane_perf),
                    "realistic_avg_delta_vs_v2": _decimal_delta(
                        lane_perf.get("realistic_avg_r_closed"),
                        lane_v2_perf.get("realistic_avg_r_closed"),
                    ),
                    "worst_filter_id": worst_filter.get("bucket") if worst_filter else None,
                    "worst_filter_label": worst_filter.get("label") if worst_filter else None,
                    "worst_filter_sl_count": int(worst_filter.get("sl_count") or 0) if worst_filter else 0,
                    "worst_symbol": worst_symbol.get("bucket") if worst_symbol else None,
                    "worst_symbol_sl_count": int(worst_symbol.get("sl_count") or 0) if worst_symbol else 0,
                    "top_evidence_field": evidence_gap.get("field") if evidence_gap else None,
                    "top_evidence_label": evidence_gap.get("label") if evidence_gap else None,
                    "top_evidence_quality_flag": evidence_gap.get("quality_flag") if evidence_gap else None,
                    "top_evidence_tp_median": evidence_gap.get("tp_median") if evidence_gap else None,
                    "top_evidence_sl_median": evidence_gap.get("sl_median") if evidence_gap else None,
                    "verdict": verdict,
                    "read": _v3_higher_timeframe_read(
                        timeframe,
                        stage,
                        lane_perf,
                        lane_v2_perf,
                        worst_filter,
                        worst_symbol,
                        evidence_gap,
                        min_sample=min_sample,
                    ),
                }
            )

    active_lanes = [row for row in lane_rows if int(row.get("v3_signal_count") or 0) > 0]
    ready_lanes = [row for row in lane_rows if int(row.get("v3_closed_count") or 0) >= min_sample]
    noisy_lanes = [row for row in ready_lanes if row.get("verdict") in {"LOSS_HEAVY", "REALISTIC_NEGATIVE", "COST_DRAG"}]
    monitor_lanes = [row for row in ready_lanes if row.get("verdict") in {"MONITOR_CANDIDATE", "PARTIAL_IMPROVEMENT"}]
    lane_rows.sort(
        key=lambda row: (
            row.get("timeframe") not in {"1h", "4h", "24h"},
            {"1h": 0, "4h": 1, "24h": 2}.get(str(row.get("timeframe")), 99),
            int(row.get("v3_signal_count") or 0) == 0,
            str(row.get("stage") or ""),
        )
    )
    return {
        "scope": "v3_higher_timeframe_quality_audit_read_only",
        "timeframes": list(higher_timeframes),
        "summary": {
            "higher_timeframe_v2_signal_count": sum(int(row.get("v2_signal_count") or 0) for row in timeframe_rows),
            "higher_timeframe_v3_signal_count": sum(int(row.get("v3_signal_count") or 0) for row in timeframe_rows),
            "higher_timeframe_v3_closed_count": sum(int(row.get("v3_closed_count") or 0) for row in timeframe_rows),
            "active_lane_count": len(active_lanes),
            "ready_lane_count": len(ready_lanes),
            "monitor_lane_count": len(monitor_lanes),
            "noisy_lane_count": len(noisy_lanes),
            "waiting_lane_count": len([row for row in lane_rows if int(row.get("v3_signal_count") or 0) == 0]),
            "audit_readiness": _v3_higher_timeframe_audit_readiness(ready_lanes, monitor_lanes, noisy_lanes),
        },
        "timeframe_rows": timeframe_rows,
        "lane_rows": lane_rows,
        "priority_lanes": sorted(
            [row for row in lane_rows if int(row.get("v3_closed_count") or 0) >= min_sample],
            key=lambda row: (
                row.get("verdict") in {"MONITOR_CANDIDATE", "PARTIAL_IMPROVEMENT"},
                Decimal(row.get("v3_realistic_total_r_closed") or 0),
                Decimal(row.get("v3_total_r_closed") or 0),
            ),
            reverse=True,
        )[:limit],
        "guardrails": [
            "Higher-timeframe quality audit only reads logged V3 shadow outcomes.",
            "1h, 4h, and 24h are evaluated separately; 15m is not mixed into these verdicts.",
            "This audit does not change Signal Factory rules, scanner behavior, TP/SL formula, or execution.",
        ],
    }


def _v3_higher_timeframe_verdict(v3_perf: dict[str, Any], v2_perf: dict[str, Any], *, min_sample: int) -> str:
    closed = int(v3_perf.get("closed_count") or 0)
    if closed <= 0:
        return "WAITING_V3_SAMPLE"
    if closed < min_sample:
        return "SAMPLE_TOO_SMALL"
    realistic_total = _decimal_or_zero(v3_perf.get("realistic_total_r_closed"))
    ideal_total = _decimal_or_zero(v3_perf.get("total_r_closed"))
    realistic_avg_delta = _decimal_delta(v3_perf.get("realistic_avg_r_closed"), v2_perf.get("realistic_avg_r_closed"))
    sl_share = _sl_share(v3_perf)
    tp_count = int(v3_perf.get("tp_count") or 0)
    sl_count = int(v3_perf.get("sl_count") or 0)
    if realistic_total > 0 and ideal_total > 0 and sl_count <= tp_count and (realistic_avg_delta is None or realistic_avg_delta >= 0):
        return "MONITOR_CANDIDATE"
    if ideal_total > 0 and realistic_total < 0:
        return "COST_DRAG"
    if realistic_total > 0 or (realistic_avg_delta is not None and realistic_avg_delta > 0):
        return "PARTIAL_IMPROVEMENT"
    if sl_count > tp_count or (sl_share is not None and sl_share > Decimal("55")):
        return "LOSS_HEAVY"
    if realistic_total < 0:
        return "REALISTIC_NEGATIVE"
    return "MIXED"


def _v3_higher_timeframe_audit_readiness(
    ready_lanes: list[dict[str, Any]],
    monitor_lanes: list[dict[str, Any]],
    noisy_lanes: list[dict[str, Any]],
) -> str:
    if not ready_lanes:
        return "WAITING_HIGHER_TIMEFRAME_SAMPLE"
    if monitor_lanes and not noisy_lanes:
        return "HIGHER_TIMEFRAME_MONITOR_READY"
    if monitor_lanes:
        return "MIXED_MONITOR_AND_NOISY_LANES"
    return "HIGHER_TIMEFRAME_NEEDS_REFINEMENT"


def _v3_higher_timeframe_read(
    timeframe: str,
    stage: str,
    v3_perf: dict[str, Any],
    v2_perf: dict[str, Any],
    worst_filter: dict[str, Any] | None,
    worst_symbol: dict[str, Any] | None,
    evidence_gap: dict[str, Any] | None,
    *,
    min_sample: int,
) -> str:
    closed = int(v3_perf.get("closed_count") or 0)
    if closed <= 0:
        return f"{stage} {timeframe}: belum ada V3 pass/sample."
    if closed < min_sample:
        return f"{stage} {timeframe}: sample closed {closed}, belum cukup untuk verdict kuat."
    verdict = _v3_higher_timeframe_verdict(v3_perf, v2_perf, min_sample=min_sample)
    parts = [
        f"{stage} {timeframe}: {verdict}",
        f"TP/SL {int(v3_perf.get('tp_count') or 0)}/{int(v3_perf.get('sl_count') or 0)}",
        f"realistic R {v3_perf.get('realistic_total_r_closed')}",
    ]
    if worst_filter:
        parts.append(f"worst filter {worst_filter.get('label')} ({worst_filter.get('sl_count')} SL)")
    if worst_symbol:
        parts.append(f"worst symbol {worst_symbol.get('bucket')} ({worst_symbol.get('sl_count')} SL)")
    if evidence_gap:
        parts.append(
            f"evidence gap {evidence_gap.get('label')} TP {evidence_gap.get('tp_median')} vs SL {evidence_gap.get('sl_median')}"
        )
    return "; ".join(parts) + "."


def _v3_failure_readiness(*, v2_perf: dict[str, Any], v3_perf: dict[str, Any], min_sample: int) -> str:
    v3_closed = int(v3_perf.get("closed_count") or 0)
    if v3_closed < min_sample:
        return "V3_NEEDS_MORE_SAMPLE"
    v3_realistic = _decimal_or_zero(v3_perf.get("realistic_total_r_closed"))
    v3_total = _decimal_or_zero(v3_perf.get("total_r_closed"))
    avg_delta = _decimal_delta(v3_perf.get("realistic_avg_r_closed"), v2_perf.get("realistic_avg_r_closed"))
    sl_delta = _decimal_delta(_sl_share(v3_perf), _sl_share(v2_perf))
    if v3_realistic > 0 and v3_total > 0 and avg_delta is not None and avg_delta > 0 and (sl_delta is None or sl_delta <= 0):
        return "V3_FORWARD_STABLE_ENOUGH_TO_MONITOR"
    if v3_realistic > 0 or (avg_delta is not None and avg_delta > 0):
        return "V3_PARTIAL_IMPROVEMENT_NEEDS_FAILURE_REFINEMENT"
    if v3_realistic < 0:
        return "V3_RULE_TOO_NOISY"
    return "V3_INCONCLUSIVE"


def _v3_failure_read(
    *,
    v3_perf: dict[str, Any],
    useful_evidence: list[dict[str, Any]],
    filter_rows: list[dict[str, Any]],
) -> str:
    if int(v3_perf.get("closed_count") or 0) <= 0:
        return "Belum ada V3 closed sample untuk dibedah."
    worst_filter = next((row for row in filter_rows if int(row.get("sl_count") or 0) > 0), None)
    best_gap = useful_evidence[0] if useful_evidence else None
    parts: list[str] = []
    if worst_filter:
        parts.append(f"Filter dengan SL terbanyak: {worst_filter.get('label')} ({worst_filter.get('sl_count')} SL).")
    if best_gap:
        parts.append(
            f"Evidence gap terbesar: {best_gap.get('label')} "
            f"TP median {best_gap.get('tp_median')} vs SL median {best_gap.get('sl_median')}."
        )
    if not parts:
        return "V3 belum menunjukkan pemisahan TP vs SL yang bersih; lanjut collect sample atau cari evidence baru."
    return " ".join(parts)


def _v3_failure_bucket_rows(
    items: list[dict[str, Any]],
    *,
    key: str,
    label_key: str | None,
    min_sample: int,
    limit: int,
    sort_by_loss: bool = False,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, str] = {}
    expressions: dict[str, str] = {}
    for item in items:
        bucket = str(item.get(key) or "UNKNOWN")
        grouped[bucket].append(item)
        labels[bucket] = str(item.get(label_key) or bucket) if label_key else bucket
        expressions[bucket] = str(item.get("v3_shadow_filter_expression") or "")
    rows: list[dict[str, Any]] = []
    for bucket, bucket_items in grouped.items():
        perf = _performance_summary(bucket_items)
        sl_count = int(perf.get("sl_count") or 0)
        row = {
            "bucket": bucket,
            "label": labels.get(bucket, bucket),
            "expression": expressions.get(bucket, ""),
            "sample_count": len(bucket_items),
            "sl_share_pct": _sl_share(perf),
            "read": _v3_failure_bucket_read(perf, min_sample=min_sample),
            **perf,
        }
        rows.append(row)
    if sort_by_loss:
        rows.sort(
            key=lambda row: (
                int(row.get("sl_count") or 0),
                Decimal(row.get("realistic_total_r_closed") or 0) * Decimal("-1"),
                int(row.get("sample_count") or 0),
            ),
            reverse=True,
        )
    else:
        rows.sort(
            key=lambda row: (
                int(row.get("closed_count") or 0) >= min_sample,
                int(row.get("sl_count") or 0),
                Decimal(row.get("realistic_total_r_closed") or 0) * Decimal("-1"),
                int(row.get("sample_count") or 0),
            ),
            reverse=True,
        )
    return rows[:limit]


def _v3_failure_bucket_read(perf: dict[str, Any], *, min_sample: int) -> str:
    closed = int(perf.get("closed_count") or 0)
    if closed < min_sample:
        return "WAIT_SAMPLE"
    if Decimal(perf.get("realistic_total_r_closed") or 0) > 0 and int(perf.get("sl_count") or 0) <= int(perf.get("tp_count") or 0):
        return "FILTER_HEALTHY"
    if int(perf.get("sl_count") or 0) > int(perf.get("tp_count") or 0):
        return "LOSS_HEAVY"
    return "MIXED"


def _v3_failure_lane_rows(items: list[dict[str, Any]], *, min_sample: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[(str(item.get("stage") or "UNKNOWN"), str(item.get("timeframe") or "UNKNOWN"))].append(item)
    rows: list[dict[str, Any]] = []
    for (stage, timeframe), lane_items in grouped.items():
        perf = _performance_summary(lane_items)
        rows.append(
            {
                "stage": stage,
                "timeframe": timeframe,
                "sample_count": len(lane_items),
                "sl_share_pct": _sl_share(perf),
                "read": _v3_failure_bucket_read(perf, min_sample=min_sample),
                **perf,
            }
        )
    rows.sort(
        key=lambda row: (
            int(row.get("sl_count") or 0),
            Decimal(row.get("realistic_total_r_closed") or 0) * Decimal("-1"),
            int(row.get("sample_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _sorted_signal_rows(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (_parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol") or "")),
        reverse=True,
    )[:limit]


def _retention(count: int, total: int) -> Decimal | None:
    if total <= 0:
        return None
    return Decimal(count) / Decimal(total) * Decimal("100")


def _v3_comparison_read(v2: dict[str, Any], v3_pass: dict[str, Any], pass_count: int, *, min_sample: int) -> str:
    if pass_count < min_sample:
        return "V3_SAMPLE_TOO_SMALL"
    avg_delta = _decimal_delta(v3_pass.get("avg_r_closed"), v2.get("avg_r_closed"))
    sl_delta = _decimal_delta(_sl_share(v3_pass), _sl_share(v2))
    total_r = Decimal(v3_pass.get("total_r_closed") or 0)
    if avg_delta is not None and avg_delta > Decimal("0.05") and (sl_delta is None or sl_delta <= 0) and total_r > 0:
        return "V3_SHADOW_IMPROVES_V2"
    if avg_delta is not None and avg_delta > 0:
        return "V3_SHADOW_MONITOR_MORE"
    if avg_delta is not None and avg_delta < 0:
        return "V3_SHADOW_WEAKER_THAN_V2"
    return "V3_SHADOW_INCONCLUSIVE"


def _v3_bucket_verdict(row: dict[str, Any], *, min_sample: int) -> str:
    if int(row.get("closed_count") or 0) < min_sample:
        return "SAMPLE_TOO_SMALL"
    avg_delta = row.get("avg_r_delta_vs_v2")
    sl_delta = row.get("sl_share_delta_vs_v2")
    total_r = Decimal(row.get("total_r_closed") or 0)
    if avg_delta is not None and Decimal(avg_delta) > Decimal("0.05") and total_r > 0 and (sl_delta is None or Decimal(sl_delta) <= 0):
        return "BETTER_THAN_V2_BASELINE"
    if avg_delta is not None and Decimal(avg_delta) > 0:
        return "MONITOR_MORE"
    if avg_delta is not None and Decimal(avg_delta) < 0:
        return "WEAKER_THAN_V2_BASELINE"
    return "INCONCLUSIVE"


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


def _signal_chart_payload(
    signal: SignalForwardReturnLog,
    item: dict[str, Any],
    candles: list[PerfCandle],
) -> dict[str, Any]:
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    latest_candle = ordered[-1] if ordered else None
    result_time = _parse_dt(item.get("result_time_utc"))
    box_end_time = result_time or (latest_candle.close_time if latest_candle else _naive(signal.signal_timestamp))
    return {
        "market": "BINANCE_USDS_M_FUTURES",
        "price_source": "local closed futures candles",
        "display_interval": "15m_closed_plus_1m_tail",
        "candle_count": len(ordered),
        "signal_time": signal.signal_timestamp,
        "signal_time_wib": _wib_string(signal.signal_timestamp),
        "result_time": result_time,
        "result_time_wib": _wib_string(result_time),
        "box_end_time": box_end_time,
        "direction": signal.direction,
        "result_status": item.get("result_status"),
        "entry": item.get("entry"),
        "stop_loss": item.get("stop_loss"),
        "take_profit": item.get("take_profit"),
        "latest_price": item.get("exit_price"),
        "latest_candle_time": latest_candle.close_time if latest_candle else None,
        "candles": [
            {
                "open_time": candle.open_time,
                "close_time": candle.close_time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "source_interval": candle.source_interval,
            }
            for candle in ordered
        ],
    }


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


def signal_factory_v3_shadow_for_candidate(
    candidate: dict[str, Any],
    filter_map: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    merged = {**evidence, **candidate}
    item = {
        "stage": candidate.get("setup_type") or candidate.get("stage") or "UNKNOWN",
        "timeframe": candidate.get("timeframe") or "15m",
        "evidence_snapshot": _evidence_snapshot_from_mapping(merged),
    }
    return _v3_shadow_result_for_item(item, filter_map)


def _evidence_snapshot_from_mapping(evidence: dict[str, Any]) -> dict[str, Decimal | None]:
    snapshot: dict[str, Decimal | None] = {}
    for field, _label in EVIDENCE_FIELDS:
        snapshot[field] = _decimal_or_none(evidence.get(field))
    return snapshot


def _signal_strategy_version(signal: SignalForwardReturnLog) -> str:
    raw_evidence = signal.evidence if isinstance(signal.evidence, dict) else {}
    nested = raw_evidence.get("evidence") if isinstance(raw_evidence.get("evidence"), dict) else {}
    version = (
        raw_evidence.get("signal_factory_version")
        or nested.get("signal_factory_version")
        or nested.get("logic_version")
        or LIVE_STRATEGY_VERSION
    )
    return str(version)


def _apply_v3_shadow(items: list[dict[str, Any]], *, min_sample: int) -> None:
    filter_map = _v3_shadow_filter_map(items, min_sample=min_sample, limit=100)
    for item in items:
        item.update(_v3_shadow_result_for_item(item, filter_map))


def _v3_shadow_filter_map(
    items: list[dict[str, Any]],
    *,
    min_sample: int,
    limit: int,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    specs = {spec.filter_id: spec for spec in _filter_study_specs()}
    filter_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for stage in ("EARLY_LONG", "EARLY_SHORT", "MID_LONG", "MID_SHORT"):
        for timeframe in ("15m", "1h", "4h", "24h"):
            lane_items = [
                item
                for item in items
                if item.get("stage") == stage and item.get("timeframe") == timeframe
            ]
            lane = _calibration_lane(
                stage=stage,
                timeframe=timeframe,
                items=lane_items,
                min_sample=min_sample,
                limit=limit,
            )
            selected: list[dict[str, Any]] = []
            for row in lane["filter_candidates"]:
                spec = specs.get(str(row.get("filter_id")))
                if spec is None or row.get("promotion_status") != "V3_CANDIDATE":
                    continue
                selected.append(
                    {
                        "filter_id": row["filter_id"],
                        "label": row["label"],
                        "expression": row["expression"],
                        "promotion_score": row["promotion_score"],
                        "promotion_reasons": row["promotion_reasons"],
                        "_spec": spec,
                    }
                )
            filter_map[(stage, timeframe)] = selected
    return filter_map


def _v3_shadow_result_for_item(
    item: dict[str, Any],
    filter_map: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    stage = str(item.get("stage") or "UNKNOWN")
    timeframe = str(item.get("timeframe") or "15m")
    filters = filter_map.get((stage, timeframe), [])
    base = {
        "strategy_version": LIVE_STRATEGY_VERSION,
        "strategy_family": "Signal Factory V2",
        "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
        "v3_shadow_filter_count": len(filters),
        "v3_shadow_status": "V3_SHADOW_NO_FILTER",
        "v3_shadow_filter_id": None,
        "v3_shadow_filter_label": None,
        "v3_shadow_filter_expression": None,
        "v3_shadow_promotion_score": None,
        "v3_shadow_reason": "No V3_CANDIDATE filter exists for this stage/timeframe yet.",
    }
    if not filters:
        return base

    missing_fields: set[str] = set()
    evaluated_filter_count = 0
    for row in filters:
        spec: FilterStudySpec = row["_spec"]
        missing = [
            field
            for field in spec.required_fields
            if (item.get("evidence_snapshot") or {}).get(field) is None
        ]
        if missing:
            missing_fields.update(missing)
            continue
        evaluated_filter_count += 1
        if spec.predicate(item):
            return {
                **base,
                "v3_shadow_status": "V3_SHADOW_PASS",
                "v3_shadow_filter_id": row["filter_id"],
                "v3_shadow_filter_label": row["label"],
                "v3_shadow_filter_expression": row["expression"],
                "v3_shadow_promotion_score": row["promotion_score"],
                "v3_shadow_reason": f"Matched V3 calibration filter: {row['label']}.",
            }

    if evaluated_filter_count == 0:
        return {
            **base,
            "v3_shadow_status": "V3_SHADOW_UNAVAILABLE",
            "v3_shadow_reason": "Required V3 filter evidence missing: " + ", ".join(sorted(missing_fields)),
        }
    return {
        **base,
        "v3_shadow_status": "V3_SHADOW_FAIL",
        "v3_shadow_reason": "V3 calibration filters exist for this lane, but this signal evidence did not match them.",
    }


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


def _decimal_or_none_any(value: Any) -> Decimal | None:
    return _decimal_or_none(value)


def _decimal_or_zero(value: Any) -> Decimal:
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None else Decimal("0")


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


def _volume_rank_rows(items: list[dict[str, Any]], *, min_sample: int) -> list[dict[str, Any]]:
    specs = [
        ("TOP_5_VOLUME", "Top 5 volume rank", 5),
        ("TOP_10_VOLUME", "Top 10 volume rank", 10),
        ("TOP_20_VOLUME", "Top 20 volume rank", 20),
        ("ALL_VOLUME", "All ranked/all signals", None),
    ]
    missing_rank_count = sum(1 for item in items if _rank_value(item) is None)
    rows: list[dict[str, Any]] = []
    for bucket, label, cutoff in specs:
        if cutoff is None:
            bucket_items = items
            scope = "all signals in current filter"
        else:
            bucket_items = [item for item in items if (rank := _rank_value(item)) is not None and rank <= cutoff]
            scope = f"universe_rank <= {cutoff}"
        row = _bucket_summary(bucket, bucket_items, min_sample=min_sample)
        row.update(
            {
                "label": label,
                "rank_cutoff": cutoff,
                "rank_scope": scope,
                "missing_rank_count": missing_rank_count if cutoff is None else 0,
            }
        )
        rows.append(row)
    return rows


def _v2_profit_loss_research(items: list[dict[str, Any]], *, min_sample: int, limit: int) -> dict[str, Any]:
    perf = _performance_summary(items)
    evidence_rows = _evidence_field_rows(items, min_sample=min_sample)
    driver_rows = [
        _tp_driver_row(row)
        for row in evidence_rows
        if row["quality_flag"] in {"TP_HIGHER", "SL_HIGHER"}
    ][:limit]

    return {
        "scope": "v2_profit_loss_research_read_only",
        "method": (
            "Compare closed V2 Signal outcomes by TP/SL evidence medians, stage/timeframe lanes, "
            "and realistic execution drag. This is analysis only and does not alter live rules."
        ),
        "summary": {
            **perf,
            "sl_share_pct": _sl_share(perf),
            "realistic_read": _v2_realistic_read(perf, min_sample=min_sample),
        },
        "tp_drivers": driver_rows,
        "lane_rows": _v2_profit_loss_lane_rows(items, min_sample=min_sample, limit=limit),
        "realistic_drag": _v2_realistic_drag_sections(items, min_sample=min_sample, limit=limit),
        "read": _v2_profit_loss_research_read(perf, driver_rows, min_sample=min_sample),
        "guardrails": [
            "Read-only V2 research; no Signal Factory rule changed.",
            "No TP/SL formula, classifier threshold, scanner behavior, or outcome calculation changed.",
            "Rows explain why existing V2 signals TP/SL; they are not execution instructions.",
        ],
    }


def _tp_driver_row(row: dict[str, Any]) -> dict[str, Any]:
    delta = row.get("delta_tp_minus_sl")
    return {
        "field": row["field"],
        "label": row["label"],
        "quality_flag": row["quality_flag"],
        "direction_read": "TP median higher than SL" if delta is not None and Decimal(delta) > 0 else "TP median lower than SL",
        "available_count": row["available_count"],
        "missing_count": row["missing_count"],
        "available_pct": row["available_pct"],
        "tp_count": row["tp_count"],
        "sl_count": row["sl_count"],
        "tp_median": row["tp_median"],
        "sl_median": row["sl_median"],
        "tp_q1": row["tp_q1"],
        "tp_q3": row["tp_q3"],
        "sl_q1": row["sl_q1"],
        "sl_q3": row["sl_q3"],
        "delta_tp_minus_sl": delta,
        "read": _tp_driver_read(row),
    }


def _tp_driver_read(row: dict[str, Any]) -> str:
    field = row["label"]
    flag = row["quality_flag"]
    if flag == "TP_HIGHER":
        return f"{field} cenderung lebih tinggi pada TP daripada SL dalam filter saat ini."
    if flag == "SL_HIGHER":
        return f"{field} cenderung lebih tinggi pada SL daripada TP dalam filter saat ini."
    return f"{field} belum punya gap TP/SL yang bersih."


def _v2_profit_loss_lane_rows(items: list[dict[str, Any]], *, min_sample: int, limit: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[(str(item.get("stage") or "UNKNOWN"), str(item.get("timeframe") or "UNKNOWN"))].append(item)

    rows = []
    for (stage, timeframe), lane_items in groups.items():
        perf = _performance_summary(lane_items)
        evidence_gap = _top_evidence_gap(lane_items, min_sample=min_sample)
        row = {
            "stage": stage,
            "timeframe": timeframe,
            "sample_count": len(lane_items),
            "sl_share_pct": _sl_share(perf),
            "realistic_read": _v2_realistic_read(perf, min_sample=min_sample),
            "top_evidence_gap": evidence_gap,
            "top_loss_symbol": _top_symbol_by_realistic_r(lane_items, reverse=False),
            "top_profit_symbol": _top_symbol_by_realistic_r(lane_items, reverse=True),
            **perf,
        }
        rows.append(row)

    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0) < min_sample,
            Decimal(row.get("realistic_total_r_closed") or 0),
            int(row.get("sample_count") or 0),
        )
    )
    return rows[:limit]


def _top_evidence_gap(items: list[dict[str, Any]], *, min_sample: int) -> dict[str, Any] | None:
    rows = [
        row
        for row in _evidence_field_rows(items, min_sample=min_sample)
        if row["quality_flag"] in {"TP_HIGHER", "SL_HIGHER"}
    ]
    if not rows:
        return None
    row = rows[0]
    return {
        "field": row["field"],
        "label": row["label"],
        "quality_flag": row["quality_flag"],
        "tp_median": row["tp_median"],
        "sl_median": row["sl_median"],
        "delta_tp_minus_sl": row["delta_tp_minus_sl"],
    }


def _top_symbol_by_realistic_r(items: list[dict[str, Any]], *, reverse: bool) -> dict[str, Any] | None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[str(item.get("symbol") or "UNKNOWN")].append(item)
    rows = []
    for symbol, symbol_items in groups.items():
        perf = _performance_summary(symbol_items)
        rows.append(
            {
                "symbol": symbol,
                "sample_count": len(symbol_items),
                "closed_count": perf["closed_count"],
                "tp_count": perf["tp_count"],
                "sl_count": perf["sl_count"],
                "total_r_closed": perf["total_r_closed"],
                "realistic_total_r_closed": perf["realistic_total_r_closed"],
            }
        )
    if not rows:
        return None
    rows.sort(key=lambda row: Decimal(row.get("realistic_total_r_closed") or 0), reverse=reverse)
    return rows[0]


def _v2_realistic_drag_sections(items: list[dict[str, Any]], *, min_sample: int, limit: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "by_symbol": _v2_realistic_drag_rows(items, key="symbol", min_sample=min_sample, limit=limit),
        "by_stage": _v2_realistic_drag_rows(items, key="stage", min_sample=min_sample, limit=limit),
        "by_timeframe": _v2_realistic_drag_rows(items, key="timeframe", min_sample=min_sample, limit=limit),
        "by_confidence": _v2_realistic_drag_rows(items, key="confidence_tier", min_sample=min_sample, limit=limit),
        "by_fill_quality": _v2_realistic_drag_rows(items, key="realistic_fill_quality", min_sample=min_sample, limit=limit),
    }


def _v2_realistic_drag_rows(
    items: list[dict[str, Any]],
    *,
    key: str,
    min_sample: int,
    limit: int,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[str(item.get(key) or "UNKNOWN")].append(item)

    rows = []
    for bucket, bucket_items in groups.items():
        perf = _performance_summary(bucket_items)
        closed_count = int(perf.get("closed_count") or 0)
        penalty = Decimal(perf.get("realism_penalty_r_closed") or 0)
        row = {
            "dimension": key,
            "bucket": bucket,
            "sample_count": len(bucket_items),
            "sl_share_pct": _sl_share(perf),
            "avg_penalty_r_closed": (penalty / Decimal(closed_count)) if closed_count else None,
            "realistic_read": _v2_realistic_read(perf, min_sample=min_sample),
            **perf,
        }
        rows.append(row)

    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0) < min_sample,
            Decimal(row.get("realistic_total_r_closed") or 0),
            Decimal(row.get("realism_penalty_r_closed") or 0),
            int(row.get("sample_count") or 0),
        )
    )
    return rows[:limit]


def _v2_realistic_read(perf: dict[str, Any], *, min_sample: int) -> str:
    closed_count = int(perf.get("closed_count") or 0)
    ideal_r = Decimal(perf.get("total_r_closed") or 0)
    realistic_r = Decimal(perf.get("realistic_total_r_closed") or 0)
    penalty_r = Decimal(perf.get("realism_penalty_r_closed") or 0)
    if closed_count < min_sample:
        return "SAMPLE_TOO_SMALL"
    if realistic_r > 0:
        return "REALISTIC_POSITIVE_MONITOR"
    if ideal_r > 0 and realistic_r <= 0:
        return "IDEAL_PROFIT_COST_DRAG"
    if penalty_r > abs(realistic_r):
        return "COST_DRAG_DOMINANT"
    if realistic_r < 0:
        return "REALISTIC_NEGATIVE_NEEDS_FILTER"
    return "NO_CLEAR_EDGE"


def _v2_profit_loss_research_read(
    perf: dict[str, Any],
    driver_rows: list[dict[str, Any]],
    *,
    min_sample: int,
) -> str:
    closed_count = int(perf.get("closed_count") or 0)
    realistic_r = Decimal(perf.get("realistic_total_r_closed") or 0)
    if closed_count < min_sample:
        return "WAIT_MORE_CLOSED_SAMPLE"
    if realistic_r > 0 and driver_rows:
        return "HAS_REALISTIC_POSITIVE_DRIVERS"
    if realistic_r > 0:
        return "REALISTIC_POSITIVE_BUT_DRIVERS_WEAK"
    if driver_rows:
        return "DRIVERS_FOUND_BUT_REALISTIC_NEGATIVE"
    return "NO_CLEAR_TP_DRIVER_YET"


def _v2_mid_short_1h_refinement(items: list[dict[str, Any]], *, min_sample: int, limit: int) -> dict[str, Any]:
    lane_items = [
        item
        for item in items
        if item.get("stage") == "MID_SHORT" and item.get("timeframe") == "1h"
    ]
    baseline = _walk_forward_perf(lane_items)
    shadow_pass_items = [item for item in lane_items if item.get("quality_shadow_status") == "SHADOW_PASS"]
    shadow_fail_items = [item for item in lane_items if item.get("quality_shadow_status") == "SHADOW_FAIL"]
    shadow_unavailable_items = [item for item in lane_items if item.get("quality_shadow_status") == "SHADOW_UNAVAILABLE"]
    rows: list[dict[str, Any]] = []
    for spec in _v2_mid_short_1h_refinement_specs():
        selected, missing = _apply_filter_spec(lane_items, spec)
        perf = _walk_forward_perf(selected, baseline=baseline)
        row = {
            "filter_id": spec.filter_id,
            "label": spec.label,
            "expression": spec.expression,
            "family": spec.family,
            "required_fields": list(spec.required_fields),
            "source_count": len(lane_items),
            "missing_data_count": missing,
            "missing_data_pct": (Decimal(missing) / Decimal(len(lane_items)) * Decimal("100")) if lane_items else None,
            "sample_retention_pct": (Decimal(len(selected)) / Decimal(len(lane_items)) * Decimal("100")) if lane_items else None,
            **perf,
        }
        row["verdict"] = _v2_refinement_verdict(row, min_sample=min_sample)
        row["mitigation_read"] = _v2_refinement_mitigation_read(row)
        row["risk_notes"] = _v2_refinement_risk_notes(row, min_sample=min_sample)
        rows.append(row)

    rows = _sort_v2_refinement_rows(rows)
    promising = [row for row in rows if row["verdict"] in {"REFINEMENT_PROMISING", "REFINEMENT_REDUCES_DAMAGE"}]
    rejected = [row for row in rows if row["verdict"] == "REFINEMENT_REJECT"]
    return {
        "scope": "v2_mid_short_1h_refinement_read_only",
        "stage": "MID_SHORT",
        "timeframe": "1h",
        "direction": "SHORT",
        "method": "Evaluate read-only mitigation filters for V2 MID_SHORT 1h using realistic R, SL share, sample retention, concentration, and drawdown.",
        "baseline": baseline,
        "summary": {
            "source_count": len(lane_items),
            "promising_count": len([row for row in promising if row["verdict"] == "REFINEMENT_PROMISING"]),
            "damage_reduction_count": len([row for row in promising if row["verdict"] == "REFINEMENT_REDUCES_DAMAGE"]),
            "rejected_count": len(rejected),
            "readiness": _v2_mid_short_refinement_readiness(baseline, promising, min_sample=min_sample),
        },
        "shadow_filter": {
            "filter_id": MID_SHORT_1H_QUALITY_SHADOW_FILTER_ID,
            "label": MID_SHORT_1H_QUALITY_SHADOW_FILTER_LABEL,
            "expression": MID_SHORT_1H_QUALITY_SHADOW_FILTER_EXPRESSION,
            "status_meaning": "SHADOW_PASS means research-only quality gate matched; no live rule changed.",
        },
        "shadow_monitor": {
            "pass_count": len(shadow_pass_items),
            "fail_count": len(shadow_fail_items),
            "unavailable_count": len(shadow_unavailable_items),
            "pass": _walk_forward_perf(shadow_pass_items, baseline=baseline),
            "fail": _walk_forward_perf(shadow_fail_items, baseline=baseline),
            "unavailable": _walk_forward_perf(shadow_unavailable_items, baseline=baseline),
        },
        "top_filters": rows[:limit],
        "promising_filters": promising[:limit],
        "rejected_filters": rejected[:limit],
        "mitigation_plan": _v2_mid_short_mitigation_plan(baseline, promising, min_sample=min_sample),
        "guardrails": [
            "Read-only refinement study; no Signal Factory rule changed.",
            "No scanner output, TP/SL formula, or execution behavior changed.",
            "Filters must be forward-observed before any promotion to production rule.",
        ],
    }


def _quality_shadow_status_rows(
    groups: dict[str, list[dict[str, Any]]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    label_by_status = {
        "SHADOW_PASS": "Pass quality gate",
        "SHADOW_FAIL": "Failed quality gate",
        "SHADOW_UNAVAILABLE": "Missing gate evidence",
        "SHADOW_NOT_APPLICABLE": "Not applicable",
    }
    rows: list[dict[str, Any]] = []
    total = int(baseline.get("sample_count") or baseline.get("signals_evaluated") or 0)
    for status in ("SHADOW_PASS", "SHADOW_FAIL", "SHADOW_UNAVAILABLE", "SHADOW_NOT_APPLICABLE"):
        items = groups.get(status, [])
        perf = _walk_forward_perf(items, baseline=baseline)
        row = {
            "shadow_status": status,
            "bucket": status,
            "label": label_by_status.get(status, status),
            "sample_count": len(items),
            "sample_retention_pct": _retention(len(items), total),
            "read": _quality_shadow_status_read(status, perf, min_sample=min_sample),
            **perf,
        }
        rows.append(row)
    return rows


def _quality_shadow_status_read(status: str, perf: dict[str, Any], *, min_sample: int) -> str:
    closed = int(perf.get("closed_count") or 0)
    if int(perf.get("sample_count") or 0) <= 0:
        return "NO_SAMPLE"
    if closed < min_sample:
        return "WAIT_MORE_CLOSED_SAMPLE"
    realistic_total = Decimal(perf.get("realistic_total_r_closed") or 0)
    sl_share = perf.get("sl_share_pct")
    if status == "SHADOW_PASS" and realistic_total > 0 and (sl_share is None or Decimal(sl_share) <= Decimal("50")):
        return "PASS_HEALTHY_SO_FAR"
    if status == "SHADOW_PASS" and realistic_total > 0:
        return "PASS_POSITIVE_BUT_STILL_NOISY"
    if status == "SHADOW_FAIL" and realistic_total < 0:
        return "FAIL_BUCKET_WEAK_AS_EXPECTED"
    if status == "SHADOW_UNAVAILABLE":
        return "EVIDENCE_MISSING_MONITOR"
    return "MIXED_MONITOR_MORE"


def _quality_shadow_forward_read(
    *,
    baseline: dict[str, Any],
    pass_perf: dict[str, Any],
    fail_perf: dict[str, Any],
    min_sample: int,
) -> str:
    if int(pass_perf.get("closed_count") or 0) < min_sample:
        return "SHADOW_PASS_NEEDS_MORE_SAMPLE"
    pass_realistic = Decimal(pass_perf.get("realistic_total_r_closed") or 0)
    pass_avg = pass_perf.get("realistic_avg_r_closed")
    fail_avg = fail_perf.get("realistic_avg_r_closed")
    pass_sl = pass_perf.get("sl_share_pct")
    baseline_sl = baseline.get("sl_share_pct")
    if (
        pass_realistic > 0
        and pass_avg is not None
        and fail_avg is not None
        and Decimal(pass_avg) > Decimal(fail_avg)
        and (baseline_sl is None or pass_sl is None or Decimal(pass_sl) <= Decimal(baseline_sl))
    ):
        return "SHADOW_PASS_OUTPERFORMS_FAIL"
    if pass_realistic > 0:
        return "SHADOW_PASS_POSITIVE_MONITOR_MORE"
    return "SHADOW_PASS_NOT_CLEAN_YET"


def _annotate_mid_short_failure_anatomy(
    items: list[dict[str, Any]],
    candles: dict[str, list[PerfCandle]],
) -> list[dict[str, Any]]:
    btc_candles = candles.get("BTCUSDT", [])
    eth_candles = candles.get("ETHUSDT", [])
    annotated: list[dict[str, Any]] = []
    for item in items:
        path = _mid_short_path_anatomy(item, candles.get(str(item.get("symbol") or ""), []))
        regime = _mid_short_regime_context(item, btc_candles=btc_candles, eth_candles=eth_candles)
        enriched = {
            **item,
            **path,
            **regime,
            "wib_session": _wib_session(_parse_dt(item.get("signal_timestamp"))),
        }
        annotated.append(enriched)
    return annotated


def _mid_short_path_anatomy(item: dict[str, Any], candles: list[PerfCandle]) -> dict[str, Any]:
    entry = _decimal_or_none_any(item.get("entry"))
    stop = _decimal_or_none_any(item.get("stop_loss"))
    target = _decimal_or_none_any(item.get("take_profit"))
    risk = _decimal_or_none_any(item.get("risk"))
    signal_time = _parse_dt(item.get("signal_timestamp"))
    if entry is None or stop is None or target is None or risk is None or risk <= 0 or signal_time is None:
        return _empty_path_anatomy("MISSING_PRICE_CONTEXT")

    ordered = sorted(candles, key=lambda candle: candle.open_time)
    open_times = [candle.open_time for candle in ordered]
    future = ordered[bisect_left(open_times, signal_time):]
    if not future:
        return _empty_path_anatomy("NO_FORWARD_CANDLE")

    first_hit_status = None
    first_hit_time = None
    first_hit_index = None
    mfe_before_first_hit = Decimal("0")
    mae_before_first_hit = Decimal("0")
    mfe = Decimal("0")
    mae = Decimal("0")
    direction = str(item.get("direction") or "")
    for index, candle in enumerate(future, start=1):
        if direction == "SHORT":
            candle_mfe = (entry - candle.low) / risk
            candle_mae = (entry - candle.high) / risk
            tp_hit = candle.low <= target
            sl_hit = candle.high >= stop
        else:
            candle_mfe = (candle.high - entry) / risk
            candle_mae = (candle.low - entry) / risk
            tp_hit = candle.high >= target
            sl_hit = candle.low <= stop
        mfe = max(mfe, candle_mfe)
        mae = min(mae, candle_mae)
        if tp_hit or sl_hit:
            mfe_before_first_hit = mfe
            mae_before_first_hit = mae
            first_hit_time = candle.close_time
            first_hit_index = index
            if tp_hit and sl_hit:
                first_hit_status = "BOTH_HIT_SAME_CANDLE"
            elif tp_hit:
                first_hit_status = "TP_HIT"
            else:
                first_hit_status = "SL_HIT"
            break

    after_sl_would_hit_tp = False
    after_sl_tp_time = None
    if first_hit_status == "SL_HIT" and first_hit_index is not None:
        for candle in future[first_hit_index:]:
            if direction == "SHORT" and candle.low <= target:
                after_sl_would_hit_tp = True
                after_sl_tp_time = candle.close_time
                break
            if direction == "LONG" and candle.high >= target:
                after_sl_would_hit_tp = True
                after_sl_tp_time = candle.close_time
                break

    horizon_returns = _horizon_returns(item, future)
    direction_labels = {
        f"direction_{label}": _direction_label(direction, value)
        for label, value in horizon_returns.items()
    }
    result_status = str(item.get("result_status") or "")
    tp_near_before_sl = result_status == "SL_HIT" and mfe_before_first_hit >= Decimal("0.75")
    path_type = _mid_short_path_type(
        result_status=result_status,
        first_hit_status=first_hit_status,
        first_hit_index=first_hit_index,
        mfe_before_first_hit=mfe_before_first_hit,
        mae_before_first_hit=mae_before_first_hit,
        after_sl_would_hit_tp=after_sl_would_hit_tp,
        direction_1h=direction_labels.get("direction_1h"),
        unrealized_r=_decimal_or_none_any(item.get("unrealized_r")),
    )
    return {
        "path_type": path_type,
        "first_hit_status": first_hit_status,
        "first_hit_time_utc": first_hit_time,
        "first_hit_time_wib": _wib_string(first_hit_time),
        "first_hit_candle_index": first_hit_index,
        "mfe_before_first_hit_r": mfe_before_first_hit,
        "mae_before_first_hit_r": mae_before_first_hit,
        "tp_near_before_sl": tp_near_before_sl,
        "after_sl_would_hit_tp": after_sl_would_hit_tp,
        "after_sl_tp_time_utc": after_sl_tp_time,
        "after_sl_tp_time_wib": _wib_string(after_sl_tp_time),
        **{f"return_{label}_pct": value for label, value in horizon_returns.items()},
        **direction_labels,
    }


def _empty_path_anatomy(reason: str) -> dict[str, Any]:
    return {
        "path_type": reason,
        "first_hit_status": None,
        "first_hit_time_utc": None,
        "first_hit_time_wib": None,
        "first_hit_candle_index": None,
        "mfe_before_first_hit_r": None,
        "mae_before_first_hit_r": None,
        "tp_near_before_sl": False,
        "after_sl_would_hit_tp": False,
        "after_sl_tp_time_utc": None,
        "after_sl_tp_time_wib": None,
        "return_15m_pct": None,
        "return_30m_pct": None,
        "return_1h_pct": None,
        "return_2h_pct": None,
        "return_4h_pct": None,
        "direction_15m": "MISSING_FORWARD_DATA",
        "direction_30m": "MISSING_FORWARD_DATA",
        "direction_1h": "MISSING_FORWARD_DATA",
        "direction_2h": "MISSING_FORWARD_DATA",
        "direction_4h": "MISSING_FORWARD_DATA",
    }


def _mid_short_path_type(
    *,
    result_status: str,
    first_hit_status: str | None,
    first_hit_index: int | None,
    mfe_before_first_hit: Decimal,
    mae_before_first_hit: Decimal,
    after_sl_would_hit_tp: bool,
    direction_1h: str | None,
    unrealized_r: Decimal | None,
) -> str:
    if result_status == "BOTH_HIT_SAME_CANDLE" or first_hit_status == "BOTH_HIT_SAME_CANDLE":
        return "CHOPPY_BOTH_ZONE"
    if result_status == "TP_HIT":
        if mae_before_first_hit <= Decimal("-0.75"):
            return "DEEP_ADVERSE_THEN_TP"
        if first_hit_index is not None and first_hit_index <= 2:
            return "TP_DIRECT"
        return "TP_GRIND"
    if result_status == "SL_HIT":
        if after_sl_would_hit_tp:
            return "SL_THEN_WOULD_TP"
        if mfe_before_first_hit >= Decimal("0.75"):
            return "TP_NEAR_THEN_SL"
        if first_hit_index is not None and first_hit_index <= 2 and mae_before_first_hit <= Decimal("-1"):
            return "SL_DIRECT"
        if direction_1h == "WRONG_DIRECTION":
            return "WRONG_DIRECTION_DRIFT"
        return "CHOPPY_OR_LATE_SL"
    if result_status == "OPEN":
        if unrealized_r is not None and unrealized_r >= Decimal("0.5"):
            return "OPEN_FAVORABLE"
        if unrealized_r is not None and unrealized_r <= Decimal("-0.5"):
            return "OPEN_ADVERSE"
        return "OPEN_NO_CLEAR_MOVE"
    if result_status == "WAITING_DATA":
        return "WAITING_FORWARD_DATA"
    if result_status == "STALE_FORWARD_DATA":
        return "STALE_FORWARD_DATA"
    return result_status or "UNKNOWN_PATH"


def _horizon_returns(item: dict[str, Any], future: list[PerfCandle]) -> dict[str, Decimal | None]:
    entry = _decimal_or_none_any(item.get("entry"))
    signal_time = _parse_dt(item.get("signal_timestamp"))
    horizons = {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}
    if entry is None or entry <= 0 or signal_time is None:
        return {label: None for label in horizons}
    output: dict[str, Decimal | None] = {}
    for label, minutes in horizons.items():
        target_time = signal_time + timedelta(minutes=minutes)
        candle = next((row for row in future if row.close_time >= target_time), None)
        output[label] = ((candle.close - entry) / entry * Decimal("100")) if candle else None
    return output


def _direction_label(direction: str, return_pct: Decimal | None) -> str:
    if return_pct is None:
        return "MISSING_FORWARD_DATA"
    if abs(return_pct) < Decimal("0.05"):
        return "FLAT"
    if direction == "SHORT":
        return "CORRECT_DIRECTION" if return_pct < 0 else "WRONG_DIRECTION"
    if direction == "LONG":
        return "CORRECT_DIRECTION" if return_pct > 0 else "WRONG_DIRECTION"
    return "NON_DIRECTIONAL"


def _mid_short_regime_context(
    item: dict[str, Any],
    *,
    btc_candles: list[PerfCandle],
    eth_candles: list[PerfCandle],
) -> dict[str, Any]:
    signal_time = _parse_dt(item.get("signal_timestamp"))
    btc_1h = _prior_return_pct(btc_candles, signal_time, minutes=60)
    btc_4h = _prior_return_pct(btc_candles, signal_time, minutes=240)
    eth_1h = _prior_return_pct(eth_candles, signal_time, minutes=60)
    eth_4h = _prior_return_pct(eth_candles, signal_time, minutes=240)
    return {
        "btc_1h_return_pct": btc_1h,
        "btc_4h_return_pct": btc_4h,
        "eth_1h_return_pct": eth_1h,
        "eth_4h_return_pct": eth_4h,
        "btc_1h_regime": _regime_label(btc_1h),
        "btc_4h_regime": _regime_label(btc_4h),
        "eth_1h_regime": _regime_label(eth_1h),
        "eth_4h_regime": _regime_label(eth_4h),
    }


def _prior_return_pct(candles: list[PerfCandle], signal_time: datetime | None, *, minutes: int) -> Decimal | None:
    if not candles or signal_time is None:
        return None
    ordered = sorted(candles, key=lambda candle: candle.close_time)
    current = None
    previous = None
    previous_cutoff = signal_time - timedelta(minutes=minutes)
    for candle in ordered:
        if candle.close_time <= signal_time:
            current = candle
        if candle.close_time <= previous_cutoff:
            previous = candle
        if candle.close_time > signal_time:
            break
    if current is None or previous is None or previous.close <= 0:
        return None
    return (current.close - previous.close) / previous.close * Decimal("100")


def _regime_label(return_pct: Decimal | None) -> str:
    if return_pct is None:
        return "REGIME_UNKNOWN"
    if return_pct >= Decimal("0.50"):
        return "BULLISH_REGIME"
    if return_pct <= Decimal("-0.50"):
        return "BEARISH_REGIME"
    return "CHOPPY_REGIME"


def _wib_session(signal_time: datetime | None) -> str:
    if signal_time is None:
        return "SESSION_UNKNOWN"
    hour = (_naive(signal_time) + timedelta(hours=7)).hour
    if 7 <= hour < 14:
        return "ASIA_DAY"
    if 14 <= hour < 20:
        return "EUROPE_OVERLAP"
    if 20 <= hour or hour < 4:
        return "US_SESSION"
    return "QUIET_PRE_ASIA"


def _mid_short_failure_summary_read(items: list[dict[str, Any]], *, min_sample: int) -> str:
    closed = [item for item in items if item.get("result_status") in COMPLETED_OUTCOMES]
    if len(closed) < min_sample:
        return "WAIT_MORE_CLOSED_SAMPLE"
    sl_items = [item for item in closed if item.get("result_status") == "SL_HIT"]
    if not sl_items:
        return "NO_SL_IN_SCOPE"
    sl_then_tp = sum(1 for item in sl_items if item.get("after_sl_would_hit_tp"))
    near_tp = sum(1 for item in sl_items if item.get("tp_near_before_sl"))
    wrong_1h = sum(1 for item in sl_items if item.get("direction_1h") == "WRONG_DIRECTION")
    if wrong_1h >= max(sl_then_tp, near_tp):
        return "SL_MAINLY_DIRECTION_PROBLEM"
    if sl_then_tp > near_tp:
        return "SL_MAINLY_TIMING_OR_STOP_PLACEMENT"
    if near_tp > 0:
        return "SL_OFTEN_AFTER_PARTIAL_FAVORABLE_MOVE"
    return "SL_MIXED_CAUSES"


def _mid_short_mfe_mae_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {
        "TP_HIT": [item for item in items if item.get("result_status") == "TP_HIT"],
        "SL_HIT": [item for item in items if item.get("result_status") == "SL_HIT"],
        "OPEN": [item for item in items if item.get("result_status") == "OPEN"],
    }
    output: dict[str, Any] = {}
    for status, group in groups.items():
        mfe_values = [_decimal_or_none_any(item.get("mfe_r")) for item in group]
        mae_values = [_decimal_or_none_any(item.get("mae_r")) for item in group]
        before_mfe_values = [_decimal_or_none_any(item.get("mfe_before_first_hit_r")) for item in group]
        before_mae_values = [_decimal_or_none_any(item.get("mae_before_first_hit_r")) for item in group]
        mfe_clean = [value for value in mfe_values if value is not None]
        mae_clean = [value for value in mae_values if value is not None]
        before_mfe_clean = [value for value in before_mfe_values if value is not None]
        before_mae_clean = [value for value in before_mae_values if value is not None]
        output[status] = {
            "sample_count": len(group),
            "median_mfe_r": _median_decimal(mfe_clean),
            "median_mae_r": _median_decimal(mae_clean),
            "median_mfe_before_first_hit_r": _median_decimal(before_mfe_clean),
            "median_mae_before_first_hit_r": _median_decimal(before_mae_clean),
            "mfe_ge_0_5_count": sum(1 for value in mfe_clean if value >= Decimal("0.5")),
            "mfe_ge_1_0_count": sum(1 for value in mfe_clean if value >= Decimal("1.0")),
            "mae_le_minus_1_count": sum(1 for value in mae_clean if value <= Decimal("-1.0")),
        }
    return output


def _anatomy_bucket_rows(
    items: list[dict[str, Any]],
    *,
    key: str,
    min_sample: int,
    baseline: dict[str, Any],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[str(item.get(key) or "UNKNOWN")].append(item)
    rows: list[dict[str, Any]] = []
    for bucket, bucket_items in groups.items():
        perf = _walk_forward_perf(bucket_items, baseline=baseline)
        rows.append(
            {
                "dimension": key,
                "bucket": bucket,
                "label": bucket,
                "sample_count": len(bucket_items),
                "tp_count": int(perf.get("tp_count") or 0),
                "sl_count": int(perf.get("sl_count") or 0),
                "open_count": int(perf.get("open_count") or 0),
                "sl_share_pct": perf.get("sl_share_pct"),
                "read": _anatomy_bucket_read(bucket, perf, min_sample=min_sample),
                **perf,
            }
        )
    rows.sort(
        key=lambda row: (
            Decimal(row.get("realistic_total_r_closed") or 0),
            int(row.get("sample_count") or 0),
        ),
        reverse=True,
    )
    return rows[:limit] if limit is not None else rows


def _anatomy_bucket_read(bucket: str, perf: dict[str, Any], *, min_sample: int) -> str:
    closed = int(perf.get("closed_count") or 0)
    if closed < min_sample:
        return "WAIT_MORE_SAMPLE"
    realistic_total = Decimal(perf.get("realistic_total_r_closed") or 0)
    sl_share = perf.get("sl_share_pct")
    if realistic_total > 0 and (sl_share is None or Decimal(sl_share) <= Decimal("50")):
        return "HEALTHIER_BUCKET"
    if realistic_total < 0 and sl_share is not None and Decimal(sl_share) > Decimal("55"):
        return "LOSS_HEAVY_BUCKET"
    if bucket in {"SL_THEN_WOULD_TP", "TP_NEAR_THEN_SL"}:
        return "TIMING_OR_EXIT_PROBLEM"
    if bucket == "WRONG_DIRECTION_DRIFT":
        return "DIRECTION_PROBLEM"
    return "MIXED_BUCKET"


def _direction_correctness_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for horizon in ("15m", "30m", "1h", "2h", "4h"):
        key = f"direction_{horizon}"
        for row in _anatomy_bucket_rows(items, key=key, min_sample=min_sample, baseline=baseline):
            row["horizon"] = horizon
            rows.append(row)
    rows.sort(
        key=lambda row: (
            row.get("horizon"),
            Decimal(row.get("realistic_total_r_closed") or 0),
        )
    )
    return rows


def _mid_short_regime_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("btc_1h_regime", "btc_4h_regime", "eth_1h_regime", "eth_4h_regime"):
        rows.extend(_anatomy_bucket_rows(items, key=key, min_sample=min_sample, baseline=baseline))
    rows.sort(
        key=lambda row: (
            row.get("dimension"),
            Decimal(row.get("realistic_total_r_closed") or 0),
        )
    )
    return rows


def _mid_short_failure_improvement_candidates(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
    limit: int,
) -> list[dict[str, Any]]:
    specs: list[FilterStudySpec] = [
        FilterStudySpec(
            "NO_BTC_1H_BULL",
            "Exclude BTC 1h bullish regime",
            "btc_1h_regime != BULLISH_REGIME",
            "regime",
            (),
            lambda item: item.get("btc_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "NO_ETH_1H_BULL",
            "Exclude ETH 1h bullish regime",
            "eth_1h_regime != BULLISH_REGIME",
            "regime",
            (),
            lambda item: item.get("eth_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "NO_BTC_ETH_1H_BULL",
            "Exclude BTC/ETH 1h bullish regime",
            "btc_1h_regime != BULLISH_REGIME AND eth_1h_regime != BULLISH_REGIME",
            "regime",
            (),
            lambda item: item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "TAKER_SELL_GE_52",
            "Taker sell >= 52%",
            "kline_taker_sell_ratio >= 0.52",
            "taker",
            ("kline_taker_sell_ratio",),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.52"),
        ),
        FilterStudySpec(
            "TAKER_BUY_LE_50",
            "Taker buy <= 50%",
            "kline_taker_buy_ratio <= 0.50",
            "taker",
            ("kline_taker_buy_ratio",),
            lambda item: (_evidence_value(item, "kline_taker_buy_ratio") or Decimal("999")) <= Decimal("0.50"),
        ),
        FilterStudySpec(
            "OI_Z_GE_1",
            "OI z-score >= 1",
            "oi_zscore >= 1",
            "open_interest",
            ("oi_zscore",),
            lambda item: (_evidence_value(item, "oi_zscore") or Decimal("-999")) >= Decimal("1"),
        ),
        FilterStudySpec(
            "PRICE_RETURN_LE_0",
            "Signal candle already weak",
            "price_return <= 0",
            "direction",
            ("price_return",),
            lambda item: (_evidence_value(item, "price_return") or Decimal("999")) <= Decimal("0"),
        ),
        FilterStudySpec(
            "RANGE_ATR_LE_1_0",
            "Range/ATR <= 1.0",
            "range_ratio_vs_atr <= 1.0",
            "extension",
            ("range_ratio_vs_atr",),
            lambda item: (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.0"),
        ),
        FilterStudySpec(
            "FUNDING_GE_65",
            "Funding percentile >= 65",
            "funding_percentile_30d >= 65",
            "positioning",
            ("funding_percentile_30d",),
            lambda item: (_evidence_value(item, "funding_percentile_30d") or Decimal("-999")) >= Decimal("65"),
        ),
        FilterStudySpec(
            "REGIME_AND_TAKER",
            "No BTC/ETH bull + taker sell >= 52%",
            "no BTC/ETH 1h bull AND kline_taker_sell_ratio >= 0.52",
            "combo",
            ("kline_taker_sell_ratio",),
            lambda item: item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME"
            and (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.52"),
        ),
        FilterStudySpec(
            "REGIME_RANGE_TAKER",
            "No BTC/ETH bull + range <= 1.0 + taker sell >= 52%",
            "no BTC/ETH 1h bull AND range_ratio_vs_atr <= 1.0 AND kline_taker_sell_ratio >= 0.52",
            "combo",
            ("range_ratio_vs_atr", "kline_taker_sell_ratio"),
            lambda item: item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME"
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.0")
            and (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.52"),
        ),
    ]
    rows: list[dict[str, Any]] = []
    for spec in specs:
        selected, missing = _apply_filter_spec(items, spec)
        perf = _walk_forward_perf(selected, baseline=baseline)
        row = {
            "filter_id": spec.filter_id,
            "label": spec.label,
            "expression": spec.expression,
            "family": spec.family,
            "required_fields": list(spec.required_fields),
            "source_count": len(items),
            "missing_data_count": missing,
            "missing_data_pct": (Decimal(missing) / Decimal(len(items)) * Decimal("100")) if items else None,
            "sample_retention_pct": _retention(len(selected), len(items)),
            "read": _mid_short_candidate_filter_read(perf, min_sample=min_sample),
            **perf,
        }
        rows.append(row)
    rows.sort(
        key=lambda row: (
            row["read"] in {"FILTER_CANDIDATE_MONITOR", "REDUCES_DAMAGE_MONITOR"},
            _decimal_or_zero(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero(row.get("realistic_total_r_delta_vs_baseline")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _mid_short_candidate_filter_read(perf: dict[str, Any], *, min_sample: int) -> str:
    if int(perf.get("closed_count") or 0) < min_sample:
        return "WAIT_MORE_SAMPLE"
    realistic_total = Decimal(perf.get("realistic_total_r_closed") or 0)
    avg_delta = _decimal_or_none_any(perf.get("realistic_avg_r_delta_vs_baseline"))
    sl_delta = _decimal_or_none_any(perf.get("sl_share_delta_vs_baseline"))
    if realistic_total > 0 and avg_delta is not None and avg_delta > 0 and (sl_delta is None or sl_delta <= 0):
        return "FILTER_CANDIDATE_MONITOR"
    if avg_delta is not None and avg_delta > 0:
        return "REDUCES_DAMAGE_MONITOR"
    if avg_delta is not None and avg_delta < 0:
        return "WORSE_THAN_SHADOW_PASS"
    return "NO_CLEAR_SEPARATION"


def _misidentification_lane(
    *,
    stage: str,
    timeframe: str,
    items: list[dict[str, Any]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    direction = _stage_direction(stage)
    baseline = _walk_forward_perf(items)
    enriched: list[dict[str, Any]] = []
    for item in items:
        tags = _misidentification_tags(item)
        reverse = _reverse_proxy(item)
        enriched.append(
            {
                **item,
                "misidentification_primary_reason": _misidentification_reason(tags, reverse),
                "reverse_proxy_bucket": reverse["bucket"],
                "reverse_clean_proxy": reverse["reverse_clean_proxy"],
                "reverse_both_zone_proxy": reverse["reverse_both_zone_proxy"],
                "reverse_mfe_r": reverse["reverse_mfe_r"],
                "reverse_mae_r": reverse["reverse_mae_r"],
                "entry_overextended_bucket": _entry_overextended(item),
                "cost_or_fill_bucket": _cost_or_fill_drag(item),
            }
        )

    closed = [item for item in enriched if item.get("result_status") in COMPLETED_OUTCOMES]
    wrong_1h = [item for item in closed if item.get("direction_1h") == "WRONG_DIRECTION"]
    correct_1h = [item for item in closed if item.get("direction_1h") == "CORRECT_DIRECTION"]
    reverse_clean = [item for item in closed if item.get("reverse_clean_proxy")]
    reverse_both_zone = [item for item in closed if item.get("reverse_both_zone_proxy")]
    summary = {
        "sample_count": len(enriched),
        "closed_count": len(closed),
        "tp_count": int(baseline.get("tp_count") or 0),
        "sl_count": int(baseline.get("sl_count") or 0),
        "wrong_direction_1h_count": len(wrong_1h),
        "correct_direction_1h_count": len(correct_1h),
        "reverse_clean_count": len(reverse_clean),
        "reverse_both_zone_count": len(reverse_both_zone),
        "sl_share_pct": baseline.get("sl_share_pct"),
        "wrong_direction_1h_share_pct": _pct(len(wrong_1h), len(closed)),
        "reverse_clean_share_pct": _pct(len(reverse_clean), len(closed)),
        "verdict": _misidentification_verdict(baseline, len(wrong_1h), len(reverse_clean), min_sample=min_sample),
        "read": _misidentification_read(baseline, len(wrong_1h), len(reverse_clean), min_sample=min_sample),
    }
    return {
        "lane": f"{stage}_{timeframe}",
        "stage": stage,
        "timeframe": timeframe,
        "direction": direction,
        "summary": summary,
        "baseline": baseline,
        "reason_rows": _misidentification_bucket_rows(
            enriched,
            key="misidentification_primary_reason",
            baseline=baseline,
            min_sample=min_sample,
            limit=limit,
        ),
        "reverse_rows": _misidentification_bucket_rows(
            enriched,
            key="reverse_proxy_bucket",
            baseline=baseline,
            min_sample=min_sample,
            limit=limit,
        ),
        "path_rows": _misidentification_bucket_rows(
            enriched,
            key="path_type",
            baseline=baseline,
            min_sample=min_sample,
            limit=limit,
        ),
        "evidence_correct_vs_wrong": _misidentification_evidence_rows(enriched),
        "latest_sl_signals": _sorted_signal_rows([item for item in enriched if item.get("result_status") == "SL_HIT"], limit=limit),
        "latest_tp_signals": _sorted_signal_rows([item for item in enriched if item.get("result_status") == "TP_HIT"], limit=limit),
        "reverse_clean_examples": _sorted_signal_rows(reverse_clean, limit=min(limit, 20)),
    }


def _misidentification_tags(item: dict[str, Any]) -> set[str]:
    tags: set[str] = set()
    if item.get("direction_1h") == "WRONG_DIRECTION":
        tags.add("WRONG_DIRECTION_1H")
    if item.get("direction_2h") == "WRONG_DIRECTION":
        tags.add("WRONG_DIRECTION_2H")
    if item.get("direction_4h") == "WRONG_DIRECTION":
        tags.add("WRONG_DIRECTION_4H")
    if item.get("path_type") in {"SL_THEN_WOULD_TP", "TP_NEAR_THEN_SL"}:
        tags.add("STOP_OR_TIMING_PROBLEM")
    if item.get("path_type") == "CHOPPY_BOTH_ZONE" or item.get("result_status") == "BOTH_HIT_SAME_CANDLE":
        tags.add("CHOPPY_BOTH_ZONE")
    if _decimal_or_none_any(item.get("mfe_before_first_hit_r")) is not None and _decimal_or_none_any(item.get("mfe_before_first_hit_r")) >= Decimal("0.75"):
        tags.add("FAVORABLE_THEN_REVERSED")
    if _entry_overextended(item) != "ENTRY_EXTENSION_OK":
        tags.add("ENTRY_OVEREXTENDED")
    if _cost_or_fill_drag(item) != "COST_FILL_OK":
        tags.add("COST_OR_FILL_DRAG")
    return tags


def _misidentification_reason(tags: set[str], reverse: dict[str, Any]) -> str:
    if reverse.get("reverse_clean_proxy"):
        return "WRONG_DIRECTION_REVERSE_CANDIDATE"
    if "CHOPPY_BOTH_ZONE" in tags:
        return "CHOPPY_BOTH_SIDE_RISK"
    if "WRONG_DIRECTION_1H" in tags and "WRONG_DIRECTION_2H" in tags:
        return "WRONG_DIRECTION_PERSISTENT"
    if "WRONG_DIRECTION_1H" in tags:
        return "WRONG_DIRECTION_SHORT_TERM"
    if "STOP_OR_TIMING_PROBLEM" in tags:
        return "STOP_OR_TIMING_PROBLEM"
    if "FAVORABLE_THEN_REVERSED" in tags:
        return "FAVORABLE_THEN_REVERSED"
    if "ENTRY_OVEREXTENDED" in tags:
        return "ENTRY_OVEREXTENDED"
    if "COST_OR_FILL_DRAG" in tags:
        return "COST_OR_FILL_DRAG"
    return "MIXED_OR_NO_CLEAR_CAUSE"


def _reverse_proxy(item: dict[str, Any]) -> dict[str, Any]:
    mfe = _decimal_or_none_any(item.get("mfe_r"))
    mae = _decimal_or_none_any(item.get("mae_r"))
    rr = _decimal_or_none_any(item.get("rr")) or Decimal("1.5")
    if mfe is None or mae is None:
        return {
            "bucket": "REVERSE_UNKNOWN",
            "reverse_clean_proxy": False,
            "reverse_both_zone_proxy": False,
            "reverse_mfe_r": None,
            "reverse_mae_r": None,
        }
    reverse_mfe = abs(mae)
    reverse_mae = -abs(mfe)
    reverse_tp = reverse_mfe >= rr
    reverse_sl = abs(reverse_mae) >= Decimal("1")
    if reverse_tp and not reverse_sl:
        bucket = "REVERSE_CLEAN_PROXY"
    elif reverse_tp and reverse_sl:
        bucket = "REVERSE_BOTH_ZONE_PROXY"
    elif not reverse_tp and reverse_sl:
        bucket = "REVERSE_WOULD_SL_PROXY"
    else:
        bucket = "REVERSE_NO_TP_PROXY"
    return {
        "bucket": bucket,
        "reverse_clean_proxy": bucket == "REVERSE_CLEAN_PROXY",
        "reverse_both_zone_proxy": bucket == "REVERSE_BOTH_ZONE_PROXY",
        "reverse_mfe_r": reverse_mfe,
        "reverse_mae_r": reverse_mae,
    }


def _entry_overextended(item: dict[str, Any]) -> str:
    range_atr = _evidence_value(item, "range_ratio_vs_atr")
    price_atr = _evidence_value(item, "price_atr_multiple")
    atr_ext = _evidence_value(item, "atr_extension_normalized")
    price_return = _evidence_value(item, "price_return")
    if range_atr is not None and range_atr >= Decimal("1.5"):
        return "RANGE_OVEREXTENDED"
    if price_atr is not None and price_atr >= Decimal("1.5"):
        return "PRICE_ATR_OVEREXTENDED"
    if atr_ext is not None and atr_ext >= Decimal("1.5"):
        return "ATR_EXTENSION_OVEREXTENDED"
    direction = str(item.get("direction") or "")
    if direction == "LONG" and price_return is not None and price_return >= Decimal("2.0"):
        return "LONG_AFTER_STRONG_GREEN"
    if direction == "SHORT" and price_return is not None and price_return <= Decimal("-2.0"):
        return "SHORT_AFTER_STRONG_RED"
    return "ENTRY_EXTENSION_OK"


def _cost_or_fill_drag(item: dict[str, Any]) -> str:
    fill = str(item.get("realistic_fill_quality") or "")
    penalty = _decimal_or_none_any(item.get("realism_penalty_r"))
    ideal = _decimal_or_none_any(item.get("realized_r"))
    realistic = _decimal_or_none_any(item.get("realistic_realized_r"))
    if fill in {"FILL_BAD", "SPREAD_UNKNOWN"}:
        return fill
    if ideal is not None and realistic is not None and ideal > 0 and realistic <= 0:
        return "IDEAL_WIN_REALISTIC_LOSS"
    if penalty is not None and penalty >= Decimal("0.25"):
        return "HIGH_REALISM_PENALTY"
    return "COST_FILL_OK"


def _misidentification_bucket_rows(
    items: list[dict[str, Any]],
    *,
    key: str,
    baseline: dict[str, Any],
    min_sample: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows = _anatomy_bucket_rows(items, key=key, min_sample=min_sample, baseline=baseline, limit=None)
    for row in rows:
        row["read"] = _misidentification_bucket_read(row, min_sample=min_sample)
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0) >= min_sample,
            int(row.get("sl_count") or 0),
            Decimal(row.get("realistic_total_r_closed") or 0) * Decimal("-1"),
            int(row.get("sample_count") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _misidentification_bucket_read(row: dict[str, Any], *, min_sample: int) -> str:
    if int(row.get("closed_count") or 0) < min_sample:
        return "WAIT_MORE_SAMPLE"
    bucket = str(row.get("bucket") or "")
    if bucket in {"WRONG_DIRECTION_REVERSE_CANDIDATE", "REVERSE_CLEAN_PROXY"}:
        return "REVERSE_WORTH_RESEARCH"
    if bucket.startswith("WRONG_DIRECTION"):
        return "DIRECTION_WEAK"
    if bucket in {"ENTRY_OVEREXTENDED", "RANGE_OVEREXTENDED", "PRICE_ATR_OVEREXTENDED", "ATR_EXTENSION_OVEREXTENDED"}:
        return "ENTRY_FILTER_CANDIDATE"
    if bucket in {"STOP_OR_TIMING_PROBLEM", "FAVORABLE_THEN_REVERSED", "SL_THEN_WOULD_TP", "TP_NEAR_THEN_SL"}:
        return "STOP_OR_TIMEOUT_RESEARCH"
    if Decimal(row.get("realistic_total_r_closed") or 0) > 0:
        return "HEALTHY_BUCKET"
    return "LOSS_BUCKET"


def _misidentification_evidence_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    correct = [item for item in items if item.get("direction_1h") == "CORRECT_DIRECTION"]
    wrong = [item for item in items if item.get("direction_1h") == "WRONG_DIRECTION"]
    fields = [
        ("price_return", "Price return %"),
        ("volume_ratio_vs_lookback", "Volume vs avg"),
        ("range_ratio_vs_atr", "Range / ATR"),
        ("atr_extension_normalized", "ATR extension"),
        ("price_atr_multiple", "Price / ATR"),
        ("kline_taker_buy_ratio", "Taker buy ratio"),
        ("kline_taker_sell_ratio", "Taker sell ratio"),
        ("oi_change_pct", "OI change %"),
        ("oi_zscore", "OI z-score"),
        ("funding_percentile_30d", "Funding percentile"),
        ("global_long_short_ratio", "Global L/S"),
        ("top_trader_position_ratio", "Top position"),
        ("top_trader_account_ratio", "Top account"),
        ("futures_spread_pct", "Futures spread %"),
    ]
    rows: list[dict[str, Any]] = []
    for field, label in fields:
        correct_values = [value for value in (_evidence_value(item, field) for item in correct) if value is not None]
        wrong_values = [value for value in (_evidence_value(item, field) for item in wrong) if value is not None]
        correct_median = _median_decimal(correct_values)
        wrong_median = _median_decimal(wrong_values)
        rows.append(
            {
                "field": field,
                "label": label,
                "quality_flag": _evidence_gap_flag(correct_median, wrong_median),
                "available_count": len(correct_values) + len(wrong_values),
                "missing_count": len(correct) + len(wrong) - len(correct_values) - len(wrong_values),
                "available_pct": _pct(len(correct_values) + len(wrong_values), len(correct) + len(wrong)),
                "correct_count": len(correct_values),
                "wrong_count": len(wrong_values),
                "correct_median": correct_median,
                "wrong_median": wrong_median,
                "delta_correct_minus_wrong": _decimal_delta(correct_median, wrong_median),
            }
        )
    rows.sort(
        key=lambda row: (
            row["quality_flag"] in {"CORRECT_HIGHER", "WRONG_HIGHER"},
            abs(Decimal(row.get("delta_correct_minus_wrong") or 0)),
            int(row.get("available_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _evidence_gap_flag(correct_median: Decimal | None, wrong_median: Decimal | None) -> str:
    if correct_median is None or wrong_median is None:
        return "UNAVAILABLE"
    delta = correct_median - wrong_median
    if abs(delta) < Decimal("0.05"):
        return "NO_CLEAR_GAP"
    return "CORRECT_HIGHER" if delta > 0 else "WRONG_HIGHER"


def _misidentification_verdict(
    baseline: dict[str, Any],
    wrong_1h_count: int,
    reverse_clean_count: int,
    *,
    min_sample: int,
) -> str:
    closed = int(baseline.get("closed_count") or 0)
    if closed < min_sample:
        return "WAIT_MORE_SAMPLE"
    wrong_share = Decimal(wrong_1h_count) / Decimal(closed) * Decimal("100") if closed else Decimal("0")
    reverse_share = Decimal(reverse_clean_count) / Decimal(closed) * Decimal("100") if closed else Decimal("0")
    realistic_total = Decimal(baseline.get("realistic_total_r_closed") or 0)
    sl_share = baseline.get("sl_share_pct")
    if reverse_share >= Decimal("20"):
        return "REVERSE_HYPOTHESIS_WORTH_TESTING"
    if wrong_share >= Decimal("55"):
        return "DIRECTION_IDENTIFICATION_WEAK"
    if sl_share is not None and Decimal(sl_share) >= Decimal("60"):
        return "RISK_OR_ENTRY_MODEL_WEAK"
    if realistic_total > 0:
        return "DIRECTION_ACCEPTABLE_MONITOR"
    return "NO_CLEAR_FIX_YET"


def _misidentification_read(
    baseline: dict[str, Any],
    wrong_1h_count: int,
    reverse_clean_count: int,
    *,
    min_sample: int,
) -> str:
    verdict = _misidentification_verdict(
        baseline,
        wrong_1h_count,
        reverse_clean_count,
        min_sample=min_sample,
    )
    return {
        "WAIT_MORE_SAMPLE": "Sample belum cukup untuk menyimpulkan salah arah.",
        "REVERSE_HYPOTHESIS_WORTH_TESTING": "Ada cukup banyak SL yang secara path lebih cocok kalau dibalik; perlu studi reverse read-only, belum boleh jadi rule.",
        "DIRECTION_IDENTIFICATION_WEAK": "Banyak signal bergerak melawan arah dalam 1h; masalah utama kemungkinan definisi arah.",
        "RISK_OR_ENTRY_MODEL_WEAK": "Arah tidak jelas-jelas salah, tetapi SL share tinggi; fokus ke entry telat, stop placement, timeout, atau filter cost.",
        "DIRECTION_ACCEPTABLE_MONITOR": "Arah relatif bisa diterima dalam sample ini; tetap pantau realistic R dan drawdown.",
        "NO_CLEAR_FIX_YET": "Loss tersebar di beberapa penyebab; perlu pecah per bucket/evidence.",
    }.get(verdict, verdict)


def _misidentification_summary(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    lane_count = len(lanes)
    reverse_count = sum(1 for lane in lanes if lane.get("summary", {}).get("verdict") == "REVERSE_HYPOTHESIS_WORTH_TESTING")
    direction_weak_count = sum(1 for lane in lanes if lane.get("summary", {}).get("verdict") == "DIRECTION_IDENTIFICATION_WEAK")
    entry_weak_count = sum(1 for lane in lanes if lane.get("summary", {}).get("verdict") == "RISK_OR_ENTRY_MODEL_WEAK")
    ranked = sorted(
        lanes,
        key=lambda lane: Decimal(lane.get("baseline", {}).get("realistic_total_r_closed") or 0),
        reverse=True,
    )
    return {
        "lane_count": lane_count,
        "reverse_worth_testing_count": reverse_count,
        "direction_weak_count": direction_weak_count,
        "entry_or_risk_weak_count": entry_weak_count,
        "best_lane": ranked[0]["lane"] if ranked else None,
        "worst_lane": ranked[-1]["lane"] if ranked else None,
    }


def _stage_direction(stage: str) -> str:
    if "SHORT" in stage:
        return "SHORT"
    if "LONG" in stage:
        return "LONG"
    return "UNKNOWN"


def _mid_short_second_filter_specs() -> list[FilterStudySpec]:
    return [
        FilterStudySpec(
            "TAKER_SELL_GE_52",
            "Taker sell >= 52%",
            "kline_taker_sell_ratio >= 0.52",
            "taker",
            ("kline_taker_sell_ratio",),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.52"),
        ),
        FilterStudySpec(
            "TAKER_BUY_LE_50",
            "Taker buy <= 50%",
            "kline_taker_buy_ratio <= 0.50",
            "taker",
            ("kline_taker_buy_ratio",),
            lambda item: (_evidence_value(item, "kline_taker_buy_ratio") or Decimal("999")) <= Decimal("0.50"),
        ),
        FilterStudySpec(
            "NO_BTC_ETH_1H_BULL",
            "Exclude BTC/ETH 1h bullish regime",
            "btc_1h_regime != BULLISH_REGIME AND eth_1h_regime != BULLISH_REGIME",
            "regime",
            (),
            lambda item: item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "REGIME_AND_TAKER",
            "No BTC/ETH bull + taker sell >= 52%",
            "btc/eth not bullish AND kline_taker_sell_ratio >= 0.52",
            "combo",
            ("kline_taker_sell_ratio",),
            lambda item: item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME"
            and (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.52"),
        ),
        FilterStudySpec(
            "REGIME_RANGE_TAKER",
            "No BTC/ETH bull + range <= 1.0 + taker sell >= 52%",
            "btc/eth not bullish AND range_ratio_vs_atr <= 1.0 AND kline_taker_sell_ratio >= 0.52",
            "combo",
            ("range_ratio_vs_atr", "kline_taker_sell_ratio"),
            lambda item: item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME"
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.0")
            and (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.52"),
        ),
    ]


def _mid_short_second_filter_shadow_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    baseline_path = _mid_short_path_count_summary(items)
    for spec in _mid_short_second_filter_specs():
        selected, missing = _apply_filter_spec(items, spec)
        perf = _walk_forward_perf(selected, baseline=baseline)
        path_summary = _mid_short_path_count_summary(selected, baseline=baseline_path)
        row = {
            "filter_id": spec.filter_id,
            "label": spec.label,
            "expression": spec.expression,
            "family": spec.family,
            "required_fields": list(spec.required_fields),
            "source_count": len(items),
            "missing_data_count": missing,
            "missing_data_pct": (Decimal(missing) / Decimal(len(items)) * Decimal("100")) if items else None,
            "sample_retention_pct": _retention(len(selected), len(items)),
            "read": _mid_short_second_filter_read(perf, path_summary, min_sample=min_sample),
            **path_summary,
            **perf,
        }
        rows.append(row)
    rows.sort(
        key=lambda row: (
            row["read"] == "SECOND_FILTER_MONITOR",
            row["read"] == "SECOND_FILTER_REDUCES_DAMAGE",
            _decimal_or_zero(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero(row.get("realistic_total_r_delta_vs_baseline")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _apply_named_second_filter(items: list[dict[str, Any]], filter_id: str) -> list[dict[str, Any]]:
    spec = next((row for row in _mid_short_second_filter_specs() if row.filter_id == filter_id), None)
    if spec is None:
        return []
    selected, _missing = _apply_filter_spec(items, spec)
    return selected


def _mid_short_path_count_summary(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sl_items = [item for item in items if item.get("result_status") == "SL_HIT"]
    sample_count = len(items)
    sl_count = len(sl_items)
    summary = {
        "sl_then_would_tp_count": sum(1 for item in sl_items if item.get("after_sl_would_hit_tp")),
        "tp_near_then_sl_count": sum(1 for item in sl_items if item.get("tp_near_before_sl")),
        "wrong_direction_1h_count": sum(1 for item in items if item.get("direction_1h") == "WRONG_DIRECTION"),
        "correct_direction_1h_count": sum(1 for item in items if item.get("direction_1h") == "CORRECT_DIRECTION"),
        "sl_direct_count": sum(1 for item in sl_items if item.get("path_type") == "SL_DIRECT"),
    }
    summary.update(
        {
            "sl_then_would_tp_share_pct": _pct(summary["sl_then_would_tp_count"], sl_count),
            "tp_near_then_sl_share_pct": _pct(summary["tp_near_then_sl_count"], sl_count),
            "wrong_direction_1h_share_pct": _pct(summary["wrong_direction_1h_count"], sample_count),
            "correct_direction_1h_share_pct": _pct(summary["correct_direction_1h_count"], sample_count),
        }
    )
    if baseline is not None:
        for key in (
            "sl_then_would_tp_share_pct",
            "tp_near_then_sl_share_pct",
            "wrong_direction_1h_share_pct",
            "correct_direction_1h_share_pct",
        ):
            summary[f"{key}_delta_vs_baseline"] = _decimal_delta(summary.get(key), baseline.get(key))
    return summary


def _pct(count: int, total: int) -> Decimal | None:
    if total <= 0:
        return None
    return Decimal(count) / Decimal(total) * Decimal("100")


def _mid_short_second_filter_read(
    perf: dict[str, Any],
    path_summary: dict[str, Any],
    *,
    min_sample: int,
) -> str:
    if int(perf.get("closed_count") or 0) < min_sample:
        return "WAIT_MORE_SAMPLE"
    realistic_total = _decimal_or_zero(perf.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_none_any(perf.get("realistic_avg_r_delta_vs_baseline"))
    sl_delta = _decimal_or_none_any(perf.get("sl_share_delta_vs_baseline"))
    wrong_delta = _decimal_or_none_any(path_summary.get("wrong_direction_1h_share_pct_delta_vs_baseline"))
    timing_delta = _decimal_or_none_any(path_summary.get("sl_then_would_tp_share_pct_delta_vs_baseline"))
    if (
        realistic_total > 0
        and avg_delta is not None
        and avg_delta > 0
        and (sl_delta is None or sl_delta <= 0)
        and (wrong_delta is None or wrong_delta <= 0)
    ):
        return "SECOND_FILTER_MONITOR"
    if (
        (avg_delta is not None and avg_delta > 0)
        or (sl_delta is not None and sl_delta < 0)
        or (wrong_delta is not None and wrong_delta < 0)
        or (timing_delta is not None and timing_delta < 0)
    ):
        return "SECOND_FILTER_REDUCES_DAMAGE"
    if avg_delta is not None and avg_delta < 0 and (sl_delta is not None and sl_delta > 0):
        return "SECOND_FILTER_WORSE"
    return "SECOND_FILTER_NO_CLEAR_EDGE"


def _mid_short_second_filter_summary_read(rows: list[dict[str, Any]], *, min_sample: int) -> str:
    if not rows:
        return "NO_SECOND_FILTER_ROWS"
    ready_rows = [row for row in rows if int(row.get("closed_count") or 0) >= min_sample]
    if not ready_rows:
        return "WAIT_MORE_SAMPLE"
    if any(row.get("read") == "SECOND_FILTER_MONITOR" for row in ready_rows):
        return "HAS_SECOND_FILTER_MONITOR_CANDIDATE"
    if any(row.get("read") == "SECOND_FILTER_REDUCES_DAMAGE" for row in ready_rows):
        return "HAS_DAMAGE_REDUCTION_CANDIDATE"
    return "NO_CLEAN_SECOND_FILTER_YET"


def _mid_short_taker_sell_deep_filter_specs() -> list[FilterStudySpec]:
    return [
        FilterStudySpec(
            "TAKER_SELL_GE_55",
            "Taker sell >= 55%",
            "kline_taker_sell_ratio >= 0.55",
            "taker_strength",
            ("kline_taker_sell_ratio",),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.55"),
        ),
        FilterStudySpec(
            "TAKER_SELL_GE_58",
            "Taker sell >= 58%",
            "kline_taker_sell_ratio >= 0.58",
            "taker_strength",
            ("kline_taker_sell_ratio",),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.58"),
        ),
        FilterStudySpec(
            "TAKER_SELL_GE_60",
            "Taker sell >= 60%",
            "kline_taker_sell_ratio >= 0.60",
            "taker_strength",
            ("kline_taker_sell_ratio",),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.60"),
        ),
        FilterStudySpec(
            "RANGE_ATR_LE_1_25",
            "Range/ATR <= 1.25",
            "range_ratio_vs_atr <= 1.25",
            "late_momentum",
            ("range_ratio_vs_atr",),
            lambda item: (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "RANGE_ATR_LE_1_00",
            "Range/ATR <= 1.00",
            "range_ratio_vs_atr <= 1.00",
            "late_momentum",
            ("range_ratio_vs_atr",),
            lambda item: (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.00"),
        ),
        FilterStudySpec(
            "PRICE_ATR_LE_1_25",
            "Price/ATR <= 1.25",
            "price_atr_multiple <= 1.25",
            "late_momentum",
            ("price_atr_multiple",),
            lambda item: (_evidence_value(item, "price_atr_multiple") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "VOLUME_LE_1_50",
            "Volume <= 1.50x lookback",
            "volume_ratio_vs_lookback <= 1.50",
            "late_momentum",
            ("volume_ratio_vs_lookback",),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "FUTURES_SPREAD_LE_0_03",
            "Futures spread <= 0.03%",
            "futures_spread_pct <= 0.03",
            "cost_gate",
            ("futures_spread_pct",),
            lambda item: (_evidence_value(item, "futures_spread_pct") or Decimal("999")) <= Decimal("0.03"),
        ),
        FilterStudySpec(
            "FILL_GOOD_ONLY",
            "Fill good only",
            "realistic_fill_quality == FILL_GOOD",
            "cost_gate",
            (),
            lambda item: str(item.get("realistic_fill_quality") or "") == "FILL_GOOD",
        ),
        FilterStudySpec(
            "COST_R_LE_0_20",
            "Cost R <= 0.20",
            "realistic_cost_r_estimate <= 0.20",
            "cost_gate",
            (),
            lambda item: _decimal_or_none(item.get("realistic_cost_r_estimate")) is not None
            and (_decimal_or_none(item.get("realistic_cost_r_estimate")) or Decimal("999")) <= Decimal("0.20"),
        ),
        FilterStudySpec(
            "PRICE_RETURN_LE_0",
            "Signal candle red/weak",
            "price_return <= 0",
            "direction_gate",
            ("price_return",),
            lambda item: (_evidence_value(item, "price_return") or Decimal("999")) <= Decimal("0"),
        ),
        FilterStudySpec(
            "OI_Z_GE_1",
            "OI z-score >= 1",
            "oi_zscore >= 1",
            "open_interest",
            ("oi_zscore",),
            lambda item: (_evidence_value(item, "oi_zscore") or Decimal("-999")) >= Decimal("1"),
        ),
        FilterStudySpec(
            "OI_Z_GE_2",
            "OI z-score >= 2",
            "oi_zscore >= 2",
            "open_interest",
            ("oi_zscore",),
            lambda item: (_evidence_value(item, "oi_zscore") or Decimal("-999")) >= Decimal("2"),
        ),
        FilterStudySpec(
            "FUNDING_GE_65",
            "Funding percentile >= 65",
            "funding_percentile_30d >= 65",
            "positioning",
            ("funding_percentile_30d",),
            lambda item: (_evidence_value(item, "funding_percentile_30d") or Decimal("-999")) >= Decimal("65"),
        ),
        FilterStudySpec(
            "GLOBAL_LS_GE_1_20",
            "Global long/short >= 1.20",
            "global_long_short_ratio >= 1.20",
            "positioning",
            ("global_long_short_ratio",),
            lambda item: (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "TOP_POSITION_GE_1_20",
            "Top trader position >= 1.20",
            "top_trader_position_ratio >= 1.20",
            "positioning",
            ("top_trader_position_ratio",),
            lambda item: (_evidence_value(item, "top_trader_position_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "NO_BTC_ETH_1H_BULL",
            "Exclude BTC/ETH 1h bullish regime",
            "btc_1h_regime != BULLISH_REGIME AND eth_1h_regime != BULLISH_REGIME",
            "regime",
            (),
            lambda item: item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "TAKER55_AND_RANGE_LE_1_25",
            "Taker sell >=55% + range/ATR <=1.25",
            "kline_taker_sell_ratio >= 0.55 AND range_ratio_vs_atr <= 1.25",
            "combo_taker_late",
            ("kline_taker_sell_ratio", "range_ratio_vs_atr"),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.55")
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "TAKER55_AND_FILL_GOOD",
            "Taker sell >=55% + fill good",
            "kline_taker_sell_ratio >= 0.55 AND realistic_fill_quality == FILL_GOOD",
            "combo_taker_cost",
            ("kline_taker_sell_ratio",),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.55")
            and str(item.get("realistic_fill_quality") or "") == "FILL_GOOD",
        ),
        FilterStudySpec(
            "TAKER55_RANGE_COST",
            "Taker sell >=55% + range <=1.25 + cost R <=0.20",
            "kline_taker_sell_ratio >= 0.55 AND range_ratio_vs_atr <= 1.25 AND realistic_cost_r_estimate <= 0.20",
            "combo_taker_late_cost",
            ("kline_taker_sell_ratio", "range_ratio_vs_atr"),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.55")
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25")
            and _decimal_or_none(item.get("realistic_cost_r_estimate")) is not None
            and (_decimal_or_none(item.get("realistic_cost_r_estimate")) or Decimal("999")) <= Decimal("0.20"),
        ),
        FilterStudySpec(
            "TAKER55_NO_BTC_ETH_BULL",
            "Taker sell >=55% + no BTC/ETH 1h bull",
            "kline_taker_sell_ratio >= 0.55 AND btc/eth not bullish",
            "combo_taker_regime",
            ("kline_taker_sell_ratio",),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.55")
            and item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "TAKER55_POSITIONING",
            "Taker sell >=55% + crowded longs",
            "kline_taker_sell_ratio >= 0.55 AND global_long_short_ratio >= 1.20",
            "combo_taker_positioning",
            ("kline_taker_sell_ratio", "global_long_short_ratio"),
            lambda item: (_evidence_value(item, "kline_taker_sell_ratio") or Decimal("-999")) >= Decimal("0.55")
            and (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
    ]


def _mid_short_taker_sell_deep_filter_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    baseline_path = _mid_short_path_count_summary(items)
    for spec in _mid_short_taker_sell_deep_filter_specs():
        selected, missing = _apply_filter_spec(items, spec)
        perf = _walk_forward_perf(selected, baseline=baseline)
        path_summary = _mid_short_path_count_summary(selected, baseline=baseline_path)
        row = {
            "filter_id": spec.filter_id,
            "label": spec.label,
            "expression": spec.expression,
            "family": spec.family,
            "required_fields": list(spec.required_fields),
            "source_count": len(items),
            "missing_data_count": missing,
            "missing_data_pct": (Decimal(missing) / Decimal(len(items)) * Decimal("100")) if items else None,
            "sample_retention_pct": _retention(len(selected), len(items)),
            "read": _mid_short_taker_sell_deep_filter_read(perf, path_summary, min_sample=min_sample),
            **path_summary,
            **perf,
        }
        rows.append(row)
    rows.sort(
        key=lambda row: (
            row["read"] == "TAKER_DEEP_FILTER_PROMISING",
            row["read"] == "TAKER_DEEP_FILTER_REDUCES_DAMAGE",
            _decimal_or_zero(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero(row.get("realistic_total_r_delta_vs_baseline")),
            _decimal_or_zero(row.get("sl_share_delta_vs_baseline")) * Decimal("-1"),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _apply_named_taker_sell_deep_filter(items: list[dict[str, Any]], filter_id: str) -> list[dict[str, Any]]:
    spec = next((row for row in _mid_short_taker_sell_deep_filter_specs() if row.filter_id == filter_id), None)
    if spec is None:
        return []
    selected, _missing = _apply_filter_spec(items, spec)
    return selected


def _mid_short_taker_sell_deep_filter_read(
    perf: dict[str, Any],
    path_summary: dict[str, Any],
    *,
    min_sample: int,
) -> str:
    if int(perf.get("closed_count") or 0) < min_sample:
        return "TAKER_DEEP_WAIT_MORE_SAMPLE"
    realistic_total = _decimal_or_zero(perf.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_none_any(perf.get("realistic_avg_r_delta_vs_baseline"))
    sl_delta = _decimal_or_none_any(perf.get("sl_share_delta_vs_baseline"))
    wrong_delta = _decimal_or_none_any(path_summary.get("wrong_direction_1h_share_pct_delta_vs_baseline"))
    timing_delta = _decimal_or_none_any(path_summary.get("sl_then_would_tp_share_pct_delta_vs_baseline"))
    drawdown_delta = _decimal_or_none_any(perf.get("max_drawdown_delta_vs_baseline"))
    if (
        realistic_total > 0
        and avg_delta is not None
        and avg_delta > 0
        and (sl_delta is None or sl_delta <= 0)
        and (wrong_delta is None or wrong_delta <= 0)
        and (drawdown_delta is None or drawdown_delta >= 0)
    ):
        return "TAKER_DEEP_FILTER_PROMISING"
    if (
        (avg_delta is not None and avg_delta > 0)
        or (sl_delta is not None and sl_delta < 0)
        or (wrong_delta is not None and wrong_delta < 0)
        or (timing_delta is not None and timing_delta < 0)
    ):
        return "TAKER_DEEP_FILTER_REDUCES_DAMAGE"
    if avg_delta is not None and avg_delta < 0 and (sl_delta is not None and sl_delta > 0):
        return "TAKER_DEEP_FILTER_WORSE"
    return "TAKER_DEEP_NO_CLEAR_EDGE"


def _mid_short_taker_sell_deep_summary_read(rows: list[dict[str, Any]], *, min_sample: int) -> str:
    if not rows:
        return "NO_TAKER_DEEP_FILTER_ROWS"
    ready_rows = [row for row in rows if int(row.get("closed_count") or 0) >= min_sample]
    if not ready_rows:
        return "TAKER_DEEP_WAIT_MORE_SAMPLE"
    if any(row.get("read") == "TAKER_DEEP_FILTER_PROMISING" for row in ready_rows):
        return "HAS_TAKER_DEEP_PROMISING_FILTER"
    if any(row.get("read") == "TAKER_DEEP_FILTER_REDUCES_DAMAGE" for row in ready_rows):
        return "HAS_TAKER_DEEP_DAMAGE_REDUCTION"
    return "NO_TAKER_DEEP_CLEAN_FILTER_YET"


def _annotate_mid_short_wrong_direction(item: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    wrong_type = _mid_short_wrong_direction_type(item)
    enriched.update(
        {
            "wrong_direction_type": wrong_type,
            "first_15m_return_bucket": _mid_short_first_return_bucket(item.get("return_15m_pct")),
            "followthrough_quality": _mid_short_followthrough_quality(item),
            "immediate_reversal_flag": _mid_short_immediate_reversal(item),
            "no_sell_followthrough_flag": _mid_short_no_sell_followthrough(item),
            "btc_eth_pull_up_flag": _mid_short_btc_eth_pull_up(item),
            "sell_absorption_flag": _mid_short_sell_absorption(item),
            "oi_conflict_flag": _mid_short_oi_conflict(item),
            "volume_overextended_flag": _mid_short_volume_overextended(item),
            "range_overextended_flag": _mid_short_range_overextended(item),
            "spot_spread_bad_flag": _mid_short_spot_spread_bad(item),
            "cost_bad_flag": _mid_short_cost_bad(item),
        }
    )
    return enriched


def _mid_short_wrong_direction_type(item: dict[str, Any]) -> str:
    direction_1h = str(item.get("direction_1h") or "")
    if direction_1h == "CORRECT_DIRECTION":
        return "CORRECT_DIRECTION"
    if direction_1h == "FLAT":
        return "FLAT_1H"
    if direction_1h == "MISSING_FORWARD_DATA":
        return "MISSING_FORWARD_DATA"
    if direction_1h != "WRONG_DIRECTION":
        return "WRONG_DIRECTION_OTHER"
    if _mid_short_immediate_reversal(item):
        return "IMMEDIATE_REVERSAL"
    if _mid_short_btc_eth_pull_up(item):
        return "BTC_ETH_PULL_UP"
    if _mid_short_sell_absorption(item):
        return "SELL_ABSORPTION"
    if bool(item.get("after_sl_would_hit_tp")) or str(item.get("direction_2h") or "") == "CORRECT_DIRECTION":
        return "STOP_RUN_THEN_DROP"
    if _mid_short_no_sell_followthrough(item):
        return "NO_SELL_FOLLOWTHROUGH"
    if str(item.get("direction_30m") or "") == "WRONG_DIRECTION":
        return "GRIND_UP"
    return "WRONG_DIRECTION_OTHER"


def _mid_short_immediate_reversal(item: dict[str, Any]) -> bool:
    return str(item.get("direction_15m") or "") == "WRONG_DIRECTION" and _decimal_or_zero(item.get("return_15m_pct")) >= Decimal("0.05")


def _mid_short_no_sell_followthrough(item: dict[str, Any]) -> bool:
    mfe = _decimal_or_none_any(item.get("mfe_before_first_hit_r"))
    return (mfe is not None and mfe < Decimal("0.25")) or str(item.get("direction_15m") or "") in {"WRONG_DIRECTION", "FLAT"}


def _mid_short_btc_eth_pull_up(item: dict[str, Any]) -> bool:
    return item.get("btc_1h_regime") == "BULLISH_REGIME" or item.get("eth_1h_regime") == "BULLISH_REGIME"


def _mid_short_sell_absorption(item: dict[str, Any]) -> bool:
    taker_sell = _evidence_value(item, "kline_taker_sell_ratio")
    price_return = _evidence_value(item, "price_return")
    close_position = _evidence_value(item, "close_position_in_range")
    return (
        taker_sell is not None
        and taker_sell >= Decimal("0.52")
        and (
            (price_return is not None and price_return > 0)
            or (close_position is not None and close_position >= Decimal("0.65"))
        )
    )


def _mid_short_oi_conflict(item: dict[str, Any]) -> bool:
    oi_change = _evidence_value(item, "oi_change_pct")
    oi_z = _evidence_value(item, "oi_zscore")
    price_return = _evidence_value(item, "price_return")
    return (
        ((oi_change is not None and oi_change < 0) or (oi_z is not None and oi_z < Decimal("0.5")))
        and price_return is not None
        and price_return > 0
    )


def _mid_short_volume_overextended(item: dict[str, Any]) -> bool:
    value = _evidence_value(item, "volume_ratio_vs_lookback")
    return value is not None and value > Decimal("1.50")


def _mid_short_range_overextended(item: dict[str, Any]) -> bool:
    value = _evidence_value(item, "range_ratio_vs_atr")
    return value is not None and value > Decimal("1.25")


def _mid_short_spot_spread_bad(item: dict[str, Any]) -> bool:
    value = _evidence_value(item, "spot_spread_pct")
    return value is not None and value > Decimal("0.05")


def _mid_short_cost_bad(item: dict[str, Any]) -> bool:
    value = _decimal_or_none_any(item.get("realistic_cost_r_estimate"))
    return value is not None and value > Decimal("0.20")


def _mid_short_first_return_bucket(value: Any) -> str:
    ret = _decimal_or_none_any(value)
    if ret is None:
        return "MISSING_FORWARD_DATA"
    if ret >= Decimal("0.35"):
        return "UP_STRONG"
    if ret >= Decimal("0.05"):
        return "UP"
    if ret <= Decimal("-0.35"):
        return "DOWN_STRONG"
    if ret <= Decimal("-0.05"):
        return "DOWN"
    return "FLAT"


def _mid_short_followthrough_quality(item: dict[str, Any]) -> str:
    if str(item.get("direction_1h") or "") == "CORRECT_DIRECTION":
        return "SHORT_FOLLOWTHROUGH_1H"
    if str(item.get("direction_15m") or "") == "CORRECT_DIRECTION":
        return "EARLY_DROP_THEN_REBOUND"
    if _mid_short_immediate_reversal(item):
        return "NO_FOLLOWTHROUGH_IMMEDIATE_REVERSAL"
    if str(item.get("direction_1h") or "") == "WRONG_DIRECTION":
        return "NO_SHORT_FOLLOWTHROUGH_1H"
    return "FOLLOWTHROUGH_UNKNOWN"


def _mid_short_wrong_direction_filter_specs() -> list[FilterStudySpec]:
    return [
        FilterStudySpec(
            "PRICE_RETURN_LE_0",
            "Signal candle red/weak",
            "price_return <= 0",
            "direction_gate",
            ("price_return",),
            lambda item: (_evidence_value(item, "price_return") or Decimal("999")) <= Decimal("0"),
        ),
        FilterStudySpec(
            "CLOSE_POSITION_LE_0_45",
            "Close not near candle high",
            "close_position_in_range <= 0.45",
            "candle_structure",
            ("close_position_in_range",),
            lambda item: (_evidence_value(item, "close_position_in_range") or Decimal("999")) <= Decimal("0.45"),
        ),
        FilterStudySpec(
            "VOLUME_LE_1_50",
            "Volume <= 1.50x lookback",
            "volume_ratio_vs_lookback <= 1.50",
            "late_momentum",
            ("volume_ratio_vs_lookback",),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "RANGE_ATR_LE_1_00",
            "Range/ATR <= 1.00",
            "range_ratio_vs_atr <= 1.00",
            "late_momentum",
            ("range_ratio_vs_atr",),
            lambda item: (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.00"),
        ),
        FilterStudySpec(
            "PRICE_ATR_LE_1_25",
            "Price/ATR <= 1.25",
            "price_atr_multiple <= 1.25",
            "late_momentum",
            ("price_atr_multiple",),
            lambda item: (_evidence_value(item, "price_atr_multiple") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "NO_BTC_ETH_1H_BULL",
            "Exclude BTC/ETH 1h bullish regime",
            "btc_1h_regime != BULLISH_REGIME AND eth_1h_regime != BULLISH_REGIME",
            "regime",
            (),
            lambda item: item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "OI_Z_GE_1",
            "OI z-score >= 1",
            "oi_zscore >= 1",
            "open_interest",
            ("oi_zscore",),
            lambda item: (_evidence_value(item, "oi_zscore") or Decimal("-999")) >= Decimal("1"),
        ),
        FilterStudySpec(
            "OI_CHANGE_GE_0",
            "OI not unwinding",
            "oi_change_pct >= 0",
            "open_interest",
            ("oi_change_pct",),
            lambda item: (_evidence_value(item, "oi_change_pct") or Decimal("-999")) >= Decimal("0"),
        ),
        FilterStudySpec(
            "FUNDING_GE_65",
            "Funding percentile >= 65",
            "funding_percentile_30d >= 65",
            "positioning",
            ("funding_percentile_30d",),
            lambda item: (_evidence_value(item, "funding_percentile_30d") or Decimal("-999")) >= Decimal("65"),
        ),
        FilterStudySpec(
            "GLOBAL_LS_GE_1_20",
            "Global long/short >= 1.20",
            "global_long_short_ratio >= 1.20",
            "positioning",
            ("global_long_short_ratio",),
            lambda item: (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "TOP_POSITION_GE_1_20",
            "Top trader position >= 1.20",
            "top_trader_position_ratio >= 1.20",
            "positioning",
            ("top_trader_position_ratio",),
            lambda item: (_evidence_value(item, "top_trader_position_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "FUTURES_SPREAD_LE_0_03",
            "Futures spread <= 0.03%",
            "futures_spread_pct <= 0.03",
            "cost_gate",
            ("futures_spread_pct",),
            lambda item: (_evidence_value(item, "futures_spread_pct") or Decimal("999")) <= Decimal("0.03"),
        ),
        FilterStudySpec(
            "VOLUME_AND_PRICE_WEAK",
            "Volume <=1.50x + signal candle weak",
            "volume_ratio_vs_lookback <= 1.50 AND price_return <= 0",
            "combo_late_momentum",
            ("volume_ratio_vs_lookback", "price_return"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "price_return") or Decimal("999")) <= Decimal("0"),
        ),
        FilterStudySpec(
            "VOLUME_NO_BTC_ETH_BULL",
            "Volume <=1.50x + no BTC/ETH bull",
            "volume_ratio_vs_lookback <= 1.50 AND btc/eth not bullish",
            "combo_regime_momentum",
            ("volume_ratio_vs_lookback",),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "WEAK_CANDLE_NO_BTC_ETH_BULL",
            "Weak signal candle + no BTC/ETH bull",
            "price_return <= 0 AND close_position <= 0.45 AND btc/eth not bullish",
            "combo_structure_regime",
            ("price_return", "close_position_in_range"),
            lambda item: (_evidence_value(item, "price_return") or Decimal("999")) <= Decimal("0")
            and (_evidence_value(item, "close_position_in_range") or Decimal("999")) <= Decimal("0.45")
            and item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "POSITIONING_VOLUME",
            "Crowded longs + volume <=1.50x",
            "global_long_short_ratio >= 1.20 AND volume_ratio_vs_lookback <= 1.50",
            "combo_positioning_momentum",
            ("global_long_short_ratio", "volume_ratio_vs_lookback"),
            lambda item: (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20")
            and (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
    ]


def _mid_short_wrong_direction_filter_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    direction_baseline = _mid_short_direction_summary(items)
    for spec in _mid_short_wrong_direction_filter_specs():
        selected, missing = _apply_filter_spec(items, spec)
        perf = _walk_forward_perf(selected, baseline=baseline)
        direction_summary = _mid_short_direction_summary(selected, baseline=direction_baseline)
        row = {
            "filter_id": spec.filter_id,
            "label": spec.label,
            "expression": spec.expression,
            "family": spec.family,
            "required_fields": list(spec.required_fields),
            "source_count": len(items),
            "missing_data_count": missing,
            "missing_data_pct": (Decimal(missing) / Decimal(len(items)) * Decimal("100")) if items else None,
            "sample_retention_pct": _retention(len(selected), len(items)),
            "read": _mid_short_wrong_direction_filter_read(perf, direction_summary, min_sample=min_sample),
            **direction_summary,
            **perf,
        }
        rows.append(row)
    rows.sort(
        key=lambda row: (
            row["read"] == "WRONG_DIR_FILTER_PROMISING",
            row["read"] == "WRONG_DIR_FILTER_REDUCES_DAMAGE",
            _decimal_or_zero(row.get("wrong_direction_1h_share_pct_delta_vs_baseline")) * Decimal("-1"),
            _decimal_or_zero(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero(row.get("sl_share_delta_vs_baseline")) * Decimal("-1"),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _apply_named_wrong_direction_filter(items: list[dict[str, Any]], filter_id: str) -> list[dict[str, Any]]:
    spec = next((row for row in _mid_short_wrong_direction_filter_specs() if row.filter_id == filter_id), None)
    if spec is None:
        return []
    selected, _missing = _apply_filter_spec(items, spec)
    return selected


def _filter_spec_by_id(specs: list[FilterStudySpec], filter_id: str) -> FilterStudySpec:
    spec = next((row for row in specs if row.filter_id == filter_id), None)
    if spec is None:
        raise ValueError(f"Unknown filter spec: {filter_id}")
    return spec


def _split_filter_spec(
    items: list[dict[str, Any]],
    spec: FilterStudySpec,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    passed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for item in items:
        evidence = item.get("evidence_snapshot") or {}
        if any(evidence.get(field) is None for field in spec.required_fields):
            missing.append(item)
            continue
        if spec.predicate(item):
            passed.append(item)
        else:
            failed.append(item)
    return passed, failed, missing


def _mid_short_volume_safe_status_rows(
    *,
    pass_items: list[dict[str, Any]],
    fail_items: list[dict[str, Any]],
    missing_items: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for status, label, items in (
        ("VOLUME_SAFE_PASS", "Volume <= 1.50x", pass_items),
        ("VOLUME_SAFE_FAIL", "Volume > 1.50x", fail_items),
        ("VOLUME_SAFE_MISSING", "Volume evidence missing", missing_items),
    ):
        perf = _walk_forward_perf(items, baseline=baseline)
        rows.append(
            {
                "shadow_status": status,
                "bucket": status,
                "label": label,
                "sample_retention_pct": _retention(len(items), int(baseline.get("sample_count") or 0)),
                **_mid_short_direction_summary(items, baseline=_mid_short_direction_summary(pass_items + fail_items + missing_items)),
                **perf,
            }
        )
    return rows


def _mid_short_volume_safe_read(
    pass_perf: dict[str, Any],
    fail_perf: dict[str, Any],
    pass_direction: dict[str, Any],
    *,
    min_sample: int,
) -> str:
    if int(pass_perf.get("closed_count") or 0) < min_sample:
        return "VOLUME_SAFE_WAIT_MORE_SAMPLE"
    pass_total = _decimal_or_zero(pass_perf.get("realistic_total_r_closed"))
    pass_avg_delta = _decimal_or_none_any(pass_perf.get("realistic_avg_r_delta_vs_baseline"))
    fail_avg = _decimal_or_none_any(fail_perf.get("realistic_avg_r_closed"))
    pass_avg = _decimal_or_none_any(pass_perf.get("realistic_avg_r_closed"))
    wrong_delta = _decimal_or_none_any(pass_direction.get("wrong_direction_1h_share_pct_delta_vs_baseline"))
    if (
        pass_total > 0
        and pass_avg_delta is not None
        and pass_avg_delta > 0
        and (wrong_delta is None or wrong_delta <= 0)
        and (fail_avg is None or pass_avg is None or pass_avg > fail_avg)
    ):
        return "VOLUME_SAFE_SHADOW_MONITOR"
    if (pass_avg_delta is not None and pass_avg_delta > 0) or (wrong_delta is not None and wrong_delta < 0):
        return "VOLUME_SAFE_REDUCES_DAMAGE"
    return "VOLUME_SAFE_NO_CLEAR_EDGE"


def _mid_short_filter_combination_specs() -> list[FilterStudySpec]:
    return [
        FilterStudySpec(
            "VOLUME_LE_1_50",
            "Volume <= 1.50x",
            "volume_ratio_vs_lookback <= 1.50",
            "late_momentum",
            ("volume_ratio_vs_lookback",),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "VOLUME_NO_BTC_ETH_BULL",
            "Volume <= 1.50x + no BTC/ETH bull",
            "volume_ratio_vs_lookback <= 1.50 AND btc/eth not bullish",
            "combo_regime_momentum",
            ("volume_ratio_vs_lookback",),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME",
        ),
        FilterStudySpec(
            "VOLUME_RANGE_LE_1_25",
            "Volume <= 1.50x + range/ATR <= 1.25",
            "volume_ratio_vs_lookback <= 1.50 AND range_ratio_vs_atr <= 1.25",
            "combo_late_momentum",
            ("volume_ratio_vs_lookback", "range_ratio_vs_atr"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "VOLUME_PRICE_ATR_LE_1_25",
            "Volume <= 1.50x + price/ATR <= 1.25",
            "volume_ratio_vs_lookback <= 1.50 AND price_atr_multiple <= 1.25",
            "combo_late_momentum",
            ("volume_ratio_vs_lookback", "price_atr_multiple"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "price_atr_multiple") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "VOLUME_NO_LATE_MOMENTUM",
            "Volume <= 1.50x + range <= 1.25 + price/ATR <= 1.25",
            "volume <= 1.50 AND range_ratio_vs_atr <= 1.25 AND price_atr_multiple <= 1.25",
            "combo_late_momentum",
            ("volume_ratio_vs_lookback", "range_ratio_vs_atr", "price_atr_multiple"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25")
            and (_evidence_value(item, "price_atr_multiple") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "VOLUME_FILL_GOOD",
            "Volume <= 1.50x + fill good",
            "volume_ratio_vs_lookback <= 1.50 AND realistic_fill_quality == FILL_GOOD",
            "combo_cost_momentum",
            ("volume_ratio_vs_lookback",),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and str(item.get("realistic_fill_quality") or "") == "FILL_GOOD",
        ),
        FilterStudySpec(
            "VOLUME_COST_R_LE_0_20",
            "Volume <= 1.50x + cost R <= 0.20",
            "volume_ratio_vs_lookback <= 1.50 AND realistic_cost_r_estimate <= 0.20",
            "combo_cost_momentum",
            ("volume_ratio_vs_lookback",),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and _decimal_or_none(item.get("realistic_cost_r_estimate")) is not None
            and (_decimal_or_none(item.get("realistic_cost_r_estimate")) or Decimal("999")) <= Decimal("0.20"),
        ),
        FilterStudySpec(
            "VOLUME_SPREAD_LE_0_03",
            "Volume <= 1.50x + futures spread <= 0.03%",
            "volume_ratio_vs_lookback <= 1.50 AND futures_spread_pct <= 0.03",
            "combo_cost_momentum",
            ("volume_ratio_vs_lookback", "futures_spread_pct"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "futures_spread_pct") or Decimal("999")) <= Decimal("0.03"),
        ),
        FilterStudySpec(
            "VOLUME_OI_Z_GE_1",
            "Volume <= 1.50x + OI z-score >= 1",
            "volume_ratio_vs_lookback <= 1.50 AND oi_zscore >= 1",
            "combo_oi_momentum",
            ("volume_ratio_vs_lookback", "oi_zscore"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "oi_zscore") or Decimal("-999")) >= Decimal("1"),
        ),
        FilterStudySpec(
            "VOLUME_OI_CHANGE_GE_0",
            "Volume <= 1.50x + OI not unwinding",
            "volume_ratio_vs_lookback <= 1.50 AND oi_change_pct >= 0",
            "combo_oi_momentum",
            ("volume_ratio_vs_lookback", "oi_change_pct"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "oi_change_pct") or Decimal("-999")) >= Decimal("0"),
        ),
        FilterStudySpec(
            "VOLUME_FUNDING_GE_65",
            "Volume <= 1.50x + funding percentile >= 65",
            "volume_ratio_vs_lookback <= 1.50 AND funding_percentile_30d >= 65",
            "combo_positioning_momentum",
            ("volume_ratio_vs_lookback", "funding_percentile_30d"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "funding_percentile_30d") or Decimal("-999")) >= Decimal("65"),
        ),
        FilterStudySpec(
            "VOLUME_GLOBAL_LS_GE_1_20",
            "Volume <= 1.50x + global L/S >= 1.20",
            "volume_ratio_vs_lookback <= 1.50 AND global_long_short_ratio >= 1.20",
            "combo_positioning_momentum",
            ("volume_ratio_vs_lookback", "global_long_short_ratio"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "VOLUME_TOP_POSITION_GE_1_20",
            "Volume <= 1.50x + top position >= 1.20",
            "volume_ratio_vs_lookback <= 1.50 AND top_trader_position_ratio >= 1.20",
            "combo_positioning_momentum",
            ("volume_ratio_vs_lookback", "top_trader_position_ratio"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "top_trader_position_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "VOLUME_POSITIONING",
            "Volume <= 1.50x + crowded positioning",
            "volume <= 1.50 AND global L/S >= 1.20 AND top position >= 1.20",
            "combo_positioning_momentum",
            ("volume_ratio_vs_lookback", "global_long_short_ratio", "top_trader_position_ratio"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20")
            and (_evidence_value(item, "top_trader_position_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "VOLUME_NO_BULL_COST_RANGE",
            "Volume <= 1.50x + no BTC/ETH bull + cost <= 0.20 + range <= 1.25",
            "volume <= 1.50 AND btc/eth not bullish AND cost <= 0.20 AND range <= 1.25",
            "combo_full_quality",
            ("volume_ratio_vs_lookback", "range_ratio_vs_atr"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and item.get("btc_1h_regime") != "BULLISH_REGIME"
            and item.get("eth_1h_regime") != "BULLISH_REGIME"
            and _decimal_or_none(item.get("realistic_cost_r_estimate")) is not None
            and (_decimal_or_none(item.get("realistic_cost_r_estimate")) or Decimal("999")) <= Decimal("0.20")
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25"),
        ),
    ]


def _mid_short_filter_combination_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    baseline_direction: dict[str, Any],
    baseline_path: dict[str, Any],
    min_sample: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in _mid_short_filter_combination_specs():
        selected, missing = _apply_filter_spec(items, spec)
        perf = _walk_forward_perf(selected, baseline=baseline)
        direction_summary = _mid_short_direction_summary(selected, baseline=baseline_direction)
        path_summary = _mid_short_path_count_summary(selected, baseline=baseline_path)
        row = {
            "filter_id": spec.filter_id,
            "label": spec.label,
            "expression": spec.expression,
            "family": spec.family,
            "required_fields": list(spec.required_fields),
            "source_count": len(items),
            "missing_data_count": missing,
            "missing_data_pct": (Decimal(missing) / Decimal(len(items)) * Decimal("100")) if items else None,
            "sample_retention_pct": _retention(len(selected), len(items)),
            **direction_summary,
            **path_summary,
            **perf,
        }
        row["read"] = _mid_short_filter_combination_read(row, min_sample=min_sample)
        row["shadow_recommendation"] = _mid_short_filter_combination_recommendation(row)
        row["risk_notes"] = _mid_short_filter_combination_risk_notes(row, min_sample=min_sample)
        rows.append(row)

    read_rank = {
        "COMBO_SHADOW_CANDIDATE": 4,
        "COMBO_REDUCES_DAMAGE": 3,
        "COMBO_NO_CLEAR_EDGE": 2,
        "COMBO_WAIT_MORE_SAMPLE": 1,
        "COMBO_REJECT": 0,
    }
    rows.sort(
        key=lambda row: (
            read_rank.get(str(row.get("read")), -1),
            _decimal_or_zero(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero(row.get("wrong_direction_1h_share_pct_delta_vs_baseline")) * Decimal("-1"),
            _decimal_or_zero(row.get("sl_share_delta_vs_baseline")) * Decimal("-1"),
            _decimal_or_zero(row.get("realistic_total_r_closed")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows[:limit]


def _mid_short_filter_combination_read(row: dict[str, Any], *, min_sample: int) -> str:
    if int(row.get("closed_count") or 0) < min_sample:
        return "COMBO_WAIT_MORE_SAMPLE"
    realistic_total = _decimal_or_zero(row.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_none_any(row.get("realistic_avg_r_delta_vs_baseline"))
    sl_delta = _decimal_or_none_any(row.get("sl_share_delta_vs_baseline"))
    wrong_delta = _decimal_or_none_any(row.get("wrong_direction_1h_share_pct_delta_vs_baseline"))
    drawdown_delta = _decimal_or_none_any(row.get("max_drawdown_delta_vs_baseline"))
    top_share = _decimal_or_none_any(row.get("top_symbol_share_pct"))
    concentration_ok = top_share is None or top_share <= Decimal("35")
    if (
        realistic_total > 0
        and avg_delta is not None
        and avg_delta >= Decimal("0.04")
        and (sl_delta is None or sl_delta <= Decimal("0"))
        and (wrong_delta is None or wrong_delta <= Decimal("0"))
        and (drawdown_delta is None or drawdown_delta >= Decimal("0"))
        and concentration_ok
    ):
        return "COMBO_SHADOW_CANDIDATE"
    if (
        (avg_delta is not None and avg_delta > 0)
        or (sl_delta is not None and sl_delta < 0)
        or (wrong_delta is not None and wrong_delta < 0)
        or (drawdown_delta is not None and drawdown_delta > 0)
    ):
        return "COMBO_REDUCES_DAMAGE"
    if avg_delta is not None and avg_delta < 0 and sl_delta is not None and sl_delta > 0:
        return "COMBO_REJECT"
    return "COMBO_NO_CLEAR_EDGE"


def _mid_short_filter_combination_recommendation(row: dict[str, Any]) -> str:
    read = row.get("read")
    if read == "COMBO_SHADOW_CANDIDATE":
        return "Kandidat V2.1 shadow monitor; belum promosi live."
    if read == "COMBO_REDUCES_DAMAGE":
        return "Pantau sebagai damage-reduction; butuh sample lebih bersih."
    if read == "COMBO_WAIT_MORE_SAMPLE":
        return "Sample belum cukup untuk dibaca."
    if read == "COMBO_REJECT":
        return "Jangan dipakai; kombinasi memperburuk baseline."
    return "Belum ada separation yang jelas."


def _mid_short_filter_combination_risk_notes(row: dict[str, Any], *, min_sample: int) -> list[str]:
    notes: list[str] = []
    if int(row.get("closed_count") or 0) < min_sample:
        notes.append(f"Closed sample < {min_sample}.")
    if _decimal_or_zero(row.get("realistic_total_r_closed")) <= 0:
        notes.append("Realistic R belum positif.")
    sl_delta = _decimal_or_none_any(row.get("sl_share_delta_vs_baseline"))
    if sl_delta is not None and sl_delta > 0:
        notes.append("SL share naik vs baseline.")
    wrong_delta = _decimal_or_none_any(row.get("wrong_direction_1h_share_pct_delta_vs_baseline"))
    if wrong_delta is not None and wrong_delta > 0:
        notes.append("Wrong-direction 1h naik vs baseline.")
    top_share = _decimal_or_none_any(row.get("top_symbol_share_pct"))
    if top_share is not None and top_share > Decimal("35"):
        notes.append("Terlalu terkonsentrasi di satu symbol.")
    missing_pct = _decimal_or_none_any(row.get("missing_data_pct"))
    if missing_pct is not None and missing_pct > Decimal("25"):
        notes.append("Evidence missing tinggi.")
    if not notes:
        notes.append("Belum ada risk note fatal di metric ini.")
    return notes


def _mid_short_filter_combination_summary_read(rows: list[dict[str, Any]], *, min_sample: int) -> str:
    if not rows:
        return "NO_COMBO_FILTER_ROWS"
    ready_rows = [row for row in rows if int(row.get("closed_count") or 0) >= min_sample]
    if not ready_rows:
        return "COMBO_WAIT_MORE_SAMPLE"
    if any(row.get("read") == "COMBO_SHADOW_CANDIDATE" for row in ready_rows):
        return "HAS_V2_1_SHADOW_CANDIDATE"
    if any(row.get("read") == "COMBO_REDUCES_DAMAGE" for row in ready_rows):
        return "HAS_COMBO_DAMAGE_REDUCTION"
    return "NO_CLEAN_COMBO_FILTER_YET"


def _mid_short_filter_combination_decision_panel(
    rows: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    baseline_direction: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    ready_rows = [row for row in rows if int(row.get("closed_count") or 0) >= min_sample]
    shadow_rows = [row for row in ready_rows if row.get("read") == "COMBO_SHADOW_CANDIDATE"]
    top_shadow = shadow_rows[0] if shadow_rows else None
    monitor_rows = [row for row in ready_rows if row.get("read") in {"COMBO_SHADOW_CANDIDATE", "COMBO_REDUCES_DAMAGE"}]
    monitor_row = top_shadow or (monitor_rows[0] if monitor_rows else (ready_rows[0] if ready_rows else None))
    best_sl = min(
        ready_rows,
        key=lambda row: (
            _decimal_or_none_any(row.get("sl_share_delta_vs_baseline")) or Decimal("999"),
            _decimal_or_none_any(row.get("realistic_avg_r_delta_vs_baseline")) or Decimal("-999"),
        ),
        default=None,
    )
    best_wrong = min(
        ready_rows,
        key=lambda row: (
            _decimal_or_none_any(row.get("wrong_direction_1h_share_pct_delta_vs_baseline")) or Decimal("999"),
            _decimal_or_none_any(row.get("realistic_avg_r_delta_vs_baseline")) or Decimal("-999"),
        ),
        default=None,
    )
    best_drawdown = max(
        ready_rows,
        key=lambda row: (
            _decimal_or_none_any(row.get("max_drawdown_delta_vs_baseline")) or Decimal("-999"),
            _decimal_or_none_any(row.get("realistic_avg_r_delta_vs_baseline")) or Decimal("-999"),
        ),
        default=None,
    )

    baseline_closed = int(baseline.get("closed_count") or 0)
    baseline_realistic_total = _decimal_or_zero(baseline.get("realistic_total_r_closed"))
    baseline_realistic_avg = _decimal_or_zero(baseline.get("realistic_avg_r_closed"))
    baseline_sl_share = _decimal_or_none_any(baseline.get("sl_share_pct"))
    baseline_wrong_share = _decimal_or_none_any(baseline_direction.get("wrong_direction_1h_share_pct"))

    blockers: list[str] = []
    if baseline_closed < 120:
        blockers.append("Closed sample masih < 120; belum cukup untuk promosi rule.")
    if top_shadow is None:
        blockers.append("Belum ada combo yang lolos sebagai V2.1 shadow candidate.")
    else:
        top_sl_delta = _decimal_or_none_any(top_shadow.get("sl_share_delta_vs_baseline"))
        top_wrong_delta = _decimal_or_none_any(top_shadow.get("wrong_direction_1h_share_pct_delta_vs_baseline"))
        top_avg_delta = _decimal_or_none_any(top_shadow.get("realistic_avg_r_delta_vs_baseline"))
        if top_sl_delta is not None and top_sl_delta > Decimal("-5"):
            blockers.append("SL share belum turun minimal 5pp dari baseline.")
        if top_wrong_delta is not None and top_wrong_delta > Decimal("-5"):
            blockers.append("Wrong-direction belum turun minimal 5pp dari baseline.")
        if top_avg_delta is not None and top_avg_delta < Decimal("0.08"):
            blockers.append("Realistic avg R belum naik minimal +0.08R dari baseline.")

    if top_shadow is not None:
        decision = "MONITOR_V2_1_SHADOW"
    elif any(row.get("read") == "COMBO_REDUCES_DAMAGE" for row in ready_rows):
        decision = "MONITOR_DAMAGE_REDUCTION_ONLY"
    elif ready_rows:
        decision = "NO_PROMOTABLE_FILTER_YET"
    else:
        decision = "WAIT_MORE_SAMPLE"

    recommendation = (
        "Pantau top combo sebagai V2.1 shadow, tapi jangan promosi ke Signal Factory sampai blocker promosi hilang."
        if decision == "MONITOR_V2_1_SHADOW"
        else "Belum ada filter yang cukup bersih untuk dipromosikan; lanjut kumpulkan sample dan baca damage-reduction."
    )

    return {
        "decision": decision,
        "recommendation": recommendation,
        "baseline_snapshot": {
            "closed_count": baseline_closed,
            "tp_count": int(baseline.get("tp_count") or 0),
            "sl_count": int(baseline.get("sl_count") or 0),
            "realistic_total_r_closed": baseline_realistic_total,
            "realistic_avg_r_closed": baseline_realistic_avg,
            "sl_share_pct": baseline_sl_share,
            "wrong_direction_1h_share_pct": baseline_wrong_share,
        },
        "watch_filter": _mid_short_filter_combination_brief(monitor_row),
        "best_sl_reducer": _mid_short_filter_combination_brief(best_sl),
        "best_wrong_direction_reducer": _mid_short_filter_combination_brief(best_wrong),
        "best_drawdown_reducer": _mid_short_filter_combination_brief(best_drawdown),
        "promotion_blockers": blockers or ["Belum ada blocker teknis, tapi tetap butuh forward validation sebelum rule live."],
        "next_validation": [
            "Tunggu closed sample MID_SHORT 1h minimal 120.",
            "Top filter harus menjaga realistic total R positif.",
            "SL share dan wrong-direction idealnya turun >= 5pp vs baseline.",
            "Realistic avg R idealnya naik >= +0.08R vs baseline.",
            "Tidak boleh ada concentration satu symbol > 20%.",
        ],
    }


def _mid_short_filter_combination_brief(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "filter_id": row.get("filter_id"),
        "label": row.get("label"),
        "expression": row.get("expression"),
        "read": row.get("read"),
        "sample_count": row.get("sample_count"),
        "closed_count": row.get("closed_count"),
        "tp_count": row.get("tp_count"),
        "sl_count": row.get("sl_count"),
        "realistic_total_r_closed": row.get("realistic_total_r_closed"),
        "realistic_avg_r_closed": row.get("realistic_avg_r_closed"),
        "realistic_avg_r_delta_vs_baseline": row.get("realistic_avg_r_delta_vs_baseline"),
        "sl_share_pct": row.get("sl_share_pct"),
        "sl_share_delta_vs_baseline": row.get("sl_share_delta_vs_baseline"),
        "wrong_direction_1h_share_pct": row.get("wrong_direction_1h_share_pct"),
        "wrong_direction_1h_share_pct_delta_vs_baseline": row.get("wrong_direction_1h_share_pct_delta_vs_baseline"),
        "max_realistic_drawdown_r": row.get("max_realistic_drawdown_r"),
        "max_drawdown_delta_vs_baseline": row.get("max_drawdown_delta_vs_baseline"),
        "top_symbol": row.get("top_symbol"),
        "top_symbol_share_pct": row.get("top_symbol_share_pct"),
    }


def _mid_short_wrong_direction_filter_read(
    perf: dict[str, Any],
    direction_summary: dict[str, Any],
    *,
    min_sample: int,
) -> str:
    if int(perf.get("closed_count") or 0) < min_sample:
        return "WRONG_DIR_WAIT_MORE_SAMPLE"
    realistic_total = _decimal_or_zero(perf.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_none_any(perf.get("realistic_avg_r_delta_vs_baseline"))
    sl_delta = _decimal_or_none_any(perf.get("sl_share_delta_vs_baseline"))
    wrong_delta = _decimal_or_none_any(direction_summary.get("wrong_direction_1h_share_pct_delta_vs_baseline"))
    drawdown_delta = _decimal_or_none_any(perf.get("max_drawdown_delta_vs_baseline"))
    if (
        realistic_total > 0
        and avg_delta is not None
        and avg_delta > 0
        and wrong_delta is not None
        and wrong_delta < 0
        and (sl_delta is None or sl_delta <= 0)
        and (drawdown_delta is None or drawdown_delta >= 0)
    ):
        return "WRONG_DIR_FILTER_PROMISING"
    if (
        (wrong_delta is not None and wrong_delta < 0)
        or (avg_delta is not None and avg_delta > 0)
        or (sl_delta is not None and sl_delta < 0)
    ):
        return "WRONG_DIR_FILTER_REDUCES_DAMAGE"
    if avg_delta is not None and avg_delta < 0 and wrong_delta is not None and wrong_delta > 0:
        return "WRONG_DIR_FILTER_WORSE"
    return "WRONG_DIR_NO_CLEAR_EDGE"


def _mid_short_wrong_direction_summary_read(rows: list[dict[str, Any]], *, min_sample: int) -> str:
    if not rows:
        return "NO_WRONG_DIRECTION_FILTER_ROWS"
    ready_rows = [row for row in rows if int(row.get("closed_count") or 0) >= min_sample]
    if not ready_rows:
        return "WRONG_DIR_WAIT_MORE_SAMPLE"
    if any(row.get("read") == "WRONG_DIR_FILTER_PROMISING" for row in ready_rows):
        return "HAS_WRONG_DIR_PROMISING_FILTER"
    if any(row.get("read") == "WRONG_DIR_FILTER_REDUCES_DAMAGE" for row in ready_rows):
        return "HAS_WRONG_DIR_DAMAGE_REDUCTION"
    return "NO_WRONG_DIRECTION_CLEAN_FILTER_YET"


def _mid_short_direction_summary(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = len(items)
    wrong = sum(1 for item in items if item.get("direction_1h") == "WRONG_DIRECTION")
    correct = sum(1 for item in items if item.get("direction_1h") == "CORRECT_DIRECTION")
    flat = sum(1 for item in items if item.get("direction_1h") == "FLAT")
    missing = sum(1 for item in items if item.get("direction_1h") == "MISSING_FORWARD_DATA")
    row: dict[str, Any] = {
        "wrong_direction_1h_count": wrong,
        "correct_direction_1h_count": correct,
        "flat_1h_count": flat,
        "missing_direction_1h_count": missing,
        "wrong_direction_1h_share_pct": (Decimal(wrong) / Decimal(total) * Decimal("100")) if total else None,
        "correct_direction_1h_share_pct": (Decimal(correct) / Decimal(total) * Decimal("100")) if total else None,
        "flat_1h_share_pct": (Decimal(flat) / Decimal(total) * Decimal("100")) if total else None,
        "missing_direction_1h_share_pct": (Decimal(missing) / Decimal(total) * Decimal("100")) if total else None,
    }
    if baseline is not None:
        row.update(
            {
                "wrong_direction_1h_share_pct_delta_vs_baseline": _decimal_delta(
                    row.get("wrong_direction_1h_share_pct"),
                    baseline.get("wrong_direction_1h_share_pct"),
                ),
                "correct_direction_1h_share_pct_delta_vs_baseline": _decimal_delta(
                    row.get("correct_direction_1h_share_pct"),
                    baseline.get("correct_direction_1h_share_pct"),
                ),
            }
        )
    return row


def _mid_short_wrong_direction_followthrough_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in (
        "first_15m_return_bucket",
        "followthrough_quality",
        "immediate_reversal_flag",
        "no_sell_followthrough_flag",
        "btc_eth_pull_up_flag",
        "sell_absorption_flag",
        "oi_conflict_flag",
        "volume_overextended_flag",
        "range_overextended_flag",
        "spot_spread_bad_flag",
        "cost_bad_flag",
    ):
        rows.extend(_anatomy_bucket_rows(items, key=key, min_sample=min_sample, baseline=baseline))
    rows.sort(
        key=lambda row: (
            row.get("dimension"),
            _decimal_or_zero(row.get("realistic_total_r_closed")),
        )
    )
    return rows


def _direction_evidence_field_rows(
    correct_items: list[dict[str, Any]],
    wrong_items: list[dict[str, Any]],
    *,
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    all_items = correct_items + wrong_items
    for field, label in EVIDENCE_FIELDS:
        correct_values = [
            Decimal(value)
            for item in correct_items
            if (value := (item.get("evidence_snapshot") or {}).get(field)) is not None
        ]
        wrong_values = [
            Decimal(value)
            for item in wrong_items
            if (value := (item.get("evidence_snapshot") or {}).get(field)) is not None
        ]
        available_count = len(correct_values) + len(wrong_values)
        missing_count = len(all_items) - available_count
        correct_median = _median_decimal(correct_values)
        wrong_median = _median_decimal(wrong_values)
        delta = _decimal_delta(correct_median, wrong_median)
        rows.append(
            {
                "field": field,
                "label": label,
                "quality_flag": _direction_evidence_quality_flag(correct_values, wrong_values, min_sample=min_sample),
                "available_count": available_count,
                "missing_count": missing_count,
                "available_pct": (Decimal(available_count) / Decimal(len(all_items)) * Decimal("100")) if all_items else None,
                "correct_count": len(correct_values),
                "wrong_count": len(wrong_values),
                "correct_median": correct_median,
                "wrong_median": wrong_median,
                "correct_q1": _percentile_decimal(correct_values, Decimal("0.25")),
                "correct_q3": _percentile_decimal(correct_values, Decimal("0.75")),
                "wrong_q1": _percentile_decimal(wrong_values, Decimal("0.25")),
                "wrong_q3": _percentile_decimal(wrong_values, Decimal("0.75")),
                "delta_correct_minus_wrong": delta,
            }
        )
    rows.sort(
        key=lambda row: (
            row["quality_flag"] not in {"CORRECT_HIGHER", "WRONG_HIGHER"},
            _decimal_or_zero(row.get("delta_correct_minus_wrong")).copy_abs(),
            row["available_count"],
        ),
        reverse=True,
    )
    return rows


def _direction_evidence_quality_flag(
    correct_values: list[Decimal],
    wrong_values: list[Decimal],
    *,
    min_sample: int,
) -> str:
    if len(correct_values) < min_sample or len(wrong_values) < min_sample:
        return "SAMPLE_TOO_SMALL"
    correct_median = _median_decimal(correct_values)
    wrong_median = _median_decimal(wrong_values)
    if correct_median is None or wrong_median is None:
        return "NO_CLEAR_GAP"
    delta = correct_median - wrong_median
    if abs(delta) < Decimal("0.05"):
        return "NO_CLEAR_GAP"
    return "CORRECT_HIGHER" if delta > 0 else "WRONG_HIGHER"


def _v2_mid_short_1h_refinement_specs() -> list[FilterStudySpec]:
    return [
        FilterStudySpec(
            "EXCLUDE_FILL_BAD",
            "Exclude bad fill quality",
            "realistic_fill_quality != FILL_BAD",
            "cost_gate",
            (),
            lambda item: str(item.get("realistic_fill_quality") or "") != "FILL_BAD",
        ),
        FilterStudySpec(
            "FILL_GOOD_ONLY",
            "Fill good only",
            "realistic_fill_quality == FILL_GOOD",
            "cost_gate",
            (),
            lambda item: str(item.get("realistic_fill_quality") or "") == "FILL_GOOD",
        ),
        FilterStudySpec(
            "COST_R_LE_0_20",
            "Cost R <= 0.20",
            "realistic_cost_r_estimate <= 0.20",
            "cost_gate",
            (),
            lambda item: _decimal_or_none(item.get("realistic_cost_r_estimate")) is not None
            and (_decimal_or_none(item.get("realistic_cost_r_estimate")) or Decimal("999")) <= Decimal("0.20"),
        ),
        FilterStudySpec(
            "COST_R_LE_0_35",
            "Cost R <= 0.35",
            "realistic_cost_r_estimate <= 0.35",
            "cost_gate",
            (),
            lambda item: _decimal_or_none(item.get("realistic_cost_r_estimate")) is not None
            and (_decimal_or_none(item.get("realistic_cost_r_estimate")) or Decimal("999")) <= Decimal("0.35"),
        ),
        FilterStudySpec(
            "FUTURES_SPREAD_LE_0_03",
            "Futures spread <= 0.03%",
            "futures_spread_pct <= 0.03",
            "cost_gate",
            ("futures_spread_pct",),
            lambda item: (_evidence_value(item, "futures_spread_pct") or Decimal("999")) <= Decimal("0.03"),
        ),
        FilterStudySpec(
            "VOLUME_LE_1_50",
            "Volume not overextended",
            "volume_ratio_vs_lookback <= 1.50",
            "late_momentum_gate",
            ("volume_ratio_vs_lookback",),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "RANGE_ATR_LE_1_25",
            "Range not overextended",
            "range_ratio_vs_atr <= 1.25",
            "late_momentum_gate",
            ("range_ratio_vs_atr",),
            lambda item: (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "PRICE_ATR_LE_1_25",
            "Price/ATR not stretched",
            "price_atr_multiple <= 1.25",
            "late_momentum_gate",
            ("price_atr_multiple",),
            lambda item: (_evidence_value(item, "price_atr_multiple") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "PRICE_RETURN_ABS_LE_0_50",
            "Price move not too large",
            "abs(price_return) <= 0.50",
            "late_momentum_gate",
            ("price_return",),
            lambda item: abs(_evidence_value(item, "price_return") or Decimal("999")) <= Decimal("0.50"),
        ),
        FilterStudySpec(
            "PRICE_RETURN_LE_0",
            "Short after non-positive return",
            "price_return <= 0",
            "direction_gate",
            ("price_return",),
            lambda item: (_evidence_value(item, "price_return") or Decimal("999")) <= Decimal("0"),
        ),
        FilterStudySpec(
            "FUNDING_GE_65",
            "Funding percentile >= 65",
            "funding_percentile_30d >= 65",
            "positioning_gate",
            ("funding_percentile_30d",),
            lambda item: (_evidence_value(item, "funding_percentile_30d") or Decimal("-999")) >= Decimal("65"),
        ),
        FilterStudySpec(
            "GLOBAL_LS_GE_1_20",
            "Global L/S >= 1.20",
            "global_long_short_ratio >= 1.20",
            "positioning_gate",
            ("global_long_short_ratio",),
            lambda item: (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20"),
        ),
        FilterStudySpec(
            "OI_Z_GE_2",
            "OI z-score >= 2",
            "oi_zscore >= 2",
            "open_interest_gate",
            ("oi_zscore",),
            lambda item: (_evidence_value(item, "oi_zscore") or Decimal("-999")) >= Decimal("2"),
        ),
        FilterStudySpec(
            "FILL_GOOD_AND_VOLUME_LE_1_50",
            "Fill good + volume controlled",
            "realistic_fill_quality == FILL_GOOD AND volume_ratio_vs_lookback <= 1.50",
            "combo_cost_late",
            ("volume_ratio_vs_lookback",),
            lambda item: str(item.get("realistic_fill_quality") or "") == "FILL_GOOD"
            and (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50"),
        ),
        FilterStudySpec(
            "FILL_GOOD_AND_RANGE_ATR_LE_1_25",
            "Fill good + range controlled",
            "realistic_fill_quality == FILL_GOOD AND range_ratio_vs_atr <= 1.25",
            "combo_cost_late",
            ("range_ratio_vs_atr",),
            lambda item: str(item.get("realistic_fill_quality") or "") == "FILL_GOOD"
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "NO_LATE_MOMENTUM",
            "No late momentum",
            "volume_ratio_vs_lookback <= 1.50 AND range_ratio_vs_atr <= 1.25 AND price_atr_multiple <= 1.25",
            "late_momentum_gate",
            ("volume_ratio_vs_lookback", "range_ratio_vs_atr", "price_atr_multiple"),
            lambda item: (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25")
            and (_evidence_value(item, "price_atr_multiple") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "COST_AND_NO_LATE_MOMENTUM",
            "Cost good + no late momentum",
            "realistic_fill_quality == FILL_GOOD AND volume <= 1.50 AND range/ATR <= 1.25 AND price/ATR <= 1.25",
            "combo_cost_late",
            ("volume_ratio_vs_lookback", "range_ratio_vs_atr", "price_atr_multiple"),
            lambda item: str(item.get("realistic_fill_quality") or "") == "FILL_GOOD"
            and (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25")
            and (_evidence_value(item, "price_atr_multiple") or Decimal("999")) <= Decimal("1.25"),
        ),
        FilterStudySpec(
            "POSITIONING_AND_NO_LATE",
            "Positioning support + no late momentum",
            "global_long_short_ratio >= 1.20 AND volume <= 1.50 AND range/ATR <= 1.25",
            "combo_positioning_late",
            ("global_long_short_ratio", "volume_ratio_vs_lookback", "range_ratio_vs_atr"),
            lambda item: (_evidence_value(item, "global_long_short_ratio") or Decimal("-999")) >= Decimal("1.20")
            and (_evidence_value(item, "volume_ratio_vs_lookback") or Decimal("999")) <= Decimal("1.50")
            and (_evidence_value(item, "range_ratio_vs_atr") or Decimal("999")) <= Decimal("1.25"),
        ),
    ]


def _v2_refinement_verdict(row: dict[str, Any], *, min_sample: int) -> str:
    if int(row.get("closed_count") or 0) < min_sample:
        return "REFINEMENT_SAMPLE_TOO_SMALL"
    realistic_total = Decimal(row.get("realistic_total_r_closed") or 0)
    avg_delta = row.get("realistic_avg_r_delta_vs_baseline")
    total_delta = row.get("realistic_total_r_delta_vs_baseline")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    concentration = row.get("top_symbol_share_pct")
    concentration_ok = concentration is None or Decimal(concentration) <= Decimal("35")
    if (
        realistic_total > 0
        and avg_delta is not None
        and Decimal(avg_delta) > 0
        and (sl_delta is None or Decimal(sl_delta) <= 0)
        and concentration_ok
    ):
        return "REFINEMENT_PROMISING"
    if (
        (avg_delta is not None and Decimal(avg_delta) > 0)
        or (total_delta is not None and Decimal(total_delta) > 0)
        or (sl_delta is not None and Decimal(sl_delta) < 0)
    ):
        return "REFINEMENT_REDUCES_DAMAGE"
    if (
        avg_delta is not None
        and Decimal(avg_delta) < 0
        and total_delta is not None
        and Decimal(total_delta) < 0
    ):
        return "REFINEMENT_REJECT"
    return "REFINEMENT_NO_CLEAR_EDGE"


def _v2_refinement_mitigation_read(row: dict[str, Any]) -> str:
    verdict = row.get("verdict")
    family = row.get("family")
    if verdict == "REFINEMENT_PROMISING":
        return f"{family} layak dipantau sebagai filter riset karena realistic R membaik."
    if verdict == "REFINEMENT_REDUCES_DAMAGE":
        return f"{family} mengurangi sebagian kerusakan, tapi belum cukup bersih."
    if verdict == "REFINEMENT_REJECT":
        return f"{family} memperburuk baseline MID_SHORT 1h saat ini."
    if verdict == "REFINEMENT_SAMPLE_TOO_SMALL":
        return "Sample belum cukup untuk dibaca."
    return "Belum ada edge realistis yang jelas."


def _v2_refinement_risk_notes(row: dict[str, Any], *, min_sample: int) -> list[str]:
    notes: list[str] = []
    if int(row.get("closed_count") or 0) < min_sample:
        notes.append(f"Closed sample < {min_sample}.")
    if Decimal(row.get("realistic_total_r_closed") or 0) <= 0:
        notes.append("Realistic R belum positif.")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    if sl_delta is not None and Decimal(sl_delta) > 0:
        notes.append("SL share naik vs baseline.")
    concentration = row.get("top_symbol_share_pct")
    if concentration is not None and Decimal(concentration) > Decimal("35"):
        notes.append("Terlalu terkonsentrasi di satu symbol.")
    missing = row.get("missing_data_pct")
    if missing is not None and Decimal(missing) > Decimal("25"):
        notes.append("Evidence missing tinggi.")
    return notes


def _sort_v2_refinement_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    verdict_rank = {
        "REFINEMENT_PROMISING": 4,
        "REFINEMENT_REDUCES_DAMAGE": 3,
        "REFINEMENT_NO_CLEAR_EDGE": 2,
        "REFINEMENT_SAMPLE_TOO_SMALL": 1,
        "REFINEMENT_REJECT": 0,
    }
    return sorted(
        rows,
        key=lambda row: (
            verdict_rank.get(str(row.get("verdict")), -1),
            Decimal(row.get("realistic_avg_r_delta_vs_baseline") or Decimal("-999")),
            Decimal(row.get("realistic_total_r_closed") or 0),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )


def _v2_mid_short_refinement_readiness(
    baseline: dict[str, Any],
    promising: list[dict[str, Any]],
    *,
    min_sample: int,
) -> str:
    if int(baseline.get("closed_count") or 0) < min_sample:
        return "MID_SHORT_1H_WAIT_MORE_SAMPLE"
    if any(row.get("verdict") == "REFINEMENT_PROMISING" for row in promising):
        return "MID_SHORT_1H_HAS_PROMISING_FILTER"
    if promising:
        return "MID_SHORT_1H_DAMAGE_REDUCTION_ONLY"
    if Decimal(baseline.get("realistic_total_r_closed") or 0) > 0:
        return "MID_SHORT_1H_BASELINE_REALISTIC_POSITIVE"
    return "MID_SHORT_1H_NEEDS_REFINEMENT"


def _v2_mid_short_mitigation_plan(
    baseline: dict[str, Any],
    promising: list[dict[str, Any]],
    *,
    min_sample: int,
) -> list[str]:
    if int(baseline.get("closed_count") or 0) < min_sample:
        return ["Tunggu closed sample MID_SHORT 1h bertambah sebelum promosi filter apa pun."]
    plan = [
        "Prioritaskan MID_SHORT 1h sebagai lane riset utama; jangan promosi 15m saat realistic R masih bocor.",
        "Uji cost gate lebih dulu karena ideal R MID_SHORT 1h positif tetapi realistic R negatif.",
        "Uji late-momentum gate untuk menghindari entry yang sudah terlalu ramai: volume, range/ATR, dan price/ATR terlalu besar.",
    ]
    if promising:
        best = promising[0]
        plan.append(f"Pantau filter teratas: {best.get('label')} ({best.get('verdict')}); belum mengubah rule live.")
    else:
        plan.append("Belum ada filter yang cukup bersih; tetap read-only sampai ada damage reduction yang stabil.")
    return plan


def _rank_value(item: dict[str, Any]) -> int | None:
    value = item.get("universe_rank")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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


def _one_hour_filter_lane(
    *,
    stage: str,
    direction: str,
    items: list[dict[str, Any]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    baseline = _filter_study_row(
        filter_id="BASELINE",
        label=f"Baseline 1h {stage}",
        expression="no additional filter",
        family="BASELINE",
        items=items,
        source_count=len(items),
        missing_data_count=0,
        required_fields=(),
        baseline_perf=None,
        min_sample=min_sample,
    )
    rows: list[dict[str, Any]] = []
    for spec in _filter_study_specs():
        passed, missing = _apply_filter_spec(items, spec)
        row = _filter_study_row(
            filter_id=spec.filter_id,
            label=spec.label,
            expression=spec.expression,
            family=spec.family,
            items=passed,
            source_count=len(items),
            missing_data_count=missing,
            required_fields=spec.required_fields,
            baseline_perf=baseline,
            min_sample=min_sample,
        )
        rows.append(_with_one_hour_filter_action(row, stage=stage, direction=direction, min_sample=min_sample))
    rows = _sort_one_hour_filter_candidates(rows)
    actionable = [row for row in rows if row["action"] in {"PROMOTE_TO_SHADOW", "MONITOR_MORE"}]
    return {
        "lane": f"{stage}_1h",
        "stage": stage,
        "direction": direction,
        "timeframe": "1h",
        "source_count": len(items),
        "baseline": baseline,
        "filter_candidates": rows[:limit],
        "actionable_candidates": actionable[:limit],
        "lane_status": _one_hour_lane_status(baseline, actionable, min_sample=min_sample),
        "lane_note": _one_hour_lane_note(baseline, actionable, min_sample=min_sample),
    }


def _with_one_hour_filter_action(
    row: dict[str, Any],
    *,
    stage: str,
    direction: str,
    min_sample: int,
) -> dict[str, Any]:
    enriched = {**row, "stage": stage, "direction": direction, "timeframe": "1h"}
    action = _one_hour_filter_action(enriched, min_sample=min_sample)
    enriched["action"] = action
    enriched["action_reason"] = _one_hour_filter_action_reason(enriched, action=action, min_sample=min_sample)
    enriched["risk_notes"] = _one_hour_filter_risk_notes(enriched)
    return enriched


def _one_hour_filter_action(row: dict[str, Any], *, min_sample: int) -> str:
    if int(row.get("sample_count") or 0) < min_sample or int(row.get("closed_count") or 0) < min_sample:
        return "MONITOR_MORE_SAMPLE"
    avg_delta = row.get("avg_r_delta_vs_baseline")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    top_share = row.get("top_symbol_share_pct")
    total_r = Decimal(row.get("total_r_closed") or 0)
    concentration_ok = top_share is None or Decimal(top_share) <= Decimal("35")
    if (
        row.get("verdict") == "PROMISING_FILTER"
        and avg_delta is not None
        and Decimal(avg_delta) >= Decimal("0.05")
        and (sl_delta is None or Decimal(sl_delta) <= 0)
        and total_r > 0
        and concentration_ok
    ):
        return "PROMOTE_TO_SHADOW"
    if (
        row.get("verdict") == "REDUCES_DAMAGE"
        or (avg_delta is not None and Decimal(avg_delta) > 0)
        or (sl_delta is not None and Decimal(sl_delta) < 0)
    ):
        return "MONITOR_MORE"
    if row.get("verdict") == "WORSE_THAN_BASELINE":
        return "REJECT_FILTER"
    return "NO_CLEAR_USE"


def _one_hour_filter_action_reason(row: dict[str, Any], *, action: str, min_sample: int) -> str:
    if action == "PROMOTE_TO_SHADOW":
        return "Filter membaik vs baseline 1h, total R positif, SL share tidak memburuk, dan concentration masih wajar. Shadow monitoring saja."
    if action == "MONITOR_MORE":
        return "Ada perbaikan sebagian, tapi belum cukup bersih untuk shadow utama."
    if action == "MONITOR_MORE_SAMPLE":
        return f"Closed sample belum memenuhi minimum {min_sample}."
    if action == "REJECT_FILTER":
        return "Filter lebih buruk dari baseline lane 1h saat ini."
    return "Belum ada separation yang cukup jelas dari baseline lane 1h."


def _one_hour_filter_risk_notes(row: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    top_share = row.get("top_symbol_share_pct")
    if top_share is not None and Decimal(top_share) > Decimal("35"):
        notes.append("Symbol concentration tinggi; hasil bisa ditarik satu token.")
    missing_pct = row.get("missing_data_pct")
    if missing_pct is not None and Decimal(missing_pct) > Decimal("25"):
        notes.append("Data evidence banyak missing; filter belum representatif.")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    if sl_delta is not None and Decimal(sl_delta) > 0:
        notes.append("SL share lebih buruk dari baseline.")
    if Decimal(row.get("total_r_closed") or 0) <= 0:
        notes.append("Total R filter belum positif.")
    return notes


def _sort_one_hour_filter_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=_one_hour_filter_candidate_sort_key, reverse=True)


def _one_hour_filter_candidate_sort_key(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, int]:
    action_rank = {
        "PROMOTE_TO_SHADOW": 4,
        "MONITOR_MORE": 3,
        "NO_CLEAR_USE": 2,
        "MONITOR_MORE_SAMPLE": 1,
        "REJECT_FILTER": 0,
    }
    avg_delta = row.get("avg_r_delta_vs_baseline")
    total_r = row.get("total_r_closed")
    return (
        action_rank.get(str(row.get("action")), -1),
        Decimal(avg_delta) if avg_delta is not None else Decimal("-999"),
        Decimal(total_r) if total_r is not None else Decimal("-999"),
        int(row.get("closed_count") or 0),
    )


def _one_hour_lane_status(baseline: dict[str, Any], actionable: list[dict[str, Any]], *, min_sample: int) -> str:
    if int(baseline.get("closed_count") or 0) < min_sample:
        return "LANE_NEEDS_MORE_SAMPLE"
    if any(row.get("action") == "PROMOTE_TO_SHADOW" for row in actionable):
        return "HAS_SHADOW_CANDIDATE"
    if actionable:
        return "HAS_MONITOR_CANDIDATE"
    if Decimal(baseline.get("total_r_closed") or 0) > 0:
        return "BASELINE_POSITIVE_NO_FILTER"
    return "LANE_WEAK"


def _one_hour_lane_note(baseline: dict[str, Any], actionable: list[dict[str, Any]], *, min_sample: int) -> str:
    if int(baseline.get("closed_count") or 0) < min_sample:
        return f"Lane 1h belum punya closed sample minimum {min_sample}."
    if any(row.get("action") == "PROMOTE_TO_SHADOW" for row in actionable):
        return "Ada filter yang layak dipantau sebagai shadow research, belum mengubah rule live."
    if actionable:
        return "Ada filter yang perlu dipantau, tetapi separation belum cukup bersih."
    if Decimal(baseline.get("total_r_closed") or 0) > 0:
        return "Baseline lane positif, tetapi filter tambahan belum lebih baik."
    return "Lane 1h masih lemah; jangan promosi rule."


def _one_hour_walk_forward_lane(
    *,
    stage: str,
    direction: str,
    items: list[dict[str, Any]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    sorted_items = sorted(
        items,
        key=lambda item: (_parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol") or "")),
    )
    if len(sorted_items) >= 2:
        split_index = max(1, min(len(sorted_items) - 1, int(Decimal(len(sorted_items)) * Decimal("0.70"))))
    else:
        split_index = len(sorted_items)
    train_items = sorted_items[:split_index]
    validation_items = sorted_items[split_index:]
    baseline_all = _walk_forward_perf(sorted_items)
    baseline_train = _walk_forward_perf(train_items)
    baseline_validation = _walk_forward_perf(validation_items)
    candidates = [
        _one_hour_walk_forward_candidate(
            spec=spec,
            all_items=sorted_items,
            train_items=train_items,
            validation_items=validation_items,
            baseline_all=baseline_all,
            baseline_train=baseline_train,
            baseline_validation=baseline_validation,
            stage=stage,
            direction=direction,
            min_sample=min_sample,
        )
        for spec in _filter_study_specs()
    ]
    candidates.sort(key=_one_hour_walk_forward_sort_key, reverse=True)
    actionable = [row for row in candidates if row["verdict"] in {"WF_PROMISING", "WF_REDUCES_DAMAGE"}]
    return {
        "lane": f"{stage}_1h",
        "stage": stage,
        "direction": direction,
        "timeframe": "1h",
        "sample_count": len(sorted_items),
        "train_count": len(train_items),
        "validation_count": len(validation_items),
        "split_method": "chronological_70_30",
        "baseline_all": baseline_all,
        "baseline_train": baseline_train,
        "baseline_validation": baseline_validation,
        "lane_status": _one_hour_walk_forward_lane_status(baseline_train, baseline_validation, actionable, min_sample=min_sample),
        "lane_note": _one_hour_walk_forward_lane_note(baseline_train, baseline_validation, actionable, min_sample=min_sample),
        "filter_candidates": candidates[:limit],
        "actionable_candidates": actionable[:limit],
    }


def _one_hour_walk_forward_candidate(
    *,
    spec: FilterStudySpec,
    all_items: list[dict[str, Any]],
    train_items: list[dict[str, Any]],
    validation_items: list[dict[str, Any]],
    baseline_all: dict[str, Any],
    baseline_train: dict[str, Any],
    baseline_validation: dict[str, Any],
    stage: str,
    direction: str,
    min_sample: int,
) -> dict[str, Any]:
    all_selected, all_missing = _apply_filter_spec(all_items, spec)
    train_selected, train_missing = _apply_filter_spec(train_items, spec)
    validation_selected, validation_missing = _apply_filter_spec(validation_items, spec)
    all_perf = _walk_forward_perf(all_selected, baseline=baseline_all)
    train = _walk_forward_perf(train_selected, baseline=baseline_train)
    validation = _walk_forward_perf(validation_selected, baseline=baseline_validation)
    verdict = _one_hour_walk_forward_verdict(train, validation, min_sample=min_sample)
    return {
        "stage": stage,
        "direction": direction,
        "timeframe": "1h",
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
        "score": _one_hour_walk_forward_score(train, validation, verdict=verdict, min_sample=min_sample),
        "note": _one_hour_walk_forward_note(verdict),
        "risk_notes": _one_hour_walk_forward_risk_notes(validation),
    }


def _walk_forward_perf(items: list[dict[str, Any]], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    perf = _performance_summary(items)
    realistic_values = [
        Decimal(item["realistic_realized_r"])
        for item in items
        if item.get("result_status") in COMPLETED_OUTCOMES and item.get("realistic_realized_r") is not None
    ]
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    top_symbol, top_symbol_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    drawdown = _realistic_drawdown_summary(items)
    row = {
        **perf,
        "sample_count": len(items),
        "median_realistic_r_closed": _median_decimal(realistic_values),
        "max_realistic_drawdown_r": drawdown["max_drawdown_r"],
        "sl_share_pct": _sl_share(perf),
        "top_symbol": top_symbol,
        "top_symbol_count": top_symbol_count,
        "top_symbol_share_pct": (Decimal(top_symbol_count) / Decimal(len(items)) * Decimal("100")) if items else None,
    }
    if baseline is not None:
        row.update(
            {
                "sample_delta_vs_baseline": int(row["sample_count"]) - int(baseline.get("sample_count") or 0),
                "realistic_avg_r_delta_vs_baseline": _decimal_delta(row.get("realistic_avg_r_closed"), baseline.get("realistic_avg_r_closed")),
                "realistic_total_r_delta_vs_baseline": _decimal_delta(row.get("realistic_total_r_closed"), baseline.get("realistic_total_r_closed")),
                "winrate_delta_vs_baseline": _decimal_delta(row.get("winrate_pct"), baseline.get("winrate_pct")),
                "sl_share_delta_vs_baseline": _decimal_delta(row.get("sl_share_pct"), baseline.get("sl_share_pct")),
                "max_drawdown_delta_vs_baseline": _decimal_delta(row.get("max_realistic_drawdown_r"), baseline.get("max_realistic_drawdown_r")),
            }
        )
    return row


def _realistic_drawdown_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [
        item
        for item in items
        if item.get("result_status") in COMPLETED_OUTCOMES and item.get("realistic_realized_r") is not None
    ]
    closed.sort(key=lambda item: (_parse_dt(item.get("result_time_utc")) or _parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol"))))
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for item in closed:
        cumulative += Decimal(item["realistic_realized_r"])
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return {
        "closed_count": len(closed),
        "total_r_closed": cumulative,
        "peak_r": peak,
        "max_drawdown_r": max_drawdown,
        "current_drawdown_r": cumulative - peak,
    }


def _one_hour_walk_forward_verdict(train: dict[str, Any], validation: dict[str, Any], *, min_sample: int) -> str:
    if int(train.get("closed_count") or 0) < min_sample or int(validation.get("closed_count") or 0) < min_sample:
        return "WF_NEED_MORE_SAMPLE"
    train_good = _walk_forward_perf_good(train)
    validation_good = _walk_forward_perf_good(validation)
    validation_reduces_damage = _walk_forward_reduces_damage(validation)
    validation_delta = validation.get("realistic_avg_r_delta_vs_baseline")
    if train_good and validation_good:
        return "WF_PROMISING"
    if train_good and not validation_good:
        return "WF_OVERFIT"
    if validation_reduces_damage:
        return "WF_REDUCES_DAMAGE"
    if validation_delta is not None and Decimal(validation_delta) < 0:
        return "WF_REJECT"
    return "WF_NOISY"


def _walk_forward_perf_good(row: dict[str, Any]) -> bool:
    avg_delta = row.get("realistic_avg_r_delta_vs_baseline")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    top_share = row.get("top_symbol_share_pct")
    concentration_ok = int(row.get("sample_count") or 0) < 10 or top_share is None or Decimal(top_share) <= Decimal("35")
    return (
        avg_delta is not None
        and Decimal(avg_delta) >= Decimal("0.05")
        and Decimal(row.get("realistic_total_r_closed") or 0) > 0
        and (sl_delta is None or Decimal(sl_delta) <= 0)
        and concentration_ok
    )


def _walk_forward_reduces_damage(row: dict[str, Any]) -> bool:
    avg_delta = row.get("realistic_avg_r_delta_vs_baseline")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    return (
        (avg_delta is not None and Decimal(avg_delta) > 0)
        or (sl_delta is not None and Decimal(sl_delta) < 0)
    )


def _one_hour_walk_forward_score(train: dict[str, Any], validation: dict[str, Any], *, verdict: str, min_sample: int) -> int:
    score = 0
    if int(train.get("closed_count") or 0) >= min_sample and int(validation.get("closed_count") or 0) >= min_sample:
        score += 2
    validation_delta = validation.get("realistic_avg_r_delta_vs_baseline")
    if validation_delta is not None and Decimal(validation_delta) >= Decimal("0.05"):
        score += 2
    if Decimal(validation.get("realistic_total_r_closed") or 0) > 0:
        score += 1
    sl_delta = validation.get("sl_share_delta_vs_baseline")
    if sl_delta is None or Decimal(sl_delta) <= 0:
        score += 1
    top_share = validation.get("top_symbol_share_pct")
    if int(validation.get("sample_count") or 0) < 10 or top_share is None or Decimal(top_share) <= Decimal("35"):
        score += 1
    if verdict == "WF_OVERFIT":
        score = min(score, 3)
    return score


def _one_hour_walk_forward_note(verdict: str) -> str:
    if verdict == "WF_PROMISING":
        return "Filter membaik di train dan validation memakai realistic R. Kandidat shadow research, belum rule live."
    if verdict == "WF_OVERFIT":
        return "Filter bagus di train tapi gagal di validation. Jangan dipromosikan."
    if verdict == "WF_REDUCES_DAMAGE":
        return "Ada tanda mengurangi kerusakan di validation, tapi belum cukup bersih."
    if verdict == "WF_REJECT":
        return "Validation lebih buruk dari baseline 1h."
    if verdict == "WF_NEED_MORE_SAMPLE":
        return "Train/validation belum punya closed sample cukup."
    return "Belum ada separation yang bersih."


def _one_hour_walk_forward_risk_notes(row: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    top_share = row.get("top_symbol_share_pct")
    if top_share is not None and Decimal(top_share) > Decimal("35"):
        notes.append("Validation terlalu terkonsentrasi di satu symbol.")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    if sl_delta is not None and Decimal(sl_delta) > 0:
        notes.append("SL share validation lebih buruk dari baseline.")
    if Decimal(row.get("realistic_total_r_closed") or 0) <= 0:
        notes.append("Validation realistic R belum positif.")
    return notes


def _one_hour_walk_forward_lane_status(
    baseline_train: dict[str, Any],
    baseline_validation: dict[str, Any],
    actionable: list[dict[str, Any]],
    *,
    min_sample: int,
) -> str:
    if int(baseline_train.get("closed_count") or 0) < min_sample or int(baseline_validation.get("closed_count") or 0) < min_sample:
        return "WF_LANE_NEEDS_MORE_SAMPLE"
    if any(row.get("verdict") == "WF_PROMISING" for row in actionable):
        return "WF_HAS_PROMISING_FILTER"
    if actionable:
        return "WF_HAS_DAMAGE_REDUCTION"
    if Decimal(baseline_validation.get("realistic_total_r_closed") or 0) > 0:
        return "WF_BASELINE_POSITIVE_NO_FILTER"
    return "WF_LANE_WEAK"


def _one_hour_walk_forward_lane_note(
    baseline_train: dict[str, Any],
    baseline_validation: dict[str, Any],
    actionable: list[dict[str, Any]],
    *,
    min_sample: int,
) -> str:
    if int(baseline_train.get("closed_count") or 0) < min_sample or int(baseline_validation.get("closed_count") or 0) < min_sample:
        return f"Closed sample train/validation belum memenuhi minimum {min_sample}."
    if any(row.get("verdict") == "WF_PROMISING" for row in actionable):
        return "Ada filter yang bertahan di validation. Layak masuk shadow monitoring."
    if actionable:
        return "Ada filter yang mengurangi kerusakan, tapi belum cukup kuat."
    if Decimal(baseline_validation.get("realistic_total_r_closed") or 0) > 0:
        return "Baseline validation positif, tetapi filter tambahan belum lebih baik."
    return "Validation lane masih lemah."


def _one_hour_walk_forward_sort_key(row: dict[str, Any]) -> tuple[int, int, Decimal, Decimal, int]:
    verdict_rank = {
        "WF_PROMISING": 5,
        "WF_REDUCES_DAMAGE": 4,
        "WF_NOISY": 3,
        "WF_OVERFIT": 2,
        "WF_REJECT": 1,
        "WF_NEED_MORE_SAMPLE": 0,
    }
    validation = row.get("validation") or {}
    avg_delta = validation.get("realistic_avg_r_delta_vs_baseline")
    total_r = validation.get("realistic_total_r_closed")
    return (
        verdict_rank.get(str(row.get("verdict")), -1),
        int(row.get("score") or 0),
        Decimal(avg_delta) if avg_delta is not None else Decimal("-999"),
        Decimal(total_r) if total_r is not None else Decimal("-999"),
        int(validation.get("closed_count") or 0),
    )


def _one_hour_v4_selected_filters(candidates: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in candidates:
        if row.get("verdict") not in {"WF_PROMISING", "WF_REDUCES_DAMAGE"}:
            continue
        selected.append(
            {
                "stage": row.get("stage"),
                "direction": row.get("direction"),
                "timeframe": "1h",
                "filter_id": row.get("filter_id"),
                "label": row.get("label"),
                "expression": row.get("expression"),
                "family": row.get("family"),
                "required_fields": row.get("required_fields") or [],
                "walk_forward_verdict": row.get("verdict"),
                "walk_forward_score": row.get("score"),
                "validation": row.get("validation") or {},
                "risk_notes": row.get("risk_notes") or [],
            }
        )
    return selected[: max(1, limit)]


def _one_hour_v4_apply_shadow(
    items: list[dict[str, Any]],
    selected_filters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    specs_by_id = {spec.filter_id: spec for spec in _filter_study_specs()}
    filters_by_lane: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in selected_filters:
        filters_by_lane[(str(row.get("stage") or ""), str(row.get("timeframe") or ""))].append(row)
    return [_one_hour_v4_shadow_result(item, filters_by_lane, specs_by_id) for item in items]


def _one_hour_v4_shadow_result(
    item: dict[str, Any],
    filters_by_lane: dict[tuple[str, str], list[dict[str, Any]]],
    specs_by_id: dict[str, FilterStudySpec],
) -> dict[str, Any]:
    row = dict(item)
    lane_filters = filters_by_lane.get((str(item.get("stage") or ""), str(item.get("timeframe") or "")), [])
    base = {
        "v4_shadow_status": "V4_SHADOW_NO_FILTER",
        "v4_filter_id": None,
        "v4_filter_label": None,
        "v4_filter_expression": None,
        "v4_walk_forward_verdict": None,
        "v4_walk_forward_score": None,
        "v4_shadow_reason": "No 1h walk-forward filter is selected for this lane yet.",
    }
    if not lane_filters:
        row.update(base)
        return row

    missing_fields: set[str] = set()
    checked_filter_count = 0
    evidence = item.get("evidence_snapshot") or {}
    for selected in lane_filters:
        spec = specs_by_id.get(str(selected.get("filter_id") or ""))
        if spec is None:
            continue
        missing = [field for field in spec.required_fields if evidence.get(field) is None]
        if missing:
            missing_fields.update(missing)
            continue
        checked_filter_count += 1
        if spec.predicate(item):
            row.update(
                {
                    "v4_shadow_status": "V4_SHADOW_PASS",
                    "v4_filter_id": selected.get("filter_id"),
                    "v4_filter_label": selected.get("label"),
                    "v4_filter_expression": selected.get("expression"),
                    "v4_walk_forward_verdict": selected.get("walk_forward_verdict"),
                    "v4_walk_forward_score": selected.get("walk_forward_score"),
                    "v4_shadow_reason": f"Matched V4 walk-forward filter: {selected.get('label')}.",
                }
            )
            return row

    if checked_filter_count == 0 and missing_fields:
        base.update(
            {
                "v4_shadow_status": "V4_SHADOW_UNAVAILABLE",
                "v4_shadow_reason": "Required V4 filter evidence missing: " + ", ".join(sorted(missing_fields)),
            }
        )
    else:
        base.update(
            {
                "v4_shadow_status": "V4_SHADOW_FAIL",
                "v4_shadow_reason": "Selected V4 walk-forward filters exist for this lane, but this signal evidence did not match them.",
            }
        )
    row.update(base)
    return row


def _one_hour_v4_stage_rows(
    items: list[dict[str, Any]],
    *,
    selected_filters: list[dict[str, Any]],
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stage in ("MID_LONG", "MID_SHORT"):
        lane_items = [item for item in items if item.get("stage") == stage and item.get("timeframe") == "1h"]
        lane_selected_count = sum(1 for row in selected_filters if row.get("stage") == stage and row.get("timeframe") == "1h")
        baseline = _walk_forward_perf(lane_items)
        pass_items = [item for item in lane_items if item.get("v4_shadow_status") == "V4_SHADOW_PASS"]
        fail_items = [item for item in lane_items if item.get("v4_shadow_status") == "V4_SHADOW_FAIL"]
        v4_pass = _walk_forward_perf(pass_items, baseline=baseline)
        row = {
            "stage": stage,
            "timeframe": "1h",
            "v2_baseline": baseline,
            "v4_shadow_pass": v4_pass,
            "v4_shadow_fail": _walk_forward_perf(fail_items, baseline=baseline),
            "v4_shadow_pass_count": len(pass_items),
            "v4_shadow_fail_count": len(fail_items),
            "v4_shadow_unavailable_count": sum(1 for item in lane_items if item.get("v4_shadow_status") == "V4_SHADOW_UNAVAILABLE"),
            "v4_shadow_no_filter_count": sum(1 for item in lane_items if item.get("v4_shadow_status") == "V4_SHADOW_NO_FILTER"),
            "sample_retention_pct": _retention(len(pass_items), len(lane_items)),
        }
        row["read"] = _one_hour_v4_read(
            baseline=baseline,
            v4_pass=v4_pass,
            selected_filter_count=lane_selected_count,
            min_sample=min_sample,
        )
        rows.append(row)
    return rows


def _one_hour_v4_read(
    *,
    baseline: dict[str, Any],
    v4_pass: dict[str, Any],
    selected_filter_count: int,
    min_sample: int,
) -> str:
    if selected_filter_count <= 0:
        return "V4_NO_FILTER_SELECTED"
    if int(v4_pass.get("closed_count") or 0) < min_sample:
        return "V4_MONITOR_MORE_SAMPLE"
    avg_delta = v4_pass.get("realistic_avg_r_delta_vs_baseline")
    sl_delta = v4_pass.get("sl_share_delta_vs_baseline")
    total_r = Decimal(v4_pass.get("realistic_total_r_closed") or 0)
    if avg_delta is not None and Decimal(avg_delta) >= Decimal("0.05") and total_r > 0 and (sl_delta is None or Decimal(sl_delta) <= 0):
        return "V4_SHADOW_BETTER_THAN_V2_BASELINE"
    if (avg_delta is not None and Decimal(avg_delta) > 0) or (sl_delta is not None and Decimal(sl_delta) < 0):
        return "V4_SHADOW_MONITOR_MORE"
    if avg_delta is not None and Decimal(avg_delta) < 0:
        return "V4_SHADOW_WEAKER_THAN_V2_BASELINE"
    if Decimal(baseline.get("realistic_total_r_closed") or 0) > 0:
        return "V4_BASELINE_POSITIVE_NO_CLEAR_FILTER"
    return "V4_SHADOW_INCONCLUSIVE"


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
    row = {
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
    row.update(_calibration_promotion_readiness(row, min_sample=min_sample))
    return row


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


def _calibration_promotion_readiness(row: dict[str, Any], *, min_sample: int) -> dict[str, Any]:
    verdict = str(row.get("verdict") or "")
    train = row.get("train") or {}
    validation = row.get("validation") or {}
    reasons: list[str] = []
    score = 0

    train_closed = int(train.get("closed_count") or 0)
    validation_closed = int(validation.get("closed_count") or 0)
    if train_closed >= min_sample and validation_closed >= min_sample:
        score += 2
        reasons.append("Train dan validation punya closed sample minimum.")
    else:
        reasons.append("Closed sample train/validation belum cukup.")

    avg_delta = validation.get("avg_r_delta_vs_baseline")
    if avg_delta is not None and Decimal(avg_delta) >= Decimal("0.05"):
        score += 2
        reasons.append("Validation average R membaik minimal +0.05R vs baseline lane.")
    else:
        reasons.append("Validation average R belum cukup membaik.")

    total_r = validation.get("total_r_closed")
    if total_r is not None and Decimal(total_r) > 0:
        score += 1
        reasons.append("Validation total R positif.")
    else:
        reasons.append("Validation total R belum positif.")

    sl_delta = validation.get("sl_share_delta_vs_baseline")
    if sl_delta is None or Decimal(sl_delta) <= 0:
        score += 1
        reasons.append("SL share validation tidak lebih buruk dari baseline.")
    else:
        reasons.append("SL share validation memburuk vs baseline.")

    sample_count = int(validation.get("sample_count") or 0)
    top_share = validation.get("top_symbol_share_pct")
    if sample_count < 10 or top_share is None or Decimal(top_share) <= Decimal("35"):
        score += 1
        reasons.append("Symbol concentration masih masuk batas riset.")
    else:
        reasons.append("Validation terlalu terkonsentrasi di satu symbol.")

    if verdict == "TRAIN_ONLY_OVERFIT":
        status = "REJECT_OVERFIT"
    elif train_closed < min_sample or validation_closed < min_sample:
        status = "MONITOR_MORE"
    elif verdict == "VALIDATION_PROMISING" and score >= 6:
        status = "V3_CANDIDATE"
    elif score >= 4 and verdict in {"VALIDATION_PROMISING", "REDUCES_DAMAGE", "NO_CLEAR_EDGE"}:
        status = "MONITOR_MORE"
    else:
        status = "WEAK_FILTER"

    return {
        "promotion_status": status,
        "promotion_score": score,
        "promotion_reasons": reasons,
    }


def _calibration_candidate_sort_key(row: dict[str, Any]) -> tuple[int, int, Decimal, Decimal, int]:
    promotion_rank = {
        "V3_CANDIDATE": 4,
        "MONITOR_MORE": 3,
        "WEAK_FILTER": 2,
        "REJECT_OVERFIT": 1,
    }
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
        promotion_rank.get(str(row.get("promotion_status")), 0),
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
