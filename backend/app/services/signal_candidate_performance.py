from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from time import monotonic
from typing import Any, Callable

from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.market import (
    FuturesKline1h,
    FuturesKline1m,
    FuturesKline15m,
    FuturesKline4h,
    MarketlabActiveUniverse,
    RichFutures5mAlignment,
    SignalForwardReturnLog,
)
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.structure_zone_shadow import StructureZoneShadowService, structure_zone_chart_zones
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
    taker_buy_base_volume: Decimal | None = None
    taker_sell_base_volume: Decimal | None = None
    source_interval: str = "15m"


@dataclass(frozen=True)
class FilterStudySpec:
    filter_id: str
    label: str
    expression: str
    family: str
    required_fields: tuple[str, ...]
    predicate: Callable[[dict[str, Any]], bool]


@dataclass(frozen=True)
class StructureZoneConfig:
    config_id: str
    label: str
    lookback_hours: int
    pivot_span: int
    zone_half_width_atr: Decimal
    min_touches: int = 2


LAB56_ZONE_CONFIGS = (
    StructureZoneConfig(
        config_id="TIGHT_96H_020ATR",
        label="Tight 96h / 0.20 ATR",
        lookback_hours=96,
        pivot_span=2,
        zone_half_width_atr=Decimal("0.20"),
    ),
    StructureZoneConfig(
        config_id="BALANCED_168H_030ATR",
        label="Balanced 168h / 0.30 ATR",
        lookback_hours=168,
        pivot_span=2,
        zone_half_width_atr=Decimal("0.30"),
    ),
    StructureZoneConfig(
        config_id="BROAD_240H_040ATR",
        label="Broad 240h / 0.40 ATR",
        lookback_hours=240,
        pivot_span=2,
        zone_half_width_atr=Decimal("0.40"),
    ),
)
LAB56_PRIMARY_CONFIG_ID = "BALANCED_168H_030ATR"


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
        v3_filter_map: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
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
                v3_filter_map
                if v3_filter_map is not None
                else self.v3_shadow_filter_map(
                    epoch=epoch,
                    include_watch_only=include_watch_only,
                    position_lock=True,
                    min_sample=5,
                    limit=100,
                ),
            )
        )
        persisted_zone_snapshot = _structure_zone_snapshot(signal)
        zone_snapshot = persisted_zone_snapshot
        zone_snapshot_source = "PERSISTED"
        if zone_snapshot is None:
            zone_snapshot = StructureZoneShadowService(self.db).snapshots_for_signals(
                [
                    {
                        "signal_id": signal.signal_id,
                        "symbol": signal.symbol,
                        "timeframe": signal.timeframe,
                        "signal_timestamp": signal.signal_timestamp,
                        "direction": signal.direction,
                        "price_at_signal": signal.price_at_signal,
                    }
                ]
            ).get(signal.signal_id)
            zone_snapshot_source = "ON_DEMAND_CAUSAL" if zone_snapshot else "UNAVAILABLE"
        if zone_snapshot:
            item.update(_structure_zone_result_fields(zone_snapshot))
        item["structure_zone_snapshot_source"] = zone_snapshot_source
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
        chart_payload = _signal_chart_payload(signal, item, chart_candles)
        if chart_payload and zone_snapshot and chart_candles:
            chart_payload["structure_zones"] = structure_zone_chart_zones(
                zone_snapshot,
                chart_start=chart_candles[0].open_time,
                chart_end=chart_candles[-1].close_time,
                min_price=min(candle.low for candle in chart_candles),
                max_price=max(candle.high for candle in chart_candles),
            )
        response_evidence = dict(signal.evidence or {})
        if zone_snapshot and persisted_zone_snapshot is None:
            response_evidence["structure_zone_shadow"] = zone_snapshot
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
            "chart": chart_payload,
            "evidence": response_evidence,
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

    def structure_zone_shadow_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
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
        baseline = _performance_summary(evaluated)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        lane_grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in evaluated:
            status = str(item.get("structure_zone_status") or "ZONE_UNAVAILABLE")
            grouped[status].append(item)
            lane_grouped[(str(item.get("stage")), str(item.get("timeframe")), status)].append(item)

        def study_row(label: str, items: list[dict[str, Any]]) -> dict[str, Any]:
            performance = _performance_summary(items)
            directional_closed = int(performance.get("tp_count") or 0) + int(performance.get("sl_count") or 0)
            sl_share = (
                Decimal(int(performance.get("sl_count") or 0)) / Decimal(directional_closed) * Decimal("100")
                if directional_closed
                else None
            )
            return {
                "bucket": label,
                "sample_count": len(items),
                "sample_share_pct": Decimal(len(items)) / Decimal(len(evaluated)) * Decimal("100") if evaluated else None,
                "sl_share_pct": sl_share,
                "realistic_avg_r_delta_vs_all": _decimal_delta(
                    performance.get("realistic_avg_r_closed"),
                    baseline.get("realistic_avg_r_closed"),
                ),
                "sample_status": "COMPARABLE" if len(items) >= min_sample else "NEEDS_MORE_SAMPLE",
                **performance,
            }

        bucket_rows = [study_row(status, items) for status, items in grouped.items()]
        bucket_rows.sort(key=lambda row: int(row.get("sample_count") or 0), reverse=True)
        lane_rows = [
            {
                "stage": stage,
                "timeframe": timeframe,
                **study_row(status, items),
            }
            for (stage, timeframe, status), items in lane_grouped.items()
        ]
        lane_rows.sort(key=lambda row: int(row.get("sample_count") or 0), reverse=True)
        latest_items = sorted(
            evaluated,
            key=lambda item: item.get("signal_timestamp") or datetime.min,
            reverse=True,
        )[:limit]
        persisted_count = sum(1 for item in evaluated if item.get("structure_zone_shadow"))
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
            "study_scope": "all_signal_causal_structure_zone_shadow",
            "latest_evaluation_candle_time": latest_candle_time,
            "snapshot_coverage": {
                "evaluated_count": len(evaluated),
                "persisted_snapshot_count": persisted_count,
                "missing_snapshot_count": len(evaluated) - persisted_count,
                "coverage_pct": Decimal(persisted_count) / Decimal(len(evaluated)) * Decimal("100") if evaluated else None,
            },
            "baseline": baseline,
            "by_zone_status": bucket_rows,
            "by_stage_timeframe_zone": lane_rows,
            "latest_signals": latest_items,
            "skipped_by_position_lock": dict(skipped),
            "guardrails": [
                "Zone labels are frozen from candles closed at or before signal time.",
                "Zone labels do not change Signal Factory decisions, entry, SL, TP, or outcomes.",
                "ZONE_UNAVAILABLE remains unavailable and is never promoted to aligned.",
                "Bucket comparison is observational and not a production gate.",
            ],
        }

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
        base_filter: str = "ALL",
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status, _candles = self._mid_short_1h_anatomy_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            shadow_status=shadow_status,
            include_target_distance_context=True,
        )
        source_before_base_filter_count = len(annotated)
        normalized_base_filter = (base_filter or "ALL").upper()
        if normalized_base_filter == "TAKER_SELL_GE_52":
            annotated = _apply_named_second_filter(annotated, "TAKER_SELL_GE_52")
        elif normalized_base_filter != "ALL":
            normalized_base_filter = "ALL"
        target_distance_study = _mid_short_target_distance_study(annotated, min_sample=min_sample)
        structure_clearance_study = _mid_short_structure_clearance_shadow_study(
            annotated,
            min_sample=min_sample,
        )
        support_target_study = _mid_short_support_target_shadow_study(
            annotated,
            min_sample=min_sample,
        )
        for item in annotated:
            _strip_lab52_internal_item_fields(item)
        baseline = _walk_forward_perf(annotated)
        closed = [item for item in annotated if item.get("result_status") in COMPLETED_OUTCOMES]
        tp_items = [item for item in closed if item.get("result_status") == "TP_HIT"]
        sl_items = [item for item in closed if item.get("result_status") == "SL_HIT"]
        both_items = [item for item in closed if item.get("result_status") == "BOTH_HIT_SAME_CANDLE"]
        sl_failure_cause_rows = _mid_short_sl_failure_cause_rows(sl_items)
        sl_failure_cause_summary = _mid_short_sl_failure_cause_summary(
            sl_items,
            rows=sl_failure_cause_rows,
        )
        legacy_path_read = _mid_short_failure_summary_read(annotated, min_sample=min_sample)
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
                "base_filter": normalized_base_filter,
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
            "base_filter": {
                "filter_id": normalized_base_filter,
                "label": "Taker sell >= 52%" if normalized_base_filter == "TAKER_SELL_GE_52" else "All shadow status rows",
                "expression": "kline_taker_sell_ratio >= 0.52" if normalized_base_filter == "TAKER_SELL_GE_52" else "no additional base filter",
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            "summary": {
                "source_before_base_filter_count": source_before_base_filter_count,
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
                "classified_sl_count": sl_failure_cause_summary["classified_sl_count"],
                "unresolved_sl_count": sl_failure_cause_summary["unresolved_sl_count"],
                "dominant_failure_cause": sl_failure_cause_summary["dominant_failure_cause"],
                "dominant_failure_count": sl_failure_cause_summary["dominant_failure_count"],
                "dominant_failure_share_pct": sl_failure_cause_summary["dominant_failure_share_pct"],
                "legacy_path_read": legacy_path_read,
                "read": _mid_short_failure_cause_read(sl_failure_cause_summary, min_sample=min_sample),
            },
            "baseline": baseline,
            "sl_failure_cause_summary": sl_failure_cause_summary,
            "sl_failure_cause_rows": sl_failure_cause_rows,
            "structure_clearance_study": structure_clearance_study,
            "support_target_study": support_target_study,
            "target_distance_study": target_distance_study,
            "mfe_mae_summary": _mid_short_mfe_mae_summary(annotated),
            "outcome_path_rows": _anatomy_bucket_rows(annotated, key="path_type", min_sample=min_sample, baseline=baseline),
            "direction_rows": _direction_correctness_rows(annotated, baseline=baseline, min_sample=min_sample),
            "regime_rows": _mid_short_regime_rows(annotated, baseline=baseline, min_sample=min_sample),
            "session_rows": _anatomy_bucket_rows(annotated, key="wib_session", min_sample=min_sample, baseline=baseline),
            "symbol_rows": _anatomy_bucket_rows(annotated, key="symbol", min_sample=1, baseline=baseline, limit=limit),
            "evidence_tp_vs_sl": _evidence_field_rows(closed, min_sample=max(3, min_sample // 2)),
            "improvement_candidates": improvement_candidates,
            "latest_sl_signals": _sorted_signal_rows(sl_items, limit=min(limit, 20)),
            "latest_tp_signals": _sorted_signal_rows(tp_items, limit=min(limit, 20)),
            "latest_open_signals": _sorted_signal_rows(
                [item for item in annotated if item.get("result_status") == "OPEN"],
                limit=min(limit, 20),
            ),
            "guardrails": [
                "Failure anatomy only reads logged V2 MID_SHORT 1h signals and local futures candles.",
                "Path labels explain why TP/SL happened; they do not change Signal Factory rules.",
                "Primary failure causes are mutually exclusive research hypotheses, not proof of market causality.",
                "LAB-52 entry diagnostics use only information closed at signal time; forward fields are outcome-only.",
                "LAB-52 exit variants are fixed-cohort 4h simulations and do not replace the live TP/SL rule.",
                "LAB-53 structure clearance is a read-only shadow split and does not suppress live signals.",
                "LAB-54 support-aware targets are read-only 4h simulations and do not replace the live target.",
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
        annotated, skipped, latest_candle_time, normalized_shadow_status, _candles = self._mid_short_1h_anatomy_dataset(
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
        annotated, skipped, latest_candle_time, normalized_shadow_status, _candles = self._mid_short_1h_anatomy_dataset(
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
        annotated, skipped, latest_candle_time, normalized_shadow_status, _candles = self._mid_short_1h_anatomy_dataset(
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

    def mid_short_1h_entry_confirmation_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status, candles = (
            self._mid_short_1h_anatomy_dataset(
                epoch=epoch,
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                shadow_status="SHADOW_PASS",
            )
        )
        taker_scope = _apply_named_second_filter(annotated, "TAKER_SELL_GE_52")
        study = _mid_short_entry_confirmation_shadow_study(
            taker_scope,
            candles=candles,
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
                "base_filter_id": "TAKER_SELL_GE_52",
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_entry_confirmation_shadow_study",
            "study_scope": "read_only_mid_short_1h_15m_entry_confirmation",
            "source_table": "signal_forward_return_logs + futures_klines_15m",
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "base_filter": {
                "filter_id": "TAKER_SELL_GE_52",
                "label": "MID_SHORT 1h SHADOW_PASS + taker sell >= 52%",
                "expression": (
                    "stage == MID_SHORT AND timeframe == 1h AND SHADOW_PASS "
                    "AND kline_taker_sell_ratio >= 0.52"
                ),
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            **study,
            "guardrails": [
                "LAB-55 is a fixed-cohort shadow study and does not alter Signal Factory or scanner output.",
                "The confirmation candle must close before a delayed entry can exist.",
                "Delayed TP/SL evaluation starts from the candle after confirmation; confirmation high/low is never reused.",
                "The original risk distance and RR are preserved, while entry, stop, target, and realistic cost are recalculated.",
                "Position lock selects the source cohort once and is not re-optimized per confirmation variant.",
                "No threshold, live signal, order, execution, leverage, or position sizing is changed.",
            ],
        }

    def mid_short_1h_structure_zone_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
        signal_id: str | None = None,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status, _forward_candles = (
            self._mid_short_1h_anatomy_dataset(
                epoch=epoch,
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                shadow_status="SHADOW_PASS",
                include_failure_anatomy=False,
            )
        )
        signal_times = [
            value
            for value in (_parse_dt(item.get("signal_timestamp")) for item in annotated)
            if value is not None
        ]
        symbols = {str(item.get("symbol") or "") for item in annotated if item.get("symbol")}
        min_signal_time = min(signal_times, default=None)
        max_signal_time = max(signal_times, default=None)
        one_hour_candles = self._load_1h_candles(
            symbols,
            start_time=(min_signal_time - timedelta(hours=264)) if min_signal_time is not None else None,
            end_time=(max_signal_time + timedelta(hours=4)) if max_signal_time is not None else None,
        )
        four_hour_candles = self._load_4h_candles(
            symbols,
            start_time=(min_signal_time - timedelta(days=45)) if min_signal_time is not None else None,
            end_time=(max_signal_time + timedelta(hours=4)) if max_signal_time is not None else None,
        )
        study = _mid_short_structure_zone_study(
            annotated,
            one_hour_candles=one_hour_candles,
            four_hour_candles=four_hour_candles,
            min_sample=min_sample,
            limit=limit,
            selected_signal_id=signal_id,
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
                "signal_id": signal_id,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_structure_zone_study",
            "study_scope": "read_only_mid_short_1h_causal_structure_zones",
            "source_table": (
                "signal_forward_return_logs + futures_klines_1h + futures_klines_4h"
            ),
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            **study,
            "guardrails": [
                "Every 1h zone uses only futures candles closed before the signal; the signal candle may classify a reaction but cannot create its own zone.",
                "The 4h layer is optional confluence and never a hard gate for a MID_SHORT 1h signal.",
                "Configuration selection reads train performance only; validation stays an untouched checkpoint.",
                "Filtered rows remain in the fixed cohort as zero-R no-entry observations when tradeoff metrics are calculated.",
                "No Signal Factory rule, scanner decision, TP/SL formula, threshold, outcome logger, or execution path is changed.",
            ],
        }

    def mid_short_1h_v21_structure_interaction_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status, _forward_candles = (
            self._mid_short_1h_anatomy_dataset(
                epoch=epoch,
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                shadow_status="SHADOW_PASS",
                include_failure_anatomy=False,
            )
        )
        fixed_cohort = _apply_named_second_filter(annotated, "TAKER_SELL_GE_52")
        signal_times = [
            value
            for value in (_parse_dt(item.get("signal_timestamp")) for item in fixed_cohort)
            if value is not None
        ]
        symbols = {str(item.get("symbol") or "") for item in fixed_cohort if item.get("symbol")}
        min_signal_time = min(signal_times, default=None)
        max_signal_time = max(signal_times, default=None)
        one_hour_candles = self._load_1h_candles(
            symbols,
            start_time=(min_signal_time - timedelta(hours=264)) if min_signal_time is not None else None,
            end_time=(max_signal_time + timedelta(hours=4)) if max_signal_time is not None else None,
        )
        four_hour_candles = self._load_4h_candles(
            symbols,
            start_time=(min_signal_time - timedelta(days=45)) if min_signal_time is not None else None,
            end_time=(max_signal_time + timedelta(hours=4)) if max_signal_time is not None else None,
        )
        study = _mid_short_v21_structure_interaction_study(
            fixed_cohort,
            one_hour_candles=one_hour_candles,
            four_hour_candles=four_hour_candles,
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
                "base_filter_id": "TAKER_SELL_GE_52",
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_v21_structure_interaction_study",
            "study_scope": "read_only_mid_short_1h_v21_shadow_pass_structure_interaction",
            "source_table": (
                "signal_forward_return_logs + futures_klines_1h + futures_klines_4h"
            ),
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "base_filter": {
                "filter_id": "TAKER_SELL_GE_52",
                "label": "MID_SHORT 1h SHADOW_PASS + taker sell >= 52%",
                "expression": (
                    "stage == MID_SHORT AND timeframe == 1h AND SHADOW_PASS "
                    "AND kline_taker_sell_ratio >= 0.52"
                ),
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            **study,
            "guardrails": [
                "LAB-59 reads only the fixed V2.1 SHADOW_PASS plus taker-sell cohort; SHADOW_FAIL and other stages or timeframes are excluded.",
                "Every zone uses only futures candles closed at or before the signal and cannot see future pivots.",
                "Rows rejected by a variant remain zero-R observations in the fixed cohort comparison.",
                "Missing zone data is reported separately and is not silently treated as a conflict.",
                "The 4h zone is context-only and never a hard gate in this study.",
                "No Signal Factory rule, scanner decision, threshold, TP/SL formula, outcome logic, or execution path is changed.",
            ],
        }

    def mid_short_1h_v21_structure_exit_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status, forward_candles = (
            self._mid_short_1h_anatomy_dataset(
                epoch=epoch,
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                shadow_status="SHADOW_PASS",
                include_failure_anatomy=False,
            )
        )
        fixed_cohort = _apply_named_second_filter(annotated, "TAKER_SELL_GE_52")
        signal_times = [
            value
            for value in (_parse_dt(item.get("signal_timestamp")) for item in fixed_cohort)
            if value is not None
        ]
        symbols = {str(item.get("symbol") or "") for item in fixed_cohort if item.get("symbol")}
        min_signal_time = min(signal_times, default=None)
        max_signal_time = max(signal_times, default=None)
        one_hour_candles = self._load_1h_candles(
            symbols,
            start_time=(min_signal_time - timedelta(hours=264)) if min_signal_time is not None else None,
            end_time=(max_signal_time + timedelta(hours=4)) if max_signal_time is not None else None,
        )
        study = _mid_short_v21_structure_exit_study(
            fixed_cohort,
            one_hour_candles=one_hour_candles,
            forward_candles=forward_candles,
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
                "base_filter_id": "TAKER_SELL_GE_52",
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_v21_structure_exit_study",
            "study_scope": "read_only_mid_short_1h_v21_shadow_pass_structure_exit",
            "source_table": (
                "signal_forward_return_logs + futures_klines_15m + futures_klines_1m + futures_klines_1h"
            ),
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "base_filter": {
                "filter_id": "TAKER_SELL_GE_52",
                "label": "MID_SHORT 1h SHADOW_PASS + taker sell >= 52%",
                "expression": (
                    "stage == MID_SHORT AND timeframe == 1h AND SHADOW_PASS "
                    "AND kline_taker_sell_ratio >= 0.52"
                ),
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            **study,
            "guardrails": [
                "LAB-60 reads only the fixed V2.1 SHADOW_PASS plus taker-sell cohort.",
                "Repeated zones use only futures 1h candles closed before the signal.",
                "All exit variants use the same four-hour closed futures path and conservative same-candle handling.",
                "Unavailable structure falls back to logged geometry and is counted explicitly.",
                "No Signal Factory rule, scanner decision, threshold, logged TP/SL, outcome logic, or execution path is changed.",
            ],
        }

    def mid_short_1h_v21_dynamic_exit_study(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 50,
    ) -> dict[str, Any]:
        annotated, skipped, latest_candle_time, normalized_shadow_status, forward_candles = (
            self._mid_short_1h_anatomy_dataset(
                epoch=epoch,
                include_watch_only=include_watch_only,
                position_lock=position_lock,
                shadow_status="SHADOW_PASS",
                include_failure_anatomy=False,
            )
        )
        fixed_cohort = _apply_named_second_filter(annotated, "TAKER_SELL_GE_52")
        signal_times = [
            value
            for value in (_parse_dt(item.get("signal_timestamp")) for item in fixed_cohort)
            if value is not None
        ]
        symbols = {str(item.get("symbol") or "") for item in fixed_cohort if item.get("symbol")}
        min_signal_time = min(signal_times, default=None)
        max_signal_time = max(signal_times, default=None)
        one_hour_candles = self._load_1h_candles(
            symbols,
            start_time=(min_signal_time - timedelta(hours=264)) if min_signal_time is not None else None,
            end_time=(max_signal_time + timedelta(hours=4)) if max_signal_time is not None else None,
        )
        study = _mid_short_v21_dynamic_exit_study(
            fixed_cohort,
            one_hour_candles=one_hour_candles,
            forward_candles=forward_candles,
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
                "base_filter_id": "TAKER_SELL_GE_52",
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "artifact_type": "mid_short_1h_v21_dynamic_exit_study",
            "study_scope": "read_only_mid_short_1h_v21_causal_dynamic_exit",
            "source_table": (
                "signal_forward_return_logs + futures_klines_15m + futures_klines_1m + futures_klines_1h"
            ),
            "strategy_version": LIVE_STRATEGY_VERSION,
            "shadow_strategy_version": SHADOW_STRATEGY_VERSION,
            "base_filter": {
                "filter_id": "TAKER_SELL_GE_52",
                "label": "MID_SHORT 1h SHADOW_PASS + taker sell >= 52%",
                "expression": (
                    "stage == MID_SHORT AND timeframe == 1h AND SHADOW_PASS "
                    "AND kline_taker_sell_ratio >= 0.52"
                ),
            },
            "latest_evaluation_candle_time": latest_candle_time,
            "latest_futures_15m_close_time": latest_candle_time,
            "skipped_by_position_lock": dict(skipped),
            **study,
            "guardrails": [
                "LAB-61 reads exactly the fixed LAB-59/LAB-60 V2.1 cohort; no signal is added or removed per variant.",
                "A support-reclaim decision uses only a fully closed futures 15m candle and a causal 1h zone known at signal time.",
                "TP or SL touched before the decision candle closes remains terminal; the study never rewrites that result.",
                "A simulated dynamic exit fills at the next available futures candle open, never at the trigger candle close.",
                "The latest 1m tail may provide a next-open fill but can never create the 15m reclaim decision.",
                "No Signal Factory rule, scanner decision, threshold, logged TP/SL, outcome logic, or execution path is changed.",
            ],
        }

    def mid_short_1h_structure_zone_case(
        self,
        *,
        signal_id: str,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
    ) -> dict[str, Any]:
        signals = self._load_signals(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage="MID_SHORT",
            timeframe="1h",
            symbol=None,
            signal_id=signal_id,
        )
        if not signals:
            return {"selected_case": None, "selected_chart": None}

        signal = signals[0]
        signal_time = _naive(signal.signal_timestamp)
        symbols = {signal.symbol}
        base_candles = self._load_15m_candles(
            symbols,
            start_time=signal_time - timedelta(hours=10),
        )
        latest_base_time = max(
            (candle.close_time for rows in base_candles.values() for candle in rows),
            default=None,
        )
        tail_candles = self._load_1m_candles(
            symbols,
            start_time=latest_base_time or signal_time,
        )
        forward_candles = _merge_candle_maps(base_candles, tail_candles)
        evaluated, _skipped = self._evaluate(
            signals,
            forward_candles,
            position_lock=False,
            global_latest_candle_time=self._global_latest_candle_time() or latest_base_time,
        )
        if not evaluated:
            return {"selected_case": None, "selected_chart": None}

        one_hour_candles = self._load_1h_candles(
            symbols,
            start_time=signal_time - timedelta(hours=264),
            end_time=signal_time + timedelta(hours=4),
        )
        four_hour_candles = self._load_4h_candles(
            symbols,
            start_time=signal_time - timedelta(days=45),
            end_time=signal_time + timedelta(hours=4),
        )
        item = evaluated[0]
        context = _lab56_structure_context(
            item,
            one_hour_candles=sorted(
                one_hour_candles.get(signal.symbol, []),
                key=lambda candle: candle.close_time,
            ),
            four_hour_candles=sorted(
                four_hour_candles.get(signal.symbol, []),
                key=lambda candle: candle.close_time,
            ),
            config=next(
                config for config in LAB56_ZONE_CONFIGS if config.config_id == LAB56_PRIMARY_CONFIG_ID
            ),
        )
        selected = {**item, **context}
        return {
            "selected_case": _lab56_case_row(selected),
            "selected_chart": _lab56_zone_chart_payload(
                selected,
                candles=one_hour_candles.get(signal.symbol, []),
            ),
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
        annotated, skipped, latest_candle_time, normalized_shadow_status, _candles = self._mid_short_1h_anatomy_dataset(
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
        annotated, skipped, latest_candle_time, normalized_shadow_status, _candles = self._mid_short_1h_anatomy_dataset(
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
        include_target_distance_context: bool = False,
        include_failure_anatomy: bool = True,
    ) -> tuple[
        list[dict[str, Any]],
        Counter[str],
        datetime | None,
        str,
        dict[str, list[PerfCandle]],
    ]:
        signals = self._load_signals(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage="MID_SHORT",
            timeframe="1h",
            symbol=None,
            signal_id=None,
        )
        min_signal_time = min((_naive(row.signal_timestamp) for row in signals), default=None)
        max_signal_time = max((_naive(row.signal_timestamp) for row in signals), default=None)
        source_symbols = {row.symbol for row in signals}
        candle_symbols = (
            set(source_symbols) | {"BTCUSDT", "ETHUSDT"}
            if include_failure_anatomy
            else set(source_symbols)
        )
        candle_start = min_signal_time - timedelta(hours=10) if min_signal_time is not None else None
        start_times_by_symbol: dict[str, datetime] = {}
        for signal in signals:
            symbol_start = _naive(signal.signal_timestamp) - timedelta(hours=10)
            current = start_times_by_symbol.get(signal.symbol)
            if current is None or symbol_start < current:
                start_times_by_symbol[signal.symbol] = symbol_start
        for symbol in candle_symbols - source_symbols:
            if candle_start is not None:
                start_times_by_symbol[symbol] = candle_start
        base_candles = self._load_15m_candles(
            candle_symbols,
            start_time=candle_start,
            start_times_by_symbol=start_times_by_symbol,
        )
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
        one_hour_candles = (
            self._load_1h_candles(
                source_symbols,
                start_time=min_signal_time - timedelta(hours=72) if min_signal_time is not None else None,
                end_time=max_signal_time + timedelta(hours=4) if max_signal_time is not None else None,
            )
            if include_target_distance_context
            else {}
        )
        oi_history = (
            self._load_1h_oi_changes(
                source_symbols,
                start_time=min_signal_time if min_signal_time is not None else None,
                end_time=max_signal_time + timedelta(hours=1, minutes=15) if max_signal_time is not None else None,
            )
            if include_target_distance_context
            else {}
        )
        normalized_shadow_status = (shadow_status or "SHADOW_PASS").upper()
        if normalized_shadow_status != "ALL":
            evaluated = [
                item
                for item in evaluated
                if str(item.get("quality_shadow_status") or "").upper() == normalized_shadow_status
            ]
        annotated = (
            _annotate_mid_short_failure_anatomy(
                evaluated,
                candles,
                one_hour_candles=one_hour_candles,
                oi_history=oi_history,
                include_target_distance_context=include_target_distance_context,
            )
            if include_failure_anatomy
            else evaluated
        )
        return (
            annotated,
            skipped,
            latest_candle_time,
            normalized_shadow_status,
            candles,
        )

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
        start_times_by_symbol: dict[str, datetime] | None = None,
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
                FuturesKline15m.taker_buy_base_volume,
                FuturesKline15m.taker_sell_base_volume,
                FuturesKline15m.aggregation_status,
            )
            .order_by(asc(FuturesKline15m.symbol), asc(FuturesKline15m.open_time))
        )
        if start_times_by_symbol:
            symbol_windows = []
            for symbol in symbols:
                symbol_start = start_times_by_symbol.get(symbol, start_time)
                predicate = FuturesKline15m.symbol == symbol
                if symbol_start is not None:
                    predicate = and_(predicate, FuturesKline15m.open_time >= symbol_start)
                symbol_windows.append(predicate)
            query = query.where(or_(*symbol_windows))
        else:
            query = query.where(FuturesKline15m.symbol.in_(symbols))
            if start_time is not None:
                query = query.where(FuturesKline15m.open_time >= start_time)
        if end_time is not None:
            query = query.where(FuturesKline15m.open_time <= end_time)
        rows = self.db.execute(query).all()
        output: dict[str, list[PerfCandle]] = defaultdict(list)
        for row in rows:
            if row.aggregation_status != "AGG_READY":
                continue
            output[row.symbol].append(
                PerfCandle(
                    open_time=_naive(row.open_time),
                    close_time=_naive(row.close_time),
                    open=Decimal(row.open),
                    high=Decimal(row.high),
                    low=Decimal(row.low),
                    close=Decimal(row.close),
                    volume=Decimal(row.volume) if row.volume is not None else None,
                    taker_buy_base_volume=(
                        Decimal(row.taker_buy_base_volume) if row.taker_buy_base_volume is not None else None
                    ),
                    taker_sell_base_volume=(
                        Decimal(row.taker_sell_base_volume) if row.taker_sell_base_volume is not None else None
                    ),
                    source_interval="15m",
                )
            )
        return dict(output)

    def _load_1h_candles(
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
                FuturesKline1h.symbol,
                FuturesKline1h.open_time,
                FuturesKline1h.close_time,
                FuturesKline1h.open,
                FuturesKline1h.high,
                FuturesKline1h.low,
                FuturesKline1h.close,
                FuturesKline1h.volume,
                FuturesKline1h.taker_buy_base_volume,
                FuturesKline1h.taker_sell_base_volume,
                FuturesKline1h.aggregation_status,
            )
            .where(
                FuturesKline1h.symbol.in_(symbols),
            )
            .order_by(asc(FuturesKline1h.symbol), asc(FuturesKline1h.open_time))
        )
        if start_time is not None:
            query = query.where(FuturesKline1h.open_time >= start_time)
        if end_time is not None:
            query = query.where(FuturesKline1h.open_time <= end_time)
        rows = self.db.execute(query).all()
        output: dict[str, list[PerfCandle]] = defaultdict(list)
        for row in rows:
            if row.aggregation_status != "AGG_READY":
                continue
            output[row.symbol].append(
                PerfCandle(
                    open_time=_naive(row.open_time),
                    close_time=_naive(row.close_time),
                    open=Decimal(row.open),
                    high=Decimal(row.high),
                    low=Decimal(row.low),
                    close=Decimal(row.close),
                    volume=Decimal(row.volume) if row.volume is not None else None,
                    taker_buy_base_volume=(
                        Decimal(row.taker_buy_base_volume) if row.taker_buy_base_volume is not None else None
                    ),
                    taker_sell_base_volume=(
                        Decimal(row.taker_sell_base_volume) if row.taker_sell_base_volume is not None else None
                    ),
                    source_interval="1h",
                )
            )
        return dict(output)

    def _load_4h_candles(
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
                FuturesKline4h.symbol,
                FuturesKline4h.open_time,
                FuturesKline4h.close_time,
                FuturesKline4h.open,
                FuturesKline4h.high,
                FuturesKline4h.low,
                FuturesKline4h.close,
                FuturesKline4h.volume,
                FuturesKline4h.taker_buy_base_volume,
                FuturesKline4h.taker_sell_base_volume,
                FuturesKline4h.aggregation_status,
            )
            .where(FuturesKline4h.symbol.in_(symbols))
            .order_by(asc(FuturesKline4h.symbol), asc(FuturesKline4h.open_time))
        )
        if start_time is not None:
            query = query.where(FuturesKline4h.open_time >= start_time)
        if end_time is not None:
            query = query.where(FuturesKline4h.open_time <= end_time)
        output: dict[str, list[PerfCandle]] = defaultdict(list)
        for row in self.db.execute(query).all():
            if row.aggregation_status != "AGG_READY":
                continue
            output[row.symbol].append(
                PerfCandle(
                    open_time=_naive(row.open_time),
                    close_time=_naive(row.close_time),
                    open=Decimal(row.open),
                    high=Decimal(row.high),
                    low=Decimal(row.low),
                    close=Decimal(row.close),
                    volume=Decimal(row.volume) if row.volume is not None else None,
                    taker_buy_base_volume=(
                        Decimal(row.taker_buy_base_volume) if row.taker_buy_base_volume is not None else None
                    ),
                    taker_sell_base_volume=(
                        Decimal(row.taker_sell_base_volume) if row.taker_sell_base_volume is not None else None
                    ),
                    source_interval="4h",
                )
            )
        return dict(output)

    def _load_1h_oi_changes(
        self,
        symbols: set[str],
        *,
        start_time: datetime | None,
        end_time: datetime | None = None,
    ) -> dict[str, list[tuple[datetime, Decimal]]]:
        if not symbols or start_time is None:
            return {}
        query = (
            select(
                RichFutures5mAlignment.symbol,
                RichFutures5mAlignment.window_close_time,
                RichFutures5mAlignment.oi_change_pct,
            )
            .where(
                RichFutures5mAlignment.symbol.in_(symbols),
                RichFutures5mAlignment.timeframe == "1h",
                RichFutures5mAlignment.alignment_status == "ALIGNED",
                RichFutures5mAlignment.window_close_time >= start_time,
                RichFutures5mAlignment.oi_change_pct.is_not(None),
            )
            .order_by(
                asc(RichFutures5mAlignment.symbol),
                asc(RichFutures5mAlignment.window_close_time),
            )
        )
        if end_time is not None:
            query = query.where(RichFutures5mAlignment.window_close_time <= end_time)
        output: dict[str, list[tuple[datetime, Decimal]]] = defaultdict(list)
        for row in self.db.execute(query).all():
            output[row.symbol].append((_naive(row.window_close_time), Decimal(row.oi_change_pct)))
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
                FuturesKline1m.taker_buy_base_volume,
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
            volume = Decimal(row.volume) if row.volume is not None else None
            taker_buy = Decimal(row.taker_buy_base_volume) if row.taker_buy_base_volume is not None else None
            output[row.symbol].append(
                PerfCandle(
                    open_time=_naive(row.open_time),
                    close_time=_naive(row.close_time),
                    open=Decimal(row.open_price),
                    high=Decimal(row.high_price),
                    low=Decimal(row.low_price),
                    close=Decimal(row.close_price),
                    volume=volume,
                    taker_buy_base_volume=taker_buy,
                    taker_sell_base_volume=(volume - taker_buy) if volume is not None and taker_buy is not None else None,
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
        structure_zone_shadow = _structure_zone_snapshot(signal)
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
            **_structure_zone_result_fields(structure_zone_shadow),
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


def _structure_zone_snapshot(signal: SignalForwardReturnLog) -> dict[str, Any] | None:
    raw_evidence = signal.evidence if isinstance(signal.evidence, dict) else {}
    snapshot = raw_evidence.get("structure_zone_shadow")
    return snapshot if isinstance(snapshot, dict) else None


def _structure_zone_result_fields(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {
            "structure_zone_shadow": None,
            "structure_zone_status": "ZONE_UNAVAILABLE",
            "structure_zone_reason": "No persisted structure-zone snapshot exists for this signal.",
            "structure_zone_primary_timeframe": None,
            "structure_zone_primary_state": None,
            "structure_zone_primary_reason": None,
            "structure_zone_primary_zone_count": None,
            "structure_zone_context_timeframe": None,
            "structure_zone_context_status": None,
            "structure_zone_context_state": None,
            "structure_zone_context_reason": None,
            "structure_zone_snapshot_time": None,
        }
    primary = snapshot.get("primary") if isinstance(snapshot.get("primary"), dict) else {}
    context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
    return {
        "structure_zone_shadow": snapshot,
        "structure_zone_status": snapshot.get("status") or "ZONE_UNAVAILABLE",
        "structure_zone_reason": snapshot.get("reason") or "Structure-zone snapshot is unavailable.",
        "structure_zone_primary_timeframe": snapshot.get("primary_timeframe"),
        "structure_zone_primary_state": primary.get("state"),
        "structure_zone_primary_reason": primary.get("reason"),
        "structure_zone_primary_zone_count": primary.get("zone_count"),
        "structure_zone_nearest_support_distance_atr": primary.get("nearest_support_distance_atr"),
        "structure_zone_nearest_resistance_distance_atr": primary.get("nearest_resistance_distance_atr"),
        "structure_zone_context_timeframe": snapshot.get("context_timeframe"),
        "structure_zone_context_status": context.get("status"),
        "structure_zone_context_state": context.get("state"),
        "structure_zone_context_reason": context.get("reason"),
        "structure_zone_snapshot_time": snapshot.get("generated_at_utc"),
    }


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


def build_v3_shadow_filter_map(
    items: list[dict[str, Any]],
    *,
    min_sample: int = 5,
    limit: int = 100,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    return _v3_shadow_filter_map(items, min_sample=max(1, min_sample), limit=max(1, limit))


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
    *,
    one_hour_candles: dict[str, list[PerfCandle]] | None = None,
    oi_history: dict[str, list[tuple[datetime, Decimal]]] | None = None,
    include_target_distance_context: bool = False,
) -> list[dict[str, Any]]:
    one_hour_candles = one_hour_candles or {}
    oi_history = oi_history or {}
    btc_candles = candles.get("BTCUSDT", [])
    eth_candles = candles.get("ETHUSDT", [])
    annotated: list[dict[str, Any]] = []
    for item in items:
        symbol = str(item.get("symbol") or "")
        symbol_candles = candles.get(symbol, [])
        path = _mid_short_path_anatomy(item, symbol_candles)
        regime = _mid_short_regime_context(item, btc_candles=btc_candles, eth_candles=eth_candles)
        target_context = (
            _mid_short_target_distance_context(
                item,
                candles=symbol_candles,
                one_hour_candles=one_hour_candles.get(symbol, []),
                oi_rows=oi_history.get(symbol, []),
            )
            if include_target_distance_context
            else {}
        )
        base = {
            **item,
            **path,
            **regime,
            **target_context,
            "wib_session": _wib_session(_parse_dt(item.get("signal_timestamp"))),
        }
        enriched = {**base, **_mid_short_sl_failure_classification(base)}
        annotated.append(enriched)
    return annotated


LAB52_COUNTERFACTUAL_SPECS = (
    ("CONTROL_LOGGED", "Logged SL / TP", Decimal("1"), None, None, True),
    ("TP_0_75R", "Target 0.75R", Decimal("1"), Decimal("0.75"), None, False),
    ("TP_1_0R", "Target 1.00R", Decimal("1"), Decimal("1.00"), None, False),
    ("TP_1_25R", "Target 1.25R", Decimal("1"), Decimal("1.25"), None, False),
    ("TP_1_5R", "Target 1.50R", Decimal("1"), Decimal("1.50"), None, False),
    ("TP_1_5R_BE_0_75R", "Target 1.50R + protect entry after 0.75R", Decimal("1"), Decimal("1.50"), Decimal("0.75"), False),
    ("ATR_RISK_0_75X_RR_1_5", "Risk 0.75x logged + target 1.50R", Decimal("0.75"), Decimal("1.50"), None, False),
    ("ATR_RISK_1_25X_RR_1_5", "Risk 1.25x logged + target 1.50R", Decimal("1.25"), Decimal("1.50"), None, False),
)


LAB54_TARGET_SPECS = (
    ("CONTROL_LOGGED", "Logged target", "LOGGED_TARGET"),
    ("TP_0_75R", "Fixed target 0.75R", "FIXED_R_REFERENCE"),
    ("SUPPORT_TOUCH", "Nearest closed 1h support", "SUPPORT_REFERENCE"),
    (
        "SUPPORT_COST_BUFFER",
        "Before support + execution-impact buffer",
        "SUPPORT_EXECUTION_BUFFER",
    ),
)

LAB54_SUPPORT_CONFIG_IDS = frozenset({"SUPPORT_TOUCH", "SUPPORT_COST_BUFFER"})

LAB55_CONFIRMATION_SPECS = (
    (
        "CONTROL_IMMEDIATE",
        "Immediate entry control",
        "Enter at the logged signal close with logged stop and target.",
    ),
    (
        "WAIT_15M_ALWAYS",
        "Wait one closed 15m candle",
        "Always enter at the first closed 15m confirmation price.",
    ),
    (
        "VETO_UP_REVERSAL_0_05",
        "Wait 15m and veto +0.05% reversal",
        "Enter unless the confirmation close is at least 0.05% above the signal entry.",
    ),
    (
        "CONFIRM_CLOSE_BELOW_ENTRY",
        "Confirm close below signal entry",
        "Enter only when the confirmation close is below the original signal entry.",
    ),
    (
        "CONFIRM_BELOW_ENTRY_TAKER_SELL_52",
        "Confirm direction and taker sell",
        "Enter only when confirmation closes below signal entry and taker sell is at least 52%.",
    ),
)

LAB55_LOSS_STATUSES = frozenset({"SL_HIT", "BOTH_HIT_SAME_CANDLE"})


LAB52_ITEM_ONLY_FIELDS = frozenset(
    {
        "_lab52_counterfactuals",
        "atr_1h_at_entry",
        "atr_pct_entry",
        "logged_risk_atr_ratio",
        "atr_30_median",
        "atr_vs_30_median",
        "atr_prior_value",
        "atr_signal_inflation_ratio",
        "signal_true_range_atr",
        "signal_tr_contribution_pct",
        "pre_entry_1h_move_atr",
        "pre_entry_4h_move_atr",
        "atr_closed_candle_count",
        "support_price_proxy",
        "support_distance_r",
        "support_before_target",
        "support_method",
        "forward_1h_realized_range_atr",
        "forward_1h_mfe_r",
        "forward_1h_mae_r",
        "forward_2h_mfe_r",
        "forward_2h_mae_r",
        "forward_4h_mfe_r",
        "forward_4h_mae_r",
        "forward_1h_taker_sell_ratio",
        "forward_1h_volume_vs_pre30",
        "forward_1h_oi_change_pct",
        "time_to_0_25r_minutes",
        "time_to_0_50r_minutes",
        "time_to_0_75r_minutes",
        "time_to_1_00r_minutes",
        "time_to_1_25r_minutes",
        "time_to_1_50r_minutes",
        "time_to_mfe_minutes",
        "volume_baseline_candle_count",
        "oi_entry_timestamp",
        "oi_forward_1h_timestamp",
        "oi_forward_source",
        "entry_taker_sell_ratio",
        "entry_volume_ratio",
        "entry_oi_change_pct",
        "taker_sell_delta_1h",
        "oi_change_delta_1h",
        "target_distance_context_available",
        "target_distance_context_total",
        "target_distance_context_status",
        "target_distance_hypotheses",
        "target_distance_primary_hypothesis",
        "structure_clearance_status",
        "support_clearance_to_target_r",
        "_lab54_support_targets",
    }
)


def _strip_lab52_internal_item_fields(item: dict[str, Any]) -> None:
    for field in LAB52_ITEM_ONLY_FIELDS:
        item.pop(field, None)


def _mid_short_target_distance_context(
    item: dict[str, Any],
    *,
    candles: list[PerfCandle],
    one_hour_candles: list[PerfCandle],
    oi_rows: list[tuple[datetime, Decimal]],
) -> dict[str, Any]:
    entry = _decimal_or_none_any(item.get("entry"))
    risk = _decimal_or_none_any(item.get("risk"))
    target = _decimal_or_none_any(item.get("take_profit"))
    signal_time = _parse_dt(item.get("signal_timestamp"))
    if entry is None or risk is None or risk <= 0 or target is None or signal_time is None:
        return _empty_mid_short_target_distance_context()

    atr_context = _mid_short_atr_context(
        entry=entry,
        risk=risk,
        signal_time=signal_time,
        one_hour_candles=one_hour_candles,
    )
    forward_context = _mid_short_forward_context(
        item,
        candles=candles,
        signal_time=signal_time,
        entry=entry,
        risk=risk,
        atr_1h=_decimal_or_none_any(atr_context.get("atr_1h_at_entry")),
    )
    support_context = _mid_short_support_context(
        entry=entry,
        target=target,
        risk=risk,
        signal_time=signal_time,
        one_hour_candles=one_hour_candles,
    )
    oi_context = _mid_short_oi_context(signal_time=signal_time, oi_rows=oi_rows)
    evidence = item.get("evidence_snapshot") if isinstance(item.get("evidence_snapshot"), dict) else {}
    entry_taker_sell = _decimal_or_none_any(evidence.get("kline_taker_sell_ratio"))
    entry_volume_ratio = _decimal_or_none_any(evidence.get("volume_ratio_vs_lookback"))
    entry_oi_change = _decimal_or_none_any(evidence.get("oi_change_pct"))
    forward_taker_sell = _decimal_or_none_any(forward_context.get("forward_1h_taker_sell_ratio"))
    forward_oi_change = _decimal_or_none_any(oi_context.get("forward_1h_oi_change_pct"))
    ordered_candles = sorted(candles, key=lambda candle: candle.open_time)
    open_times = [candle.open_time for candle in ordered_candles]
    prepared_future_4h = [
        candle
        for candle in ordered_candles[bisect_left(open_times, signal_time):]
        if candle.close_time <= signal_time + timedelta(hours=4)
    ]
    data_points = {
        "atr": atr_context.get("atr_1h_at_entry"),
        "structure": support_context.get("support_price_proxy"),
        "forward_range": forward_context.get("forward_1h_realized_range_atr"),
        "taker": forward_taker_sell,
        "volume": forward_context.get("forward_1h_volume_vs_pre30"),
        "oi": forward_oi_change,
    }
    available_count = sum(value is not None for value in data_points.values())
    return {
        **atr_context,
        **forward_context,
        **support_context,
        **oi_context,
        "entry_taker_sell_ratio": entry_taker_sell,
        "entry_volume_ratio": entry_volume_ratio,
        "entry_oi_change_pct": entry_oi_change,
        "taker_sell_delta_1h": (
            forward_taker_sell - entry_taker_sell
            if forward_taker_sell is not None and entry_taker_sell is not None
            else None
        ),
        "oi_change_delta_1h": (
            forward_oi_change - entry_oi_change
            if forward_oi_change is not None and entry_oi_change is not None
            else None
        ),
        "target_distance_context_available": available_count,
        "target_distance_context_total": len(data_points),
        "target_distance_context_status": (
            "CONTEXT_COMPLETE" if available_count == len(data_points) else "CONTEXT_PARTIAL"
        ),
        "_lab52_counterfactuals": {
            config_id: _mid_short_counterfactual_exit(
                item,
                candles=candles,
                risk_scale=risk_scale,
                target_rr=target_rr,
                protect_at_r=protect_at_r,
                use_logged_target=use_logged_target,
                prepared_future_4h=prepared_future_4h,
            )
            for config_id, _label, risk_scale, target_rr, protect_at_r, use_logged_target in LAB52_COUNTERFACTUAL_SPECS
        },
        "_lab54_support_targets": _lab54_support_target_results(
            item,
            support_price=_decimal_or_none_any(support_context.get("support_price_proxy")),
            prepared_future_4h=prepared_future_4h,
        ),
    }


def _empty_mid_short_target_distance_context() -> dict[str, Any]:
    return {
        "atr_1h_at_entry": None,
        "atr_pct_entry": None,
        "logged_risk_atr_ratio": None,
        "atr_30_median": None,
        "atr_vs_30_median": None,
        "atr_prior_value": None,
        "atr_signal_inflation_ratio": None,
        "signal_true_range_atr": None,
        "signal_tr_contribution_pct": None,
        "pre_entry_1h_move_atr": None,
        "pre_entry_4h_move_atr": None,
        "support_price_proxy": None,
        "support_distance_r": None,
        "support_before_target": False,
        "forward_1h_realized_range_atr": None,
        "forward_1h_mfe_r": None,
        "forward_1h_mae_r": None,
        "forward_2h_mfe_r": None,
        "forward_2h_mae_r": None,
        "forward_4h_mfe_r": None,
        "forward_4h_mae_r": None,
        "forward_1h_taker_sell_ratio": None,
        "forward_1h_volume_vs_pre30": None,
        "forward_1h_oi_change_pct": None,
        "entry_taker_sell_ratio": None,
        "entry_volume_ratio": None,
        "entry_oi_change_pct": None,
        "taker_sell_delta_1h": None,
        "oi_change_delta_1h": None,
        "target_distance_context_available": 0,
        "target_distance_context_total": 6,
        "target_distance_context_status": "CONTEXT_MISSING",
        "_lab52_counterfactuals": {},
        "_lab54_support_targets": {},
    }


def _mid_short_atr_context(
    *,
    entry: Decimal,
    risk: Decimal,
    signal_time: datetime,
    one_hour_candles: list[PerfCandle],
) -> dict[str, Any]:
    closed = sorted(
        (candle for candle in one_hour_candles if candle.close_time <= signal_time),
        key=lambda candle: candle.close_time,
    )
    true_ranges = _candle_true_ranges(closed)
    atr_series: list[tuple[datetime, Decimal]] = []
    for index in range(13, len(true_ranges)):
        atr_series.append(
            (
                closed[index].close_time,
                sum(true_ranges[index - 13 : index + 1], Decimal("0")) / Decimal("14"),
            )
        )
    atr = atr_series[-1][1] if atr_series else None
    prior_atr = atr_series[-2][1] if len(atr_series) >= 2 else None
    historical_atrs = [value for _time, value in atr_series[-31:-1]]
    atr_30_median = _percentile_decimal(historical_atrs, Decimal("0.5"))
    current_tr = true_ranges[-1] if true_ranges else None
    prior_close_1h = closed[-2].close if len(closed) >= 2 else None
    prior_close_4h = closed[-5].close if len(closed) >= 5 else None
    return {
        "atr_1h_at_entry": atr,
        "atr_pct_entry": (atr / entry * Decimal("100")) if atr is not None and entry > 0 else None,
        "logged_risk_atr_ratio": (risk / atr) if atr is not None and atr > 0 else None,
        "atr_30_median": atr_30_median,
        "atr_vs_30_median": (atr / atr_30_median) if atr is not None and atr_30_median not in (None, Decimal("0")) else None,
        "atr_prior_value": prior_atr,
        "atr_signal_inflation_ratio": (atr / prior_atr) if atr is not None and prior_atr not in (None, Decimal("0")) else None,
        "signal_true_range_atr": (current_tr / atr) if current_tr is not None and atr not in (None, Decimal("0")) else None,
        "signal_tr_contribution_pct": (current_tr / (atr * Decimal("14")) * Decimal("100")) if current_tr is not None and atr not in (None, Decimal("0")) else None,
        "pre_entry_1h_move_atr": ((prior_close_1h - entry) / atr) if prior_close_1h is not None and atr not in (None, Decimal("0")) else None,
        "pre_entry_4h_move_atr": ((prior_close_4h - entry) / atr) if prior_close_4h is not None and atr not in (None, Decimal("0")) else None,
        "atr_closed_candle_count": len(closed),
    }


def _candle_true_ranges(candles: list[PerfCandle]) -> list[Decimal]:
    output: list[Decimal] = []
    previous_close: Decimal | None = None
    for candle in candles:
        values = [candle.high - candle.low]
        if previous_close is not None:
            values.extend((abs(candle.high - previous_close), abs(candle.low - previous_close)))
        output.append(max(values))
        previous_close = candle.close
    return output


def _mid_short_support_context(
    *,
    entry: Decimal,
    target: Decimal,
    risk: Decimal,
    signal_time: datetime,
    one_hour_candles: list[PerfCandle],
) -> dict[str, Any]:
    closed = sorted(
        (candle for candle in one_hour_candles if candle.close_time <= signal_time),
        key=lambda candle: candle.close_time,
    )[-24:]
    swing_low = None
    support_method = "CONFIRMED_SWING_LOW_1H"
    for index in range(len(closed) - 2, 0, -1):
        if closed[index].low <= closed[index - 1].low and closed[index].low <= closed[index + 1].low:
            swing_low = closed[index].low
            break
    if swing_low is None and closed:
        swing_low = min(candle.low for candle in closed)
        support_method = "PERIOD_LOW_FALLBACK_1H"
    support_distance_r = (entry - swing_low) / risk if swing_low is not None and risk > 0 else None
    return {
        "support_price_proxy": swing_low,
        "support_distance_r": support_distance_r,
        "support_before_target": bool(
            swing_low is not None and target < swing_low < entry and support_distance_r is not None and support_distance_r > 0
        ),
        "support_method": support_method,
    }


def _mid_short_forward_context(
    item: dict[str, Any],
    *,
    candles: list[PerfCandle],
    signal_time: datetime,
    entry: Decimal,
    risk: Decimal,
    atr_1h: Decimal | None,
) -> dict[str, Any]:
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    open_times = [candle.open_time for candle in ordered]
    future = ordered[bisect_left(open_times, signal_time):]
    future_4h = [candle for candle in future if candle.close_time <= signal_time + timedelta(hours=4)]
    pre_15m = [
        candle
        for candle in ordered
        if candle.source_interval == "15m" and candle.close_time <= signal_time and candle.volume is not None
    ][-30:]
    mean_pre_volume = _avg_decimal([Decimal(candle.volume) for candle in pre_15m if candle.volume is not None])
    output: dict[str, Any] = {}
    for label, minutes in (("1h", 60), ("2h", 120), ("4h", 240)):
        rows = [candle for candle in future if candle.close_time <= signal_time + timedelta(minutes=minutes)]
        if not rows:
            output[f"forward_{label}_mfe_r"] = None
            output[f"forward_{label}_mae_r"] = None
            if label == "1h":
                output["forward_1h_realized_range_atr"] = None
            continue
        output[f"forward_{label}_mfe_r"] = max((entry - candle.low) / risk for candle in rows)
        output[f"forward_{label}_mae_r"] = min((entry - candle.high) / risk for candle in rows)
        if label == "1h":
            realized_range = max(candle.high for candle in rows) - min(candle.low for candle in rows)
            output["forward_1h_realized_range_atr"] = (
                realized_range / atr_1h if atr_1h not in (None, Decimal("0")) else None
            )
            buy = sum(
                (Decimal(candle.taker_buy_base_volume) for candle in rows if candle.taker_buy_base_volume is not None),
                Decimal("0"),
            )
            sell = sum(
                (Decimal(candle.taker_sell_base_volume) for candle in rows if candle.taker_sell_base_volume is not None),
                Decimal("0"),
            )
            output["forward_1h_taker_sell_ratio"] = sell / (buy + sell) if buy + sell > 0 else None
            forward_volume = sum(
                (Decimal(candle.volume) for candle in rows if candle.volume is not None),
                Decimal("0"),
            )
            expected_volume = mean_pre_volume * Decimal("4") if mean_pre_volume is not None else None
            output["forward_1h_volume_vs_pre30"] = (
                forward_volume / expected_volume if expected_volume not in (None, Decimal("0")) else None
            )

    level_times: dict[str, Decimal | None] = {}
    for level in (Decimal("0.25"), Decimal("0.50"), Decimal("0.75"), Decimal("1.00"), Decimal("1.25"), Decimal("1.50")):
        hit = next((candle for candle in future_4h if candle.low <= entry - (risk * level)), None)
        key = str(level).replace(".", "_")
        level_times[f"time_to_{key}r_minutes"] = (
            Decimal((hit.close_time - signal_time).total_seconds()) / Decimal("60") if hit else None
        )
    mfe_candle = min(future_4h, key=lambda candle: candle.low) if future_4h else None
    return {
        **output,
        **level_times,
        "time_to_mfe_minutes": (
            Decimal((mfe_candle.close_time - signal_time).total_seconds()) / Decimal("60") if mfe_candle else None
        ),
        "volume_baseline_candle_count": len(pre_15m),
    }


def _mid_short_oi_context(
    *,
    signal_time: datetime,
    oi_rows: list[tuple[datetime, Decimal]],
) -> dict[str, Any]:
    ordered = sorted(oi_rows, key=lambda row: row[0])
    timestamps = [row[0] for row in ordered]

    def point_at_or_before(cutoff: datetime) -> tuple[datetime, Decimal] | None:
        index = bisect_right(timestamps, cutoff) - 1
        if index < 0:
            return None
        point = ordered[index]
        return point if cutoff - point[0] <= timedelta(minutes=10) else None

    end = point_at_or_before(signal_time + timedelta(hours=1))
    return {
        "forward_1h_oi_change_pct": end[1] if end else None,
        "oi_entry_timestamp": signal_time,
        "oi_forward_1h_timestamp": end[0] if end else None,
        "oi_forward_source": "rich_futures_5m_alignment timeframe=1h",
    }


def _mid_short_counterfactual_exit(
    item: dict[str, Any],
    *,
    candles: list[PerfCandle],
    risk_scale: Decimal,
    target_rr: Decimal | None,
    protect_at_r: Decimal | None,
    use_logged_target: bool,
    prepared_future_4h: list[PerfCandle] | None = None,
    target_override: Decimal | None = None,
    require_complete_horizon_for_neither: bool = False,
) -> dict[str, Any]:
    entry = _decimal_or_none_any(item.get("entry"))
    logged_risk = _decimal_or_none_any(item.get("risk"))
    signal_time = _parse_dt(item.get("signal_timestamp"))
    if entry is None or logged_risk is None or logged_risk <= 0 or signal_time is None:
        return {"status": "MISSING_CONTEXT", "realistic_r": None}
    risk = logged_risk * risk_scale
    stop = _decimal_or_none_any(item.get("stop_loss")) if use_logged_target else entry + risk
    if target_override is not None:
        target = target_override
    elif use_logged_target:
        target = _decimal_or_none_any(item.get("take_profit"))
    else:
        target = entry - (risk * target_rr) if target_rr is not None else None
    if stop is None or target is None:
        return {"status": "MISSING_CONTEXT", "realistic_r": None}
    if target <= 0 or target >= entry or stop <= entry:
        return {
            "status": "INVALID_TARGET_GEOMETRY",
            "realistic_r": None,
            "entry": entry,
            "stop": stop,
            "target": target,
            "risk": risk,
        }
    if prepared_future_4h is None:
        ordered = sorted(candles, key=lambda candle: candle.open_time)
        open_times = [candle.open_time for candle in ordered]
        future = [
            candle
            for candle in ordered[bisect_left(open_times, signal_time):]
            if candle.close_time <= signal_time + timedelta(hours=4)
        ]
    else:
        future = prepared_future_4h
    if not future:
        return {"status": "MISSING_CONTEXT", "realistic_r": None}
    protected = False
    mfe = Decimal("0")
    mae = Decimal("0")
    for candle in future:
        active_stop = entry if protected else stop
        tp_hit = candle.low <= target
        sl_hit = candle.high >= active_stop
        mfe = max(mfe, (entry - candle.low) / risk)
        mae = min(mae, (entry - candle.high) / risk)
        if tp_hit or sl_hit:
            if tp_hit and sl_hit:
                status = "BOTH_HIT_SAME_CANDLE"
                exit_reference = active_stop
                ideal_r = Decimal("0") if not protected else Decimal("0")
                conservative_status = "SL_HIT_CONSERVATIVE"
            elif tp_hit:
                status = "TP_HIT"
                exit_reference = target
                ideal_r = (entry - target) / risk
                conservative_status = None
            elif protected:
                status = "BREAKEVEN_PROTECTED"
                exit_reference = entry
                ideal_r = Decimal("0")
                conservative_status = None
            else:
                status = "SL_HIT"
                exit_reference = stop
                ideal_r = Decimal("-1")
                conservative_status = None
            realistic = _realistic_result_fields(
                item,
                entry=entry,
                exit_reference=exit_reference,
                risk=risk,
                direction="SHORT",
                ideal_status=status,
                ideal_r=ideal_r,
                conservative_status=conservative_status,
            )
            return {
                "status": status,
                "result_time_utc": candle.close_time,
                "ideal_r": ideal_r,
                "realistic_r": realistic.get("realistic_realized_r"),
                "entry": entry,
                "stop": stop,
                "target": target,
                "risk": risk,
                "mfe_r": mfe,
                "mae_r": mae,
            }
        if protect_at_r is not None and not protected and candle.low <= entry - (risk * protect_at_r):
            protected = True
    last = future[-1]
    if (
        require_complete_horizon_for_neither
        and last.close_time < signal_time + timedelta(hours=4) - timedelta(milliseconds=1)
    ):
        return {
            "status": "WAITING_4H",
            "result_time_utc": last.close_time,
            "ideal_r": None,
            "realistic_r": None,
            "entry": entry,
            "stop": stop,
            "target": target,
            "risk": risk,
            "mfe_r": mfe,
            "mae_r": mae,
        }
    ideal_r = (entry - last.close) / risk
    realistic = _realistic_result_fields(
        item,
        entry=entry,
        exit_reference=last.close,
        risk=risk,
        direction="SHORT",
        ideal_status="NEITHER_4H",
        ideal_r=ideal_r,
        realized=False,
    )
    return {
        "status": "NEITHER_4H",
        "result_time_utc": last.close_time,
        "ideal_r": ideal_r,
        "realistic_r": realistic.get("realistic_unrealized_r"),
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "mfe_r": mfe,
        "mae_r": mae,
    }


def _lab54_support_target_results(
    item: dict[str, Any],
    *,
    support_price: Decimal | None,
    prepared_future_4h: list[PerfCandle],
) -> dict[str, dict[str, Any]]:
    entry = _decimal_or_none_any(item.get("entry"))
    risk = _decimal_or_none_any(item.get("risk"))
    if entry is None or risk is None or risk <= 0:
        return {}

    logged_target = _decimal_or_none_any(item.get("take_profit"))
    fixed_target = entry - (risk * Decimal("0.75"))
    impact_pct = _realistic_price_impact_pct(item)
    support_buffer = support_price * impact_pct if support_price is not None and impact_pct is not None else None
    buffered_target = support_price + support_buffer if support_price is not None and support_buffer is not None else None
    target_by_config = {
        "CONTROL_LOGGED": logged_target,
        "TP_0_75R": fixed_target,
        "SUPPORT_TOUCH": support_price,
        "SUPPORT_COST_BUFFER": buffered_target,
    }
    results: dict[str, dict[str, Any]] = {}
    for config_id, _label, method in LAB54_TARGET_SPECS:
        target = target_by_config.get(config_id)
        if target is None:
            results[config_id] = {
                "status": "MISSING_CONTEXT",
                "realistic_r": None,
                "target": None,
                "target_rr": None,
                "target_method": method,
                "support_buffer_price": support_buffer,
            }
            continue
        result = _mid_short_counterfactual_exit(
            item,
            candles=[],
            risk_scale=Decimal("1"),
            target_rr=None,
            protect_at_r=None,
            use_logged_target=True,
            prepared_future_4h=prepared_future_4h,
            target_override=target,
            require_complete_horizon_for_neither=True,
        )
        results[config_id] = {
            **result,
            "target_rr": (entry - target) / risk if target < entry else None,
            "target_method": method,
            "support_buffer_price": support_buffer if config_id == "SUPPORT_COST_BUFFER" else None,
        }
    return results


LAB52_METRICS = (
    ("atr_pct_entry", "ATR 1h / entry %"),
    ("logged_risk_atr_ratio", "Logged risk / ATR 1h"),
    ("atr_vs_30_median", "ATR / median 30 ATR"),
    ("atr_signal_inflation_ratio", "ATR signal / prior ATR"),
    ("signal_true_range_atr", "Signal true range / ATR"),
    ("pre_entry_1h_move_atr", "Pre-entry 1h move / ATR"),
    ("pre_entry_4h_move_atr", "Pre-entry 4h move / ATR"),
    ("support_distance_r", "Nearest support distance R"),
    ("forward_1h_realized_range_atr", "Forward 1h realized range / ATR"),
    ("forward_1h_taker_sell_ratio", "Forward 1h taker sell ratio"),
    ("taker_sell_delta_1h", "Forward vs entry taker-sell delta"),
    ("forward_1h_volume_vs_pre30", "Forward 1h volume / 30-candle baseline"),
    ("forward_1h_oi_change_pct", "Forward 1h OI change %"),
    ("mfe_before_first_hit_r", "MFE before first hit R"),
    ("first_hit_candle_index", "First hit candle index"),
)


def _mid_short_target_distance_study(
    items: list[dict[str, Any]],
    *,
    min_sample: int,
) -> dict[str, Any]:
    closed = [item for item in items if item.get("result_status") in COMPLETED_OUTCOMES]
    target_items = [item for item in closed if item.get("failure_primary_cause") == "TARGET_TOO_FAR"]
    tp_control = [item for item in closed if item.get("result_status") == "TP_HIT"]
    other_sl = [
        item
        for item in closed
        if item.get("result_status") == "SL_HIT" and item.get("failure_primary_cause") != "TARGET_TOO_FAR"
    ]
    thresholds = _lab52_data_derived_thresholds(tp_control)
    hypothesis_counter: Counter[str] = Counter()
    multi_counter: Counter[str] = Counter()
    for item in target_items:
        flags = _lab52_hypothesis_flags(item, thresholds=thresholds)
        primary = _lab52_primary_hypothesis(flags)
        item["target_distance_hypotheses"] = flags
        item["target_distance_primary_hypothesis"] = primary
        hypothesis_counter[primary] += 1
        multi_counter.update(flags)

    metric_rows = [
        _lab52_metric_comparison_row(
            field=field,
            label=label,
            target_items=target_items,
            tp_items=tp_control,
            other_sl_items=other_sl,
        )
        for field, label in LAB52_METRICS
    ]
    config_rows = _lab52_counterfactual_rows(closed, target_items=target_items, min_sample=min_sample)
    dominant = hypothesis_counter.most_common(1)[0] if hypothesis_counter else ("NO_TARGET_TOO_FAR_SAMPLE", 0)
    case_rows = [
        _lab52_case_row(item)
        for item in sorted(
            target_items,
            key=lambda row: (_parse_dt(row.get("signal_timestamp")) or datetime.min, str(row.get("symbol") or "")),
            reverse=True,
        )
    ]
    return {
        "study_id": "LAB_52_TARGET_TOO_FAR_DECOMPOSITION",
        "read_only": True,
        "method": (
            "Entry diagnostics use only closed candles and OI known at or before the signal. "
            "Post-entry range, taker, volume, OI, and level timing are outcome diagnostics only."
        ),
        "summary": {
            "target_too_far_count": len(target_items),
            "tp_control_count": len(tp_control),
            "other_sl_count": len(other_sl),
            "unique_symbol_count": len({str(item.get('symbol') or '') for item in target_items}),
            "dominant_hypothesis": dominant[0],
            "dominant_hypothesis_count": dominant[1],
            "dominant_hypothesis_share_pct": (
                Decimal(dominant[1]) / Decimal(len(target_items)) * Decimal("100") if target_items else None
            ),
            "complete_context_count": sum(
                1 for item in target_items if item.get("target_distance_context_status") == "CONTEXT_COMPLETE"
            ),
            "verdict": _lab52_study_verdict(
                target_count=len(target_items),
                dominant_count=dominant[1],
                counterfactual_rows=config_rows,
                min_sample=min_sample,
            ),
        },
        "data_derived_thresholds": thresholds,
        "hypothesis_rows": [
            {
                "hypothesis": hypothesis,
                "primary_count": count,
                "primary_share_pct": Decimal(count) / Decimal(len(target_items)) * Decimal("100") if target_items else None,
                "multi_label_count": multi_counter.get(hypothesis, 0),
                "multi_label_share_pct": (
                    Decimal(multi_counter.get(hypothesis, 0)) / Decimal(len(target_items)) * Decimal("100")
                    if target_items
                    else None
                ),
                "read": _lab52_hypothesis_read(hypothesis),
            }
            for hypothesis, count in hypothesis_counter.most_common()
        ],
        "metric_comparison_rows": metric_rows,
        "counterfactual_rows": config_rows,
        "case_rows": case_rows,
        "limitations": [
            "Threshold diagnostic berasal dari kuartil TP control pada cohort yang sama; bukan threshold live baru.",
            "Counterfactual memakai cohort signal yang tetap dan horizon 4h; position lock tidak dihitung ulang.",
            "Candle OHLC tidak dapat menentukan urutan intrabar saat target dan stop tersentuh pada candle yang sama, sehingga stop dipilih konservatif.",
            "Support adalah proxy swing-low 1h, bukan order-book liquidity wall.",
            "Forward taker, volume, OI, dan realized range tidak boleh dipakai sebagai input entry karena baru diketahui setelah signal.",
        ],
    }


def _mid_short_structure_clearance_shadow_study(
    items: list[dict[str, Any]],
    *,
    min_sample: int,
) -> dict[str, Any]:
    for item in items:
        status, clearance = _lab53_structure_clearance_status(item)
        item["structure_clearance_status"] = status
        item["support_clearance_to_target_r"] = clearance

    ordered, train, validation, validation_cutoff = _lab53_chronological_split(items)
    available = [item for item in ordered if item.get("structure_clearance_status") != "STRUCTURE_UNAVAILABLE"]
    train_available = [item for item in train if item.get("structure_clearance_status") != "STRUCTURE_UNAVAILABLE"]
    validation_available = [
        item for item in validation if item.get("structure_clearance_status") != "STRUCTURE_UNAVAILABLE"
    ]
    baselines = {
        "all": _walk_forward_perf(available),
        "train": _walk_forward_perf(train_available),
        "validation": _walk_forward_perf(validation_available),
    }
    status_rows = [
        _lab53_structure_status_row(
            status,
            ordered=ordered,
            train=train,
            validation=validation,
            baselines=baselines,
        )
        for status in ("STRUCTURE_CLEAR", "STRUCTURE_BLOCKED", "STRUCTURE_UNAVAILABLE")
    ]
    row_by_status = {row["status"]: row for row in status_rows}
    clear_row = row_by_status["STRUCTURE_CLEAR"]
    blocked_row = row_by_status["STRUCTURE_BLOCKED"]
    verdict = _lab53_structure_clearance_verdict(
        clear=clear_row,
        blocked=blocked_row,
        min_sample=min_sample,
    )
    blocked_items = [item for item in ordered if item.get("structure_clearance_status") == "STRUCTURE_BLOCKED"]
    return {
        "study_id": "LAB_53_STRUCTURE_CLEARANCE_SHADOW",
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
        "method": (
            "Nearest confirmed 1h swing low is computed from the latest 24 futures 1h candles closed at or before "
            "the signal. A period-low fallback is used when no confirmed swing exists. No future candle is read."
        ),
        "definition": {
            "structure_clear": "support_1h <= target OR support_1h >= entry",
            "structure_blocked": "target < support_1h < entry for MID_SHORT",
            "structure_unavailable": "entry, target, risk, or closed 1h support context is missing",
            "live_effect": "none; classification is shadow-only",
        },
        "summary": {
            "source_count": len(ordered),
            "context_available_count": len(available),
            "structure_clear_count": sum(
                1 for item in ordered if item.get("structure_clearance_status") == "STRUCTURE_CLEAR"
            ),
            "structure_blocked_count": len(blocked_items),
            "structure_unavailable_count": sum(
                1 for item in ordered if item.get("structure_clearance_status") == "STRUCTURE_UNAVAILABLE"
            ),
            "clear_validation_closed_count": int(clear_row["validation"].get("closed_count") or 0),
            "blocked_validation_closed_count": int(blocked_row["validation"].get("closed_count") or 0),
            "validation_cutoff_utc": validation_cutoff,
            "verdict": verdict,
            "recommended_action": _lab53_recommended_action(verdict),
        },
        "baseline": baselines,
        "status_rows": status_rows,
        "exit_variant_rows": _lab53_structure_exit_variant_rows(
            ordered=ordered,
            train=train,
            validation=validation,
            min_sample=min_sample,
        ),
        "blocked_case_rows": [
            _lab53_structure_case_row(item)
            for item in sorted(
                blocked_items,
                key=lambda row: (
                    _parse_dt(row.get("signal_timestamp")) or datetime.min,
                    str(row.get("symbol") or ""),
                ),
                reverse=True,
            )
        ],
        "limitations": [
            "Support is a candle-structure proxy, not visible resting liquidity or an order-book wall.",
            "The period-low fallback is reported separately because it is weaker evidence than a confirmed swing low.",
            "Train and validation use one chronological split; promotion requires additional forward checkpoints.",
            "Exit variants keep the signal cohort fixed and do not model a new position-lock sequence.",
            "No structure status changes Signal Factory, scanner output, TP/SL, or execution.",
        ],
    }


def _lab53_structure_clearance_status(item: dict[str, Any]) -> tuple[str, Decimal | None]:
    entry = _decimal_or_none_any(item.get("entry"))
    target = _decimal_or_none_any(item.get("take_profit"))
    risk = _decimal_or_none_any(item.get("risk"))
    support = _decimal_or_none_any(item.get("support_price_proxy"))
    if entry is None or target is None or risk is None or risk <= 0 or support is None:
        return "STRUCTURE_UNAVAILABLE", None
    clearance_to_target_r = (support - target) / risk
    if target < support < entry:
        return "STRUCTURE_BLOCKED", clearance_to_target_r
    return "STRUCTURE_CLEAR", clearance_to_target_r


def _lab53_chronological_split(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], datetime | None]:
    ordered = sorted(
        items,
        key=lambda item: (
            _parse_dt(item.get("signal_timestamp")) or datetime.min,
            str(item.get("symbol") or ""),
        ),
    )
    if len(ordered) < 2:
        return ordered, ordered, [], None
    split_index = max(1, min(len(ordered) - 1, int(len(ordered) * 0.70)))
    cutoff = _parse_dt(ordered[split_index].get("signal_timestamp"))
    if cutoff is None:
        return ordered, ordered[:split_index], ordered[split_index:], None
    train = [item for item in ordered if (_parse_dt(item.get("signal_timestamp")) or datetime.min) < cutoff]
    validation = [item for item in ordered if (_parse_dt(item.get("signal_timestamp")) or datetime.min) >= cutoff]
    if not train or not validation:
        train = ordered[:split_index]
        validation = ordered[split_index:]
        cutoff = _parse_dt(validation[0].get("signal_timestamp")) if validation else None
    return ordered, train, validation, cutoff


def _lab53_structure_status_row(
    status: str,
    *,
    ordered: list[dict[str, Any]],
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    baselines: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    all_items = [item for item in ordered if item.get("structure_clearance_status") == status]
    train_items = [item for item in train if item.get("structure_clearance_status") == status]
    validation_items = [item for item in validation if item.get("structure_clearance_status") == status]
    comparable = status != "STRUCTURE_UNAVAILABLE"
    return {
        "status": status,
        "sample_retention_pct": _retention(len(all_items), len(ordered)),
        "all": _walk_forward_perf(all_items, baseline=baselines["all"]) if comparable else _walk_forward_perf(all_items),
        "train": (
            _walk_forward_perf(train_items, baseline=baselines["train"])
            if comparable
            else _walk_forward_perf(train_items)
        ),
        "validation": (
            _walk_forward_perf(validation_items, baseline=baselines["validation"])
            if comparable
            else _walk_forward_perf(validation_items)
        ),
        "read": _lab53_structure_status_read(status),
    }


def _lab53_structure_clearance_verdict(
    *,
    clear: dict[str, Any],
    blocked: dict[str, Any],
    min_sample: int,
) -> str:
    clear_validation = clear["validation"]
    blocked_validation = blocked["validation"]
    required_clear = max(10, min_sample // 2)
    if (
        int(clear_validation.get("closed_count") or 0) < required_clear
        or int(blocked_validation.get("closed_count") or 0) < 5
    ):
        return "STRUCTURE_CLEARANCE_NEEDS_MORE_SAMPLE"
    clear_avg = _decimal_or_none_any(clear_validation.get("realistic_avg_r_closed"))
    blocked_avg = _decimal_or_none_any(blocked_validation.get("realistic_avg_r_closed"))
    avg_delta = _decimal_or_none_any(clear_validation.get("realistic_avg_r_delta_vs_baseline"))
    sl_delta = _decimal_or_none_any(clear_validation.get("sl_share_delta_vs_baseline"))
    drawdown_delta = _decimal_or_none_any(clear_validation.get("max_drawdown_delta_vs_baseline"))
    if (
        clear_avg is not None
        and blocked_avg is not None
        and clear_avg > blocked_avg
        and Decimal(clear_validation.get("realistic_total_r_closed") or 0) > 0
        and (avg_delta is None or avg_delta > 0)
        and (sl_delta is None or sl_delta <= 0)
        and (drawdown_delta is None or drawdown_delta >= 0)
    ):
        return "STRUCTURE_CLEARANCE_VALIDATION_IMPROVES"
    if (avg_delta is not None and avg_delta > 0) or (sl_delta is not None and sl_delta < 0):
        return "STRUCTURE_CLEARANCE_REDUCES_DAMAGE_MONITOR"
    return "STRUCTURE_CLEARANCE_NO_CLEAR_EDGE"


def _lab53_structure_exit_variant_rows(
    *,
    ordered: list[dict[str, Any]],
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    min_sample: int,
) -> list[dict[str, Any]]:
    clear_all = [item for item in ordered if item.get("structure_clearance_status") == "STRUCTURE_CLEAR"]
    clear_train = [item for item in train if item.get("structure_clearance_status") == "STRUCTURE_CLEAR"]
    clear_validation = [
        item for item in validation if item.get("structure_clearance_status") == "STRUCTURE_CLEAR"
    ]
    blocked_validation = [
        item for item in validation if item.get("structure_clearance_status") == "STRUCTURE_BLOCKED"
    ]
    control_train = _lab52_counterfactual_performance(clear_train, "CONTROL_LOGGED")
    control_validation = _lab52_counterfactual_performance(clear_validation, "CONTROL_LOGGED")
    rows: list[dict[str, Any]] = []
    for config_id, label, risk_scale, target_rr, protect_at_r, use_logged_target in LAB52_COUNTERFACTUAL_SPECS:
        all_perf = _lab52_counterfactual_performance(clear_all, config_id)
        train_perf = _lab52_counterfactual_performance(clear_train, config_id)
        validation_perf = _lab52_counterfactual_performance(clear_validation, config_id)
        blocked_validation_perf = _lab52_counterfactual_performance(blocked_validation, config_id)
        rows.append(
            {
                "config_id": config_id,
                "label": label,
                "risk_scale": risk_scale,
                "target_rr": target_rr,
                "protect_at_r": protect_at_r,
                "use_logged_target": use_logged_target,
                "clear_all": all_perf,
                "clear_train": train_perf,
                "clear_validation": validation_perf,
                "blocked_validation": blocked_validation_perf,
                "clear_validation_avg_delta_vs_logged": _decimal_delta(
                    validation_perf.get("avg_realistic_r"),
                    control_validation.get("avg_realistic_r"),
                ),
                "clear_validation_avg_delta_vs_blocked": _decimal_delta(
                    validation_perf.get("avg_realistic_r"),
                    blocked_validation_perf.get("avg_realistic_r"),
                ),
                "verdict": _lab53_structure_exit_verdict(
                    config_id=config_id,
                    train=train_perf,
                    validation=validation_perf,
                    control_train=control_train,
                    control_validation=control_validation,
                    min_sample=min_sample,
                ),
            }
        )
    return rows


def _lab53_structure_exit_verdict(
    *,
    config_id: str,
    train: dict[str, Any],
    validation: dict[str, Any],
    control_train: dict[str, Any],
    control_validation: dict[str, Any],
    min_sample: int,
) -> str:
    if config_id == "CONTROL_LOGGED":
        return "CURRENT_CONTROL"
    if int(validation.get("sample_count") or 0) < max(10, min_sample // 2):
        return "NEEDS_MORE_SAMPLE"
    validation_delta = _decimal_delta(validation.get("avg_realistic_r"), control_validation.get("avg_realistic_r"))
    train_delta = _decimal_delta(train.get("avg_realistic_r"), control_train.get("avg_realistic_r"))
    if (
        validation_delta is not None
        and validation_delta > 0
        and train_delta is not None
        and train_delta > 0
        and Decimal(validation.get("total_realistic_r") or 0) > 0
    ):
        return "VALIDATION_IMPROVES_FIXED_COHORT"
    if validation_delta is not None and validation_delta > 0:
        return "EXIT_GEOMETRY_IMPROVES_FIXED_COHORT_MONITOR"
    if train_delta is not None and train_delta > 0:
        return "TRAIN_ONLY_IMPROVEMENT"
    return "NO_CLEAR_IMPROVEMENT"


def _lab53_structure_case_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": item.get("signal_id"),
        "symbol": item.get("symbol"),
        "signal_timestamp": item.get("signal_timestamp"),
        "signal_time_wib": item.get("signal_time_wib"),
        "entry": item.get("entry"),
        "stop_loss": item.get("stop_loss"),
        "take_profit": item.get("take_profit"),
        "rr": item.get("rr"),
        "support_price_proxy": item.get("support_price_proxy"),
        "support_distance_r": item.get("support_distance_r"),
        "support_clearance_to_target_r": item.get("support_clearance_to_target_r"),
        "support_method": item.get("support_method"),
        "result_status": item.get("result_status"),
        "realistic_r": (
            item.get("realistic_realized_r")
            if item.get("result_status") in COMPLETED_OUTCOMES
            else item.get("realistic_unrealized_r")
        ),
        "failure_primary_cause": item.get("failure_primary_cause"),
    }


def _lab53_structure_status_read(status: str) -> str:
    return {
        "STRUCTURE_CLEAR": "Support proxy tidak berada di antara entry dan target.",
        "STRUCTURE_BLOCKED": "Support proxy 1h berada di jalur entry menuju target short.",
        "STRUCTURE_UNAVAILABLE": "Candle 1h closed belum cukup untuk membentuk proxy support.",
    }.get(status, "Status structure belum dikenal.")


def _lab53_recommended_action(verdict: str) -> str:
    return {
        "STRUCTURE_CLEARANCE_VALIDATION_IMPROVES": (
            "Continue at least one more forward checkpoint; do not promote to a live rule yet."
        ),
        "STRUCTURE_CLEARANCE_REDUCES_DAMAGE_MONITOR": (
            "Monitor more samples; validation reduces some damage but is not independently positive."
        ),
        "STRUCTURE_CLEARANCE_NEEDS_MORE_SAMPLE": (
            "Collect more blocked and clear validation samples before judging the filter."
        ),
        "STRUCTURE_CLEARANCE_NO_CLEAR_EDGE": (
            "Do not promote the structure filter; current validation does not improve the baseline."
        ),
    }.get(verdict, "Keep the current live rule frozen.")


def _mid_short_support_target_shadow_study(
    items: list[dict[str, Any]],
    *,
    min_sample: int,
) -> dict[str, Any]:
    ordered, train, validation, validation_cutoff = _lab53_chronological_split(items)
    blocked = [item for item in ordered if item.get("structure_clearance_status") == "STRUCTURE_BLOCKED"]
    blocked_train = [item for item in train if item.get("structure_clearance_status") == "STRUCTURE_BLOCKED"]
    blocked_validation = [
        item for item in validation if item.get("structure_clearance_status") == "STRUCTURE_BLOCKED"
    ]
    control = {
        "all": _lab54_target_performance(blocked, "CONTROL_LOGGED"),
        "train": _lab54_target_performance(blocked_train, "CONTROL_LOGGED"),
        "validation": _lab54_target_performance(blocked_validation, "CONTROL_LOGGED"),
    }
    variant_rows = [
        _lab54_target_variant_row(
            config_id=config_id,
            label=label,
            target_method=target_method,
            blocked=blocked,
            blocked_train=blocked_train,
            blocked_validation=blocked_validation,
            control=control,
            min_sample=min_sample,
        )
        for config_id, label, target_method in LAB54_TARGET_SPECS
    ]
    support_rows = [row for row in variant_rows if row["config_id"] in LAB54_SUPPORT_CONFIG_IDS]
    comparable_support_rows = [
        row
        for row in support_rows
        if row["validation"].get("avg_realistic_r") is not None
    ]
    best_support_row = (
        max(
            comparable_support_rows,
            key=lambda row: Decimal(row["validation"]["avg_realistic_r"]),
        )
        if comparable_support_rows
        else None
    )
    verdict = _lab54_support_target_verdict(
        best_support_row,
        min_sample=min_sample,
    )
    return {
        "study_id": "LAB_54_STRUCTURE_AWARE_TARGET_SHADOW",
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
        "evaluation_horizon": "4h closed futures path",
        "method": (
            "Only STRUCTURE_BLOCKED MID_SHORT 1h rows are evaluated. SUPPORT_TOUCH uses the nearest 1h "
            "support formed by candles closed at signal time. SUPPORT_COST_BUFFER places the reference target "
            "above support by one modeled exit-impact unit: half futures spread plus one-side slippage."
        ),
        "target_definitions": {
            "CONTROL_LOGGED": "Logged target and logged stop.",
            "TP_0_75R": "Fixed 0.75R target with the logged stop.",
            "SUPPORT_TOUCH": "Target reference equals the nearest closed 1h support proxy.",
            "SUPPORT_COST_BUFFER": (
                "target = support * (1 + ((futures_spread_pct / 2 + slippage_pct_per_side) / 100))"
            ),
            "waiting_rule": "No-hit rows remain WAITING_4H until the full four-hour path is closed.",
        },
        "summary": {
            "source_count": len(ordered),
            "structure_blocked_count": len(blocked),
            "blocked_train_count": len(blocked_train),
            "blocked_validation_count": len(blocked_validation),
            "validation_cutoff_utc": validation_cutoff,
            "control_validation_evaluated_count": control["validation"]["evaluated_count"],
            "control_validation_waiting_count": control["validation"]["waiting_count"],
            "best_validation_config_id": best_support_row.get("config_id") if best_support_row else None,
            "best_validation_avg_realistic_r": (
                best_support_row["validation"].get("avg_realistic_r") if best_support_row else None
            ),
            "best_validation_total_realistic_r": (
                best_support_row["validation"].get("total_realistic_r") if best_support_row else None
            ),
            "verdict": verdict,
            "recommended_action": _lab54_recommended_action(verdict),
        },
        "control": control,
        "variant_rows": variant_rows,
        "case_rows": [
            _lab54_support_target_case_row(item)
            for item in sorted(
                blocked,
                key=lambda row: (
                    _parse_dt(row.get("signal_timestamp")) or datetime.min,
                    str(row.get("symbol") or ""),
                ),
                reverse=True,
            )
        ],
        "limitations": [
            "Nearest support is a closed-candle proxy, not an order-book liquidity wall.",
            "The cost buffer uses the existing realistic spread/slippage model; it is not an optimized threshold.",
            "TP/SL and same-candle ambiguity use the same conservative path rules as the existing paper study.",
            "A TP or SL hit is final even before four hours; unresolved rows require the full closed 4h horizon.",
            "The chronological split is one checkpoint and must not be promoted without further forward validation.",
            "No target variant changes Signal Factory, scanner output, logged TP/SL, or execution.",
        ],
    }


def _lab54_target_variant_row(
    *,
    config_id: str,
    label: str,
    target_method: str,
    blocked: list[dict[str, Any]],
    blocked_train: list[dict[str, Any]],
    blocked_validation: list[dict[str, Any]],
    control: dict[str, dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    all_perf = _lab54_target_performance(blocked, config_id)
    train_perf = _lab54_target_performance(blocked_train, config_id)
    validation_perf = _lab54_target_performance(blocked_validation, config_id)
    validation_avg_delta = _decimal_delta(
        validation_perf.get("avg_realistic_r"),
        control["validation"].get("avg_realistic_r"),
    )
    train_avg_delta = _decimal_delta(
        train_perf.get("avg_realistic_r"),
        control["train"].get("avg_realistic_r"),
    )
    validation_drawdown_delta = _decimal_delta(
        validation_perf.get("max_drawdown_r"),
        control["validation"].get("max_drawdown_r"),
    )
    return {
        "config_id": config_id,
        "label": label,
        "target_method": target_method,
        "all": all_perf,
        "train": train_perf,
        "validation": validation_perf,
        "train_avg_r_delta_vs_control": train_avg_delta,
        "validation_avg_r_delta_vs_control": validation_avg_delta,
        "validation_total_r_delta_vs_control": _decimal_delta(
            validation_perf.get("total_realistic_r"),
            control["validation"].get("total_realistic_r"),
        ),
        "validation_drawdown_delta_vs_control": validation_drawdown_delta,
        "validation_sl_share_delta_vs_control": _decimal_delta(
            validation_perf.get("sl_share_pct_closed"),
            control["validation"].get("sl_share_pct_closed"),
        ),
        "verdict": _lab54_target_variant_verdict(
            config_id=config_id,
            train=train_perf,
            validation=validation_perf,
            control_train=control["train"],
            control_validation=control["validation"],
            min_sample=min_sample,
        ),
    }


def _lab54_target_performance(items: list[dict[str, Any]], config_id: str) -> dict[str, Any]:
    ordered = sorted(
        items,
        key=lambda item: (
            _parse_dt(item.get("signal_timestamp")) or datetime.min,
            str(item.get("symbol") or ""),
        ),
    )
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    status_counts: Counter[str] = Counter()
    missing_count = 0
    for item in ordered:
        configs = item.get("_lab54_support_targets")
        result = configs.get(config_id) if isinstance(configs, dict) else None
        if not isinstance(result, dict):
            missing_count += 1
            continue
        status = str(result.get("status") or "MISSING_CONTEXT")
        status_counts[status] += 1
        if status in {"MISSING_CONTEXT", "INVALID_TARGET_GEOMETRY"}:
            missing_count += 1
        if result.get("realistic_r") is not None:
            rows.append((item, result))
    values = [Decimal(result["realistic_r"]) for _item, result in rows]
    target_rr_values = [
        Decimal(result["target_rr"])
        for _item, result in rows
        if result.get("target_rr") is not None
    ]
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    symbol_counts = Counter(str(item.get("symbol") or "") for item, _result in rows)
    top_symbol, top_count = symbol_counts.most_common(1)[0] if symbol_counts else (None, 0)
    closed_count = (
        status_counts.get("TP_HIT", 0)
        + status_counts.get("SL_HIT", 0)
        + status_counts.get("BOTH_HIT_SAME_CANDLE", 0)
        + status_counts.get("BREAKEVEN_PROTECTED", 0)
    )
    return {
        "source_count": len(ordered),
        "evaluated_count": len(rows),
        "waiting_count": status_counts.get("WAITING_4H", 0),
        "missing_count": missing_count,
        "closed_count": closed_count,
        "tp_count": status_counts.get("TP_HIT", 0),
        "sl_count": status_counts.get("SL_HIT", 0),
        "both_count": status_counts.get("BOTH_HIT_SAME_CANDLE", 0),
        "breakeven_count": status_counts.get("BREAKEVEN_PROTECTED", 0),
        "neither_count": status_counts.get("NEITHER_4H", 0),
        "total_realistic_r": sum(values, Decimal("0")),
        "avg_realistic_r": _avg_decimal(values),
        "median_realistic_r": _percentile_decimal(values, Decimal("0.50")),
        "max_drawdown_r": max_drawdown,
        "tp_share_pct_closed": (
            Decimal(status_counts.get("TP_HIT", 0)) / Decimal(closed_count) * Decimal("100")
            if closed_count
            else None
        ),
        "sl_share_pct_closed": (
            Decimal(status_counts.get("SL_HIT", 0) + status_counts.get("BOTH_HIT_SAME_CANDLE", 0))
            / Decimal(closed_count)
            * Decimal("100")
            if closed_count
            else None
        ),
        "target_rr_q1": _percentile_decimal(target_rr_values, Decimal("0.25")),
        "target_rr_median": _percentile_decimal(target_rr_values, Decimal("0.50")),
        "target_rr_q3": _percentile_decimal(target_rr_values, Decimal("0.75")),
        "top_symbol": top_symbol,
        "top_symbol_count": top_count,
        "top_symbol_share_pct": Decimal(top_count) / Decimal(len(rows)) * Decimal("100") if rows else None,
    }


def _lab54_target_variant_verdict(
    *,
    config_id: str,
    train: dict[str, Any],
    validation: dict[str, Any],
    control_train: dict[str, Any],
    control_validation: dict[str, Any],
    min_sample: int,
) -> str:
    if config_id == "CONTROL_LOGGED":
        return "CURRENT_CONTROL"
    if config_id == "TP_0_75R":
        return "FIXED_TARGET_REFERENCE"
    required_validation = max(10, min_sample // 2)
    if (
        int(validation.get("evaluated_count") or 0) < required_validation
        or int(train.get("evaluated_count") or 0) < max(10, min_sample)
    ):
        return "NEEDS_MORE_SAMPLE"
    validation_delta = _decimal_delta(
        validation.get("avg_realistic_r"),
        control_validation.get("avg_realistic_r"),
    )
    train_delta = _decimal_delta(
        train.get("avg_realistic_r"),
        control_train.get("avg_realistic_r"),
    )
    drawdown_delta = _decimal_delta(
        validation.get("max_drawdown_r"),
        control_validation.get("max_drawdown_r"),
    )
    if (
        validation_delta is not None
        and validation_delta > 0
        and train_delta is not None
        and train_delta > 0
        and Decimal(validation.get("total_realistic_r") or 0) > 0
        and (drawdown_delta is None or drawdown_delta >= 0)
    ):
        return "SUPPORT_TARGET_VALIDATION_IMPROVES"
    if validation_delta is not None and validation_delta > 0:
        return "SUPPORT_TARGET_REDUCES_DAMAGE_ONLY"
    if train_delta is not None and train_delta > 0:
        return "SUPPORT_TARGET_TRAIN_ONLY"
    return "SUPPORT_TARGET_NO_IMPROVEMENT"


def _lab54_support_target_verdict(
    best_support_row: dict[str, Any] | None,
    *,
    min_sample: int,
) -> str:
    if best_support_row is None:
        return "SUPPORT_TARGET_NEEDS_MORE_SAMPLE"
    if int(best_support_row["validation"].get("evaluated_count") or 0) < max(10, min_sample // 2):
        return "SUPPORT_TARGET_NEEDS_MORE_SAMPLE"
    row_verdict = str(best_support_row.get("verdict") or "")
    if row_verdict == "SUPPORT_TARGET_VALIDATION_IMPROVES":
        return "SUPPORT_TARGET_VALIDATION_IMPROVES"
    if row_verdict == "SUPPORT_TARGET_REDUCES_DAMAGE_ONLY":
        return "SUPPORT_TARGET_REDUCES_DAMAGE_ONLY"
    return "SUPPORT_TARGET_NO_IMPROVEMENT"


def _lab54_support_target_case_row(item: dict[str, Any]) -> dict[str, Any]:
    configs = item.get("_lab54_support_targets") if isinstance(item.get("_lab54_support_targets"), dict) else {}

    def result_for(config_id: str) -> dict[str, Any]:
        result = configs.get(config_id) if isinstance(configs.get(config_id), dict) else {}
        return {
            "status": result.get("status") or "MISSING_CONTEXT",
            "target": result.get("target"),
            "target_rr": result.get("target_rr"),
            "realistic_r": result.get("realistic_r"),
            "result_time_utc": result.get("result_time_utc"),
            "mfe_r": result.get("mfe_r"),
            "mae_r": result.get("mae_r"),
            "support_buffer_price": result.get("support_buffer_price"),
        }

    return {
        "signal_id": item.get("signal_id"),
        "symbol": item.get("symbol"),
        "signal_timestamp": item.get("signal_timestamp"),
        "signal_time_wib": item.get("signal_time_wib"),
        "entry": item.get("entry"),
        "stop_loss": item.get("stop_loss"),
        "risk": item.get("risk"),
        "support_price_proxy": item.get("support_price_proxy"),
        "support_method": item.get("support_method"),
        "support_distance_r": item.get("support_distance_r"),
        "control": result_for("CONTROL_LOGGED"),
        "fixed_0_75r": result_for("TP_0_75R"),
        "support_touch": result_for("SUPPORT_TOUCH"),
        "support_cost_buffer": result_for("SUPPORT_COST_BUFFER"),
    }


def _lab54_recommended_action(verdict: str) -> str:
    return {
        "SUPPORT_TARGET_VALIDATION_IMPROVES": (
            "Keep the best support target in shadow for another forward checkpoint; do not change the live TP."
        ),
        "SUPPORT_TARGET_REDUCES_DAMAGE_ONLY": (
            "Monitor more samples; the target reduces damage but is not independently positive."
        ),
        "SUPPORT_TARGET_NEEDS_MORE_SAMPLE": (
            "Wait for more completed four-hour validation paths before judging support-aware targets."
        ),
        "SUPPORT_TARGET_NO_IMPROVEMENT": (
            "Do not promote support-aware targets; continue the wrong-direction and entry-timing investigation."
        ),
    }.get(verdict, "Keep the current live target frozen.")


def _mid_short_entry_confirmation_shadow_study(
    items: list[dict[str, Any]],
    *,
    candles: dict[str, list[PerfCandle]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    ordered, train, validation, validation_cutoff = _lab53_chronological_split(items)
    train_keys = {_lab55_item_key(item) for item in train}
    validation_keys = {_lab55_item_key(item) for item in validation}
    results_by_config: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for config_id, _label, _definition in LAB55_CONFIRMATION_SPECS:
        results_by_config[config_id] = {
            _lab55_item_key(item): _lab55_evaluate_confirmation_config(
                item,
                candles=candles.get(str(item.get("symbol") or ""), []),
                config_id=config_id,
            )
            for item in ordered
        }

    def pairs_for(config_id: str, keys: set[tuple[str, str]] | None = None) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        output: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for item in ordered:
            key = _lab55_item_key(item)
            if keys is not None and key not in keys:
                continue
            output.append((item, results_by_config[config_id][key]))
        return output

    control_id = "CONTROL_IMMEDIATE"
    control_pairs = {
        "all": pairs_for(control_id),
        "train": pairs_for(control_id, train_keys),
        "validation": pairs_for(control_id, validation_keys),
    }
    control = {split: _lab55_confirmation_performance(rows) for split, rows in control_pairs.items()}
    variant_rows: list[dict[str, Any]] = []
    for config_id, label, definition in LAB55_CONFIRMATION_SPECS:
        split_pairs = {
            "all": pairs_for(config_id),
            "train": pairs_for(config_id, train_keys),
            "validation": pairs_for(config_id, validation_keys),
        }
        perf = {split: _lab55_confirmation_performance(rows) for split, rows in split_pairs.items()}
        tradeoff = {
            split: _lab55_confirmation_tradeoff(control_pairs[split], rows)
            for split, rows in split_pairs.items()
        }
        row = {
            "config_id": config_id,
            "label": label,
            "definition": definition,
            **perf,
            "tradeoff_vs_control": tradeoff,
            "train_avg_r_delta_vs_control": _decimal_delta(
                perf["train"].get("avg_realistic_r"),
                control["train"].get("avg_realistic_r"),
            ),
            "validation_avg_r_delta_vs_control": _decimal_delta(
                perf["validation"].get("avg_realistic_r"),
                control["validation"].get("avg_realistic_r"),
            ),
            "validation_total_r_delta_vs_control": _decimal_delta(
                perf["validation"].get("total_realistic_r"),
                control["validation"].get("total_realistic_r"),
            ),
            "validation_drawdown_delta_vs_control": _decimal_delta(
                perf["validation"].get("max_drawdown_r"),
                control["validation"].get("max_drawdown_r"),
            ),
        }
        row["verdict"] = _lab55_confirmation_variant_verdict(
            row,
            control=control,
            min_sample=min_sample,
        )
        variant_rows.append(row)

    comparable = [
        row
        for row in variant_rows
        if row["config_id"] != control_id and row["validation"].get("avg_realistic_r") is not None
    ]
    best = max(comparable, key=lambda row: Decimal(row["validation"]["avg_realistic_r"])) if comparable else None
    control_results = results_by_config[control_id]
    verdict = _lab55_confirmation_study_verdict(best)
    return {
        "study_id": "LAB_55_15M_ENTRY_CONFIRMATION_SHADOW",
        "evaluation_horizon": "4h from each simulated entry using closed futures candles",
        "method": (
            "The source cohort is fixed before any variant is evaluated. Delayed variants wait for the first complete "
            "15m futures candle after the 1h signal, enter at its close, preserve the logged absolute risk and RR, "
            "shift stop/target around the new entry, and evaluate only subsequent candles."
        ),
        "definitions": {
            config_id: definition for config_id, _label, definition in LAB55_CONFIRMATION_SPECS
        },
        "summary": {
            "source_count": len(ordered),
            "train_count": len(train),
            "validation_count": len(validation),
            "validation_cutoff_utc": validation_cutoff,
            "confirmation_available_count": sum(
                1 for result in control_results.values() if result.get("confirmation_time_utc") is not None
            ),
            "immediate_reversal_count": sum(
                1
                for result in control_results.values()
                if _decimal_or_none_any(result.get("confirmation_return_pct")) is not None
                and Decimal(result["confirmation_return_pct"]) >= Decimal("0.05")
            ),
            "direction_confirmed_count": sum(
                1
                for result in control_results.values()
                if _decimal_or_none_any(result.get("confirmation_return_pct")) is not None
                and Decimal(result["confirmation_return_pct"]) < 0
            ),
            "best_validation_config_id": best.get("config_id") if best else None,
            "best_validation_avg_realistic_r": best["validation"].get("avg_realistic_r") if best else None,
            "best_validation_total_realistic_r": best["validation"].get("total_realistic_r") if best else None,
            "best_validation_avoided_sl_count": (
                best["tradeoff_vs_control"]["validation"].get("avoided_sl_count") if best else 0
            ),
            "best_validation_lost_tp_count": (
                best["tradeoff_vs_control"]["validation"].get("lost_tp_count") if best else 0
            ),
            "verdict": verdict,
            "recommended_action": _lab55_confirmation_recommended_action(verdict),
        },
        "control": control,
        "variant_rows": variant_rows,
        "confirmation_bucket_rows": _lab55_confirmation_bucket_rows(
            ordered,
            control_results=control_results,
        ),
        "case_rows": _lab55_confirmation_case_rows(
            ordered,
            results_by_config=results_by_config,
            limit=limit,
        ),
        "limitations": [
            "The +0.05% veto and 52% taker threshold are sensitivity references already used by prior diagnostics, not new live rules.",
            "Waiting changes the entry price; therefore every delayed stop, target, and realistic R is recalculated instead of reusing the logged outcome.",
            "A filtered historical TP is counted as lost even if another later setup might have appeared; this study does not invent replacement entries.",
            "The four-hour horizon is fixed per simulated entry. Unfinished paths remain WAITING_4H and contribute no R.",
            "OHLC cannot resolve intrabar order when stop and target hit in one candle, so the result stays conservative.",
            "One chronological checkpoint is not sufficient to promote a confirmation gate into Signal Factory.",
        ],
    }


LAB56_GATE_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "AVOID_1H_SUPPORT_CONFLICT",
        "Avoid 1h support conflict",
        (
            "AT_1H_RESISTANCE",
            "1H_RESISTANCE_REJECTED",
            "1H_SUPPORT_BREAK",
            "1H_BREAK_RETEST_REJECTED",
            "1H_MID_RANGE",
        ),
    ),
    (
        "SHORT_STRUCTURE_CONFIRMED",
        "Confirmed short structure",
        (
            "1H_RESISTANCE_REJECTED",
            "1H_SUPPORT_BREAK",
            "1H_BREAK_RETEST_REJECTED",
        ),
    ),
    (
        "RESISTANCE_OR_BREAK_CONTEXT",
        "Resistance or broken support context",
        (
            "AT_1H_RESISTANCE",
            "1H_RESISTANCE_REJECTED",
            "1H_SUPPORT_BREAK",
            "1H_BREAK_RETEST_REJECTED",
        ),
    ),
)


def _mid_short_structure_zone_study(
    items: list[dict[str, Any]],
    *,
    one_hour_candles: dict[str, list[PerfCandle]],
    four_hour_candles: dict[str, list[PerfCandle]],
    min_sample: int,
    limit: int,
    selected_signal_id: str | None,
) -> dict[str, Any]:
    one_hour_candles = {
        symbol: sorted(rows, key=lambda candle: candle.close_time)
        for symbol, rows in one_hour_candles.items()
    }
    four_hour_candles = {
        symbol: sorted(rows, key=lambda candle: candle.close_time)
        for symbol, rows in four_hour_candles.items()
    }
    ordered, train, validation, validation_cutoff = _lab53_chronological_split(items)
    split_keys = {
        "all": {_lab55_item_key(item) for item in ordered},
        "train": {_lab55_item_key(item) for item in train},
        "validation": {_lab55_item_key(item) for item in validation},
    }
    by_config: dict[str, list[dict[str, Any]]] = {}
    for config in LAB56_ZONE_CONFIGS:
        enriched: list[dict[str, Any]] = []
        for item in ordered:
            symbol = str(item.get("symbol") or "")
            context = _lab56_structure_context(
                item,
                one_hour_candles=one_hour_candles.get(symbol, []),
                four_hour_candles=four_hour_candles.get(symbol, []),
                config=config,
                include_four_hour_confluence=config.config_id == LAB56_PRIMARY_CONFIG_ID,
            )
            enriched.append({**item, **context})
        by_config[config.config_id] = enriched

    primary_items = by_config[LAB56_PRIMARY_CONFIG_ID]
    primary_split = {
        split: [item for item in primary_items if _lab55_item_key(item) in keys]
        for split, keys in split_keys.items()
    }
    primary_baselines = {split: _walk_forward_perf(rows) for split, rows in primary_split.items()}
    state_names = (
        "AT_1H_SUPPORT",
        "AT_1H_RESISTANCE",
        "1H_RESISTANCE_REJECTED",
        "1H_SUPPORT_BREAK",
        "1H_BREAK_RETEST_REJECTED",
        "1H_FAILED_BREAK_RECLAIM",
        "1H_MID_RANGE",
        "1H_ZONE_UNAVAILABLE",
    )
    state_rows = [
        _lab56_bucket_row(
            state,
            field="structure_state",
            split_items=primary_split,
            baselines=primary_baselines,
        )
        for state in state_names
    ]
    gate_rows = [
        _lab56_gate_row(
            gate_id=gate_id,
            label=label,
            allowed_states=allowed_states,
            split_items=primary_split,
            baselines=primary_baselines,
            min_sample=min_sample,
        )
        for gate_id, label, allowed_states in LAB56_GATE_SPECS
    ]

    config_rows: list[dict[str, Any]] = []
    for config in LAB56_ZONE_CONFIGS:
        config_items = by_config[config.config_id]
        config_split = {
            split: [item for item in config_items if _lab55_item_key(item) in keys]
            for split, keys in split_keys.items()
        }
        config_baselines = {split: _walk_forward_perf(rows) for split, rows in config_split.items()}
        not_conflicted = _lab56_gate_row(
            gate_id="AVOID_1H_SUPPORT_CONFLICT",
            label="Avoid 1h support conflict",
            allowed_states=LAB56_GATE_SPECS[0][2],
            split_items=config_split,
            baselines=config_baselines,
            min_sample=min_sample,
        )
        config_rows.append(
            {
                "config_id": config.config_id,
                "label": config.label,
                "lookback_hours": config.lookback_hours,
                "pivot_span": config.pivot_span,
                "zone_half_width_atr": config.zone_half_width_atr,
                "min_touches": config.min_touches,
                "zone_available_count": sum(
                    1 for item in config_items if item.get("structure_state") != "1H_ZONE_UNAVAILABLE"
                ),
                "not_conflicted_gate": not_conflicted,
            }
        )

    selected_config_row = _lab56_select_config_from_train(config_rows)
    selected_gate = selected_config_row.get("not_conflicted_gate") if selected_config_row else None
    verdict = _lab56_study_verdict(selected_gate, min_sample=min_sample)
    all_scope = _lab56_cohort_row("ALL_SHADOW_PASS", primary_items, primary_baselines["all"])
    taker_scope_items = _apply_named_second_filter(primary_items, "TAKER_SELL_GE_52")
    taker_scope = _lab56_cohort_row(
        "TAKER_SELL_GE_52",
        taker_scope_items,
        primary_baselines["all"],
    )
    confluence_rows = [
        _lab56_bucket_row(
            status,
            field="four_hour_confluence_status",
            split_items=primary_split,
            baselines=primary_baselines,
        )
        for status in (
            "ALIGNED_WITH_4H_RESISTANCE",
            "CONFLICT_WITH_4H_SUPPORT",
            "NO_4H_CONFLUENCE",
            "FOUR_H_CONTEXT_UNAVAILABLE",
        )
    ]
    case_rows = [
        _lab56_case_row(item)
        for item in sorted(
            primary_items,
            key=lambda row: (
                _parse_dt(row.get("signal_timestamp")) or datetime.min,
                str(row.get("symbol") or ""),
            ),
            reverse=True,
        )[:limit]
    ]
    selected = next(
        (item for item in primary_items if str(item.get("signal_id") or "") == str(selected_signal_id or "")),
        None,
    )
    if selected is None and primary_items:
        selected = max(
            primary_items,
            key=lambda row: _parse_dt(row.get("signal_timestamp")) or datetime.min,
        )
    selected_symbol = str(selected.get("symbol") or "") if selected else ""
    selected_case = _lab56_case_row(selected) if selected else None
    selected_chart = (
        _lab56_zone_chart_payload(
            selected,
            candles=one_hour_candles.get(selected_symbol, []),
        )
        if selected
        else None
    )
    train_choice_validation = (
        selected_config_row["not_conflicted_gate"]["validation"] if selected_config_row else None
    )
    return {
        "study_id": "LAB_56_MID_SHORT_1H_STRUCTURE_ZONE_STUDY",
        "method": (
            "Repeated pivot highs and lows from closed futures 1h candles are clustered into ATR-normalized zones. "
            "The signal candle classifies rejection, break, retest, reclaim, support, resistance, or mid-range but "
            "cannot create the zone it is being tested against. Three predeclared sensitivity configurations are "
            "compared; the research choice is ranked on train only and then read on chronological validation."
        ),
        "definitions": {
            "primary_timeframe": "futures 1h closed candles",
            "outcome_path": "futures 15m closed candles with the existing realistic cost model",
            "four_hour_role": "optional confluence only; never a hard fail",
            "independent_touch_gap": "at least four hours between 1h pivot touches",
            "at_zone_distance": "entry within the zone or no farther than 0.15 ATR from its boundary",
            "fixed_cohort": "rows rejected by a simulated gate remain zero-R no-entry observations",
            "states": {
                "AT_1H_SUPPORT": "entry is on or immediately above a repeated 1h zone",
                "AT_1H_RESISTANCE": "entry is on or immediately below a repeated 1h zone",
                "1H_RESISTANCE_REJECTED": "signal candle probes a repeated resistance zone and closes below it",
                "1H_SUPPORT_BREAK": "signal candle closes below a zone that the previous candle held",
                "1H_BREAK_RETEST_REJECTED": "support was already broken, then the signal retests and closes below it",
                "1H_FAILED_BREAK_RECLAIM": "price had broken a zone but the signal closes back above it",
                "1H_MID_RANGE": "no immediate repeated-zone interaction",
                "1H_ZONE_UNAVAILABLE": "closed history, ATR, or repeated pivots are insufficient",
            },
        },
        "summary": {
            "source_count": len(primary_items),
            "train_count": len(primary_split["train"]),
            "validation_count": len(primary_split["validation"]),
            "validation_cutoff_utc": validation_cutoff,
            "zone_available_count": sum(
                1 for item in primary_items if item.get("structure_state") != "1H_ZONE_UNAVAILABLE"
            ),
            "four_hour_context_available_count": sum(
                1
                for item in primary_items
                if item.get("four_hour_confluence_status") != "FOUR_H_CONTEXT_UNAVAILABLE"
            ),
            "primary_config_id": LAB56_PRIMARY_CONFIG_ID,
            "train_selected_config_id": selected_config_row.get("config_id") if selected_config_row else None,
            "train_selected_validation_avg_r_delta": (
                train_choice_validation.get("fixed_avg_r_delta_vs_baseline")
                if train_choice_validation
                else None
            ),
            "train_selected_validation_sl_avoided": (
                train_choice_validation.get("sl_avoided_count") if train_choice_validation else 0
            ),
            "train_selected_validation_tp_lost": (
                train_choice_validation.get("tp_lost_count") if train_choice_validation else 0
            ),
            "verdict": verdict,
            "recommended_action": _lab56_recommended_action(verdict),
        },
        "cohort_rows": [all_scope, taker_scope],
        "config_rows": config_rows,
        "state_rows": state_rows,
        "gate_rows": gate_rows,
        "four_hour_confluence_rows": confluence_rows,
        "case_rows": case_rows,
        "selected_case": selected_case,
        "selected_chart": selected_chart,
        "limitations": [
            "A candle-derived zone is not order-book liquidity and can move when more history accumulates.",
            "OHLC proves that a zone was touched, not the exact intrabar sequence or resting order size.",
            "Zone parameters are a small predeclared sensitivity grid; no validation winner is optimized into a rule.",
            "The 4h context can be unavailable when fewer closed aggregates exist and is reported honestly.",
            "One chronological validation checkpoint cannot establish a production filter.",
        ],
    }


LAB59_PRIMARY_CONFLICT_STATES = frozenset(
    {
        "AT_1H_SUPPORT",
        "1H_FAILED_BREAK_RECLAIM",
    }
)
LAB59_SHORT_ALIGNED_STATES = frozenset(
    {
        "AT_1H_RESISTANCE",
        "1H_RESISTANCE_REJECTED",
        "1H_SUPPORT_BREAK",
        "1H_BREAK_RETEST_REJECTED",
    }
)


def _mid_short_v21_structure_interaction_study(
    items: list[dict[str, Any]],
    *,
    one_hour_candles: dict[str, list[PerfCandle]],
    four_hour_candles: dict[str, list[PerfCandle]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    primary_config = next(
        config for config in LAB56_ZONE_CONFIGS if config.config_id == LAB56_PRIMARY_CONFIG_ID
    )
    sorted_one_hour = {
        symbol: sorted(rows, key=lambda candle: candle.close_time)
        for symbol, rows in one_hour_candles.items()
    }
    sorted_four_hour = {
        symbol: sorted(rows, key=lambda candle: candle.close_time)
        for symbol, rows in four_hour_candles.items()
    }
    enriched: list[dict[str, Any]] = []
    for item in items:
        symbol = str(item.get("symbol") or "")
        structure = _lab56_structure_context(
            item,
            one_hour_candles=sorted_one_hour.get(symbol, []),
            four_hour_candles=sorted_four_hour.get(symbol, []),
            config=primary_config,
        )
        with_structure = {**item, **structure}
        enriched.append({**with_structure, **_lab59_target_path_context(with_structure)})

    ordered, train, validation, validation_cutoff = _lab53_chronological_split(enriched)
    split_items = {"all": ordered, "train": train, "validation": validation}
    baselines = {split: _walk_forward_perf(rows) for split, rows in split_items.items()}
    variants = [
        _lab59_variant_row(
            variant_id=variant_id,
            label=label,
            selection_rule=selection_rule,
            split_items=split_items,
            baselines=baselines,
            min_sample=min_sample,
        )
        for variant_id, label, selection_rule in (
            (
                "V21_CONTROL",
                "V2.1 fixed-cohort control",
                "All MID_SHORT 1h SHADOW_PASS rows with taker sell >= 52%.",
            ),
            (
                "PRIMARY_CONFLICT_VETO",
                "Veto immediate 1h structure conflict",
                "Exclude AT_1H_SUPPORT and 1H_FAILED_BREAK_RECLAIM; unavailable zones remain included.",
            ),
            (
                "TARGET_PATH_CLEAR",
                "Require clear path to logged target",
                "Exclude only rows where repeated 1h support lies strictly between short entry and target; unavailable stays included.",
            ),
            (
                "ALIGNED_AND_CLEAR",
                "Require aligned short structure and clear target path",
                "Keep resistance, resistance rejection, support break, or break-retest rejection and exclude blocked target paths.",
            ),
        )
    ]
    state_names = (
        "AT_1H_SUPPORT",
        "AT_1H_RESISTANCE",
        "1H_RESISTANCE_REJECTED",
        "1H_SUPPORT_BREAK",
        "1H_BREAK_RETEST_REJECTED",
        "1H_FAILED_BREAK_RECLAIM",
        "1H_MID_RANGE",
        "1H_ZONE_UNAVAILABLE",
    )
    state_rows = [
        _lab56_bucket_row(
            state,
            field="structure_state",
            split_items=split_items,
            baselines=baselines,
        )
        for state in state_names
    ]
    target_path_rows = [
        _lab56_bucket_row(
            status,
            field="target_path_status",
            split_items=split_items,
            baselines=baselines,
        )
        for status in ("TARGET_PATH_CLEAR", "TARGET_PATH_BLOCKED", "TARGET_PATH_UNAVAILABLE")
    ]
    four_hour_context_rows = [
        _lab56_bucket_row(
            status,
            field="four_hour_confluence_status",
            split_items=split_items,
            baselines=baselines,
        )
        for status in (
            "ALIGNED_WITH_4H_RESISTANCE",
            "CONFLICT_WITH_4H_SUPPORT",
            "NO_4H_CONFLUENCE",
            "FOUR_H_CONTEXT_UNAVAILABLE",
        )
    ]
    non_control = [
        row
        for row in variants
        if row["variant_id"] != "V21_CONTROL"
        and int(row["validation"].get("entered_closed_count") or 0) > 0
        and row["validation"].get("fixed_avg_r_delta_vs_baseline") is not None
    ]
    ranked = sorted(
        non_control,
        key=lambda row: (
            _decimal_or_zero(row["validation"].get("fixed_avg_r_delta_vs_baseline")),
            int(row["validation"].get("entered_closed_count") or 0),
        ),
        reverse=True,
    )
    best_variant = ranked[0] if ranked else None
    source_closed_count = int(variants[0]["all"].get("source_closed_count") or 0) if variants else 0
    validation_closed_count = (
        int(variants[0]["validation"].get("source_closed_count") or 0) if variants else 0
    )
    readiness_status = (
        "READY_FOR_READ_ONLY_COMPARISON"
        if source_closed_count >= 120 and validation_closed_count >= max(12, min_sample)
        else "MONITOR_MORE"
    )
    case_rows = [
        _lab59_case_row(item)
        for item in sorted(
            ordered,
            key=lambda row: (
                _parse_dt(row.get("signal_timestamp")) or datetime.min,
                str(row.get("symbol") or ""),
            ),
            reverse=True,
        )[:limit]
    ]
    conflict_count = sum(
        1 for item in ordered if str(item.get("structure_state") or "") in LAB59_PRIMARY_CONFLICT_STATES
    )
    blocked_path_count = sum(1 for item in ordered if item.get("target_path_status") == "TARGET_PATH_BLOCKED")
    return {
        "study_id": "LAB_59_MID_SHORT_1H_V21_STRUCTURE_INTERACTION",
        "method": (
            "The V2.1 fixed cohort is formed before any structure variant: MID_SHORT 1h, SHADOW_PASS, "
            "taker sell at least 52%, and one shared position lock. Repeated 1h pivot zones are causal. "
            "Four predefined variants are compared on the same chronological 70/30 split; rejected rows "
            "remain zero-R in fixed-cohort metrics. The 4h structure is descriptive context only."
        ),
        "definitions": {
            "fixed_cohort": "MID_SHORT 1h + SHADOW_PASS + taker sell >= 52%",
            "outcome_path": "existing realistic futures paper outcome from closed 15m/1m candles",
            "zone_source": "closed futures 1h candles before or at signal time",
            "target_path_blocked": "nearest repeated 1h support center is strictly between short entry and logged target",
            "primary_conflict_states": sorted(LAB59_PRIMARY_CONFLICT_STATES),
            "short_aligned_states": sorted(LAB59_SHORT_ALIGNED_STATES),
            "four_hour_role": "context-only; never changes variant membership",
            "sample_target": "120 fixed-cohort closed rows and at least max(12, min_sample) validation closed rows",
        },
        "summary": {
            "fixed_cohort_count": len(ordered),
            "fixed_cohort_closed_count": source_closed_count,
            "train_count": len(train),
            "validation_count": len(validation),
            "validation_closed_count": validation_closed_count,
            "validation_cutoff_utc": validation_cutoff,
            "zone_available_count": sum(
                1 for item in ordered if item.get("structure_state") != "1H_ZONE_UNAVAILABLE"
            ),
            "zone_unavailable_count": sum(
                1 for item in ordered if item.get("structure_state") == "1H_ZONE_UNAVAILABLE"
            ),
            "primary_conflict_count": conflict_count,
            "target_path_blocked_count": blocked_path_count,
            "four_hour_context_available_count": sum(
                1
                for item in ordered
                if item.get("four_hour_confluence_status") != "FOUR_H_CONTEXT_UNAVAILABLE"
            ),
            "open_count": sum(1 for item in ordered if item.get("result_status") == "OPEN"),
            "waiting_count": sum(1 for item in ordered if str(item.get("result_status") or "").startswith("WAITING")),
            "readiness_target_closed": 120,
            "readiness_status": readiness_status,
            "best_validation_variant_id": best_variant.get("variant_id") if best_variant else None,
            "best_validation_verdict": best_variant.get("verdict") if best_variant else None,
            "study_verdict": _lab59_study_verdict(readiness_status, best_variant),
            "recommended_action": _lab59_recommended_action(readiness_status, best_variant),
        },
        "baseline": baselines,
        "variant_rows": variants,
        "state_rows": state_rows,
        "target_path_rows": target_path_rows,
        "four_hour_context_rows": four_hour_context_rows,
        "case_rows": case_rows,
        "research_answers": {
            "does_primary_support_conflict_explain_losses": (
                f"{conflict_count} of {len(ordered)} fixed-cohort rows are immediate support/reclaim conflicts; compare their TP/SL/R in state_rows."
            ),
            "does_target_path_blockage_explain_missed_targets": (
                f"{blocked_path_count} of {len(ordered)} rows have repeated support between entry and target; compare TARGET_PATH_BLOCKED against CLEAR."
            ),
            "is_four_hour_context_a_gate": "No. It is grouped for diagnosis and never changes selected rows.",
            "can_a_variant_change_live_v21_now": "No. This checkpoint is read-only and requires forward confirmation before any rule proposal.",
        },
        "limitations": [
            "Repeated OHLC pivot zones approximate market structure; they are not order-book liquidity.",
            "The nearest support center is a deterministic path diagnostic, not a replacement target.",
            "Unavailable structure remains explicit and is not converted into a conflict or a pass claim.",
            "A single chronological validation checkpoint can describe behavior but cannot establish a live filter.",
        ],
    }


def _lab59_target_path_context(item: dict[str, Any]) -> dict[str, Any]:
    entry = _decimal_or_none_any(item.get("entry"))
    target = _decimal_or_none_any(item.get("take_profit"))
    risk = _decimal_or_none_any(item.get("risk"))
    support = item.get("nearest_support") if isinstance(item.get("nearest_support"), dict) else None
    support_center = _decimal_or_none_any(support.get("center")) if support else None
    if entry is None or target is None or risk is None or risk <= 0 or support_center is None:
        return {
            "target_path_status": "TARGET_PATH_UNAVAILABLE",
            "target_path_reason": "Entry, target, risk, or a repeated 1h support zone is unavailable.",
            "target_path_support_center": support_center,
            "support_clearance_to_target_r": None,
        }
    clearance = (support_center - target) / risk
    if target < support_center < entry:
        return {
            "target_path_status": "TARGET_PATH_BLOCKED",
            "target_path_reason": "Repeated 1h support lies between the short entry and logged target.",
            "target_path_support_center": support_center,
            "support_clearance_to_target_r": clearance,
        }
    return {
        "target_path_status": "TARGET_PATH_CLEAR",
        "target_path_reason": "No nearest repeated 1h support center lies between entry and target.",
        "target_path_support_center": support_center,
        "support_clearance_to_target_r": clearance,
    }


def _lab59_variant_selected(item: dict[str, Any], variant_id: str) -> bool:
    state = str(item.get("structure_state") or "1H_ZONE_UNAVAILABLE")
    target_path = str(item.get("target_path_status") or "TARGET_PATH_UNAVAILABLE")
    if variant_id == "V21_CONTROL":
        return True
    if variant_id == "PRIMARY_CONFLICT_VETO":
        return state not in LAB59_PRIMARY_CONFLICT_STATES
    if variant_id == "TARGET_PATH_CLEAR":
        return target_path != "TARGET_PATH_BLOCKED"
    if variant_id == "ALIGNED_AND_CLEAR":
        return state in LAB59_SHORT_ALIGNED_STATES and target_path != "TARGET_PATH_BLOCKED"
    return False


def _lab59_variant_row(
    *,
    variant_id: str,
    label: str,
    selection_rule: str,
    split_items: dict[str, list[dict[str, Any]]],
    baselines: dict[str, dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    selected = {
        split: [item for item in rows if _lab59_variant_selected(item, variant_id)]
        for split, rows in split_items.items()
    }
    fixed = {
        split: _lab56_fixed_cohort_perf(split_items[split], selected[split])
        for split in ("all", "train", "validation")
    }
    row = {
        "variant_id": variant_id,
        "label": label,
        "selection_rule": selection_rule,
        "all": fixed["all"],
        "train": fixed["train"],
        "validation": fixed["validation"],
        "selected_performance": {
            split: _walk_forward_perf(selected[split], baseline=baselines[split])
            for split in ("all", "train", "validation")
        },
        "selected_state_counts": dict(
            Counter(str(item.get("structure_state") or "UNKNOWN") for item in selected["all"])
        ),
        "selected_target_path_counts": dict(
            Counter(str(item.get("target_path_status") or "UNKNOWN") for item in selected["all"])
        ),
    }
    row["verdict"] = _lab59_variant_verdict(row, min_sample=min_sample)
    return row


def _lab59_variant_verdict(row: dict[str, Any], *, min_sample: int) -> str:
    if row.get("variant_id") == "V21_CONTROL":
        return "FIXED_COHORT_CONTROL"
    all_row = row["all"]
    train = row["train"]
    validation = row["validation"]
    if (
        int(all_row.get("source_closed_count") or 0) < 120
        or int(validation.get("source_closed_count") or 0) < max(12, min_sample)
        or int(validation.get("entered_closed_count") or 0) < max(6, min_sample // 2)
    ):
        return "MONITOR_MORE"
    train_delta = _decimal_or_none_any(train.get("fixed_avg_r_delta_vs_baseline"))
    validation_delta = _decimal_or_none_any(validation.get("fixed_avg_r_delta_vs_baseline"))
    validation_total = _decimal_or_none_any(validation.get("fixed_total_realistic_r"))
    validation_drawdown = _decimal_or_none_any(validation.get("fixed_max_drawdown_r"))
    control_drawdown = _decimal_or_none_any(validation.get("baseline_max_drawdown_r"))
    tradeoff_ok = int(validation.get("sl_avoided_count") or 0) >= int(validation.get("tp_lost_count") or 0)
    drawdown_ok = (
        validation_drawdown is not None
        and control_drawdown is not None
        and validation_drawdown >= control_drawdown
    )
    if validation_delta is not None and validation_delta > 0 and tradeoff_ok and drawdown_ok:
        return "VALIDATION_IMPROVES" if validation_total is not None and validation_total > 0 else "VALIDATION_REDUCES_DAMAGE"
    if train_delta is not None and train_delta > 0 and (validation_delta is None or validation_delta <= 0):
        return "TRAIN_ONLY"
    return "NO_CLEAR_GAIN"


def _lab59_study_verdict(readiness_status: str, best_variant: dict[str, Any] | None) -> str:
    if readiness_status != "READY_FOR_READ_ONLY_COMPARISON":
        return "V21_STRUCTURE_MONITOR_MORE"
    verdict = str(best_variant.get("verdict") or "") if best_variant else ""
    if verdict == "VALIDATION_IMPROVES":
        return "V21_STRUCTURE_FORWARD_CHECKPOINT_REQUIRED"
    if verdict == "VALIDATION_REDUCES_DAMAGE":
        return "V21_STRUCTURE_DAMAGE_REDUCTION_ONLY"
    return "V21_STRUCTURE_NO_PROMOTION"


def _lab59_recommended_action(readiness_status: str, best_variant: dict[str, Any] | None) -> str:
    if readiness_status != "READY_FOR_READ_ONLY_COMPARISON":
        return "Collect more closed V2.1 fixed-cohort outcomes; do not alter the live gate."
    if best_variant and best_variant.get("verdict") == "VALIDATION_IMPROVES":
        return "Track the descriptive winner in a new forward-only shadow checkpoint before proposing any rule change."
    return "Keep V2.1 unchanged; current structure variants do not justify promotion."


def _lab59_case_row(item: dict[str, Any]) -> dict[str, Any]:
    row = _lab56_case_row(item) or {}
    return {
        **row,
        "target_path_status": item.get("target_path_status"),
        "target_path_reason": item.get("target_path_reason"),
        "target_path_support_center": item.get("target_path_support_center"),
        "support_clearance_to_target_r": item.get("support_clearance_to_target_r"),
        "primary_conflict": str(item.get("structure_state") or "") in LAB59_PRIMARY_CONFLICT_STATES,
        "variant_membership": {
            variant_id: _lab59_variant_selected(item, variant_id)
            for variant_id in (
                "V21_CONTROL",
                "PRIMARY_CONFLICT_VETO",
                "TARGET_PATH_CLEAR",
                "ALIGNED_AND_CLEAR",
            )
        },
    }


LAB60_EXIT_VARIANTS = (
    ("CONTROL_LOGGED", "Logged V2.1 TP/SL", "Existing V2.1 logged target and stop."),
    ("TARGET_1_00R", "Fixed target 1.00R", "Keep the logged stop and place target at 1.00 logged R."),
    ("TARGET_1_25R", "Fixed target 1.25R", "Keep the logged stop and place target at 1.25 logged R."),
    ("TARGET_1_50R", "Fixed target 1.50R", "Keep the logged stop and place target at 1.50 logged R."),
    (
        "SUPPORT_FRONT_0_10ATR",
        "Target before support +0.10 ATR",
        "For a short, move the target above the upper edge of blocking support plus 0.10 ATR; otherwise keep logged target.",
    ),
    ("STOP_0_75X", "Stop risk 0.75x", "Use 75% of logged price risk while keeping the logged target."),
    ("STOP_1_25X", "Stop risk 1.25x", "Use 125% of logged price risk while keeping the logged target."),
    (
        "RESISTANCE_BACK_0_10ATR",
        "Stop behind resistance +0.10 ATR",
        "Place stop above the upper edge of nearest repeated resistance plus 0.10 ATR; otherwise keep logged stop.",
    ),
    (
        "ZONE_ADAPTIVE_BOTH",
        "Structure target + stop",
        "Combine target before blocking support with stop behind repeated resistance; unavailable sides keep logged geometry.",
    ),
)


def _mid_short_v21_structure_exit_study(
    items: list[dict[str, Any]],
    *,
    one_hour_candles: dict[str, list[PerfCandle]],
    forward_candles: dict[str, list[PerfCandle]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    primary_config = next(
        config for config in LAB56_ZONE_CONFIGS if config.config_id == LAB56_PRIMARY_CONFIG_ID
    )
    sorted_one_hour = {
        symbol: sorted(rows, key=lambda candle: candle.close_time)
        for symbol, rows in one_hour_candles.items()
    }
    sorted_forward = {
        symbol: sorted(rows, key=lambda candle: candle.open_time)
        for symbol, rows in forward_candles.items()
    }
    enriched: list[dict[str, Any]] = []
    for item in items:
        symbol = str(item.get("symbol") or "")
        signal_time = _parse_dt(item.get("signal_timestamp"))
        structure = _lab56_structure_context(
            item,
            one_hour_candles=sorted_one_hour.get(symbol, []),
            four_hour_candles=[],
            config=primary_config,
            include_four_hour_confluence=False,
        )
        with_structure = {**item, **structure}
        with_path = {**with_structure, **_lab59_target_path_context(with_structure)}
        future = _lab60_future_four_hours(
            sorted_forward.get(symbol, []),
            signal_time=signal_time,
        )
        results = {
            variant_id: _lab60_evaluate_variant(
                with_path,
                variant_id=variant_id,
                prepared_future_4h=future,
            )
            for variant_id, _label, _method in LAB60_EXIT_VARIANTS
        }
        enriched.append(
            {
                **with_path,
                "_lab60_exit_results": results,
                "_lab60_path_sequence": _lab60_path_sequence(with_path, future),
            }
        )

    ordered, train, validation, validation_cutoff = _lab53_chronological_split(enriched)
    split_items = {"all": ordered, "train": train, "validation": validation}
    control_perf = {
        split: _lab60_exit_performance(rows, "CONTROL_LOGGED")
        for split, rows in split_items.items()
    }
    variant_rows = [
        _lab60_exit_variant_row(
            variant_id=variant_id,
            label=label,
            method=method,
            split_items=split_items,
            control_perf=control_perf,
            min_sample=min_sample,
        )
        for variant_id, label, method in LAB60_EXIT_VARIANTS
    ]
    eligible_variants = [
        row
        for row in variant_rows
        if row["variant_id"] != "CONTROL_LOGGED"
        and row["validation"].get("avg_realistic_r_delta_vs_control") is not None
    ]
    ranked = sorted(
        eligible_variants,
        key=lambda row: (
            _decimal_or_zero(row["validation"].get("avg_realistic_r_delta_vs_control")),
            _decimal_or_zero(row["validation"].get("max_drawdown_delta_vs_control")),
            int(row["validation"].get("evaluated_count") or 0),
        ),
        reverse=True,
    )
    best_variant = ranked[0] if ranked else None
    original_closed = sum(1 for item in ordered if item.get("result_status") in COMPLETED_OUTCOMES)
    validation_original_closed = sum(
        1 for item in validation if item.get("result_status") in COMPLETED_OUTCOMES
    )
    readiness_status = (
        "READY_FOR_READ_ONLY_COMPARISON"
        if original_closed >= 120 and validation_original_closed >= max(12, min_sample)
        else "MONITOR_MORE"
    )
    path_summary = _lab60_path_summary(ordered)
    case_rows = [
        _lab60_case_row(item)
        for item in sorted(
            ordered,
            key=lambda row: (
                _parse_dt(row.get("signal_timestamp")) or datetime.min,
                str(row.get("symbol") or ""),
            ),
            reverse=True,
        )[:limit]
    ]
    return {
        "study_id": "LAB_60_MID_SHORT_1H_V21_STRUCTURE_EXIT_PATH",
        "method": (
            "LAB-60 keeps the LAB-59 V2.1 cohort fixed, reconstructs causal repeated 1h zones, "
            "and replays nine predefined target/stop geometries over the same closed futures path. "
            "Every variant uses the existing Binance-fee, spread, and slippage model, conservative "
            "same-candle handling, and one chronological 70/30 split."
        ),
        "definitions": {
            "fixed_cohort": "MID_SHORT 1h + SHADOW_PASS + taker sell >= 52%",
            "evaluation_horizon": "Four hours after signal close using merged closed futures 15m plus latest 1m tail",
            "support_front_target": (
                "Short target is placed above support upper edge plus 0.10 ATR, never below support."
            ),
            "resistance_back_stop": "Short stop is placed above resistance upper edge plus 0.10 ATR.",
            "same_candle_rule": "If target and stop occur in one candle, the stop-side conservative result is used.",
            "fixed_cohort_accounting": "All exit variants evaluate the same rows; no signal is filtered out.",
        },
        "summary": {
            "fixed_cohort_count": len(ordered),
            "fixed_cohort_closed_count": original_closed,
            "train_count": len(train),
            "validation_count": len(validation),
            "validation_closed_count": validation_original_closed,
            "validation_cutoff_utc": validation_cutoff,
            "zone_available_count": sum(
                1 for item in ordered if item.get("structure_state") != "1H_ZONE_UNAVAILABLE"
            ),
            "path_complete_count": path_summary.get("path_complete_count", 0),
            "path_waiting_count": path_summary.get("waiting_4h_count", 0),
            "readiness_target_closed": 120,
            "readiness_status": readiness_status,
            "best_validation_variant_id": best_variant.get("variant_id") if best_variant else None,
            "best_validation_verdict": best_variant.get("verdict") if best_variant else None,
            "best_validation_avg_r_delta": (
                best_variant["validation"].get("avg_realistic_r_delta_vs_control")
                if best_variant
                else None
            ),
            "study_verdict": _lab60_study_verdict(readiness_status, best_variant),
            "recommended_action": _lab60_recommended_action(readiness_status, best_variant),
        },
        "control": control_perf,
        "variant_rows": variant_rows,
        "path_summary": path_summary,
        "case_rows": case_rows,
        "research_answers": {
            "does_logged_target_fail_after_partial_progress": (
                f"{path_summary.get('sl_after_0_50r_count', 0)} stop-first paths reached +0.50R in an earlier candle; "
                f"{path_summary.get('sl_after_1_00r_count', 0)} reached +1.00R before later stopping."
            ),
            "is_same_candle_order_known": (
                f"No. {path_summary.get('both_same_candle_count', 0)} paths are ambiguous and treated conservatively."
            ),
            "does_structure_geometry_change_live_signals": (
                "No. All geometry is replayed read-only; logged V2.1 entry, target, and stop remain untouched."
            ),
        },
        "limitations": [
            "Candle OHLC cannot prove intrabar order when target and stop are both inside one candle.",
            "Repeated pivot zones approximate structure and are not visible resting liquidity.",
            "Close-at-horizon R is descriptive and is not a final exit instruction.",
            "A validation improvement remains a research candidate until a later forward-only checkpoint.",
        ],
    }


def _lab60_future_four_hours(
    candles: list[PerfCandle],
    *,
    signal_time: datetime | None,
) -> list[PerfCandle]:
    if signal_time is None or not candles:
        return []
    open_times = [candle.open_time for candle in candles]
    return [
        candle
        for candle in candles[bisect_left(open_times, signal_time):]
        if candle.close_time <= signal_time + timedelta(hours=4)
    ]


def _lab60_variant_geometry(item: dict[str, Any], variant_id: str) -> dict[str, Any]:
    entry = _decimal_or_none_any(item.get("entry"))
    logged_risk = _decimal_or_none_any(item.get("risk"))
    logged_stop = _decimal_or_none_any(item.get("stop_loss"))
    logged_target = _decimal_or_none_any(item.get("take_profit"))
    atr = _decimal_or_none_any(item.get("atr_1h_at_signal"))
    if (
        entry is None
        or logged_risk is None
        or logged_risk <= 0
        or logged_stop is None
        or logged_target is None
    ):
        return {
            "geometry_status": "MISSING_LOGGED_GEOMETRY",
            "geometry_reason": "Entry, risk, stop, or target is unavailable.",
            "entry": entry,
            "stop": logged_stop,
            "target": logged_target,
            "risk": logged_risk,
            "adjusted": False,
        }

    stop = logged_stop
    target = logged_target
    status = "CONTROL_LOGGED"
    reason = "Existing V2.1 target and stop are retained."
    if variant_id == "TARGET_1_00R":
        target = entry - logged_risk
        status = "FIXED_TARGET"
        reason = "Target is fixed at 1.00 logged R."
    elif variant_id == "TARGET_1_25R":
        target = entry - (logged_risk * Decimal("1.25"))
        status = "FIXED_TARGET"
        reason = "Target is fixed at 1.25 logged R."
    elif variant_id == "TARGET_1_50R":
        target = entry - (logged_risk * Decimal("1.50"))
        status = "FIXED_TARGET"
        reason = "Target is fixed at 1.50 logged R."
    elif variant_id == "STOP_0_75X":
        stop = entry + (logged_risk * Decimal("0.75"))
        status = "FIXED_STOP"
        reason = "Stop risk is 0.75x logged risk."
    elif variant_id == "STOP_1_25X":
        stop = entry + (logged_risk * Decimal("1.25"))
        status = "FIXED_STOP"
        reason = "Stop risk is 1.25x logged risk."
    elif variant_id in {"SUPPORT_FRONT_0_10ATR", "ZONE_ADAPTIVE_BOTH"}:
        target, target_status, target_reason = _lab60_support_front_target(
            entry=entry,
            logged_target=logged_target,
            atr=atr,
            support=item.get("nearest_support"),
        )
        status = target_status
        reason = target_reason
    if variant_id in {"RESISTANCE_BACK_0_10ATR", "ZONE_ADAPTIVE_BOTH"}:
        stop, stop_status, stop_reason = _lab60_resistance_back_stop(
            entry=entry,
            logged_stop=logged_stop,
            atr=atr,
            resistance=item.get("nearest_resistance"),
        )
        if variant_id == "ZONE_ADAPTIVE_BOTH":
            status = f"TARGET_{status}__STOP_{stop_status}"
            reason = f"{reason} {stop_reason}"
        else:
            status = stop_status
            reason = stop_reason

    risk = stop - entry
    valid = target > 0 and target < entry and stop > entry and risk > 0
    if not valid:
        stop = logged_stop
        target = logged_target
        risk = logged_risk
        status = "INVALID_STRUCTURE_FALLBACK_LOGGED"
        reason = "Derived geometry was invalid, so the logged target and stop were retained."
    adjusted = stop != logged_stop or target != logged_target
    return {
        "geometry_status": status,
        "geometry_reason": reason,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "risk_scale": risk / logged_risk,
        "target_rr": (entry - target) / risk if risk > 0 else None,
        "stop_risk_multiple": risk / logged_risk,
        "adjusted": adjusted,
    }


def _lab60_support_front_target(
    *,
    entry: Decimal,
    logged_target: Decimal,
    atr: Decimal | None,
    support: Any,
) -> tuple[Decimal, str, str]:
    zone = support if isinstance(support, dict) else None
    upper = _decimal_or_none_any(zone.get("upper")) if zone else None
    if atr is None or atr <= 0 or upper is None:
        return logged_target, "SUPPORT_UNAVAILABLE_FALLBACK", "Support or ATR is unavailable; logged target is retained."
    if not logged_target < upper < entry:
        return logged_target, "SUPPORT_NOT_BLOCKING", "Repeated support does not block the logged short target."
    candidate = upper + (atr * Decimal("0.10"))
    if candidate >= entry:
        return logged_target, "SUPPORT_BUFFER_INVALID_FALLBACK", "Buffered support target would not be below entry."
    return max(logged_target, candidate), "SUPPORT_FRONT_ADJUSTED", "Target is above blocking support upper edge plus 0.10 ATR."


def _lab60_resistance_back_stop(
    *,
    entry: Decimal,
    logged_stop: Decimal,
    atr: Decimal | None,
    resistance: Any,
) -> tuple[Decimal, str, str]:
    zone = resistance if isinstance(resistance, dict) else None
    upper = _decimal_or_none_any(zone.get("upper")) if zone else None
    if atr is None or atr <= 0 or upper is None:
        return logged_stop, "RESISTANCE_UNAVAILABLE_FALLBACK", "Resistance or ATR is unavailable; logged stop is retained."
    candidate = upper + (atr * Decimal("0.10"))
    if candidate <= entry:
        return logged_stop, "RESISTANCE_BUFFER_INVALID_FALLBACK", "Buffered resistance stop would not be above entry."
    return candidate, "RESISTANCE_BACK_ADJUSTED", "Stop is above resistance upper edge plus 0.10 ATR."


def _lab60_evaluate_variant(
    item: dict[str, Any],
    *,
    variant_id: str,
    prepared_future_4h: list[PerfCandle],
) -> dict[str, Any]:
    geometry = _lab60_variant_geometry(item, variant_id)
    risk = _decimal_or_none_any(geometry.get("risk"))
    logged_risk = _decimal_or_none_any(item.get("risk"))
    target = _decimal_or_none_any(geometry.get("target"))
    stop = _decimal_or_none_any(geometry.get("stop"))
    logged_stop = _decimal_or_none_any(item.get("stop_loss"))
    if risk is None or risk <= 0 or logged_risk is None or logged_risk <= 0 or target is None:
        return {**geometry, "status": "MISSING_CONTEXT", "realistic_r": None}
    result = _mid_short_counterfactual_exit(
        item,
        candles=[],
        risk_scale=risk / logged_risk,
        target_rr=None,
        protect_at_r=None,
        use_logged_target=stop == logged_stop,
        prepared_future_4h=prepared_future_4h,
        target_override=target,
        require_complete_horizon_for_neither=True,
    )
    return {
        **geometry,
        **result,
        "target_rr": (entry - target) / risk
        if (entry := _decimal_or_none_any(geometry.get("entry"))) is not None
        else None,
    }


def _lab60_exit_performance(items: list[dict[str, Any]], variant_id: str) -> dict[str, Any]:
    ordered = sorted(
        items,
        key=lambda item: (
            _parse_dt(item.get("signal_timestamp")) or datetime.min,
            str(item.get("symbol") or ""),
        ),
    )
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    statuses: Counter[str] = Counter()
    geometry_statuses: Counter[str] = Counter()
    for item in ordered:
        results = item.get("_lab60_exit_results")
        result = results.get(variant_id) if isinstance(results, dict) else None
        if not isinstance(result, dict):
            statuses["MISSING_CONTEXT"] += 1
            continue
        status = str(result.get("status") or "MISSING_CONTEXT")
        statuses[status] += 1
        geometry_statuses[str(result.get("geometry_status") or "UNKNOWN")] += 1
        if result.get("realistic_r") is not None:
            rows.append((item, result))
    values = [Decimal(result["realistic_r"]) for _item, result in rows]
    target_rr_values = [
        Decimal(result["target_rr"])
        for _item, result in rows
        if result.get("target_rr") is not None
    ]
    stop_multiple_values = [
        Decimal(result["stop_risk_multiple"])
        for _item, result in rows
        if result.get("stop_risk_multiple") is not None
    ]
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    symbol_counts = Counter(str(item.get("symbol") or "") for item, _result in rows)
    top_symbol, top_count = symbol_counts.most_common(1)[0] if symbol_counts else (None, 0)
    closed_count = statuses["TP_HIT"] + statuses["SL_HIT"] + statuses["BOTH_HIT_SAME_CANDLE"]
    return {
        "source_count": len(ordered),
        "evaluated_count": len(rows),
        "waiting_count": statuses["WAITING_4H"],
        "missing_count": statuses["MISSING_CONTEXT"] + statuses["INVALID_TARGET_GEOMETRY"],
        "closed_count": closed_count,
        "tp_count": statuses["TP_HIT"],
        "sl_count": statuses["SL_HIT"],
        "both_count": statuses["BOTH_HIT_SAME_CANDLE"],
        "neither_count": statuses["NEITHER_4H"],
        "total_realistic_r": sum(values, Decimal("0")),
        "avg_realistic_r": _avg_decimal(values),
        "median_realistic_r": _percentile_decimal(values, Decimal("0.50")),
        "max_drawdown_r": max_drawdown,
        "tp_share_pct_closed": Decimal(statuses["TP_HIT"]) / Decimal(closed_count) * Decimal("100") if closed_count else None,
        "loss_share_pct_closed": Decimal(statuses["SL_HIT"] + statuses["BOTH_HIT_SAME_CANDLE"]) / Decimal(closed_count) * Decimal("100") if closed_count else None,
        "target_rr_q1": _percentile_decimal(target_rr_values, Decimal("0.25")),
        "target_rr_median": _percentile_decimal(target_rr_values, Decimal("0.50")),
        "target_rr_q3": _percentile_decimal(target_rr_values, Decimal("0.75")),
        "stop_multiple_q1": _percentile_decimal(stop_multiple_values, Decimal("0.25")),
        "stop_multiple_median": _percentile_decimal(stop_multiple_values, Decimal("0.50")),
        "stop_multiple_q3": _percentile_decimal(stop_multiple_values, Decimal("0.75")),
        "geometry_adjusted_count": sum(1 for _item, result in rows if result.get("adjusted")),
        "geometry_fallback_count": sum(
            count for status, count in geometry_statuses.items() if "FALLBACK" in status or "UNAVAILABLE" in status
        ),
        "geometry_status_counts": dict(geometry_statuses),
        "top_symbol": top_symbol,
        "top_symbol_count": top_count,
        "top_symbol_share_pct": Decimal(top_count) / Decimal(len(rows)) * Decimal("100") if rows else None,
    }


def _lab60_exit_variant_row(
    *,
    variant_id: str,
    label: str,
    method: str,
    split_items: dict[str, list[dict[str, Any]]],
    control_perf: dict[str, dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    performance = {
        split: _lab60_exit_performance(rows, variant_id)
        for split, rows in split_items.items()
    }
    for split in ("all", "train", "validation"):
        current = performance[split]
        control = control_perf[split]
        current["total_realistic_r_delta_vs_control"] = _decimal_delta(
            current.get("total_realistic_r"), control.get("total_realistic_r")
        )
        current["avg_realistic_r_delta_vs_control"] = _decimal_delta(
            current.get("avg_realistic_r"), control.get("avg_realistic_r")
        )
        current["max_drawdown_delta_vs_control"] = _decimal_delta(
            current.get("max_drawdown_r"), control.get("max_drawdown_r")
        )
        current.update(_lab60_transition_counts(split_items[split], variant_id))
    row = {
        "variant_id": variant_id,
        "label": label,
        "method": method,
        **performance,
    }
    row["verdict"] = _lab60_variant_verdict(row, min_sample=min_sample)
    return row


def _lab60_transition_counts(items: list[dict[str, Any]], variant_id: str) -> dict[str, int]:
    output = Counter()
    loss_statuses = {"SL_HIT", "BOTH_HIT_SAME_CANDLE"}
    for item in items:
        results = item.get("_lab60_exit_results")
        if not isinstance(results, dict):
            continue
        control = results.get("CONTROL_LOGGED")
        variant = results.get(variant_id)
        if not isinstance(control, dict) or not isinstance(variant, dict):
            continue
        control_status = str(control.get("status") or "")
        variant_status = str(variant.get("status") or "")
        if control_status == "TP_HIT" and variant_status != "TP_HIT":
            output["tp_lost_count"] += 1
        if control_status != "TP_HIT" and variant_status == "TP_HIT":
            output["tp_gained_count"] += 1
        if control_status in loss_statuses and variant_status not in loss_statuses:
            output["sl_avoided_count"] += 1
        if control_status not in loss_statuses and variant_status in loss_statuses:
            output["sl_added_count"] += 1
    return {
        "tp_lost_count": output["tp_lost_count"],
        "tp_gained_count": output["tp_gained_count"],
        "sl_avoided_count": output["sl_avoided_count"],
        "sl_added_count": output["sl_added_count"],
    }


def _lab60_variant_verdict(row: dict[str, Any], *, min_sample: int) -> str:
    if row.get("variant_id") == "CONTROL_LOGGED":
        return "CURRENT_CONTROL"
    all_perf = row["all"]
    validation = row["validation"]
    if (
        int(all_perf.get("evaluated_count") or 0) < 120
        or int(validation.get("evaluated_count") or 0) < max(12, min_sample)
    ):
        return "MONITOR_MORE"
    train_delta = _decimal_or_none_any(row["train"].get("avg_realistic_r_delta_vs_control"))
    validation_delta = _decimal_or_none_any(validation.get("avg_realistic_r_delta_vs_control"))
    validation_total = _decimal_or_none_any(validation.get("total_realistic_r"))
    drawdown_delta = _decimal_or_none_any(validation.get("max_drawdown_delta_vs_control"))
    if (
        train_delta is not None
        and train_delta > 0
        and validation_delta is not None
        and validation_delta > 0
        and validation_total is not None
        and validation_total > 0
        and drawdown_delta is not None
        and drawdown_delta >= 0
    ):
        return "VALIDATION_IMPROVES_RESEARCH_ONLY"
    if validation_delta is not None and validation_delta > 0:
        return "VALIDATION_ONLY_MONITOR"
    if train_delta is not None and train_delta > 0:
        return "TRAIN_ONLY"
    return "NO_CLEAR_GAIN"


def _lab60_study_verdict(readiness_status: str, best_variant: dict[str, Any] | None) -> str:
    if readiness_status != "READY_FOR_READ_ONLY_COMPARISON":
        return "V21_EXIT_GEOMETRY_MONITOR_MORE"
    if best_variant and best_variant.get("verdict") == "VALIDATION_IMPROVES_RESEARCH_ONLY":
        return "FORWARD_ONLY_CHECKPOINT_REQUIRED"
    return "NO_EXIT_GEOMETRY_PROMOTION"


def _lab60_recommended_action(readiness_status: str, best_variant: dict[str, Any] | None) -> str:
    if readiness_status != "READY_FOR_READ_ONLY_COMPARISON":
        return "Collect at least 120 closed fixed-cohort outcomes; keep V2.1 target and stop unchanged."
    if best_variant and best_variant.get("verdict") == "VALIDATION_IMPROVES_RESEARCH_ONLY":
        return "Track this geometry in a new forward-only shadow checkpoint before any rule proposal."
    return "Keep logged V2.1 exits; no predefined structure geometry has survived validation cleanly."


def _lab60_path_sequence(
    item: dict[str, Any],
    future: list[PerfCandle],
) -> dict[str, Any]:
    entry = _decimal_or_none_any(item.get("entry"))
    risk = _decimal_or_none_any(item.get("risk"))
    stop = _decimal_or_none_any(item.get("stop_loss"))
    target = _decimal_or_none_any(item.get("take_profit"))
    signal_time = _parse_dt(item.get("signal_timestamp"))
    if entry is None or risk is None or risk <= 0 or stop is None or target is None or signal_time is None or not future:
        return {"path_status": "MISSING_CONTEXT", "path_complete": False}

    levels = {
        "0_50r": entry - (risk * Decimal("0.50")),
        "1_00r": entry - risk,
        "1_25r": entry - (risk * Decimal("1.25")),
        "1_50r": entry - (risk * Decimal("1.50")),
    }
    level_indices: dict[str, int | None] = {
        name: next((index for index, candle in enumerate(future) if candle.low <= price), None)
        for name, price in levels.items()
    }
    tp_index = next((index for index, candle in enumerate(future) if candle.low <= target), None)
    sl_index = next((index for index, candle in enumerate(future) if candle.high >= stop), None)
    if tp_index is not None and sl_index is not None and tp_index == sl_index:
        path_status = "BOTH_SAME_CANDLE"
        terminal_index = tp_index
    elif tp_index is not None and (sl_index is None or tp_index < sl_index):
        path_status = "TP_FIRST"
        terminal_index = tp_index
    elif sl_index is not None:
        path_status = "SL_FIRST"
        terminal_index = sl_index
    else:
        complete = future[-1].close_time >= signal_time + timedelta(hours=4) - timedelta(milliseconds=1)
        path_status = "NEITHER_4H" if complete else "WAITING_4H"
        terminal_index = len(future) - 1
    observed = future[: terminal_index + 1]
    mfe_r = max(((entry - candle.low) / risk for candle in observed), default=Decimal("0"))
    mae_r = min(((entry - candle.high) / risk for candle in observed), default=Decimal("0"))
    return {
        "path_status": path_status,
        "path_complete": path_status != "WAITING_4H",
        "terminal_candle_index": terminal_index,
        "terminal_time_utc": future[terminal_index].close_time,
        "mfe_r_to_terminal": mfe_r,
        "mae_r_to_terminal": mae_r,
        "tp_candle_index": tp_index,
        "sl_candle_index": sl_index,
        "first_level_candle_index": level_indices,
        "reached_0_50r_before_sl": (
            path_status == "SL_FIRST"
            and level_indices["0_50r"] is not None
            and level_indices["0_50r"] < terminal_index
        ),
        "reached_1_00r_before_sl": (
            path_status == "SL_FIRST"
            and level_indices["1_00r"] is not None
            and level_indices["1_00r"] < terminal_index
        ),
        "reached_1_25r_before_sl": (
            path_status == "SL_FIRST"
            and level_indices["1_25r"] is not None
            and level_indices["1_25r"] < terminal_index
        ),
        "reached_1_50r_before_sl": (
            path_status == "SL_FIRST"
            and level_indices["1_50r"] is not None
            and level_indices["1_50r"] < terminal_index
        ),
        "time_to_0_50r_minutes": _lab60_time_to_index(future, signal_time, level_indices["0_50r"]),
        "time_to_1_00r_minutes": _lab60_time_to_index(future, signal_time, level_indices["1_00r"]),
        "time_to_tp_minutes": _lab60_time_to_index(future, signal_time, tp_index),
        "time_to_sl_minutes": _lab60_time_to_index(future, signal_time, sl_index),
    }


def _lab60_time_to_index(
    candles: list[PerfCandle],
    signal_time: datetime,
    index: int | None,
) -> Decimal | None:
    if index is None:
        return None
    return Decimal((candles[index].close_time - signal_time).total_seconds()) / Decimal("60")


def _lab60_path_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    paths = [item.get("_lab60_path_sequence") for item in items]
    rows = [path for path in paths if isinstance(path, dict)]
    counts = Counter(str(path.get("path_status") or "MISSING_CONTEXT") for path in rows)
    tp_rows = [path for path in rows if path.get("path_status") == "TP_FIRST"]
    sl_rows = [path for path in rows if path.get("path_status") == "SL_FIRST"]
    tp_mae = [_decimal_or_zero(path.get("mae_r_to_terminal")) for path in tp_rows]
    sl_mfe = [_decimal_or_zero(path.get("mfe_r_to_terminal")) for path in sl_rows]
    return {
        "source_count": len(items),
        "path_complete_count": sum(1 for path in rows if path.get("path_complete")),
        "tp_first_count": counts["TP_FIRST"],
        "sl_first_count": counts["SL_FIRST"],
        "both_same_candle_count": counts["BOTH_SAME_CANDLE"],
        "neither_4h_count": counts["NEITHER_4H"],
        "waiting_4h_count": counts["WAITING_4H"],
        "missing_context_count": counts["MISSING_CONTEXT"],
        "sl_after_0_50r_count": sum(1 for path in sl_rows if path.get("reached_0_50r_before_sl")),
        "sl_after_1_00r_count": sum(1 for path in sl_rows if path.get("reached_1_00r_before_sl")),
        "sl_after_1_25r_count": sum(1 for path in sl_rows if path.get("reached_1_25r_before_sl")),
        "sl_after_1_50r_count": sum(1 for path in sl_rows if path.get("reached_1_50r_before_sl")),
        "tp_mae_r_median": _percentile_decimal(tp_mae, Decimal("0.50")),
        "tp_mae_r_q3": _percentile_decimal(tp_mae, Decimal("0.75")),
        "tp_mae_r_q90": _percentile_decimal(tp_mae, Decimal("0.90")),
        "sl_mfe_r_median": _percentile_decimal(sl_mfe, Decimal("0.50")),
        "sl_mfe_r_q3": _percentile_decimal(sl_mfe, Decimal("0.75")),
        "sl_mfe_r_q90": _percentile_decimal(sl_mfe, Decimal("0.90")),
        "time_to_tp_minutes_median": _percentile_decimal(
            [_decimal_or_zero(path.get("time_to_tp_minutes")) for path in tp_rows if path.get("time_to_tp_minutes") is not None],
            Decimal("0.50"),
        ),
        "time_to_sl_minutes_median": _percentile_decimal(
            [_decimal_or_zero(path.get("time_to_sl_minutes")) for path in sl_rows if path.get("time_to_sl_minutes") is not None],
            Decimal("0.50"),
        ),
    }


def _lab60_case_row(item: dict[str, Any]) -> dict[str, Any]:
    base = _lab59_case_row(item)
    results = item.get("_lab60_exit_results") if isinstance(item.get("_lab60_exit_results"), dict) else {}
    return {
        **base,
        "path_sequence": item.get("_lab60_path_sequence"),
        "exit_results": {
            variant_id: {
                "status": result.get("status"),
                "realistic_r": result.get("realistic_r"),
                "target": result.get("target"),
                "stop": result.get("stop"),
                "target_rr": result.get("target_rr"),
                "stop_risk_multiple": result.get("stop_risk_multiple"),
                "geometry_status": result.get("geometry_status"),
                "adjusted": bool(result.get("adjusted")),
            }
            for variant_id, result in results.items()
            if isinstance(result, dict)
        },
    }


LAB61_DYNAMIC_EXIT_VARIANTS = (
    (
        "CONTROL_LOGGED",
        "Logged V2.1 exit",
        "Keep the existing V2.1 target and stop for the full four-hour path.",
    ),
    (
        "EXIT_FIRST_SUPPORT_RECLAIM",
        "Exit after first support reclaim",
        "After a closed bullish 15m candle touches blocking support and closes above it, exit at the next candle open.",
    ),
    (
        "EXIT_CONFIRMED_SUPPORT_REVERSAL",
        "Exit after confirmed reclaim",
        "Require the next closed 15m candle to close above the reclaim candle high, then exit at the following candle open.",
    ),
    (
        "EXIT_SUPPORT_RECLAIM_AFTER_0_50R",
        "Exit reclaim after +0.50R",
        "Use the first support reclaim only after the short path has already reached at least +0.50R, then exit at the next open.",
    ),
    (
        "SUPPORT_FRONT_0_10ATR",
        "Static target before support",
        "LAB-60 comparator: move target above blocking support plus 0.10 ATR without adding a dynamic exit.",
    ),
)


def _mid_short_v21_dynamic_exit_study(
    items: list[dict[str, Any]],
    *,
    one_hour_candles: dict[str, list[PerfCandle]],
    forward_candles: dict[str, list[PerfCandle]],
    min_sample: int,
    limit: int,
) -> dict[str, Any]:
    primary_config = next(
        config for config in LAB56_ZONE_CONFIGS if config.config_id == LAB56_PRIMARY_CONFIG_ID
    )
    sorted_one_hour = {
        symbol: sorted(rows, key=lambda candle: candle.close_time)
        for symbol, rows in one_hour_candles.items()
    }
    sorted_forward = {
        symbol: sorted(rows, key=lambda candle: (candle.open_time, candle.close_time))
        for symbol, rows in forward_candles.items()
    }
    enriched: list[dict[str, Any]] = []
    for item in items:
        symbol = str(item.get("symbol") or "")
        signal_time = _parse_dt(item.get("signal_timestamp"))
        structure = _lab56_structure_context(
            item,
            one_hour_candles=sorted_one_hour.get(symbol, []),
            four_hour_candles=[],
            config=primary_config,
            include_four_hour_confluence=False,
        )
        with_structure = {**item, **structure}
        with_path = {**with_structure, **_lab59_target_path_context(with_structure)}
        future = _lab60_future_four_hours(
            sorted_forward.get(symbol, []),
            signal_time=signal_time,
        )
        results = {
            variant_id: _lab61_evaluate_dynamic_exit(
                with_path,
                variant_id=variant_id,
                prepared_future_4h=future,
            )
            for variant_id, _label, _method in LAB61_DYNAMIC_EXIT_VARIANTS
        }
        enriched.append(
            {
                **with_path,
                "_lab61_dynamic_exit_results": results,
                "_lab60_path_sequence": _lab60_path_sequence(with_path, future),
            }
        )

    ordered, train, validation, validation_cutoff = _lab53_chronological_split(enriched)
    split_items = {"all": ordered, "train": train, "validation": validation}
    control_perf = {
        split: _lab61_dynamic_exit_performance(rows, "CONTROL_LOGGED")
        for split, rows in split_items.items()
    }
    variant_rows = [
        _lab61_dynamic_exit_variant_row(
            variant_id=variant_id,
            label=label,
            method=method,
            split_items=split_items,
            control_perf=control_perf,
            min_sample=min_sample,
        )
        for variant_id, label, method in LAB61_DYNAMIC_EXIT_VARIANTS
    ]
    eligible = [
        row
        for row in variant_rows
        if row["variant_id"] != "CONTROL_LOGGED"
        and row["validation"].get("avg_realistic_r_delta_vs_control") is not None
    ]
    ranked = sorted(
        eligible,
        key=lambda row: (
            _decimal_or_zero(row["validation"].get("avg_realistic_r_delta_vs_control")),
            _decimal_or_zero(row["validation"].get("max_drawdown_delta_vs_control")),
            -int(row["validation"].get("tp_sacrificed_count") or 0),
        ),
        reverse=True,
    )
    best_variant = ranked[0] if ranked else None
    original_closed = sum(1 for item in ordered if item.get("result_status") in COMPLETED_OUTCOMES)
    validation_original_closed = sum(
        1 for item in validation if item.get("result_status") in COMPLETED_OUTCOMES
    )
    readiness_status = (
        "READY_FOR_READ_ONLY_COMPARISON"
        if original_closed >= 120 and validation_original_closed >= max(12, min_sample)
        else "MONITOR_MORE"
    )
    case_rows = [
        _lab61_dynamic_exit_case_row(item)
        for item in sorted(
            ordered,
            key=lambda row: (
                _parse_dt(row.get("signal_timestamp")) or datetime.min,
                str(row.get("symbol") or ""),
            ),
            reverse=True,
        )[:limit]
    ]
    return {
        "study_id": "LAB_61_MID_SHORT_1H_V21_DYNAMIC_EXIT",
        "method": (
            "LAB-61 keeps the LAB-59/LAB-60 V2.1 cohort fixed and observes every closed futures 15m candle after entry. "
            "A dynamic exit can be decided only after a bullish candle touches causal blocking support and closes back above it. "
            "The simulated fill is the next available candle open, while any TP/SL reached before that decision remains final."
        ),
        "definitions": {
            "fixed_cohort": "MID_SHORT 1h + SHADOW_PASS + taker sell >= 52%",
            "blocking_support": "Repeated causal 1h support with logged target below support and entry above support.",
            "support_reclaim": "Closed bullish 15m candle intersects support and closes above the support upper edge.",
            "confirmed_reversal": "The next closed 15m candle closes above the reclaim candle high.",
            "decision_cadence": "Closed futures 15m candles only; 1m candles cannot create a trigger.",
            "fill_rule": "Exit at the first available futures candle open at or after the decision close.",
            "terminal_precedence": "TP/SL inside the trigger or confirmation candle wins before any dynamic exit.",
            "evaluation_horizon": "Four hours after signal close.",
        },
        "summary": {
            "fixed_cohort_count": len(ordered),
            "fixed_cohort_closed_count": original_closed,
            "train_count": len(train),
            "validation_count": len(validation),
            "validation_closed_count": validation_original_closed,
            "validation_cutoff_utc": validation_cutoff,
            "zone_available_count": sum(
                1 for item in ordered if item.get("structure_state") != "1H_ZONE_UNAVAILABLE"
            ),
            "blocking_support_count": sum(
                1 for item in ordered if _lab61_blocking_support(item) is not None
            ),
            "first_reclaim_trigger_count": _lab61_trigger_count(
                ordered, "EXIT_FIRST_SUPPORT_RECLAIM"
            ),
            "confirmed_reversal_trigger_count": _lab61_trigger_count(
                ordered, "EXIT_CONFIRMED_SUPPORT_REVERSAL"
            ),
            "reclaim_after_0_50r_trigger_count": _lab61_trigger_count(
                ordered, "EXIT_SUPPORT_RECLAIM_AFTER_0_50R"
            ),
            "readiness_target_closed": 120,
            "readiness_status": readiness_status,
            "best_validation_variant_id": best_variant.get("variant_id") if best_variant else None,
            "best_validation_verdict": best_variant.get("verdict") if best_variant else None,
            "best_validation_avg_r_delta": (
                best_variant["validation"].get("avg_realistic_r_delta_vs_control")
                if best_variant
                else None
            ),
            "study_verdict": _lab61_study_verdict(readiness_status, best_variant),
            "recommended_action": _lab61_recommended_action(readiness_status, best_variant),
        },
        "control": control_perf,
        "variant_rows": variant_rows,
        "case_rows": case_rows,
        "research_answers": {
            "can_support_reclaim_reduce_full_stop_losses": (
                "Read SL avoided and R saved in validation; a lower loss count is not enough if TP sacrifice or drawdown worsens."
            ),
            "does_the_study_exit_on_the_trigger_close": (
                "No. The trigger candle must close first and the simulation fills at the next available candle open."
            ),
            "can_the_1m_tail_create_a_reclaim": (
                "No. The 1m tail can only provide the next-open fill after a closed 15m decision."
            ),
            "does_this_change_v2_1": (
                "No. LAB-61 is a read-only counterfactual over logged V2.1 signals and outcomes."
            ),
        },
        "limitations": [
            "Repeated candle zones approximate structure and are not order-book liquidity or resting orders.",
            "A closed-candle decision reacts after confirmation and cannot claim the trigger candle close as an executable fill.",
            "The four-hour horizon does not prove behavior outside the observed window.",
            "Any apparent improvement must survive a later forward-only checkpoint before a rule proposal.",
        ],
    }


def _lab61_blocking_support(item: dict[str, Any]) -> dict[str, Decimal] | None:
    support = item.get("nearest_support")
    if not isinstance(support, dict):
        return None
    entry = _decimal_or_none_any(item.get("entry"))
    target = _decimal_or_none_any(item.get("take_profit"))
    lower = _decimal_or_none_any(support.get("lower"))
    upper = _decimal_or_none_any(support.get("upper"))
    center = _decimal_or_none_any(support.get("center"))
    if entry is None or target is None or lower is None or upper is None:
        return None
    if not target < upper < entry or lower > upper:
        return None
    return {"lower": lower, "upper": upper, "center": center or ((lower + upper) / Decimal("2"))}


def _lab61_is_support_reclaim(candle: PerfCandle, support: dict[str, Decimal]) -> bool:
    intersects = candle.low <= support["upper"] and candle.high >= support["lower"]
    return intersects and candle.close > candle.open and candle.close > support["upper"]


def _lab61_next_fill_candle(
    future: list[PerfCandle],
    *,
    decision_close: datetime,
) -> PerfCandle | None:
    candidates = [candle for candle in future if candle.open_time >= decision_close]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candle: (
            candle.open_time,
            0 if candle.source_interval == "1m" else 1,
            candle.close_time,
        ),
    )


def _lab61_evaluate_dynamic_exit(
    item: dict[str, Any],
    *,
    variant_id: str,
    prepared_future_4h: list[PerfCandle],
) -> dict[str, Any]:
    if variant_id in {"CONTROL_LOGGED", "SUPPORT_FRONT_0_10ATR"}:
        result = _lab60_evaluate_variant(
            item,
            variant_id=variant_id,
            prepared_future_4h=prepared_future_4h,
        )
        return {
            **result,
            "dynamic_action_taken": False,
            "trigger_status": "STATIC_COMPARATOR" if variant_id != "CONTROL_LOGGED" else "CONTROL",
            "trigger_time_utc": None,
            "fill_time_utc": None,
            "fill_price": None,
        }

    control = _lab60_evaluate_variant(
        item,
        variant_id="CONTROL_LOGGED",
        prepared_future_4h=prepared_future_4h,
    )
    entry = _decimal_or_none_any(item.get("entry"))
    risk = _decimal_or_none_any(item.get("risk"))
    stop = _decimal_or_none_any(item.get("stop_loss"))
    target = _decimal_or_none_any(item.get("take_profit"))
    signal_time = _parse_dt(item.get("signal_timestamp"))
    support = _lab61_blocking_support(item)

    def no_action(trigger_status: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            **control,
            "dynamic_action_taken": False,
            "trigger_status": trigger_status,
            "trigger_reason": reason,
            "trigger_time_utc": None,
            "fill_time_utc": None,
            "fill_price": None,
            "control_status": control.get("status"),
            "control_realistic_r": control.get("realistic_r"),
            **extra,
        }

    if entry is None or risk is None or risk <= 0 or stop is None or target is None or signal_time is None:
        return no_action("MISSING_CONTEXT", "Entry, risk, target, stop, or signal time is unavailable.")
    if support is None:
        return no_action("NO_BLOCKING_SUPPORT", "No causal repeated 1h support blocks the logged short target.")
    decision_candles = [
        candle
        for candle in prepared_future_4h
        if candle.source_interval == "15m"
        and candle.open_time >= signal_time
        and candle.close_time <= signal_time + timedelta(hours=4)
    ]
    if not decision_candles:
        return no_action("NO_CLOSED_15M_DECISION_DATA", "No closed futures 15m candle is available after entry.")

    cumulative_mfe = Decimal("0")
    pending_reclaim: PerfCandle | None = None
    for candle in decision_candles:
        cumulative_mfe = max(cumulative_mfe, (entry - candle.low) / risk)
        tp_hit = candle.low <= target
        sl_hit = candle.high >= stop
        if tp_hit or sl_hit:
            return no_action(
                "TERMINAL_BEFORE_DYNAMIC_EXIT",
                "The logged target or stop was touched before a causal dynamic-exit fill could occur.",
                terminal_decision_candle_time_utc=candle.close_time,
                mfe_r_at_terminal=cumulative_mfe,
            )

        decision_candle: PerfCandle | None = None
        trigger_status = ""
        if variant_id == "EXIT_CONFIRMED_SUPPORT_REVERSAL" and pending_reclaim is not None:
            if candle.close > pending_reclaim.high:
                decision_candle = candle
                trigger_status = "CONFIRMED_SUPPORT_REVERSAL"
            pending_reclaim = None

        reclaim = _lab61_is_support_reclaim(candle, support)
        if decision_candle is None and reclaim:
            if variant_id == "EXIT_FIRST_SUPPORT_RECLAIM":
                decision_candle = candle
                trigger_status = "FIRST_SUPPORT_RECLAIM"
            elif variant_id == "EXIT_SUPPORT_RECLAIM_AFTER_0_50R" and cumulative_mfe >= Decimal("0.50"):
                decision_candle = candle
                trigger_status = "SUPPORT_RECLAIM_AFTER_0_50R"
            elif variant_id == "EXIT_CONFIRMED_SUPPORT_REVERSAL":
                pending_reclaim = candle

        if decision_candle is None:
            continue
        fill = _lab61_next_fill_candle(
            prepared_future_4h,
            decision_close=decision_candle.close_time,
        )
        if fill is None:
            return no_action(
                "TRIGGERED_WAITING_NEXT_OPEN",
                "A closed 15m trigger exists, but the next futures candle open is not available yet.",
                trigger_time_utc=decision_candle.close_time,
                trigger_candle={
                    "open": decision_candle.open,
                    "high": decision_candle.high,
                    "low": decision_candle.low,
                    "close": decision_candle.close,
                },
                cumulative_mfe_r=cumulative_mfe,
            )
        ideal_r = (entry - fill.open) / risk
        status = {
            "EXIT_FIRST_SUPPORT_RECLAIM": "EARLY_EXIT_SUPPORT_RECLAIM",
            "EXIT_CONFIRMED_SUPPORT_REVERSAL": "EARLY_EXIT_CONFIRMED_REVERSAL",
            "EXIT_SUPPORT_RECLAIM_AFTER_0_50R": "EARLY_EXIT_RECLAIM_AFTER_0_50R",
        }[variant_id]
        realistic = _realistic_result_fields(
            item,
            entry=entry,
            exit_reference=fill.open,
            risk=risk,
            direction="SHORT",
            ideal_status=status,
            ideal_r=ideal_r,
        )
        return {
            "status": status,
            "result_time_utc": fill.open_time,
            "ideal_r": ideal_r,
            "realistic_r": realistic.get("realistic_realized_r"),
            "entry": entry,
            "stop": stop,
            "target": target,
            "risk": risk,
            "target_rr": (entry - target) / risk,
            "stop_risk_multiple": Decimal("1"),
            "geometry_status": "CONTROL_LOGGED",
            "adjusted": False,
            "dynamic_action_taken": True,
            "trigger_status": trigger_status,
            "trigger_reason": "Closed futures 15m support-reclaim rule passed; fill uses the next candle open.",
            "trigger_time_utc": decision_candle.close_time,
            "fill_time_utc": fill.open_time,
            "fill_price": fill.open,
            "fill_source_interval": fill.source_interval,
            "trigger_candle": {
                "open": decision_candle.open,
                "high": decision_candle.high,
                "low": decision_candle.low,
                "close": decision_candle.close,
            },
            "support_zone": support,
            "cumulative_mfe_r": cumulative_mfe,
            "control_status": control.get("status"),
            "control_realistic_r": control.get("realistic_r"),
        }

    return no_action(
        "NO_DYNAMIC_TRIGGER",
        "No qualifying closed 15m support reclaim completed before the four-hour path ended.",
        cumulative_mfe_r=cumulative_mfe,
    )


def _lab61_dynamic_exit_performance(items: list[dict[str, Any]], variant_id: str) -> dict[str, Any]:
    ordered = sorted(
        items,
        key=lambda item: (
            _parse_dt(item.get("signal_timestamp")) or datetime.min,
            str(item.get("symbol") or ""),
        ),
    )
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    statuses: Counter[str] = Counter()
    trigger_statuses: Counter[str] = Counter()
    for item in ordered:
        results = item.get("_lab61_dynamic_exit_results")
        result = results.get(variant_id) if isinstance(results, dict) else None
        if not isinstance(result, dict):
            statuses["MISSING_CONTEXT"] += 1
            continue
        statuses[str(result.get("status") or "MISSING_CONTEXT")] += 1
        trigger_statuses[str(result.get("trigger_status") or "UNKNOWN")] += 1
        if result.get("realistic_r") is not None:
            pairs.append((item, result))
    values = [Decimal(result["realistic_r"]) for _item, result in pairs]
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    early = [(item, result) for item, result in pairs if result.get("dynamic_action_taken")]
    symbol_counts = Counter(str(item.get("symbol") or "") for item, _result in pairs)
    top_symbol, top_count = symbol_counts.most_common(1)[0] if symbol_counts else (None, 0)
    terminal_count = (
        statuses["TP_HIT"]
        + statuses["SL_HIT"]
        + statuses["BOTH_HIT_SAME_CANDLE"]
        + sum(count for status, count in statuses.items() if status.startswith("EARLY_EXIT_"))
    )
    return {
        "source_count": len(ordered),
        "evaluated_count": len(pairs),
        "waiting_count": statuses["WAITING_4H"],
        "missing_count": statuses["MISSING_CONTEXT"],
        "terminal_count": terminal_count,
        "tp_count": statuses["TP_HIT"],
        "sl_count": statuses["SL_HIT"],
        "both_count": statuses["BOTH_HIT_SAME_CANDLE"],
        "neither_count": statuses["NEITHER_4H"],
        "early_exit_count": len(early),
        "early_exit_positive_count": sum(1 for _item, result in early if Decimal(result["realistic_r"]) > 0),
        "early_exit_negative_count": sum(1 for _item, result in early if Decimal(result["realistic_r"]) < 0),
        "early_exit_nonnegative_count": sum(1 for _item, result in early if Decimal(result["realistic_r"]) >= 0),
        "total_realistic_r": sum(values, Decimal("0")),
        "avg_realistic_r": _avg_decimal(values),
        "median_realistic_r": _percentile_decimal(values, Decimal("0.50")),
        "max_drawdown_r": max_drawdown,
        "status_counts": dict(statuses),
        "trigger_status_counts": dict(trigger_statuses),
        "top_symbol": top_symbol,
        "top_symbol_count": top_count,
        "top_symbol_share_pct": Decimal(top_count) / Decimal(len(pairs)) * Decimal("100") if pairs else None,
    }


def _lab61_dynamic_exit_variant_row(
    *,
    variant_id: str,
    label: str,
    method: str,
    split_items: dict[str, list[dict[str, Any]]],
    control_perf: dict[str, dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    performance = {
        split: _lab61_dynamic_exit_performance(rows, variant_id)
        for split, rows in split_items.items()
    }
    for split in ("all", "train", "validation"):
        current = performance[split]
        control = control_perf[split]
        current["total_realistic_r_delta_vs_control"] = _decimal_delta(
            current.get("total_realistic_r"), control.get("total_realistic_r")
        )
        current["avg_realistic_r_delta_vs_control"] = _decimal_delta(
            current.get("avg_realistic_r"), control.get("avg_realistic_r")
        )
        current["max_drawdown_delta_vs_control"] = _decimal_delta(
            current.get("max_drawdown_r"), control.get("max_drawdown_r")
        )
        current.update(_lab61_dynamic_exit_transition(split_items[split], variant_id))
    row = {
        "variant_id": variant_id,
        "label": label,
        "method": method,
        **performance,
    }
    row["verdict"] = _lab61_variant_verdict(row, min_sample=min_sample)
    return row


def _lab61_dynamic_exit_transition(items: list[dict[str, Any]], variant_id: str) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    saved = Decimal("0")
    sacrificed = Decimal("0")
    loss_statuses = {"SL_HIT", "BOTH_HIT_SAME_CANDLE"}
    for item in items:
        results = item.get("_lab61_dynamic_exit_results")
        if not isinstance(results, dict):
            continue
        control = results.get("CONTROL_LOGGED")
        variant = results.get(variant_id)
        if not isinstance(control, dict) or not isinstance(variant, dict):
            continue
        control_r = _decimal_or_none_any(control.get("realistic_r"))
        variant_r = _decimal_or_none_any(variant.get("realistic_r"))
        if control_r is None or variant_r is None:
            continue
        dynamic = bool(variant.get("dynamic_action_taken"))
        control_status = str(control.get("status") or "")
        if dynamic and control_status == "TP_HIT":
            counts["tp_sacrificed_count"] += 1
            sacrificed += max(Decimal("0"), control_r - variant_r)
        if dynamic and control_status in loss_statuses and variant_r > control_r:
            counts["sl_avoided_count"] += 1
            saved += variant_r - control_r
        if dynamic and control_status not in loss_statuses and variant_r < control_r:
            counts["nonloss_degraded_count"] += 1
        if dynamic and variant_r > control_r:
            counts["improved_row_count"] += 1
        if dynamic and variant_r < control_r:
            counts["degraded_row_count"] += 1
    return {
        "tp_sacrificed_count": counts["tp_sacrificed_count"],
        "sl_avoided_count": counts["sl_avoided_count"],
        "nonloss_degraded_count": counts["nonloss_degraded_count"],
        "improved_row_count": counts["improved_row_count"],
        "degraded_row_count": counts["degraded_row_count"],
        "r_saved_from_control_losses": saved,
        "r_sacrificed_from_control_tps": sacrificed,
    }


def _lab61_variant_verdict(row: dict[str, Any], *, min_sample: int) -> str:
    if row.get("variant_id") == "CONTROL_LOGGED":
        return "CURRENT_CONTROL"
    all_perf = row["all"]
    validation = row["validation"]
    if (
        int(all_perf.get("evaluated_count") or 0) < 120
        or int(validation.get("evaluated_count") or 0) < max(12, min_sample)
    ):
        return "MONITOR_MORE"
    train_delta = _decimal_or_none_any(row["train"].get("avg_realistic_r_delta_vs_control"))
    validation_delta = _decimal_or_none_any(validation.get("avg_realistic_r_delta_vs_control"))
    drawdown_delta = _decimal_or_none_any(validation.get("max_drawdown_delta_vs_control"))
    if (
        train_delta is not None
        and train_delta > 0
        and validation_delta is not None
        and validation_delta > 0
        and drawdown_delta is not None
        and drawdown_delta >= 0
        and int(validation.get("sl_avoided_count") or 0) >= int(validation.get("tp_sacrificed_count") or 0)
    ):
        return "VALIDATION_IMPROVES_RESEARCH_ONLY"
    if validation_delta is not None and validation_delta > 0:
        return "VALIDATION_ONLY_MONITOR"
    if train_delta is not None and train_delta > 0:
        return "TRAIN_ONLY"
    return "NO_CLEAR_GAIN"


def _lab61_study_verdict(readiness_status: str, best_variant: dict[str, Any] | None) -> str:
    if readiness_status != "READY_FOR_READ_ONLY_COMPARISON":
        return "V21_DYNAMIC_EXIT_MONITOR_MORE"
    if best_variant and best_variant.get("verdict") == "VALIDATION_IMPROVES_RESEARCH_ONLY":
        return "DYNAMIC_EXIT_FORWARD_CHECKPOINT_REQUIRED"
    return "NO_DYNAMIC_EXIT_PROMOTION"


def _lab61_recommended_action(readiness_status: str, best_variant: dict[str, Any] | None) -> str:
    if readiness_status != "READY_FOR_READ_ONLY_COMPARISON":
        return "Collect at least 120 closed fixed-cohort outcomes; keep V2.1 exits unchanged."
    if best_variant and best_variant.get("verdict") == "VALIDATION_IMPROVES_RESEARCH_ONLY":
        return "Monitor this definition in a new forward-only shadow lane before proposing any exit-rule change."
    return "Keep the current V2.1 exit behavior; the closed-candle dynamic variants have not justified promotion."


def _lab61_trigger_count(items: list[dict[str, Any]], variant_id: str) -> int:
    return sum(
        1
        for item in items
        if isinstance(item.get("_lab61_dynamic_exit_results"), dict)
        and bool(item["_lab61_dynamic_exit_results"].get(variant_id, {}).get("dynamic_action_taken"))
    )


def _lab61_dynamic_exit_case_row(item: dict[str, Any]) -> dict[str, Any]:
    base = _lab59_case_row(item)
    results = (
        item.get("_lab61_dynamic_exit_results")
        if isinstance(item.get("_lab61_dynamic_exit_results"), dict)
        else {}
    )
    return {
        **base,
        "path_sequence": item.get("_lab60_path_sequence"),
        "dynamic_exit_results": {
            variant_id: {
                "status": result.get("status"),
                "realistic_r": result.get("realistic_r"),
                "dynamic_action_taken": bool(result.get("dynamic_action_taken")),
                "trigger_status": result.get("trigger_status"),
                "trigger_reason": result.get("trigger_reason"),
                "trigger_time_utc": result.get("trigger_time_utc"),
                "fill_time_utc": result.get("fill_time_utc"),
                "fill_price": result.get("fill_price"),
                "fill_source_interval": result.get("fill_source_interval"),
                "cumulative_mfe_r": result.get("cumulative_mfe_r"),
                "control_status": result.get("control_status"),
                "control_realistic_r": result.get("control_realistic_r"),
            }
            for variant_id, result in results.items()
            if isinstance(result, dict)
        },
    }


def _lab56_structure_context(
    item: dict[str, Any],
    *,
    one_hour_candles: list[PerfCandle],
    four_hour_candles: list[PerfCandle],
    config: StructureZoneConfig,
    include_four_hour_confluence: bool = True,
) -> dict[str, Any]:
    signal_time = _parse_dt(item.get("signal_timestamp"))
    entry = _decimal_or_none_any(item.get("entry"))
    unavailable = {
        "zone_config_id": config.config_id,
        "structure_state": "1H_ZONE_UNAVAILABLE",
        "structure_reason": "Signal timestamp or futures entry reference is missing.",
        "atr_1h_at_signal": None,
        "one_hour_history_count": 0,
        "zone_count_1h": 0,
        "nearest_support": None,
        "nearest_resistance": None,
        "nearest_support_distance_atr": None,
        "nearest_resistance_distance_atr": None,
        "four_hour_confluence_status": "FOUR_H_CONTEXT_UNAVAILABLE",
        "four_hour_confluence_reason": "4h context was not evaluated.",
        "_lab56_zones": [],
    }
    if signal_time is None or entry is None or entry <= 0:
        return unavailable
    closed_through_signal = [
        candle for candle in one_hour_candles if candle.close_time <= signal_time
    ]
    signal_candle = closed_through_signal[-1] if closed_through_signal else None
    prior_candle = closed_through_signal[-2] if len(closed_through_signal) >= 2 else None
    atr_1h = _lab56_atr_from_closed(closed_through_signal)
    history = [
        candle
        for candle in one_hour_candles
        if signal_time - timedelta(hours=config.lookback_hours) <= candle.close_time < signal_time
    ]
    zones = _lab56_detect_zones(
        history,
        atr=atr_1h,
        pivot_span=config.pivot_span,
        zone_half_width_atr=config.zone_half_width_atr,
        min_touches=config.min_touches,
        independent_touch_gap=timedelta(hours=4),
        presorted=True,
    )
    if signal_candle is None or prior_candle is None or atr_1h is None or atr_1h <= 0 or len(history) < 24:
        return {
            **unavailable,
            "structure_reason": "At least 24 closed 1h candles plus a valid ATR(14) are required.",
            "atr_1h_at_signal": atr_1h,
            "one_hour_history_count": len(history),
            "zone_count_1h": len(zones),
            "_lab56_zones": zones,
        }
    if not zones:
        return {
            **unavailable,
            "structure_reason": "No repeated 1h pivot zone met the two-touch requirement.",
            "atr_1h_at_signal": atr_1h,
            "one_hour_history_count": len(history),
            "zone_count_1h": 0,
        }
    classification = _lab56_classify_structure(
        entry=entry,
        signal_candle=signal_candle,
        prior_candle=prior_candle,
        zones=zones,
        atr=atr_1h,
    )
    confluence = (
        _lab56_four_hour_confluence(
            entry=entry,
            signal_time=signal_time,
            primary_state=classification["structure_state"],
            primary_zone=classification.get("state_zone"),
            four_hour_candles=four_hour_candles,
        )
        if include_four_hour_confluence
        else {
            "four_hour_confluence_status": "FOUR_H_CONTEXT_NOT_EVALUATED",
            "four_hour_confluence_reason": "4h context is only evaluated for the primary display configuration.",
            "atr_4h_at_signal": None,
            "zone_count_4h": 0,
            "nearest_4h_zone": None,
        }
    )
    return {
        "zone_config_id": config.config_id,
        "atr_1h_at_signal": atr_1h,
        "one_hour_history_count": len(history),
        "zone_count_1h": len(zones),
        **classification,
        **confluence,
        "_lab56_zones": zones,
    }


def _lab56_atr_at_signal(candles: list[PerfCandle], *, signal_time: datetime) -> Decimal | None:
    closed = sorted(
        (candle for candle in candles if candle.close_time <= signal_time),
        key=lambda candle: candle.close_time,
    )
    return _lab56_atr_from_closed(closed)


def _lab56_atr_from_closed(closed: list[PerfCandle]) -> Decimal | None:
    if len(closed) < 15:
        return None
    ranges = _candle_true_ranges(closed)
    values = ranges[-14:]
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else None


def _lab56_detect_zones(
    candles: list[PerfCandle],
    *,
    atr: Decimal | None,
    pivot_span: int,
    zone_half_width_atr: Decimal,
    min_touches: int,
    independent_touch_gap: timedelta,
    presorted: bool = False,
) -> list[dict[str, Any]]:
    ordered = candles if presorted else sorted(candles, key=lambda candle: candle.close_time)
    if atr is None or atr <= 0 or len(ordered) < (pivot_span * 2) + 3:
        return []
    points: list[dict[str, Any]] = []
    for index in range(pivot_span, len(ordered) - pivot_span):
        candle = ordered[index]
        window = ordered[index - pivot_span : index + pivot_span + 1]
        if candle.low == min(row.low for row in window) and (
            candle.low < ordered[index - 1].low or candle.low < ordered[index + 1].low
        ):
            points.append({"price": candle.low, "kind": "LOW", "time": candle.close_time})
        if candle.high == max(row.high for row in window) and (
            candle.high > ordered[index - 1].high or candle.high > ordered[index + 1].high
        ):
            points.append({"price": candle.high, "kind": "HIGH", "time": candle.close_time})
    tolerance = atr * zone_half_width_atr
    clusters: list[list[dict[str, Any]]] = []
    for point in sorted(points, key=lambda row: (Decimal(row["price"]), row["time"])):
        best: list[dict[str, Any]] | None = None
        best_distance: Decimal | None = None
        for cluster in clusters:
            center = sum((Decimal(row["price"]) for row in cluster), Decimal("0")) / Decimal(len(cluster))
            distance = abs(Decimal(point["price"]) - center)
            if distance <= tolerance and (best_distance is None or distance < best_distance):
                best = cluster
                best_distance = distance
        if best is None:
            clusters.append([point])
        else:
            best.append(point)

    zones: list[dict[str, Any]] = []
    for cluster in clusters:
        independent: list[dict[str, Any]] = []
        for point in sorted(cluster, key=lambda row: row["time"]):
            if not independent or point["time"] - independent[-1]["time"] >= independent_touch_gap:
                independent.append(point)
        if len(independent) < min_touches:
            continue
        center = sum((Decimal(point["price"]) for point in independent), Decimal("0")) / Decimal(len(independent))
        low_touches = sum(1 for point in independent if point["kind"] == "LOW")
        high_touches = sum(1 for point in independent if point["kind"] == "HIGH")
        latest = max(independent, key=lambda point: point["time"])
        zones.append(
            {
                "center": center,
                "lower": center - tolerance,
                "upper": center + tolerance,
                "touch_count": len(independent),
                "support_touch_count": low_touches,
                "resistance_touch_count": high_touches,
                "origin_role": (
                    "ROLE_FLIP"
                    if low_touches and high_touches
                    else "SUPPORT_ORIGIN"
                    if low_touches
                    else "RESISTANCE_ORIGIN"
                ),
                "latest_pivot_kind": latest["kind"],
                "first_touch_time": min(point["time"] for point in independent),
                "last_touch_time": latest["time"],
            }
        )
    return sorted(zones, key=lambda zone: Decimal(zone["center"]))


def _lab56_classify_structure(
    *,
    entry: Decimal,
    signal_candle: PerfCandle,
    prior_candle: PerfCandle,
    zones: list[dict[str, Any]],
    atr: Decimal,
) -> dict[str, Any]:
    nearest_support = max(
        (zone for zone in zones if Decimal(zone["center"]) <= entry),
        key=lambda zone: Decimal(zone["center"]),
        default=None,
    )
    nearest_resistance = min(
        (zone for zone in zones if Decimal(zone["center"]) > entry),
        key=lambda zone: Decimal(zone["center"]),
        default=None,
    )
    support_distance = _lab56_distance_to_zone(entry, nearest_support, atr)
    resistance_distance = _lab56_distance_to_zone(entry, nearest_resistance, atr)

    failed_reclaim = min(
        (
            zone
            for zone in zones
            if prior_candle.close < Decimal(zone["lower"])
            and signal_candle.close > Decimal(zone["upper"])
        ),
        key=lambda zone: abs(Decimal(zone["center"]) - entry),
        default=None,
    )
    if failed_reclaim is not None:
        state = "1H_FAILED_BREAK_RECLAIM"
        reason = "The prior candle was below a repeated zone, but the signal candle reclaimed above it."
        state_zone = failed_reclaim
    else:
        break_retest = min(
            (
                zone
                for zone in zones
                if prior_candle.close < Decimal(zone["lower"])
                and signal_candle.high >= Decimal(zone["lower"])
                and signal_candle.close < Decimal(zone["lower"])
            ),
            key=lambda zone: abs(Decimal(zone["center"]) - entry),
            default=None,
        )
        support_break = min(
            (
                zone
                for zone in zones
                if prior_candle.close >= Decimal(zone["lower"])
                and signal_candle.close < Decimal(zone["lower"])
            ),
            key=lambda zone: abs(Decimal(zone["center"]) - entry),
            default=None,
        )
        resistance_rejection = min(
            (
                zone
                for zone in zones
                if int(zone.get("resistance_touch_count") or 0) > 0
                and signal_candle.open < Decimal(zone["lower"])
                and signal_candle.high >= Decimal(zone["lower"])
                and signal_candle.close < Decimal(zone["lower"])
            ),
            key=lambda zone: abs(Decimal(zone["center"]) - entry),
            default=None,
        )
        if break_retest is not None:
            state = "1H_BREAK_RETEST_REJECTED"
            reason = "Price stayed below broken support after a retest into the repeated zone."
            state_zone = break_retest
        elif support_break is not None:
            state = "1H_SUPPORT_BREAK"
            reason = "The signal candle closed below a repeated zone held by the prior candle."
            state_zone = support_break
        elif resistance_rejection is not None:
            state = "1H_RESISTANCE_REJECTED"
            reason = "The signal candle probed repeated resistance and closed back below the zone."
            state_zone = resistance_rejection
        elif support_distance is not None and support_distance <= Decimal("0.15"):
            state = "AT_1H_SUPPORT"
            reason = "The short entry is inside or within 0.15 ATR above repeated 1h support."
            state_zone = nearest_support
        elif resistance_distance is not None and resistance_distance <= Decimal("0.15"):
            state = "AT_1H_RESISTANCE"
            reason = "The short entry is inside or within 0.15 ATR below repeated 1h resistance."
            state_zone = nearest_resistance
        else:
            state = "1H_MID_RANGE"
            reason = "No immediate repeated 1h support or resistance interaction was detected."
            state_zone = None
    return {
        "structure_state": state,
        "structure_reason": reason,
        "nearest_support": _lab56_public_zone(nearest_support),
        "nearest_resistance": _lab56_public_zone(nearest_resistance),
        "nearest_support_distance_atr": support_distance,
        "nearest_resistance_distance_atr": resistance_distance,
        "state_zone": _lab56_public_zone(state_zone),
    }


def _lab56_distance_to_zone(
    entry: Decimal,
    zone: dict[str, Any] | None,
    atr: Decimal,
) -> Decimal | None:
    if zone is None or atr <= 0:
        return None
    lower = Decimal(zone["lower"])
    upper = Decimal(zone["upper"])
    if lower <= entry <= upper:
        return Decimal("0")
    return min(abs(entry - lower), abs(entry - upper)) / atr


def _lab56_public_zone(zone: dict[str, Any] | None) -> dict[str, Any] | None:
    if zone is None:
        return None
    return {key: value for key, value in zone.items() if not str(key).startswith("_")}


def _lab56_four_hour_confluence(
    *,
    entry: Decimal,
    signal_time: datetime,
    primary_state: str,
    primary_zone: dict[str, Any] | None,
    four_hour_candles: list[PerfCandle],
) -> dict[str, Any]:
    atr_4h = _lab56_atr_at_signal(four_hour_candles, signal_time=signal_time)
    history = [
        candle
        for candle in four_hour_candles
        if signal_time - timedelta(days=45) <= candle.close_time < signal_time
    ]
    zones = _lab56_detect_zones(
        history,
        atr=atr_4h,
        pivot_span=2,
        zone_half_width_atr=Decimal("0.35"),
        min_touches=2,
        independent_touch_gap=timedelta(hours=16),
        presorted=True,
    )
    if atr_4h is None or not zones:
        return {
            "four_hour_confluence_status": "FOUR_H_CONTEXT_UNAVAILABLE",
            "four_hour_confluence_reason": "Repeated closed 4h zones or ATR(14) are unavailable.",
            "atr_4h_at_signal": atr_4h,
            "zone_count_4h": len(zones),
            "nearest_4h_zone": None,
        }
    nearest = min(zones, key=lambda zone: _lab56_distance_to_zone(entry, zone, atr_4h) or Decimal("0"))
    nearest_distance = _lab56_distance_to_zone(entry, nearest, atr_4h)
    overlaps = bool(
        primary_zone
        and any(
            Decimal(zone["lower"]) <= Decimal(primary_zone["upper"])
            and Decimal(zone["upper"]) >= Decimal(primary_zone["lower"])
            for zone in zones
        )
    )
    short_aligned_states = {
        "AT_1H_RESISTANCE",
        "1H_RESISTANCE_REJECTED",
        "1H_SUPPORT_BREAK",
        "1H_BREAK_RETEST_REJECTED",
    }
    if overlaps and primary_state in short_aligned_states:
        status = "ALIGNED_WITH_4H_RESISTANCE"
        reason = "The active 1h short structure overlaps a repeated 4h zone."
    elif (
        Decimal(nearest["center"]) <= entry
        and nearest_distance is not None
        and nearest_distance <= Decimal("0.25")
    ):
        status = "CONFLICT_WITH_4H_SUPPORT"
        reason = "Entry is on or immediately above a repeated 4h support zone."
    else:
        status = "NO_4H_CONFLUENCE"
        reason = "No nearby 4h zone aligns with or directly conflicts with the 1h setup."
    return {
        "four_hour_confluence_status": status,
        "four_hour_confluence_reason": reason,
        "atr_4h_at_signal": atr_4h,
        "zone_count_4h": len(zones),
        "nearest_4h_zone": _lab56_public_zone(nearest),
        "nearest_4h_zone_distance_atr": nearest_distance,
    }


def _lab56_bucket_row(
    bucket: str,
    *,
    field: str,
    split_items: dict[str, list[dict[str, Any]]],
    baselines: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = {
        split: [item for item in items if str(item.get(field) or "") == bucket]
        for split, items in split_items.items()
    }
    return {
        "bucket": bucket,
        "all": _walk_forward_perf(rows["all"], baseline=baselines["all"]),
        "train": _walk_forward_perf(rows["train"], baseline=baselines["train"]),
        "validation": _walk_forward_perf(rows["validation"], baseline=baselines["validation"]),
    }


def _lab56_gate_row(
    *,
    gate_id: str,
    label: str,
    allowed_states: tuple[str, ...],
    split_items: dict[str, list[dict[str, Any]]],
    baselines: dict[str, dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    selected = {
        split: [item for item in items if str(item.get("structure_state") or "") in allowed_states]
        for split, items in split_items.items()
    }
    fixed = {
        split: _lab56_fixed_cohort_perf(split_items[split], selected[split])
        for split in ("all", "train", "validation")
    }
    row = {
        "gate_id": gate_id,
        "label": label,
        "allowed_states": list(allowed_states),
        "all": fixed["all"],
        "train": fixed["train"],
        "validation": fixed["validation"],
        "selected_performance": {
            split: _walk_forward_perf(selected[split], baseline=baselines[split])
            for split in ("all", "train", "validation")
        },
    }
    row["verdict"] = _lab56_gate_verdict(row, min_sample=min_sample)
    return row


def _lab56_fixed_cohort_perf(
    source_items: list[dict[str, Any]],
    selected_items: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_keys = {_lab55_item_key(item) for item in selected_items}
    closed = [
        item
        for item in source_items
        if item.get("result_status") in COMPLETED_OUTCOMES and item.get("realistic_realized_r") is not None
    ]
    closed.sort(
        key=lambda item: (
            _parse_dt(item.get("result_time_utc"))
            or _parse_dt(item.get("signal_timestamp"))
            or datetime.min,
            str(item.get("symbol") or ""),
        )
    )
    values: list[Decimal] = []
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    baseline_cumulative = Decimal("0")
    baseline_peak = Decimal("0")
    baseline_max_drawdown = Decimal("0")
    selected_closed = []
    for item in closed:
        entered = _lab55_item_key(item) in selected_keys
        value = Decimal(item["realistic_realized_r"]) if entered else Decimal("0")
        baseline_value = Decimal(item["realistic_realized_r"])
        values.append(value)
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
        baseline_cumulative += baseline_value
        baseline_peak = max(baseline_peak, baseline_cumulative)
        baseline_max_drawdown = min(
            baseline_max_drawdown,
            baseline_cumulative - baseline_peak,
        )
        if entered:
            selected_closed.append(item)
    baseline_total = sum((Decimal(item["realistic_realized_r"]) for item in closed), Decimal("0"))
    baseline_avg = baseline_total / Decimal(len(closed)) if closed else None
    fixed_avg = cumulative / Decimal(len(closed)) if closed else None
    baseline_tp = [item for item in closed if item.get("result_status") == "TP_HIT"]
    baseline_sl = [item for item in closed if item.get("result_status") == "SL_HIT"]
    selected_tp = [item for item in selected_closed if item.get("result_status") == "TP_HIT"]
    selected_sl = [item for item in selected_closed if item.get("result_status") == "SL_HIT"]
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in selected_items)
    top_symbol, top_count = symbols.most_common(1)[0] if symbols else (None, 0)
    return {
        "source_count": len(source_items),
        "source_closed_count": len(closed),
        "entered_count": len(selected_items),
        "entered_closed_count": len(selected_closed),
        "filtered_no_entry_count": len(source_items) - len(selected_items),
        "retention_pct": _retention(len(selected_items), len(source_items)),
        "tp_retained_count": len(selected_tp),
        "tp_lost_count": len(baseline_tp) - len(selected_tp),
        "sl_retained_count": len(selected_sl),
        "sl_avoided_count": len(baseline_sl) - len(selected_sl),
        "both_retained_count": sum(1 for item in selected_closed if item.get("result_status") == "BOTH_HIT_SAME_CANDLE"),
        "fixed_total_realistic_r": cumulative,
        "fixed_avg_realistic_r": fixed_avg,
        "fixed_median_realistic_r": _median_decimal(values),
        "fixed_max_drawdown_r": max_drawdown,
        "baseline_total_realistic_r": baseline_total,
        "baseline_avg_realistic_r": baseline_avg,
        "baseline_max_drawdown_r": baseline_max_drawdown,
        "fixed_total_r_delta_vs_baseline": cumulative - baseline_total,
        "fixed_avg_r_delta_vs_baseline": (
            fixed_avg - baseline_avg if fixed_avg is not None and baseline_avg is not None else None
        ),
        "top_symbol": top_symbol,
        "top_symbol_count": top_count,
        "top_symbol_share_pct": (
            Decimal(top_count) / Decimal(len(selected_items)) * Decimal("100") if selected_items else None
        ),
    }


def _lab56_gate_verdict(row: dict[str, Any], *, min_sample: int) -> str:
    train = row["train"]
    validation = row["validation"]
    required = max(6, min_sample // 2)
    if (
        int(validation.get("source_closed_count") or 0) < required
        or int(validation.get("entered_closed_count") or 0) < max(3, required // 3)
    ):
        return "STRUCTURE_NEEDS_MORE_SAMPLE"
    train_delta = _decimal_or_none_any(train.get("fixed_avg_r_delta_vs_baseline"))
    validation_delta = _decimal_or_none_any(validation.get("fixed_avg_r_delta_vs_baseline"))
    validation_total = _decimal_or_none_any(validation.get("fixed_total_realistic_r"))
    if (
        train_delta is not None
        and train_delta > 0
        and validation_delta is not None
        and validation_delta >= Decimal("0.05")
        and validation_total is not None
        and validation_total > 0
        and int(validation.get("sl_avoided_count") or 0) >= int(validation.get("tp_lost_count") or 0)
    ):
        return "STRUCTURE_VALIDATION_IMPROVES"
    if validation_delta is not None and validation_delta > 0:
        return "STRUCTURE_REDUCES_DAMAGE_ONLY"
    if train_delta is not None and train_delta > 0 and (validation_delta is None or validation_delta <= 0):
        return "STRUCTURE_TRAIN_ONLY"
    return "STRUCTURE_NO_CLEAR_GAIN"


def _lab56_select_config_from_train(config_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row
        for row in config_rows
        if row.get("not_conflicted_gate", {}).get("train", {}).get("fixed_avg_r_delta_vs_baseline") is not None
        and int(row.get("not_conflicted_gate", {}).get("train", {}).get("entered_closed_count") or 0) >= 3
    ]
    return max(
        candidates,
        key=lambda row: (
            Decimal(row["not_conflicted_gate"]["train"]["fixed_avg_r_delta_vs_baseline"]),
            int(row["not_conflicted_gate"]["train"].get("entered_closed_count") or 0),
        ),
        default=None,
    )


def _lab56_study_verdict(selected_gate: dict[str, Any] | None, *, min_sample: int) -> str:
    if selected_gate is None:
        return "STRUCTURE_NEEDS_MORE_SAMPLE"
    return _lab56_gate_verdict(selected_gate, min_sample=min_sample)


def _lab56_recommended_action(verdict: str) -> str:
    return {
        "STRUCTURE_VALIDATION_IMPROVES": (
            "Keep the train-selected zone configuration in read-only shadow monitoring; do not change the live gate."
        ),
        "STRUCTURE_REDUCES_DAMAGE_ONLY": (
            "Collect another chronological checkpoint; the zone gate reduces damage but is not independently positive."
        ),
        "STRUCTURE_TRAIN_ONLY": (
            "Reject promotion because the apparent train improvement did not survive validation."
        ),
        "STRUCTURE_NO_CLEAR_GAIN": (
            "Do not add structure to the live gate; continue collecting MID_SHORT 1h outcomes."
        ),
        "STRUCTURE_NEEDS_MORE_SAMPLE": (
            "Wait for more closed validation paths before judging the 1h structure hypothesis."
        ),
    }.get(verdict, "Keep the live rule frozen.")


def _lab56_cohort_row(
    cohort_id: str,
    items: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    return {
        "cohort_id": cohort_id,
        "performance": _walk_forward_perf(items, baseline=baseline),
        "state_counts": dict(Counter(str(item.get("structure_state") or "UNKNOWN") for item in items)),
    }


def _lab56_case_row(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    evidence = item.get("evidence_snapshot") if isinstance(item.get("evidence_snapshot"), dict) else {}
    return {
        "signal_id": item.get("signal_id"),
        "symbol": item.get("symbol"),
        "signal_timestamp": item.get("signal_timestamp"),
        "signal_time_wib": item.get("signal_time_wib"),
        "entry": item.get("entry"),
        "stop_loss": item.get("stop_loss"),
        "take_profit": item.get("take_profit"),
        "result_status": item.get("result_status"),
        "realistic_realized_r": item.get("realistic_realized_r"),
        "structure_state": item.get("structure_state"),
        "structure_reason": item.get("structure_reason"),
        "atr_1h_at_signal": item.get("atr_1h_at_signal"),
        "one_hour_history_count": item.get("one_hour_history_count"),
        "zone_count_1h": item.get("zone_count_1h"),
        "nearest_support": item.get("nearest_support"),
        "nearest_resistance": item.get("nearest_resistance"),
        "nearest_support_distance_atr": item.get("nearest_support_distance_atr"),
        "nearest_resistance_distance_atr": item.get("nearest_resistance_distance_atr"),
        "state_zone": item.get("state_zone"),
        "four_hour_confluence_status": item.get("four_hour_confluence_status"),
        "four_hour_confluence_reason": item.get("four_hour_confluence_reason"),
        "nearest_4h_zone": item.get("nearest_4h_zone"),
        "taker_sell_ratio": evidence.get("kline_taker_sell_ratio"),
        "detail_href": f"/signals/{item.get('symbol')}?signal_id={item.get('signal_id')}",
    }


def _lab56_zone_chart_payload(
    item: dict[str, Any],
    *,
    candles: list[PerfCandle],
) -> dict[str, Any] | None:
    signal_time = _parse_dt(item.get("signal_timestamp"))
    entry = _decimal_or_none_any(item.get("entry"))
    stop = _decimal_or_none_any(item.get("stop_loss"))
    target = _decimal_or_none_any(item.get("take_profit"))
    if signal_time is None or entry is None or stop is None or target is None:
        return None
    visible = [
        candle
        for candle in candles
        if signal_time - timedelta(hours=168) <= candle.open_time <= signal_time + timedelta(hours=4)
    ]
    if not visible:
        return None
    result_time = _parse_dt(item.get("result_time_utc"))
    end_time = min(
        max((candle.close_time for candle in visible), default=signal_time),
        signal_time + timedelta(hours=4),
    )
    return {
        "market": "futures",
        "price_source": "futures_klines_1h",
        "display_interval": "1h_closed",
        "candle_count": len(visible),
        "signal_time": signal_time,
        "signal_time_wib": _wib_string(signal_time),
        "result_time": result_time,
        "result_time_wib": _wib_string(result_time),
        "box_end_time": result_time or end_time,
        "direction": "SHORT",
        "result_status": item.get("result_status"),
        "entry": entry,
        "stop_loss": stop,
        "take_profit": target,
        "latest_price": visible[-1].close,
        "latest_candle_time": visible[-1].close_time,
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
            for candle in visible
        ],
        "structure_zones": [
            {
                **_lab56_public_zone(zone),
                "start_time": max(
                    _parse_dt(zone.get("first_touch_time")) or visible[0].open_time,
                    visible[0].open_time,
                ),
                "end_time": end_time,
            }
            for zone in item.get("_lab56_zones", [])
            if Decimal(zone["upper"]) >= min(candle.low for candle in visible)
            and Decimal(zone["lower"]) <= max(candle.high for candle in visible)
        ],
    }


def _lab55_item_key(item: dict[str, Any]) -> tuple[str, str]:
    signal_time = _parse_dt(item.get("signal_timestamp"))
    return str(item.get("signal_id") or ""), signal_time.isoformat() if signal_time is not None else ""


def _lab55_confirmation_context(
    item: dict[str, Any],
    candles: list[PerfCandle],
) -> tuple[PerfCandle | None, Decimal | None, Decimal | None]:
    signal_time = _parse_dt(item.get("signal_timestamp"))
    entry = _decimal_or_none_any(item.get("entry"))
    if signal_time is None or entry is None or entry <= 0:
        return None, None, None
    confirmation = next(
        (
            candle
            for candle in sorted(candles, key=lambda row: row.open_time)
            if candle.source_interval == "15m"
            and candle.open_time >= signal_time
            and candle.open_time < signal_time + timedelta(minutes=15)
        ),
        None,
    )
    if confirmation is None:
        return None, None, None
    return_pct = (confirmation.close - entry) / entry * Decimal("100")
    buy = confirmation.taker_buy_base_volume
    sell = confirmation.taker_sell_base_volume
    taker_sell_ratio = sell / (buy + sell) if buy is not None and sell is not None and buy + sell > 0 else None
    return confirmation, return_pct, taker_sell_ratio


def _lab55_confirmation_gate(
    config_id: str,
    *,
    return_pct: Decimal | None,
    taker_sell_ratio: Decimal | None,
) -> tuple[bool, str]:
    if config_id == "WAIT_15M_ALWAYS":
        return True, "Confirmation candle closed; delay-only variant enters."
    if return_pct is None:
        return False, "Confirmation return is unavailable."
    if config_id == "VETO_UP_REVERSAL_0_05":
        passed = return_pct < Decimal("0.05")
        return passed, "No +0.05% upward reversal." if passed else "Confirmation reversed upward by at least 0.05%."
    if config_id == "CONFIRM_CLOSE_BELOW_ENTRY":
        passed = return_pct < 0
        return passed, "Confirmation closed below signal entry." if passed else "Confirmation did not close below signal entry."
    if config_id == "CONFIRM_BELOW_ENTRY_TAKER_SELL_52":
        if taker_sell_ratio is None:
            return False, "Confirmation taker split is unavailable."
        passed = return_pct < 0 and taker_sell_ratio >= Decimal("0.52")
        return (
            passed,
            "Direction and taker-sell confirmation passed."
            if passed
            else "Direction or confirmation taker-sell threshold did not pass.",
        )
    return False, "Unknown confirmation configuration."


def _lab55_evaluate_confirmation_config(
    item: dict[str, Any],
    *,
    candles: list[PerfCandle],
    config_id: str,
) -> dict[str, Any]:
    signal_time = _parse_dt(item.get("signal_timestamp"))
    original_entry = _decimal_or_none_any(item.get("entry"))
    original_stop = _decimal_or_none_any(item.get("stop_loss"))
    original_target = _decimal_or_none_any(item.get("take_profit"))
    risk = _decimal_or_none_any(item.get("risk"))
    rr = _decimal_or_none_any(item.get("rr"))
    if rr is None and None not in (original_entry, original_target, risk) and risk != 0:
        rr = abs(Decimal(original_target) - Decimal(original_entry)) / Decimal(risk)
    confirmation, return_pct, taker_sell_ratio = _lab55_confirmation_context(item, candles)
    confirmation_fields = {
        "confirmation_time_utc": confirmation.close_time if confirmation is not None else None,
        "confirmation_time_wib": _wib_string(confirmation.close_time) if confirmation is not None else None,
        "confirmation_open": confirmation.open if confirmation is not None else None,
        "confirmation_high": confirmation.high if confirmation is not None else None,
        "confirmation_low": confirmation.low if confirmation is not None else None,
        "confirmation_close": confirmation.close if confirmation is not None else None,
        "confirmation_return_pct": return_pct,
        "confirmation_return_bucket": _mid_short_first_return_bucket(return_pct),
        "confirmation_taker_sell_ratio": taker_sell_ratio,
    }
    if signal_time is None or original_entry is None or original_stop is None or original_target is None or risk is None or risk <= 0 or rr is None:
        return {
            **confirmation_fields,
            "status": "MISSING_CONTEXT",
            "entered": False,
            "gate_reason": "Signal entry, risk, target, or timestamp is unavailable.",
            "realistic_r": None,
        }

    if config_id == "CONTROL_IMMEDIATE":
        entry_time = signal_time
        entry = original_entry
        stop = original_stop
        target = original_target
        gate_reason = "Immediate control uses the logged signal entry."
    else:
        if confirmation is None:
            return {
                **confirmation_fields,
                "status": "MISSING_CONFIRMATION",
                "entered": False,
                "gate_reason": "The first closed 15m candle after signal is unavailable.",
                "realistic_r": None,
            }
        passed, gate_reason = _lab55_confirmation_gate(
            config_id,
            return_pct=return_pct,
            taker_sell_ratio=taker_sell_ratio,
        )
        if not passed:
            return {
                **confirmation_fields,
                "status": "FILTERED_NO_ENTRY",
                "entered": False,
                "gate_reason": gate_reason,
                "realistic_r": None,
            }
        entry_time = confirmation.close_time
        entry = confirmation.close
        stop = entry + risk
        target = entry - (risk * rr)

    ordered = sorted(candles, key=lambda candle: candle.open_time)
    future = [
        candle
        for candle in ordered
        if candle.open_time >= entry_time and candle.close_time <= entry_time + timedelta(hours=4)
    ]
    evidence = item.get("evidence_snapshot") if isinstance(item.get("evidence_snapshot"), dict) else {}
    assumptions = _realistic_assumptions(entry=entry, risk=risk, evidence_snapshot=evidence)
    shadow_item = {
        **item,
        **assumptions,
        "signal_timestamp": entry_time,
        "entry": entry,
        "stop_loss": stop,
        "take_profit": target,
        "risk": risk,
        "rr": rr,
    }
    result = _mid_short_counterfactual_exit(
        shadow_item,
        candles=[],
        risk_scale=Decimal("1"),
        target_rr=None,
        protect_at_r=None,
        use_logged_target=True,
        prepared_future_4h=future,
        require_complete_horizon_for_neither=True,
    )
    return {
        **confirmation_fields,
        **result,
        "entered": True,
        "entry_time_utc": entry_time,
        "entry_time_wib": _wib_string(entry_time),
        "gate_reason": gate_reason,
        "rr": rr,
    }


def _lab55_confirmation_performance(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    status_counts = Counter(str(result.get("status") or "UNKNOWN") for _item, result in pairs)
    evaluated = [(item, result) for item, result in pairs if result.get("realistic_r") is not None]
    values = [Decimal(result["realistic_r"]) for _item, result in evaluated]
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    symbol_counts = Counter(str(item.get("symbol") or "") for item, _result in evaluated)
    top_symbol, top_count = symbol_counts.most_common(1)[0] if symbol_counts else (None, 0)
    closed_count = (
        status_counts.get("TP_HIT", 0)
        + status_counts.get("SL_HIT", 0)
        + status_counts.get("BOTH_HIT_SAME_CANDLE", 0)
    )
    entered_count = sum(1 for _item, result in pairs if result.get("entered"))
    return {
        "source_count": len(pairs),
        "entered_count": entered_count,
        "filtered_count": status_counts.get("FILTERED_NO_ENTRY", 0),
        "missing_confirmation_count": status_counts.get("MISSING_CONFIRMATION", 0),
        "waiting_count": status_counts.get("WAITING_4H", 0),
        "evaluated_count": len(evaluated),
        "closed_count": closed_count,
        "tp_count": status_counts.get("TP_HIT", 0),
        "sl_count": status_counts.get("SL_HIT", 0),
        "both_count": status_counts.get("BOTH_HIT_SAME_CANDLE", 0),
        "neither_count": status_counts.get("NEITHER_4H", 0),
        "total_realistic_r": sum(values, Decimal("0")),
        "avg_realistic_r": _avg_decimal(values),
        "median_realistic_r": _percentile_decimal(values, Decimal("0.50")),
        "max_drawdown_r": max_drawdown,
        "sample_retention_pct": Decimal(entered_count) / Decimal(len(pairs)) * Decimal("100") if pairs else None,
        "tp_share_pct_closed": (
            Decimal(status_counts.get("TP_HIT", 0)) / Decimal(closed_count) * Decimal("100") if closed_count else None
        ),
        "sl_share_pct_closed": (
            Decimal(status_counts.get("SL_HIT", 0) + status_counts.get("BOTH_HIT_SAME_CANDLE", 0))
            / Decimal(closed_count)
            * Decimal("100")
            if closed_count
            else None
        ),
        "top_symbol": top_symbol,
        "top_symbol_count": top_count,
        "top_symbol_share_pct": Decimal(top_count) / Decimal(len(evaluated)) * Decimal("100") if evaluated else None,
    }


def _lab55_confirmation_tradeoff(
    control_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    variant_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, int]:
    control_by_key = {_lab55_item_key(item): result for item, result in control_pairs}
    counts: Counter[str] = Counter()
    for item, variant in variant_pairs:
        control = control_by_key.get(_lab55_item_key(item), {})
        control_status = str(control.get("status") or "")
        variant_status = str(variant.get("status") or "")
        filtered = variant_status == "FILTERED_NO_ENTRY"
        if control_status == "TP_HIT" and filtered:
            counts["lost_tp_count"] += 1
        if control_status in LAB55_LOSS_STATUSES and filtered:
            counts["avoided_sl_count"] += 1
        if control_status == "TP_HIT" and variant_status == "TP_HIT":
            counts["retained_tp_count"] += 1
        if control_status == "TP_HIT" and variant_status in LAB55_LOSS_STATUSES:
            counts["tp_to_sl_count"] += 1
        if control_status in LAB55_LOSS_STATUSES and variant_status == "TP_HIT":
            counts["sl_to_tp_count"] += 1
        if control_status in LAB55_LOSS_STATUSES and variant_status in LAB55_LOSS_STATUSES:
            counts["retained_sl_count"] += 1
    return {
        "lost_tp_count": counts["lost_tp_count"],
        "avoided_sl_count": counts["avoided_sl_count"],
        "retained_tp_count": counts["retained_tp_count"],
        "tp_to_sl_count": counts["tp_to_sl_count"],
        "sl_to_tp_count": counts["sl_to_tp_count"],
        "retained_sl_count": counts["retained_sl_count"],
    }


def _lab55_confirmation_bucket_rows(
    items: list[dict[str, Any]],
    *,
    control_results: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    bucket_order = ("UP_STRONG", "UP", "FLAT", "DOWN", "DOWN_STRONG", "MISSING_FORWARD_DATA")
    output: list[dict[str, Any]] = []
    for bucket in bucket_order:
        rows = [
            (item, control_results[_lab55_item_key(item)])
            for item in items
            if control_results[_lab55_item_key(item)].get("confirmation_return_bucket") == bucket
        ]
        if not rows:
            continue
        perf = _lab55_confirmation_performance(rows)
        output.append(
            {
                "bucket": bucket,
                "sample_count": len(rows),
                "wrong_direction_1h_count": sum(
                    1 for item, _result in rows if item.get("direction_1h") == "WRONG_DIRECTION"
                ),
                "logged_tp_count": sum(1 for item, _result in rows if item.get("result_status") == "TP_HIT"),
                "logged_sl_count": sum(1 for item, _result in rows if item.get("result_status") == "SL_HIT"),
                "control_4h_tp_count": perf["tp_count"],
                "control_4h_sl_count": perf["sl_count"] + perf["both_count"],
                "control_4h_neither_count": perf["neither_count"],
                "control_4h_avg_realistic_r": perf["avg_realistic_r"],
                "read": _lab55_confirmation_bucket_read(bucket, perf),
            }
        )
    return output


def _lab55_confirmation_bucket_read(bucket: str, perf: dict[str, Any]) -> str:
    if int(perf.get("evaluated_count") or 0) < 10:
        return "SMALL_SAMPLE"
    if bucket in {"UP_STRONG", "UP"} and int(perf.get("sl_count") or 0) + int(perf.get("both_count") or 0) > int(perf.get("tp_count") or 0):
        return "UPWARD_CONFIRMATION_LOSS_HEAVY"
    if bucket in {"DOWN", "DOWN_STRONG"} and int(perf.get("tp_count") or 0) > int(perf.get("sl_count") or 0) + int(perf.get("both_count") or 0):
        return "SHORT_CONFIRMATION_HEALTHIER"
    return "MIXED_PATH"


def _lab55_confirmation_case_rows(
    items: list[dict[str, Any]],
    *,
    results_by_config: dict[str, dict[tuple[str, str], dict[str, Any]]],
    limit: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in sorted(
        items,
        key=lambda row: (_parse_dt(row.get("signal_timestamp")) or datetime.min, str(row.get("symbol") or "")),
        reverse=True,
    )[:limit]:
        key = _lab55_item_key(item)
        control = results_by_config["CONTROL_IMMEDIATE"][key]
        output.append(
            {
                "signal_id": item.get("signal_id"),
                "symbol": item.get("symbol"),
                "signal_timestamp": item.get("signal_timestamp"),
                "signal_time_wib": item.get("signal_time_wib"),
                "logged_result_status": item.get("result_status"),
                "failure_primary_cause": item.get("failure_primary_cause"),
                "original_entry": item.get("entry"),
                "original_stop": item.get("stop_loss"),
                "original_target": item.get("take_profit"),
                "original_risk": item.get("risk"),
                "original_rr": item.get("rr"),
                "confirmation_time_utc": control.get("confirmation_time_utc"),
                "confirmation_time_wib": control.get("confirmation_time_wib"),
                "confirmation_open": control.get("confirmation_open"),
                "confirmation_high": control.get("confirmation_high"),
                "confirmation_low": control.get("confirmation_low"),
                "confirmation_close": control.get("confirmation_close"),
                "confirmation_return_pct": control.get("confirmation_return_pct"),
                "confirmation_return_bucket": control.get("confirmation_return_bucket"),
                "confirmation_taker_sell_ratio": control.get("confirmation_taker_sell_ratio"),
                "results": {
                    config_id: _lab55_case_result(results[key])
                    for config_id, results in results_by_config.items()
                },
            }
        )
    return output


def _lab55_case_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "entered": result.get("entered"),
        "gate_reason": result.get("gate_reason"),
        "entry_time_utc": result.get("entry_time_utc"),
        "entry_time_wib": result.get("entry_time_wib"),
        "entry": result.get("entry"),
        "stop": result.get("stop"),
        "target": result.get("target"),
        "realistic_r": result.get("realistic_r"),
        "result_time_utc": result.get("result_time_utc"),
        "mfe_r": result.get("mfe_r"),
        "mae_r": result.get("mae_r"),
    }


def _lab55_confirmation_variant_verdict(
    row: dict[str, Any],
    *,
    control: dict[str, dict[str, Any]],
    min_sample: int,
) -> str:
    if row.get("config_id") == "CONTROL_IMMEDIATE":
        return "CURRENT_CONTROL"
    train = row["train"]
    validation = row["validation"]
    if (
        int(train.get("evaluated_count") or 0) < max(10, min_sample)
        or int(validation.get("evaluated_count") or 0) < max(10, min_sample // 2)
    ):
        return "CONFIRMATION_NEEDS_MORE_SAMPLE"
    train_delta = _decimal_delta(train.get("avg_realistic_r"), control["train"].get("avg_realistic_r"))
    validation_delta = _decimal_delta(
        validation.get("avg_realistic_r"),
        control["validation"].get("avg_realistic_r"),
    )
    drawdown_delta = _decimal_delta(
        validation.get("max_drawdown_r"),
        control["validation"].get("max_drawdown_r"),
    )
    if (
        train_delta is not None
        and train_delta > 0
        and validation_delta is not None
        and validation_delta > 0
        and Decimal(validation.get("total_realistic_r") or 0) > 0
        and (drawdown_delta is None or drawdown_delta >= 0)
    ):
        return "CONFIRMATION_VALIDATION_IMPROVES"
    if validation_delta is not None and validation_delta > 0:
        return "CONFIRMATION_REDUCES_DAMAGE_ONLY"
    if train_delta is not None and train_delta > 0:
        return "CONFIRMATION_TRAIN_ONLY"
    return "CONFIRMATION_NO_IMPROVEMENT"


def _lab55_confirmation_study_verdict(best: dict[str, Any] | None) -> str:
    if best is None:
        return "CONFIRMATION_NEEDS_MORE_SAMPLE"
    verdict = str(best.get("verdict") or "")
    if verdict == "CONFIRMATION_VALIDATION_IMPROVES":
        return "CONFIRMATION_VALIDATION_IMPROVES"
    if verdict == "CONFIRMATION_REDUCES_DAMAGE_ONLY":
        return "CONFIRMATION_REDUCES_DAMAGE_ONLY"
    if verdict == "CONFIRMATION_TRAIN_ONLY":
        return "CONFIRMATION_TRAIN_ONLY"
    if verdict == "CONFIRMATION_NEEDS_MORE_SAMPLE":
        return "CONFIRMATION_NEEDS_MORE_SAMPLE"
    return "CONFIRMATION_NO_CLEAR_GAIN"


def _lab55_confirmation_recommended_action(verdict: str) -> str:
    return {
        "CONFIRMATION_VALIDATION_IMPROVES": (
            "Keep the best confirmation variant in shadow for another forward checkpoint; do not change live entry yet."
        ),
        "CONFIRMATION_REDUCES_DAMAGE_ONLY": (
            "Monitor more samples; the confirmation reduces some damage but does not yet justify a rule change."
        ),
        "CONFIRMATION_TRAIN_ONLY": (
            "Do not promote. The apparent improvement did not hold in chronological validation."
        ),
        "CONFIRMATION_NEEDS_MORE_SAMPLE": (
            "Collect more completed four-hour paths before judging delayed entry."
        ),
        "CONFIRMATION_NO_CLEAR_GAIN": (
            "Keep immediate entry unchanged; current confirmation variants do not improve validation."
        ),
    }.get(verdict, "Keep Signal Factory entry logic frozen.")


def _lab52_data_derived_thresholds(tp_items: list[dict[str, Any]]) -> dict[str, Any]:
    specs = {
        "atr_inflated_q75": ("atr_vs_30_median", Decimal("0.75")),
        "late_entry_q75": ("pre_entry_4h_move_atr", Decimal("0.75")),
        "forward_range_q25": ("forward_1h_realized_range_atr", Decimal("0.25")),
        "taker_delta_q25": ("taker_sell_delta_1h", Decimal("0.25")),
        "forward_volume_q25": ("forward_1h_volume_vs_pre30", Decimal("0.25")),
        "forward_oi_q25": ("forward_1h_oi_change_pct", Decimal("0.25")),
    }
    output: dict[str, Any] = {}
    for name, (field, percentile) in specs.items():
        values = [value for item in tp_items if (value := _decimal_or_none_any(item.get(field))) is not None]
        output[name] = {
            "field": field,
            "percentile": percentile,
            "value": _percentile_decimal(values, percentile),
            "available_count": len(values),
            "source": "TP_HIT control cohort in the current page filters",
        }
    return output


def _lab52_hypothesis_flags(item: dict[str, Any], *, thresholds: dict[str, Any]) -> list[str]:
    flags: list[str] = []

    def threshold(name: str) -> Decimal | None:
        row = thresholds.get(name) if isinstance(thresholds.get(name), dict) else {}
        return _decimal_or_none_any(row.get("value"))

    atr_ratio = _decimal_or_none_any(item.get("atr_vs_30_median"))
    atr_limit = threshold("atr_inflated_q75")
    if atr_ratio is not None and atr_limit is not None and atr_ratio >= atr_limit and atr_ratio > Decimal("1"):
        flags.append("ATR_INFLATED")

    pre_move = _decimal_or_none_any(item.get("pre_entry_4h_move_atr"))
    late_limit = threshold("late_entry_q75")
    if pre_move is not None and late_limit is not None and pre_move > 0 and pre_move >= max(Decimal("0"), late_limit):
        flags.append("LATE_ENTRY_EXTENSION")

    forward_range = _decimal_or_none_any(item.get("forward_1h_realized_range_atr"))
    range_limit = threshold("forward_range_q25")
    if forward_range is not None and range_limit is not None and forward_range <= range_limit:
        flags.append("VOLATILITY_CONTRACTION")

    if bool(item.get("support_before_target")):
        flags.append("STRUCTURE_BLOCK")

    momentum_checks = (
        ("taker_sell_delta_1h", "taker_delta_q25"),
        ("forward_1h_volume_vs_pre30", "forward_volume_q25"),
        ("forward_1h_oi_change_pct", "forward_oi_q25"),
    )
    available = 0
    weak = 0
    for field, threshold_name in momentum_checks:
        value = _decimal_or_none_any(item.get(field))
        limit = threshold(threshold_name)
        if value is None or limit is None:
            continue
        available += 1
        weak += int(value <= limit)
    if available >= 2 and weak >= 2:
        flags.append("MOMENTUM_DECAY")

    if not flags:
        flags.append("RR_GEOMETRY_MISMATCH")
    return flags


def _lab52_primary_hypothesis(flags: list[str]) -> str:
    precedence = (
        "STRUCTURE_BLOCK",
        "ATR_INFLATED",
        "LATE_ENTRY_EXTENSION",
        "VOLATILITY_CONTRACTION",
        "MOMENTUM_DECAY",
        "RR_GEOMETRY_MISMATCH",
    )
    return next((value for value in precedence if value in flags), "RR_GEOMETRY_MISMATCH")


def _lab52_metric_comparison_row(
    *,
    field: str,
    label: str,
    target_items: list[dict[str, Any]],
    tp_items: list[dict[str, Any]],
    other_sl_items: list[dict[str, Any]],
) -> dict[str, Any]:
    target = _lab52_distribution(target_items, field)
    tp = _lab52_distribution(tp_items, field)
    other_sl = _lab52_distribution(other_sl_items, field)
    return {
        "field": field,
        "label": label,
        "target_too_far": target,
        "tp_control": tp,
        "other_sl": other_sl,
        "median_delta_vs_tp": _decimal_delta(target.get("median"), tp.get("median")),
    }


def _lab52_distribution(items: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [value for item in items if (value := _decimal_or_none_any(item.get(field))) is not None]
    return {
        "sample_count": len(items),
        "available_count": len(values),
        "q1": _percentile_decimal(values, Decimal("0.25")),
        "median": _percentile_decimal(values, Decimal("0.50")),
        "q3": _percentile_decimal(values, Decimal("0.75")),
    }


def _lab52_counterfactual_rows(
    closed: list[dict[str, Any]],
    *,
    target_items: list[dict[str, Any]],
    min_sample: int,
) -> list[dict[str, Any]]:
    ordered = sorted(closed, key=lambda item: (_parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol") or "")))
    split_index = max(1, min(len(ordered), int(len(ordered) * 0.70))) if ordered else 0
    train = ordered[:split_index]
    validation = ordered[split_index:]
    control_validation = _lab52_counterfactual_performance(validation, "CONTROL_LOGGED")
    rows: list[dict[str, Any]] = []
    for config_id, label, risk_scale, target_rr, protect_at_r, use_logged_target in LAB52_COUNTERFACTUAL_SPECS:
        all_perf = _lab52_counterfactual_performance(ordered, config_id)
        train_perf = _lab52_counterfactual_performance(train, config_id)
        validation_perf = _lab52_counterfactual_performance(validation, config_id)
        target_perf = _lab52_counterfactual_performance(target_items, config_id)
        rows.append(
            {
                "config_id": config_id,
                "label": label,
                "risk_scale": risk_scale,
                "target_rr": target_rr,
                "protect_at_r": protect_at_r,
                "use_logged_target": use_logged_target,
                "evaluation_horizon": "4h fixed cohort",
                "all": all_perf,
                "train": train_perf,
                "validation": validation_perf,
                "target_too_far_subset": target_perf,
                "validation_avg_r_delta_vs_control": _decimal_delta(
                    validation_perf.get("avg_realistic_r"),
                    control_validation.get("avg_realistic_r"),
                ),
                "verdict": _lab52_counterfactual_verdict(
                    config_id=config_id,
                    train=train_perf,
                    validation=validation_perf,
                    control_validation=control_validation,
                    min_sample=min_sample,
                ),
            }
        )
    return rows


def _lab52_counterfactual_performance(items: list[dict[str, Any]], config_id: str) -> dict[str, Any]:
    rows = []
    for item in items:
        configs = item.get("_lab52_counterfactuals") if isinstance(item.get("_lab52_counterfactuals"), dict) else {}
        result = configs.get(config_id) if isinstance(configs.get(config_id), dict) else None
        if result and result.get("realistic_r") is not None:
            rows.append((item, result))
    status_counts = Counter(str(result.get("status") or "UNKNOWN") for _item, result in rows)
    values = [Decimal(result["realistic_r"]) for _item, result in rows]
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    symbol_counts = Counter(str(item.get("symbol") or "") for item, _result in rows)
    top_symbol, top_count = symbol_counts.most_common(1)[0] if symbol_counts else (None, 0)
    return {
        "sample_count": len(rows),
        "tp_count": status_counts.get("TP_HIT", 0),
        "sl_count": status_counts.get("SL_HIT", 0),
        "both_count": status_counts.get("BOTH_HIT_SAME_CANDLE", 0),
        "breakeven_count": status_counts.get("BREAKEVEN_PROTECTED", 0),
        "neither_count": status_counts.get("NEITHER_4H", 0),
        "total_realistic_r": sum(values, Decimal("0")),
        "avg_realistic_r": _avg_decimal(values),
        "median_realistic_r": _percentile_decimal(values, Decimal("0.50")),
        "max_drawdown_r": max_drawdown,
        "sl_share_pct": (
            Decimal(status_counts.get("SL_HIT", 0) + status_counts.get("BOTH_HIT_SAME_CANDLE", 0))
            / Decimal(len(rows))
            * Decimal("100")
            if rows
            else None
        ),
        "top_symbol": top_symbol,
        "top_symbol_count": top_count,
        "top_symbol_share_pct": Decimal(top_count) / Decimal(len(rows)) * Decimal("100") if rows else None,
    }


def _lab52_counterfactual_verdict(
    *,
    config_id: str,
    train: dict[str, Any],
    validation: dict[str, Any],
    control_validation: dict[str, Any],
    min_sample: int,
) -> str:
    if config_id == "CONTROL_LOGGED":
        return "CURRENT_CONTROL"
    if int(validation.get("sample_count") or 0) < max(10, min_sample // 2):
        return "NEEDS_MORE_SAMPLE"
    validation_delta = _decimal_delta(validation.get("avg_realistic_r"), control_validation.get("avg_realistic_r"))
    train_delta = _decimal_delta(train.get("avg_realistic_r"), Decimal("0"))
    if validation_delta is not None and validation_delta > 0 and Decimal(validation.get("total_realistic_r") or 0) > 0:
        return "VALIDATION_IMPROVES_FIXED_COHORT"
    if train_delta is not None and train_delta > 0:
        return "TRAIN_ONLY_IMPROVEMENT"
    return "NO_CLEAR_IMPROVEMENT"


def _lab52_case_row(item: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "signal_id", "symbol", "signal_timestamp", "signal_time_wib", "entry", "stop_loss", "take_profit", "rr",
        "result_time_wib", "mfe_before_first_hit_r", "mae_before_first_hit_r", "first_hit_candle_index",
        "atr_1h_at_entry", "atr_pct_entry", "logged_risk_atr_ratio", "atr_30_median", "atr_vs_30_median",
        "atr_signal_inflation_ratio", "signal_true_range_atr", "signal_tr_contribution_pct",
        "pre_entry_1h_move_atr", "pre_entry_4h_move_atr", "support_price_proxy", "support_distance_r",
        "support_before_target", "forward_1h_realized_range_atr", "forward_1h_mfe_r", "forward_1h_mae_r",
        "entry_taker_sell_ratio", "forward_1h_taker_sell_ratio", "taker_sell_delta_1h", "entry_volume_ratio",
        "forward_1h_volume_vs_pre30", "entry_oi_change_pct", "forward_1h_oi_change_pct", "oi_change_delta_1h",
        "time_to_0_25r_minutes", "time_to_0_50r_minutes", "time_to_0_75r_minutes", "time_to_1_00r_minutes",
        "time_to_1_25r_minutes", "time_to_1_50r_minutes", "target_distance_context_status",
        "target_distance_primary_hypothesis", "target_distance_hypotheses",
    )
    return {field: item.get(field) for field in fields}


def _lab52_hypothesis_read(hypothesis: str) -> str:
    return {
        "ATR_INFLATED": "ATR signal berada di tail atas TP control, sehingga jarak target ikut membesar.",
        "LATE_ENTRY_EXTENSION": "Harga sudah bergerak jauh sebelum entry relatif ATR; ruang lanjutan mengecil.",
        "VOLATILITY_CONTRACTION": "Range 1h setelah entry berada di tail bawah TP control.",
        "STRUCTURE_BLOCK": "Proxy support 1h berada di antara entry dan target.",
        "MOMENTUM_DECAY": "Minimal dua dari taker, volume, dan OI forward lebih lemah dari TP control.",
        "RR_GEOMETRY_MISMATCH": "Tidak ada blocker tunggal; target 1.5R tetap lebih jauh daripada gerak yang tersedia.",
    }.get(hypothesis, "Hipotesis belum tersedia.")


def _lab52_study_verdict(
    *,
    target_count: int,
    dominant_count: int,
    counterfactual_rows: list[dict[str, Any]],
    min_sample: int,
) -> str:
    if target_count < min_sample:
        return "TARGET_DISTANCE_NEEDS_MORE_SAMPLE"
    improved = [row for row in counterfactual_rows if row.get("verdict") == "VALIDATION_IMPROVES_FIXED_COHORT"]
    if improved and dominant_count >= max(3, target_count // 3):
        return "TARGET_DISTANCE_HAS_TESTABLE_HYPOTHESIS"
    if improved:
        return "EXIT_GEOMETRY_IMPROVES_FIXED_COHORT_MONITOR"
    return "TARGET_DISTANCE_NO_CLEAN_FIX_YET"


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

    after_sl_would_hit_tp_within_4h = bool(
        after_sl_would_hit_tp
        and after_sl_tp_time is not None
        and after_sl_tp_time <= signal_time + timedelta(hours=4)
    )

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
        "after_sl_would_hit_tp_within_4h": after_sl_would_hit_tp_within_4h,
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
        "after_sl_would_hit_tp_within_4h": False,
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


SL_FAILURE_RESEARCH_ACTIONS = {
    "STOP_TOO_TIGHT": "Uji shadow stop ATR yang sedikit lebih lebar dengan target dan biaya tetap sama.",
    "TARGET_TOO_FAR": "Uji band target atau profit-protection secara shadow; jangan mengubah TP live dulu.",
    "REGIME_CONFLICT": "Uji filter shadow yang menahan short saat BTC atau ETH 1h bullish.",
    "LATE_ENTRY": "Uji batas extension dan entry-delay setelah impuls turun yang sudah terlalu jauh.",
    "WRONG_DIRECTION": "Perkuat evidence arah dan counterfactual reverse; jangan membalik signal secara otomatis.",
    "NO_FOLLOWTHROUGH": "Minta konfirmasi sell follow-through tambahan sebelum menaikkan candidate menjadi signal.",
    "MIXED_UNRESOLVED": "Kumpulkan sample dan bedah chart; belum ada satu penyebab dominan yang terukur.",
}

SL_FAILURE_EVIDENCE_STRENGTH = {
    "STOP_TOO_TIGHT": "PATH_CONFIRMED",
    "TARGET_TOO_FAR": "PATH_CONFIRMED",
    "REGIME_CONFLICT": "CONTEXT_SUPPORTED",
    "LATE_ENTRY": "EVIDENCE_SUPPORTED",
    "WRONG_DIRECTION": "PATH_SUPPORTED",
    "NO_FOLLOWTHROUGH": "PATH_SUPPORTED",
    "MIXED_UNRESOLVED": "UNRESOLVED",
}


def _mid_short_sl_failure_classification(item: dict[str, Any]) -> dict[str, Any]:
    if str(item.get("result_status") or "") != "SL_HIT":
        return {
            "failure_primary_cause": "NOT_SL",
            "failure_cause_reason": None,
            "failure_contributors": [],
            "failure_evidence_strength": "NOT_APPLICABLE",
            "failure_research_action": None,
            "reverse_proxy_bucket": None,
            "reverse_clean_proxy": False,
            "entry_overextended_bucket": _entry_overextended(item),
        }

    reverse = _reverse_proxy(item)
    entry_bucket = _entry_overextended(item)
    direction_15m = str(item.get("direction_15m") or "")
    direction_1h = str(item.get("direction_1h") or "")
    direction_2h = str(item.get("direction_2h") or "")
    first_hit_index = int(item.get("first_hit_candle_index") or 0)
    mfe_before_hit = _decimal_or_none_any(item.get("mfe_before_first_hit_r"))
    regime_conflict = _mid_short_btc_eth_pull_up(item)
    persistent_wrong = direction_1h == "WRONG_DIRECTION" and direction_2h == "WRONG_DIRECTION"
    late_entry = entry_bucket != "ENTRY_EXTENSION_OK" and (
        first_hit_index <= 2 or direction_15m == "WRONG_DIRECTION"
    )
    no_followthrough = (
        (mfe_before_hit is not None and mfe_before_hit < Decimal("0.25"))
        or direction_15m in {"WRONG_DIRECTION", "FLAT"}
    )

    contributors: list[str] = []
    if item.get("after_sl_would_hit_tp_within_4h"):
        contributors.append("STOP_TOO_TIGHT")
    if item.get("tp_near_before_sl"):
        contributors.append("TARGET_TOO_FAR")
    if regime_conflict:
        contributors.append("REGIME_CONFLICT")
    if late_entry:
        contributors.append("LATE_ENTRY")
    if reverse.get("reverse_clean_proxy") or persistent_wrong:
        contributors.append("WRONG_DIRECTION")
    if no_followthrough:
        contributors.append("NO_FOLLOWTHROUGH")

    if item.get("after_sl_would_hit_tp_within_4h"):
        cause = "STOP_TOO_TIGHT"
        reason = "SL tersentuh lebih dulu, tetapi target awal kemudian tersentuh dalam jalur 4h yang sama."
        strength = "PATH_CONFIRMED"
    elif item.get("tp_near_before_sl"):
        cause = "TARGET_TOO_FAR"
        reason = "Harga sempat bergerak minimal +0.75R ke arah short sebelum berbalik dan menyentuh SL."
        strength = "PATH_CONFIRMED"
    elif regime_conflict and direction_1h == "WRONG_DIRECTION":
        cause = "REGIME_CONFLICT"
        reason = "Short bergerak salah arah saat BTC atau ETH berada dalam regime bullish 1h."
        strength = "CONTEXT_SUPPORTED"
    elif late_entry:
        cause = "LATE_ENTRY"
        reason = f"Entry sudah berada pada bucket {entry_bucket} dan bergerak adverse dalam dua candle pertama."
        strength = "EVIDENCE_SUPPORTED"
    elif reverse.get("reverse_clean_proxy") or persistent_wrong:
        cause = "WRONG_DIRECTION"
        reason = "Arah 1h/2h tetap melawan short atau jalur reverse mencapai target proxy tanpa stop proxy."
        strength = "PATH_SUPPORTED"
    elif no_followthrough:
        cause = "NO_FOLLOWTHROUGH"
        reason = "Gerak favorable sebelum SL kurang dari +0.25R atau candle awal tidak melanjutkan tekanan jual."
        strength = "PATH_SUPPORTED"
    else:
        cause = "MIXED_UNRESOLVED"
        reason = "Tidak ada satu pola path, regime, extension, atau reverse yang cukup dominan."
        strength = "UNRESOLVED"

    return {
        "failure_primary_cause": cause,
        "failure_cause_reason": reason,
        "failure_contributors": contributors,
        "failure_evidence_strength": strength,
        "failure_research_action": SL_FAILURE_RESEARCH_ACTIONS[cause],
        "reverse_proxy_bucket": reverse["bucket"],
        "reverse_clean_proxy": reverse["reverse_clean_proxy"],
        "reverse_mfe_r": reverse["reverse_mfe_r"],
        "reverse_mae_r": reverse["reverse_mae_r"],
        "entry_overextended_bucket": entry_bucket,
    }


def _mid_short_sl_failure_cause_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sl_items = [item for item in items if item.get("result_status") == "SL_HIT"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cause in SL_FAILURE_RESEARCH_ACTIONS:
        groups[cause] = []
    for item in sl_items:
        groups[str(item.get("failure_primary_cause") or "MIXED_UNRESOLVED")].append(item)

    rows: list[dict[str, Any]] = []
    for cause, cause_items in groups.items():
        mfe_values = [
            value
            for value in (_decimal_or_none_any(item.get("mfe_before_first_hit_r")) for item in cause_items)
            if value is not None
        ]
        mae_values = [
            value
            for value in (_decimal_or_none_any(item.get("mae_before_first_hit_r")) for item in cause_items)
            if value is not None
        ]
        hit_indexes = [
            Decimal(str(item.get("first_hit_candle_index")))
            for item in cause_items
            if item.get("first_hit_candle_index") is not None
        ]
        rows.append(
            {
                "cause": cause,
                "label": cause,
                "sl_count": len(cause_items),
                "sl_share_pct": _pct(len(cause_items), len(sl_items)),
                "median_mfe_before_sl_r": _median_decimal(mfe_values),
                "median_mae_before_sl_r": _median_decimal(mae_values),
                "median_first_hit_candle_index": _median_decimal(hit_indexes),
                "after_sl_target_within_4h_count": sum(
                    1 for item in cause_items if item.get("after_sl_would_hit_tp_within_4h")
                ),
                "tp_near_before_sl_count": sum(1 for item in cause_items if item.get("tp_near_before_sl")),
                "reverse_clean_count": sum(1 for item in cause_items if item.get("reverse_clean_proxy")),
                "regime_conflict_count": sum(
                    1 for item in cause_items if "REGIME_CONFLICT" in (item.get("failure_contributors") or [])
                ),
                "overextended_count": sum(
                    1
                    for item in cause_items
                    if item.get("entry_overextended_bucket") != "ENTRY_EXTENSION_OK"
                ),
                "evidence_strength": SL_FAILURE_EVIDENCE_STRENGTH[cause],
                "research_action": SL_FAILURE_RESEARCH_ACTIONS.get(cause),
            }
        )
    rows.sort(key=lambda row: (int(row["sl_count"]), str(row["cause"])), reverse=True)
    return rows


def _mid_short_failure_cause_read(summary: dict[str, Any], *, min_sample: int) -> str:
    sl_count = int(summary.get("sl_count") or 0)
    if sl_count == 0:
        return "NO_SL_IN_SCOPE"
    if sl_count < min_sample:
        return "WAIT_MORE_CLOSED_SAMPLE"
    cause = str(summary.get("dominant_failure_cause") or "MIXED_UNRESOLVED")
    return f"SL_PRIMARY_{cause}"


def _mid_short_sl_failure_cause_summary(
    items: list[dict[str, Any]],
    *,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    sl_items = [item for item in items if item.get("result_status") == "SL_HIT"]
    unresolved = sum(1 for item in sl_items if item.get("failure_primary_cause") == "MIXED_UNRESOLVED")
    dominant = next((row for row in rows if int(row.get("sl_count") or 0) > 0), None)
    return {
        "sl_count": len(sl_items),
        "classified_sl_count": len(sl_items) - unresolved,
        "unresolved_sl_count": unresolved,
        "classification_coverage_pct": _pct(len(sl_items) - unresolved, len(sl_items)),
        "dominant_failure_cause": dominant.get("cause") if dominant else None,
        "dominant_failure_count": int(dominant.get("sl_count") or 0) if dominant else 0,
        "dominant_failure_share_pct": dominant.get("sl_share_pct") if dominant else None,
        "cause_count": len(rows),
        "method": "mutually_exclusive_primary_hypothesis_with_multi_label_contributors",
    }


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
