from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from time import monotonic
from typing import Any, Callable

from sqlalchemy import asc, func, or_, select
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
