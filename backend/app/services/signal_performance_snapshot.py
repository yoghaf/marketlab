from __future__ import annotations

import json
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import (
    COMPLETED_OUTCOMES,
    EVIDENCE_FIELDS,
    SignalCandidatePerformanceService,
    aggregate_signal_performance_items,
    build_misidentification_audit_payload,
    build_one_hour_filter_candidate_study_payload,
    build_one_hour_v4_shadow_monitor_payload,
    build_one_hour_walk_forward_payload,
    build_v3_shadow_filter_map,
)
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import json_safe, utcnow


DEFAULT_SIGNAL_PERFORMANCE_SNAPSHOT_DIR = REPO_ROOT / "backend" / "artifacts" / "signal_performance" / "live"
PERFORMANCE_FILE = "performance_closed.json"
PERFORMANCE_COMPACT_FILE = "performance_closed_compact.json"
FORWARD_INTEGRITY_FILE = "forward_integrity.json"
PERFORMANCE_1H_FILE = "performance_closed_1h.json"
PERFORMANCE_1H_COMPACT_FILE = "performance_closed_1h_compact.json"
FORWARD_INTEGRITY_1H_FILE = "forward_integrity_1h.json"
MID_SHORT_FILTER_COMBO_1H_FILE = "mid_short_filter_combination_1h.json"
QUALITY_LAB_FILE = "quality_lab.json"
MID_SHORT_SHADOW_FORWARD_1H_FILE = "mid_short_shadow_forward_1h.json"
MID_SHORT_FAILURE_ANATOMY_1H_FILE = "mid_short_failure_anatomy_1h.json"
MID_SHORT_SECOND_FILTER_1H_FILE = "mid_short_second_filter_1h.json"
MID_SHORT_TAKER_SELL_DEEP_DIVE_1H_FILE = "mid_short_taker_sell_deep_dive_1h.json"
MID_SHORT_WRONG_DIRECTION_DEEP_DIVE_1H_FILE = "mid_short_wrong_direction_deep_dive_1h.json"
MID_SHORT_ENTRY_CONFIRMATION_1H_FILE = "mid_short_entry_confirmation_1h.json"
MID_SHORT_STRUCTURE_ZONE_1H_FILE = "mid_short_structure_zone_1h.json"
MID_SHORT_V21_STRUCTURE_INTERACTION_1H_FILE = "mid_short_v21_structure_interaction_1h.json"
MID_SHORT_V21_STRUCTURE_EXIT_1H_FILE = "mid_short_v21_structure_exit_1h.json"
MID_SHORT_V21_DYNAMIC_EXIT_1H_FILE = "mid_short_v21_dynamic_exit_1h.json"
MID_SHORT_VOLUME_SAFE_1H_FILE = "mid_short_volume_safe_1h.json"
DEFAULT_PERFORMANCE_LIMIT = 500
DEFAULT_PERFORMANCE_1H_LIMIT = 5000
DEFAULT_PERFORMANCE_COMPACT_LIMIT = 100
DEFAULT_FORWARD_INTEGRITY_LIMIT = 200
DEFAULT_MID_SHORT_FILTER_COMBO_LIMIT = 100
DEFAULT_MID_SHORT_FILTER_COMBO_MIN_SAMPLE = 20
DEFAULT_QUALITY_LAB_LIMIT = 100
DEFAULT_RESEARCH_LIMIT = 150
DEFAULT_RESEARCH_MIN_SAMPLE = 20

DEFAULT_SIGNAL_RESEARCH_LIST_KEYS = (
    "items",
    "latest_pass_signals",
    "latest_fail_signals",
    "latest_missing_signals",
    "latest_unavailable_signals",
    "latest_not_applicable_signals",
    "latest_sl_signals",
    "latest_tp_signals",
    "latest_open_signals",
    "top_filter_items",
    "case_rows",
    "top_filter_pass_signals",
    "top_filter_fail_signals",
    "top_filter_missing_signals",
    "baseline_path_rows",
    "pass_taxonomy_rows",
    "fail_taxonomy_rows",
    "filter_rows",
    "combination_rows",
    "candidate_rows",
)

QUALITY_LAB_LIST_KEYS = (
    "best_signals",
    "worst_signals",
    "open_signals",
    "top_symbols",
    "weak_symbols",
    "by_stage",
    "by_confidence",
    "by_timeframe",
    "by_volume_rank",
    "evidence_fields",
)


class SignalPerformanceSnapshotRunner:
    """Persist default Signal History payloads so the web page does not recompute them on open."""

    def __init__(self, db: Session, artifact_dir: Path = DEFAULT_SIGNAL_PERFORMANCE_SNAPSHOT_DIR) -> None:
        self.db = db
        self.artifact_dir = artifact_dir

    def run(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        performance_limit: int = DEFAULT_PERFORMANCE_LIMIT,
        forward_integrity_limit: int = DEFAULT_FORWARD_INTEGRITY_LIMIT,
        scope: str = "all",
    ) -> dict[str, Any]:
        if scope not in {"all", "default", "one-hour", "mid-short-research"}:
            raise ValueError("scope must be 'all', 'default', 'one-hour', or 'mid-short-research'")

        service = SignalCandidatePerformanceService(self.db)
        generated_at = utcnow().isoformat()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        result: dict[str, Any] = {
            "generated_at_utc": generated_at,
            "artifact_dir": str(self.artifact_dir),
            "scope": scope,
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
        }

        if scope in {"all", "default"}:
            performance = _with_snapshot_meta(
                _performance_payload(service, epoch=epoch, timeframe=None, limit=max(1, performance_limit)),
                generated_at_utc=generated_at,
                source="signal_performance_snapshot",
                filename=PERFORMANCE_FILE,
            )
            forward_integrity = _with_snapshot_meta(
                _forward_integrity_payload(
                    service,
                    epoch=epoch,
                    timeframe=None,
                    limit=max(1, forward_integrity_limit),
                ),
                generated_at_utc=generated_at,
                source="signal_forward_integrity_snapshot",
                filename=FORWARD_INTEGRITY_FILE,
            )
            quality_lab = _with_snapshot_meta(
                service.quality_lab(
                    epoch=epoch,
                    include_watch_only=False,
                    position_lock=True,
                    stage=None,
                    timeframe=None,
                    min_sample=5,
                    limit=DEFAULT_QUALITY_LAB_LIMIT,
                ),
                generated_at_utc=generated_at,
                source="signal_quality_lab_snapshot",
                filename=QUALITY_LAB_FILE,
            )
            _atomic_write_json(self.artifact_dir / PERFORMANCE_FILE, json_safe(performance))
            _atomic_write_json(
                self.artifact_dir / PERFORMANCE_COMPACT_FILE,
                json_safe(
                    _compact_snapshot_payload(
                        performance,
                        filename=PERFORMANCE_COMPACT_FILE,
                        limit=DEFAULT_PERFORMANCE_COMPACT_LIMIT,
                        list_keys=("items",),
                    )
                ),
            )
            _atomic_write_json(self.artifact_dir / FORWARD_INTEGRITY_FILE, json_safe(forward_integrity))
            _atomic_write_json(self.artifact_dir / QUALITY_LAB_FILE, json_safe(quality_lab))
            result.update(
                {
                    "performance_path": str(self.artifact_dir / PERFORMANCE_FILE),
                    "performance_compact_path": str(self.artifact_dir / PERFORMANCE_COMPACT_FILE),
                    "forward_integrity_path": str(self.artifact_dir / FORWARD_INTEGRITY_FILE),
                    "quality_lab_path": str(self.artifact_dir / QUALITY_LAB_FILE),
                    "performance_items": len(performance.get("items") or []),
                    "performance_compact_items": min(
                        len(performance.get("items") or []),
                        DEFAULT_PERFORMANCE_COMPACT_LIMIT,
                    ),
                    "forward_integrity_items": len(forward_integrity.get("items") or []),
                    "quality_lab_items": len(quality_lab.get("best_signals") or []),
                }
            )

        if scope in {"all", "one-hour"}:
            performance_1h = _with_snapshot_meta(
                _performance_payload(
                    service,
                    epoch=epoch,
                    timeframe="1h",
                    limit=max(DEFAULT_PERFORMANCE_1H_LIMIT, performance_limit),
                ),
                generated_at_utc=generated_at,
                source="signal_performance_snapshot_1h",
                filename=PERFORMANCE_1H_FILE,
            )
            forward_integrity_1h = _with_snapshot_meta(
                _forward_integrity_payload(
                    service,
                    epoch=epoch,
                    timeframe="1h",
                    limit=max(1, forward_integrity_limit),
                ),
                generated_at_utc=generated_at,
                source="signal_forward_integrity_snapshot_1h",
                filename=FORWARD_INTEGRITY_1H_FILE,
            )
            _atomic_write_json(self.artifact_dir / PERFORMANCE_1H_FILE, json_safe(performance_1h))
            _atomic_write_json(
                self.artifact_dir / PERFORMANCE_1H_COMPACT_FILE,
                json_safe(
                    _compact_snapshot_payload(
                        performance_1h,
                        filename=PERFORMANCE_1H_COMPACT_FILE,
                        limit=DEFAULT_PERFORMANCE_COMPACT_LIMIT,
                        list_keys=("items",),
                    )
                ),
            )
            _atomic_write_json(self.artifact_dir / FORWARD_INTEGRITY_1H_FILE, json_safe(forward_integrity_1h))
            mid_short_filter_combo = _with_snapshot_meta(
                service.mid_short_1h_filter_combination_study(
                    epoch=epoch,
                    include_watch_only=False,
                    position_lock=True,
                    min_sample=DEFAULT_MID_SHORT_FILTER_COMBO_MIN_SAMPLE,
                    limit=DEFAULT_MID_SHORT_FILTER_COMBO_LIMIT,
                ),
                generated_at_utc=generated_at,
                source="mid_short_filter_combination_snapshot_1h",
                filename=MID_SHORT_FILTER_COMBO_1H_FILE,
            )
            _atomic_write_json(
                self.artifact_dir / MID_SHORT_FILTER_COMBO_1H_FILE,
                json_safe(mid_short_filter_combo),
            )
            result.update(
                {
                    "performance_1h_path": str(self.artifact_dir / PERFORMANCE_1H_FILE),
                    "performance_1h_compact_path": str(self.artifact_dir / PERFORMANCE_1H_COMPACT_FILE),
                    "forward_integrity_1h_path": str(self.artifact_dir / FORWARD_INTEGRITY_1H_FILE),
                    "mid_short_filter_combo_1h_path": str(self.artifact_dir / MID_SHORT_FILTER_COMBO_1H_FILE),
                    "performance_1h_items": len(performance_1h.get("items") or []),
                    "performance_1h_compact_items": min(
                        len(performance_1h.get("items") or []),
                        DEFAULT_PERFORMANCE_COMPACT_LIMIT,
                    ),
                    "forward_integrity_1h_items": len(forward_integrity_1h.get("items") or []),
                    "mid_short_filter_combo_1h_rows": len(mid_short_filter_combo.get("combination_rows") or []),
                }
            )

        if scope == "mid-short-research":
            mid_short_research = _mid_short_research_payloads(
                service,
                epoch=epoch,
                generated_at_utc=generated_at,
            )
            for filename, payload in mid_short_research.items():
                _atomic_write_json(self.artifact_dir / filename, json_safe(payload))
            result.update(
                {
                    "mid_short_research_artifacts": len(mid_short_research),
                    "mid_short_research_files": sorted(mid_short_research.keys()),
                }
            )

        return result


class SignalPerformanceSnapshotService:
    def __init__(self, artifact_dir: Path = DEFAULT_SIGNAL_PERFORMANCE_SNAPSHOT_DIR) -> None:
        self.artifact_dir = artifact_dir

    def performance(self, *, limit: int) -> dict[str, Any]:
        normalized_limit = max(1, limit)
        payload = self._read_performance_payload(
            compact_filename=PERFORMANCE_COMPACT_FILE,
            full_filename=PERFORMANCE_FILE,
            limit=normalized_limit,
        )
        return _slice_payload(payload, limit=normalized_limit, list_keys=("items",))

    def performance_1h(self, *, limit: int) -> dict[str, Any]:
        normalized_limit = max(1, limit)
        payload = self._read_performance_payload(
            compact_filename=PERFORMANCE_1H_COMPACT_FILE,
            full_filename=PERFORMANCE_1H_FILE,
            limit=normalized_limit,
        )
        return _slice_payload(payload, limit=normalized_limit, list_keys=("items",))

    def forward_integrity(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(FORWARD_INTEGRITY_FILE)
        return _slice_payload(payload, limit=max(1, limit), list_keys=("items", "stale_items"))

    def forward_integrity_1h(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(FORWARD_INTEGRITY_1H_FILE)
        return _slice_payload(payload, limit=max(1, limit), list_keys=("items", "stale_items"))

    def quality_lab(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(QUALITY_LAB_FILE)
        return _slice_payload(payload, limit=max(1, limit), list_keys=QUALITY_LAB_LIST_KEYS)

    def v3_shadow_filter_map(self) -> dict[tuple[str, str], list[dict[str, Any]]]:
        payload = self._read(PERFORMANCE_FILE)
        return build_v3_shadow_filter_map(list(payload.get("items") or []), min_sample=5, limit=100)

    def one_hour_filter_candidate_study(self, *, min_sample: int, limit: int) -> dict[str, Any]:
        payload = self._read(PERFORMANCE_1H_FILE)
        aggregate = payload.get("aggregate") or {}
        study = build_one_hour_filter_candidate_study_payload(
            evaluated=list(payload.get("items") or []),
            skipped=aggregate.get("skip_reasons") or {},
            latest_candle_time=payload.get("latest_futures_15m_close_time") or payload.get("latest_evaluation_candle_time"),
            epoch=str(payload.get("epoch") or OBSERVATION_EPOCH),
            include_watch_only=bool((payload.get("filters") or {}).get("include_watch_only", False)),
            position_lock=bool((payload.get("filters") or {}).get("position_lock", True)),
            min_sample=max(1, min_sample),
            limit=max(1, limit),
            source="signal_performance_snapshot_1h",
        )
        study["snapshot"] = payload.get("snapshot")
        return study

    def one_hour_walk_forward_study(self, *, min_sample: int, limit: int) -> dict[str, Any]:
        payload = self._read(PERFORMANCE_1H_FILE)
        aggregate = payload.get("aggregate") or {}
        study = build_one_hour_walk_forward_payload(
            evaluated=list(payload.get("items") or []),
            skipped=aggregate.get("skip_reasons") or {},
            latest_candle_time=payload.get("latest_futures_15m_close_time") or payload.get("latest_evaluation_candle_time"),
            epoch=str(payload.get("epoch") or OBSERVATION_EPOCH),
            include_watch_only=bool((payload.get("filters") or {}).get("include_watch_only", False)),
            position_lock=bool((payload.get("filters") or {}).get("position_lock", True)),
            min_sample=max(1, min_sample),
            limit=max(1, limit),
            source="signal_performance_snapshot_1h",
        )
        study["snapshot"] = payload.get("snapshot")
        return study

    def one_hour_v4_shadow_monitor(self, *, min_sample: int, limit: int) -> dict[str, Any]:
        payload = self._read(PERFORMANCE_1H_FILE)
        aggregate = payload.get("aggregate") or {}
        study = build_one_hour_v4_shadow_monitor_payload(
            evaluated=list(payload.get("items") or []),
            skipped=aggregate.get("skip_reasons") or {},
            latest_candle_time=payload.get("latest_futures_15m_close_time") or payload.get("latest_evaluation_candle_time"),
            epoch=str(payload.get("epoch") or OBSERVATION_EPOCH),
            include_watch_only=bool((payload.get("filters") or {}).get("include_watch_only", False)),
            position_lock=bool((payload.get("filters") or {}).get("position_lock", True)),
            min_sample=max(1, min_sample),
            limit=max(1, limit),
            source="signal_performance_snapshot_1h",
        )
        study["snapshot"] = payload.get("snapshot")
        return study

    def misidentification_audit_1h(
        self,
        *,
        stages: tuple[str, ...],
        min_sample: int,
        limit: int,
        max_signals_per_stage: int,
    ) -> dict[str, Any]:
        payload = self._read(PERFORMANCE_1H_FILE)
        aggregate = payload.get("aggregate") or {}
        study = build_misidentification_audit_payload(
            evaluated=list(payload.get("items") or []),
            skipped=aggregate.get("skip_reasons") or {},
            latest_candle_time=payload.get("latest_futures_15m_close_time") or payload.get("latest_evaluation_candle_time"),
            epoch=str(payload.get("epoch") or OBSERVATION_EPOCH),
            include_watch_only=bool((payload.get("filters") or {}).get("include_watch_only", False)),
            position_lock=bool((payload.get("filters") or {}).get("position_lock", True)),
            timeframe="1h",
            stages=stages,
            min_sample=max(1, min_sample),
            limit=max(1, limit),
            max_signals_per_stage=max(1, max_signals_per_stage),
            source="signal_performance_snapshot_1h",
        )
        study["snapshot"] = payload.get("snapshot")
        return study

    def mid_long_1h_baseline(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(PERFORMANCE_1H_FILE)
        aggregate = payload.get("aggregate") or {}
        source_items = list(payload.get("items") or [])
        evaluated = [
            item
            for item in source_items
            if item.get("stage") == "MID_LONG" and item.get("timeframe") == "1h"
        ]
        evaluated.sort(key=lambda item: str(item.get("signal_timestamp") or ""), reverse=True)
        baseline_aggregate = aggregate_signal_performance_items(evaluated)
        source_total = int(aggregate.get("signals_evaluated") or len(source_items))
        baseline_research = _mid_long_baseline_research(evaluated)
        rr_distribution = Counter(_rounded_r_distribution_key(item.get("rr")) for item in evaluated)
        strategy_distribution = Counter(
            str(item.get("strategy_version") or "UNKNOWN") for item in evaluated
        )
        confidence_distribution = Counter(
            str(item.get("confidence_tier") or "UNKNOWN") for item in evaluated
        )
        return {
            "generated_at_utc": (payload.get("snapshot") or {}).get("generated_at_utc") or payload.get("generated_at_utc"),
            "baseline_id": "MID_LONG_1H_V2_BASELINE",
            "scope": "mid_long_1h_logged_v2_closed_signals",
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "closed_only_snapshot": True,
            "filters": {
                "stage": "MID_LONG",
                "timeframe": "1h",
                "position_lock": True,
                "include_watch_only": False,
                "result_status": "closed",
                "limit": max(1, limit),
            },
            "snapshot_coverage": {
                "source_1h_rows": len(source_items),
                "source_1h_total": source_total,
                "mid_long_1h_rows": len(evaluated),
                "is_truncated": len(source_items) < source_total,
            },
            "latest_evaluation_candle_time": payload.get("latest_futures_15m_close_time")
            or payload.get("latest_evaluation_candle_time"),
            "aggregate": baseline_aggregate,
            **baseline_research,
            "rr_distribution": dict(sorted(rr_distribution.items())),
            "strategy_distribution": dict(sorted(strategy_distribution.items())),
            "confidence_distribution": dict(sorted(confidence_distribution.items())),
            "items": evaluated[: max(1, limit)],
            "snapshot": payload.get("snapshot"),
            "guardrails": [
                "This page is the frozen MID_LONG 1h V2 baseline, not a filter study.",
                "Entry, stop, target, RR, and result are read directly from logged V2 signals.",
                "No geometry override, timeout experiment, filter search, or promotion verdict is applied.",
            ],
        }

    def mid_short_filter_combination_1h(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(MID_SHORT_FILTER_COMBO_1H_FILE)
        return _slice_payload(
            payload,
            limit=max(1, limit),
            list_keys=(
                "combination_rows",
                "candidate_rows",
                "baseline_path_rows",
                "top_filter_pass_taxonomy",
                "top_filter_fail_taxonomy",
                "top_filter_pass_signals",
                "top_filter_fail_signals",
                "top_filter_missing_signals",
            ),
        )

    def research_snapshot(self, filename: str, *, limit: int) -> dict[str, Any]:
        payload = self._read(filename)
        return _slice_payload(payload, limit=max(1, limit), list_keys=DEFAULT_SIGNAL_RESEARCH_LIST_KEYS)

    def _read(self, filename: str) -> dict[str, Any]:
        path = self.artifact_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Signal performance snapshot not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_performance_payload(self, *, compact_filename: str, full_filename: str, limit: int) -> dict[str, Any]:
        compact_path = self.artifact_dir / compact_filename
        filename = compact_filename if limit <= DEFAULT_PERFORMANCE_COMPACT_LIMIT and compact_path.exists() else full_filename
        return self._read(filename)


def _mid_short_research_payloads(
    service: SignalCandidatePerformanceService,
    *,
    epoch: str,
    generated_at_utc: str,
) -> dict[str, dict[str, Any]]:
    return {
        MID_SHORT_SHADOW_FORWARD_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_shadow_forward_log(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                result_status=None,
                limit=DEFAULT_RESEARCH_LIMIT,
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_shadow_forward_snapshot_1h",
            filename=MID_SHORT_SHADOW_FORWARD_1H_FILE,
        ),
        MID_SHORT_FAILURE_ANATOMY_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_failure_anatomy(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                shadow_status="SHADOW_PASS",
                base_filter="ALL",
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_failure_anatomy_snapshot_1h",
            filename=MID_SHORT_FAILURE_ANATOMY_1H_FILE,
        ),
        MID_SHORT_SECOND_FILTER_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_second_filter_shadow(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                shadow_status="SHADOW_PASS",
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_second_filter_snapshot_1h",
            filename=MID_SHORT_SECOND_FILTER_1H_FILE,
        ),
        MID_SHORT_TAKER_SELL_DEEP_DIVE_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_taker_sell_deep_dive(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_taker_sell_deep_dive_snapshot_1h",
            filename=MID_SHORT_TAKER_SELL_DEEP_DIVE_1H_FILE,
        ),
        MID_SHORT_WRONG_DIRECTION_DEEP_DIVE_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_wrong_direction_deep_dive(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_wrong_direction_deep_dive_snapshot_1h",
            filename=MID_SHORT_WRONG_DIRECTION_DEEP_DIVE_1H_FILE,
        ),
        MID_SHORT_ENTRY_CONFIRMATION_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_entry_confirmation_study(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_entry_confirmation_snapshot_1h",
            filename=MID_SHORT_ENTRY_CONFIRMATION_1H_FILE,
        ),
        MID_SHORT_STRUCTURE_ZONE_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_structure_zone_study(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
                signal_id=None,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_structure_zone_snapshot_1h",
            filename=MID_SHORT_STRUCTURE_ZONE_1H_FILE,
        ),
        MID_SHORT_V21_STRUCTURE_INTERACTION_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_v21_structure_interaction_study(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_v21_structure_interaction_snapshot_1h",
            filename=MID_SHORT_V21_STRUCTURE_INTERACTION_1H_FILE,
        ),
        MID_SHORT_V21_STRUCTURE_EXIT_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_v21_structure_exit_study(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_v21_structure_exit_snapshot_1h",
            filename=MID_SHORT_V21_STRUCTURE_EXIT_1H_FILE,
        ),
        MID_SHORT_V21_DYNAMIC_EXIT_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_v21_dynamic_exit_study(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_v21_dynamic_exit_snapshot_1h",
            filename=MID_SHORT_V21_DYNAMIC_EXIT_1H_FILE,
        ),
        MID_SHORT_VOLUME_SAFE_1H_FILE: _with_snapshot_meta(
            service.mid_short_1h_volume_safe_shadow(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                min_sample=DEFAULT_RESEARCH_MIN_SAMPLE,
                limit=DEFAULT_RESEARCH_LIMIT,
            ),
            generated_at_utc=generated_at_utc,
            source="mid_short_volume_safe_snapshot_1h",
            filename=MID_SHORT_VOLUME_SAFE_1H_FILE,
        ),
    }


def _performance_payload(
    service: SignalCandidatePerformanceService,
    *,
    epoch: str,
    timeframe: str | None,
    limit: int,
) -> dict[str, Any]:
    return service.summary(
        epoch=epoch,
        include_watch_only=False,
        position_lock=True,
        stage=None,
        timeframe=timeframe,
        symbol=None,
        result_status="closed",
        limit=limit,
    )


def _forward_integrity_payload(
    service: SignalCandidatePerformanceService,
    *,
    epoch: str,
    timeframe: str | None,
    limit: int,
) -> dict[str, Any]:
    return service.forward_integrity(
        epoch=epoch,
        include_watch_only=False,
        position_lock=True,
        stage=None,
        timeframe=timeframe,
        limit=limit,
    )


def _with_snapshot_meta(payload: dict[str, Any], *, generated_at_utc: str, source: str, filename: str) -> dict[str, Any]:
    safe_payload = dict(payload)
    safe_payload["snapshot"] = {
        "source": source,
        "filename": filename,
        "generated_at_utc": generated_at_utc,
        "refresh_owner": "marketlab_research_loop",
        "read_model": "artifact_snapshot",
    }
    return safe_payload


def _slice_payload(payload: dict[str, Any], *, limit: int, list_keys: tuple[str, ...]) -> dict[str, Any]:
    sliced = deepcopy(payload)
    for key in list_keys:
        rows = sliced.get(key)
        if isinstance(rows, list):
            sliced[key] = rows[:limit]
    filters = sliced.get("filters")
    if isinstance(filters, dict):
        filters["limit"] = limit
    sliced["cache"] = {"hit": True, "source": "artifact_snapshot", "ttl_seconds": None}
    return sliced


def _compact_snapshot_payload(
    payload: dict[str, Any],
    *,
    filename: str,
    limit: int,
    list_keys: tuple[str, ...],
) -> dict[str, Any]:
    compact = _slice_payload(payload, limit=limit, list_keys=list_keys)
    snapshot = compact.get("snapshot")
    if isinstance(snapshot, dict):
        snapshot["filename"] = filename
        snapshot["compact_limit"] = limit
    return compact


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _distribution_key(value: Any) -> str:
    if value is None:
        return "MISSING"
    try:
        normalized = Decimal(str(value)).normalize()
    except (ArithmeticError, ValueError):
        return str(value)
    return f"{normalized}R"


def _rounded_r_distribution_key(value: Any) -> str:
    if value is None:
        return "MISSING"
    try:
        rounded = Decimal(str(value)).quantize(Decimal("0.1"))
    except (ArithmeticError, ValueError):
        return str(value)
    formatted = format(rounded, "f").rstrip("0").rstrip(".")
    if formatted in {"", "-0"}:
        formatted = "0"
    return f"{formatted}R"


def _mid_long_baseline_research(items: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = _mid_long_perf_row(
        "BASELINE",
        "MID_LONG 1h V2 baseline",
        "no additional filter",
        items,
        baseline=None,
        required_fields=(),
        min_sample=20,
    )
    entry_rows = _mid_long_entry_combination_rows(items, baseline=baseline, min_sample=20)
    return {
        "research_summary": {
            "scope": "MID_LONG 1h closed V2 signals",
            "method": "Read-only baseline reset plus transparent entry-combination ranking from logged evidence.",
            "min_sample": 20,
            "closed_count": baseline["closed_count"],
            "tp_count": baseline["tp_count"],
            "sl_count": baseline["sl_count"],
            "winrate_pct": baseline["winrate_pct"],
            "realistic_total_r_closed": baseline["realistic_total_r_closed"],
            "realistic_avg_r_closed": baseline["realistic_avg_r_closed"],
            "median_realistic_r_closed": baseline["median_realistic_r_closed"],
            "max_realistic_drawdown_r": baseline["max_realistic_drawdown_r"],
            "read": _mid_long_baseline_read(baseline),
        },
        "evidence_comparison": _mid_long_evidence_comparison(items, min_sample=20),
        "structure_breakdown": _mid_long_bucket_rows(items, key="structure_zone_status", min_sample=20),
        "primary_zone_breakdown": _mid_long_bucket_rows(items, key="structure_zone_primary_state", min_sample=20),
        "fill_quality_breakdown": _mid_long_bucket_rows(items, key="realistic_fill_quality", min_sample=20),
        "entry_combination_ranking": entry_rows[:25],
        "entry_combination_worst": sorted(
            entry_rows,
            key=lambda row: (
                _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed")),
                _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
            ),
        )[:10],
    }


def _mid_long_baseline_read(baseline: dict[str, Any]) -> str:
    realistic_total = _decimal_or_zero_snapshot(baseline.get("realistic_total_r_closed"))
    sl_count = int(baseline.get("sl_count") or 0)
    tp_count = int(baseline.get("tp_count") or 0)
    if realistic_total < 0 and sl_count > tp_count:
        return "BASELINE_WEAK_SL_DOMINANT"
    if realistic_total > 0 and tp_count >= sl_count:
        return "BASELINE_POSITIVE"
    return "BASELINE_MIXED"


def _mid_long_entry_combination_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    specs = _mid_long_condition_specs()
    rows: list[dict[str, Any]] = []
    # Keep this endpoint request-time safe. Single and pair filters are enough
    # for baseline triage; deeper combinations belong in an offline lab runner.
    for size in (1, 2):
        for selected_specs in combinations(specs, size):
            required_fields = tuple(
                sorted({field for spec in selected_specs for field in spec["required_fields"]})
            )
            selected: list[dict[str, Any]] = []
            missing_data = 0
            for item in items:
                if any(_mid_long_evidence_value(item, field) is None for field in required_fields):
                    missing_data += 1
                    continue
                if all(spec["predicate"](item) for spec in selected_specs):
                    selected.append(item)
            if not selected:
                continue
            row = _mid_long_perf_row(
                "+".join(str(spec["id"]) for spec in selected_specs),
                " + ".join(str(spec["label"]) for spec in selected_specs),
                " AND ".join(str(spec["expression"]) for spec in selected_specs),
                selected,
                baseline=baseline,
                required_fields=required_fields,
                missing_data_count=missing_data,
                min_sample=min_sample,
            )
            if int(row["closed_count"]) >= min_sample:
                rows.append(row)
    rows.sort(
        key=lambda row: (
            _mid_long_verdict_rank(str(row.get("verdict"))),
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero_snapshot(row.get("realistic_total_r_delta_vs_baseline")),
            _decimal_or_zero_snapshot(row.get("max_drawdown_delta_vs_baseline")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_condition_specs() -> tuple[dict[str, Any], ...]:
    return (
        {
            "id": "FILL_GOOD",
            "label": "fill bagus",
            "expression": "realistic_fill_quality == FILL_GOOD",
            "required_fields": (),
            "predicate": lambda item: str(item.get("realistic_fill_quality") or "") == "FILL_GOOD",
        },
        {
            "id": "COST_LE_020R",
            "label": "cost <= 0.20R",
            "expression": "realistic_cost_r_estimate <= 0.20",
            "required_fields": (),
            "predicate": lambda item: _item_decimal(item, "realistic_cost_r_estimate") is not None
            and _item_decimal(item, "realistic_cost_r_estimate") <= Decimal("0.20"),
        },
        {
            "id": "ZONE_ALIGNED",
            "label": "zona selaras",
            "expression": "structure_zone_status == ZONE_ALIGNED",
            "required_fields": (),
            "predicate": lambda item: str(item.get("structure_zone_status") or "") == "ZONE_ALIGNED",
        },
        {
            "id": "LONG_ZONE_STATE",
            "label": "support/breakout",
            "expression": "primary zone in AT_SUPPORT, SUPPORT_BOUNCE, RESISTANCE_BREAKOUT",
            "required_fields": (),
            "predicate": lambda item: str(item.get("structure_zone_primary_state") or "")
            in {"AT_SUPPORT", "SUPPORT_BOUNCE", "RESISTANCE_BREAKOUT"},
        },
        {
            "id": "NOT_ZONE_CONFLICT",
            "label": "bukan konflik zona",
            "expression": "structure_zone_status != ZONE_CONFLICT",
            "required_fields": (),
            "predicate": lambda item: str(item.get("structure_zone_status") or "") != "ZONE_CONFLICT",
        },
        {
            "id": "VOLUME_08_20",
            "label": "volume 0.8-2.0x",
            "expression": "0.80 <= volume_ratio_vs_lookback <= 2.00",
            "required_fields": ("volume_ratio_vs_lookback",),
            "predicate": lambda item: _between_evidence(item, "volume_ratio_vs_lookback", Decimal("0.80"), Decimal("2.00")),
        },
        {
            "id": "TAKER_BUY_GE_053",
            "label": "taker buy >= 53%",
            "expression": "kline_taker_buy_ratio >= 0.53",
            "required_fields": ("kline_taker_buy_ratio",),
            "predicate": lambda item: _evidence_gte(item, "kline_taker_buy_ratio", Decimal("0.53")),
        },
        {
            "id": "OI_Z_GE_2",
            "label": "OI z >= 2",
            "expression": "oi_zscore >= 2",
            "required_fields": ("oi_zscore",),
            "predicate": lambda item: _evidence_gte(item, "oi_zscore", Decimal("2")),
        },
        {
            "id": "OI_CHANGE_POSITIVE",
            "label": "OI naik",
            "expression": "oi_change_pct > 0",
            "required_fields": ("oi_change_pct",),
            "predicate": lambda item: _evidence_gt(item, "oi_change_pct", Decimal("0")),
        },
        {
            "id": "PRICE_RETURN_LE_2",
            "label": "price return <= 2%",
            "expression": "price_return <= 2.00",
            "required_fields": ("price_return",),
            "predicate": lambda item: _evidence_lte(item, "price_return", Decimal("2.00")),
        },
        {
            "id": "ATR_EXTENSION_LE_1",
            "label": "ATR extension <= 1x",
            "expression": "atr_extension_normalized <= 1.00",
            "required_fields": ("atr_extension_normalized",),
            "predicate": lambda item: _evidence_lte(item, "atr_extension_normalized", Decimal("1.00")),
        },
        {
            "id": "RANGE_ATR_LE_15",
            "label": "range/ATR <= 1.5",
            "expression": "range_ratio_vs_atr <= 1.50",
            "required_fields": ("range_ratio_vs_atr",),
            "predicate": lambda item: _evidence_lte(item, "range_ratio_vs_atr", Decimal("1.50")),
        },
        {
            "id": "SPREAD_LE_003",
            "label": "spread <= 0.03%",
            "expression": "futures_spread_pct <= 0.03",
            "required_fields": ("futures_spread_pct",),
            "predicate": lambda item: _evidence_lte(item, "futures_spread_pct", Decimal("0.03")),
        },
        {
            "id": "FUNDING_NOT_CROWDED",
            "label": "funding <= 75 pct",
            "expression": "funding_percentile_30d <= 75",
            "required_fields": ("funding_percentile_30d",),
            "predicate": lambda item: _evidence_lte(item, "funding_percentile_30d", Decimal("75")),
        },
        {
            "id": "GLSR_GE_120",
            "label": "global L/S >= 1.20",
            "expression": "global_long_short_ratio >= 1.20",
            "required_fields": ("global_long_short_ratio",),
            "predicate": lambda item: _evidence_gte(item, "global_long_short_ratio", Decimal("1.20")),
        },
        {
            "id": "TOP_POS_GE_130",
            "label": "top position >= 1.30",
            "expression": "top_trader_position_ratio >= 1.30",
            "required_fields": ("top_trader_position_ratio",),
            "predicate": lambda item: _evidence_gte(item, "top_trader_position_ratio", Decimal("1.30")),
        },
    )


def _mid_long_perf_row(
    filter_id: str,
    label: str,
    expression: str,
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any] | None,
    required_fields: tuple[str, ...],
    missing_data_count: int = 0,
    min_sample: int,
) -> dict[str, Any]:
    perf = aggregate_signal_performance_items(items)
    realistic_values = [
        _decimal_or_none_snapshot(item.get("realistic_realized_r"))
        for item in items
        if item.get("result_status") in COMPLETED_OUTCOMES
    ]
    realistic_values = [value for value in realistic_values if value is not None]
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    top_symbol, top_symbol_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    drawdown = _mid_long_realistic_drawdown(items)
    row: dict[str, Any] = {
        "filter_id": filter_id,
        "label": label,
        "expression": expression,
        "required_fields": list(required_fields),
        "missing_data_count": missing_data_count,
        "sample_count": len(items),
        "sample_retention_pct": _pct_decimal(len(items), int(baseline.get("sample_count") or 0)) if baseline else Decimal("100") if items else None,
        "closed_count": perf["closed_count"],
        "tp_count": perf["tp_count"],
        "sl_count": perf["sl_count"],
        "both_hit_count": perf["both_hit_count"],
        "winrate_pct": perf["winrate_pct"],
        "sl_share_pct": _sl_share_snapshot(perf),
        "ideal_total_r_closed": perf["total_r_closed"],
        "realistic_total_r_closed": perf["realistic_total_r_closed"],
        "realistic_avg_r_closed": perf["realistic_avg_r_closed"],
        "median_realistic_r_closed": _median_decimal_snapshot(realistic_values),
        "max_realistic_drawdown_r": drawdown["max_drawdown_r"],
        "top_symbol": top_symbol,
        "top_symbol_count": top_symbol_count,
        "top_symbol_share_pct": _pct_decimal(top_symbol_count, len(items)) if items else None,
    }
    if baseline is not None:
        row.update(
            {
                "realistic_avg_r_delta_vs_baseline": _decimal_delta_snapshot(
                    row.get("realistic_avg_r_closed"),
                    baseline.get("realistic_avg_r_closed"),
                ),
                "realistic_total_r_delta_vs_baseline": _decimal_delta_snapshot(
                    row.get("realistic_total_r_closed"),
                    baseline.get("realistic_total_r_closed"),
                ),
                "winrate_delta_vs_baseline": _decimal_delta_snapshot(row.get("winrate_pct"), baseline.get("winrate_pct")),
                "sl_share_delta_vs_baseline": _decimal_delta_snapshot(row.get("sl_share_pct"), baseline.get("sl_share_pct")),
                "max_drawdown_delta_vs_baseline": _decimal_delta_snapshot(
                    row.get("max_realistic_drawdown_r"),
                    baseline.get("max_realistic_drawdown_r"),
                ),
            }
        )
    row["verdict"] = _mid_long_entry_verdict(row, min_sample=min_sample, baseline=baseline)
    row["note"] = _mid_long_entry_note(str(row["verdict"]))
    return row


def _mid_long_entry_verdict(row: dict[str, Any], *, min_sample: int, baseline: dict[str, Any] | None) -> str:
    if int(row.get("closed_count") or 0) < min_sample:
        return "SAMPLE_TOO_SMALL"
    if baseline is None:
        return "BASELINE_CONTROL"
    avg_delta = _decimal_or_none_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    total_delta = _decimal_or_none_snapshot(row.get("realistic_total_r_delta_vs_baseline"))
    drawdown_delta = _decimal_or_none_snapshot(row.get("max_drawdown_delta_vs_baseline"))
    sl_delta = _decimal_or_none_snapshot(row.get("sl_share_delta_vs_baseline"))
    total_r = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    top_share = _decimal_or_none_snapshot(row.get("top_symbol_share_pct"))
    concentration_ok = top_share is None or top_share <= Decimal("35")
    if (
        avg_delta is not None
        and avg_delta >= Decimal("0.10")
        and total_r > 0
        and (sl_delta is None or sl_delta <= Decimal("0"))
        and concentration_ok
    ):
        return "PROMISING_RESEARCH_CANDIDATE"
    if avg_delta is not None and avg_delta > 0 and (drawdown_delta is None or drawdown_delta >= 0):
        return "DAMAGE_REDUCTION"
    if total_delta is not None and total_delta < 0:
        return "WORSE_THAN_BASELINE"
    return "NO_CLEAR_SEPARATION"


def _mid_long_entry_note(verdict: str) -> str:
    if verdict == "PROMISING_RESEARCH_CANDIDATE":
        return "Kombinasi ini membaik secara realistic R dan tidak memperbesar SL share; lanjut validasi waktu sebelum jadi V2.1."
    if verdict == "DAMAGE_REDUCTION":
        return "Ada perbaikan kecil atau drawdown lebih baik, tapi belum cukup bersih."
    if verdict == "WORSE_THAN_BASELINE":
        return "Lebih buruk dari baseline V2; jangan dipakai sebagai filter."
    if verdict == "SAMPLE_TOO_SMALL":
        return "Sample belum cukup."
    if verdict == "BASELINE_CONTROL":
        return "Kontrol awal tanpa filter tambahan."
    return "Belum ada pemisahan TP/SL yang jelas."


def _mid_long_verdict_rank(verdict: str) -> int:
    return {
        "PROMISING_RESEARCH_CANDIDATE": 4,
        "DAMAGE_REDUCTION": 3,
        "NO_CLEAR_SEPARATION": 2,
        "SAMPLE_TOO_SMALL": 1,
        "WORSE_THAN_BASELINE": 0,
    }.get(verdict, 0)


def _mid_long_evidence_comparison(items: list[dict[str, Any]], *, min_sample: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, label in EVIDENCE_FIELDS:
        tp_values: list[Decimal] = []
        sl_values: list[Decimal] = []
        both_values: list[Decimal] = []
        missing = 0
        for item in items:
            value = _mid_long_evidence_value(item, field)
            if value is None:
                missing += 1
                continue
            if item.get("result_status") == "TP_HIT":
                tp_values.append(value)
            elif item.get("result_status") == "SL_HIT":
                sl_values.append(value)
            elif item.get("result_status") == "BOTH_HIT_SAME_CANDLE":
                both_values.append(value)
        tp_median = _median_decimal_snapshot(tp_values)
        sl_median = _median_decimal_snapshot(sl_values)
        delta = tp_median - sl_median if tp_median is not None and sl_median is not None else None
        rows.append(
            {
                "field": field,
                "label": label,
                "available_count": len(tp_values) + len(sl_values) + len(both_values),
                "missing_count": missing,
                "available_pct": _pct_decimal(len(tp_values) + len(sl_values) + len(both_values), len(items)),
                "tp_count": len(tp_values),
                "sl_count": len(sl_values),
                "both_count": len(both_values),
                "tp_median": tp_median,
                "sl_median": sl_median,
                "tp_q1": _percentile_decimal_snapshot(tp_values, Decimal("0.25")),
                "tp_q3": _percentile_decimal_snapshot(tp_values, Decimal("0.75")),
                "sl_q1": _percentile_decimal_snapshot(sl_values, Decimal("0.25")),
                "sl_q3": _percentile_decimal_snapshot(sl_values, Decimal("0.75")),
                "delta_tp_minus_sl": delta,
                "quality_flag": _mid_long_evidence_flag(
                    tp_count=len(tp_values),
                    sl_count=len(sl_values),
                    delta=delta,
                    min_sample=min_sample,
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            row["quality_flag"] != "SAMPLE_TOO_SMALL",
            abs(_decimal_or_zero_snapshot(row.get("delta_tp_minus_sl"))),
            int(row.get("available_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_evidence_flag(*, tp_count: int, sl_count: int, delta: Decimal | None, min_sample: int) -> str:
    if tp_count < min_sample or sl_count < min_sample or delta is None:
        return "SAMPLE_TOO_SMALL"
    if abs(delta) < Decimal("0.0001"):
        return "NO_CLEAR_GAP"
    return "TP_HIGHER" if delta > 0 else "SL_HIGHER"


def _mid_long_bucket_rows(items: list[dict[str, Any]], *, key: str, min_sample: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        buckets[str(item.get(key) or "UNKNOWN")].append(item)
    baseline = _mid_long_perf_row(
        "BASELINE",
        "MID_LONG 1h V2 baseline",
        "no additional filter",
        items,
        baseline=None,
        required_fields=(),
        min_sample=min_sample,
    )
    rows = [
        _mid_long_perf_row(
            bucket,
            bucket,
            f"{key} == {bucket}",
            rows,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        for bucket, rows in buckets.items()
    ]
    rows.sort(
        key=lambda row: (
            _mid_long_verdict_rank(str(row.get("verdict"))),
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_realistic_drawdown(items: list[dict[str, Any]]) -> dict[str, Decimal | int]:
    closed = [
        item
        for item in items
        if item.get("result_status") in COMPLETED_OUTCOMES and item.get("realistic_realized_r") is not None
    ]
    closed.sort(key=lambda item: (str(item.get("result_time_utc") or item.get("signal_timestamp") or ""), str(item.get("symbol") or "")))
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for item in closed:
        cumulative += _decimal_or_zero_snapshot(item.get("realistic_realized_r"))
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return {
        "closed_count": len(closed),
        "total_r_closed": cumulative,
        "peak_r": peak,
        "max_drawdown_r": max_drawdown,
        "current_drawdown_r": cumulative - peak,
    }


def _mid_long_evidence_value(item: dict[str, Any], field: str) -> Decimal | None:
    value = (item.get("evidence_snapshot") or {}).get(field)
    return _decimal_or_none_snapshot(value)


def _item_decimal(item: dict[str, Any], key: str) -> Decimal | None:
    return _decimal_or_none_snapshot(item.get(key))


def _between_evidence(item: dict[str, Any], field: str, lower: Decimal, upper: Decimal) -> bool:
    value = _mid_long_evidence_value(item, field)
    return value is not None and lower <= value <= upper


def _evidence_gte(item: dict[str, Any], field: str, threshold: Decimal) -> bool:
    value = _mid_long_evidence_value(item, field)
    return value is not None and value >= threshold


def _evidence_gt(item: dict[str, Any], field: str, threshold: Decimal) -> bool:
    value = _mid_long_evidence_value(item, field)
    return value is not None and value > threshold


def _evidence_lte(item: dict[str, Any], field: str, threshold: Decimal) -> bool:
    value = _mid_long_evidence_value(item, field)
    return value is not None and value <= threshold


def _sl_share_snapshot(perf: dict[str, Any]) -> Decimal | None:
    denominator = int(perf.get("tp_count") or 0) + int(perf.get("sl_count") or 0)
    if denominator <= 0:
        return None
    return Decimal(int(perf.get("sl_count") or 0)) / Decimal(denominator) * Decimal("100")


def _pct_decimal(count: int, total: int) -> Decimal | None:
    if total <= 0:
        return None
    return Decimal(count) / Decimal(total) * Decimal("100")


def _decimal_delta_snapshot(value: Any, baseline: Any) -> Decimal | None:
    parsed = _decimal_or_none_snapshot(value)
    parsed_baseline = _decimal_or_none_snapshot(baseline)
    if parsed is None or parsed_baseline is None:
        return None
    return parsed - parsed_baseline


def _decimal_or_none_snapshot(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _decimal_or_zero_snapshot(value: Any) -> Decimal:
    parsed = _decimal_or_none_snapshot(value)
    return parsed if parsed is not None else Decimal("0")


def _median_decimal_snapshot(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _percentile_decimal_snapshot(values: list[Decimal], pct: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (Decimal(len(ordered) - 1) * pct)
    lower = int(index.to_integral_value(rounding="ROUND_FLOOR"))
    upper = int(index.to_integral_value(rounding="ROUND_CEILING"))
    if lower == upper:
        return ordered[lower]
    fraction = index - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
