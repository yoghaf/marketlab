from __future__ import annotations

import json
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
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
    definition_audit = _mid_long_definition_audit(items, baseline=baseline, min_sample=20)
    return {
        "research_summary": {
            "scope": "MID_LONG 1h closed V2 signals",
            "method": "Read-only definition audit from logged MID_LONG 1h evidence, path, structure, and realistic execution.",
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
        "definition_audit": definition_audit,
        "evidence_comparison": _mid_long_evidence_comparison(items, min_sample=20),
        "entry_anatomy_summary": _mid_long_entry_anatomy_summary(items, baseline=baseline),
        "outcome_entry_profiles": _mid_long_outcome_entry_profiles(items),
        "entry_area_anatomy": _mid_long_entry_area_anatomy(items, baseline=baseline, min_sample=20),
        "path_anatomy": _mid_long_path_anatomy(items, baseline=baseline, min_sample=20),
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
    specs_by_id = {str(spec["id"]): spec for spec in _mid_long_condition_specs()}
    candidate_sets = (
        ("FILL_GOOD", "RANGE_ATR_LE_15"),
        ("FILL_GOOD", "ATR_EXTENSION_LE_1"),
        ("FILL_GOOD", "TAKER_BUY_GE_053"),
        ("FILL_GOOD", "VOLUME_08_20"),
        ("FILL_GOOD", "COST_LE_020R"),
        ("LONG_ZONE_STATE", "TAKER_BUY_GE_053"),
        ("LONG_ZONE_STATE", "RANGE_ATR_LE_15"),
        ("ZONE_ALIGNED", "TAKER_BUY_GE_053"),
        ("TAKER_BUY_GE_053", "OI_Z_GE_2"),
        ("TAKER_BUY_GE_053", "OI_CHANGE_POSITIVE"),
        ("PRICE_RETURN_LE_2", "ATR_EXTENSION_LE_1"),
        ("SPREAD_LE_003", "FILL_GOOD"),
        ("FUNDING_NOT_CROWDED", "TAKER_BUY_GE_053"),
        ("GLSR_GE_120", "TOP_POS_GE_130"),
        ("FILL_GOOD", "RANGE_ATR_LE_15", "TAKER_BUY_GE_053"),
        ("LONG_ZONE_STATE", "FILL_GOOD", "TAKER_BUY_GE_053"),
    )
    rows: list[dict[str, Any]] = []
    for spec_ids in candidate_sets:
        selected_specs = tuple(specs_by_id[spec_id] for spec_id in spec_ids if spec_id in specs_by_id)
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


MID_LONG_ANATOMY_EVIDENCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("price_return", "Price return %"),
    ("volume_ratio_vs_lookback", "Volume vs avg"),
    ("kline_taker_buy_ratio", "Taker buy ratio"),
    ("oi_change_pct", "OI change %"),
    ("oi_zscore", "OI z-score"),
    ("range_ratio_vs_atr", "Range / ATR"),
    ("atr_extension_normalized", "ATR extension"),
    ("funding_percentile_30d", "Funding percentile"),
    ("futures_spread_pct", "Futures spread %"),
    ("global_long_short_ratio", "Global L/S ratio"),
    ("top_trader_position_ratio", "Top trader position"),
)


MID_LONG_DEFINITION_AXIS_SPECS: dict[str, dict[str, str]] = {
    "EXT": {
        "label": "Extension",
        "question": "Apakah entry MID_LONG sudah telat atau masih normal terhadap ATR?",
    },
    "STR": {
        "label": "Structure",
        "question": "Apakah entry punya support/breakout, dekat resistance, atau masuk tengah range?",
    },
    "FLW": {
        "label": "Flow",
        "question": "Apakah volume, taker buy, dan OI benar-benar mendukung long?",
    },
    "CRD": {
        "label": "Crowding",
        "question": "Apakah long sudah crowded dari funding/OI/positioning?",
    },
}

MID_LONG_DEFINITION_THRESHOLDS: dict[str, str] = {
    "EXTENDED_ATR_EXTENSION": "atr_extension_normalized >= 1.00",
    "EXTENDED_PRICE_ATR": "price_atr_multiple >= 1.25",
    "FLOW_VOLUME": "volume_ratio_vs_lookback >= 1.00",
    "FLOW_TAKER_BUY": "kline_taker_buy_ratio >= 0.53",
    "FLOW_OI": "oi_change_pct > 0",
    "CROWDED_FUNDING": "funding_percentile_30d >= 75",
    "CROWDED_OI_Z": "oi_zscore >= 3.00 with crowded positioning",
    "EXECUTION_VALID": "realistic_fill_quality == FILL_GOOD OR realistic_cost_r_estimate <= 0.20",
}


def _mid_long_definition_audit(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    axis_states = {str(item.get("signal_id") or idx): _mid_long_definition_axis_state(item) for idx, item in enumerate(items)}
    layer_rows = _mid_long_layer_decomposition(items, baseline=baseline, min_sample=min_sample)
    path_summary = _mid_long_path_decision_summary(items)
    axis_rows = _mid_long_axis_rows(items, axis_states=axis_states, baseline=baseline, min_sample=min_sample)
    cross_tables = {
        "EXTxSTR": _mid_long_axis_cross_rows(
            items,
            axis_states=axis_states,
            first_axis="EXT",
            second_axis="STR",
            baseline=baseline,
            min_sample=min_sample,
        ),
        "FLWxCRD": _mid_long_axis_cross_rows(
            items,
            axis_states=axis_states,
            first_axis="FLW",
            second_axis="CRD",
            baseline=baseline,
            min_sample=min_sample,
        ),
    }
    geometry = _mid_long_geometry_diagnostic(items)
    ablation = _mid_long_ablation_preview(
        items,
        axis_states=axis_states,
        baseline=baseline,
        min_sample=min_sample,
    )
    verdict = _mid_long_definition_verdict(
        baseline=baseline,
        layer_rows=layer_rows,
        path_summary=path_summary,
        axis_rows=axis_rows,
        geometry=geometry,
    )
    return {
        "scope": "MID_LONG 1h logged V2 closed signals",
        "method": "Flag-first definition audit: every MID_LONG signal remains in the sample; flags are measured before any gate proposal.",
        "min_sample": min_sample,
        "thresholds": MID_LONG_DEFINITION_THRESHOLDS,
        "axis_specs": MID_LONG_DEFINITION_AXIS_SPECS,
        "layer_decomposition": layer_rows,
        "path_decision_summary": path_summary,
        "axis_rows": axis_rows,
        "cross_tables": cross_tables,
        "geometry_diagnostic": geometry,
        "ablation_preview": ablation,
        "verdict": verdict,
        "guardrails": [
            "Candidate flags are not live gates.",
            "No Signal Factory rule, scanner behavior, TP/SL, or execution logic is changed.",
            "Support/resistance readings must be treated as invalid if their timestamp uses future candles.",
        ],
    }


def _mid_long_layer_decomposition(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    execution_valid = [item for item in items if _mid_long_execution_state(item) == "EXECUTION_VALID"]
    execution_invalid = [item for item in items if _mid_long_execution_state(item) == "EXECUTION_RISK"]
    execution_unknown = [item for item in items if _mid_long_execution_state(item) == "EXECUTION_UNKNOWN"]
    rows: list[dict[str, Any]] = []
    for row_id, label, row_items, note in (
        ("ALL", "All MID_LONG 1h", items, "Raw baseline. Nothing is filtered out."),
        ("EXECUTION_VALID", "Execution-valid subset", execution_valid, "Fill/cost looks usable; compare against ALL to isolate execution drag."),
        ("EXECUTION_RISK", "Execution-risk subset", execution_invalid, "Bad fill or high cost; read as microstructure risk, not necessarily thesis failure."),
        ("EXECUTION_UNKNOWN", "Execution unknown", execution_unknown, "Cost/fill data unavailable for these rows."),
    ):
        row = _mid_long_perf_row(
            row_id,
            label,
            row_id,
            row_items,
            baseline=baseline if row_id != "ALL" else None,
            required_fields=(),
            min_sample=min_sample,
        )
        row["ideal_realistic_gap_r"] = _decimal_delta_snapshot(
            row.get("ideal_total_r_closed"),
            row.get("realistic_total_r_closed"),
        )
        row["median_cost_r"] = _median_decimal_snapshot(
            [
                value
                for item in row_items
                if (value := _decimal_or_none_snapshot(item.get("realistic_cost_r_estimate"))) is not None
            ]
        )
        row["note"] = note
        rows.append(row)
    return rows


def _mid_long_path_decision_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[_mid_long_path_decision_bucket(item)].append(item)
    total = len(items)
    for bucket, label, definition in (
        ("INSTANT_SL", "Instant SL", "SL with MFE < +0.25R"),
        ("PARTIAL_FAIL", "+0.25R to +1R then SL", "SL after some follow-through, but before +1R"),
        ("DEEP_FAIL", "+1R+ then SL", "SL after thesis already moved at least +1R"),
        ("CLEAN_TP", "Clean TP", "TP with MAE better than -0.50R"),
        ("PULLBACK_TP", "TP after pullback", "TP after MAE <= -0.50R"),
        ("BOTH_SAME_CANDLE", "Both same candle", "TP and SL touched in same candle"),
        ("OTHER", "Other / open-like", "Rows outside TP/SL/BOTH"),
    ):
        bucket_items = grouped.get(bucket, [])
        rows.append(
            {
                "bucket": bucket,
                "label": label,
                "definition": definition,
                "count": len(bucket_items),
                "share_pct": _pct_decimal(len(bucket_items), total),
                "realistic_total_r_closed": sum(
                    (
                        _decimal_or_zero_snapshot(item.get("realistic_realized_r"))
                        for item in bucket_items
                        if item.get("result_status") in COMPLETED_OUTCOMES
                    ),
                    Decimal("0"),
                ),
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_values(bucket_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_values(bucket_items, "mae_r")),
            }
        )
    instant = len(grouped.get("INSTANT_SL", []))
    deep_fail = len(grouped.get("DEEP_FAIL", []))
    partial = len(grouped.get("PARTIAL_FAIL", []))
    return {
        "rows": rows,
        "instant_sl_count": instant,
        "partial_fail_count": partial,
        "deep_fail_count": deep_fail,
        "instant_sl_share_pct": _pct_decimal(instant, total),
        "deep_fail_share_pct": _pct_decimal(deep_fail, total),
        "read": _mid_long_path_decision_read(total=total, instant=instant, partial=partial, deep_fail=deep_fail),
    }


def _mid_long_path_decision_bucket(item: dict[str, Any]) -> str:
    status = str(item.get("result_status") or "UNKNOWN")
    mfe = _decimal_or_zero_snapshot(item.get("mfe_r"))
    mae = _decimal_or_zero_snapshot(item.get("mae_r"))
    if status == "SL_HIT":
        if mfe >= Decimal("1.0"):
            return "DEEP_FAIL"
        if mfe >= Decimal("0.25"):
            return "PARTIAL_FAIL"
        return "INSTANT_SL"
    if status == "TP_HIT":
        if mae <= Decimal("-0.50"):
            return "PULLBACK_TP"
        return "CLEAN_TP"
    if status == "BOTH_HIT_SAME_CANDLE":
        return "BOTH_SAME_CANDLE"
    return "OTHER"


def _mid_long_path_decision_read(*, total: int, instant: int, partial: int, deep_fail: int) -> str:
    if total <= 0:
        return "INSUFFICIENT_DATA"
    instant_share = Decimal(instant) / Decimal(total)
    harvest_share = Decimal(partial + deep_fail) / Decimal(total)
    if instant_share >= Decimal("0.30"):
        return "ENTRY_DEFINITION_PRESSURE"
    if harvest_share >= Decimal("0.25"):
        return "GEOMETRY_OR_EXIT_PRESSURE"
    return "PATH_MIXED"


def _mid_long_axis_rows(
    items: list[dict[str, Any]],
    *,
    axis_states: dict[str, dict[str, str]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total_negative_r = _mid_long_total_negative_r(items)
    for axis in ("EXT", "STR", "FLW", "CRD"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for idx, item in enumerate(items):
            state = axis_states[str(item.get("signal_id") or idx)][axis]
            grouped[state].append(item)
        for state, state_items in grouped.items():
            row = _mid_long_perf_row(
                f"{axis}:{state}",
                state,
                f"{axis} == {state}",
                state_items,
                baseline=baseline,
                required_fields=(),
                min_sample=min_sample,
            )
            row.update(
                {
                    "axis": axis,
                    "axis_label": MID_LONG_DEFINITION_AXIS_SPECS[axis]["label"],
                    "state": state,
                    "negative_r_abs": _mid_long_total_negative_r(state_items),
                    "negative_r_share_pct": _pct_decimal_decimal(_mid_long_total_negative_r(state_items), total_negative_r),
                    "top3_symbol_share_pct": _mid_long_top_n_symbol_share(state_items, n=3),
                    "read": _mid_long_axis_state_read(axis, state, row),
                }
            )
            rows.append(row)
    rows.sort(
        key=lambda row: (
            str(row.get("axis") or ""),
            _decimal_or_zero_snapshot(row.get("negative_r_abs")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_axis_cross_rows(
    items: list[dict[str, Any]],
    *,
    axis_states: dict[str, dict[str, str]],
    first_axis: str,
    second_axis: str,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total_negative_r = _mid_long_total_negative_r(items)
    for idx, item in enumerate(items):
        states = axis_states[str(item.get("signal_id") or idx)]
        grouped[f"{states[first_axis]} x {states[second_axis]}"].append(item)
    rows: list[dict[str, Any]] = []
    for key, cell_items in grouped.items():
        row = _mid_long_perf_row(
            f"{first_axis}x{second_axis}:{key}",
            key,
            f"{first_axis} x {second_axis} == {key}",
            cell_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "first_axis": first_axis,
                "second_axis": second_axis,
                "cell": key,
                "is_readable": int(row.get("closed_count") or 0) >= min_sample,
                "negative_r_abs": _mid_long_total_negative_r(cell_items),
                "negative_r_share_pct": _pct_decimal_decimal(_mid_long_total_negative_r(cell_items), total_negative_r),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            bool(row.get("is_readable")),
            _decimal_or_zero_snapshot(row.get("negative_r_abs")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_geometry_diagnostic(items: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [
        item
        for item in items
        if item.get("result_status") in COMPLETED_OUTCOMES and _decimal_or_none_snapshot(item.get("mfe_r")) is not None
    ]
    rows: list[dict[str, Any]] = []
    for threshold in (Decimal("0.25"), Decimal("0.50"), Decimal("0.75"), Decimal("1.00"), Decimal("1.50")):
        touched = [item for item in completed if _decimal_or_zero_snapshot(item.get("mfe_r")) >= threshold]
        tp_after = [item for item in touched if item.get("result_status") == "TP_HIT"]
        sl_after = [item for item in touched if item.get("result_status") == "SL_HIT"]
        rows.append(
            {
                "threshold_r": threshold,
                "touched_count": len(touched),
                "touched_share_pct": _pct_decimal(len(touched), len(completed)),
                "tp_after_count": len(tp_after),
                "sl_after_count": len(sl_after),
                "tp_given_touch_pct": _pct_decimal(len(tp_after), len(touched)),
                "sl_given_touch_pct": _pct_decimal(len(sl_after), len(touched)),
            }
        )
    winners = [item for item in completed if item.get("result_status") == "TP_HIT"]
    losers = [item for item in completed if item.get("result_status") == "SL_HIT"]
    winner_mae = _mid_long_item_values(winners, "mae_r")
    loser_mfe = _mid_long_item_values(losers, "mfe_r")
    return {
        "mfe_threshold_rows": rows,
        "winner_mae_quantiles": {
            "q25": _percentile_decimal_snapshot(winner_mae, Decimal("0.25")),
            "q50": _percentile_decimal_snapshot(winner_mae, Decimal("0.50")),
            "q75": _percentile_decimal_snapshot(winner_mae, Decimal("0.75")),
            "q90": _percentile_decimal_snapshot(winner_mae, Decimal("0.90")),
        },
        "loser_mfe_quantiles": {
            "q25": _percentile_decimal_snapshot(loser_mfe, Decimal("0.25")),
            "q50": _percentile_decimal_snapshot(loser_mfe, Decimal("0.50")),
            "q75": _percentile_decimal_snapshot(loser_mfe, Decimal("0.75")),
            "q90": _percentile_decimal_snapshot(loser_mfe, Decimal("0.90")),
        },
        "read": _mid_long_geometry_read(rows),
    }


def _mid_long_ablation_preview(
    items: list[dict[str, Any]],
    *,
    axis_states: dict[str, dict[str, str]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    scenarios: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
        ("DROP_EXTENDED", "Remove extended entries", (("EXT", "EXTENDED"),)),
        ("DROP_UNDER_RESISTANCE", "Remove under-resistance entries", (("STR", "UNDER_RESISTANCE"),)),
        ("DROP_WEAK_FLOW", "Remove weak-flow entries", (("FLW", "WEAK"),)),
        ("DROP_CROWDED", "Remove crowded-long entries", (("CRD", "CROWDED"),)),
        (
            "DROP_EXTENDED_OR_UNDER_RESISTANCE",
            "Remove extended OR under resistance",
            (("EXT", "EXTENDED"), ("STR", "UNDER_RESISTANCE")),
        ),
        (
            "KEEP_CLEAN_CONTINUATION",
            "Keep normal + confirmed flow + clean crowding",
            (("EXT", "NORMAL"), ("FLW", "CONFIRMED"), ("CRD", "CLEAN")),
        ),
    )
    rows: list[dict[str, Any]] = []
    for scenario_id, label, rules in scenarios:
        selected: list[dict[str, Any]] = []
        discarded: list[dict[str, Any]] = []
        if scenario_id == "KEEP_CLEAN_CONTINUATION":
            for idx, item in enumerate(items):
                states = axis_states[str(item.get("signal_id") or idx)]
                if all(states[axis] == state for axis, state in rules):
                    selected.append(item)
                else:
                    discarded.append(item)
            expression = " AND ".join(f"{axis} == {state}" for axis, state in rules)
        else:
            for idx, item in enumerate(items):
                states = axis_states[str(item.get("signal_id") or idx)]
                if any(states[axis] == state for axis, state in rules):
                    discarded.append(item)
                else:
                    selected.append(item)
            expression = "Remove rows where " + " OR ".join(f"{axis} == {state}" for axis, state in rules)
        row = _mid_long_perf_row(
            scenario_id,
            label,
            expression,
            selected,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        discarded_perf = aggregate_signal_performance_items(discarded)
        row.update(
            {
                "discarded_count": len(discarded),
                "discarded_tp_count": discarded_perf["tp_count"],
                "discarded_sl_count": discarded_perf["sl_count"],
                "discarded_realistic_total_r_closed": discarded_perf["realistic_total_r_closed"],
                "discarded_realistic_avg_r_closed": discarded_perf["realistic_avg_r_closed"],
                "ablation_read": _mid_long_ablation_read(row, discarded_perf),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero_snapshot(row.get("realistic_total_r_delta_vs_baseline")),
        ),
        reverse=True,
    )
    return rows


def _mid_long_definition_verdict(
    *,
    baseline: dict[str, Any],
    layer_rows: list[dict[str, Any]],
    path_summary: dict[str, Any],
    axis_rows: list[dict[str, Any]],
    geometry: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    labels: list[str] = []
    ideal_total = _decimal_or_zero_snapshot(baseline.get("ideal_total_r_closed"))
    realistic_total = _decimal_or_zero_snapshot(baseline.get("realistic_total_r_closed"))
    if ideal_total <= 0:
        labels.append("ENTRY_OR_EDGE_PROBLEM")
        reasons.append("Ideal R is not positive, so the issue exists before realistic costs.")
    elif realistic_total <= 0:
        labels.append("EXECUTION_COST_PROBLEM")
        reasons.append("Ideal R is positive while realistic R is not; fee/spread/slippage drag matters.")
    path_read = str(path_summary.get("read") or "")
    if path_read == "ENTRY_DEFINITION_PRESSURE":
        labels.append("ENTRY_DEFINITION_PROBLEM")
        reasons.append("Instant-SL share is high enough to suspect the entry definition.")
    if path_read == "GEOMETRY_OR_EXIT_PRESSURE":
        labels.append("GEOMETRY_PROBLEM")
        reasons.append("Many rows move in favor before failing, suggesting target/exit geometry needs study.")
    damaging_axis = [
        row
        for row in axis_rows
        if _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")) < 0
        and _decimal_or_zero_snapshot(row.get("negative_r_share_pct")) >= Decimal("20")
    ]
    if damaging_axis:
        labels.append("AXIS_DAMAGE_CONCENTRATION")
        top = max(damaging_axis, key=lambda row: _decimal_or_zero_snapshot(row.get("negative_r_share_pct")))
        reasons.append(
            f"{top.get('axis')}:{top.get('state')} explains {top.get('negative_r_share_pct')}% of negative R."
        )
    geometry_read = str(geometry.get("read") or "")
    if geometry_read == "HARVEST_PROBLEM":
        labels.append("GEOMETRY_PROBLEM")
        reasons.append("P(TP after +1R) is weak; the setup may be right but harvesting is poor.")
    if not labels:
        labels.append("MIXED_OR_INSUFFICIENT_SEPARATION")
        reasons.append("No single layer dominates yet; read axis and path tables together.")
    primary = "MIXED_PROBLEM" if len(set(labels)) > 1 else labels[0]
    return {
        "primary": primary,
        "labels": sorted(set(labels)),
        "reasons": reasons,
        "recommended_next_step": "Run decision-tree/ablation only after this audit is reviewed; do not promote V2.1 from this page alone.",
    }


def _mid_long_definition_axis_state(item: dict[str, Any]) -> dict[str, str]:
    return {
        "EXT": _mid_long_ext_state(item),
        "STR": _mid_long_structure_state(item),
        "FLW": _mid_long_flow_state(item),
        "CRD": _mid_long_crowding_state(item),
    }


def _mid_long_ext_state(item: dict[str, Any]) -> str:
    atr_extension = _mid_long_evidence_value(item, "atr_extension_normalized")
    price_atr = _mid_long_evidence_value(item, "price_atr_multiple")
    if atr_extension is None and price_atr is None:
        return "UNKNOWN"
    if (atr_extension is not None and atr_extension >= Decimal("1.00")) or (
        price_atr is not None and price_atr >= Decimal("1.25")
    ):
        return "EXTENDED"
    return "NORMAL"


def _mid_long_structure_state(item: dict[str, Any]) -> str:
    status = str(item.get("structure_zone_status") or "").upper()
    primary = str(item.get("structure_zone_primary_state") or "").upper()
    context = str(item.get("structure_zone_context_status") or "").upper()
    if not status and not primary and not context:
        return "UNAVAILABLE"
    if "RESISTANCE" in primary and "BREAK" not in primary:
        return "UNDER_RESISTANCE"
    if "CONFLICT" in status or "CONFLICT" in context:
        return "UNDER_RESISTANCE"
    if "BREAKOUT" in primary:
        return "BREAKOUT_CONFIRMED"
    if "SUPPORT" in primary:
        return "AT_SUPPORT"
    if "NEUTRAL" in status or "MID" in primary or "RANGE" in primary:
        return "MID_RANGE"
    if "UNAVAILABLE" in status or "UNKNOWN" in primary:
        return "UNAVAILABLE"
    if "ALIGNED" in status:
        return "BREAKOUT_CONFIRMED"
    return "MID_RANGE"


def _mid_long_flow_state(item: dict[str, Any]) -> str:
    volume = _mid_long_evidence_value(item, "volume_ratio_vs_lookback")
    taker_buy = _mid_long_evidence_value(item, "kline_taker_buy_ratio")
    oi_change = _mid_long_evidence_value(item, "oi_change_pct")
    if volume is None and taker_buy is None and oi_change is None:
        return "UNKNOWN"
    checks = [
        volume is not None and volume >= Decimal("1.00"),
        taker_buy is not None and taker_buy >= Decimal("0.53"),
        oi_change is not None and oi_change > Decimal("0"),
    ]
    passed = sum(1 for check in checks if check)
    if passed == 3:
        return "CONFIRMED"
    if passed <= 1:
        return "WEAK"
    return "MIXED"


def _mid_long_crowding_state(item: dict[str, Any]) -> str:
    funding = _mid_long_evidence_value(item, "funding_percentile_30d")
    oi_z = _mid_long_evidence_value(item, "oi_zscore")
    glsr = _mid_long_evidence_value(item, "global_long_short_ratio")
    top_position = _mid_long_evidence_value(item, "top_trader_position_ratio")
    if funding is None and oi_z is None and glsr is None and top_position is None:
        return "UNKNOWN"
    crowded_funding = funding is not None and funding >= Decimal("75")
    crowded_oi_positioning = (
        oi_z is not None
        and oi_z >= Decimal("3")
        and (
            (glsr is not None and glsr >= Decimal("1.30"))
            or (top_position is not None and top_position >= Decimal("1.40"))
        )
    )
    if crowded_funding or crowded_oi_positioning:
        return "CROWDED"
    return "CLEAN"


def _mid_long_execution_state(item: dict[str, Any]) -> str:
    fill = str(item.get("realistic_fill_quality") or "")
    cost = _decimal_or_none_snapshot(item.get("realistic_cost_r_estimate"))
    if fill == "FILL_GOOD" or (cost is not None and cost <= Decimal("0.20")):
        return "EXECUTION_VALID"
    if fill == "FILL_BAD" or (cost is not None and cost > Decimal("0.20")):
        return "EXECUTION_RISK"
    return "EXECUTION_UNKNOWN"


def _mid_long_total_negative_r(items: list[dict[str, Any]]) -> Decimal:
    total = Decimal("0")
    for item in items:
        value = _decimal_or_none_snapshot(item.get("realistic_realized_r"))
        if value is not None and value < 0:
            total += abs(value)
    return total


def _pct_decimal_decimal(count: Decimal, total: Decimal) -> Decimal | None:
    if total <= 0:
        return None
    return count / total * Decimal("100")


def _mid_long_top_n_symbol_share(items: list[dict[str, Any]], *, n: int) -> Decimal | None:
    if not items:
        return None
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    top_count = sum(count for _symbol, count in symbols.most_common(n))
    return _pct_decimal(top_count, len(items))


def _mid_long_axis_state_read(axis: str, state: str, row: dict[str, Any]) -> str:
    total_r = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    if axis == "EXT" and state == "EXTENDED":
        return "Candidate late-chase damage flag." if total_r < 0 else "Extended entries are not harmful in this sample yet."
    if axis == "STR" and state == "UNDER_RESISTANCE":
        return "Candidate resistance-trap flag." if total_r < 0 else "Under-resistance entries need manual chart review."
    if axis == "FLW" and state == "WEAK":
        return "Candidate weak-sponsorship flag." if total_r < 0 else "Weak flow is not isolating damage yet."
    if axis == "CRD" and state == "CROWDED":
        return "Candidate crowded-long risk flag." if total_r < 0 else "Crowded context is not harmful in this sample yet."
    return "Definition audit state; compare with complement and cross tables."


def _mid_long_geometry_read(rows: list[dict[str, Any]]) -> str:
    plus_one = next((row for row in rows if _decimal_or_zero_snapshot(row.get("threshold_r")) == Decimal("1.00")), None)
    if not plus_one:
        return "INSUFFICIENT_DATA"
    touched = int(plus_one.get("touched_count") or 0)
    tp_after_pct = _decimal_or_none_snapshot(plus_one.get("tp_given_touch_pct"))
    if touched >= 20 and tp_after_pct is not None and tp_after_pct < Decimal("60"):
        return "HARVEST_PROBLEM"
    return "GEOMETRY_NOT_PRIMARY_YET"


def _mid_long_ablation_read(row: dict[str, Any], discarded_perf: dict[str, Any]) -> str:
    survivor_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    discarded_total = _decimal_or_zero_snapshot(discarded_perf.get("realistic_total_r_closed"))
    if survivor_delta > 0 and discarded_total < 0:
        return "Candidate gate: discarded set is negative and survivors improve."
    if survivor_delta > 0:
        return "Survivors improve, but check discarded set and sample starvation."
    return "Does not improve baseline; keep as evidence only."


def _mid_long_entry_anatomy_summary(items: list[dict[str, Any]], *, baseline: dict[str, Any]) -> dict[str, Any]:
    tp_items = [item for item in items if item.get("result_status") == "TP_HIT"]
    sl_items = [item for item in items if item.get("result_status") == "SL_HIT"]
    tp_area = _mid_long_dominant_area(tp_items)
    sl_area = _mid_long_dominant_area(sl_items)
    zone_rows = _mid_long_entry_area_anatomy(items, baseline=baseline, min_sample=20)
    best_zone = max(
        zone_rows,
        key=lambda row: (
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed")),
        ),
        default=None,
    )
    worst_zone = min(
        zone_rows,
        key=lambda row: (
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed")),
        ),
        default=None,
    )
    return {
        "question": "Where do MID_LONG 1h winners and losers enter, and what evidence profile separates them?",
        "read": _mid_long_entry_anatomy_read(baseline, best_zone=best_zone, worst_zone=worst_zone),
        "dominant_tp_area": tp_area,
        "dominant_sl_area": sl_area,
        "best_area": _mid_long_area_summary(best_zone),
        "worst_area": _mid_long_area_summary(worst_zone),
        "hypothesis": _mid_long_entry_anatomy_hypothesis(best_zone=best_zone, worst_zone=worst_zone),
        "guardrail": "Read-only anatomy. This does not change Signal Factory, scanner, TP/SL, or execution.",
    }


def _mid_long_entry_anatomy_read(
    baseline: dict[str, Any],
    *,
    best_zone: dict[str, Any] | None,
    worst_zone: dict[str, Any] | None,
) -> str:
    realistic_total = _decimal_or_zero_snapshot(baseline.get("realistic_total_r_closed"))
    if realistic_total >= 0:
        return "BASELINE_NOT_CURRENTLY_BAD"
    if worst_zone and str(worst_zone.get("structure_zone_status") or "") == "ZONE_NEUTRAL":
        return "ZONE_NEUTRAL_DAMAGE_DOMINANT"
    if best_zone and str(best_zone.get("structure_zone_status") or "") == "ZONE_ALIGNED":
        return "ZONE_ALIGNMENT_IS_PRIMARY_CLUE"
    return "ENTRY_AREA_AND_EVIDENCE_MIXED"


def _mid_long_entry_anatomy_hypothesis(
    *,
    best_zone: dict[str, Any] | None,
    worst_zone: dict[str, Any] | None,
) -> str:
    best_status = str((best_zone or {}).get("structure_zone_status") or "")
    worst_status = str((worst_zone or {}).get("structure_zone_status") or "")
    if best_status == "ZONE_ALIGNED" and worst_status == "ZONE_NEUTRAL":
        return "MID_LONG likely needs structural confirmation; neutral-range long entries appear to carry most damage."
    if worst_status == "ZONE_CONFLICT":
        return "MID_LONG losses are concentrated where structure conflicts with the long setup."
    return "No single entry-area cause is isolated yet; keep reading area plus evidence together."


def _mid_long_area_summary(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "area_id": row.get("area_id"),
        "label": row.get("label"),
        "closed_count": row.get("closed_count"),
        "tp_count": row.get("tp_count"),
        "sl_count": row.get("sl_count"),
        "realistic_total_r_closed": row.get("realistic_total_r_closed"),
        "realistic_avg_r_closed": row.get("realistic_avg_r_closed"),
        "note": row.get("note"),
    }


def _mid_long_outcome_entry_profiles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for status, label in (("TP_HIT", "Winners / TP"), ("SL_HIT", "Losers / SL")):
        status_items = [item for item in items if item.get("result_status") == status]
        rows.append(
            {
                "result_status": status,
                "label": label,
                "sample_count": len(status_items),
                "dominant_area": _mid_long_dominant_area(status_items),
                "evidence_medians": _mid_long_evidence_medians(status_items),
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_values(status_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_values(status_items, "mae_r")),
                "median_realistic_r": _median_decimal_snapshot(_mid_long_item_values(status_items, "realistic_realized_r")),
            }
        )
    return rows


def _mid_long_dominant_area(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[_mid_long_area_id(item)].append(item)
    area_id, area_items = max(grouped.items(), key=lambda pair: len(pair[1]))
    example = area_items[0]
    return {
        "area_id": area_id,
        "label": _mid_long_area_label(example),
        "structure_zone_status": str(example.get("structure_zone_status") or "UNKNOWN"),
        "primary_state": str(example.get("structure_zone_primary_state") or "UNKNOWN"),
        "context_status": str(example.get("structure_zone_context_status") or "UNKNOWN"),
        "count": len(area_items),
        "share_pct": _pct_decimal(len(area_items), len(items)),
    }


def _mid_long_entry_area_anatomy(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[_mid_long_area_id(item)].append(item)
    rows: list[dict[str, Any]] = []
    for area_id, area_items in grouped.items():
        if len(area_items) < min_sample:
            continue
        example = area_items[0]
        row = _mid_long_perf_row(
            area_id,
            _mid_long_area_label(example),
            _mid_long_area_expression(example),
            area_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "area_id": area_id,
                "structure_zone_status": str(example.get("structure_zone_status") or "UNKNOWN"),
                "primary_state": str(example.get("structure_zone_primary_state") or "UNKNOWN"),
                "context_status": str(example.get("structure_zone_context_status") or "UNKNOWN"),
                "nearest_support_distance_atr_median": _median_decimal_snapshot(
                    _mid_long_item_values(area_items, "structure_zone_nearest_support_distance_atr")
                ),
                "nearest_resistance_distance_atr_median": _median_decimal_snapshot(
                    _mid_long_item_values(area_items, "structure_zone_nearest_resistance_distance_atr")
                ),
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_values(area_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_values(area_items, "mae_r")),
                "evidence_medians": _mid_long_evidence_medians(area_items),
                "tp_evidence_medians": _mid_long_evidence_medians(
                    [item for item in area_items if item.get("result_status") == "TP_HIT"]
                ),
                "sl_evidence_medians": _mid_long_evidence_medians(
                    [item for item in area_items if item.get("result_status") == "SL_HIT"]
                ),
            }
        )
        row["note"] = _mid_long_area_note(row)
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_path_anatomy(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[_mid_long_path_bucket(item)].append(item)
    rows: list[dict[str, Any]] = []
    for bucket, bucket_items in grouped.items():
        if len(bucket_items) < min_sample:
            continue
        row = _mid_long_perf_row(
            bucket,
            _mid_long_path_label(bucket),
            _mid_long_path_expression(bucket),
            bucket_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "path_bucket": bucket,
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_values(bucket_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_values(bucket_items, "mae_r")),
                "dominant_area": _mid_long_dominant_area(bucket_items),
                "evidence_medians": _mid_long_evidence_medians(bucket_items),
            }
        )
        row["note"] = _mid_long_path_note(bucket)
        rows.append(row)
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0),
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
        ),
        reverse=True,
    )
    return rows


def _mid_long_area_id(item: dict[str, Any]) -> str:
    return "|".join(
        (
            str(item.get("structure_zone_status") or "UNKNOWN"),
            str(item.get("structure_zone_primary_state") or "UNKNOWN"),
            str(item.get("structure_zone_context_status") or "UNKNOWN"),
        )
    )


def _mid_long_area_label(item: dict[str, Any]) -> str:
    return " / ".join(
        (
            str(item.get("structure_zone_status") or "UNKNOWN"),
            str(item.get("structure_zone_primary_state") or "UNKNOWN"),
            str(item.get("structure_zone_context_status") or "UNKNOWN"),
        )
    )


def _mid_long_area_expression(item: dict[str, Any]) -> str:
    return (
        f"structure_zone_status == {item.get('structure_zone_status') or 'UNKNOWN'}; "
        f"primary == {item.get('structure_zone_primary_state') or 'UNKNOWN'}; "
        f"context == {item.get('structure_zone_context_status') or 'UNKNOWN'}"
    )


def _mid_long_area_note(row: dict[str, Any]) -> str:
    total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    status = str(row.get("structure_zone_status") or "")
    if total >= 0 and status == "ZONE_ALIGNED":
        return "Area ini paling layak dibedah lanjut: struktur mendukung dan damage rendah/positif."
    if total < 0 and status == "ZONE_NEUTRAL":
        return "Area ini kandidat penyebab utama loss: long masuk tanpa support/resistance interaction jelas."
    if total < 0 and status == "ZONE_CONFLICT":
        return "Area ini berlawanan dengan konteks struktur; jangan dipromosikan tanpa filter tambahan."
    if total < 0:
        return "Masih negatif; perlu lihat evidence dan path setelah entry."
    return "Positif secara sample ini, tapi tetap read-only sampai divalidasi waktu."


def _mid_long_path_bucket(item: dict[str, Any]) -> str:
    status = str(item.get("result_status") or "UNKNOWN")
    mfe = _decimal_or_zero_snapshot(item.get("mfe_r"))
    mae = _decimal_or_zero_snapshot(item.get("mae_r"))
    if status == "TP_HIT":
        if mae <= Decimal("-0.75"):
            return "TP_AFTER_DEEP_PULLBACK"
        if mae <= Decimal("-0.50"):
            return "TP_AFTER_PULLBACK"
        return "TP_CLEAN_OR_SHALLOW_PULLBACK"
    if status == "SL_HIT":
        if mfe >= Decimal("1.25"):
            return "SL_AFTER_STRONG_PROFIT"
        if mfe >= Decimal("0.75"):
            return "SL_AFTER_PARTIAL_PROFIT"
        if mfe >= Decimal("0.25"):
            return "SL_WEAK_FOLLOW_THROUGH"
        return "SL_NO_FOLLOW_THROUGH"
    if status == "BOTH_HIT_SAME_CANDLE":
        return "BOTH_SAME_CANDLE"
    return status


def _mid_long_path_label(bucket: str) -> str:
    return {
        "TP_AFTER_DEEP_PULLBACK": "TP after deep pullback",
        "TP_AFTER_PULLBACK": "TP after pullback",
        "TP_CLEAN_OR_SHALLOW_PULLBACK": "TP clean / shallow pullback",
        "SL_AFTER_STRONG_PROFIT": "SL after strong profit",
        "SL_AFTER_PARTIAL_PROFIT": "SL after partial profit",
        "SL_WEAK_FOLLOW_THROUGH": "SL weak follow-through",
        "SL_NO_FOLLOW_THROUGH": "SL no follow-through",
        "BOTH_SAME_CANDLE": "Both hit same candle",
    }.get(bucket, bucket)


def _mid_long_path_expression(bucket: str) -> str:
    return {
        "TP_AFTER_DEEP_PULLBACK": "TP_HIT with MAE <= -0.75R before target",
        "TP_AFTER_PULLBACK": "TP_HIT with -0.75R < MAE <= -0.50R",
        "TP_CLEAN_OR_SHALLOW_PULLBACK": "TP_HIT with MAE > -0.50R",
        "SL_AFTER_STRONG_PROFIT": "SL_HIT after MFE >= +1.25R",
        "SL_AFTER_PARTIAL_PROFIT": "SL_HIT after +0.75R <= MFE < +1.25R",
        "SL_WEAK_FOLLOW_THROUGH": "SL_HIT after +0.25R <= MFE < +0.75R",
        "SL_NO_FOLLOW_THROUGH": "SL_HIT with MFE < +0.25R",
        "BOTH_SAME_CANDLE": "TP and SL touched in the same candle",
    }.get(bucket, bucket)


def _mid_long_path_note(bucket: str) -> str:
    return {
        "SL_AFTER_STRONG_PROFIT": "Target/exit geometry may be too greedy for this subset.",
        "SL_AFTER_PARTIAL_PROFIT": "There is follow-through, but not enough persistence; candidate for target/timeout study.",
        "SL_WEAK_FOLLOW_THROUGH": "Weak continuation after entry; likely entry quality or regime issue.",
        "SL_NO_FOLLOW_THROUGH": "Immediate failure bucket; likely wrong area/direction signal.",
        "TP_AFTER_DEEP_PULLBACK": "Winning trades can tolerate deep pullback, so tighter stop may cut some winners.",
        "TP_AFTER_PULLBACK": "Winning trades often need some room before target.",
        "TP_CLEAN_OR_SHALLOW_PULLBACK": "Cleanest winner path; use as reference profile.",
    }.get(bucket, "Path bucket for read-only anatomy.")


def _mid_long_evidence_medians(items: list[dict[str, Any]]) -> dict[str, Any]:
    medians: dict[str, Any] = {}
    for field, _label in MID_LONG_ANATOMY_EVIDENCE_FIELDS:
        medians[field] = _median_decimal_snapshot(
            [
                value
                for item in items
                if (value := _mid_long_evidence_value(item, field)) is not None
            ]
        )
    medians["nearest_support_distance_atr"] = _median_decimal_snapshot(
        _mid_long_item_values(items, "structure_zone_nearest_support_distance_atr")
    )
    medians["nearest_resistance_distance_atr"] = _median_decimal_snapshot(
        _mid_long_item_values(items, "structure_zone_nearest_resistance_distance_atr")
    )
    return medians


def _mid_long_item_values(items: list[dict[str, Any]], field: str) -> list[Decimal]:
    values: list[Decimal] = []
    for item in items:
        value = _decimal_or_none_snapshot(item.get(field))
        if value is not None:
            values.append(value)
    return values


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
