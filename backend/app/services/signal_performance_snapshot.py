from __future__ import annotations

import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

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
MID_LONG_1H_BASELINE_FILE = "mid_long_1h_baseline.json"
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
            performance_1h_payload, forward_integrity_1h_payload = service.summary_and_forward_integrity(
                epoch=epoch,
                include_watch_only=False,
                position_lock=True,
                stage=None,
                timeframe="1h",
                symbol=None,
                result_status="closed",
                performance_limit=max(DEFAULT_PERFORMANCE_1H_LIMIT, performance_limit),
                forward_integrity_limit=max(1, forward_integrity_limit),
            )
            performance_1h = _with_snapshot_meta(
                performance_1h_payload,
                generated_at_utc=generated_at,
                source="signal_performance_snapshot_1h",
                filename=PERFORMANCE_1H_FILE,
            )
            forward_integrity_1h = _with_snapshot_meta(
                forward_integrity_1h_payload,
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
            mid_long_started = perf_counter()
            mid_long_baseline_payload = _mid_long_1h_baseline_payload(
                performance_1h,
                limit=DEFAULT_RESEARCH_LIMIT,
                items_enricher=service.enrich_mid_long_1h_breakout_diagnostics,
                exact_replay_builder=service.mid_long_1h_first_hour_exact_replay,
            )
            mid_long_baseline_payload["artifact_status"] = "FRESH"
            mid_long_baseline_payload["calculation_duration_ms"] = int((perf_counter() - mid_long_started) * 1000)
            mid_long_baseline = _with_snapshot_meta(
                mid_long_baseline_payload,
                generated_at_utc=generated_at,
                source="mid_long_1h_baseline_snapshot",
                filename=MID_LONG_1H_BASELINE_FILE,
            )
            _atomic_write_json(
                self.artifact_dir / MID_LONG_1H_BASELINE_FILE,
                json_safe(mid_long_baseline),
            )
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
                    "mid_long_1h_baseline_path": str(self.artifact_dir / MID_LONG_1H_BASELINE_FILE),
                    "mid_short_filter_combo_1h_path": str(self.artifact_dir / MID_SHORT_FILTER_COMBO_1H_FILE),
                    "performance_1h_items": len(performance_1h.get("items") or []),
                    "performance_1h_compact_items": min(
                        len(performance_1h.get("items") or []),
                        DEFAULT_PERFORMANCE_COMPACT_LIMIT,
                    ),
                    "forward_integrity_1h_items": len(forward_integrity_1h.get("items") or []),
                    "mid_long_1h_rows": (mid_long_baseline.get("snapshot_coverage") or {}).get("mid_long_1h_rows", 0),
                    "mid_long_1h_calculation_duration_ms": mid_long_baseline_payload.get("calculation_duration_ms"),
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

    def mid_long_1h_baseline(
        self,
        *,
        limit: int,
        items_enricher: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        artifact_path = self.artifact_dir / MID_LONG_1H_BASELINE_FILE
        if artifact_path.exists():
            return _slice_payload(
                self._read(MID_LONG_1H_BASELINE_FILE),
                limit=max(1, limit),
                list_keys=("items",),
            )
        return _mid_long_1h_baseline_payload(
            self._read(PERFORMANCE_1H_FILE),
            limit=max(1, limit),
            items_enricher=items_enricher,
        )

    def long_definition_lab(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(PERFORMANCE_1H_FILE)
        return _long_definition_lab_payload(payload, limit=max(1, limit))

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


def _mid_long_1h_baseline_payload(
    payload: dict[str, Any],
    *,
    limit: int,
    items_enricher: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    exact_replay_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    aggregate = payload.get("aggregate") or {}
    source_items = list(payload.get("items") or [])
    evaluated = [
        item
        for item in source_items
        if item.get("stage") == "MID_LONG" and item.get("timeframe") == "1h"
    ]
    evaluated.sort(key=lambda item: str(item.get("signal_timestamp") or ""), reverse=True)
    if items_enricher is not None:
        evaluated = items_enricher(evaluated)
    baseline_aggregate = aggregate_signal_performance_items(evaluated)
    source_total = int(aggregate.get("signals_evaluated") or len(source_items))
    baseline_research = _mid_long_baseline_research(
        evaluated,
        exact_replay_builder=exact_replay_builder,
    )
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


LONG_DEFINITION_FAMILIES: tuple[dict[str, str], ...] = (
    {
        "family_id": "BREAKOUT_LONG_PROXY",
        "family_label": "Breakout Long Proxy",
        "family_role": "candidate",
        "description": "Close menembus zona/resistance dengan room ke resistance berikutnya masih cukup.",
    },
    {
        "family_id": "RETEST_LONG_PROXY",
        "family_label": "Retest Long Proxy",
        "family_role": "candidate",
        "description": "Entry dekat support/retest/flip zone, bukan chase di tengah range.",
    },
    {
        "family_id": "SQUEEZE_LONG_PROXY",
        "family_label": "Squeeze Long Proxy",
        "family_role": "candidate",
        "description": "Harga naik saat OI turun dan taker buy dominan; dibaca sebagai squeeze/context, bukan entry live.",
    },
    {
        "family_id": "LATE_CHASE_LONG",
        "family_label": "Late Chase Long",
        "family_role": "reject",
        "description": "Entry terlalu extended atau room ke resistance terlalu sempit.",
    },
    {
        "family_id": "CROWDED_LONG",
        "family_label": "Crowded Long",
        "family_role": "reject",
        "description": "Long crowding tinggi dari funding/OI/positioning sehingga raw bullish impulse dicurigai rapuh.",
    },
    {
        "family_id": "UNCLASSIFIED_LONG",
        "family_label": "Unclassified Long",
        "family_role": "unknown",
        "description": "Belum punya pola pre-entry yang cukup jelas untuk disebut breakout, retest, squeeze, late chase, atau crowded.",
    },
)


def _long_definition_lab_payload(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
    source_items = list(payload.get("items") or [])
    long_items = [
        item
        for item in source_items
        if str(item.get("timeframe") or "") == "1h"
        and str(item.get("direction") or "").upper().startswith("LONG")
        and str(item.get("stage") or "") in {"MID_LONG", "EARLY_LONG"}
    ]
    long_items.sort(key=lambda item: str(item.get("signal_timestamp") or ""), reverse=True)
    baseline = _mid_long_perf_row(
        "LONG_1H_LEGACY_CONTROL",
        "Legacy long 1h control",
        "stage in EARLY_LONG/MID_LONG and direction LONG",
        long_items,
        baseline=None,
        required_fields=(),
        min_sample=20,
    )
    family_specs = {spec["family_id"]: spec for spec in LONG_DEFINITION_FAMILIES}
    family_items: dict[str, list[dict[str, Any]]] = {str(spec["family_id"]): [] for spec in LONG_DEFINITION_FAMILIES}
    classified_rows: list[dict[str, Any]] = []
    for item in long_items:
        classification = _long_definition_classification(item)
        family_items[classification["family_id"]].append(item)
        classified_rows.append(_long_definition_signal_row(item, classification))

    family_rows: list[dict[str, Any]] = []
    for family_id, items in family_items.items():
        spec = family_specs[family_id]
        if not items:
            row = {
                "filter_id": family_id,
                "label": spec["family_label"],
                "expression": spec["description"],
                "required_fields": [],
                "missing_data_count": 0,
                "sample_count": 0,
                "sample_retention_pct": _pct_decimal(0, len(long_items)),
                "closed_count": 0,
                "tp_count": 0,
                "sl_count": 0,
                "both_hit_count": 0,
                "winrate_pct": None,
                "sl_share_pct": None,
                "ideal_total_r_closed": Decimal("0"),
                "realistic_total_r_closed": Decimal("0"),
                "realistic_avg_r_closed": None,
                "median_realistic_r_closed": None,
                "max_realistic_drawdown_r": Decimal("0"),
                "top_symbol": "-",
                "top_symbol_count": 0,
                "top_symbol_share_pct": None,
                "verdict": "SAMPLE_TOO_SMALL",
                "note": "Belum ada sample.",
            }
        else:
            row = _mid_long_perf_row(
                family_id,
                spec["family_label"],
                spec["description"],
                items,
                baseline=baseline,
                required_fields=(),
                min_sample=20,
            )
        row.update(
            {
                "family_id": family_id,
                "family_role": spec["family_role"],
                "family_label": spec["family_label"],
                "description": spec["description"],
                "research_status": _long_definition_family_verdict(row, str(spec["family_role"])),
            }
        )
        family_rows.append(row)

    candidate_rows = [row for row in family_rows if row["family_role"] == "candidate"]
    reject_rows = [row for row in family_rows if row["family_role"] == "reject"]
    best_candidate = _long_definition_best_candidate(candidate_rows)
    worst_reject = _long_definition_worst_bucket(reject_rows)
    return {
        "generated_at_utc": (payload.get("snapshot") or {}).get("generated_at_utc") or payload.get("generated_at_utc"),
        "lab_id": "LONG_1H_DEFINITION_LAB_V2",
        "scope": "long_1h_logged_v2_closed_signals",
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
        "production_rule_change": False,
        "filters": {
            "direction": "LONG",
            "timeframe": "1h",
            "stages": ["EARLY_LONG", "MID_LONG"],
            "position_lock": True,
            "include_watch_only": False,
            "result_status": "closed",
            "limit": max(1, limit),
        },
        "snapshot_coverage": {
            "source_1h_rows": len(source_items),
            "long_1h_rows": len(long_items),
            "mid_long_rows": sum(1 for item in long_items if item.get("stage") == "MID_LONG"),
            "early_long_rows": sum(1 for item in long_items if item.get("stage") == "EARLY_LONG"),
        },
        "latest_evaluation_candle_time": payload.get("latest_futures_15m_close_time")
        or payload.get("latest_evaluation_candle_time"),
        "legacy_control": baseline,
        "summary": {
            "read": _long_definition_lab_read(baseline, best_candidate, worst_reject),
            "raw_long_count": len(long_items),
            "candidate_family_count": sum(1 for row in candidate_rows if int(row.get("closed_count") or 0) > 0),
            "rejection_bucket_count": sum(1 for row in reject_rows if int(row.get("closed_count") or 0) > 0),
            "best_candidate_family": best_candidate,
            "worst_reject_bucket": worst_reject,
            "next_action": "Use this page to decide which long family deserves a shadow replay; do not promote legacy MID_LONG directly.",
        },
        "family_definitions": list(LONG_DEFINITION_FAMILIES),
        "family_rows": family_rows,
        "candidate_rows": candidate_rows,
        "rejection_rows": reject_rows,
        "latest_items": classified_rows[: max(1, limit)],
        "guardrails": [
            "This is a definition lab only; Signal Factory V2 live rules are unchanged.",
            "Families use pre-entry evidence and structure fields already logged in the snapshot.",
            "TP/SL/R are evaluation outputs only, never predictors for family assignment.",
            "Old EARLY_LONG and MID_LONG labels are treated as source labels, not final future definitions.",
        ],
        "snapshot": payload.get("snapshot"),
    }


def _long_definition_classification(item: dict[str, Any]) -> dict[str, Any]:
    taker_buy = _long_ratio_value(_mid_long_evidence_value(item, "kline_taker_buy_ratio"))
    price_return = _mid_long_evidence_value(item, "price_return")
    oi_change = _mid_long_evidence_value(item, "oi_change_pct")
    oi_zscore = _mid_long_evidence_value(item, "oi_zscore")
    funding = _mid_long_evidence_value(item, "funding_percentile_30d")
    global_ls = _mid_long_evidence_value(item, "global_long_short_ratio")
    top_position = _mid_long_evidence_value(item, "top_trader_position_ratio")
    top_account = _mid_long_evidence_value(item, "top_trader_account_ratio")
    atr_extension = _mid_long_evidence_value(item, "atr_extension_normalized")
    range_atr = _mid_long_evidence_value(item, "range_ratio_vs_atr")
    room_resistance = _long_item_decimal_any(item, ("room_to_next_resistance_atr", "breakout_room_to_next_resistance_atr"))
    entry_distance = _long_item_decimal_any(item, ("entry_distance_from_zone_atr", "breakout_entry_distance_from_zone_atr"))
    close_penetration = _long_item_decimal_any(item, ("close_penetration_atr", "breakout_close_penetration_atr"))
    body_above = _long_item_decimal_any(item, ("body_above_zone_ratio", "breakout_body_above_zone_ratio"))
    state_text = " ".join(
        str(item.get(key) or "")
        for key in (
            "structure_zone_status",
            "structure_zone_primary_state",
            "structure_zone_context_state",
            "structure_zone_reason",
            "structure_zone_shadow",
            "quality_shadow_reason",
        )
    ).upper()

    crowding_flags: list[str] = []
    if funding is not None and funding >= Decimal("100"):
        crowding_flags.append("funding_percentile=100")
    if oi_zscore is not None and oi_zscore >= Decimal("6.5"):
        crowding_flags.append("oi_zscore>=6.5")
    if global_ls is not None and global_ls >= Decimal("1.75"):
        crowding_flags.append("global_long_short>=1.75")
    if top_position is not None and top_position >= Decimal("1.90"):
        crowding_flags.append("top_position>=1.90")
    if top_account is not None and top_account >= Decimal("2.00"):
        crowding_flags.append("top_account>=2.00")

    chase_flags: list[str] = []
    if room_resistance is not None and room_resistance < Decimal("1.0"):
        chase_flags.append("room_to_resistance<1ATR")
    if atr_extension is not None and atr_extension >= Decimal("1.5"):
        chase_flags.append("atr_extension>=1.5")
    if range_atr is not None and range_atr >= Decimal("1.8"):
        chase_flags.append("range_vs_atr>=1.8")
    if entry_distance is not None and entry_distance >= Decimal("1.0"):
        chase_flags.append("entry_distance_from_zone>=1ATR")

    support_like = any(token in state_text for token in ("SUPPORT", "RETEST", "BOUNCE", "RECLAIM", "FLIP"))
    breakout_like = (
        any(token in state_text for token in ("BREAKOUT", "RESISTANCE_BREAKOUT", "ACCEPT"))
        or (close_penetration is not None and close_penetration >= Decimal("0.10"))
        or (body_above is not None and body_above >= Decimal("0.35"))
    )
    has_room = room_resistance is None or room_resistance >= Decimal("1.0")
    not_crowded = funding is None or funding <= Decimal("85")

    if len(crowding_flags) >= 3 or ("funding_percentile=100" in crowding_flags and len(crowding_flags) >= 2):
        return _long_definition_result("CROWDED_LONG", "Crowding long tinggi: " + ", ".join(crowding_flags), crowding_flags, chase_flags)
    if chase_flags:
        return _long_definition_result("LATE_CHASE_LONG", "Entry raw long terlihat telat/sempit: " + ", ".join(chase_flags), crowding_flags, chase_flags)
    if (
        price_return is not None
        and price_return > 0
        and oi_change is not None
        and oi_change < 0
        and taker_buy is not None
        and taker_buy >= Decimal("0.52")
        and has_room
        and not_crowded
    ):
        return _long_definition_result("SQUEEZE_LONG_PROXY", "Price naik + OI turun + taker buy dominan; dibaca squeeze proxy.", crowding_flags, chase_flags)
    if support_like and (entry_distance is None or entry_distance <= Decimal("0.75")) and has_room and (taker_buy is None or taker_buy >= Decimal("0.50")):
        return _long_definition_result("RETEST_LONG_PROXY", "Entry dekat support/retest/flip zone dengan room cukup.", crowding_flags, chase_flags)
    if breakout_like and has_room and (taker_buy is None or taker_buy >= Decimal("0.52")) and not_crowded:
        return _long_definition_result("BREAKOUT_LONG_PROXY", "Close/entry menembus zona dengan room dan taker buy cukup.", crowding_flags, chase_flags)
    return _long_definition_result("UNCLASSIFIED_LONG", "Belum cukup bukti untuk keluarga breakout/retest/squeeze atau rejection bucket.", crowding_flags, chase_flags)


def _long_definition_result(
    family_id: str,
    reason: str,
    crowding_flags: list[str],
    chase_flags: list[str],
) -> dict[str, Any]:
    spec = next(spec for spec in LONG_DEFINITION_FAMILIES if spec["family_id"] == family_id)
    return {
        "family_id": family_id,
        "family_label": spec["family_label"],
        "family_role": spec["family_role"],
        "family_reason": reason,
        "crowding_flags": crowding_flags,
        "anti_chase_flags": chase_flags,
    }


def _long_definition_signal_row(item: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": item.get("signal_id"),
        "symbol": item.get("symbol"),
        "source_stage": item.get("stage"),
        "timeframe": item.get("timeframe"),
        "direction": item.get("direction"),
        "signal_timestamp": item.get("signal_timestamp"),
        "signal_time_wib": item.get("signal_time_wib"),
        "result_status": item.get("result_status"),
        "realistic_realized_r": item.get("realistic_realized_r"),
        "mfe_r": item.get("mfe_r"),
        "mae_r": item.get("mae_r"),
        "family_id": classification["family_id"],
        "family_label": classification["family_label"],
        "family_role": classification["family_role"],
        "family_reason": classification["family_reason"],
        "crowding_flags": classification["crowding_flags"],
        "anti_chase_flags": classification["anti_chase_flags"],
        "price_return": _mid_long_evidence_value(item, "price_return"),
        "volume_ratio_vs_lookback": _mid_long_evidence_value(item, "volume_ratio_vs_lookback"),
        "taker_buy_ratio": _long_ratio_value(_mid_long_evidence_value(item, "kline_taker_buy_ratio")),
        "oi_change_pct": _mid_long_evidence_value(item, "oi_change_pct"),
        "oi_zscore": _mid_long_evidence_value(item, "oi_zscore"),
        "funding_percentile_30d": _mid_long_evidence_value(item, "funding_percentile_30d"),
        "room_to_next_resistance_atr": _long_item_decimal_any(item, ("room_to_next_resistance_atr", "breakout_room_to_next_resistance_atr")),
        "room_to_next_support_atr": _long_item_decimal_any(item, ("room_to_next_support_atr", "breakout_room_to_next_support_atr")),
        "entry_distance_from_zone_atr": _long_item_decimal_any(item, ("entry_distance_from_zone_atr", "breakout_entry_distance_from_zone_atr")),
        "atr_extension_normalized": _mid_long_evidence_value(item, "atr_extension_normalized"),
        "range_ratio_vs_atr": _mid_long_evidence_value(item, "range_ratio_vs_atr"),
        "close_penetration_atr": _long_item_decimal_any(item, ("close_penetration_atr", "breakout_close_penetration_atr")),
        "body_above_zone_ratio": _long_item_decimal_any(item, ("body_above_zone_ratio", "breakout_body_above_zone_ratio")),
        "structure_zone_status": item.get("structure_zone_status"),
        "structure_zone_primary_state": item.get("structure_zone_primary_state"),
    }


def _long_definition_family_verdict(row: dict[str, Any], role: str) -> str:
    closed = int(row.get("closed_count") or 0)
    total_r = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    avg_r = _decimal_or_none_snapshot(row.get("realistic_avg_r_closed"))
    top_share = _decimal_or_none_snapshot(row.get("top_symbol_share_pct"))
    if closed < 20:
        return "SAMPLE_TOO_SMALL"
    if role == "reject":
        return "DAMAGE_BUCKET" if total_r < 0 else "REJECT_BUCKET_NOT_CONFIRMED"
    if role == "candidate" and total_r > 0 and avg_r is not None and avg_r > 0 and (top_share is None or top_share <= Decimal("35")):
        return "LONG_RESEARCH_CANDIDATE"
    if role == "candidate" and total_r > 0:
        return "LONG_MONITOR_MORE"
    if role == "unknown":
        return "NEEDS_REDEFINITION"
    return "NO_LONG_EDGE_YET"


def _long_definition_best_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    readable = [row for row in rows if int(row.get("closed_count") or 0) >= 20]
    if not readable:
        return None
    return sorted(
        readable,
        key=lambda row: (
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed")),
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )[0]


def _long_definition_worst_bucket(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    readable = [row for row in rows if int(row.get("closed_count") or 0) >= 20]
    if not readable:
        return None
    return sorted(
        readable,
        key=lambda row: (
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed")),
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
        ),
    )[0]


def _long_definition_lab_read(
    baseline: dict[str, Any],
    best_candidate: dict[str, Any] | None,
    worst_reject: dict[str, Any] | None,
) -> str:
    if best_candidate and str(best_candidate.get("research_status")) == "LONG_RESEARCH_CANDIDATE":
        return "LONG_FAMILY_CANDIDATE_FOUND"
    if worst_reject and _decimal_or_zero_snapshot(worst_reject.get("realistic_total_r_closed")) < 0:
        return "LONG_DAMAGE_BUCKETS_IDENTIFIED"
    if _decimal_or_zero_snapshot(baseline.get("realistic_total_r_closed")) < 0:
        return "LEGACY_LONG_BASELINE_WEAK"
    return "LONG_DEFINITION_INCONCLUSIVE"


def _long_item_decimal_any(item: dict[str, Any], keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        value = _item_decimal(item, key)
        if value is not None:
            return value
    return None


def _long_ratio_value(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if value > Decimal("2"):
        return value / Decimal("100")
    return value


def _mid_long_baseline_research(
    items: list[dict[str, Any]],
    *,
    exact_replay_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    exact_replay = (
        exact_replay_builder(items, baseline=baseline, min_sample=20)
        if exact_replay_builder is not None
        else None
    )
    definition_audit = _mid_long_definition_audit(
        items,
        baseline=baseline,
        min_sample=20,
        first_hour_exact_replay=exact_replay,
    )
    reverse_shadow_audit = _mid_long_reverse_shadow_audit(items, min_sample=20)
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
        "reverse_shadow_audit": reverse_shadow_audit,
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

MID_LONG_BREAKOUT_AUDIT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("structure_zone_status", "Structure zone status", "top_level"),
    ("structure_zone_primary_state", "Primary zone state", "top_level"),
    ("structure_zone_primary_reason", "Primary zone reason", "top_level"),
    ("structure_zone_nearest_resistance_distance_atr", "Room to resistance ATR", "top_level"),
    ("structure_zone_nearest_support_distance_atr", "Distance to support ATR", "top_level"),
    ("path_label_050", "+0.5R path label", "post_entry_diagnostic"),
    ("path_events", "Path event timestamps", "post_entry_diagnostic"),
    ("wick_to_close_decay_r", "Wick-to-close decay R", "post_entry_diagnostic"),
    ("close_followthrough_1h_r", "1h close follow-through R", "post_entry_diagnostic"),
    ("atr_extension_normalized", "ATR extension", "evidence"),
    ("volume_ratio_vs_lookback", "Volume vs 30-candle lookback", "evidence"),
    ("kline_taker_buy_ratio", "Taker buy ratio", "evidence"),
    ("oi_change_pct", "OI change pct", "evidence"),
    ("oi_zscore", "OI z-score", "evidence"),
    ("funding_percentile_30d", "Funding percentile 30d", "evidence"),
    ("global_long_short_ratio", "Global long/short ratio", "evidence"),
    ("top_trader_position_ratio", "Top trader position ratio", "evidence"),
    ("top_trader_account_ratio", "Top trader account ratio", "evidence"),
    ("realistic_cost_r_estimate", "Realistic cost R", "top_level"),
    ("futures_spread_pct", "Futures spread pct", "evidence"),
    ("spot_spread_pct", "Spot spread pct", "evidence"),
    ("zone_lower", "Zone lower", "precise_zone_metric"),
    ("zone_upper", "Zone upper", "precise_zone_metric"),
    ("zone_center", "Zone center", "precise_zone_metric"),
    ("close_penetration_atr", "Close penetration ATR", "precise_zone_metric"),
    ("close_penetration_zone_width", "Close penetration zone width", "precise_zone_metric"),
    ("body_above_zone_ratio", "Body above zone ratio", "precise_zone_metric"),
    ("close_location_in_candle", "Close location in candle", "precise_zone_metric"),
    ("upper_wick_to_body_ratio", "Upper wick/body ratio", "precise_zone_metric"),
    ("breakout_candle_range_atr", "Breakout candle range ATR", "precise_zone_metric"),
    ("breakout_body_atr", "Breakout body ATR", "precise_zone_metric"),
    ("bars_since_breakout", "Bars since breakout", "precise_zone_metric"),
    ("entry_distance_from_zone_atr", "Entry distance from zone ATR", "precise_zone_metric"),
    ("entry_extension_from_zone_atr", "Entry extension from zone ATR", "precise_zone_metric"),
    ("room_to_next_resistance_atr", "Room to next resistance ATR", "precise_zone_metric"),
    ("room_to_next_support_atr", "Room to next support ATR", "precise_zone_metric"),
    ("zone_touch_count", "Zone touch count", "precise_zone_metric"),
    ("zone_age_bars", "Zone age bars", "precise_zone_metric"),
    ("zone_width_atr", "Zone width ATR", "precise_zone_metric"),
)


def _mid_long_definition_audit(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
    first_hour_exact_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    axis_states = {str(item.get("signal_id") or idx): _mid_long_definition_axis_state(item) for idx, item in enumerate(items)}
    taxonomy_by_id = _mid_long_taxonomy_by_id(items)
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
    taxonomy = _mid_long_taxonomy_context(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    integrity = _mid_long_integrity_audit(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    damage = _mid_long_damage_isolation(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    sl_anatomy = _mid_long_sl_anatomy_v2(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    first_hour_response = _mid_long_first_hour_response_audit(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    first_hour_action = _mid_long_first_hour_action_simulation(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    matched_contrastive = _mid_long_matched_contrastive_anatomy(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    damage_hurdle = _mid_long_family_damage_hurdle_study(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    dual_track_discovery = _mid_long_dual_track_pattern_discovery(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    definition_reset = _mid_long_definition_reset_lab(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    sub_setup = _mid_long_sub_setup_split_lab(
        items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    breakout_deep_dive = _mid_long_breakout_accepted_deep_dive(
        items,
        taxonomy_by_id=taxonomy_by_id,
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
        "taxonomy_study": taxonomy,
        "integrity_audit": integrity,
        "damage_isolation": damage,
        "sl_anatomy_v2": sl_anatomy,
        "first_hour_response_audit": first_hour_response,
        "first_hour_action_simulation": first_hour_action,
        "matched_contrastive_anatomy": matched_contrastive,
        "family_damage_hurdle_study": damage_hurdle,
        "dual_track_pattern_discovery": dual_track_discovery,
        "first_hour_exact_replay_lab": first_hour_exact_replay,
        "definition_reset_lab": definition_reset,
        "sub_setup_split_lab": sub_setup,
        "breakout_accepted_deep_dive": breakout_deep_dive,
        "verdict": verdict,
        "guardrails": [
            "Candidate flags are not live gates.",
            "No Signal Factory rule, scanner behavior, TP/SL, or execution logic is changed.",
            "Support/resistance readings must be treated as invalid if their timestamp uses future candles.",
            "Pre-entry taxonomy must not use post-entry follow-through as a live entry gate.",
            "Draft V2.1 previews are hypothesis previews only, not production rule changes.",
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


def _mid_long_taxonomy_context(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]] | None = None,
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    taxonomy_by_id = taxonomy_by_id or _mid_long_taxonomy_by_id(items)
    extension_values = [
        value
        for item in items
        if (value := _mid_long_evidence_value(item, "atr_extension_normalized")) is not None
    ]
    dimensions: tuple[tuple[str, str], ...] = (
        ("structure_status", "Structure status"),
        ("setup_family", "Setup family"),
        ("breakout_state_pre_entry", "Breakout pre-entry"),
        ("retest_quality_pre_entry", "Retest quality"),
        ("entry_timing_bucket", "Entry timing"),
        ("extension_bucket", "Extension bucket"),
        ("flow_state_provisional", "Flow state"),
        ("crowding_bucket", "Crowding bucket"),
        ("room_to_resistance_bucket", "Room to resistance"),
        ("projected_cost_bucket", "Projected cost"),
    )
    return {
        "scope": "MID_LONG 1h multidimensional taxonomy, read-only",
        "method": (
            "Pre-entry taxonomy is separated from post-entry path sequencing. "
            "Continuous fields remain the source of truth; buckets are provisional research labels."
        ),
        "canonical_acceptance_threshold_r": Decimal("0.50"),
        "extension_quantiles": {
            "q25": _percentile_decimal_snapshot(extension_values, Decimal("0.25")),
            "q75": _percentile_decimal_snapshot(extension_values, Decimal("0.75")),
            "q90": _percentile_decimal_snapshot(extension_values, Decimal("0.90")),
        },
        "dimension_rows": {
            key: _mid_long_taxonomy_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                dimension_key=key,
                dimension_label=label,
                baseline=baseline,
                min_sample=min_sample,
            )
            for key, label in dimensions
        },
        "path_sequence_rows": _mid_long_path_sequence_rows(items, baseline=baseline, min_sample=min_sample),
        "taxonomy_path_cross_tables": {
            "setup_family_x_path": _mid_long_taxonomy_path_cross_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="setup_family",
                taxonomy_label="Setup family",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "breakout_state_x_path": _mid_long_taxonomy_path_cross_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="breakout_state_pre_entry",
                taxonomy_label="Breakout pre-entry",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "flow_x_path": _mid_long_taxonomy_path_cross_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="flow_state_provisional",
                taxonomy_label="Flow",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "crowding_x_path": _mid_long_taxonomy_path_cross_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="crowding_bucket",
                taxonomy_label="Crowding",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "cost_x_path": _mid_long_taxonomy_path_cross_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="projected_cost_bucket",
                taxonomy_label="Projected cost",
                baseline=baseline,
                min_sample=min_sample,
            ),
        },
        "draft_v21_previews": _mid_long_draft_preview_rows(
            items,
            taxonomy_by_id=taxonomy_by_id,
            baseline=baseline,
            min_sample=min_sample,
        ),
        "raw_feature_notes": [
            "room_to_resistance uses current structure-zone ATR distance as a provisional proxy; final R-based room needs a stricter zone anchor.",
            "entry_timing uses ATR-extension quantile buckets until anchor-specific extension is available.",
            "breakout follow-through is post-entry diagnostic and must not be used as an entry gate.",
            "path_label_050 is based on +0.50R close acceptance; +0.25R/+0.75R/+1R events are retained in path_events when the snapshot is refreshed.",
        ],
    }


def _mid_long_taxonomy_by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    extension_values = [
        value
        for item in items
        if (value := _mid_long_evidence_value(item, "atr_extension_normalized")) is not None
    ]
    return {
        str(item.get("signal_id") or idx): _mid_long_taxonomy_state(
            item,
            extension_values=extension_values,
        )
        for idx, item in enumerate(items)
    }


def _mid_long_taxonomy_state(
    item: dict[str, Any],
    *,
    extension_values: list[Decimal],
) -> dict[str, Any]:
    structure_status = _mid_long_structure_status(item)
    setup_family = _mid_long_setup_family(item, structure_status=structure_status)
    extension_raw = _mid_long_evidence_value(item, "atr_extension_normalized")
    extension_bucket = _mid_long_quantile_bucket(extension_raw, extension_values)
    flow_state = _mid_long_flow_state(item)
    crowding_score = _mid_long_crowding_score(item)
    cost = _decimal_or_none_snapshot(item.get("realistic_cost_r_estimate"))
    room_to_resistance = _decimal_or_none_snapshot(item.get("structure_zone_nearest_resistance_distance_atr"))
    return {
        "structure_status": structure_status,
        "setup_family": setup_family,
        "breakout_state_pre_entry": _mid_long_breakout_state(item, setup_family=setup_family),
        "retest_quality_pre_entry": _mid_long_retest_quality(item, setup_family=setup_family),
        "entry_anchor_type": _mid_long_entry_anchor_type(setup_family),
        "entry_extension_raw": extension_raw,
        "entry_timing_bucket": _mid_long_entry_timing_bucket(setup_family, extension_bucket),
        "extension_bucket": extension_bucket,
        "flow_state_provisional": flow_state,
        "flow_regime": _mid_long_flow_regime(item),
        "crowding_score": crowding_score,
        "crowding_bucket": _mid_long_crowding_bucket(crowding_score),
        "room_to_resistance_atr": room_to_resistance,
        "room_to_resistance_bucket": _mid_long_room_bucket(room_to_resistance),
        "projected_cost_r": cost,
        "projected_cost_bucket": _mid_long_cost_bucket(cost),
        "path_label_050": _mid_long_path_label_050(item),
    }


def _mid_long_structure_status(item: dict[str, Any]) -> str:
    status = str(item.get("structure_zone_status") or "").upper()
    primary = str(item.get("structure_zone_primary_state") or "").upper()
    if not status or "UNAVAILABLE" in status:
        return "UNAVAILABLE"
    if not primary or "UNKNOWN" in primary:
        return "PARTIAL"
    return "AVAILABLE"


def _mid_long_setup_family(item: dict[str, Any], *, structure_status: str) -> str:
    if structure_status == "UNAVAILABLE":
        return "UNCLASSIFIED"
    status = str(item.get("structure_zone_status") or "").upper()
    primary = str(item.get("structure_zone_primary_state") or "").upper()
    reason = str(item.get("structure_zone_primary_reason") or "").upper()
    if "RETEST" in primary or "RETEST" in reason or "ROLE" in reason:
        return "RETEST"
    if "BREAKOUT" in primary or "RESISTANCE_BREAK" in primary:
        return "BREAKOUT_ATTEMPT"
    if "SUPPORT" in primary:
        return "SUPPORT_BOUNCE"
    if "NEUTRAL" in status or "MID" in primary or "RANGE" in primary:
        return "MID_RANGE"
    return "UNCLASSIFIED"


def _mid_long_breakout_state(item: dict[str, Any], *, setup_family: str) -> str:
    if setup_family != "BREAKOUT_ATTEMPT":
        return "NO_BREAKOUT_ATTEMPT"
    status = str(item.get("structure_zone_status") or "").upper()
    reason = str(item.get("structure_zone_primary_reason") or "").upper()
    if "ALIGNED" in status or "CLOSE" in reason or "CLOSED" in reason:
        return "CLOSE_ACCEPTED"
    return "WICK_ONLY"


def _mid_long_retest_quality(item: dict[str, Any], *, setup_family: str) -> str:
    if setup_family != "RETEST":
        return "NO_RETEST"
    status = str(item.get("structure_zone_status") or "").upper()
    reason = str(item.get("structure_zone_primary_reason") or "").upper()
    if "UNAVAILABLE" in status:
        return "UNAVAILABLE"
    if "FAILED" in reason or "BREAKDOWN" in reason or "CONFLICT" in status:
        return "RETEST_FAILED"
    if "ABOVE" in reason or "HOLD" in reason or "ALIGNED" in status:
        return "RETEST_HOLD_STRONG"
    return "RETEST_HOLD_IN_ZONE"


def _mid_long_entry_anchor_type(setup_family: str) -> str:
    if setup_family == "BREAKOUT_ATTEMPT":
        return "BREAKOUT_ZONE"
    if setup_family == "RETEST":
        return "RETEST_ZONE"
    if setup_family == "SUPPORT_BOUNCE":
        return "SUPPORT_ZONE"
    if setup_family == "MID_RANGE":
        return "RANGE_INTERIOR"
    return "UNAVAILABLE"


def _mid_long_entry_timing_bucket(setup_family: str, extension_bucket: str) -> str:
    if setup_family in {"UNCLASSIFIED", "MID_RANGE"} or extension_bucket == "UNKNOWN":
        return "UNAVAILABLE"
    if extension_bucket == "LOW_EXTENSION":
        return "EARLY"
    if extension_bucket in {"HIGH_EXTENSION", "EXTREME_EXTENSION"}:
        return "LATE_CHASE"
    return "NORMAL"


def _mid_long_quantile_bucket(value: Decimal | None, values: list[Decimal]) -> str:
    if value is None or len(values) < 4:
        return "UNKNOWN"
    q25 = _percentile_decimal_snapshot(values, Decimal("0.25"))
    q75 = _percentile_decimal_snapshot(values, Decimal("0.75"))
    q90 = _percentile_decimal_snapshot(values, Decimal("0.90"))
    if q25 is None or q75 is None or q90 is None:
        return "UNKNOWN"
    if value >= q90:
        return "EXTREME_EXTENSION"
    if value >= q75:
        return "HIGH_EXTENSION"
    if value <= q25:
        return "LOW_EXTENSION"
    return "MID_EXTENSION"


def _mid_long_flow_regime(item: dict[str, Any]) -> str:
    price_return = _mid_long_evidence_value(item, "price_return")
    oi_change = _mid_long_evidence_value(item, "oi_change_pct")
    taker_buy = _mid_long_evidence_value(item, "kline_taker_buy_ratio")
    if price_return is None or oi_change is None or taker_buy is None:
        return "UNKNOWN"
    buy_imbalance = taker_buy >= Decimal("0.53")
    if price_return > 0 and oi_change > 0 and buy_imbalance:
        return "PRICE_UP_OI_UP_BUY_IMBALANCE"
    if price_return > 0 and oi_change <= 0:
        return "PRICE_UP_OI_DOWN_SHORT_COVER"
    if price_return > 0 and oi_change > 0 and not buy_imbalance:
        return "PRICE_UP_OI_UP_WEAK_BUY"
    if price_return <= 0 and oi_change > 0:
        return "PRICE_NOT_UP_OI_UP_CROWDING_RISK"
    return "MIXED_OR_NEUTRAL"


def _mid_long_crowding_score(item: dict[str, Any]) -> int:
    score = 0
    funding = _mid_long_evidence_value(item, "funding_percentile_30d")
    oi_z = _mid_long_evidence_value(item, "oi_zscore")
    glsr = _mid_long_evidence_value(item, "global_long_short_ratio")
    top_position = _mid_long_evidence_value(item, "top_trader_position_ratio")
    top_account = _mid_long_evidence_value(item, "top_trader_account_ratio")
    if funding is not None and funding >= Decimal("90"):
        score += 2
    elif funding is not None and funding >= Decimal("75"):
        score += 1
    if oi_z is not None and oi_z >= Decimal("3"):
        score += 1
    if glsr is not None and glsr >= Decimal("1.30"):
        score += 1
    if top_position is not None and top_position >= Decimal("1.40"):
        score += 1
    if top_account is not None and top_account >= Decimal("1.30"):
        score += 1
    return score


def _mid_long_crowding_bucket(score: int) -> str:
    if score >= 5:
        return "EXTREME_CROWDING"
    if score >= 3:
        return "HIGH_CROWDING"
    if score >= 1:
        return "MODERATE_CROWDING"
    return "LOW_CROWDING"


def _mid_long_room_bucket(value: Decimal | None) -> str:
    if value is None:
        return "ROOM_UNAVAILABLE"
    if value <= Decimal("0.75"):
        return "LOW_ROOM"
    if value <= Decimal("1.50"):
        return "MODERATE_ROOM"
    return "HIGH_ROOM"


def _mid_long_cost_bucket(value: Decimal | None) -> str:
    if value is None:
        return "COST_UNKNOWN"
    if value <= Decimal("0.10"):
        return "LOW_COST"
    if value <= Decimal("0.20"):
        return "MODERATE_COST"
    if value <= Decimal("0.35"):
        return "HIGH_COST"
    return "EXTREME_COST"


def _mid_long_path_label_050(item: dict[str, Any]) -> str:
    label = str(item.get("path_label_050") or "")
    if label:
        return label
    return _mid_long_path_label_050_fallback(item)


def _mid_long_path_label_050_fallback(item: dict[str, Any]) -> str:
    status = str(item.get("result_status") or "")
    mfe = _decimal_or_zero_snapshot(item.get("mfe_r"))
    mae = _decimal_or_zero_snapshot(item.get("mae_r"))
    if status == "BOTH_HIT_SAME_CANDLE":
        return "SAME_BAR_AMBIGUOUS"
    if status == "SL_HIT":
        if mfe < Decimal("0.25"):
            return "INSTANT_SL"
        if mfe < Decimal("0.50"):
            return "SHALLOW_PROFIT_THEN_FAIL"
        return "PROFIT_THEN_FAIL_LEGACY"
    if status == "TP_HIT":
        if mae <= Decimal("-0.50"):
            return "PULLBACK_TP"
        return "CLEAN_CONTINUATION_TP"
    if status in {"OPEN", "STALE_FORWARD_DATA"}:
        return "OPEN_PATH"
    return "UNAVAILABLE"


def _mid_long_taxonomy_dimension_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    dimension_key: str,
    dimension_label: str,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        state = str(taxonomy_by_id[str(item.get("signal_id") or idx)].get(dimension_key) or "UNKNOWN")
        grouped[state].append(item)
    rows: list[dict[str, Any]] = []
    for state, state_items in grouped.items():
        row = _mid_long_perf_row(
            f"{dimension_key}:{state}",
            state,
            f"{dimension_key} == {state}",
            state_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "dimension_key": dimension_key,
                "dimension_label": dimension_label,
                "state": state,
                "path_mix": _mid_long_path_mix(state_items),
                "median_cost_r": _median_decimal_snapshot(
                    [
                        value
                        for item in state_items
                        if (value := _decimal_or_none_snapshot(item.get("realistic_cost_r_estimate"))) is not None
                    ]
                ),
                "median_room_to_resistance_atr": _median_decimal_snapshot(
                    [
                        value
                        for item in state_items
                        if (
                            value := _decimal_or_none_snapshot(
                                item.get("structure_zone_nearest_resistance_distance_atr")
                            )
                        )
                        is not None
                    ]
                ),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0),
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
        ),
        reverse=True,
    )
    return rows


def _mid_long_path_sequence_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[_mid_long_path_label_050(item)].append(item)
    rows: list[dict[str, Any]] = []
    for label, label_items in grouped.items():
        row = _mid_long_perf_row(
            f"PATH050:{label}",
            label,
            f"path_label_050 == {label}",
            label_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "path_label": label,
                "path_read": _mid_long_path_sequence_read(label),
                "median_wick_decay_r": _median_decimal_snapshot(
                    [
                        value
                        for item in label_items
                        if (value := _decimal_or_none_snapshot(item.get("wick_to_close_decay_r"))) is not None
                    ]
                ),
                "median_followthrough_1h_r": _median_decimal_snapshot(
                    [
                        value
                        for item in label_items
                        if (value := _decimal_or_none_snapshot(item.get("close_followthrough_1h_r"))) is not None
                    ]
                ),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _mid_long_path_priority(str(row.get("path_label") or "")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_taxonomy_path_cross_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    taxonomy_key: str,
    taxonomy_label: str,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
        key = f"{taxonomy.get(taxonomy_key) or 'UNKNOWN'} x {taxonomy.get('path_label_050') or 'UNKNOWN'}"
        grouped[key].append(item)
    rows: list[dict[str, Any]] = []
    for cell, cell_items in grouped.items():
        row = _mid_long_perf_row(
            f"{taxonomy_key}:PATH:{cell}",
            cell,
            f"{taxonomy_key} x path_label_050 == {cell}",
            cell_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "taxonomy_key": taxonomy_key,
                "taxonomy_label": taxonomy_label,
                "cell": cell,
                "is_readable": int(row.get("closed_count") or 0) >= min_sample,
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            bool(row.get("is_readable")),
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_draft_preview_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    scenarios: tuple[tuple[str, str, str], ...] = (
        (
            "DRAFT_HYGIENE",
            "Structure available + no weak flow + not mid-range + cost not extreme",
            "Obvious hygiene gates only; tests whether low-quality rows are dragging baseline.",
        ),
        (
            "DRAFT_BREAKOUT",
            "Hygiene + breakout close accepted + room not low",
            "Breakout-specific preview; not a production rule.",
        ),
        (
            "DRAFT_RETEST",
            "Hygiene + retest hold strong",
            "Retest-specific preview; likely small sample until detector is audited.",
        ),
        (
            "DRAFT_CROWDING_INTERACTION",
            "Hygiene + reject high crowding when paired with high extension, mixed flow, or low room",
            "Interaction preview; crowding is not rejected by itself.",
        ),
    )
    rows: list[dict[str, Any]] = []
    for scenario_id, label, note in scenarios:
        selected: list[dict[str, Any]] = []
        discarded: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
            passed = _mid_long_preview_pass(scenario_id, taxonomy)
            (selected if passed else discarded).append(item)
        row = _mid_long_perf_row(
            scenario_id,
            label,
            scenario_id,
            selected,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        discarded_perf = aggregate_signal_performance_items(discarded)
        row.update(
            {
                "preview_id": scenario_id,
                "preview_status": "DRAFT_PREVIEW",
                "discarded_count": len(discarded),
                "discarded_tp_count": discarded_perf["tp_count"],
                "discarded_sl_count": discarded_perf["sl_count"],
                "discarded_realistic_total_r_closed": discarded_perf["realistic_total_r_closed"],
                "retained_path_mix": _mid_long_path_mix(selected),
                "discarded_path_mix": _mid_long_path_mix(discarded),
                "preview_read": _mid_long_preview_read(row, discarded_perf),
                "note": note,
            }
        )
        rows.append(row)
    return rows


def _mid_long_preview_pass(scenario_id: str, taxonomy: dict[str, Any]) -> bool:
    hygiene = (
        taxonomy.get("structure_status") in {"AVAILABLE", "PARTIAL"}
        and taxonomy.get("flow_state_provisional") != "WEAK"
        and taxonomy.get("setup_family") != "MID_RANGE"
        and taxonomy.get("projected_cost_bucket") != "EXTREME_COST"
    )
    if scenario_id == "DRAFT_HYGIENE":
        return hygiene
    if scenario_id == "DRAFT_BREAKOUT":
        return (
            hygiene
            and taxonomy.get("setup_family") == "BREAKOUT_ATTEMPT"
            and taxonomy.get("breakout_state_pre_entry") == "CLOSE_ACCEPTED"
            and taxonomy.get("room_to_resistance_bucket") != "LOW_ROOM"
        )
    if scenario_id == "DRAFT_RETEST":
        return hygiene and taxonomy.get("setup_family") == "RETEST" and taxonomy.get("retest_quality_pre_entry") == "RETEST_HOLD_STRONG"
    if scenario_id == "DRAFT_CROWDING_INTERACTION":
        crowding = taxonomy.get("crowding_bucket") in {"HIGH_CROWDING", "EXTREME_CROWDING"}
        danger_pair = (
            taxonomy.get("extension_bucket") in {"HIGH_EXTENSION", "EXTREME_EXTENSION"}
            or taxonomy.get("flow_state_provisional") == "MIXED"
            or taxonomy.get("room_to_resistance_bucket") == "LOW_ROOM"
        )
        return hygiene and not (crowding and danger_pair)
    return False


def _mid_long_path_mix(items: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(_mid_long_path_label_050(item) for item in items))


def _mid_long_path_priority(label: str) -> int:
    priorities = {
        "CLOSE_PROFIT_THEN_FAIL": 90,
        "WICK_PROFIT_THEN_FAIL": 85,
        "SHALLOW_PROFIT_THEN_FAIL": 80,
        "INSTANT_SL": 75,
        "SAME_BAR_AMBIGUOUS": 70,
        "PULLBACK_TP": 60,
        "DRAWDOWN_FIRST_THEN_TP": 55,
        "WICK_PROFIT_THEN_TP": 50,
        "CLEAN_CONTINUATION_TP": 45,
    }
    return priorities.get(label, 10)


def _mid_long_path_sequence_read(label: str) -> str:
    reads = {
        "INSTANT_SL": "Entry definition/location problem candidate.",
        "SHALLOW_PROFIT_THEN_FAIL": "Tiny follow-through only; likely not enough acceptance.",
        "WICK_PROFIT_THEN_FAIL": "Profit existed intrabar but was not accepted by close.",
        "CLOSE_PROFIT_THEN_FAIL": "Acceptance existed; protection/dynamic exit deserves study.",
        "WICK_PROFIT_THEN_TP": "Wick-first winner; do not reject wick-only blindly.",
        "DRAWDOWN_FIRST_THEN_TP": "Winner needs stop tolerance before follow-through.",
        "CLEAN_CONTINUATION_TP": "Best continuation profile; study pre-entry features.",
        "PULLBACK_TP": "Winner retraces materially; aggressive protection may cut it.",
        "SAME_BAR_AMBIGUOUS": "OHLC ordering ambiguous; needs lower timeframe or conservative handling.",
    }
    return reads.get(label, "Path diagnostic row.")


def _mid_long_preview_read(row: dict[str, Any], discarded_perf: dict[str, Any]) -> str:
    selected_total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    discarded_total = _decimal_or_zero_snapshot(discarded_perf.get("realistic_total_r_closed"))
    sample = int(row.get("closed_count") or 0)
    if sample <= 0:
        return "No retained sample; detector/gate is not usable yet."
    if selected_total > 0 and avg_delta > 0 and discarded_total < 0:
        return "Promising research preview, but still needs time split and detector audit."
    if avg_delta > 0:
        return "Improves average R, but total R/sample/path mix must be checked."
    return "Not improving baseline yet; keep as diagnosis only."


def _mid_long_integrity_audit(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    path_rows = _mid_long_economic_rows_by_path(items, baseline=baseline, min_sample=min_sample)
    flow_rows = _mid_long_economic_rows_by_taxonomy(
        items,
        taxonomy_by_id=taxonomy_by_id,
        taxonomy_key="flow_state_provisional",
        label_prefix="Flow",
        baseline=baseline,
        min_sample=min_sample,
    )
    room_rows = _mid_long_economic_rows_by_taxonomy(
        items,
        taxonomy_by_id=taxonomy_by_id,
        taxonomy_key="room_to_resistance_bucket",
        label_prefix="Room",
        baseline=baseline,
        min_sample=min_sample,
    )
    cost_rows = _mid_long_economic_rows_by_taxonomy(
        items,
        taxonomy_by_id=taxonomy_by_id,
        taxonomy_key="projected_cost_bucket",
        label_prefix="Cost",
        baseline=baseline,
        min_sample=min_sample,
    )
    flags = _mid_long_integrity_flags(
        items,
        path_rows=path_rows,
        room_rows=room_rows,
        min_sample=min_sample,
    )
    return {
        "scope": "MID_LONG 1h taxonomy/path integrity audit",
        "method": (
            "Checks whether taxonomy/path labels are economically coherent before any damage/protection rule is studied."
        ),
        "path_economics_rows": path_rows,
        "flow_economics_rows": flow_rows,
        "room_quality_rows": room_rows,
        "cost_economics_rows": cost_rows,
        "anomaly_flags": flags,
        "read": _mid_long_integrity_read(flags),
    }


def _mid_long_damage_isolation(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    experiments: tuple[tuple[str, str, str], ...] = (
        ("DI-00", "Baseline V2", "No damage filter; control row."),
        ("DI-01", "Exclude MID_RANGE", "setup_family != MID_RANGE"),
        ("DI-02", "Exclude WEAK flow", "flow_state_provisional != WEAK"),
        ("DI-03", "Exclude MID_RANGE + WEAK", "DI-01 AND DI-02"),
        ("DI-04", "DI-03 + exclude extreme cost", "DI-03 AND projected_cost_bucket != EXTREME_COST"),
        (
            "DI-05",
            "DI-04 + conditional crowding reject",
            "DI-04 AND NOT(high/extreme crowding with high extension, mixed/weak flow, or low room)",
        ),
    )
    rows = [
        _mid_long_damage_experiment_row(
            experiment_id,
            label,
            expression,
            items,
            taxonomy_by_id=taxonomy_by_id,
            baseline=baseline,
            min_sample=min_sample,
        )
        for experiment_id, label, expression in experiments
    ]
    return {
        "scope": "MID_LONG 1h damage isolation, read-only",
        "method": (
            "Each DI row keeps a retained cohort and reports what damage/winners were removed. "
            "This is not a Signal Factory gate."
        ),
        "experiment_rows": rows,
        "mid_range_interactions": {
            "flow_state_provisional": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="setup_family",
                anchor_value="MID_RANGE",
                dimension_key="flow_state_provisional",
                dimension_label="MID_RANGE x flow",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "crowding_bucket": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="setup_family",
                anchor_value="MID_RANGE",
                dimension_key="crowding_bucket",
                dimension_label="MID_RANGE x crowding",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "extension_bucket": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="setup_family",
                anchor_value="MID_RANGE",
                dimension_key="extension_bucket",
                dimension_label="MID_RANGE x extension",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "room_to_resistance_bucket": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="setup_family",
                anchor_value="MID_RANGE",
                dimension_key="room_to_resistance_bucket",
                dimension_label="MID_RANGE x room",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "path_label_050": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="setup_family",
                anchor_value="MID_RANGE",
                dimension_key="path_label_050",
                dimension_label="MID_RANGE x path",
                baseline=baseline,
                min_sample=min_sample,
            ),
        },
        "confirmed_flow_interactions": {
            "setup_family": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="flow_state_provisional",
                anchor_value="CONFIRMED",
                dimension_key="setup_family",
                dimension_label="CONFIRMED flow x setup",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "room_to_resistance_bucket": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="flow_state_provisional",
                anchor_value="CONFIRMED",
                dimension_key="room_to_resistance_bucket",
                dimension_label="CONFIRMED flow x room",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "crowding_bucket": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="flow_state_provisional",
                anchor_value="CONFIRMED",
                dimension_key="crowding_bucket",
                dimension_label="CONFIRMED flow x crowding",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "extension_bucket": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="flow_state_provisional",
                anchor_value="CONFIRMED",
                dimension_key="extension_bucket",
                dimension_label="CONFIRMED flow x extension",
                baseline=baseline,
                min_sample=min_sample,
            ),
            "projected_cost_bucket": _mid_long_subset_dimension_rows(
                items,
                taxonomy_by_id=taxonomy_by_id,
                anchor_key="flow_state_provisional",
                anchor_value="CONFIRMED",
                dimension_key="projected_cost_bucket",
                dimension_label="CONFIRMED flow x cost",
                baseline=baseline,
                min_sample=min_sample,
            ),
        },
        "guardrails": [
            "DI rows are not production hard rejects.",
            "A damage filter must be validated chronologically before becoming any shadow rule.",
            "Protection/BE study must be run after damage-cleaned cohorts are understood.",
        ],
        "read": _mid_long_damage_isolation_read(rows),
    }


def _mid_long_family_damage_hurdle_study(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    reset_by_id = {
        str(item.get("signal_id") or idx): _mid_long_reset_state(
            item,
            taxonomy_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    state_by_id = {
        str(item.get("signal_id") or idx): _mid_long_first_hour_state(
            item,
            reset_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    labels_by_id = {
        str(item.get("signal_id") or idx): _mid_long_damage_hurdle_label(
            item,
            first_hour_state=state_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    score_by_id = {
        str(item.get("signal_id") or idx): _mid_long_damage_hurdle_score_state(
            item,
            reset=reset_by_id[str(item.get("signal_id") or idx)],
            taxonomy=taxonomy_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    baseline_hurdle = _mid_long_hurdle_perf_summary(
        items,
        labels_by_id=labels_by_id,
        baseline=None,
    )
    family_rows = _mid_long_hurdle_group_rows(
        items,
        group_key="primary_family",
        group_label="Primary family",
        group_lookup=lambda idx, item: str(reset_by_id[str(item.get("signal_id") or idx)]["primary_family"]),
        labels_by_id=labels_by_id,
        baseline=baseline,
        baseline_hurdle=baseline_hurdle,
        min_sample=min_sample,
    )
    damage_label_rows = _mid_long_hurdle_group_rows(
        items,
        group_key="damage_label",
        group_label="Damage label",
        group_lookup=lambda idx, item: str(labels_by_id[str(item.get("signal_id") or idx)]),
        labels_by_id=labels_by_id,
        baseline=baseline,
        baseline_hurdle=baseline_hurdle,
        min_sample=min_sample,
    )
    predictor_group_rows = {
        "zone_freshness": _mid_long_hurdle_group_rows(
            items,
            group_key="zone_freshness",
            group_label="Zone freshness",
            group_lookup=lambda idx, item: str(score_by_id[str(item.get("signal_id") or idx)]["components"]["zone_freshness"]),
            labels_by_id=labels_by_id,
            baseline=baseline,
            baseline_hurdle=baseline_hurdle,
            min_sample=min_sample,
        ),
        "entry_geometry": _mid_long_hurdle_group_rows(
            items,
            group_key="entry_geometry",
            group_label="Entry geometry",
            group_lookup=lambda idx, item: str(score_by_id[str(item.get("signal_id") or idx)]["components"]["entry_geometry"]),
            labels_by_id=labels_by_id,
            baseline=baseline,
            baseline_hurdle=baseline_hurdle,
            min_sample=min_sample,
        ),
        "spatial_room": _mid_long_hurdle_group_rows(
            items,
            group_key="spatial_room",
            group_label="Spatial room",
            group_lookup=lambda idx, item: str(score_by_id[str(item.get("signal_id") or idx)]["components"]["spatial_room"]),
            labels_by_id=labels_by_id,
            baseline=baseline,
            baseline_hurdle=baseline_hurdle,
            min_sample=min_sample,
        ),
        "flow_crowding": _mid_long_hurdle_group_rows(
            items,
            group_key="flow_crowding",
            group_label="Flow/crowding",
            group_lookup=lambda idx, item: str(score_by_id[str(item.get("signal_id") or idx)]["components"]["flow_crowding"]),
            labels_by_id=labels_by_id,
            baseline=baseline,
            baseline_hurdle=baseline_hurdle,
            min_sample=min_sample,
        ),
        "tradability": _mid_long_hurdle_group_rows(
            items,
            group_key="tradability",
            group_label="Tradability",
            group_lookup=lambda idx, item: str(score_by_id[str(item.get("signal_id") or idx)]["components"]["tradability"]),
            labels_by_id=labels_by_id,
            baseline=baseline,
            baseline_hurdle=baseline_hurdle,
            min_sample=min_sample,
        ),
    }
    score_bucket_rows = _mid_long_hurdle_score_bucket_rows(
        items,
        score_by_id=score_by_id,
        labels_by_id=labels_by_id,
        baseline=baseline,
        baseline_hurdle=baseline_hurdle,
        min_sample=min_sample,
    )
    threshold_rows = _mid_long_hurdle_threshold_rows(
        items,
        score_by_id=score_by_id,
        labels_by_id=labels_by_id,
        baseline=baseline,
        baseline_hurdle=baseline_hurdle,
        min_sample=min_sample,
    )
    best_threshold = _mid_long_hurdle_best_threshold(threshold_rows, min_sample=min_sample)
    block_rows = _mid_long_hurdle_chronological_block_rows(
        items,
        score_by_id=score_by_id,
        labels_by_id=labels_by_id,
        threshold=int(best_threshold.get("threshold_score") or 0) if best_threshold else 0,
        min_sample=min_sample,
    )
    return {
        "scope": "MID_LONG 1h Family-Conditioned Damage Hurdle Study",
        "method": (
            "Read-only diagnostic: split MID_LONG 1h by structure family, label early damage from observed path, "
            "then compare damage share and realistic R across pre-entry predictor groups."
        ),
        "model_version": "MID_LONG_DAMAGE_HURDLE_DIAGNOSTIC_V1",
        "min_sample": min_sample,
        "target_policy": {
            "primary_target": "Y_EARLY_DAMAGE",
            "primary_definition": (
                "1 when first-hour response is price-reversed/structure-failed or path is instant/shallow SL. "
                "This is an outcome label for research, not an entry predictor."
            ),
            "secondary_target": "realistic_realized_r",
            "auxiliary_target": "Y_CONFIRM from first-hour response; kept only as diagnostic, not objective final.",
        },
        "predictor_groups": [
            "primary family",
            "zone freshness",
            "entry geometry",
            "spatial room",
            "flow/crowding",
            "tradability",
        ],
        "baseline": baseline_hurdle,
        "family_rows": family_rows,
        "damage_label_rows": damage_label_rows,
        "predictor_group_rows": predictor_group_rows,
        "score_bucket_rows": score_bucket_rows,
        "threshold_rows": threshold_rows,
        "chronological_block_rows": block_rows,
        "summary": _mid_long_hurdle_summary(
            baseline_hurdle=baseline_hurdle,
            threshold_rows=threshold_rows,
            block_rows=block_rows,
            min_sample=min_sample,
        ),
        "guardrails": [
            "Hurdle score is a diagnostic rank, not a live Signal Factory score.",
            "Y_EARLY_DAMAGE uses post-entry outcome/path only as a label; it must not be used as a pre-entry feature.",
            "Threshold rows are coverage trade-offs for research, not gates.",
            "Any V2.1 shadow proposal must survive chronological validation and concentration checks first.",
        ],
    }


def _mid_long_damage_hurdle_label(item: dict[str, Any], *, first_hour_state: str) -> str:
    path = _mid_long_path_label_050(item)
    status = str(item.get("result_status") or "")
    if first_hour_state in {"FIRST_HOUR_PRICE_REVERSED", "FIRST_HOUR_STRUCTURE_FAILED"}:
        return "EARLY_DAMAGE"
    if path in {"INSTANT_SL", "SHALLOW_PROFIT_THEN_FAIL"}:
        return "EARLY_DAMAGE"
    if status == "TP_HIT":
        return "SURVIVED_POSITIVE_PAYOFF"
    if status == "SL_HIT":
        return "SURVIVED_NEGATIVE_PAYOFF"
    return "DAMAGE_UNKNOWN"


def _mid_long_dual_track_pattern_discovery(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    reset_by_id = {
        str(item.get("signal_id") or idx): _mid_long_reset_state(
            item,
            taxonomy_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    first_hour_by_id = {
        str(item.get("signal_id") or idx): _mid_long_first_hour_state(
            item,
            reset_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    labels_by_id = {
        str(item.get("signal_id") or idx): _mid_long_damage_hurdle_label(
            item,
            first_hour_state=first_hour_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    score_by_id = {
        str(item.get("signal_id") or idx): _mid_long_damage_hurdle_score_state(
            item,
            reset=reset_by_id[str(item.get("signal_id") or idx)],
            taxonomy=taxonomy_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    ordered = sorted(items, key=_mid_long_signal_sort_key)
    split_index = max(1, min(len(ordered), int(Decimal(len(ordered)) * Decimal("0.70")))) if ordered else 0
    train_items = ordered[:split_index]
    validation_items = ordered[split_index:]
    if len(validation_items) < min_sample and len(ordered) >= min_sample * 2:
        split_index = max(min_sample, len(ordered) - min_sample)
        train_items = ordered[:split_index]
        validation_items = ordered[split_index:]

    predicate_specs = _mid_long_dual_predicate_specs()
    predicate_rows = _mid_long_dual_predicate_rows(
        train_items,
        validation_items,
        predicate_specs=predicate_specs,
        taxonomy_by_id=taxonomy_by_id,
        reset_by_id=reset_by_id,
        score_by_id=score_by_id,
        labels_by_id=labels_by_id,
        min_sample=min_sample,
    )
    rule_rows = _mid_long_dual_rule_rows(
        train_items,
        validation_items,
        predicate_rows=predicate_rows,
        predicate_specs=predicate_specs,
        taxonomy_by_id=taxonomy_by_id,
        reset_by_id=reset_by_id,
        score_by_id=score_by_id,
        labels_by_id=labels_by_id,
        min_sample=min_sample,
    )
    group_rows = _mid_long_dual_group_rows(predicate_rows, rule_rows)
    cluster_rows = _mid_long_unclassified_archetype_rows(
        items,
        taxonomy_by_id=taxonomy_by_id,
        reset_by_id=reset_by_id,
        score_by_id=score_by_id,
        labels_by_id=labels_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    summary = _mid_long_dual_discovery_summary(
        predicate_rows=predicate_rows,
        rule_rows=rule_rows,
        group_rows=group_rows,
        cluster_rows=cluster_rows,
        min_sample=min_sample,
    )
    return {
        "scope": "MID_LONG 1h Dual-Track Pattern Discovery Lab",
        "method": (
            "Track A asks whether pre-entry fields can separate early damage from viable continuation using "
            "chronological train/validation predicate discovery. Track B splits UNCLASSIFIED_MID_LONG into "
            "pre-entry archetypes before looking at outcome."
        ),
        "model_version": "MID_LONG_DUAL_TRACK_DISCOVERY_V1_LOCAL_SAFE",
        "execution_policy": {
            "runtime": "local-safe lightweight diagnostics",
            "dependency_policy": "no new sklearn/lightgbm dependency; deterministic predicates and archetypes only",
            "production_rule_change": False,
        },
        "target_policy": {
            "primary_target": "EARLY_DAMAGE",
            "primary_definition": (
                "Outcome label for research only: first-hour reversed/structure-failed, instant SL, or shallow-profit fail."
            ),
            "economic_metric": "realistic_R on validation and selected cohorts",
            "forbidden_inputs": [
                "result_status",
                "realized R",
                "MFE/MAE",
                "first-hour state as a predictor",
                "future candles",
            ],
        },
        "chronological_split": {
            "train_count": len(train_items),
            "validation_count": len(validation_items),
            "train_first": train_items[0].get("signal_timestamp") if train_items else None,
            "train_last": train_items[-1].get("signal_timestamp") if train_items else None,
            "validation_first": validation_items[0].get("signal_timestamp") if validation_items else None,
            "validation_last": validation_items[-1].get("signal_timestamp") if validation_items else None,
        },
        "track_a_supervised_discrimination": {
            "baseline_train": _mid_long_dual_metrics(train_items, baseline_items=train_items, labels_by_id=labels_by_id),
            "baseline_validation": _mid_long_dual_metrics(
                validation_items,
                baseline_items=validation_items,
                labels_by_id=labels_by_id,
            ),
            "predicate_rows": predicate_rows[:24],
            "rule_rows": rule_rows[:20],
            "feature_group_rows": group_rows,
        },
        "track_b_unclassified_archetypes": {
            "target_family": "UNCLASSIFIED_MID_LONG",
            "archetype_rows": cluster_rows,
        },
        "summary": summary,
        "guardrails": [
            "This lab is read-only and must not change Signal Factory rules.",
            "Track A uses chronological validation; train-only winners are not candidates.",
            "Track B assigns unclassified archetypes without outcome, then reads TP/SL/R afterward.",
            "Optuna/threshold optimization remains blocked until a stable pattern or archetype survives validation.",
        ],
    }


def _mid_long_dual_predicate_specs() -> list[dict[str, Any]]:
    return [
        {
            "id": "FAMILY_BREAKOUT",
            "label": "Breakout continuation family",
            "group": "structure",
            "expression": "primary_family == BREAKOUT_CONTINUATION_LONG",
            "predicate": lambda _idx, _item, ctx: ctx["reset"].get("primary_family") == "BREAKOUT_CONTINUATION_LONG",
        },
        {
            "id": "FAMILY_SUPPORT_RETEST",
            "label": "Support retest family",
            "group": "structure",
            "expression": "primary_family == SUPPORT_RETEST_LONG",
            "predicate": lambda _idx, _item, ctx: ctx["reset"].get("primary_family") == "SUPPORT_RETEST_LONG",
        },
        {
            "id": "NOT_UNCLASSIFIED",
            "label": "Structure classified",
            "group": "structure",
            "expression": "primary_family != UNCLASSIFIED_MID_LONG",
            "predicate": lambda _idx, _item, ctx: ctx["reset"].get("primary_family") != "UNCLASSIFIED_MID_LONG",
        },
        {
            "id": "ZONE_REPEATED",
            "label": "Repeated zone",
            "group": "structure",
            "expression": "zone_touch_count >= 2",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "zone_touch_count") is not None
            and _mid_long_first_decimal(item, "zone_touch_count") >= Decimal("2"),
        },
        {
            "id": "ZONE_NOT_OLD",
            "label": "Zone age <= 48 bars",
            "group": "structure",
            "expression": "zone_age_bars <= 48",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "zone_age_bars") is not None
            and _mid_long_first_decimal(item, "zone_age_bars") <= Decimal("48"),
        },
        {
            "id": "ROOM_GE_100",
            "label": "Room to resistance >= 1.00 ATR",
            "group": "geometry",
            "expression": "room_to_next_resistance_atr >= 1.00",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(
                item,
                "room_to_next_resistance_atr",
                "structure_zone_nearest_resistance_distance_atr",
            )
            is not None
            and _mid_long_first_decimal(
                item,
                "room_to_next_resistance_atr",
                "structure_zone_nearest_resistance_distance_atr",
            )
            >= Decimal("1.00"),
        },
        {
            "id": "ROOM_GE_150",
            "label": "Room to resistance >= 1.50 ATR",
            "group": "geometry",
            "expression": "room_to_next_resistance_atr >= 1.50",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(
                item,
                "room_to_next_resistance_atr",
                "structure_zone_nearest_resistance_distance_atr",
            )
            is not None
            and _mid_long_first_decimal(
                item,
                "room_to_next_resistance_atr",
                "structure_zone_nearest_resistance_distance_atr",
            )
            >= Decimal("1.50"),
        },
        {
            "id": "ENTRY_DISTANCE_LE_100",
            "label": "Entry distance <= 1.00 ATR",
            "group": "geometry",
            "expression": "entry_distance_from_zone_atr <= 1.00",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "entry_distance_from_zone_atr") is not None
            and _mid_long_first_decimal(item, "entry_distance_from_zone_atr") <= Decimal("1.00"),
        },
        {
            "id": "BODY_ACCEPTED",
            "label": "Body above zone >= 0.35",
            "group": "geometry",
            "expression": "body_above_zone_ratio >= 0.35",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "body_above_zone_ratio") is not None
            and _mid_long_first_decimal(item, "body_above_zone_ratio") >= Decimal("0.35"),
        },
        {
            "id": "PENETRATION_GE_010",
            "label": "Close penetration >= 0.10 ATR",
            "group": "geometry",
            "expression": "close_penetration_atr >= 0.10",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "close_penetration_atr") is not None
            and _mid_long_first_decimal(item, "close_penetration_atr") >= Decimal("0.10"),
        },
        {
            "id": "WICK_BODY_LE_025",
            "label": "Upper wick/body <= 0.25",
            "group": "geometry",
            "expression": "upper_wick_to_body_ratio <= 0.25",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "upper_wick_to_body_ratio") is not None
            and _mid_long_first_decimal(item, "upper_wick_to_body_ratio") <= Decimal("0.25"),
        },
        {
            "id": "ATR_EXTENSION_LE_150",
            "label": "ATR extension <= 1.50",
            "group": "extension",
            "expression": "atr_extension_normalized <= 1.50",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "atr_extension_normalized") is not None
            and _mid_long_first_decimal(item, "atr_extension_normalized") <= Decimal("1.50"),
        },
        {
            "id": "RANGE_ATR_LE_150",
            "label": "Range/ATR <= 1.50",
            "group": "extension",
            "expression": "range_ratio_vs_atr <= 1.50",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "range_ratio_vs_atr") is not None
            and _mid_long_first_decimal(item, "range_ratio_vs_atr") <= Decimal("1.50"),
        },
        {
            "id": "VOLUME_GE_100",
            "label": "Volume >= 30-candle avg",
            "group": "flow",
            "expression": "volume_ratio_vs_lookback >= 1.00",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "volume_ratio_vs_lookback") is not None
            and _mid_long_first_decimal(item, "volume_ratio_vs_lookback") >= Decimal("1.00"),
        },
        {
            "id": "TAKER_BUY_GE_052",
            "label": "Taker buy >= 52%",
            "group": "flow",
            "expression": "kline_taker_buy_ratio >= 52",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "kline_taker_buy_ratio") is not None
            and _mid_long_first_decimal(item, "kline_taker_buy_ratio") >= Decimal("52"),
        },
        {
            "id": "OI_Z_GE_100",
            "label": "OI z-score >= 1.00",
            "group": "flow_oi",
            "expression": "oi_zscore >= 1.00",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "oi_zscore") is not None
            and _mid_long_first_decimal(item, "oi_zscore") >= Decimal("1.00"),
        },
        {
            "id": "OI_CHANGE_010_TO_100",
            "label": "OI change 0.10% to 1.00%",
            "group": "flow_oi",
            "expression": "0.10 <= oi_change_pct <= 1.00",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "oi_change_pct") is not None
            and Decimal("0.10") <= _mid_long_first_decimal(item, "oi_change_pct") <= Decimal("1.00"),
        },
        {
            "id": "FLOW_NOT_WEAK",
            "label": "Flow not weak",
            "group": "flow_oi",
            "expression": "flow_state_provisional != WEAK",
            "predicate": lambda _idx, _item, ctx: ctx["taxonomy"].get("flow_state_provisional") != "WEAK",
        },
        {
            "id": "NOT_CROWDED",
            "label": "Not high/ extreme crowded",
            "group": "crowding",
            "expression": "crowding_bucket not high/extreme",
            "predicate": lambda _idx, _item, ctx: ctx["taxonomy"].get("crowding_bucket") not in {"HIGH_CROWDING", "EXTREME_CROWDING"},
        },
        {
            "id": "FUNDING_PCTL_LE_80",
            "label": "Funding percentile <= 80",
            "group": "crowding",
            "expression": "funding_percentile_30d <= 80",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "funding_percentile_30d") is not None
            and _mid_long_first_decimal(item, "funding_percentile_30d") <= Decimal("80"),
        },
        {
            "id": "COST_LE_020R",
            "label": "Projected cost <= 0.20R",
            "group": "tradability",
            "expression": "realistic_cost_r_estimate <= 0.20R",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "realistic_cost_r_estimate") is not None
            and _mid_long_first_decimal(item, "realistic_cost_r_estimate") <= Decimal("0.20"),
        },
        {
            "id": "SPREAD_LE_003",
            "label": "Futures spread <= 0.03%",
            "group": "tradability",
            "expression": "futures_spread_pct <= 0.03",
            "predicate": lambda _idx, item, _ctx: _mid_long_first_decimal(item, "futures_spread_pct") is not None
            and _mid_long_first_decimal(item, "futures_spread_pct") <= Decimal("0.03"),
        },
    ]


def _mid_long_dual_predicate_rows(
    train_items: list[dict[str, Any]],
    validation_items: list[dict[str, Any]],
    *,
    predicate_specs: list[dict[str, Any]],
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
    score_by_id: dict[str, dict[str, Any]],
    labels_by_id: dict[str, str],
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in predicate_specs:
        train_selected = _mid_long_dual_select(
            train_items,
            predicate=spec["predicate"],
            taxonomy_by_id=taxonomy_by_id,
            reset_by_id=reset_by_id,
            score_by_id=score_by_id,
        )
        validation_selected = _mid_long_dual_select(
            validation_items,
            predicate=spec["predicate"],
            taxonomy_by_id=taxonomy_by_id,
            reset_by_id=reset_by_id,
            score_by_id=score_by_id,
        )
        rows.append(
            _mid_long_dual_candidate_row(
                spec["id"],
                spec["label"],
                spec["group"],
                spec["expression"],
                train_selected,
                validation_selected,
                train_items=train_items,
                validation_items=validation_items,
                labels_by_id=labels_by_id,
                min_sample=min_sample,
                row_type="PREDICATE",
            )
        )
    rows.sort(key=_mid_long_dual_row_sort_key, reverse=True)
    return rows


def _mid_long_dual_rule_rows(
    train_items: list[dict[str, Any]],
    validation_items: list[dict[str, Any]],
    *,
    predicate_rows: list[dict[str, Any]],
    predicate_specs: list[dict[str, Any]],
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
    score_by_id: dict[str, dict[str, Any]],
    labels_by_id: dict[str, str],
    min_sample: int,
) -> list[dict[str, Any]]:
    specs_by_id = {str(spec["id"]): spec for spec in predicate_specs}
    candidate_ids = [
        str(row["rule_id"])
        for row in predicate_rows
        if int(row.get("validation_selected_count") or 0) >= max(10, min_sample // 2)
    ][:12]
    rows: list[dict[str, Any]] = []
    for left_index, left_id in enumerate(candidate_ids):
        for right_id in candidate_ids[left_index + 1 :]:
            left = specs_by_id[left_id]
            right = specs_by_id[right_id]
            if left["group"] == right["group"] and left["id"] not in {"NOT_UNCLASSIFIED", "FAMILY_BREAKOUT", "FAMILY_SUPPORT_RETEST"}:
                continue

            def _pair_predicate(idx: int, item: dict[str, Any], ctx: dict[str, Any], left=left, right=right) -> bool:
                return bool(left["predicate"](idx, item, ctx) and right["predicate"](idx, item, ctx))

            train_selected = _mid_long_dual_select(
                train_items,
                predicate=_pair_predicate,
                taxonomy_by_id=taxonomy_by_id,
                reset_by_id=reset_by_id,
                score_by_id=score_by_id,
            )
            validation_selected = _mid_long_dual_select(
                validation_items,
                predicate=_pair_predicate,
                taxonomy_by_id=taxonomy_by_id,
                reset_by_id=reset_by_id,
                score_by_id=score_by_id,
            )
            rows.append(
                _mid_long_dual_candidate_row(
                    f"{left_id}__AND__{right_id}",
                    f"{left['label']} + {right['label']}",
                    f"{left['group']}+{right['group']}",
                    f"{left['expression']} AND {right['expression']}",
                    train_selected,
                    validation_selected,
                    train_items=train_items,
                    validation_items=validation_items,
                    labels_by_id=labels_by_id,
                    min_sample=min_sample,
                    row_type="TWO_PREDICATE_RULE",
                )
            )
    rows.sort(key=_mid_long_dual_row_sort_key, reverse=True)
    return rows[:30]


def _mid_long_dual_select(
    items: list[dict[str, Any]],
    *,
    predicate: Callable[[int, dict[str, Any], dict[str, Any]], bool],
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
    score_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        key = str(item.get("signal_id") or idx)
        ctx = {
            "taxonomy": taxonomy_by_id.get(key, {}),
            "reset": reset_by_id.get(key, {}),
            "score": score_by_id.get(key, {}),
        }
        try:
            if predicate(idx, item, ctx):
                selected.append(item)
        except Exception:
            continue
    return selected


def _mid_long_dual_candidate_row(
    rule_id: str,
    label: str,
    feature_group: str,
    expression: str,
    train_selected: list[dict[str, Any]],
    validation_selected: list[dict[str, Any]],
    *,
    train_items: list[dict[str, Any]],
    validation_items: list[dict[str, Any]],
    labels_by_id: dict[str, str],
    min_sample: int,
    row_type: str,
) -> dict[str, Any]:
    train_baseline = _mid_long_dual_metrics(train_items, baseline_items=train_items, labels_by_id=labels_by_id)
    validation_baseline = _mid_long_dual_metrics(
        validation_items,
        baseline_items=validation_items,
        labels_by_id=labels_by_id,
    )
    train = _mid_long_dual_metrics(train_selected, baseline_items=train_items, labels_by_id=labels_by_id)
    validation = _mid_long_dual_metrics(
        validation_selected,
        baseline_items=validation_items,
        labels_by_id=labels_by_id,
    )
    row = {
        "row_type": row_type,
        "rule_id": rule_id,
        "label": label,
        "feature_group": feature_group,
        "expression": expression,
        "train_selected_count": len(train_selected),
        "validation_selected_count": len(validation_selected),
        "train_coverage_pct": _pct_decimal(len(train_selected), len(train_items)),
        "validation_coverage_pct": _pct_decimal(len(validation_selected), len(validation_items)),
        "train": train,
        "validation": validation,
        "train_baseline": train_baseline,
        "validation_baseline": validation_baseline,
    }
    row["read"] = _mid_long_dual_candidate_read(row, min_sample=min_sample)
    return row


def _mid_long_dual_metrics(
    items: list[dict[str, Any]],
    *,
    baseline_items: list[dict[str, Any]],
    labels_by_id: dict[str, str],
) -> dict[str, Any]:
    metrics = _mid_long_hurdle_perf_summary(
        items,
        labels_by_id=labels_by_id,
        baseline=_mid_long_hurdle_perf_summary(baseline_items, labels_by_id=labels_by_id, baseline=None),
    )
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    top_symbol, top_symbol_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    metrics.update(
        {
            "sample_count": len(items),
            "top_symbol": top_symbol,
            "top_symbol_count": top_symbol_count,
            "top_symbol_share_pct": _pct_decimal(top_symbol_count, len(items)) if items else None,
        }
    )
    return metrics


def _mid_long_dual_candidate_read(row: dict[str, Any], *, min_sample: int) -> str:
    train = row.get("train") or {}
    validation = row.get("validation") or {}
    validation_count = int(row.get("validation_selected_count") or 0)
    train_count = int(row.get("train_selected_count") or 0)
    validation_avg_delta = _decimal_or_zero_snapshot(validation.get("realistic_avg_r_delta_vs_baseline"))
    validation_total = _decimal_or_zero_snapshot(validation.get("realistic_total_r_closed"))
    validation_damage_delta = _decimal_or_zero_snapshot(validation.get("early_damage_share_delta_vs_baseline"))
    train_avg_delta = _decimal_or_zero_snapshot(train.get("realistic_avg_r_delta_vs_baseline"))
    top_share = _decimal_or_zero_snapshot(validation.get("top_symbol_share_pct"))
    if train_count < min_sample:
        return "TRAIN_SAMPLE_TOO_SMALL"
    if validation_count < min_sample:
        return "VALIDATION_SAMPLE_TOO_SMALL"
    if train_count >= min_sample and train_avg_delta > 0 and validation_avg_delta <= 0:
        return "TRAIN_ONLY_OVERFIT"
    if validation_total > 0 and validation_avg_delta >= Decimal("0.10") and validation_damage_delta < 0 and top_share <= Decimal("35"):
        return "PROMISING_PATTERN"
    if validation_avg_delta > 0 and validation_damage_delta <= 0:
        return "WEAK_VALIDATION_LIFT"
    if validation_damage_delta > 0 and validation_avg_delta < 0:
        return "DAMAGE_CLUSTER"
    return "NO_STABLE_LIFT"


def _mid_long_dual_row_sort_key(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, int]:
    validation = row.get("validation") or {}
    return (
        _mid_long_dual_read_rank(str(row.get("read") or "")),
        _decimal_or_zero_snapshot(validation.get("realistic_avg_r_delta_vs_baseline")),
        _decimal_or_zero_snapshot(validation.get("realistic_total_r_closed")),
        int(row.get("validation_selected_count") or 0),
    )


def _mid_long_dual_read_rank(read: str) -> int:
    return {
        "PROMISING_PATTERN": 5,
        "WEAK_VALIDATION_LIFT": 4,
        "DAMAGE_CLUSTER": 3,
        "NO_STABLE_LIFT": 2,
        "TRAIN_ONLY_OVERFIT": 1,
        "TRAIN_SAMPLE_TOO_SMALL": 0,
        "VALIDATION_SAMPLE_TOO_SMALL": 0,
    }.get(read, 0)


def _mid_long_dual_group_rows(predicate_rows: list[dict[str, Any]], rule_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in [*predicate_rows, *rule_rows]:
        grouped[str(row.get("feature_group") or "unknown")].append(row)
    rows: list[dict[str, Any]] = []
    for group, group_items in grouped.items():
        sorted_items = sorted(group_items, key=_mid_long_dual_row_sort_key, reverse=True)
        best = sorted_items[0]
        rows.append(
            {
                "feature_group": group,
                "candidate_count": len(group_items),
                "promising_count": sum(1 for item in group_items if item.get("read") == "PROMISING_PATTERN"),
                "weak_lift_count": sum(1 for item in group_items if item.get("read") == "WEAK_VALIDATION_LIFT"),
                "overfit_count": sum(1 for item in group_items if item.get("read") == "TRAIN_ONLY_OVERFIT"),
                "best_rule_id": best.get("rule_id"),
                "best_label": best.get("label"),
                "best_read": best.get("read"),
                "best_validation_count": best.get("validation_selected_count"),
                "best_validation_avg_delta_r": (best.get("validation") or {}).get("realistic_avg_r_delta_vs_baseline"),
                "best_validation_total_r": (best.get("validation") or {}).get("realistic_total_r_closed"),
                "best_validation_damage_delta_pct": (best.get("validation") or {}).get("early_damage_share_delta_vs_baseline"),
            }
        )
    rows.sort(
        key=lambda row: (
            int(row.get("promising_count") or 0),
            int(row.get("weak_lift_count") or 0),
            _decimal_or_zero_snapshot(row.get("best_validation_avg_delta_r")),
        ),
        reverse=True,
    )
    return rows


def _mid_long_unclassified_archetype_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
    score_by_id: dict[str, dict[str, Any]],
    labels_by_id: dict[str, str],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        key = str(item.get("signal_id") or idx)
        reset = reset_by_id.get(key, {})
        if reset.get("primary_family") != "UNCLASSIFIED_MID_LONG":
            continue
        archetype = _mid_long_unclassified_archetype(
            item,
            taxonomy=taxonomy_by_id.get(key, {}),
            score_state=score_by_id.get(key, {}),
        )
        grouped[archetype].append(item)
    rows: list[dict[str, Any]] = []
    baseline_hurdle = _mid_long_hurdle_perf_summary(items, labels_by_id=labels_by_id, baseline=None)
    for archetype, archetype_items in grouped.items():
        row = _mid_long_perf_row(
            f"UNCLASSIFIED_ARCHETYPE:{archetype}",
            archetype,
            _mid_long_unclassified_archetype_definition(archetype),
            archetype_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            _mid_long_hurdle_perf_summary(
                archetype_items,
                labels_by_id=labels_by_id,
                baseline=baseline_hurdle,
            )
        )
        row.update(
            {
                "archetype": archetype,
                "definition": _mid_long_unclassified_archetype_definition(archetype),
                "read": _mid_long_unclassified_archetype_read(row, min_sample=min_sample),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0) >= min_sample,
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed")),
            -_decimal_or_zero_snapshot(row.get("early_damage_share_pct")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_unclassified_archetype(
    item: dict[str, Any],
    *,
    taxonomy: dict[str, Any],
    score_state: dict[str, Any],
) -> str:
    components = score_state.get("components") or {}
    if components.get("spatial_room") == "LOW_ROOM":
        return "UNCLASSIFIED_LOW_ROOM"
    if components.get("entry_geometry") == "CHASE_DISTANCE" or taxonomy.get("entry_timing_bucket") == "LATE_CHASE":
        return "UNCLASSIFIED_CHASE_EXTENSION"
    if components.get("flow_crowding") in {"WEAK_FLOW_NOT_CROWDED", "CROWDED_LONG"}:
        return "UNCLASSIFIED_WEAK_FLOW_OR_CROWDING"
    if components.get("tradability") in {"HIGH_COST", "EXTREME_COST"}:
        return "UNCLASSIFIED_COST_RISK"
    if components.get("zone_freshness") == "ZONE_UNKNOWN" or str(item.get("structure_zone_status") or "").upper() in {"", "UNAVAILABLE"}:
        return "UNCLASSIFIED_STRUCTURE_MISSING"
    return "UNCLASSIFIED_NEUTRAL_STRUCTURE"


def _mid_long_unclassified_archetype_definition(archetype: str) -> str:
    return {
        "UNCLASSIFIED_LOW_ROOM": "Unclassified entry with low room to next resistance.",
        "UNCLASSIFIED_CHASE_EXTENSION": "Unclassified entry with chase distance, late timing, or high extension proxy.",
        "UNCLASSIFIED_WEAK_FLOW_OR_CROWDING": "Unclassified entry with weak initiative flow or crowded long context.",
        "UNCLASSIFIED_COST_RISK": "Unclassified entry where projected cost/spread is already high.",
        "UNCLASSIFIED_STRUCTURE_MISSING": "Unclassified because structure/zone data is missing or unavailable.",
        "UNCLASSIFIED_NEUTRAL_STRUCTURE": "Unclassified row without one dominant pre-entry risk archetype.",
    }.get(archetype, "Unclassified archetype.")


def _mid_long_unclassified_archetype_read(row: dict[str, Any], *, min_sample: int) -> str:
    sample = int(row.get("closed_count") or row.get("sample_count") or 0)
    avg_r = _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed"))
    damage_delta = _decimal_or_zero_snapshot(row.get("early_damage_share_delta_vs_baseline"))
    if sample < min_sample:
        return "ARCHETYPE_SAMPLE_TOO_SMALL"
    if avg_r > 0 and damage_delta < 0:
        return "ARCHETYPE_PROMISING"
    if avg_r < 0 and damage_delta > 0:
        return "ARCHETYPE_DAMAGE_CLUSTER"
    return "ARCHETYPE_MIXED"


def _mid_long_dual_discovery_summary(
    *,
    predicate_rows: list[dict[str, Any]],
    rule_rows: list[dict[str, Any]],
    group_rows: list[dict[str, Any]],
    cluster_rows: list[dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    all_rows = [*predicate_rows, *rule_rows]
    promising = [row for row in all_rows if row.get("read") == "PROMISING_PATTERN"]
    weak = [row for row in all_rows if row.get("read") == "WEAK_VALIDATION_LIFT"]
    overfit = [row for row in all_rows if row.get("read") == "TRAIN_ONLY_OVERFIT"]
    archetype_promising = [row for row in cluster_rows if row.get("read") == "ARCHETYPE_PROMISING"]
    if promising:
        read = "PROMISING_PATTERN_FOUND"
        next_action = "Replay the top validation-stable pattern with exact candle ordering before any shadow rule discussion."
    elif weak:
        read = "WEAK_PATTERN_ONLY"
        next_action = "Treat weak-lift rows as hypotheses; collect more data or combine with clearer taxonomy first."
    elif archetype_promising:
        read = "TAXONOMY_ARCHETYPE_CANDIDATE"
        next_action = "Inspect charts from promising unclassified archetypes and try deterministic family definition."
    else:
        read = "NO_STABLE_PATTERN_YET"
        next_action = "Do not optimize thresholds. MID_LONG needs more structure definition or should remain research-only."
    best = max(all_rows, key=_mid_long_dual_row_sort_key) if all_rows else None
    return {
        "read": read,
        "min_sample": min_sample,
        "promising_pattern_count": len(promising),
        "weak_pattern_count": len(weak),
        "train_only_overfit_count": len(overfit),
        "promising_archetype_count": len(archetype_promising),
        "best_rule": {
            "rule_id": best.get("rule_id"),
            "label": best.get("label"),
            "read": best.get("read"),
            "validation_selected_count": best.get("validation_selected_count"),
            "validation_avg_delta_r": (best.get("validation") or {}).get("realistic_avg_r_delta_vs_baseline"),
            "validation_total_r": (best.get("validation") or {}).get("realistic_total_r_closed"),
            "validation_early_damage_delta_pct": (best.get("validation") or {}).get("early_damage_share_delta_vs_baseline"),
        }
        if best
        else None,
        "top_feature_group": group_rows[0] if group_rows else None,
        "next_action": next_action,
    }


MID_LONG_MATCHED_NUMERIC_FEATURES: tuple[tuple[str, str, str], ...] = (
    ("price_return", "Price return %", "evidence"),
    ("volume_ratio_vs_lookback", "Volume vs 30-candle avg", "evidence"),
    ("kline_taker_buy_ratio", "Taker buy ratio", "evidence"),
    ("kline_taker_sell_ratio", "Taker sell ratio", "evidence"),
    ("oi_change_pct", "OI change %", "evidence"),
    ("oi_zscore", "OI z-score", "evidence"),
    ("range_ratio_vs_atr", "Range / ATR", "evidence"),
    ("atr_extension_normalized", "ATR extension", "evidence"),
    ("funding_percentile_30d", "Funding percentile", "evidence"),
    ("futures_spread_pct", "Futures spread %", "evidence"),
    ("global_long_short_ratio", "Global L/S ratio", "evidence"),
    ("top_trader_position_ratio", "Top trader position", "evidence"),
    ("top_trader_account_ratio", "Top trader account", "evidence"),
    ("realistic_cost_r_estimate", "Realistic cost R", "tradability"),
    ("entry_distance_from_zone_atr", "Entry distance from zone ATR", "structure"),
    ("room_to_next_resistance_atr", "Room to next resistance ATR", "structure"),
    ("close_penetration_atr", "Close penetration ATR", "structure"),
    ("body_above_zone_ratio", "Body above zone ratio", "structure"),
    ("upper_wick_to_body_ratio", "Upper wick/body ratio", "structure"),
    ("bars_since_breakout", "Bars since breakout", "structure"),
    ("zone_touch_count", "Zone touch count", "structure"),
    ("zone_age_bars", "Zone age bars", "structure"),
)


def _mid_long_matched_contrastive_anatomy(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    reset_by_id = {
        str(item.get("signal_id") or idx): _mid_long_reset_state(
            item,
            taxonomy_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    tp_items = [item for item in items if item.get("result_status") == "TP_HIT"]
    sl_items = [item for item in items if item.get("result_status") == "SL_HIT"]
    pairs = _mid_long_matched_pairs(
        tp_items,
        sl_items,
        taxonomy_by_id=taxonomy_by_id,
        reset_by_id=reset_by_id,
    )
    feature_rows = _mid_long_matched_feature_rows(pairs, min_sample=min_sample)
    family_rows = _mid_long_matched_family_rows(pairs)
    match_level_rows = _mid_long_match_level_rows(pairs)
    return {
        "scope": "MID_LONG 1h Matched Contrastive Anatomy",
        "method": (
            "Pair TP rows with similar SL rows using pre-entry family/cost/flow context, then compare "
            "pre-entry numeric evidence. This avoids winner-only selection bias."
        ),
        "model_version": "MID_LONG_MATCHED_CONTRASTIVE_V1",
        "min_sample": min_sample,
        "target": "TP_HIT versus SL_HIT, matched on pre-entry context",
        "match_policy": {
            "primary": "primary_family + projected_cost_bucket + flow_state_provisional",
            "fallback_1": "primary_family + projected_cost_bucket",
            "fallback_2": "primary_family",
            "tie_break": "nearest signal timestamp, then same symbol preference",
            "sl_reuse": "disabled until no unused row exists in a fallback bucket",
        },
        "baseline": {
            "closed_count": baseline.get("closed_count"),
            "tp_count": baseline.get("tp_count"),
            "sl_count": baseline.get("sl_count"),
            "winrate_pct": baseline.get("winrate_pct"),
            "realistic_total_r_closed": baseline.get("realistic_total_r_closed"),
            "realistic_avg_r_closed": baseline.get("realistic_avg_r_closed"),
        },
        "tp_count": len(tp_items),
        "sl_count": len(sl_items),
        "matched_pair_count": len(pairs),
        "match_level_rows": match_level_rows,
        "family_rows": family_rows,
        "feature_rows": feature_rows,
        "top_feature_candidates": [
            row
            for row in feature_rows
            if row.get("read") in {"CLEAR_MATCHED_GAP", "WEAK_MATCHED_GAP"}
        ][:8],
        "pair_examples": [_mid_long_matched_pair_public_row(pair) for pair in pairs[:20]],
        "summary": _mid_long_matched_summary(
            pairs=pairs,
            feature_rows=feature_rows,
            min_sample=min_sample,
        ),
        "guardrails": [
            "Matched rows are diagnostics, not live gates.",
            "Only pre-entry fields are compared; MFE/MAE, first-hour response, and path labels are excluded as features.",
            "Fallback matches are weaker than strict matches and must not be overread.",
            "Any candidate fingerprint must still pass chronological validation before becoming shadow logic.",
        ],
    }


def _mid_long_matched_pairs(
    tp_items: list[dict[str, Any]],
    sl_items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    used_sl_ids: set[str] = set()
    pairs: list[dict[str, Any]] = []
    ordered_tp = sorted(tp_items, key=lambda item: _mid_long_signal_sort_key(item))
    for pair_index, tp in enumerate(ordered_tp, start=1):
        tp_key = str(tp.get("signal_id") or pair_index)
        tp_state = _mid_long_match_state(tp, taxonomy_by_id=taxonomy_by_id, reset_by_id=reset_by_id)
        candidate = _mid_long_best_sl_match(
            tp,
            tp_state=tp_state,
            sl_items=sl_items,
            taxonomy_by_id=taxonomy_by_id,
            reset_by_id=reset_by_id,
            used_sl_ids=used_sl_ids,
        )
        if not candidate:
            continue
        sl, sl_state, level = candidate
        sl_key = str(sl.get("signal_id") or f"sl:{pair_index}")
        used_sl_ids.add(sl_key)
        pairs.append(
            {
                "pair_id": f"MLPAIR-{pair_index:04d}",
                "match_level": level,
                "tp_item": tp,
                "sl_item": sl,
                "tp_state": tp_state,
                "sl_state": sl_state,
                "family": tp_state["primary_family"],
                "cost_bucket": tp_state["cost_bucket"],
                "flow_state": tp_state["flow_state"],
                "timestamp_gap_seconds": abs(
                    _mid_long_timestamp_seconds(tp) - _mid_long_timestamp_seconds(sl)
                ),
                "same_symbol": str(tp.get("symbol") or "") == str(sl.get("symbol") or ""),
                "tp_key": tp_key,
                "sl_key": sl_key,
            }
        )
    return pairs


def _mid_long_best_sl_match(
    tp: dict[str, Any],
    *,
    tp_state: dict[str, str],
    sl_items: list[dict[str, Any]],
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
    used_sl_ids: set[str],
) -> tuple[dict[str, Any], dict[str, str], str] | None:
    candidates: list[tuple[dict[str, Any], dict[str, str], str, bool]] = []
    for idx, sl in enumerate(sl_items):
        sl_key = str(sl.get("signal_id") or f"sl:{idx}")
        sl_state = _mid_long_match_state(sl, taxonomy_by_id=taxonomy_by_id, reset_by_id=reset_by_id)
        level = _mid_long_match_level(tp_state, sl_state)
        if level == "NO_MATCH":
            continue
        candidates.append((sl, sl_state, level, sl_key in used_sl_ids))
    if not candidates:
        return None
    level_rank = {"STRICT": 0, "FAMILY_COST": 1, "FAMILY_ONLY": 2, "FALLBACK_ALL": 3}
    candidates.sort(
        key=lambda row: (
            row[3],
            level_rank.get(row[2], 99),
            0 if str(row[0].get("symbol") or "") == str(tp.get("symbol") or "") else 1,
            abs(_mid_long_timestamp_seconds(tp) - _mid_long_timestamp_seconds(row[0])),
        )
    )
    sl, sl_state, level, _used = candidates[0]
    return sl, sl_state, level


def _mid_long_match_state(
    item: dict[str, Any],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
) -> dict[str, str]:
    key = str(item.get("signal_id") or "")
    taxonomy = taxonomy_by_id.get(key, {})
    reset = reset_by_id.get(key, {})
    return {
        "primary_family": str(reset.get("primary_family") or taxonomy.get("setup_family") or "UNKNOWN"),
        "cost_bucket": str(taxonomy.get("projected_cost_bucket") or "UNKNOWN"),
        "flow_state": str(taxonomy.get("flow_state_provisional") or taxonomy.get("flow_regime") or "UNKNOWN"),
        "crowding_bucket": str(taxonomy.get("crowding_bucket") or "UNKNOWN"),
    }


def _mid_long_match_level(tp_state: dict[str, str], sl_state: dict[str, str]) -> str:
    if tp_state["primary_family"] == sl_state["primary_family"]:
        if tp_state["cost_bucket"] == sl_state["cost_bucket"] and tp_state["flow_state"] == sl_state["flow_state"]:
            return "STRICT"
        if tp_state["cost_bucket"] == sl_state["cost_bucket"]:
            return "FAMILY_COST"
        return "FAMILY_ONLY"
    return "FALLBACK_ALL"


def _mid_long_matched_feature_rows(pairs: list[dict[str, Any]], *, min_sample: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, label, source in MID_LONG_MATCHED_NUMERIC_FEATURES:
        pair_values: list[tuple[Decimal, Decimal]] = []
        for pair in pairs:
            tp_value = _mid_long_matched_numeric_value(pair["tp_item"], field)
            sl_value = _mid_long_matched_numeric_value(pair["sl_item"], field)
            if tp_value is None or sl_value is None:
                continue
            pair_values.append((tp_value, sl_value))
        tp_values = [tp for tp, _sl in pair_values]
        sl_values = [sl for _tp, sl in pair_values]
        diffs = [tp - sl for tp, sl in pair_values]
        median_gap = _median_decimal_snapshot(diffs)
        positive_count = sum(1 for diff in diffs if diff > 0)
        negative_count = sum(1 for diff in diffs if diff < 0)
        usable_count = len(pair_values)
        direction = _mid_long_matched_gap_direction(median_gap)
        directional_share = _pct_decimal(
            positive_count if direction == "TP_HIGHER" else negative_count if direction == "TP_LOWER" else 0,
            usable_count,
        )
        row = {
            "field": field,
            "label": label,
            "source": source,
            "matched_count": usable_count,
            "missing_pair_count": max(0, len(pairs) - usable_count),
            "tp_median": _median_decimal_snapshot(tp_values),
            "sl_median": _median_decimal_snapshot(sl_values),
            "median_gap": median_gap,
            "tp_q1": _percentile_decimal_snapshot(tp_values, Decimal("0.25")),
            "tp_q3": _percentile_decimal_snapshot(tp_values, Decimal("0.75")),
            "sl_q1": _percentile_decimal_snapshot(sl_values, Decimal("0.25")),
            "sl_q3": _percentile_decimal_snapshot(sl_values, Decimal("0.75")),
            "direction": direction,
            "directional_pair_share_pct": directional_share,
            "tp_higher_count": positive_count,
            "sl_higher_count": negative_count,
            "equal_count": usable_count - positive_count - negative_count,
        }
        row["read"] = _mid_long_matched_feature_read(row, min_sample=min_sample)
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _mid_long_matched_feature_rank(str(row.get("read") or "")),
            _decimal_or_zero_snapshot(row.get("directional_pair_share_pct")),
            int(row.get("matched_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_matched_numeric_value(item: dict[str, Any], field: str) -> Decimal | None:
    if field == "room_to_next_resistance_atr":
        return _mid_long_first_decimal(item, "room_to_next_resistance_atr", "structure_zone_nearest_resistance_distance_atr")
    if field == "room_to_next_support_atr":
        return _mid_long_first_decimal(item, "room_to_next_support_atr", "structure_zone_nearest_support_distance_atr")
    direct = _decimal_or_none_snapshot(item.get(field))
    if direct is not None:
        return direct
    return _mid_long_evidence_value(item, field)


def _mid_long_matched_gap_direction(median_gap: Decimal | None) -> str:
    if median_gap is None or median_gap == 0:
        return "NO_DIRECTION"
    return "TP_HIGHER" if median_gap > 0 else "TP_LOWER"


def _mid_long_matched_feature_read(row: dict[str, Any], *, min_sample: int) -> str:
    matched = int(row.get("matched_count") or 0)
    if matched < min_sample:
        return "MATCHED_SAMPLE_SMALL"
    share = _decimal_or_zero_snapshot(row.get("directional_pair_share_pct"))
    gap = _decimal_or_none_snapshot(row.get("median_gap"))
    if gap is None or gap == 0:
        return "NO_MATCHED_GAP"
    if share >= Decimal("70"):
        return "CLEAR_MATCHED_GAP"
    if share >= Decimal("60"):
        return "WEAK_MATCHED_GAP"
    return "NO_MATCHED_GAP"


def _mid_long_matched_feature_rank(read: str) -> int:
    return {
        "CLEAR_MATCHED_GAP": 3,
        "WEAK_MATCHED_GAP": 2,
        "NO_MATCHED_GAP": 1,
        "MATCHED_SAMPLE_SMALL": 0,
    }.get(read, 0)


def _mid_long_matched_family_rows(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        grouped[str(pair.get("family") or "UNKNOWN")].append(pair)
    rows: list[dict[str, Any]] = []
    for family, family_pairs in grouped.items():
        tp_items = [pair["tp_item"] for pair in family_pairs]
        sl_items = [pair["sl_item"] for pair in family_pairs]
        rows.append(
            {
                "family": family,
                "matched_pair_count": len(family_pairs),
                "strict_pair_count": sum(1 for pair in family_pairs if pair.get("match_level") == "STRICT"),
                "tp_realistic_median_r": _median_decimal_snapshot(
                    [
                        value
                        for item in tp_items
                        if (value := _decimal_or_none_snapshot(item.get("realistic_realized_r"))) is not None
                    ]
                ),
                "sl_realistic_median_r": _median_decimal_snapshot(
                    [
                        value
                        for item in sl_items
                        if (value := _decimal_or_none_snapshot(item.get("realistic_realized_r"))) is not None
                    ]
                ),
                "tp_top_symbol": _mid_long_top_symbol(tp_items),
                "sl_top_symbol": _mid_long_top_symbol(sl_items),
            }
        )
    rows.sort(key=lambda row: int(row.get("matched_pair_count") or 0), reverse=True)
    return rows


def _mid_long_match_level_rows(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: Counter[str] = Counter(str(pair.get("match_level") or "UNKNOWN") for pair in pairs)
    return [
        {
            "match_level": level,
            "pair_count": count,
            "pair_share_pct": _pct_decimal(count, len(pairs)),
        }
        for level, count in grouped.most_common()
    ]


def _mid_long_top_symbol(items: list[dict[str, Any]]) -> str | None:
    if not items:
        return None
    return Counter(str(item.get("symbol") or "UNKNOWN") for item in items).most_common(1)[0][0]


def _mid_long_matched_pair_public_row(pair: dict[str, Any]) -> dict[str, Any]:
    tp = pair["tp_item"]
    sl = pair["sl_item"]
    return {
        "pair_id": pair.get("pair_id"),
        "match_level": pair.get("match_level"),
        "family": pair.get("family"),
        "cost_bucket": pair.get("cost_bucket"),
        "flow_state": pair.get("flow_state"),
        "timestamp_gap_seconds": pair.get("timestamp_gap_seconds"),
        "same_symbol": pair.get("same_symbol"),
        "tp_symbol": tp.get("symbol"),
        "tp_signal_timestamp": tp.get("signal_timestamp"),
        "tp_realistic_r": tp.get("realistic_realized_r"),
        "sl_symbol": sl.get("symbol"),
        "sl_signal_timestamp": sl.get("signal_timestamp"),
        "sl_realistic_r": sl.get("realistic_realized_r"),
    }


def _mid_long_matched_summary(
    *,
    pairs: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    clear_rows = [row for row in feature_rows if row.get("read") == "CLEAR_MATCHED_GAP"]
    weak_rows = [row for row in feature_rows if row.get("read") == "WEAK_MATCHED_GAP"]
    strict_pairs = sum(1 for pair in pairs if pair.get("match_level") == "STRICT")
    if len(pairs) < min_sample:
        read = "MATCHED_DATA_NOT_READY"
        next_action = "Collect more MID_LONG 1h closed rows before reading matched gaps."
    elif clear_rows:
        read = "MATCHED_FINGERPRINT_CANDIDATES_FOUND"
        next_action = "Inspect clear-gap features by family, then test early-damage model without post-entry leakage."
    elif weak_rows:
        read = "MATCHED_WEAK_FINGERPRINTS_ONLY"
        next_action = "Use weak-gap features as hypotheses only; do not turn them into filters yet."
    else:
        read = "NO_MATCHED_FINGERPRINT_YET"
        next_action = "Matched TP and SL remain similar; MID_LONG may need a new family definition or suspension."
    return {
        "read": read,
        "matched_pair_count": len(pairs),
        "strict_pair_count": strict_pairs,
        "strict_pair_share_pct": _pct_decimal(strict_pairs, len(pairs)),
        "clear_gap_feature_count": len(clear_rows),
        "weak_gap_feature_count": len(weak_rows),
        "next_action": next_action,
    }


def _mid_long_timestamp_seconds(item: dict[str, Any]) -> int:
    stamp = str(item.get("signal_timestamp") or item.get("window_close_time") or item.get("result_time_utc") or "")
    if not stamp:
        return 0
    try:
        return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
    except Exception:
        digits = "".join(ch for ch in stamp if ch.isdigit())
        return int(digits[:14] or 0)


def _mid_long_signal_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    return (_mid_long_timestamp_seconds(item), str(item.get("symbol") or ""))


def _mid_long_damage_hurdle_score_state(
    item: dict[str, Any],
    *,
    reset: dict[str, Any],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    components = {
        "primary_family": _mid_long_hurdle_family_bucket(reset),
        "zone_freshness": _mid_long_hurdle_zone_bucket(item),
        "entry_geometry": _mid_long_hurdle_entry_geometry_bucket(item),
        "spatial_room": _mid_long_hurdle_room_bucket(item, taxonomy),
        "flow_crowding": _mid_long_hurdle_flow_crowding_bucket(item, taxonomy),
        "tradability": _mid_long_hurdle_tradability_bucket(item, taxonomy),
    }
    points = {
        "primary_family": components["primary_family"] in {
            "BREAKOUT_CONTINUATION",
            "SUPPORT_RETEST",
            "PULLBACK",
        },
        "zone_freshness": components["zone_freshness"] in {"FRESH_REPEATED_ZONE", "MATURE_REPEATED_ZONE"},
        "entry_geometry": components["entry_geometry"] in {"ACCEPTED_MODERATE_DISTANCE", "ACCEPTED_CLOSE_DISTANCE"},
        "spatial_room": components["spatial_room"] in {"ROOM_CLEAR", "ROOM_MODERATE"},
        "flow_crowding": components["flow_crowding"] in {"FLOW_CONFIRMED_NOT_CROWDED", "MIXED_NOT_CROWDED"},
        "tradability": components["tradability"] in {"LOW_COST", "MODERATE_COST"},
    }
    return {
        "components": components,
        "points": points,
        "score": sum(1 for passed in points.values() if passed),
        "max_score": len(points),
    }


def _mid_long_hurdle_family_bucket(reset: dict[str, Any]) -> str:
    family = str(reset.get("primary_family") or "")
    return {
        "BREAKOUT_CONTINUATION_LONG": "BREAKOUT_CONTINUATION",
        "SUPPORT_RETEST_LONG": "SUPPORT_RETEST",
        "PULLBACK_LONG": "PULLBACK",
        "OTHER_STRUCTURED_LONG": "OTHER_STRUCTURED",
        "UNCLASSIFIED_MID_LONG": "UNCLASSIFIED",
    }.get(family, "UNCLASSIFIED")


def _mid_long_hurdle_zone_bucket(item: dict[str, Any]) -> str:
    touches = _mid_long_first_decimal(item, "zone_touch_count")
    age = _mid_long_first_decimal(item, "zone_age_bars")
    if touches is None or age is None:
        return "ZONE_UNKNOWN"
    if touches < Decimal("2"):
        return "SINGLE_TOUCH_ZONE"
    if age <= Decimal("12"):
        return "FRESH_REPEATED_ZONE"
    if age <= Decimal("48"):
        return "MATURE_REPEATED_ZONE"
    return "OLD_REPEATED_ZONE"


def _mid_long_hurdle_entry_geometry_bucket(item: dict[str, Any]) -> str:
    distance = _mid_long_first_decimal(item, "entry_distance_from_zone_atr")
    penetration = _mid_long_first_decimal(item, "close_penetration_atr")
    body = _mid_long_first_decimal(item, "body_above_zone_ratio")
    if distance is None:
        return "GEOMETRY_UNKNOWN"
    if distance > Decimal("1.50"):
        return "CHASE_DISTANCE"
    if penetration is not None and penetration < Decimal("0.10"):
        return "THIN_PENETRATION"
    if body is not None and body < Decimal("0.35"):
        return "THIN_BODY_ACCEPTANCE"
    if distance < Decimal("0.15"):
        return "ACCEPTED_CLOSE_DISTANCE"
    return "ACCEPTED_MODERATE_DISTANCE"


def _mid_long_hurdle_room_bucket(item: dict[str, Any], taxonomy: dict[str, Any]) -> str:
    room = _mid_long_first_decimal(
        item,
        "room_to_next_resistance_atr",
        "structure_zone_nearest_resistance_distance_atr",
    )
    if room is None:
        taxonomy_room = str(taxonomy.get("room_to_resistance_bucket") or "")
        return taxonomy_room or "ROOM_UNKNOWN"
    if room <= Decimal("0.75"):
        return "LOW_ROOM"
    if room <= Decimal("1.50"):
        return "ROOM_MODERATE"
    return "ROOM_CLEAR"


def _mid_long_hurdle_flow_crowding_bucket(item: dict[str, Any], taxonomy: dict[str, Any]) -> str:
    flow = str(taxonomy.get("flow_state_provisional") or _mid_long_flow_state(item))
    crowding = str(taxonomy.get("crowding_bucket") or "")
    if flow == "UNKNOWN" and crowding in {"", "UNKNOWN"}:
        return "FLOW_CROWDING_UNKNOWN"
    if crowding in {"HIGH_CROWDING", "EXTREME_CROWDING"}:
        return "CROWDED_LONG"
    if flow == "CONFIRMED":
        return "FLOW_CONFIRMED_NOT_CROWDED"
    if flow == "WEAK":
        return "WEAK_FLOW_NOT_CROWDED"
    return "MIXED_NOT_CROWDED"


def _mid_long_hurdle_tradability_bucket(item: dict[str, Any], taxonomy: dict[str, Any]) -> str:
    cost_bucket = str(taxonomy.get("projected_cost_bucket") or "")
    cost = _decimal_or_none_snapshot(item.get("realistic_cost_r_estimate"))
    if cost_bucket and cost_bucket != "COST_UNKNOWN":
        return cost_bucket
    if cost is None:
        return "COST_UNKNOWN"
    if cost <= Decimal("0.10"):
        return "LOW_COST"
    if cost <= Decimal("0.20"):
        return "MODERATE_COST"
    if cost <= Decimal("0.35"):
        return "HIGH_COST"
    return "EXTREME_COST"


def _mid_long_first_decimal(item: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        value = _decimal_or_none_snapshot(item.get(key))
        if value is not None:
            return value
    return None


def _mid_long_hurdle_group_rows(
    items: list[dict[str, Any]],
    *,
    group_key: str,
    group_label: str,
    group_lookup: Callable[[int, dict[str, Any]], str],
    labels_by_id: dict[str, str],
    baseline: dict[str, Any],
    baseline_hurdle: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        grouped[group_lookup(idx, item)].append(item)
    rows: list[dict[str, Any]] = []
    for value, value_items in grouped.items():
        row = _mid_long_perf_row(
            f"HURDLE:{group_key}:{value}",
            value,
            f"{group_key} == {value}",
            value_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            _mid_long_hurdle_perf_summary(
                value_items,
                labels_by_id=labels_by_id,
                baseline=baseline_hurdle,
            )
        )
        row.update(
            {
                "group_key": group_key,
                "group_label": group_label,
                "group_value": value,
                "read": _mid_long_hurdle_group_read(row, min_sample=min_sample),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0) >= min_sample,
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_hurdle_score_bucket_rows(
    items: list[dict[str, Any]],
    *,
    score_by_id: dict[str, dict[str, Any]],
    labels_by_id: dict[str, str],
    baseline: dict[str, Any],
    baseline_hurdle: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        key = str(item.get("signal_id") or idx)
        score = int(score_by_id[key]["score"])
        grouped[f"SCORE_{score}"].append(item)
    rows: list[dict[str, Any]] = []
    for score_bucket, bucket_items in sorted(grouped.items(), key=lambda pair: pair[0]):
        score = int(score_bucket.rsplit("_", 1)[-1])
        row = _mid_long_perf_row(
            f"HURDLE_SCORE:{score}",
            score_bucket,
            f"hurdle_score == {score}",
            bucket_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            _mid_long_hurdle_perf_summary(
                bucket_items,
                labels_by_id=labels_by_id,
                baseline=baseline_hurdle,
            )
        )
        row.update(
            {
                "score": score,
                "score_bucket": score_bucket,
                "read": _mid_long_hurdle_group_read(row, min_sample=min_sample),
            }
        )
        rows.append(row)
    rows.sort(key=lambda row: int(row.get("score") or 0), reverse=True)
    return rows


def _mid_long_hurdle_threshold_rows(
    items: list[dict[str, Any]],
    *,
    score_by_id: dict[str, dict[str, Any]],
    labels_by_id: dict[str, str],
    baseline: dict[str, Any],
    baseline_hurdle: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    max_score = max((int(state["max_score"]) for state in score_by_id.values()), default=0)
    rows: list[dict[str, Any]] = []
    base_tp = int(baseline_hurdle.get("tp_count") or 0)
    base_sl = int(baseline_hurdle.get("sl_count") or 0)
    base_damage = int(baseline_hurdle.get("early_damage_count") or 0)
    for threshold in range(0, max_score + 1):
        selected = [
            item
            for idx, item in enumerate(items)
            if int(score_by_id[str(item.get("signal_id") or idx)]["score"]) >= threshold
        ]
        row = _mid_long_perf_row(
            f"HURDLE_THRESHOLD:{threshold}",
            f"score >= {threshold}",
            f"diagnostic_hurdle_score >= {threshold}",
            selected,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            _mid_long_hurdle_perf_summary(
                selected,
                labels_by_id=labels_by_id,
                baseline=baseline_hurdle,
            )
        )
        selected_tp = int(row.get("tp_count") or 0)
        selected_sl = int(row.get("sl_count") or 0)
        selected_damage = int(row.get("early_damage_count") or 0)
        row.update(
            {
                "threshold_score": threshold,
                "coverage_pct": _pct_decimal(len(selected), len(items)),
                "tp_retention_pct": _pct_decimal(selected_tp, base_tp),
                "tp_rejection_pct": _pct_decimal(max(0, base_tp - selected_tp), base_tp),
                "sl_rejection_pct": _pct_decimal(max(0, base_sl - selected_sl), base_sl),
                "early_damage_rejection_pct": _pct_decimal(max(0, base_damage - selected_damage), base_damage),
                "read": _mid_long_hurdle_threshold_read(row, min_sample=min_sample),
            }
        )
        rows.append(row)
    return rows


def _mid_long_hurdle_chronological_block_rows(
    items: list[dict[str, Any]],
    *,
    score_by_id: dict[str, dict[str, Any]],
    labels_by_id: dict[str, str],
    threshold: int,
    min_sample: int,
) -> list[dict[str, Any]]:
    if not items:
        return []
    ordered = sorted(items, key=lambda item: str(item.get("signal_timestamp") or item.get("window_close_time") or ""))
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(ordered):
        block_index = min(3, idx * 4 // len(ordered))
        grouped[block_index].append(item)
    rows: list[dict[str, Any]] = []
    for block_index in range(4):
        block_items = grouped.get(block_index, [])
        selected = [
            item
            for item_idx, item in enumerate(block_items)
            if int(score_by_id.get(str(item.get("signal_id") or item_idx), {}).get("score") or 0) >= threshold
        ]
        baseline = _mid_long_perf_row(
            f"HURDLE_BLOCK_BASE:{block_index + 1}",
            f"Block {block_index + 1} baseline",
            "chronological block baseline",
            block_items,
            baseline=None,
            required_fields=(),
            min_sample=min_sample,
        )
        selected_row = _mid_long_perf_row(
            f"HURDLE_BLOCK_SELECTED:{block_index + 1}",
            f"Block {block_index + 1} selected",
            f"diagnostic_hurdle_score >= {threshold}",
            selected,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        selected_row.update(
            _mid_long_hurdle_perf_summary(
                selected,
                labels_by_id=labels_by_id,
                baseline=_mid_long_hurdle_perf_summary(block_items, labels_by_id=labels_by_id, baseline=None),
            )
        )
        rows.append(
            {
                "block": block_index + 1,
                "threshold_score": threshold,
                "sample_count": len(block_items),
                "selected_count": len(selected),
                "selected_coverage_pct": _pct_decimal(len(selected), len(block_items)),
                "first_signal_timestamp": block_items[0].get("signal_timestamp") if block_items else None,
                "last_signal_timestamp": block_items[-1].get("signal_timestamp") if block_items else None,
                "baseline_realistic_total_r_closed": baseline.get("realistic_total_r_closed"),
                "baseline_realistic_avg_r_closed": baseline.get("realistic_avg_r_closed"),
                "selected_realistic_total_r_closed": selected_row.get("realistic_total_r_closed"),
                "selected_realistic_avg_r_closed": selected_row.get("realistic_avg_r_closed"),
                "selected_early_damage_share_pct": selected_row.get("early_damage_share_pct"),
                "top_symbol": selected_row.get("top_symbol"),
                "top_symbol_share_pct": selected_row.get("top_symbol_share_pct"),
                "read": _mid_long_hurdle_block_read(selected_row, min_sample=min_sample),
            }
        )
    return rows


def _mid_long_hurdle_perf_summary(
    items: list[dict[str, Any]],
    *,
    labels_by_id: dict[str, str],
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    perf = aggregate_signal_performance_items(items)
    label_counts = Counter(
        labels_by_id.get(str(item.get("signal_id") or idx), "DAMAGE_UNKNOWN")
        for idx, item in enumerate(items)
    )
    non_damage = [
        item
        for idx, item in enumerate(items)
        if labels_by_id.get(str(item.get("signal_id") or idx), "DAMAGE_UNKNOWN") != "EARLY_DAMAGE"
    ]
    cost_values = [
        value
        for item in items
        if (value := _decimal_or_none_snapshot(item.get("realistic_cost_r_estimate"))) is not None
    ]
    ideal_total = _decimal_or_zero_snapshot(perf.get("total_r_closed"))
    realistic_total = _decimal_or_zero_snapshot(perf.get("realistic_total_r_closed"))
    row: dict[str, Any] = {
        "early_damage_count": label_counts.get("EARLY_DAMAGE", 0),
        "survived_positive_count": label_counts.get("SURVIVED_POSITIVE_PAYOFF", 0),
        "survived_negative_count": label_counts.get("SURVIVED_NEGATIVE_PAYOFF", 0),
        "damage_unknown_count": label_counts.get("DAMAGE_UNKNOWN", 0),
        "early_damage_share_pct": _pct_decimal(label_counts.get("EARLY_DAMAGE", 0), len(items)),
        "non_damage_count": len(non_damage),
        "non_damage_share_pct": _pct_decimal(len(non_damage), len(items)),
        "tp_count": perf.get("tp_count"),
        "sl_count": perf.get("sl_count"),
        "closed_count": perf.get("closed_count"),
        "ideal_total_r_closed": perf.get("total_r_closed"),
        "ideal_avg_r_closed": perf.get("avg_r_closed"),
        "realistic_total_r_closed": perf.get("realistic_total_r_closed"),
        "realistic_avg_r_closed": perf.get("realistic_avg_r_closed"),
        "execution_drag_r": realistic_total - ideal_total,
        "median_projected_cost_r": _median_decimal_snapshot(cost_values),
        "conditional_non_damage_realistic_total_r": aggregate_signal_performance_items(non_damage).get("realistic_total_r_closed"),
        "conditional_non_damage_realistic_avg_r": aggregate_signal_performance_items(non_damage).get("realistic_avg_r_closed"),
        "damage_label_mix": dict(label_counts),
    }
    if baseline is not None:
        row.update(
            {
                "early_damage_share_delta_vs_baseline": _decimal_delta_snapshot(
                    row.get("early_damage_share_pct"),
                    baseline.get("early_damage_share_pct"),
                ),
                "realistic_avg_r_delta_vs_baseline": _decimal_delta_snapshot(
                    row.get("realistic_avg_r_closed"),
                    baseline.get("realistic_avg_r_closed"),
                ),
                "realistic_total_r_delta_vs_baseline": _decimal_delta_snapshot(
                    row.get("realistic_total_r_closed"),
                    baseline.get("realistic_total_r_closed"),
                ),
                "execution_drag_delta_vs_baseline": _decimal_delta_snapshot(
                    row.get("execution_drag_r"),
                    baseline.get("execution_drag_r"),
                ),
            }
        )
    return row


def _mid_long_hurdle_group_read(row: dict[str, Any], *, min_sample: int) -> str:
    sample = int(row.get("closed_count") or row.get("sample_count") or 0)
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    damage_delta = _decimal_or_zero_snapshot(row.get("early_damage_share_delta_vs_baseline"))
    avg_r = _decimal_or_zero_snapshot(row.get("realistic_avg_r_closed"))
    if sample < min_sample:
        return "SAMPLE_TOO_SMALL"
    if avg_r > 0 and avg_delta >= Decimal("0.10") and damage_delta < 0:
        return "DAMAGE_AND_PAYOFF_IMPROVE"
    if damage_delta < 0 and avg_delta > 0:
        return "DAMAGE_REDUCED_PAYOFF_STILL_WEAK"
    if damage_delta > 0 and avg_delta < 0:
        return "DAMAGE_CLUSTER"
    return "MIXED_OR_NO_CLEAR_GAP"


def _mid_long_hurdle_threshold_read(row: dict[str, Any], *, min_sample: int) -> str:
    sample = int(row.get("closed_count") or 0)
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    total_r = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    damage_delta = _decimal_or_zero_snapshot(row.get("early_damage_share_delta_vs_baseline"))
    tp_retention = _decimal_or_zero_snapshot(row.get("tp_retention_pct"))
    if sample < min_sample:
        return "THRESHOLD_SAMPLE_SMALL"
    if total_r > 0 and avg_delta >= Decimal("0.10") and damage_delta < 0 and tp_retention >= Decimal("30"):
        return "HURDLE_SHADOW_CANDIDATE"
    if damage_delta < 0 and avg_delta > 0:
        return "HURDLE_REDUCES_DAMAGE_NOT_ECONOMIC"
    if tp_retention < Decimal("30"):
        return "HURDLE_CUTS_TOO_MANY_TP"
    return "HURDLE_NOT_READY"


def _mid_long_hurdle_block_read(row: dict[str, Any], *, min_sample: int) -> str:
    sample = int(row.get("closed_count") or 0)
    total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    if sample < min_sample:
        return "BLOCK_SAMPLE_SMALL"
    if total > 0:
        return "BLOCK_POSITIVE"
    return "BLOCK_NEGATIVE_OR_FLAT"


def _mid_long_hurdle_best_threshold(rows: list[dict[str, Any]], *, min_sample: int) -> dict[str, Any] | None:
    readable = [row for row in rows if int(row.get("closed_count") or 0) >= min_sample]
    if not readable:
        return None
    return max(
        readable,
        key=lambda row: (
            _mid_long_hurdle_threshold_rank(str(row.get("read") or "")),
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
            int(row.get("closed_count") or 0),
        ),
    )


def _mid_long_hurdle_threshold_rank(read: str) -> int:
    return {
        "HURDLE_SHADOW_CANDIDATE": 4,
        "HURDLE_REDUCES_DAMAGE_NOT_ECONOMIC": 3,
        "HURDLE_NOT_READY": 2,
        "HURDLE_CUTS_TOO_MANY_TP": 1,
        "THRESHOLD_SAMPLE_SMALL": 0,
    }.get(read, 0)


def _mid_long_hurdle_summary(
    *,
    baseline_hurdle: dict[str, Any],
    threshold_rows: list[dict[str, Any]],
    block_rows: list[dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    best = _mid_long_hurdle_best_threshold(threshold_rows, min_sample=min_sample)
    positive_blocks = sum(1 for row in block_rows if row.get("read") == "BLOCK_POSITIVE")
    readable_blocks = sum(1 for row in block_rows if row.get("read") != "BLOCK_SAMPLE_SMALL")
    if not best:
        read = "HURDLE_DATA_NOT_READY"
        next_action = "Keep collecting MID_LONG 1h rows; no readable hurdle threshold yet."
    elif best.get("read") == "HURDLE_SHADOW_CANDIDATE" and positive_blocks >= 3:
        read = "HURDLE_CANDIDATE_STABLE_ENOUGH_FOR_SHADOW_REPLAY"
        next_action = "Run exact candle-order shadow replay for this diagnostic threshold before any live rule discussion."
    elif best.get("read") == "HURDLE_SHADOW_CANDIDATE":
        read = "HURDLE_CANDIDATE_NEEDS_TIME_STABILITY"
        next_action = "Do not promote yet; inspect chronological blocks and symbol concentration."
    elif best.get("read") == "HURDLE_REDUCES_DAMAGE_NOT_ECONOMIC":
        read = "HURDLE_REDUCES_DAMAGE_BUT_PAYOFF_WEAK"
        next_action = "Use the best hurdle bucket for failure anatomy, not for a V2.1 rule."
    else:
        read = "HURDLE_NOT_SEPARATING"
        next_action = "Stop threshold tinkering; inspect family-specific damage causes and payoff geometry."
    return {
        "read": read,
        "baseline_early_damage_share_pct": baseline_hurdle.get("early_damage_share_pct"),
        "baseline_realistic_avg_r_closed": baseline_hurdle.get("realistic_avg_r_closed"),
        "best_threshold": _mid_long_hurdle_summary_threshold(best),
        "positive_block_count": positive_blocks,
        "readable_block_count": readable_blocks,
        "next_action": next_action,
    }


def _mid_long_hurdle_summary_threshold(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "threshold_score": row.get("threshold_score"),
        "closed_count": row.get("closed_count"),
        "coverage_pct": row.get("coverage_pct"),
        "tp_count": row.get("tp_count"),
        "sl_count": row.get("sl_count"),
        "early_damage_share_pct": row.get("early_damage_share_pct"),
        "realistic_total_r_closed": row.get("realistic_total_r_closed"),
        "realistic_avg_r_closed": row.get("realistic_avg_r_closed"),
        "realistic_avg_r_delta_vs_baseline": row.get("realistic_avg_r_delta_vs_baseline"),
        "tp_retention_pct": row.get("tp_retention_pct"),
        "sl_rejection_pct": row.get("sl_rejection_pct"),
        "early_damage_rejection_pct": row.get("early_damage_rejection_pct"),
        "read": row.get("read"),
    }


def _mid_long_sl_anatomy_v2(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    reset_by_id = {
        str(item.get("signal_id") or idx): _mid_long_reset_state(
            item,
            taxonomy_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    sl_items = [item for item in items if item.get("result_status") == "SL_HIT"]
    tp_items = [item for item in items if item.get("result_status") == "TP_HIT"]
    path_rows = _mid_long_sl_path_rows(
        sl_items,
        taxonomy_by_id=taxonomy_by_id,
        reset_by_id=reset_by_id,
        baseline=baseline,
        total_sl_count=len(sl_items),
        min_sample=min_sample,
    )
    cause_rows = _mid_long_sl_cause_rows(
        items,
        taxonomy_by_id=taxonomy_by_id,
        reset_by_id=reset_by_id,
        baseline=baseline,
        total_sl_count=len(sl_items),
        total_tp_count=len(tp_items),
        min_sample=min_sample,
    )
    matrix_rows = _mid_long_sl_path_cause_matrix(
        sl_items,
        taxonomy_by_id=taxonomy_by_id,
        reset_by_id=reset_by_id,
    )
    summary = _mid_long_sl_anatomy_summary(
        path_rows=path_rows,
        cause_rows=cause_rows,
        total_sl_count=len(sl_items),
        total_tp_count=len(tp_items),
    )
    return {
        "scope": "MID_LONG 1h SL Anatomy v2",
        "method": (
            "SL-only anatomy plus matched-vs-retained cause map. "
            "Cause rows are diagnostic flags; they do not become Signal Factory gates."
        ),
        "min_sample": min_sample,
        "total_signal_count": len(items),
        "tp_count": len(tp_items),
        "sl_count": len(sl_items),
        "sl_share_pct": _pct_decimal(len(sl_items), len(tp_items) + len(sl_items)),
        "path_rows": path_rows,
        "cause_rows": cause_rows,
        "path_cause_matrix": matrix_rows,
        "summary": summary,
        "guardrails": [
            "SL cause flags are research-only and may overlap.",
            "Retained rows are hypothetical diagnostics, not live reject rules.",
            "Post-entry path fields may explain failure but must not be used as pre-entry gates.",
            "A candidate damage tag must be validated chronologically before any shadow rule.",
        ],
    }


def _mid_long_sl_path_rows(
    sl_items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    total_sl_count: int,
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in sl_items:
        grouped[_mid_long_path_bucket(item)].append(item)
    path_order = (
        "SL_NO_FOLLOW_THROUGH",
        "SL_WEAK_FOLLOW_THROUGH",
        "SL_AFTER_PARTIAL_PROFIT",
        "SL_AFTER_STRONG_PROFIT",
    )
    rows: list[dict[str, Any]] = []
    for path_bucket in path_order:
        path_items = grouped.get(path_bucket, [])
        row = _mid_long_perf_row(
            f"SL_PATH:{path_bucket}",
            _mid_long_path_label(path_bucket),
            _mid_long_path_expression(path_bucket),
            path_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "path_bucket": path_bucket,
                "sl_count": len(path_items),
                "sl_share_of_all_sl_pct": _pct_decimal(len(path_items), total_sl_count),
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_decimal_values(path_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_decimal_values(path_items, "mae_r")),
                "median_cost_r": _median_decimal_snapshot(
                    _mid_long_item_decimal_values(path_items, "realistic_cost_r_estimate")
                ),
                "median_wick_decay_r": _median_decimal_snapshot(
                    _mid_long_item_decimal_values(path_items, "wick_to_close_decay_r")
                ),
                "median_followthrough_1h_r": _median_decimal_snapshot(
                    _mid_long_item_decimal_values(path_items, "close_followthrough_1h_r")
                ),
                "primary_family_mix": _mid_long_reset_mix(path_items, reset_by_id=reset_by_id, field="primary_family"),
                "modifier_mix": _mid_long_reset_modifier_mix(path_items, reset_by_id=reset_by_id),
                "setup_family_mix": _mid_long_taxonomy_mix(
                    path_items,
                    taxonomy_by_id=taxonomy_by_id,
                    taxonomy_key="setup_family",
                ),
                "flow_mix": _mid_long_taxonomy_mix(
                    path_items,
                    taxonomy_by_id=taxonomy_by_id,
                    taxonomy_key="flow_state_provisional",
                ),
                "crowding_mix": _mid_long_taxonomy_mix(
                    path_items,
                    taxonomy_by_id=taxonomy_by_id,
                    taxonomy_key="crowding_bucket",
                ),
                "extension_mix": _mid_long_taxonomy_mix(
                    path_items,
                    taxonomy_by_id=taxonomy_by_id,
                    taxonomy_key="extension_bucket",
                ),
                "read": _mid_long_sl_path_read(path_bucket, path_items, min_sample=min_sample),
            }
        )
        rows.append(row)
    return rows


def _mid_long_sl_cause_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    total_sl_count: int,
    total_tp_count: int,
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in _mid_long_sl_cause_specs():
        matched: list[dict[str, Any]] = []
        retained: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            key = str(item.get("signal_id") or idx)
            taxonomy = taxonomy_by_id[key]
            reset = reset_by_id[key]
            path_bucket = _mid_long_path_bucket(item)
            (matched if spec["predicate"](item, taxonomy, reset, path_bucket) else retained).append(item)
        row = _mid_long_sl_cause_row(
            spec,
            matched,
            retained,
            reset_by_id=reset_by_id,
            taxonomy_by_id=taxonomy_by_id,
            baseline=baseline,
            total_sl_count=total_sl_count,
            total_tp_count=total_tp_count,
            min_sample=min_sample,
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _mid_long_sl_cause_priority(str(row.get("read") or "")),
            _decimal_or_zero_snapshot(row.get("retained_realistic_total_r_delta_vs_baseline")),
            _decimal_or_zero_snapshot(row.get("matched_sl_capture_pct")),
            int(row.get("matched_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_sl_cause_row(
    spec: dict[str, Any],
    matched: list[dict[str, Any]],
    retained: list[dict[str, Any]],
    *,
    reset_by_id: dict[str, dict[str, Any]],
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    total_sl_count: int,
    total_tp_count: int,
    min_sample: int,
) -> dict[str, Any]:
    matched_perf = aggregate_signal_performance_items(matched)
    retained_perf = _mid_long_perf_row(
        f"SL_CAUSE_RETAINED:{spec['cause_id']}",
        f"Retain without {spec['label']}",
        f"NOT({spec['expression']})",
        retained,
        baseline=baseline,
        required_fields=tuple(spec.get("required_fields") or ()),
        min_sample=min_sample,
    )
    matched_sl = int(matched_perf.get("sl_count") or 0)
    matched_tp = int(matched_perf.get("tp_count") or 0)
    sl_capture = _pct_decimal(matched_sl, total_sl_count)
    tp_sacrifice = _pct_decimal(matched_tp, total_tp_count)
    row = {
        "cause_id": spec["cause_id"],
        "label": spec["label"],
        "expression": spec["expression"],
        "definition": spec["definition"],
        "required_fields": list(spec.get("required_fields") or ()),
        "matched_count": len(matched),
        "matched_share_pct": _pct_decimal(len(matched), len(matched) + len(retained)),
        "matched_tp_count": matched_tp,
        "matched_sl_count": matched_sl,
        "matched_sl_capture_pct": sl_capture,
        "matched_tp_sacrifice_pct": tp_sacrifice,
        "sl_to_tp_capture_ratio": _mid_long_decimal_ratio(sl_capture, tp_sacrifice),
        "matched_realistic_total_r_closed": matched_perf.get("realistic_total_r_closed"),
        "matched_realistic_avg_r_closed": matched_perf.get("realistic_avg_r_closed"),
        "matched_path_mix": _mid_long_path_mix(matched),
        "matched_sl_path_mix": dict(Counter(_mid_long_path_bucket(item) for item in matched if item.get("result_status") == "SL_HIT")),
        "matched_primary_family_mix": _mid_long_reset_mix(matched, reset_by_id=reset_by_id, field="primary_family"),
        "matched_modifier_mix": _mid_long_reset_modifier_mix(matched, reset_by_id=reset_by_id),
        "matched_flow_mix": _mid_long_taxonomy_mix(
            matched,
            taxonomy_by_id=taxonomy_by_id,
            taxonomy_key="flow_state_provisional",
        ),
        "retained_count": len(retained),
        "retained_tp_count": retained_perf.get("tp_count"),
        "retained_sl_count": retained_perf.get("sl_count"),
        "retained_winrate_pct": retained_perf.get("winrate_pct"),
        "retained_realistic_total_r_closed": retained_perf.get("realistic_total_r_closed"),
        "retained_realistic_avg_r_closed": retained_perf.get("realistic_avg_r_closed"),
        "retained_realistic_total_r_delta_vs_baseline": retained_perf.get("realistic_total_r_delta_vs_baseline"),
        "retained_realistic_avg_r_delta_vs_baseline": retained_perf.get("realistic_avg_r_delta_vs_baseline"),
        "retained_max_realistic_drawdown_r": retained_perf.get("max_realistic_drawdown_r"),
        "retained_path_mix": _mid_long_path_mix(retained),
        "top_symbol": retained_perf.get("top_symbol"),
        "top_symbol_share_pct": retained_perf.get("top_symbol_share_pct"),
    }
    row["read"] = _mid_long_sl_cause_read(row, min_sample=min_sample)
    return row


def _mid_long_sl_cause_specs() -> tuple[dict[str, Any], ...]:
    return (
        {
            "cause_id": "NO_STRUCTURE_OR_UNCLASSIFIED",
            "label": "No structure / unclassified",
            "expression": "primary_family == UNCLASSIFIED_MID_LONG OR structure unavailable",
            "definition": "Signal lacks a clean breakout/retest/pullback family before entry.",
            "required_fields": (),
            "predicate": lambda _item, taxonomy, reset, _path: reset.get("primary_family") == "UNCLASSIFIED_MID_LONG"
            or taxonomy.get("structure_status") == "UNAVAILABLE",
        },
        {
            "cause_id": "LATE_OR_EXTENDED_CHASE",
            "label": "Late or extended chase",
            "expression": "LATE_CHASE/HIGH_EXTENSION modifier OR high/extreme extension bucket",
            "definition": "Entry may be too far into the impulse instead of early continuation.",
            "required_fields": ("atr_extension_normalized", "price_atr_multiple"),
            "predicate": lambda _item, taxonomy, reset, _path: "LATE_CHASE" in (reset.get("modifiers") or [])
            or "HIGH_EXTENSION" in (reset.get("modifiers") or [])
            or taxonomy.get("extension_bucket") in {"HIGH_EXTENSION", "EXTREME_EXTENSION"},
        },
        {
            "cause_id": "LOW_ROOM_OR_RESISTANCE_CONFLICT",
            "label": "Low room / resistance conflict",
            "expression": "LOW_REMAINING_ROOM or STRUCTURE_CONFLICT",
            "definition": "Target path may be blocked by nearby resistance or conflicting structure.",
            "required_fields": ("structure_zone_nearest_resistance_distance_atr",),
            "predicate": lambda _item, taxonomy, reset, _path: "LOW_REMAINING_ROOM" in (reset.get("modifiers") or [])
            or "STRUCTURE_CONFLICT" in (reset.get("modifiers") or [])
            or taxonomy.get("room_to_resistance_bucket") == "LOW_ROOM",
        },
        {
            "cause_id": "WEAK_OR_MIXED_FLOW",
            "label": "Weak or mixed initiative flow",
            "expression": "flow_state_provisional != CONFIRMED",
            "definition": "Volume, taker buy, and OI are not all confirming long initiative.",
            "required_fields": ("volume_ratio_vs_lookback", "kline_taker_buy_ratio", "oi_change_pct"),
            "predicate": lambda _item, taxonomy, _reset, _path: taxonomy.get("flow_state_provisional") != "CONFIRMED",
        },
        {
            "cause_id": "CROWDED_LONG",
            "label": "Crowded long risk",
            "expression": "HIGH_CROWDING modifier OR high/extreme crowding bucket",
            "definition": "Funding, OI, or positioning are elevated enough to mark crowded-long risk.",
            "required_fields": (
                "funding_percentile_30d",
                "oi_zscore",
                "global_long_short_ratio",
                "top_trader_position_ratio",
            ),
            "predicate": lambda _item, taxonomy, reset, _path: "HIGH_CROWDING" in (reset.get("modifiers") or [])
            or taxonomy.get("crowding_bucket") in {"HIGH_CROWDING", "EXTREME_CROWDING"},
        },
        {
            "cause_id": "HIGH_COST_FILL",
            "label": "High projected cost / fill drag",
            "expression": "realistic_cost_r_estimate > 0.20 OR FILL_BAD",
            "definition": "Fee, spread, and slippage consume too much of the expected R.",
            "required_fields": ("realistic_cost_r_estimate", "realistic_fill_quality"),
            "predicate": lambda item, _taxonomy, reset, _path: "HIGH_PROJECTED_COST" in (reset.get("modifiers") or [])
            or str(item.get("realistic_fill_quality") or "") == "FILL_BAD"
            or _decimal_or_zero_snapshot(item.get("realistic_cost_r_estimate")) > Decimal("0.20"),
        },
        {
            "cause_id": "FIRST_HOUR_REVERSED",
            "label": "First hour reversed",
            "expression": "close_followthrough_1h_r < 0",
            "definition": "The first closed hour after entry fails to confirm the long path.",
            "required_fields": ("close_followthrough_1h_r",),
            "predicate": lambda item, _taxonomy, _reset, _path: (
                value := _decimal_or_none_snapshot(item.get("close_followthrough_1h_r"))
            )
            is not None
            and value < 0,
        },
        {
            "cause_id": "NO_ACCEPTANCE_MFE",
            "label": "No acceptance / tiny MFE",
            "expression": "SL path with MFE < +0.25R",
            "definition": "The signal never produced enough favorable movement to validate the entry.",
            "required_fields": ("mfe_r",),
            "predicate": lambda item, _taxonomy, _reset, path: item.get("result_status") == "SL_HIT"
            and path == "SL_NO_FOLLOW_THROUGH",
        },
        {
            "cause_id": "DEEP_FAIL_EXIT_PROBLEM",
            "label": "Deep fail / exit problem",
            "expression": "SL path after MFE >= +0.75R",
            "definition": "The trade moved meaningfully in favor but was not harvested before failing.",
            "required_fields": ("mfe_r",),
            "predicate": lambda item, _taxonomy, _reset, path: item.get("result_status") == "SL_HIT"
            and path in {"SL_AFTER_PARTIAL_PROFIT", "SL_AFTER_STRONG_PROFIT"},
        },
    )


def _mid_long_sl_path_cause_matrix(
    sl_items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    reset_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    specs = _mid_long_sl_cause_specs()
    for path_bucket in (
        "SL_NO_FOLLOW_THROUGH",
        "SL_WEAK_FOLLOW_THROUGH",
        "SL_AFTER_PARTIAL_PROFIT",
        "SL_AFTER_STRONG_PROFIT",
    ):
        path_items = [item for item in sl_items if _mid_long_path_bucket(item) == path_bucket]
        for spec in specs:
            count = 0
            for idx, item in enumerate(path_items):
                key = str(item.get("signal_id") or idx)
                taxonomy = taxonomy_by_id[key]
                reset = reset_by_id[key]
                if spec["predicate"](item, taxonomy, reset, path_bucket):
                    count += 1
            rows.append(
                {
                    "path_bucket": path_bucket,
                    "path_label": _mid_long_path_label(path_bucket),
                    "cause_id": spec["cause_id"],
                    "cause_label": spec["label"],
                    "count": count,
                    "path_count": len(path_items),
                    "path_share_pct": _pct_decimal(count, len(path_items)),
                }
            )
    rows.sort(
        key=lambda row: (
            _mid_long_path_priority(str(row.get("path_bucket") or "")),
            int(row.get("count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_sl_anatomy_summary(
    *,
    path_rows: list[dict[str, Any]],
    cause_rows: list[dict[str, Any]],
    total_sl_count: int,
    total_tp_count: int,
) -> dict[str, Any]:
    largest_path = max(path_rows, key=lambda row: int(row.get("sl_count") or 0), default=None)
    readable_causes = [row for row in cause_rows if int(row.get("matched_count") or 0) > 0]
    best_damage = max(
        readable_causes,
        key=lambda row: (
            _decimal_or_zero_snapshot(row.get("retained_realistic_total_r_delta_vs_baseline")),
            _decimal_or_zero_snapshot(row.get("matched_sl_capture_pct")),
        ),
        default=None,
    )
    instant_count = sum(int(row.get("sl_count") or 0) for row in path_rows if row.get("path_bucket") == "SL_NO_FOLLOW_THROUGH")
    deep_count = sum(
        int(row.get("sl_count") or 0)
        for row in path_rows
        if row.get("path_bucket") in {"SL_AFTER_PARTIAL_PROFIT", "SL_AFTER_STRONG_PROFIT"}
    )
    return {
        "read": _mid_long_sl_anatomy_read(best_damage=best_damage, instant_count=instant_count, deep_count=deep_count, total_sl_count=total_sl_count),
        "largest_sl_path": _mid_long_sl_summary_row(largest_path),
        "best_damage_tag": _mid_long_sl_summary_row(best_damage),
        "instant_sl_count": instant_count,
        "instant_sl_share_pct": _pct_decimal(instant_count, total_sl_count),
        "deep_fail_count": deep_count,
        "deep_fail_share_pct": _pct_decimal(deep_count, total_sl_count),
        "tp_count": total_tp_count,
        "sl_count": total_sl_count,
        "next_action": _mid_long_sl_next_action(best_damage=best_damage, instant_count=instant_count, deep_count=deep_count, total_sl_count=total_sl_count),
    }


def _mid_long_sl_summary_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row.get("cause_id") or row.get("path_bucket") or row.get("filter_id"),
        "label": row.get("label") or row.get("path_label"),
        "sample_count": row.get("sample_count") or row.get("matched_count"),
        "sl_count": row.get("sl_count") or row.get("matched_sl_count"),
        "tp_count": row.get("tp_count") or row.get("matched_tp_count"),
        "realistic_total_r_closed": row.get("realistic_total_r_closed") or row.get("retained_realistic_total_r_closed"),
        "retained_realistic_total_r_delta_vs_baseline": row.get("retained_realistic_total_r_delta_vs_baseline"),
        "read": row.get("read"),
    }


def _mid_long_sl_path_read(path_bucket: str, path_items: list[dict[str, Any]], *, min_sample: int) -> str:
    if len(path_items) < min_sample:
        return "SAMPLE_SMALL"
    if path_bucket == "SL_NO_FOLLOW_THROUGH":
        return "ENTRY_OR_DIRECTION_DAMAGE"
    if path_bucket == "SL_WEAK_FOLLOW_THROUGH":
        return "WEAK_ACCEPTANCE_DAMAGE"
    if path_bucket in {"SL_AFTER_PARTIAL_PROFIT", "SL_AFTER_STRONG_PROFIT"}:
        return "EXIT_OR_HARVEST_DAMAGE"
    return "SL_PATH_DIAGNOSTIC"


def _mid_long_sl_cause_read(row: dict[str, Any], *, min_sample: int) -> str:
    matched = int(row.get("matched_count") or 0)
    if matched < min_sample:
        return "SAMPLE_SMALL"
    sl_capture = _decimal_or_zero_snapshot(row.get("matched_sl_capture_pct"))
    tp_sacrifice = _decimal_or_zero_snapshot(row.get("matched_tp_sacrifice_pct"))
    total_delta = _decimal_or_zero_snapshot(row.get("retained_realistic_total_r_delta_vs_baseline"))
    if sl_capture >= tp_sacrifice + Decimal("10") and total_delta > Decimal("5"):
        return "DAMAGE_TAG_CANDIDATE"
    if tp_sacrifice >= sl_capture:
        return "CUTS_TOO_MUCH_TP"
    if total_delta > 0:
        return "REDUCES_DAMAGE_BUT_WEAK"
    return "NO_CLEAR_FILTER"


def _mid_long_sl_cause_priority(read: str) -> int:
    return {
        "DAMAGE_TAG_CANDIDATE": 5,
        "REDUCES_DAMAGE_BUT_WEAK": 4,
        "NO_CLEAR_FILTER": 3,
        "CUTS_TOO_MUCH_TP": 2,
        "SAMPLE_SMALL": 1,
    }.get(read, 0)


def _mid_long_sl_anatomy_read(
    *,
    best_damage: dict[str, Any] | None,
    instant_count: int,
    deep_count: int,
    total_sl_count: int,
) -> str:
    if total_sl_count <= 0:
        return "NO_SL_SAMPLE"
    if best_damage and best_damage.get("read") == "DAMAGE_TAG_CANDIDATE":
        return "HAS_DAMAGE_TAG_CANDIDATE"
    instant_share = Decimal(instant_count) / Decimal(total_sl_count)
    deep_share = Decimal(deep_count) / Decimal(total_sl_count)
    if instant_share >= Decimal("0.35"):
        return "ENTRY_DEFINITION_DAMAGE_DOMINANT"
    if deep_share >= Decimal("0.25"):
        return "EXIT_RESEARCH_REQUIRED"
    return "SL_CAUSES_MIXED"


def _mid_long_sl_next_action(
    *,
    best_damage: dict[str, Any] | None,
    instant_count: int,
    deep_count: int,
    total_sl_count: int,
) -> str:
    read = _mid_long_sl_anatomy_read(
        best_damage=best_damage,
        instant_count=instant_count,
        deep_count=deep_count,
        total_sl_count=total_sl_count,
    )
    if read == "HAS_DAMAGE_TAG_CANDIDATE" and best_damage:
        return f"Validate {best_damage.get('cause_id')} chronologically before any shadow rule."
    if read == "ENTRY_DEFINITION_DAMAGE_DOMINANT":
        return "Focus on pre-entry definition: structure, flow, crowding, and room filters before dynamic exit."
    if read == "EXIT_RESEARCH_REQUIRED":
        return "Study harvest/protection logic only for rows that first moved meaningfully in favor."
    return "Compare cause overlap and wait for a cleaner candidate before changing MID_LONG."


def _mid_long_decimal_ratio(numerator: Any, denominator: Any) -> Decimal | None:
    parsed_num = _decimal_or_none_snapshot(numerator)
    parsed_den = _decimal_or_none_snapshot(denominator)
    if parsed_num is None or parsed_den is None or parsed_den == 0:
        return None
    return parsed_num / parsed_den


MID_LONG_FIRST_HOUR_STATE_DEFINITIONS: dict[str, str] = {
    "FIRST_HOUR_CONFIRMED": "First closed hour finishes at least +0.25R in the intended long direction.",
    "FIRST_HOUR_STALLED": "First closed hour is between -0.10R and +0.25R; direction has not confirmed or failed clearly.",
    "FIRST_HOUR_PRICE_REVERSED": "First closed hour closes below -0.10R but not deeply enough to mark structure-failed proxy.",
    "FIRST_HOUR_STRUCTURE_FAILED": "Structured setup closes at or below -0.50R in the first hour. This is a proxy, not a replayed zone break.",
    "FIRST_HOUR_UNAVAILABLE": "First-hour follow-through field is missing from this snapshot.",
}


def _mid_long_first_hour_response_audit(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    reset_by_id = {
        str(item.get("signal_id") or idx): _mid_long_reset_state(
            item,
            taxonomy_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    state_by_id = {
        str(item.get("signal_id") or idx): _mid_long_first_hour_state(
            item,
            reset_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    state_rows = _mid_long_first_hour_state_rows(
        items,
        state_by_id=state_by_id,
        reset_by_id=reset_by_id,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    family_state_rows = _mid_long_first_hour_family_state_rows(
        items,
        state_by_id=state_by_id,
        reset_by_id=reset_by_id,
        taxonomy_by_id=taxonomy_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    checkpoint_rows = _mid_long_first_hour_checkpoint_rows(items)
    sample_rows = _mid_long_first_hour_sample_rows(
        items,
        state_by_id=state_by_id,
        reset_by_id=reset_by_id,
        taxonomy_by_id=taxonomy_by_id,
        limit_per_state=3,
    )
    summary = _mid_long_first_hour_summary(
        state_rows=state_rows,
        checkpoint_rows=checkpoint_rows,
        min_sample=min_sample,
    )
    return {
        "scope": "MID_LONG 1h First-Hour Response Audit",
        "method": (
            "Diagnostic-only first response study. The 60m checkpoint uses close_followthrough_1h_r "
            "from paper-live futures candles; 15m/30m only appear when those fields are logged."
        ),
        "state_model": "FIRST_HOUR_RESPONSE_PROXY_V1",
        "thresholds": {
            "confirmed_min_r": Decimal("0.25"),
            "price_reversed_below_r": Decimal("-0.10"),
            "structure_failed_proxy_below_r": Decimal("-0.50"),
        },
        "state_definitions": MID_LONG_FIRST_HOUR_STATE_DEFINITIONS,
        "total_signal_count": len(items),
        "state_rows": state_rows,
        "family_state_rows": family_state_rows,
        "checkpoint_rows": checkpoint_rows,
        "sample_rows": sample_rows,
        "summary": summary,
        "guardrails": [
            "This audit does not change Signal Factory, scanner, TP/SL, timeout, or execution.",
            "FIRST_HOUR_STRUCTURE_FAILED is a proxy from first-hour close R and setup family, not a candle-by-candle zone invalidation.",
            "Post-entry response state must not be used as a live entry gate without a separate delayed-entry simulation.",
            "15m/30m checkpoint rows are availability checks unless those checkpoint fields are explicitly logged.",
        ],
    }


def _mid_long_first_hour_state(item: dict[str, Any], reset: dict[str, Any]) -> str:
    followthrough = _decimal_or_none_snapshot(item.get("close_followthrough_1h_r"))
    if followthrough is None:
        return "FIRST_HOUR_UNAVAILABLE"
    primary = str(reset.get("primary_family") or "")
    if followthrough <= Decimal("-0.50") and primary != "UNCLASSIFIED_MID_LONG":
        return "FIRST_HOUR_STRUCTURE_FAILED"
    if followthrough < Decimal("-0.10"):
        return "FIRST_HOUR_PRICE_REVERSED"
    if followthrough >= Decimal("0.25"):
        return "FIRST_HOUR_CONFIRMED"
    return "FIRST_HOUR_STALLED"


def _mid_long_first_hour_state_rows(
    items: list[dict[str, Any]],
    *,
    state_by_id: dict[str, str],
    reset_by_id: dict[str, dict[str, Any]],
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {state: [] for state in MID_LONG_FIRST_HOUR_STATE_DEFINITIONS}
    for idx, item in enumerate(items):
        key = str(item.get("signal_id") or idx)
        grouped.setdefault(state_by_id.get(key, "FIRST_HOUR_UNAVAILABLE"), []).append(item)

    rows: list[dict[str, Any]] = []
    for state, state_items in grouped.items():
        row = _mid_long_perf_row(
            f"FIRST_HOUR:{state}",
            state,
            f"first_hour_state == {state}",
            state_items,
            baseline=baseline,
            required_fields=("close_followthrough_1h_r",),
            missing_data_count=sum(1 for item in state_items if _decimal_or_none_snapshot(item.get("close_followthrough_1h_r")) is None),
            min_sample=min_sample,
        )
        row.update(
            {
                "state": state,
                "definition": MID_LONG_FIRST_HOUR_STATE_DEFINITIONS[state],
                "available_60m_count": len(_mid_long_item_decimal_values(state_items, "close_followthrough_1h_r")),
                "available_60m_pct": _pct_decimal(
                    len(_mid_long_item_decimal_values(state_items, "close_followthrough_1h_r")),
                    len(state_items),
                ),
                "median_close_followthrough_1h_r": _median_decimal_snapshot(
                    _mid_long_item_decimal_values(state_items, "close_followthrough_1h_r")
                ),
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_decimal_values(state_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_decimal_values(state_items, "mae_r")),
                "median_wick_decay_r": _median_decimal_snapshot(_mid_long_item_decimal_values(state_items, "wick_to_close_decay_r")),
                "path_mix": _mid_long_path_mix(state_items),
                "primary_family_mix": _mid_long_reset_mix(state_items, reset_by_id=reset_by_id, field="primary_family"),
                "modifier_mix": _mid_long_reset_modifier_mix(state_items, reset_by_id=reset_by_id),
                "flow_mix": _mid_long_taxonomy_mix(
                    state_items,
                    taxonomy_by_id=taxonomy_by_id,
                    taxonomy_key="flow_state_provisional",
                ),
                "room_mix": _mid_long_taxonomy_mix(
                    state_items,
                    taxonomy_by_id=taxonomy_by_id,
                    taxonomy_key="room_to_resistance_bucket",
                ),
                "read": _mid_long_first_hour_state_read(state, state_items, min_sample=min_sample),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _mid_long_first_hour_state_priority(str(row.get("state") or "")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_first_hour_family_state_rows(
    items: list[dict[str, Any]],
    *,
    state_by_id: dict[str, str],
    reset_by_id: dict[str, dict[str, Any]],
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        key = str(item.get("signal_id") or idx)
        reset = reset_by_id[key]
        grouped[(str(reset.get("primary_family") or "UNKNOWN"), state_by_id.get(key, "FIRST_HOUR_UNAVAILABLE"))].append(item)

    rows: list[dict[str, Any]] = []
    for (family, state), state_items in grouped.items():
        row = _mid_long_perf_row(
            f"FIRST_HOUR_FAMILY:{family}:{state}",
            f"{family} x {state}",
            f"primary_family == {family} AND first_hour_state == {state}",
            state_items,
            baseline=baseline,
            required_fields=("close_followthrough_1h_r",),
            missing_data_count=sum(1 for item in state_items if _decimal_or_none_snapshot(item.get("close_followthrough_1h_r")) is None),
            min_sample=min_sample,
        )
        row.update(
            {
                "primary_family": family,
                "state": state,
                "is_readable": int(row.get("closed_count") or 0) >= min_sample,
                "median_close_followthrough_1h_r": _median_decimal_snapshot(
                    _mid_long_item_decimal_values(state_items, "close_followthrough_1h_r")
                ),
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_decimal_values(state_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_decimal_values(state_items, "mae_r")),
                "path_mix": _mid_long_path_mix(state_items),
                "modifier_mix": _mid_long_reset_modifier_mix(state_items, reset_by_id=reset_by_id),
                "flow_mix": _mid_long_taxonomy_mix(
                    state_items,
                    taxonomy_by_id=taxonomy_by_id,
                    taxonomy_key="flow_state_provisional",
                ),
                "read": _mid_long_first_hour_family_state_read(family, state, state_items, min_sample=min_sample),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            bool(row.get("is_readable")),
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows[:30]


def _mid_long_first_hour_checkpoint_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checkpoint_specs: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("15m", "First 15m close response", ("close_followthrough_15m_r", "checkpoint_15m_close_r", "first_15m_close_r")),
        ("30m", "First 30m close response", ("close_followthrough_30m_r", "checkpoint_30m_close_r", "first_30m_close_r")),
        ("60m", "First 60m / 1h close response", ("close_followthrough_1h_r", "checkpoint_60m_close_r", "first_hour_close_r")),
    )
    rows: list[dict[str, Any]] = []
    for checkpoint, label, fields in checkpoint_specs:
        field_values: list[Decimal] = []
        available_by_field: dict[str, int] = {}
        for field in fields:
            values = _mid_long_item_decimal_values(items, field)
            available_by_field[field] = len(values)
            field_values.extend(values)
        available_count = max(available_by_field.values(), default=0)
        rows.append(
            {
                "checkpoint": checkpoint,
                "label": label,
                "candidate_fields": list(fields),
                "available_by_field": available_by_field,
                "available_count": available_count,
                "missing_count": max(0, len(items) - available_count),
                "available_pct": _pct_decimal(available_count, len(items)),
                "median_close_r": _median_decimal_snapshot(field_values),
                "q25_close_r": _percentile_decimal_snapshot(field_values, Decimal("0.25")),
                "q75_close_r": _percentile_decimal_snapshot(field_values, Decimal("0.75")),
                "read": "CHECKPOINT_LOGGED" if available_count > 0 else "CHECKPOINT_NOT_LOGGED_YET",
            }
        )
    return rows


def _mid_long_first_hour_sample_rows(
    items: list[dict[str, Any]],
    *,
    state_by_id: dict[str, str],
    reset_by_id: dict[str, dict[str, Any]],
    taxonomy_by_id: dict[str, dict[str, Any]],
    limit_per_state: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        key = str(item.get("signal_id") or idx)
        grouped[state_by_id.get(key, "FIRST_HOUR_UNAVAILABLE")].append(item)

    rows: list[dict[str, Any]] = []
    for state in MID_LONG_FIRST_HOUR_STATE_DEFINITIONS:
        state_items = sorted(
            grouped.get(state, []),
            key=lambda item: str(item.get("signal_timestamp") or item.get("window_close_time") or ""),
            reverse=True,
        )[:limit_per_state]
        for item in state_items:
            key = str(item.get("signal_id") or items.index(item))
            reset = reset_by_id.get(key, {})
            taxonomy = taxonomy_by_id.get(key, {})
            rows.append(
                {
                    "signal_id": item.get("signal_id"),
                    "symbol": item.get("symbol"),
                    "signal_timestamp": item.get("signal_timestamp"),
                    "timeframe": item.get("timeframe"),
                    "result_status": item.get("result_status"),
                    "state": state,
                    "primary_family": reset.get("primary_family"),
                    "path_bucket": _mid_long_path_bucket(item),
                    "path_label_050": _mid_long_path_label_050(item),
                    "flow_state": taxonomy.get("flow_state_provisional"),
                    "room_bucket": taxonomy.get("room_to_resistance_bucket"),
                    "close_followthrough_1h_r": item.get("close_followthrough_1h_r"),
                    "mfe_r": item.get("mfe_r"),
                    "mae_r": item.get("mae_r"),
                    "realistic_realized_r": item.get("realistic_realized_r"),
                    "price_at_signal": item.get("price_at_signal"),
                    "sl_ref": item.get("sl_ref"),
                    "tp_ref": item.get("tp_ref"),
                }
            )
    return rows


def _mid_long_first_hour_summary(
    *,
    state_rows: list[dict[str, Any]],
    checkpoint_rows: list[dict[str, Any]],
    min_sample: int,
) -> dict[str, Any]:
    available_60 = next((row for row in checkpoint_rows if row.get("checkpoint") == "60m"), None)
    dominant = max(state_rows, key=lambda row: int(row.get("closed_count") or 0), default=None)
    confirmed = next((row for row in state_rows if row.get("state") == "FIRST_HOUR_CONFIRMED"), None)
    reversed_row = next((row for row in state_rows if row.get("state") == "FIRST_HOUR_PRICE_REVERSED"), None)
    structure_failed = next((row for row in state_rows if row.get("state") == "FIRST_HOUR_STRUCTURE_FAILED"), None)
    unavailable = next((row for row in state_rows if row.get("state") == "FIRST_HOUR_UNAVAILABLE"), None)
    read = _mid_long_first_hour_audit_read(
        available_60=available_60,
        dominant=dominant,
        confirmed=confirmed,
        reversed_row=reversed_row,
        structure_failed=structure_failed,
        min_sample=min_sample,
    )
    return {
        "read": read,
        "dominant_state": dominant.get("state") if dominant else None,
        "dominant_state_count": dominant.get("closed_count") if dominant else 0,
        "confirmed_count": confirmed.get("closed_count") if confirmed else 0,
        "stalled_count": next((row.get("closed_count") for row in state_rows if row.get("state") == "FIRST_HOUR_STALLED"), 0),
        "price_reversed_count": reversed_row.get("closed_count") if reversed_row else 0,
        "structure_failed_count": structure_failed.get("closed_count") if structure_failed else 0,
        "unavailable_count": unavailable.get("closed_count") if unavailable else 0,
        "latest_logged_checkpoint": "60m" if available_60 and int(available_60.get("available_count") or 0) > 0 else None,
        "next_action": _mid_long_first_hour_next_action(read),
    }


def _mid_long_first_hour_state_read(state: str, state_items: list[dict[str, Any]], *, min_sample: int) -> str:
    if len(state_items) < min_sample:
        return "SAMPLE_SMALL"
    perf = aggregate_signal_performance_items(state_items)
    total_r = _decimal_or_zero_snapshot(perf.get("realistic_total_r_closed"))
    sl_share = _sl_share_snapshot(perf)
    if state == "FIRST_HOUR_CONFIRMED" and total_r > 0:
        return "CONFIRMED_RESPONSE_CONSTRUCTIVE"
    if state in {"FIRST_HOUR_PRICE_REVERSED", "FIRST_HOUR_STRUCTURE_FAILED"} and _decimal_or_zero_snapshot(sl_share) >= Decimal("60"):
        return "EARLY_DAMAGE_CLUSTER"
    if state == "FIRST_HOUR_UNAVAILABLE":
        return "DATA_NOT_LOGGED"
    return "MIXED_RESPONSE"


def _mid_long_first_hour_family_state_read(family: str, state: str, state_items: list[dict[str, Any]], *, min_sample: int) -> str:
    if len(state_items) < min_sample:
        return "SAMPLE_SMALL"
    perf = aggregate_signal_performance_items(state_items)
    total_r = _decimal_or_zero_snapshot(perf.get("realistic_total_r_closed"))
    if state == "FIRST_HOUR_CONFIRMED" and total_r > 0:
        return "FAMILY_CONFIRMS_WELL"
    if state in {"FIRST_HOUR_PRICE_REVERSED", "FIRST_HOUR_STRUCTURE_FAILED"} and total_r < 0:
        return "FAMILY_EARLY_DAMAGE"
    if family == "UNCLASSIFIED_MID_LONG":
        return "FAMILY_UNCLASSIFIED"
    return "FAMILY_MIXED"


def _mid_long_first_hour_audit_read(
    *,
    available_60: dict[str, Any] | None,
    dominant: dict[str, Any] | None,
    confirmed: dict[str, Any] | None,
    reversed_row: dict[str, Any] | None,
    structure_failed: dict[str, Any] | None,
    min_sample: int,
) -> str:
    if not available_60 or int(available_60.get("available_count") or 0) < min_sample:
        return "FIRST_HOUR_DATA_NOT_READY"
    damage_count = int((reversed_row or {}).get("closed_count") or 0) + int((structure_failed or {}).get("closed_count") or 0)
    confirmed_count = int((confirmed or {}).get("closed_count") or 0)
    dominant_state = str((dominant or {}).get("state") or "")
    if damage_count >= confirmed_count and damage_count >= min_sample:
        return "FIRST_HOUR_DAMAGE_DOMINANT"
    if dominant_state == "FIRST_HOUR_CONFIRMED":
        return "FIRST_HOUR_CONFIRMATION_PROMISING"
    return "FIRST_HOUR_RESPONSE_MIXED"


def _mid_long_first_hour_next_action(read: str) -> str:
    if read == "FIRST_HOUR_DAMAGE_DOMINANT":
        return "Run delayed-entry and early-failure-exit simulations; do not convert this post-entry state into a live gate directly."
    if read == "FIRST_HOUR_CONFIRMATION_PROMISING":
        return "Compare confirmed vs stalled/reversed cohorts chronologically before proposing any V2.1 shadow rule."
    if read == "FIRST_HOUR_DATA_NOT_READY":
        return "Keep logging 1h follow-through and add explicit 15m/30m checkpoints before testing finer timing."
    return "Use family x first-hour rows to decide whether confirmation or exit research is the next cleaner branch."


def _mid_long_first_hour_state_priority(state: str) -> int:
    return {
        "FIRST_HOUR_STRUCTURE_FAILED": 5,
        "FIRST_HOUR_PRICE_REVERSED": 4,
        "FIRST_HOUR_CONFIRMED": 3,
        "FIRST_HOUR_STALLED": 2,
        "FIRST_HOUR_UNAVAILABLE": 1,
    }.get(state, 0)


def _mid_long_first_hour_action_simulation(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    reset_by_id = {
        str(item.get("signal_id") or idx): _mid_long_reset_state(
            item,
            taxonomy_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    state_by_id = {
        str(item.get("signal_id") or idx): _mid_long_first_hour_state(
            item,
            reset_by_id[str(item.get("signal_id") or idx)],
        )
        for idx, item in enumerate(items)
    }
    delayed_rows = [
        _mid_long_first_hour_delayed_entry_row(
            "DELAY_KEEP_CONFIRMED_1H",
            "Enter only after confirmed 1h response",
            "Keep rows where first_hour_state == FIRST_HOUR_CONFIRMED; skipped rows are diagnostic damage avoided.",
            items,
            state_by_id=state_by_id,
            keep_states={"FIRST_HOUR_CONFIRMED"},
            baseline=baseline,
            min_sample=min_sample,
        ),
        _mid_long_first_hour_delayed_entry_row(
            "DELAY_SKIP_EARLY_DAMAGE_1H",
            "Skip first-hour reversed/failed rows",
            "Keep confirmed + stalled rows, skip FIRST_HOUR_PRICE_REVERSED and FIRST_HOUR_STRUCTURE_FAILED.",
            items,
            state_by_id=state_by_id,
            keep_states={"FIRST_HOUR_CONFIRMED", "FIRST_HOUR_STALLED"},
            baseline=baseline,
            min_sample=min_sample,
        ),
        _mid_long_first_hour_delayed_entry_row(
            "DELAY_REQUIRE_LOGGED_1H_NON_DAMAGE",
            "Require logged non-damage 1h response",
            "Keep confirmed + stalled rows and exclude unavailable first-hour rows from the proxy.",
            items,
            state_by_id=state_by_id,
            keep_states={"FIRST_HOUR_CONFIRMED", "FIRST_HOUR_STALLED"},
            exclude_states={"FIRST_HOUR_UNAVAILABLE"},
            baseline=baseline,
            min_sample=min_sample,
        ),
    ]
    early_exit_rows = [
        _mid_long_first_hour_early_exit_row(
            "EXIT_PRICE_REVERSED_AT_1H_CLOSE_PROXY",
            "Exit first-hour price reversal",
            "Replace final R with close_followthrough_1h_r only for FIRST_HOUR_PRICE_REVERSED rows.",
            items,
            state_by_id=state_by_id,
            action_states={"FIRST_HOUR_PRICE_REVERSED"},
            baseline=baseline,
            min_sample=min_sample,
        ),
        _mid_long_first_hour_early_exit_row(
            "EXIT_EARLY_DAMAGE_AT_1H_CLOSE_PROXY",
            "Exit first-hour reversal or structure fail",
            "Replace final R with close_followthrough_1h_r for FIRST_HOUR_PRICE_REVERSED and FIRST_HOUR_STRUCTURE_FAILED rows.",
            items,
            state_by_id=state_by_id,
            action_states={"FIRST_HOUR_PRICE_REVERSED", "FIRST_HOUR_STRUCTURE_FAILED"},
            baseline=baseline,
            min_sample=min_sample,
        ),
        _mid_long_first_hour_early_exit_row(
            "EXIT_NON_CONFIRMED_AT_1H_CLOSE_PROXY",
            "Exit any non-confirmed logged 1h response",
            "Replace final R with close_followthrough_1h_r for stalled, reversed, and structure-failed rows.",
            items,
            state_by_id=state_by_id,
            action_states={"FIRST_HOUR_STALLED", "FIRST_HOUR_PRICE_REVERSED", "FIRST_HOUR_STRUCTURE_FAILED"},
            baseline=baseline,
            min_sample=min_sample,
        ),
    ]
    summary = _mid_long_first_hour_action_summary(
        delayed_rows=delayed_rows,
        early_exit_rows=early_exit_rows,
        baseline=baseline,
        min_sample=min_sample,
    )
    return {
        "scope": "MID_LONG 1h First-Hour Action Simulation",
        "method": (
            "Read-only proxy simulation. Delayed-entry rows are retained-cohort tests and do not reprice entry/SL/TP. "
            "Early-exit rows replace final R with the logged 1h close-followthrough R for action rows only."
        ),
        "model": "FIRST_HOUR_ACTION_PROXY_V1",
        "source_state_model": "FIRST_HOUR_RESPONSE_PROXY_V1",
        "baseline_realistic_total_r_closed": baseline.get("realistic_total_r_closed"),
        "baseline_realistic_avg_r_closed": baseline.get("realistic_avg_r_closed"),
        "baseline_max_realistic_drawdown_r": baseline.get("max_realistic_drawdown_r"),
        "delayed_entry_rows": delayed_rows,
        "early_exit_rows": early_exit_rows,
        "summary": summary,
        "guardrails": [
            "This does not change Signal Factory, scanner, TP/SL, timeout, or execution.",
            "Delayed-entry proxy does not reprice the later entry; it only tells whether confirmation is worth exact replay.",
            "Early-exit proxy uses 1h close R, not intrabar order-book execution.",
            "Any promising row must be rerun with candle-by-candle replay before becoming a shadow rule.",
        ],
    }


def _mid_long_first_hour_delayed_entry_row(
    filter_id: str,
    label: str,
    expression: str,
    items: list[dict[str, Any]],
    *,
    state_by_id: dict[str, str],
    keep_states: set[str],
    baseline: dict[str, Any],
    min_sample: int,
    exclude_states: set[str] | None = None,
) -> dict[str, Any]:
    excluded = exclude_states or set()
    retained: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    unavailable_excluded: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        state = state_by_id.get(str(item.get("signal_id") or idx), "FIRST_HOUR_UNAVAILABLE")
        if state in keep_states:
            retained.append(item)
        elif state in excluded:
            unavailable_excluded.append(item)
        else:
            skipped.append(item)

    row = _mid_long_perf_row(
        filter_id,
        label,
        expression,
        retained,
        baseline=baseline,
        required_fields=("close_followthrough_1h_r",),
        missing_data_count=sum(1 for item in retained if _decimal_or_none_snapshot(item.get("close_followthrough_1h_r")) is None),
        min_sample=min_sample,
    )
    skipped_perf = aggregate_signal_performance_items(skipped)
    row.update(
        {
            "simulation_family": "DELAYED_ENTRY_PROXY",
            "source_count": len(items),
            "retained_count": len(retained),
            "skipped_count": len(skipped),
            "excluded_unavailable_count": len(unavailable_excluded),
            "retained_state_mix": _mid_long_first_hour_state_mix(retained, state_by_id=state_by_id, all_items=items),
            "skipped_state_mix": _mid_long_first_hour_state_mix(skipped, state_by_id=state_by_id, all_items=items),
            "skipped_tp_count": skipped_perf.get("tp_count"),
            "skipped_sl_count": skipped_perf.get("sl_count"),
            "skipped_realistic_total_r_closed": skipped_perf.get("realistic_total_r_closed"),
            "skipped_realistic_avg_r_closed": skipped_perf.get("realistic_avg_r_closed"),
        }
    )
    row["read"] = _mid_long_first_hour_delayed_read(row, skipped_perf, min_sample=min_sample)
    return row


def _mid_long_first_hour_early_exit_row(
    filter_id: str,
    label: str,
    expression: str,
    items: list[dict[str, Any]],
    *,
    state_by_id: dict[str, str],
    action_states: set[str],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    scored: list[tuple[dict[str, Any], Decimal, Decimal, bool]] = []
    action_items: list[dict[str, Any]] = []
    missing_followthrough_count = 0
    for idx, item in enumerate(items):
        if item.get("result_status") not in COMPLETED_OUTCOMES:
            continue
        original = _decimal_or_none_snapshot(item.get("realistic_realized_r"))
        if original is None:
            continue
        state = state_by_id.get(str(item.get("signal_id") or idx), "FIRST_HOUR_UNAVAILABLE")
        followthrough = _decimal_or_none_snapshot(item.get("close_followthrough_1h_r"))
        should_exit = state in action_states
        if should_exit and followthrough is None:
            missing_followthrough_count += 1
        simulated = followthrough if should_exit and followthrough is not None else original
        scored.append((item, original, simulated, bool(should_exit and followthrough is not None)))
        if should_exit and followthrough is not None:
            action_items.append(item)

    proxy_values = [simulated for _, _, simulated, _ in scored]
    original_values = [original for _, original, _, _ in scored]
    action_original_values = [original for _, original, _, acted in scored if acted]
    action_simulated_values = [simulated for _, _, simulated, acted in scored if acted]
    proxy_total = sum(proxy_values, Decimal("0"))
    original_total = sum(original_values, Decimal("0"))
    r_saved = sum((simulated - original for _, original, simulated, acted in scored if acted and simulated > original), Decimal("0"))
    r_sacrificed = sum((original - simulated for _, original, simulated, acted in scored if acted and original > simulated), Decimal("0"))
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item, _, _, _ in scored)
    top_symbol, top_symbol_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    original_action_tp = sum(1 for item in action_items if item.get("result_status") == "TP_HIT")
    original_action_sl = sum(1 for item in action_items if item.get("result_status") == "SL_HIT")
    original_action_both = sum(1 for item in action_items if item.get("result_status") == "BOTH_HIT_SAME_CANDLE")
    row = {
        "filter_id": filter_id,
        "label": label,
        "expression": expression,
        "simulation_family": "EARLY_EXIT_PROXY",
        "required_fields": ["close_followthrough_1h_r"],
        "source_count": len(items),
        "sample_count": len(scored),
        "closed_count": len(scored),
        "action_count": len(action_items),
        "unchanged_count": max(0, len(scored) - len(action_items)),
        "missing_followthrough_count": missing_followthrough_count,
        "original_action_tp_count": original_action_tp,
        "original_action_sl_count": original_action_sl,
        "original_action_both_count": original_action_both,
        "sl_reduced_count": sum(1 for item, original, simulated, acted in scored if acted and item.get("result_status") == "SL_HIT" and simulated > original),
        "tp_cut_count": sum(1 for item, original, simulated, acted in scored if acted and item.get("result_status") == "TP_HIT" and simulated < original),
        "proxy_positive_count": sum(1 for value in proxy_values if value > 0),
        "proxy_negative_count": sum(1 for value in proxy_values if value < 0),
        "proxy_flat_count": sum(1 for value in proxy_values if value == 0),
        "original_realistic_total_r_closed": original_total,
        "proxy_realistic_total_r_closed": proxy_total,
        "proxy_realistic_avg_r_closed": proxy_total / Decimal(len(proxy_values)) if proxy_values else None,
        "proxy_median_realistic_r_closed": _median_decimal_snapshot(proxy_values),
        "action_original_total_r": sum(action_original_values, Decimal("0")),
        "action_proxy_total_r": sum(action_simulated_values, Decimal("0")),
        "r_saved": r_saved,
        "r_sacrificed": r_sacrificed,
        "net_saved_r": r_saved - r_sacrificed,
        "proxy_realistic_total_r_delta_vs_baseline": _decimal_delta_snapshot(proxy_total, baseline.get("realistic_total_r_closed")),
        "proxy_realistic_avg_r_delta_vs_baseline": _decimal_delta_snapshot(
            proxy_total / Decimal(len(proxy_values)) if proxy_values else None,
            baseline.get("realistic_avg_r_closed"),
        ),
        "proxy_max_drawdown_r": _mid_long_simulated_drawdown(scored)["max_drawdown_r"],
        "proxy_max_drawdown_delta_vs_baseline": _decimal_delta_snapshot(
            _mid_long_simulated_drawdown(scored)["max_drawdown_r"],
            baseline.get("max_realistic_drawdown_r"),
        ),
        "median_original_r": _median_decimal_snapshot(original_values),
        "median_proxy_r": _median_decimal_snapshot(proxy_values),
        "median_action_original_r": _median_decimal_snapshot(action_original_values),
        "median_action_proxy_r": _median_decimal_snapshot(action_simulated_values),
        "action_state_mix": _mid_long_first_hour_state_mix(action_items, state_by_id=state_by_id, all_items=items),
        "top_symbol": top_symbol,
        "top_symbol_count": top_symbol_count,
        "top_symbol_share_pct": _pct_decimal(top_symbol_count, len(scored)) if scored else None,
    }
    row["read"] = _mid_long_first_hour_early_exit_read(row, min_sample=min_sample)
    return row


def _mid_long_first_hour_state_mix(
    selected: list[dict[str, Any]],
    *,
    state_by_id: dict[str, str],
    all_items: list[dict[str, Any]],
) -> dict[str, int]:
    index_by_identity = {id(item): idx for idx, item in enumerate(all_items)}
    counter: Counter[str] = Counter()
    for item in selected:
        idx = index_by_identity.get(id(item), 0)
        counter[state_by_id.get(str(item.get("signal_id") or idx), "FIRST_HOUR_UNAVAILABLE")] += 1
    return dict(counter)


def _mid_long_simulated_drawdown(scored: list[tuple[dict[str, Any], Decimal, Decimal, bool]]) -> dict[str, Decimal | int]:
    ordered = sorted(
        scored,
        key=lambda row: (
            str(row[0].get("result_time_utc") or row[0].get("signal_timestamp") or ""),
            str(row[0].get("symbol") or ""),
        ),
    )
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for _, _, simulated, _ in ordered:
        cumulative += simulated
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return {
        "closed_count": len(ordered),
        "total_r_closed": cumulative,
        "peak_r": peak,
        "max_drawdown_r": max_drawdown,
        "current_drawdown_r": cumulative - peak,
    }


def _mid_long_first_hour_delayed_read(row: dict[str, Any], skipped_perf: dict[str, Any], *, min_sample: int) -> str:
    if int(row.get("retained_count") or 0) < min_sample:
        return "DELAYED_ENTRY_SAMPLE_SMALL"
    retained_total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    retained_avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    skipped_total = _decimal_or_zero_snapshot(skipped_perf.get("realistic_total_r_closed"))
    if retained_total > 0 and retained_avg_delta > Decimal("0.10") and skipped_total < 0:
        return "DELAYED_ENTRY_PROXY_PROMISING"
    if retained_avg_delta > 0 and skipped_total < 0:
        return "DELAYED_ENTRY_DAMAGE_REDUCED"
    if retained_total > 0:
        return "DELAYED_ENTRY_POSITIVE_BUT_NOT_CLEAN"
    return "DELAYED_ENTRY_NOT_SUPPORTED"


def _mid_long_first_hour_early_exit_read(row: dict[str, Any], *, min_sample: int) -> str:
    if int(row.get("action_count") or 0) < min_sample:
        return "EARLY_EXIT_SAMPLE_SMALL"
    net_saved = _decimal_or_zero_snapshot(row.get("net_saved_r"))
    delta = _decimal_or_zero_snapshot(row.get("proxy_realistic_total_r_delta_vs_baseline"))
    tp_cut = int(row.get("tp_cut_count") or 0)
    sl_reduced = int(row.get("sl_reduced_count") or 0)
    if net_saved > Decimal("10") and delta > 0 and sl_reduced > tp_cut:
        return "EARLY_EXIT_PROXY_PROMISING"
    if net_saved > 0 and sl_reduced >= tp_cut:
        return "EARLY_EXIT_DAMAGE_REDUCED"
    if net_saved > 0:
        return "EARLY_EXIT_SAVES_R_BUT_CUTS_TP"
    return "EARLY_EXIT_NOT_SUPPORTED"


def _mid_long_first_hour_action_summary(
    *,
    delayed_rows: list[dict[str, Any]],
    early_exit_rows: list[dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    delayed_candidates = [row for row in delayed_rows if int(row.get("retained_count") or 0) >= min_sample]
    exit_candidates = [row for row in early_exit_rows if int(row.get("action_count") or 0) >= min_sample]
    best_delayed = max(
        delayed_candidates,
        key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_total_r_delta_vs_baseline")),
        default=None,
    )
    best_exit = max(
        exit_candidates,
        key=lambda row: _decimal_or_zero_snapshot(row.get("proxy_realistic_total_r_delta_vs_baseline")),
        default=None,
    )
    best_delayed_delta = _decimal_or_zero_snapshot((best_delayed or {}).get("realistic_total_r_delta_vs_baseline"))
    best_exit_delta = _decimal_or_zero_snapshot((best_exit or {}).get("proxy_realistic_total_r_delta_vs_baseline"))
    if best_exit and str(best_exit.get("read")) in {"EARLY_EXIT_PROXY_PROMISING", "EARLY_EXIT_DAMAGE_REDUCED"}:
        read = "EARLY_EXIT_PROXY_LEADS"
        next_action = "Run exact candle replay for the best early-exit proxy before touching any MID_LONG rule."
    elif best_delayed and str(best_delayed.get("read")) in {"DELAYED_ENTRY_PROXY_PROMISING", "DELAYED_ENTRY_DAMAGE_REDUCED"}:
        read = "DELAYED_ENTRY_PROXY_LEADS"
        next_action = "Run exact delayed-entry replay with repriced entry/SL/TP for the best retained confirmation cohort."
    elif best_exit_delta > 0 or best_delayed_delta > 0:
        read = "ACTION_PROXY_MIXED"
        next_action = "Keep both branches in research; require exact replay because proxy improvement is not clean enough."
    else:
        read = "NO_ACTION_PROXY_READY"
        next_action = "Do not promote first-hour action logic yet; continue defining cleaner pre-entry MID_LONG cohorts."
    return {
        "read": read,
        "baseline_realistic_total_r_closed": baseline.get("realistic_total_r_closed"),
        "best_delayed_entry": _mid_long_action_summary_row(best_delayed, delta_key="realistic_total_r_delta_vs_baseline"),
        "best_early_exit": _mid_long_action_summary_row(best_exit, delta_key="proxy_realistic_total_r_delta_vs_baseline"),
        "best_delayed_delta_r": best_delayed_delta,
        "best_early_exit_delta_r": best_exit_delta,
        "next_action": next_action,
    }


def _mid_long_action_summary_row(row: dict[str, Any] | None, *, delta_key: str) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "filter_id": row.get("filter_id"),
        "label": row.get("label"),
        "read": row.get("read"),
        "sample_count": row.get("sample_count"),
        "action_count": row.get("action_count"),
        "retained_count": row.get("retained_count"),
        "delta_r": row.get(delta_key),
        "total_r": row.get("proxy_realistic_total_r_closed") or row.get("realistic_total_r_closed"),
        "avg_r": row.get("proxy_realistic_avg_r_closed") or row.get("realistic_avg_r_closed"),
    }


MID_LONG_RESET_PRIMARY_DEFINITIONS: dict[str, str] = {
    "BREAKOUT_CONTINUATION_LONG": "Close-accepted breakout family. Entry is tied to a prior resistance break, not just a wick above resistance.",
    "SUPPORT_RETEST_LONG": "Role-reversal or retest family. Entry follows a support/retest hold instead of the original breakout bar.",
    "PULLBACK_LONG": "Pullback/support-bounce family. Entry is anchored to a pullback/support hold without requiring a fresh role-reversal zone.",
    "OTHER_STRUCTURED_LONG": "Structure exists, but it does not cleanly match breakout, retest, or pullback definitions.",
    "UNCLASSIFIED_MID_LONG": "Structure is unavailable, mid-range, ambiguous, or missing required family evidence.",
}


MID_LONG_RESET_MODIFIER_DEFINITIONS: dict[str, str] = {
    "LATE_CHASE": "Entry timing appears late relative to ATR-extension or breakout freshness.",
    "HIGH_EXTENSION": "Entry is in the high/extreme ATR-extension bucket.",
    "LOW_REMAINING_ROOM": "Room to next resistance is low, so the target may be pushed into nearby overhead supply.",
    "WEAK_INITIATIVE_FLOW": "Volume, taker buy, and OI do not confirm long initiative strongly.",
    "HIGH_CROWDING": "Funding/OI/positioning are elevated enough to treat the long as crowded risk.",
    "HIGH_PROJECTED_COST": "Realistic cost/fill drag is high enough to matter.",
    "STRUCTURE_CONFLICT": "Structure state conflicts with a clean long continuation read.",
}


def _mid_long_definition_reset_lab(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    reset_by_id = {
        str(item.get("signal_id") or idx): _mid_long_reset_state(item, taxonomy_by_id[str(item.get("signal_id") or idx)])
        for idx, item in enumerate(items)
    }
    primary_rows = _mid_long_reset_primary_rows(
        items,
        reset_by_id=reset_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    modifier_rows = _mid_long_reset_modifier_rows(
        items,
        reset_by_id=reset_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    decision_rows = _mid_long_reset_decision_rows(
        items,
        reset_by_id=reset_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    family_modifier_rows = _mid_long_reset_family_modifier_rows(
        items,
        reset_by_id=reset_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    cohort_rows = _mid_long_reset_cohort_comparison_rows(
        items,
        reset_by_id=reset_by_id,
        baseline=baseline,
        min_sample=min_sample,
    )
    coverage = _mid_long_reset_coverage(items, reset_by_id=reset_by_id)
    return {
        "scope": "MID_LONG 1h Definition Reset Lab, read-only",
        "method": (
            "Primary family is mutually exclusive; modifiers are overlapping pre-entry risk tags; "
            "derived decision combines both for research triage only."
        ),
        "taxonomy_version": "MID_LONG_DEFINITION_RESET_V2",
        "legacy_definition": {
            "label": "MID_LONG_V2_LEGACY",
            "read": "Logged Signal Factory V2 MID_LONG 1h. Kept as control and historical evidence; never deleted.",
            "entry_basis": "price impulse plus OI expansion style trigger from the live V2 signal log.",
        },
        "structure_first_draft": {
            "label": "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "read": (
                "Read-only taxonomy layer over legacy rows: classify structure family first, then attach risk modifiers. "
                "It does not replace Signal Factory output."
            ),
            "promotion_state": "SHADOW_RESEARCH_ONLY",
        },
        "primary_family_order": [
            "SUPPORT_RETEST_LONG",
            "BREAKOUT_CONTINUATION_LONG",
            "PULLBACK_LONG",
            "OTHER_STRUCTURED_LONG",
            "UNCLASSIFIED_MID_LONG",
        ],
        "modifier_order": list(MID_LONG_RESET_MODIFIER_DEFINITIONS),
        "primary_definitions": MID_LONG_RESET_PRIMARY_DEFINITIONS,
        "modifier_definitions": MID_LONG_RESET_MODIFIER_DEFINITIONS,
        "coverage": coverage,
        "primary_family_rows": primary_rows,
        "modifier_rows": modifier_rows,
        "derived_decision_rows": decision_rows,
        "cohort_comparison_rows": cohort_rows,
        "family_modifier_rows": family_modifier_rows,
        "summary": _mid_long_reset_summary(
            primary_rows=primary_rows,
            modifier_rows=modifier_rows,
            decision_rows=decision_rows,
            cohort_rows=cohort_rows,
            coverage=coverage,
            min_sample=min_sample,
        ),
        "data_retention_policy": [
            "Do not delete legacy MID_LONG rows; they are the control group that proves whether the new definition improves.",
            "Structure-first draft labels are computed from the same historical rows and can be regenerated.",
            "Live scanner, Signal Factory rules, TP/SL, threshold, and execution behavior remain unchanged.",
        ],
        "guardrails": [
            "Primary family labels are pre-entry taxonomy, not live Signal Factory rules.",
            "Modifiers can overlap and must not be read as standalone rejection gates.",
            "Derived decisions are research triage only; they do not change scanner or TP/SL behavior.",
            "If every family remains negative on validation, MID_LONG 1h should stay research-only instead of adding more filters.",
        ],
    }


def _mid_long_reverse_shadow_audit(items: list[dict[str, Any]], *, min_sample: int) -> dict[str, Any]:
    taxonomy_by_id = _mid_long_taxonomy_by_id(items)
    reset_by_id = {
        str(item.get("signal_id") or idx): _mid_long_reset_state(item, taxonomy_by_id[str(item.get("signal_id") or idx)])
        for idx, item in enumerate(items)
    }
    rr_values = (Decimal("1.00"), Decimal("1.25"), Decimal("1.50"), Decimal("2.00"))
    cohorts: list[tuple[str, str, str, list[dict[str, Any]]]] = [
        (
            "LEGACY_V2_ALL",
            "MID_LONG_V2_LEGACY",
            "All logged MID_LONG 1h rows, interpreted as reverse short geometry.",
            items,
        ),
        (
            "STRUCTURE_FIRST_CLASSIFIED",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Rows where the structure-first draft can assign a primary family.",
            [
                item
                for idx, item in enumerate(items)
                if reset_by_id[str(item.get("signal_id") or idx)]["primary_family"] != "UNCLASSIFIED_MID_LONG"
            ],
        ),
        (
            "STRUCTURE_FIRST_ELIGIBLE_DRAFT",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Rows passing the draft eligible structure-first bucket.",
            [
                item
                for idx, item in enumerate(items)
                if str(reset_by_id[str(item.get("signal_id") or idx)]["derived_decision"]).startswith("ELIGIBLE")
            ],
        ),
        (
            "STRUCTURE_FIRST_REJECT_DRAFT",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Rows rejected by the draft structure-first triage.",
            [
                item
                for idx, item in enumerate(items)
                if str(reset_by_id[str(item.get("signal_id") or idx)]["derived_decision"]).startswith("REJECT")
            ],
        ),
        (
            "STRUCTURE_FIRST_WAIT_UNCLASSIFIED",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Rows still unclassified or structurally insufficient.",
            [
                item
                for idx, item in enumerate(items)
                if reset_by_id[str(item.get("signal_id") or idx)]["derived_decision"] == "WAIT_UNCLASSIFIED"
            ],
        ),
        (
            "BREAKOUT_CONTINUATION_LONG",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Primary family == BREAKOUT_CONTINUATION_LONG.",
            [
                item
                for idx, item in enumerate(items)
                if reset_by_id[str(item.get("signal_id") or idx)]["primary_family"] == "BREAKOUT_CONTINUATION_LONG"
            ],
        ),
        (
            "SUPPORT_RETEST_LONG",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Primary family == SUPPORT_RETEST_LONG.",
            [
                item
                for idx, item in enumerate(items)
                if reset_by_id[str(item.get("signal_id") or idx)]["primary_family"] == "SUPPORT_RETEST_LONG"
            ],
        ),
        (
            "UNCLASSIFIED_MID_LONG",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Primary family == UNCLASSIFIED_MID_LONG.",
            [
                item
                for idx, item in enumerate(items)
                if reset_by_id[str(item.get("signal_id") or idx)]["primary_family"] == "UNCLASSIFIED_MID_LONG"
            ],
        ),
    ]
    rows: list[dict[str, Any]] = []
    for cohort_id, definition_version, description, cohort_items in cohorts:
        for rr in rr_values:
            rows.append(
                _mid_long_reverse_shadow_row(
                    cohort_id=cohort_id,
                    definition_version=definition_version,
                    description=description,
                    items=cohort_items,
                    rr=rr,
                    min_sample=min_sample,
                )
            )
    return {
        "scope": "MID_LONG 1h reverse shadow audit",
        "method": (
            "Diagnostic proxy only: logged MID_LONG path MFE/MAE is inverted to ask whether the same entry area "
            "would look better as a short. This does not replay candle order and does not change live rules."
        ),
        "reverse_direction": "SHORT_PROXY_FROM_MID_LONG",
        "rr_values": [str(value.normalize()) for value in rr_values],
        "rows": rows,
        "summary": _mid_long_reverse_shadow_summary(rows, min_sample=min_sample),
        "guardrails": [
            "Reverse rows are a geometry proxy from logged MFE/MAE, not a live signal and not a final backtest.",
            "BOTH_HIT_PATH_UNKNOWN is scored at 0R before cost because candle path order is not known from aggregate MFE/MAE.",
            "If reverse proxy is positive, the next step is closed-candle replay before any rule discussion.",
            "Signal Factory, scanner behavior, TP/SL formula, thresholds, and execution remain unchanged.",
        ],
    }


def _mid_long_reverse_shadow_row(
    *,
    cohort_id: str,
    definition_version: str,
    description: str,
    items: list[dict[str, Any]],
    rr: Decimal,
    min_sample: int,
) -> dict[str, Any]:
    tp_count = 0
    sl_count = 0
    both_count = 0
    neither_count = 0
    gross_values: list[Decimal] = []
    realistic_values: list[Decimal] = []
    reverse_mfe_values: list[Decimal] = []
    reverse_mae_values: list[Decimal] = []
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    for item in items:
        result = _mid_long_reverse_shadow_result(item, rr=rr)
        reverse_mfe_values.append(result["reverse_mfe_r"])
        reverse_mae_values.append(result["reverse_mae_r"])
        status = result["result_status"]
        if status == "TP_HIT":
            tp_count += 1
        elif status == "SL_HIT":
            sl_count += 1
        elif status == "BOTH_HIT_PATH_UNKNOWN":
            both_count += 1
        else:
            neither_count += 1
        gross_values.append(result["gross_r"])
        realistic_values.append(result["realistic_r"])
    sample_count = len(items)
    terminal_count = tp_count + sl_count + both_count
    top_symbol, top_symbol_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    gross_total = sum(gross_values, Decimal("0"))
    realistic_total = sum(realistic_values, Decimal("0"))
    row: dict[str, Any] = {
        "cohort_id": cohort_id,
        "definition_version": definition_version,
        "description": description,
        "rr": rr,
        "sample_count": sample_count,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "both_hit_count": both_count,
        "neither_count": neither_count,
        "terminal_count": terminal_count,
        "tp_share_pct": _pct_decimal(tp_count, terminal_count),
        "sl_share_pct": _pct_decimal(sl_count, terminal_count),
        "both_share_pct": _pct_decimal(both_count, terminal_count),
        "gross_total_r": gross_total,
        "gross_avg_r": gross_total / Decimal(sample_count) if sample_count else None,
        "realistic_total_r": realistic_total,
        "realistic_avg_r": realistic_total / Decimal(sample_count) if sample_count else None,
        "median_realistic_r": _median_decimal_snapshot(realistic_values),
        "median_reverse_mfe_r": _median_decimal_snapshot(reverse_mfe_values),
        "median_reverse_mae_r": _median_decimal_snapshot(reverse_mae_values),
        "top_symbol": top_symbol,
        "top_symbol_count": top_symbol_count,
        "top_symbol_share_pct": _pct_decimal(top_symbol_count, sample_count),
    }
    row["read"] = _mid_long_reverse_shadow_read(row, min_sample=min_sample)
    return row


def _mid_long_reverse_shadow_result(item: dict[str, Any], *, rr: Decimal) -> dict[str, Any]:
    original_mfe = _decimal_or_zero_snapshot(item.get("mfe_r"))
    original_mae = _decimal_or_zero_snapshot(item.get("mae_r"))
    reverse_mfe = abs(original_mae)
    reverse_mae = -abs(original_mfe)
    tp_hit = reverse_mfe >= rr
    sl_hit = abs(reverse_mae) >= Decimal("1")
    if tp_hit and sl_hit:
        status = "BOTH_HIT_PATH_UNKNOWN"
        gross_r = Decimal("0")
    elif tp_hit:
        status = "TP_HIT"
        gross_r = rr
    elif sl_hit:
        status = "SL_HIT"
        gross_r = Decimal("-1")
    else:
        status = "NEITHER"
        gross_r = Decimal("0")
    cost_r = max(_decimal_or_zero_snapshot(item.get("realistic_cost_r_estimate")), Decimal("0"))
    return {
        "result_status": status,
        "reverse_mfe_r": reverse_mfe,
        "reverse_mae_r": reverse_mae,
        "gross_r": gross_r,
        "realistic_r": gross_r - cost_r,
    }


def _mid_long_reverse_shadow_read(row: dict[str, Any], *, min_sample: int) -> str:
    sample = int(row.get("sample_count") or 0)
    total = _decimal_or_zero_snapshot(row.get("realistic_total_r"))
    avg = _decimal_or_zero_snapshot(row.get("realistic_avg_r"))
    both_share = _decimal_or_zero_snapshot(row.get("both_share_pct"))
    if sample < min_sample:
        return "SAMPLE_TOO_SMALL"
    if both_share >= Decimal("20"):
        return "PATH_AMBIGUOUS_NEEDS_REPLAY"
    if total > 0 and avg >= Decimal("0.05"):
        return "REVERSE_PROMISING_PROXY"
    if total > 0:
        return "REVERSE_POSITIVE_BUT_THIN"
    return "REVERSE_NOT_SUPPORTED"


def _mid_long_reverse_shadow_summary(rows: list[dict[str, Any]], *, min_sample: int) -> dict[str, Any]:
    readable = [row for row in rows if int(row.get("sample_count") or 0) >= min_sample]
    best = max(readable, key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_total_r")), default=None)
    promising = [
        row for row in readable if str(row.get("read") or "") in {"REVERSE_PROMISING_PROXY", "REVERSE_POSITIVE_BUT_THIN"}
    ]
    ambiguous = [row for row in readable if row.get("read") == "PATH_AMBIGUOUS_NEEDS_REPLAY"]
    if promising:
        read = "REVERSE_PROXY_FOUND"
        next_action = "Replay candle order for the best reverse proxy cohorts before discussing rule changes."
    elif ambiguous:
        read = "REVERSE_PROXY_AMBIGUOUS"
        next_action = "Run candle-order replay on ambiguous cohorts; MFE/MAE alone is not enough."
    else:
        read = "REVERSE_PROXY_NOT_SUPPORTED"
        next_action = "Do not reverse MID_LONG yet; continue definition research from structure/path evidence."
    return {
        "read": read,
        "min_sample": min_sample,
        "readable_row_count": len(readable),
        "promising_row_count": len(promising),
        "ambiguous_row_count": len(ambiguous),
        "best_row": _mid_long_reverse_summary_row(best),
        "next_action": next_action,
    }


def _mid_long_reverse_summary_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "cohort_id": row.get("cohort_id"),
        "rr": row.get("rr"),
        "sample_count": row.get("sample_count"),
        "tp_count": row.get("tp_count"),
        "sl_count": row.get("sl_count"),
        "both_hit_count": row.get("both_hit_count"),
        "neither_count": row.get("neither_count"),
        "realistic_total_r": row.get("realistic_total_r"),
        "realistic_avg_r": row.get("realistic_avg_r"),
        "read": row.get("read"),
        "top_symbol": row.get("top_symbol"),
        "top_symbol_share_pct": row.get("top_symbol_share_pct"),
    }


def _mid_long_reset_state(item: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    primary = _mid_long_reset_primary_family(item, taxonomy)
    modifiers = _mid_long_reset_modifiers(item, taxonomy)
    return {
        "primary_family": primary,
        "modifiers": modifiers,
        "derived_decision": _mid_long_reset_derived_decision(primary, modifiers),
    }


def _mid_long_reset_primary_family(item: dict[str, Any], taxonomy: dict[str, Any]) -> str:
    setup = str(taxonomy.get("setup_family") or "UNCLASSIFIED")
    breakout = str(taxonomy.get("breakout_state_pre_entry") or "")
    retest = str(taxonomy.get("retest_quality_pre_entry") or "")
    structure = str(taxonomy.get("structure_status") or "")
    if structure == "UNAVAILABLE" or setup in {"UNCLASSIFIED", "MID_RANGE"}:
        return "UNCLASSIFIED_MID_LONG"
    if setup == "RETEST" and retest in {"RETEST_HOLD_STRONG", "RETEST_HOLD_IN_ZONE"}:
        return "SUPPORT_RETEST_LONG"
    if setup == "BREAKOUT_ATTEMPT" and breakout == "CLOSE_ACCEPTED":
        return "BREAKOUT_CONTINUATION_LONG"
    if setup == "SUPPORT_BOUNCE":
        return "PULLBACK_LONG"
    if structure in {"AVAILABLE", "PARTIAL"}:
        return "OTHER_STRUCTURED_LONG"
    return "UNCLASSIFIED_MID_LONG"


def _mid_long_reset_modifiers(item: dict[str, Any], taxonomy: dict[str, Any]) -> list[str]:
    modifiers: list[str] = []
    extension_bucket = str(taxonomy.get("extension_bucket") or "")
    timing = str(taxonomy.get("entry_timing_bucket") or "")
    room = str(taxonomy.get("room_to_resistance_bucket") or "")
    flow = str(taxonomy.get("flow_state_provisional") or "")
    flow_regime = str(taxonomy.get("flow_regime") or "")
    crowding = str(taxonomy.get("crowding_bucket") or "")
    cost = str(taxonomy.get("projected_cost_bucket") or "")
    status = str(item.get("structure_zone_status") or "").upper()
    context = str(item.get("structure_zone_context_status") or "").upper()
    primary = str(item.get("structure_zone_primary_state") or "").upper()

    if timing == "LATE_CHASE":
        modifiers.append("LATE_CHASE")
    if extension_bucket in {"HIGH_EXTENSION", "EXTREME_EXTENSION"}:
        modifiers.append("HIGH_EXTENSION")
    if room == "LOW_ROOM":
        modifiers.append("LOW_REMAINING_ROOM")
    if flow == "WEAK" or flow_regime in {"PRICE_UP_OI_UP_WEAK_BUY", "PRICE_NOT_UP_OI_UP_CROWDING_RISK"}:
        modifiers.append("WEAK_INITIATIVE_FLOW")
    if crowding in {"HIGH_CROWDING", "EXTREME_CROWDING"}:
        modifiers.append("HIGH_CROWDING")
    if cost in {"HIGH_COST", "EXTREME_COST"}:
        modifiers.append("HIGH_PROJECTED_COST")
    if "CONFLICT" in status or "CONFLICT" in context or ("RESISTANCE" in primary and "BREAK" not in primary):
        modifiers.append("STRUCTURE_CONFLICT")
    return modifiers


def _mid_long_reset_derived_decision(primary: str, modifiers: list[str]) -> str:
    modifier_set = set(modifiers)
    if primary == "UNCLASSIFIED_MID_LONG":
        return "WAIT_UNCLASSIFIED"
    if "HIGH_PROJECTED_COST" in modifier_set:
        return "REJECT_COST_DRAFT"
    if "LATE_CHASE" in modifier_set and (
        "LOW_REMAINING_ROOM" in modifier_set or "HIGH_EXTENSION" in modifier_set
    ):
        return "REJECT_CHASE_DRAFT"
    if "HIGH_CROWDING" in modifier_set and modifier_set.intersection(
        {"HIGH_EXTENSION", "LOW_REMAINING_ROOM", "WEAK_INITIATIVE_FLOW", "STRUCTURE_CONFLICT"}
    ):
        return "REJECT_CROWDED_CONFLICT_DRAFT"
    if primary == "BREAKOUT_CONTINUATION_LONG":
        return "ELIGIBLE_BREAKOUT_DRAFT"
    if primary == "SUPPORT_RETEST_LONG":
        return "ELIGIBLE_RETEST_DRAFT"
    if primary == "PULLBACK_LONG":
        return "ELIGIBLE_PULLBACK_DRAFT"
    return "WAIT_UNCLASSIFIED"


def _mid_long_reset_primary_rows(
    items: list[dict[str, Any]],
    *,
    reset_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        state = reset_by_id[str(item.get("signal_id") or idx)]
        grouped[str(state["primary_family"])].append(item)
    rows: list[dict[str, Any]] = []
    for family in MID_LONG_RESET_PRIMARY_DEFINITIONS:
        family_items = grouped.get(family, [])
        row = _mid_long_perf_row(
            f"RESET_PRIMARY:{family}",
            family,
            f"primary_family == {family}",
            family_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "primary_family": family,
                "definition": MID_LONG_RESET_PRIMARY_DEFINITIONS[family],
                "decision_mix": _mid_long_reset_mix(
                    family_items,
                    reset_by_id=reset_by_id,
                    field="derived_decision",
                ),
                "modifier_mix": _mid_long_reset_modifier_mix(family_items, reset_by_id=reset_by_id),
                "path_mix": _mid_long_path_mix(family_items),
                "family_role": _mid_long_reset_family_role(family),
                "read": _mid_long_reset_primary_read(row, family=family, min_sample=min_sample),
            }
        )
        rows.append(row)
    return rows


def _mid_long_reset_modifier_rows(
    items: list[dict[str, Any]],
    *,
    reset_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for modifier, definition in MID_LONG_RESET_MODIFIER_DEFINITIONS.items():
        modifier_items = [
            item
            for idx, item in enumerate(items)
            if modifier in reset_by_id[str(item.get("signal_id") or idx)]["modifiers"]
        ]
        row = _mid_long_perf_row(
            f"RESET_MODIFIER:{modifier}",
            modifier,
            f"{modifier} in modifiers",
            modifier_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "modifier": modifier,
                "definition": definition,
                "primary_family_mix": _mid_long_reset_mix(
                    modifier_items,
                    reset_by_id=reset_by_id,
                    field="primary_family",
                ),
                "path_mix": _mid_long_path_mix(modifier_items),
                "read": _mid_long_reset_modifier_read(row, modifier=modifier, min_sample=min_sample),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
            int(row.get("closed_count") or 0),
        )
    )
    return rows


def _mid_long_reset_decision_rows(
    items: list[dict[str, Any]],
    *,
    reset_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        state = reset_by_id[str(item.get("signal_id") or idx)]
        grouped[str(state["derived_decision"])].append(item)
    decision_order = (
        "ELIGIBLE_BREAKOUT_DRAFT",
        "ELIGIBLE_RETEST_DRAFT",
        "ELIGIBLE_PULLBACK_DRAFT",
        "REJECT_CHASE_DRAFT",
        "REJECT_CROWDED_CONFLICT_DRAFT",
        "REJECT_COST_DRAFT",
        "WAIT_UNCLASSIFIED",
    )
    rows: list[dict[str, Any]] = []
    for decision in decision_order:
        decision_items = grouped.get(decision, [])
        row = _mid_long_perf_row(
            f"RESET_DECISION:{decision}",
            decision,
            f"derived_decision == {decision}",
            decision_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "decision": decision,
                "primary_family_mix": _mid_long_reset_mix(
                    decision_items,
                    reset_by_id=reset_by_id,
                    field="primary_family",
                ),
                "modifier_mix": _mid_long_reset_modifier_mix(decision_items, reset_by_id=reset_by_id),
                "path_mix": _mid_long_path_mix(decision_items),
                "read": _mid_long_reset_decision_read(row, decision=decision, min_sample=min_sample),
            }
        )
        rows.append(row)
    return rows


def _mid_long_reset_family_modifier_rows(
    items: list[dict[str, Any]],
    *,
    reset_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family in MID_LONG_RESET_PRIMARY_DEFINITIONS:
        for modifier in MID_LONG_RESET_MODIFIER_DEFINITIONS:
            cell_items = [
                item
                for idx, item in enumerate(items)
                if reset_by_id[str(item.get("signal_id") or idx)]["primary_family"] == family
                and modifier in reset_by_id[str(item.get("signal_id") or idx)]["modifiers"]
            ]
            if not cell_items:
                continue
            row = _mid_long_perf_row(
                f"RESET_FAMILY_MODIFIER:{family}:{modifier}",
                f"{family} x {modifier}",
                f"primary_family == {family} AND modifier == {modifier}",
                cell_items,
                baseline=baseline,
                required_fields=(),
                min_sample=min_sample,
            )
            row.update(
                {
                    "primary_family": family,
                    "modifier": modifier,
                    "path_mix": _mid_long_path_mix(cell_items),
                    "is_readable": int(row.get("closed_count") or 0) >= min_sample,
                }
            )
            rows.append(row)
    rows.sort(
        key=lambda row: (
            bool(row.get("is_readable")),
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_reset_cohort_comparison_rows(
    items: list[dict[str, Any]],
    *,
    reset_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    cohorts: list[tuple[str, str, str, list[dict[str, Any]]]] = [
        (
            "LEGACY_V2_ALL",
            "MID_LONG_V2_LEGACY",
            "All logged MID_LONG 1h V2 rows. This is the frozen control, not deleted data.",
            items,
        ),
        (
            "STRUCTURE_FIRST_CLASSIFIED",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Rows where a primary structure family can be assigned.",
            [
                item
                for idx, item in enumerate(items)
                if reset_by_id[str(item.get("signal_id") or idx)]["primary_family"] != "UNCLASSIFIED_MID_LONG"
            ],
        ),
        (
            "STRUCTURE_FIRST_ELIGIBLE_DRAFT",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Rows passing the draft eligible bucket after structure family plus modifiers.",
            [
                item
                for idx, item in enumerate(items)
                if str(reset_by_id[str(item.get("signal_id") or idx)]["derived_decision"]).startswith("ELIGIBLE")
            ],
        ),
        (
            "STRUCTURE_FIRST_REJECT_DRAFT",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Rows rejected by draft structure-first risk triage.",
            [
                item
                for idx, item in enumerate(items)
                if str(reset_by_id[str(item.get("signal_id") or idx)]["derived_decision"]).startswith("REJECT")
            ],
        ),
        (
            "STRUCTURE_FIRST_WAIT_UNCLASSIFIED",
            "MID_LONG_STRUCTURE_FIRST_DRAFT",
            "Rows that remain unclassified or structurally insufficient.",
            [
                item
                for idx, item in enumerate(items)
                if reset_by_id[str(item.get("signal_id") or idx)]["derived_decision"] == "WAIT_UNCLASSIFIED"
            ],
        ),
    ]
    rows: list[dict[str, Any]] = []
    for cohort_id, definition_version, description, cohort_items in cohorts:
        row = _mid_long_perf_row(
            f"RESET_COHORT:{cohort_id}",
            cohort_id,
            description,
            cohort_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "cohort_id": cohort_id,
                "definition_version": definition_version,
                "description": description,
                "primary_family_mix": _mid_long_reset_mix(
                    cohort_items,
                    reset_by_id=reset_by_id,
                    field="primary_family",
                ),
                "decision_mix": _mid_long_reset_mix(
                    cohort_items,
                    reset_by_id=reset_by_id,
                    field="derived_decision",
                ),
                "modifier_mix": _mid_long_reset_modifier_mix(cohort_items, reset_by_id=reset_by_id),
                "read": _mid_long_reset_cohort_read(row, cohort_id=cohort_id, min_sample=min_sample),
            }
        )
        rows.append(row)
    return rows


def _mid_long_reset_coverage(
    items: list[dict[str, Any]],
    *,
    reset_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    total = len(items)
    unclassified = sum(
        1
        for state in reset_by_id.values()
        if state.get("primary_family") == "UNCLASSIFIED_MID_LONG"
    )
    modifier_counts = Counter(len(state.get("modifiers") or []) for state in reset_by_id.values())
    multi_modifier = sum(1 for state in reset_by_id.values() if len(state.get("modifiers") or []) >= 2)
    return {
        "total_rows": total,
        "classified_rows": total - unclassified,
        "classification_coverage_pct": _pct_decimal(total - unclassified, total),
        "unclassified_rows": unclassified,
        "unclassified_pct": _pct_decimal(unclassified, total),
        "multi_modifier_rows": multi_modifier,
        "multi_modifier_pct": _pct_decimal(multi_modifier, total),
        "modifier_count_distribution": {str(key): value for key, value in sorted(modifier_counts.items())},
    }


def _mid_long_reset_mix(
    items: list[dict[str, Any]],
    *,
    reset_by_id: dict[str, dict[str, Any]],
    field: str,
) -> dict[str, int]:
    return dict(
        Counter(
            str(reset_by_id[str(item.get("signal_id") or idx)].get(field) or "UNKNOWN")
            for idx, item in enumerate(items)
        )
    )


def _mid_long_reset_modifier_mix(
    items: list[dict[str, Any]],
    *,
    reset_by_id: dict[str, dict[str, Any]],
) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for idx, item in enumerate(items):
        modifiers = reset_by_id[str(item.get("signal_id") or idx)].get("modifiers") or []
        if not modifiers:
            counter["NO_MODIFIER"] += 1
        for modifier in modifiers:
            counter[str(modifier)] += 1
    return dict(counter)


def _mid_long_reset_family_role(family: str) -> str:
    if family in {"BREAKOUT_CONTINUATION_LONG", "SUPPORT_RETEST_LONG", "PULLBACK_LONG"}:
        return "CANDIDATE_FAMILY"
    if family == "OTHER_STRUCTURED_LONG":
        return "HOLDING_FAMILY"
    return "WAIT_DATA"


def _mid_long_reset_primary_read(row: dict[str, Any], *, family: str, min_sample: int) -> str:
    closed = int(row.get("closed_count") or 0)
    total_r = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    if closed < min_sample:
        return "Sample kecil; jangan baca sebagai edge."
    if family == "UNCLASSIFIED_MID_LONG":
        return "Unclassified harus turun sebelum MID_LONG bisa dipercaya."
    if total_r > 0 and avg_delta > Decimal("0.05"):
        return "Candidate family worth chronological validation."
    if avg_delta > 0:
        return "Less bad than V2 control, but not clean enough for promotion."
    return "No positive separation versus V2 control."


def _mid_long_reset_modifier_read(row: dict[str, Any], *, modifier: str, min_sample: int) -> str:
    closed = int(row.get("closed_count") or 0)
    total_r = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    if closed < min_sample:
        return "Too small for standalone read."
    if total_r < 0:
        return "Modifier contains damage, but overlap must be checked before using it as reject."
    return "Modifier is not a clean damage tag yet."


def _mid_long_reset_decision_read(row: dict[str, Any], *, decision: str, min_sample: int) -> str:
    closed = int(row.get("closed_count") or 0)
    total_r = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    if closed < min_sample:
        return "Insufficient sample for this draft decision."
    if decision.startswith("ELIGIBLE") and total_r > 0 and avg_delta > Decimal("0.05"):
        return "Potential candidate for time-split validation, not live rule."
    if decision.startswith("REJECT") and total_r < 0:
        return "Potential reject state; compare removed TP/SL before using."
    if decision == "WAIT_UNCLASSIFIED":
        return "Needs better structure data or separate holding cohort."
    return "No clear improvement yet."


def _mid_long_reset_cohort_read(row: dict[str, Any], *, cohort_id: str, min_sample: int) -> str:
    closed = int(row.get("closed_count") or 0)
    total_r = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    if closed < min_sample:
        return "Sample too small for cohort comparison."
    if cohort_id == "LEGACY_V2_ALL":
        return "Control group. Keep this historical data to measure improvement."
    if cohort_id == "STRUCTURE_FIRST_WAIT_UNCLASSIFIED":
        return "This should shrink before MID_LONG can become trustworthy."
    if cohort_id == "STRUCTURE_FIRST_ELIGIBLE_DRAFT" and total_r > 0 and avg_delta > Decimal("0.05"):
        return "Candidate cohort for chronological validation only."
    if cohort_id == "STRUCTURE_FIRST_ELIGIBLE_DRAFT":
        return "Eligible draft is not positive enough yet."
    if cohort_id == "STRUCTURE_FIRST_REJECT_DRAFT" and total_r < 0:
        return "Reject bucket contains damage; validate lost TP before using as a gate."
    if avg_delta > 0:
        return "Less bad than V2, but still needs validation."
    return "No clear improvement over legacy control."


def _mid_long_reset_summary(
    *,
    primary_rows: list[dict[str, Any]],
    modifier_rows: list[dict[str, Any]],
    decision_rows: list[dict[str, Any]],
    cohort_rows: list[dict[str, Any]],
    coverage: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    candidate_rows = [
        row
        for row in primary_rows
        if row.get("primary_family") in {"BREAKOUT_CONTINUATION_LONG", "SUPPORT_RETEST_LONG", "PULLBACK_LONG"}
        and int(row.get("closed_count") or 0) >= min_sample
    ]
    best_family = max(
        candidate_rows,
        key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
        default=None,
    )
    reject_rows = [
        row
        for row in decision_rows
        if str(row.get("decision") or "").startswith("REJECT")
        and int(row.get("closed_count") or 0) >= min_sample
    ]
    worst_reject = min(
        reject_rows,
        key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
        default=None,
    )
    positive_family_count = sum(
        1
        for row in candidate_rows
        if _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")) > 0
        and _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")) > 0
    )
    eligible_cohort = next(
        (row for row in cohort_rows if row.get("cohort_id") == "STRUCTURE_FIRST_ELIGIBLE_DRAFT"),
        None,
    )
    legacy_cohort = next((row for row in cohort_rows if row.get("cohort_id") == "LEGACY_V2_ALL"), None)
    return {
        "best_candidate_family": _mid_long_reset_summary_row(best_family, key="primary_family"),
        "worst_reject_decision": _mid_long_reset_summary_row(worst_reject, key="decision"),
        "legacy_v2_control": _mid_long_reset_summary_row(legacy_cohort, key="cohort_id"),
        "structure_first_eligible": _mid_long_reset_summary_row(eligible_cohort, key="cohort_id"),
        "positive_candidate_family_count": positive_family_count,
        "read": _mid_long_reset_read(
            positive_family_count=positive_family_count,
            coverage=coverage,
        ),
        "next_action": _mid_long_reset_next_action(positive_family_count=positive_family_count),
    }


def _mid_long_reset_summary_row(row: dict[str, Any] | None, *, key: str) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        key: row.get(key),
        "closed_count": row.get("closed_count"),
        "tp_count": row.get("tp_count"),
        "sl_count": row.get("sl_count"),
        "realistic_total_r_closed": row.get("realistic_total_r_closed"),
        "realistic_avg_r_closed": row.get("realistic_avg_r_closed"),
        "realistic_avg_r_delta_vs_baseline": row.get("realistic_avg_r_delta_vs_baseline"),
        "top_symbol": row.get("top_symbol"),
        "top_symbol_share_pct": row.get("top_symbol_share_pct"),
    }


def _mid_long_reset_read(*, positive_family_count: int, coverage: dict[str, Any]) -> str:
    unclassified_pct = _decimal_or_zero_snapshot(coverage.get("unclassified_pct"))
    if positive_family_count > 0:
        return "HAS_CANDIDATE_FAMILY_FOR_VALIDATION"
    if unclassified_pct >= Decimal("40"):
        return "STRUCTURE_COVERAGE_TOO_WEAK"
    return "NO_PRIMARY_FAMILY_READY"


def _mid_long_reset_next_action(*, positive_family_count: int) -> str:
    if positive_family_count > 0:
        return "Run chronological validation only on the positive primary family; keep V2 control unchanged."
    return "Do not promote MID_LONG 1h. Inspect primary family x modifier damage before trying more filters."


def _mid_long_sub_setup_split_lab(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
        grouped[_mid_long_sub_setup_label(taxonomy)].append(item)

    rows: list[dict[str, Any]] = []
    for sub_label, sub_items in grouped.items():
        row = _mid_long_perf_row(
            f"SUB_SETUP:{sub_label}",
            sub_label,
            f"sub_setup == {sub_label}",
            sub_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "sub_setup": sub_label,
                "definition": _mid_long_sub_setup_definition(sub_label),
                "sub_setup_family": _mid_long_sub_setup_family(sub_label),
                "research_status": _mid_long_sub_setup_status(row, sub_label=sub_label, min_sample=min_sample),
                "recommended_action": _mid_long_sub_setup_action(row, sub_label=sub_label, min_sample=min_sample),
                "path_mix": _mid_long_path_mix(sub_items),
                "flow_mix": _mid_long_taxonomy_mix(sub_items, taxonomy_by_id=taxonomy_by_id, taxonomy_key="flow_state_provisional"),
                "crowding_mix": _mid_long_taxonomy_mix(sub_items, taxonomy_by_id=taxonomy_by_id, taxonomy_key="crowding_bucket"),
                "room_mix": _mid_long_taxonomy_mix(sub_items, taxonomy_by_id=taxonomy_by_id, taxonomy_key="room_to_resistance_bucket"),
                "cost_mix": _mid_long_taxonomy_mix(sub_items, taxonomy_by_id=taxonomy_by_id, taxonomy_key="projected_cost_bucket"),
                "dominant_path": _mid_long_dominant_counter_key(_mid_long_path_mix(sub_items)),
                "dominant_flow": _mid_long_dominant_counter_key(
                    _mid_long_taxonomy_mix(sub_items, taxonomy_by_id=taxonomy_by_id, taxonomy_key="flow_state_provisional")
                ),
                "median_cost_r": _median_decimal_snapshot(_mid_long_item_decimal_values(sub_items, "realistic_cost_r_estimate")),
                "median_stop_pct": _median_decimal_snapshot(_mid_long_stop_pct_values(sub_items)),
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_decimal_values(sub_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_decimal_values(sub_items, "mae_r")),
                "close_050_count": _mid_long_path_event_count(sub_items, "first_close_050_bar"),
                "touch_050_count": _mid_long_path_event_count(sub_items, "first_touch_050_bar"),
                "close_acceptance_conversion_pct": _pct_decimal(
                    _mid_long_path_event_count(sub_items, "first_close_050_bar"),
                    _mid_long_path_event_count(sub_items, "first_touch_050_bar"),
                ),
            }
        )
        rows.append(row)

    rows.sort(
        key=lambda row: (
            _mid_long_sub_setup_status_rank(str(row.get("research_status") or "")),
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return {
        "scope": "MID_LONG 1h sub-setup split lab, read-only",
        "method": (
            "Breaks MID_LONG into mutually exclusive sub-setups before optimizing geometry. "
            "The split uses pre-entry taxonomy, while path mix is post-entry diagnostic."
        ),
        "rows": rows,
        "candidate_rows": [
            row for row in rows if row.get("research_status") in {"KEEP_RESEARCH", "WATCH_WITH_CONSTRAINTS"}
        ],
        "reject_rows": [
            row for row in rows if row.get("research_status") in {"DRAFT_REJECT", "WAIT_OR_REDEFINE"}
        ],
        "summary": _mid_long_sub_setup_summary(rows),
        "guardrails": [
            "Sub-setup status is research language, not a production gate.",
            "MID_RANGE can be marked invalid for continuation research without deleting historical signal rows.",
            "A sub-setup needs chronological validation before V2.1 shadow promotion.",
        ],
    }


def _mid_long_sub_setup_label(taxonomy: dict[str, Any]) -> str:
    setup = str(taxonomy.get("setup_family") or "UNCLASSIFIED")
    breakout = str(taxonomy.get("breakout_state_pre_entry") or "")
    retest = str(taxonomy.get("retest_quality_pre_entry") or "")
    structure = str(taxonomy.get("structure_status") or "")
    if setup == "BREAKOUT_ATTEMPT" and breakout == "CLOSE_ACCEPTED":
        return "MID_LONG_BREAKOUT_PROXY_CANDIDATE"
    if setup == "BREAKOUT_ATTEMPT":
        return "MID_LONG_BREAKOUT_WICK_OR_UNCONFIRMED"
    if setup == "RETEST" and retest == "RETEST_HOLD_STRONG":
        return "MID_LONG_RETEST_HOLD_STRONG"
    if setup == "RETEST" and retest == "RETEST_HOLD_IN_ZONE":
        return "MID_LONG_RETEST_HOLD_IN_ZONE"
    if setup == "RETEST":
        return "MID_LONG_RETEST_WEAK_OR_FAILED"
    if setup == "SUPPORT_BOUNCE":
        return "MID_LONG_SUPPORT_BOUNCE"
    if setup == "MID_RANGE":
        return "MID_LONG_MID_RANGE_INVALID"
    if structure == "UNAVAILABLE":
        return "MID_LONG_UNCLASSIFIED_WAIT"
    return "MID_LONG_OTHER_STRUCTURE"


def _mid_long_sub_setup_definition(sub_label: str) -> str:
    definitions = {
        "MID_LONG_BREAKOUT_PROXY_CANDIDATE": "Breakout attempt with a pre-entry close-accepted proxy state; precise zone fields decide whether it deserves more research.",
        "MID_LONG_BREAKOUT_ACCEPTED": "Legacy name for breakout proxy candidate.",
        "MID_LONG_BREAKOUT_WICK_OR_UNCONFIRMED": "Breakout family, but no clear close-accepted state before entry.",
        "MID_LONG_RETEST_HOLD_STRONG": "Retest family with a strong hold/role-flip read.",
        "MID_LONG_RETEST_HOLD_IN_ZONE": "Retest family still inside the zone, not a clean hold.",
        "MID_LONG_RETEST_WEAK_OR_FAILED": "Retest family with weak/failed/unclear retest quality.",
        "MID_LONG_SUPPORT_BOUNCE": "Entry is associated with a support-zone bounce.",
        "MID_LONG_MID_RANGE_INVALID": "Entry is inside neutral/mid-range structure; invalid candidate for continuation research unless a hidden anchor is found.",
        "MID_LONG_UNCLASSIFIED_WAIT": "Structure unavailable or unknown; wait for better zone data before judging as MID_LONG continuation.",
        "MID_LONG_OTHER_STRUCTURE": "Available structure that does not fit breakout, retest, support bounce, or mid-range buckets.",
    }
    return definitions.get(sub_label, "Sub-setup research bucket.")


def _mid_long_sub_setup_family(sub_label: str) -> str:
    if "BREAKOUT" in sub_label:
        return "BREAKOUT"
    if "RETEST" in sub_label:
        return "RETEST"
    if "SUPPORT" in sub_label:
        return "SUPPORT"
    if "MID_RANGE" in sub_label:
        return "INVALID_RANGE"
    if "UNCLASSIFIED" in sub_label:
        return "WAIT_DATA"
    return "OTHER"


def _mid_long_sub_setup_status(row: dict[str, Any], *, sub_label: str, min_sample: int) -> str:
    closed = int(row.get("closed_count") or 0)
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    sl_share_delta = _decimal_or_none_snapshot(row.get("sl_share_delta_vs_baseline"))
    if closed < min_sample:
        return "SAMPLE_TOO_SMALL"
    if sub_label == "MID_LONG_MID_RANGE_INVALID":
        return "DRAFT_REJECT"
    if sub_label == "MID_LONG_UNCLASSIFIED_WAIT":
        return "WAIT_OR_REDEFINE"
    if avg_delta > Decimal("0.10") and total > 0 and (sl_share_delta is None or sl_share_delta <= Decimal("0")):
        return "KEEP_RESEARCH"
    if avg_delta > Decimal("0"):
        return "WATCH_WITH_CONSTRAINTS"
    if total < 0 and avg_delta <= Decimal("0"):
        return "DRAFT_REJECT"
    return "INCONCLUSIVE"


def _mid_long_sub_setup_action(row: dict[str, Any], *, sub_label: str, min_sample: int) -> str:
    status = _mid_long_sub_setup_status(row, sub_label=sub_label, min_sample=min_sample)
    if status == "KEEP_RESEARCH":
        return "Keep this sub-setup in the research queue and run time-split validation before any V2.1 shadow proposal."
    if status == "WATCH_WITH_CONSTRAINTS":
        return "Watch, but require extra constraints from path/cost/flow before promotion."
    if status == "DRAFT_REJECT":
        if sub_label == "MID_LONG_MID_RANGE_INVALID":
            return "Treat as invalid for MID_LONG continuation research until a hidden support/resistance anchor is proven."
        return "Reject as a standalone MID_LONG sub-setup for now; only revisit through a narrower interaction."
    if status == "WAIT_OR_REDEFINE":
        return "Do not judge as long setup yet; improve structure-zone coverage or keep it out of continuation research."
    if status == "SAMPLE_TOO_SMALL":
        return "Collect more samples before reading this bucket."
    return "Keep as diagnostic only."


def _mid_long_sub_setup_status_rank(status: str) -> int:
    return {
        "KEEP_RESEARCH": 6,
        "WATCH_WITH_CONSTRAINTS": 5,
        "INCONCLUSIVE": 4,
        "SAMPLE_TOO_SMALL": 3,
        "WAIT_OR_REDEFINE": 2,
        "DRAFT_REJECT": 1,
    }.get(status, 0)


def _mid_long_sub_setup_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("research_status") or "UNKNOWN") for row in rows)
    best = max(
        rows,
        key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
        default=None,
    )
    worst = min(
        rows,
        key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
        default=None,
    )
    return {
        "status_counts": dict(status_counts),
        "best_sub_setup": _mid_long_sub_setup_summary_row(best),
        "worst_sub_setup": _mid_long_sub_setup_summary_row(worst),
        "read": _mid_long_sub_setup_read(rows),
    }


def _mid_long_sub_setup_summary_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "sub_setup": row.get("sub_setup"),
        "closed_count": row.get("closed_count"),
        "tp_count": row.get("tp_count"),
        "sl_count": row.get("sl_count"),
        "realistic_total_r_closed": row.get("realistic_total_r_closed"),
        "realistic_avg_r_closed": row.get("realistic_avg_r_closed"),
        "realistic_avg_r_delta_vs_baseline": row.get("realistic_avg_r_delta_vs_baseline"),
        "research_status": row.get("research_status"),
    }


def _mid_long_sub_setup_read(rows: list[dict[str, Any]]) -> str:
    keep = [row for row in rows if row.get("research_status") == "KEEP_RESEARCH"]
    watch = [row for row in rows if row.get("research_status") == "WATCH_WITH_CONSTRAINTS"]
    if keep:
        return "SUB_SETUP_CANDIDATE_FOUND"
    if watch:
        return "SUB_SETUP_WATCH_ONLY"
    return "NO_SUB_SETUP_READY"


def _mid_long_breakout_accepted_deep_dive(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    breakout_items = _mid_long_breakout_accepted_items(items, taxonomy_by_id=taxonomy_by_id)
    control = _mid_long_perf_row(
        "BA-00",
        "Breakout proxy control",
        "sub_setup == MID_LONG_BREAKOUT_PROXY_CANDIDATE",
        breakout_items,
        baseline=baseline,
        required_fields=(),
        min_sample=min_sample,
    )
    field_rows = _mid_long_breakout_field_availability_rows(breakout_items)
    mechanism_rows = _mid_long_breakout_mechanism_rows(
        breakout_items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=control,
        min_sample=min_sample,
    )
    single_filter_rows = _mid_long_breakout_single_filter_rows(
        breakout_items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=control,
        min_sample=min_sample,
    )
    interaction_rows = _mid_long_breakout_interaction_rows(
        breakout_items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=control,
        min_sample=min_sample,
    )
    draft_rows = _mid_long_breakout_draft_rows(
        breakout_items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=control,
        field_rows=field_rows,
        min_sample=min_sample,
    )
    label_purity_rows = _mid_long_breakout_label_purity_rows(breakout_items)
    pre_entry_cause_rows = _mid_long_breakout_pre_entry_cause_rows(
        breakout_items,
        baseline=control,
        min_sample=min_sample,
    )
    cause_overlap_rows = _mid_long_breakout_cause_overlap_rows(
        breakout_items,
        baseline=control,
        min_sample=min_sample,
    )
    shadow_arm_rows = _mid_long_breakout_shadow_arm_rows(
        breakout_items,
        taxonomy_by_id=taxonomy_by_id,
        baseline=control,
        min_sample=min_sample,
    )
    pre_entry_geometry_path_tables = _mid_long_breakout_pre_entry_geometry_path_tables(
        breakout_items,
        baseline=control,
        min_sample=min_sample,
    )
    observable_path_rows = _mid_long_breakout_observable_path_rows(
        breakout_items,
        baseline=control,
        min_sample=min_sample,
    )
    return {
        "scope": "MID_LONG_BREAKOUT_PROXY_CANDIDATE deep dive",
        "method": (
            "Audits whether the breakout proxy is structurally proven with pre-entry zone data, then separates "
            "observable post-entry path from pre-entry hypothesized causes."
        ),
        "control": control,
        "label_purity_rows": label_purity_rows,
        "field_availability_rows": field_rows,
        "observable_path_rows": observable_path_rows,
        "mechanism_rows": mechanism_rows,
        "pre_entry_cause_rows": pre_entry_cause_rows,
        "cause_overlap_rows": cause_overlap_rows,
        "shadow_arm_rows": shadow_arm_rows,
        "evidence_path_tables": {
            "extension_bucket_x_path": _mid_long_taxonomy_path_cross_rows(
                breakout_items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="extension_bucket",
                taxonomy_label="Extension x path",
                baseline=control,
                min_sample=min_sample,
            ),
            "room_to_resistance_bucket_x_path": _mid_long_taxonomy_path_cross_rows(
                breakout_items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="room_to_resistance_bucket",
                taxonomy_label="Room x path",
                baseline=control,
                min_sample=min_sample,
            ),
            "flow_state_provisional_x_path": _mid_long_taxonomy_path_cross_rows(
                breakout_items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="flow_state_provisional",
                taxonomy_label="Flow x path",
                baseline=control,
                min_sample=min_sample,
            ),
            "crowding_bucket_x_path": _mid_long_taxonomy_path_cross_rows(
                breakout_items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="crowding_bucket",
                taxonomy_label="Crowding x path",
                baseline=control,
                min_sample=min_sample,
            ),
            "projected_cost_bucket_x_path": _mid_long_taxonomy_path_cross_rows(
                breakout_items,
                taxonomy_by_id=taxonomy_by_id,
                taxonomy_key="projected_cost_bucket",
                taxonomy_label="Cost x path",
                baseline=control,
                min_sample=min_sample,
            ),
        },
        "pre_entry_geometry_path_tables": pre_entry_geometry_path_tables,
        "single_filter_rows": single_filter_rows,
        "interaction_rows": interaction_rows,
        "draft_cohort_rows": draft_rows,
        "summary": _mid_long_breakout_summary(
            control=control,
            field_rows=field_rows,
            label_purity_rows=label_purity_rows,
            mechanism_rows=mechanism_rows,
            single_filter_rows=single_filter_rows,
            draft_rows=draft_rows,
            shadow_arm_rows=shadow_arm_rows,
        ),
        "guardrails": [
            "Breakout proxy is a research label, not a proven continuation rule.",
            "Post-entry path labels explain behavior; they must not become live entry gates.",
            "Cause rows can overlap; use overlap and shadow-arm rows before reading a cause as marginal contribution.",
            "POST_ENTRY_DIAGNOSTIC_ONLY filters are leakage-risk for initial entries and can only be used as delayed confirmation or management research.",
            "Room-to-resistance UNKNOWN is not a hard reject.",
            "No Signal Factory rule, scanner decision, TP/SL formula, threshold, or execution behavior is changed.",
        ],
    }


def _mid_long_breakout_accepted_items(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
        if _mid_long_sub_setup_label(taxonomy) in {
            "MID_LONG_BREAKOUT_PROXY_CANDIDATE",
            "MID_LONG_BREAKOUT_ACCEPTED",
        }:
            rows.append(item)
    return rows


def _mid_long_breakout_field_availability_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, label, source in MID_LONG_BREAKOUT_AUDIT_FIELDS:
        available = sum(1 for item in items if _mid_long_item_field_available(item, field))
        rows.append(
            {
                "field": field,
                "label": label,
                "source": source,
                "available_count": available,
                "missing_count": max(len(items) - available, 0),
                "available_pct": _pct_decimal(available, len(items)),
                "read": _mid_long_breakout_field_read(source=source, available_count=available, total=len(items)),
            }
        )
    rows.sort(
        key=lambda row: (
            row["source"] in {"precise_zone_metric", "missing_precise_zone_metric"},
            int(row["available_count"] or 0),
            str(row["field"]),
        )
    )
    return rows


def _mid_long_item_field_available(item: dict[str, Any], field: str) -> bool:
    value = item.get(field)
    if isinstance(value, dict):
        return bool(value)
    if value not in (None, ""):
        return True
    evidence = item.get("evidence_snapshot")
    if isinstance(evidence, dict):
        evidence_value = evidence.get(field)
        if isinstance(evidence_value, dict):
            return bool(evidence_value)
        return evidence_value not in (None, "")
    return False


def _mid_long_breakout_field_read(*, source: str, available_count: int, total: int) -> str:
    if total <= 0:
        return "NO_SAMPLE"
    if available_count <= 0:
        if source in {"precise_zone_metric", "missing_precise_zone_metric"}:
            return "MISSING_IN_CURRENT_LOG"
        return "UNAVAILABLE"
    if available_count < total:
        return "PARTIAL_AVAILABLE"
    return "AVAILABLE"


def _mid_long_breakout_label_purity_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: tuple[tuple[str, str, str, Callable[[dict[str, Any]], bool]], ...] = (
        (
            "LP-01",
            "Zone anchor exists",
            "zone_id, zone_lower, and zone_upper are present before judging the row as breakout proxy.",
            lambda item: all(_mid_long_item_field_available(item, field) for field in ("zone_id", "zone_lower", "zone_upper")),
        ),
        (
            "LP-02",
            "Zone was created before signal",
            "zone_created_at <= signal_timestamp. This guards against future-revised zones.",
            lambda item: _mid_long_time_lte(item.get("zone_created_at"), item.get("signal_timestamp")),
        ),
        (
            "LP-03",
            "Zone last touch is not future",
            "zone_last_touch_at <= signal_timestamp. A later touch cannot be part of the entry definition.",
            lambda item: _mid_long_time_lte(item.get("zone_last_touch_at"), item.get("signal_timestamp")),
        ),
        (
            "LP-04",
            "Breakout diagnostics marked no future data",
            "breakout_no_future_data == true from the zone diagnostics engine.",
            lambda item: bool(item.get("breakout_no_future_data") is True),
        ),
        (
            "LP-05",
            "Close acceptance fields exist",
            "close_penetration_atr, body_above_zone_ratio, close_location_in_candle, and upper_wick_to_body_ratio are available.",
            lambda item: all(
                _mid_long_item_field_available(item, field)
                for field in (
                    "close_penetration_atr",
                    "body_above_zone_ratio",
                    "close_location_in_candle",
                    "upper_wick_to_body_ratio",
                )
            ),
        ),
    )
    rows: list[dict[str, Any]] = []
    total = len(items)
    for check_id, label, expression, predicate in checks:
        pass_count = sum(1 for item in items if predicate(item))
        fail_count = max(total - pass_count, 0)
        rows.append(
            {
                "check_id": check_id,
                "label": label,
                "expression": expression,
                "total_count": total,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "pass_pct": _pct_decimal(pass_count, total),
                "status": "PASS" if total > 0 and fail_count == 0 else "FAIL" if fail_count > 0 else "NO_SAMPLE",
                "read": _mid_long_breakout_label_purity_read(check_id, fail_count=fail_count, total=total),
            }
        )
    return rows


def _mid_long_breakout_label_purity_read(check_id: str, *, fail_count: int, total: int) -> str:
    if total <= 0:
        return "No breakout proxy sample."
    if fail_count <= 0:
        return "Clean for this purity check."
    if check_id in {"LP-02", "LP-03", "LP-04"}:
        return "Leakage risk: this row must not support any entry-filter conclusion until audited."
    return "Definition-purity gap: keep as proxy, not accepted breakout."


def _mid_long_breakout_observable_path_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[_mid_long_breakout_observable_path(item)].append(item)
    rows: list[dict[str, Any]] = []
    for path, path_items in grouped.items():
        row = _mid_long_perf_row(
            f"BA-PATH:{path}",
            path,
            _mid_long_breakout_observable_path_expression(path),
            path_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "observable_path": path,
                "path_read": _mid_long_breakout_observable_path_read(path),
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_decimal_values(path_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_decimal_values(path_items, "mae_r")),
                "median_wick_decay_r": _median_decimal_snapshot(
                    _mid_long_item_decimal_values(path_items, "wick_to_close_decay_r")
                ),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _mid_long_observable_path_rank(str(row.get("observable_path") or "")),
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
        ),
        reverse=True,
    )
    return rows


def _mid_long_breakout_observable_path(item: dict[str, Any]) -> str:
    path = _mid_long_path_label_050(item)
    if path == "INSTANT_SL":
        return "EARLY_FAILURE"
    if path in {"SHALLOW_PROFIT_THEN_FAIL", "WICK_PROFIT_THEN_FAIL"}:
        return "WICK_BREAK_FAILURE"
    if path == "CLOSE_PROFIT_THEN_FAIL":
        return "CLOSE_ACCEPTED_FAILURE"
    if path in {"PULLBACK_TP", "DRAWDOWN_FIRST_THEN_TP"}:
        return "PULLBACK_WINNER"
    if path in {"WICK_PROFIT_THEN_TP", "CLEAN_CONTINUATION_TP"}:
        return "CLEAN_WINNER"
    if path == "SAME_BAR_AMBIGUOUS":
        return "SAME_BAR_AMBIGUOUS"
    return "OTHER_PATH"


def _mid_long_breakout_observable_path_expression(path: str) -> str:
    return {
        "EARLY_FAILURE": "SL with little/no favorable move after entry.",
        "WICK_BREAK_FAILURE": "Signal touched some favorable move by wick, but never earned close acceptance before failing.",
        "CLOSE_ACCEPTED_FAILURE": "Signal closed at least +0.50R, then failed before target.",
        "PULLBACK_WINNER": "Target hit after meaningful pullback.",
        "CLEAN_WINNER": "Target hit after clean continuation or wick-first continuation.",
        "SAME_BAR_AMBIGUOUS": "TP/SL ambiguity inside the same candle.",
        "OTHER_PATH": "Open, unknown, or other path.",
    }.get(path, "Observable path bucket.")


def _mid_long_breakout_observable_path_read(path: str) -> str:
    return {
        "EARLY_FAILURE": "Post-entry behavior only; use this to inspect pre-entry causes, not as an entry filter.",
        "WICK_BREAK_FAILURE": "Often looks like breakout failure; test thin close acceptance and large wick before entry.",
        "CLOSE_ACCEPTED_FAILURE": "Not a pure false breakout; study room, crowding, and management separately.",
        "PULLBACK_WINNER": "Do not over-tighten stops/filters that would remove pullback winners.",
        "CLEAN_WINNER": "Reference profile for accepted continuation.",
        "SAME_BAR_AMBIGUOUS": "Keep out of clean rule conclusions.",
    }.get(path, "Diagnostic only.")


def _mid_long_observable_path_rank(path: str) -> int:
    return {
        "EARLY_FAILURE": 7,
        "WICK_BREAK_FAILURE": 6,
        "CLOSE_ACCEPTED_FAILURE": 5,
        "SAME_BAR_AMBIGUOUS": 4,
        "PULLBACK_WINNER": 3,
        "CLEAN_WINNER": 2,
        "OTHER_PATH": 1,
    }.get(path, 0)


def _mid_long_breakout_pre_entry_cause_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    cause_specs: tuple[tuple[str, str, str, Callable[[dict[str, Any]], bool], str], ...] = (
        (
            "CAUSE-01",
            "THIN_CLOSE_ACCEPTANCE",
            "close_penetration_atr < 0.10 OR body_above_zone_ratio < 0.35 OR close_location_in_candle < 0.55",
            lambda item: _mid_long_breakout_thin_acceptance(item),
            "Definition weakness: breakout close exists, but acceptance is thin.",
        ),
        (
            "CAUSE-02",
            "LARGE_BREAKOUT_WICK",
            "upper_wick_to_body_ratio >= 1.00",
            lambda item: _mid_long_breakout_decimal_gte(item, "upper_wick_to_body_ratio", "1.00"),
            "Pre-entry wick risk, not the post-entry wick-decay filter.",
        ),
        (
            "CAUSE-03",
            "LATE_CHASE",
            "bars_since_breakout >= 2 AND entry_distance_from_zone_atr >= 1.00",
            lambda item: _mid_long_breakout_late_chase(item),
            "Entry may be late relative to the breakout zone.",
        ),
        (
            "CAUSE-04",
            "LOW_REMAINING_ROOM",
            "0 <= room_to_next_resistance_atr <= 0.75",
            lambda item: _mid_long_breakout_low_room(item),
            "Only rows with known next resistance are counted; missing room is not treated as safe.",
        ),
        (
            "CAUSE-05",
            "WEAK_INITIATIVE_FLOW",
            "volume_ratio_vs_lookback < 1.00 OR kline_taker_buy_ratio < 0.53 OR oi_change_pct <= 0",
            lambda item: _mid_long_breakout_weak_flow(item),
            "Flow is not confirming the long continuation strongly enough.",
        ),
        (
            "CAUSE-06",
            "HIGH_CROWDING",
            "funding_percentile_30d >= 75 OR oi_zscore >= 3.00",
            lambda item: _mid_long_breakout_high_crowding(item),
            "OI/funding may indicate crowded expansion, not automatically bullish quality.",
        ),
        (
            "CAUSE-07",
            "HIGH_PROJECTED_COST",
            "realistic_cost_r_estimate > 0.20",
            lambda item: _mid_long_breakout_decimal_gt(item, "realistic_cost_r_estimate", "0.20"),
            "Tradability damage, separate from breakout validity.",
        ),
    )
    rows: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for cause_id, label, expression, predicate, read in cause_specs:
        selected = [item for item in items if predicate(item)]
        assigned.update(str(item.get("signal_id") or id(item)) for item in selected)
        row = _mid_long_perf_row(
            cause_id,
            label,
            expression,
            selected,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "cause_id": cause_id,
                "cause_label": label,
                "cause_class": "PRE_ENTRY_HYPOTHESIS",
                "path_mix": _mid_long_path_mix(selected),
                "observable_path_mix": dict(Counter(_mid_long_breakout_observable_path(item) for item in selected)),
                "cause_read": read,
            }
        )
        rows.append(row)
    unknown = [item for item in items if str(item.get("signal_id") or id(item)) not in assigned]
    unknown_row = _mid_long_perf_row(
        "CAUSE-99",
        "UNKNOWN_CAUSE",
        "No current pre-entry cause flag matched.",
        unknown,
        baseline=baseline,
        required_fields=(),
        min_sample=min_sample,
    )
    unknown_row.update(
        {
            "cause_id": "CAUSE-99",
            "cause_label": "UNKNOWN_CAUSE",
            "cause_class": "PRE_ENTRY_HYPOTHESIS",
            "path_mix": _mid_long_path_mix(unknown),
            "observable_path_mix": dict(Counter(_mid_long_breakout_observable_path(item) for item in unknown)),
            "cause_read": "Current cause set does not explain these rows; inspect examples before adding more flags.",
        }
    )
    rows.append(unknown_row)
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0) >= min_sample,
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_breakout_cause_flag_specs() -> tuple[tuple[str, str, Callable[[dict[str, Any]], bool]], ...]:
    return (
        ("THIN_CLOSE_ACCEPTANCE", "close_penetration_atr/body_above_zone/close_location thin", _mid_long_breakout_thin_acceptance),
        ("LARGE_BREAKOUT_WICK", "upper_wick_to_body_ratio >= 1.00", lambda item: _mid_long_breakout_decimal_gte(item, "upper_wick_to_body_ratio", "1.00")),
        ("LATE_CHASE", "bars_since_breakout >= 2 AND entry_distance_from_zone_atr >= 1.00", _mid_long_breakout_late_chase),
        ("LOW_REMAINING_ROOM", "0 <= room_to_next_resistance_atr <= 0.75", _mid_long_breakout_low_room),
        ("WEAK_INITIATIVE_FLOW", "volume < 1 OR taker_buy < 0.53 OR oi_change <= 0", _mid_long_breakout_weak_flow),
        ("HIGH_CROWDING", "funding percentile >= 75 OR oi_zscore >= 3.00", _mid_long_breakout_high_crowding),
        ("HIGH_PROJECTED_COST", "realistic_cost_r_estimate > 0.20", _mid_long_breakout_high_cost),
    )


def _mid_long_breakout_cause_overlap_rows(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    specs = _mid_long_breakout_cause_flag_specs()
    selected_by_label: dict[str, list[dict[str, Any]]] = {
        label: [item for item in items if predicate(item)]
        for label, _expression, predicate in specs
    }
    rows: list[dict[str, Any]] = []
    for idx, (left_label, left_expression, _left_predicate) in enumerate(specs):
        left_items = selected_by_label[left_label]
        left_ids = {str(item.get("signal_id") or id(item)) for item in left_items}
        for right_label, right_expression, _right_predicate in specs[idx + 1 :]:
            right_items = selected_by_label[right_label]
            right_ids = {str(item.get("signal_id") or id(item)) for item in right_items}
            overlap_ids = left_ids & right_ids
            overlap_items = [
                item
                for item in items
                if str(item.get("signal_id") or id(item)) in overlap_ids
            ]
            row = _mid_long_perf_row(
                f"CAUSE-OVERLAP:{left_label}:{right_label}",
                f"{left_label} x {right_label}",
                f"({left_expression}) AND ({right_expression})",
                overlap_items,
                baseline=baseline,
                required_fields=(),
                min_sample=min_sample,
            )
            row.update(
                {
                    "left_cause": left_label,
                    "right_cause": right_label,
                    "left_count": len(left_items),
                    "right_count": len(right_items),
                    "overlap_count": len(overlap_items),
                    "overlap_pct_of_left": _pct_decimal(len(overlap_items), len(left_items)),
                    "overlap_pct_of_right": _pct_decimal(len(overlap_items), len(right_items)),
                    "observable_path_mix": dict(Counter(_mid_long_breakout_observable_path(item) for item in overlap_items)),
                    "read": _mid_long_breakout_cause_overlap_read(row, len(overlap_items), min_sample=min_sample),
                }
            )
            rows.append(row)
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0) >= min_sample,
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
            int(row.get("overlap_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_breakout_cause_overlap_read(row: dict[str, Any], overlap_count: int, *, min_sample: int) -> str:
    if overlap_count <= 0:
        return "No overlap in this sample."
    if overlap_count < min_sample:
        return "Overlap exists but sample is small; do not infer marginal contribution."
    if _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")) < 0:
        return "Damage overlaps here; compare shadow arms before treating either cause as standalone."
    return "Overlap is not damaging in this sample; avoid double-counting the cause."


def _mid_long_breakout_shadow_arm_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    arm_specs: tuple[tuple[str, str, str, Callable[[dict[str, Any], dict[str, Any]], str], str], ...] = (
        (
            "SHADOW_CONTROL",
            "V2 breakout proxy control",
            "all MID_LONG_BREAKOUT_PROXY_CANDIDATE rows",
            lambda _item, _taxonomy: "PASS",
            "Control only.",
        ),
        (
            "SHADOW_FLOW_01",
            "Exclude weak initiative flow",
            "WEAK_INITIATIVE_FLOW -> REJECT",
            lambda item, _taxonomy: "REJECT" if _mid_long_breakout_weak_flow(item) else "PASS",
            "Tests whether flow quality alone removes failure faster than winners.",
        ),
        (
            "SHADOW_ROOM_01",
            "Require sufficient room",
            "room_to_next_resistance_atr > 0.75; ROOM_UNKNOWN -> WAIT",
            lambda item, _taxonomy: _mid_long_breakout_room_arm_decision(item),
            "Room unavailable is not considered safe; it waits outside the retained cohort.",
        ),
        (
            "SHADOW_FLOW_ROOM_01",
            "Flow + room core candidate",
            "initiative flow not weak AND room available sufficient",
            lambda item, _taxonomy: _mid_long_breakout_flow_room_arm_decision(item),
            "Main entry-definition candidate before tradability and crowding layers.",
        ),
        (
            "SHADOW_TRADABLE_01",
            "Flow + room + tradability",
            "FLOW_ROOM pass AND realistic_cost_r_estimate <= 0.20",
            lambda item, _taxonomy: _mid_long_breakout_tradable_arm_decision(item),
            "Separates signal-quality filtering from economic tradability.",
        ),
        (
            "SHADOW_CROWDING_01",
            "Conditional crowding risk",
            "TRADABLE pass AND NOT(high crowding with weak/mixed flow, low room, or high extension)",
            lambda item, taxonomy: _mid_long_breakout_crowding_arm_decision(item, taxonomy),
            "Crowding is treated as a risk amplifier, not a standalone hard reject.",
        ),
    )
    rows: list[dict[str, Any]] = []
    for order, (arm_id, label, expression, decision_fn, read) in enumerate(arm_specs):
        passed: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
            decision = decision_fn(item, taxonomy)
            if decision == "PASS":
                passed.append(item)
            elif decision == "WAIT":
                waiting.append(item)
            else:
                rejected.append(item)
        row = _mid_long_perf_row(
            arm_id,
            label,
            expression,
            passed,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        rejected_perf = aggregate_signal_performance_items(rejected)
        waiting_perf = aggregate_signal_performance_items(waiting)
        baseline_tp = int(baseline.get("tp_count") or 0)
        baseline_sl = int(baseline.get("sl_count") or 0)
        row.update(
            {
                "arm_id": arm_id,
                "arm_order": order,
                "arm_status": "DRAFT_PREVIEW_READ_ONLY" if arm_id != "SHADOW_CONTROL" else "CONTROL",
                "retained_count": len(passed),
                "rejected_count": len(rejected),
                "waiting_count": len(waiting),
                "rejected_tp_count": rejected_perf["tp_count"],
                "rejected_sl_count": rejected_perf["sl_count"],
                "waiting_tp_count": waiting_perf["tp_count"],
                "waiting_sl_count": waiting_perf["sl_count"],
                "rejected_realistic_total_r_closed": rejected_perf["realistic_total_r_closed"],
                "waiting_realistic_total_r_closed": waiting_perf["realistic_total_r_closed"],
                "tp_retention_pct": _pct_decimal(int(row.get("tp_count") or 0), baseline_tp),
                "sl_rejection_pct": _pct_decimal(int(rejected_perf.get("sl_count") or 0), baseline_sl),
                "retained_observable_path_mix": dict(Counter(_mid_long_breakout_observable_path(item) for item in passed)),
                "rejected_observable_path_mix": dict(Counter(_mid_long_breakout_observable_path(item) for item in rejected)),
                "waiting_observable_path_mix": dict(Counter(_mid_long_breakout_observable_path(item) for item in waiting)),
                "arm_read": _mid_long_breakout_shadow_arm_read(row, rejected_perf, waiting_perf, read=read, min_sample=min_sample),
            }
        )
        rows.append(row)
    rows.sort(key=lambda row: int(row.get("arm_order") or 0))
    return rows


def _mid_long_breakout_shadow_arm_read(
    row: dict[str, Any],
    rejected_perf: dict[str, Any],
    waiting_perf: dict[str, Any],
    *,
    read: str,
    min_sample: int,
) -> str:
    retained = int(row.get("closed_count") or 0)
    if str(row.get("arm_id")) == "SHADOW_CONTROL":
        return read
    if retained < min_sample:
        return f"{read} Sample retained too small for promotion."
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    retained_total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    rejected_total = _decimal_or_zero_snapshot(rejected_perf.get("realistic_total_r_closed"))
    waiting_total = _decimal_or_zero_snapshot(waiting_perf.get("realistic_total_r_closed"))
    if retained_total > 0 and avg_delta > Decimal("0.10") and rejected_total < 0:
        return f"{read} Candidate for chronological validation, not live rule."
    if avg_delta > 0 and rejected_total < 0:
        return f"{read} Improves retained cohort but needs validation and overlap check."
    if waiting_total < 0 and retained_total >= 0:
        return f"{read} Unknown/wait bucket is damaging; inspect data availability before hard-gating."
    return f"{read} Not sufficient as a standalone shadow arm yet."


def _mid_long_breakout_room_arm_decision(item: dict[str, Any]) -> str:
    room = _mid_long_breakout_decimal(item, "room_to_next_resistance_atr")
    if room is None:
        return "WAIT"
    return "PASS" if room > Decimal("0.75") else "REJECT"


def _mid_long_breakout_flow_room_arm_decision(item: dict[str, Any]) -> str:
    room_decision = _mid_long_breakout_room_arm_decision(item)
    if room_decision == "WAIT":
        return "WAIT"
    if _mid_long_breakout_weak_flow(item) or room_decision == "REJECT":
        return "REJECT"
    return "PASS"


def _mid_long_breakout_tradable_arm_decision(item: dict[str, Any]) -> str:
    flow_room = _mid_long_breakout_flow_room_arm_decision(item)
    if flow_room != "PASS":
        return flow_room
    cost = _mid_long_breakout_decimal(item, "realistic_cost_r_estimate")
    if cost is None:
        return "WAIT"
    return "PASS" if cost <= Decimal("0.20") else "REJECT"


def _mid_long_breakout_crowding_arm_decision(item: dict[str, Any], taxonomy: dict[str, Any]) -> str:
    tradable = _mid_long_breakout_tradable_arm_decision(item)
    if tradable != "PASS":
        return tradable
    if _mid_long_breakout_crowding_danger_pair_precise(item, taxonomy):
        return "REJECT"
    return "PASS"


def _mid_long_breakout_pre_entry_geometry_path_tables(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, list[dict[str, Any]]]:
    specs: tuple[tuple[str, str, Callable[[dict[str, Any]], str]], ...] = (
        ("close_penetration_bucket_x_path", "Close penetration x path", _mid_long_close_penetration_bucket),
        ("body_above_zone_bucket_x_path", "Body above zone x path", _mid_long_body_above_zone_bucket),
        ("upper_wick_body_bucket_x_path", "Upper wick/body x path", _mid_long_upper_wick_body_bucket),
        ("bars_since_breakout_bucket_x_path", "Bars since breakout x path", _mid_long_bars_since_breakout_bucket),
        ("entry_distance_zone_bucket_x_path", "Entry distance from zone x path", _mid_long_entry_distance_zone_bucket),
        ("room_to_resistance_precise_bucket_x_path", "Room to resistance x path", _mid_long_room_to_resistance_precise_bucket),
    )
    return {
        key: _mid_long_breakout_geometry_path_rows(
            items,
            dimension_key=key,
            dimension_label=label,
            bucket_fn=bucket_fn,
            baseline=baseline,
            min_sample=min_sample,
        )
        for key, label, bucket_fn in specs
    }


def _mid_long_breakout_geometry_path_rows(
    items: list[dict[str, Any]],
    *,
    dimension_key: str,
    dimension_label: str,
    bucket_fn: Callable[[dict[str, Any]], str],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        bucket = bucket_fn(item)
        path = _mid_long_breakout_observable_path(item)
        grouped[f"{bucket} x {path}"].append(item)
    rows: list[dict[str, Any]] = []
    for cell, cell_items in grouped.items():
        row = _mid_long_perf_row(
            f"BA-GEOM:{dimension_key}:{cell}",
            cell,
            f"{dimension_label} == {cell}",
            cell_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "cell": cell,
                "taxonomy_key": dimension_key,
                "taxonomy_label": dimension_label,
                "path_label": cell.rsplit(" x ", 1)[-1],
                "read": _mid_long_geometry_path_read(cell=cell, row=row),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0),
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
        ),
        reverse=True,
    )
    return rows


def _mid_long_geometry_path_read(*, cell: str, row: dict[str, Any]) -> str:
    if int(row.get("closed_count") or 0) <= 0:
        return "No sample."
    if "UNKNOWN" in cell:
        return "Do not treat missing structure as safe or unsafe."
    if _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")) < 0:
        return "Negative cell; inspect whether this pre-entry bucket explains failure concentration."
    return "Positive cell; avoid filters that remove it without validation."


def _mid_long_time_lte(left: Any, right: Any) -> bool:
    left_dt = _mid_long_parse_time(left)
    right_dt = _mid_long_parse_time(right)
    if left_dt is None or right_dt is None:
        return False
    return left_dt <= right_dt


def _mid_long_parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        text = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mid_long_breakout_decimal(item: dict[str, Any], field: str) -> Decimal | None:
    return _decimal_or_none_snapshot(item.get(field))


def _mid_long_breakout_decimal_gte(item: dict[str, Any], field: str, threshold: str) -> bool:
    value = _mid_long_breakout_decimal(item, field)
    return value is not None and value >= Decimal(threshold)


def _mid_long_breakout_decimal_gt(item: dict[str, Any], field: str, threshold: str) -> bool:
    value = _mid_long_breakout_decimal(item, field)
    return value is not None and value > Decimal(threshold)


def _mid_long_breakout_decimal_lt(item: dict[str, Any], field: str, threshold: str) -> bool:
    value = _mid_long_breakout_decimal(item, field)
    return value is not None and value < Decimal(threshold)


def _mid_long_breakout_thin_acceptance(item: dict[str, Any]) -> bool:
    return (
        _mid_long_breakout_decimal_lt(item, "close_penetration_atr", "0.10")
        or _mid_long_breakout_decimal_lt(item, "body_above_zone_ratio", "0.35")
        or _mid_long_breakout_decimal_lt(item, "close_location_in_candle", "0.55")
    )


def _mid_long_breakout_late_chase(item: dict[str, Any]) -> bool:
    bars = _mid_long_breakout_decimal(item, "bars_since_breakout")
    distance = _mid_long_breakout_decimal(item, "entry_distance_from_zone_atr")
    return bars is not None and bars >= Decimal("2") and distance is not None and distance >= Decimal("1.00")


def _mid_long_breakout_low_room(item: dict[str, Any]) -> bool:
    room = _mid_long_breakout_decimal(item, "room_to_next_resistance_atr")
    return room is not None and Decimal("0") <= room <= Decimal("0.75")


def _mid_long_breakout_weak_flow(item: dict[str, Any]) -> bool:
    volume = _mid_long_evidence_value(item, "volume_ratio_vs_lookback")
    taker_buy = _mid_long_evidence_value(item, "kline_taker_buy_ratio")
    oi_change = _mid_long_evidence_value(item, "oi_change_pct")
    return (
        (volume is not None and volume < Decimal("1.00"))
        or (taker_buy is not None and taker_buy < Decimal("0.53"))
        or (oi_change is not None and oi_change <= Decimal("0"))
    )


def _mid_long_breakout_high_crowding(item: dict[str, Any]) -> bool:
    funding = _mid_long_evidence_value(item, "funding_percentile_30d")
    oi_z = _mid_long_evidence_value(item, "oi_zscore")
    return (funding is not None and funding >= Decimal("75")) or (oi_z is not None and oi_z >= Decimal("3.00"))


def _mid_long_breakout_high_cost(item: dict[str, Any]) -> bool:
    return _mid_long_breakout_decimal_gt(item, "realistic_cost_r_estimate", "0.20")


def _mid_long_breakout_high_extension(item: dict[str, Any], taxonomy: dict[str, Any]) -> bool:
    if taxonomy.get("extension_bucket") in {"HIGH_EXTENSION", "EXTREME_EXTENSION"}:
        return True
    extension = _mid_long_evidence_value(item, "atr_extension_normalized")
    return extension is not None and extension >= Decimal("1.50")


def _mid_long_breakout_crowding_danger_pair_precise(item: dict[str, Any], taxonomy: dict[str, Any]) -> bool:
    if not _mid_long_breakout_high_crowding(item):
        return False
    flow_danger = _mid_long_breakout_weak_flow(item) or taxonomy.get("flow_state_provisional") in {"MIXED", "WEAK"}
    return bool(flow_danger or _mid_long_breakout_low_room(item) or _mid_long_breakout_high_extension(item, taxonomy))


def _mid_long_close_penetration_bucket(item: dict[str, Any]) -> str:
    value = _mid_long_breakout_decimal(item, "close_penetration_atr")
    if value is None:
        return "PENETRATION_UNKNOWN"
    if value < Decimal("0.10"):
        return "THIN_PENETRATION"
    if value < Decimal("0.30"):
        return "MODERATE_PENETRATION"
    return "STRONG_PENETRATION"


def _mid_long_body_above_zone_bucket(item: dict[str, Any]) -> str:
    value = _mid_long_breakout_decimal(item, "body_above_zone_ratio")
    if value is None:
        return "BODY_ZONE_UNKNOWN"
    if value < Decimal("0.35"):
        return "LOW_BODY_ACCEPTANCE"
    if value < Decimal("0.70"):
        return "MID_BODY_ACCEPTANCE"
    return "HIGH_BODY_ACCEPTANCE"


def _mid_long_upper_wick_body_bucket(item: dict[str, Any]) -> str:
    value = _mid_long_breakout_decimal(item, "upper_wick_to_body_ratio")
    if value is None:
        return "WICK_UNKNOWN"
    if value < Decimal("0.50"):
        return "LOW_UPPER_WICK"
    if value < Decimal("1.00"):
        return "MID_UPPER_WICK"
    return "HIGH_UPPER_WICK"


def _mid_long_bars_since_breakout_bucket(item: dict[str, Any]) -> str:
    value = _mid_long_breakout_decimal(item, "bars_since_breakout")
    if value is None:
        return "BARS_UNKNOWN"
    if value <= Decimal("0"):
        return "BREAKOUT_ENTRY"
    if value <= Decimal("1"):
        return "POST_BREAKOUT_NORMAL"
    return "LATE_BREAKOUT_CHASE"


def _mid_long_entry_distance_zone_bucket(item: dict[str, Any]) -> str:
    value = _mid_long_breakout_decimal(item, "entry_distance_from_zone_atr")
    if value is None:
        return "ENTRY_DISTANCE_UNKNOWN"
    if value < Decimal("0.30"):
        return "NEAR_ZONE"
    if value < Decimal("1.00"):
        return "NORMAL_DISTANCE"
    return "FAR_FROM_ZONE"


def _mid_long_room_to_resistance_precise_bucket(item: dict[str, Any]) -> str:
    value = _mid_long_breakout_decimal(item, "room_to_next_resistance_atr")
    if value is None:
        return "ROOM_UNKNOWN"
    if value < Decimal("0"):
        return "RESISTANCE_COLLISION"
    if value <= Decimal("0.75"):
        return "LOW_ROOM"
    if value <= Decimal("1.50"):
        return "MODERATE_ROOM"
    return "HIGH_ROOM"


def _mid_long_breakout_mechanism_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[_mid_long_breakout_mechanism(item)].append(item)
    rows: list[dict[str, Any]] = []
    for mechanism, mechanism_items in grouped.items():
        row = _mid_long_perf_row(
            f"BA-MECH:{mechanism}",
            mechanism,
            _mid_long_breakout_mechanism_expression(mechanism),
            mechanism_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "mechanism": mechanism,
                "mechanism_read": _mid_long_breakout_mechanism_read(mechanism),
                "path_mix": _mid_long_path_mix(mechanism_items),
                "flow_mix": _mid_long_taxonomy_mix(
                    mechanism_items,
                    taxonomy_by_id=taxonomy_by_id,
                    taxonomy_key="flow_state_provisional",
                ),
                "room_mix": _mid_long_taxonomy_mix(
                    mechanism_items,
                    taxonomy_by_id=taxonomy_by_id,
                    taxonomy_key="room_to_resistance_bucket",
                ),
                "median_mfe_r": _median_decimal_snapshot(_mid_long_item_decimal_values(mechanism_items, "mfe_r")),
                "median_mae_r": _median_decimal_snapshot(_mid_long_item_decimal_values(mechanism_items, "mae_r")),
                "median_wick_decay_r": _median_decimal_snapshot(
                    _mid_long_item_decimal_values(mechanism_items, "wick_to_close_decay_r")
                ),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _mid_long_breakout_mechanism_rank(str(row.get("mechanism") or "")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_breakout_mechanism(item: dict[str, Any]) -> str:
    path = _mid_long_path_label_050(item)
    if path in {"INSTANT_SL", "SHALLOW_PROFIT_THEN_FAIL", "WICK_PROFIT_THEN_FAIL", "SAME_BAR_AMBIGUOUS"}:
        return "STRUCTURAL_FALSE_BREAKOUT_CANDIDATE"
    if path == "CLOSE_PROFIT_THEN_FAIL":
        return "ACCEPTED_BUT_FAILED_CONTINUATION"
    if path in {"PULLBACK_TP", "DRAWDOWN_FIRST_THEN_TP", "WICK_PROFIT_THEN_TP", "CLEAN_CONTINUATION_TP"}:
        return "VALID_CONTINUATION_WITH_PULLBACK"
    return "OPEN_OR_OTHER_PATH"


def _mid_long_breakout_mechanism_expression(mechanism: str) -> str:
    expressions = {
        "STRUCTURAL_FALSE_BREAKOUT_CANDIDATE": "Path has instant/shallow/wick fail or same-candle ambiguity.",
        "ACCEPTED_BUT_FAILED_CONTINUATION": "Path closed at least +0.50R, then failed before target.",
        "VALID_CONTINUATION_WITH_PULLBACK": "Path reached target after continuation or material pullback.",
        "OPEN_OR_OTHER_PATH": "Open/other path; keep out of closed-result conclusions.",
    }
    return expressions.get(mechanism, "Breakout mechanism bucket.")


def _mid_long_breakout_mechanism_read(mechanism: str) -> str:
    reads = {
        "STRUCTURAL_FALSE_BREAKOUT_CANDIDATE": "Candidate label-purity problem; test pre-entry close/wick/zone quality.",
        "ACCEPTED_BUT_FAILED_CONTINUATION": "Not a pure false breakout; study room, crowding, and management separately.",
        "VALID_CONTINUATION_WITH_PULLBACK": "Do not over-tighten filters that remove pullback winners.",
        "OPEN_OR_OTHER_PATH": "Diagnostic only until closed.",
    }
    return reads.get(mechanism, "Breakout mechanism diagnostic.")


def _mid_long_breakout_mechanism_rank(mechanism: str) -> int:
    return {
        "STRUCTURAL_FALSE_BREAKOUT_CANDIDATE": 4,
        "ACCEPTED_BUT_FAILED_CONTINUATION": 3,
        "VALID_CONTINUATION_WITH_PULLBACK": 2,
        "OPEN_OR_OTHER_PATH": 1,
    }.get(mechanism, 0)


def _mid_long_breakout_single_filter_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    scenarios = (
        (
            "BA-02A",
            "Exclude wick/unconfirmed proxy",
            "breakout_state_pre_entry == CLOSE_ACCEPTED",
            lambda _item, taxonomy: taxonomy.get("breakout_state_pre_entry") == "CLOSE_ACCEPTED",
            "PRE_ENTRY_PROXY",
        ),
        (
            "BA-02B",
            "Exclude high wick decay",
            "wick_to_close_decay_r < 0.50 OR unavailable",
            lambda item, _taxonomy: not _mid_long_high_wick_decay(item),
            "POST_ENTRY_DIAGNOSTIC_ONLY",
        ),
        (
            "BA-02C",
            "Exclude high/extreme extension",
            "extension_bucket NOT IN HIGH/EXTREME",
            lambda _item, taxonomy: taxonomy.get("extension_bucket") not in {"HIGH_EXTENSION", "EXTREME_EXTENSION"},
            "PRE_ENTRY_PROXY",
        ),
        (
            "BA-02D",
            "Exclude low room when available",
            "room_to_resistance_bucket != LOW_ROOM; ROOM_UNAVAILABLE retained",
            lambda _item, taxonomy: taxonomy.get("room_to_resistance_bucket") != "LOW_ROOM",
            "PRE_ENTRY_PROXY_WITH_UNKNOWN_ALLOWED",
        ),
        (
            "BA-02E",
            "Exclude weak flow",
            "flow_state_provisional != WEAK",
            lambda _item, taxonomy: taxonomy.get("flow_state_provisional") != "WEAK",
            "PRE_ENTRY_EVIDENCE",
        ),
        (
            "BA-02F",
            "Exclude extreme cost",
            "projected_cost_bucket != EXTREME_COST",
            lambda _item, taxonomy: taxonomy.get("projected_cost_bucket") != "EXTREME_COST",
            "EXECUTION_REALISM",
        ),
        (
            "BA-02G",
            "Exclude crowding danger pair",
            "NOT(high/extreme crowding with high extension, mixed/weak flow, or low room)",
            lambda _item, taxonomy: not _mid_long_breakout_crowding_danger_pair(taxonomy),
            "PRE_ENTRY_INTERACTION",
        ),
    )
    rows = [
        _mid_long_breakout_filter_row(
            filter_id,
            label,
            expression,
            items,
            taxonomy_by_id=taxonomy_by_id,
            baseline=baseline,
            predicate=predicate,
            min_sample=min_sample,
            filter_class=filter_class,
        )
        for filter_id, label, expression, predicate, filter_class in scenarios
    ]
    rows.sort(
        key=lambda row: (
            _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
            _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_breakout_filter_row(
    filter_id: str,
    label: str,
    expression: str,
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    predicate: Any,
    min_sample: int,
    filter_class: str,
) -> dict[str, Any]:
    retained: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
        (retained if predicate(item, taxonomy) else removed).append(item)
    row = _mid_long_perf_row(
        filter_id,
        label,
        expression,
        retained,
        baseline=baseline,
        required_fields=(),
        min_sample=min_sample,
    )
    removed_perf = aggregate_signal_performance_items(removed)
    row.update(
        {
            "filter_class": filter_class,
            "retained_count": len(retained),
            "removed_count": len(removed),
            "removed_tp_count": removed_perf["tp_count"],
            "removed_sl_count": removed_perf["sl_count"],
            "removed_realistic_total_r_closed": removed_perf["realistic_total_r_closed"],
            "retained_path_mix": _mid_long_path_mix(retained),
            "removed_path_mix": _mid_long_path_mix(removed),
            "removed_mechanism_mix": dict(Counter(_mid_long_breakout_mechanism(item) for item in removed)),
            "filter_read": _mid_long_breakout_filter_read(row, removed_perf, filter_class=filter_class),
        }
    )
    return row


def _mid_long_high_wick_decay(item: dict[str, Any]) -> bool:
    value = _decimal_or_none_snapshot(item.get("wick_to_close_decay_r"))
    return value is not None and value >= Decimal("0.50")


def _mid_long_breakout_crowding_danger_pair(taxonomy: dict[str, Any]) -> bool:
    crowding = taxonomy.get("crowding_bucket") in {"HIGH_CROWDING", "EXTREME_CROWDING"}
    danger_pair = (
        taxonomy.get("extension_bucket") in {"HIGH_EXTENSION", "EXTREME_EXTENSION"}
        or taxonomy.get("flow_state_provisional") in {"MIXED", "WEAK"}
        or taxonomy.get("room_to_resistance_bucket") == "LOW_ROOM"
    )
    return bool(crowding and danger_pair)


def _mid_long_breakout_filter_read(
    row: dict[str, Any],
    removed_perf: dict[str, Any],
    *,
    filter_class: str,
) -> str:
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    retained_total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    removed_total = _decimal_or_zero_snapshot(removed_perf.get("realistic_total_r_closed"))
    if filter_class == "POST_ENTRY_DIAGNOSTIC_ONLY":
        return "Post-entry diagnostic only; do not promote as entry gate."
    if avg_delta > Decimal("0.10") and retained_total > 0 and removed_total < 0:
        return "Promising breakout damage-isolation candidate; validate chronologically before any shadow rule."
    if avg_delta > 0 and removed_total < 0:
        return "Improves breakout cohort, but still not enough alone for promotion."
    if avg_delta > 0:
        return "Average improves, but removed bucket is not clearly isolated damage."
    return "Does not improve breakout cohort."


def _mid_long_breakout_interaction_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    interactions = (
        (
            "BA-03A",
            "High extension + low room",
            "extension high/extreme AND room low",
            lambda taxonomy: taxonomy.get("extension_bucket") in {"HIGH_EXTENSION", "EXTREME_EXTENSION"}
            and taxonomy.get("room_to_resistance_bucket") == "LOW_ROOM",
        ),
        (
            "BA-03B",
            "High crowding + high extension",
            "crowding high/extreme AND extension high/extreme",
            lambda taxonomy: taxonomy.get("crowding_bucket") in {"HIGH_CROWDING", "EXTREME_CROWDING"}
            and taxonomy.get("extension_bucket") in {"HIGH_EXTENSION", "EXTREME_EXTENSION"},
        ),
        (
            "BA-03C",
            "High crowding + mixed/weak flow",
            "crowding high/extreme AND flow mixed/weak",
            lambda taxonomy: taxonomy.get("crowding_bucket") in {"HIGH_CROWDING", "EXTREME_CROWDING"}
            and taxonomy.get("flow_state_provisional") in {"MIXED", "WEAK"},
        ),
        (
            "BA-03D",
            "Weak flow + low room",
            "flow weak AND room low",
            lambda taxonomy: taxonomy.get("flow_state_provisional") == "WEAK"
            and taxonomy.get("room_to_resistance_bucket") == "LOW_ROOM",
        ),
        (
            "BA-03E",
            "Confirmed flow + low room",
            "flow confirmed AND room low",
            lambda taxonomy: taxonomy.get("flow_state_provisional") == "CONFIRMED"
            and taxonomy.get("room_to_resistance_bucket") == "LOW_ROOM",
        ),
    )
    rows: list[dict[str, Any]] = []
    for interaction_id, label, expression, predicate in interactions:
        selected: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
            if predicate(taxonomy):
                selected.append(item)
        row = _mid_long_perf_row(
            interaction_id,
            label,
            expression,
            selected,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        row.update(
            {
                "interaction_id": interaction_id,
                "path_mix": _mid_long_path_mix(selected),
                "mechanism_mix": dict(Counter(_mid_long_breakout_mechanism(item) for item in selected)),
                "interaction_read": _mid_long_breakout_interaction_read(row),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0) >= min_sample,
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
            int(row.get("closed_count") or 0),
        ),
        reverse=True,
    )
    return rows


def _mid_long_breakout_interaction_read(row: dict[str, Any]) -> str:
    closed = int(row.get("closed_count") or 0)
    total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    if closed <= 0:
        return "No sample in this interaction."
    if total < 0 and avg_delta < 0:
        return "Interaction is worse than breakout control; candidate damage cluster."
    if total < 0:
        return "Negative cluster, but compare removed winners before treating as filter."
    return "Not harmful in this sample."


def _mid_long_breakout_draft_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    field_rows: list[dict[str, Any]],
    min_sample: int,
) -> list[dict[str, Any]]:
    precise_ready = _mid_long_breakout_precise_zone_ready(field_rows)
    drafts = (
        (
            "BA-04A",
            "DRAFT_BREAKOUT_STRUCTURAL_PROXY",
            "close accepted proxy; exact zone penetration fields are reported separately",
            lambda _item, taxonomy: taxonomy.get("breakout_state_pre_entry") == "CLOSE_ACCEPTED",
        ),
        (
            "BA-04B",
            "DRAFT_BREAKOUT_SPATIAL_PROXY",
            "structural proxy + not high/extreme extension + room not low",
            lambda _item, taxonomy: taxonomy.get("breakout_state_pre_entry") == "CLOSE_ACCEPTED"
            and taxonomy.get("extension_bucket") not in {"HIGH_EXTENSION", "EXTREME_EXTENSION"}
            and taxonomy.get("room_to_resistance_bucket") != "LOW_ROOM",
        ),
        (
            "BA-04C",
            "DRAFT_BREAKOUT_EVIDENCE_PROXY",
            "spatial proxy + flow not weak + cost not extreme",
            lambda _item, taxonomy: taxonomy.get("breakout_state_pre_entry") == "CLOSE_ACCEPTED"
            and taxonomy.get("extension_bucket") not in {"HIGH_EXTENSION", "EXTREME_EXTENSION"}
            and taxonomy.get("room_to_resistance_bucket") != "LOW_ROOM"
            and taxonomy.get("flow_state_provisional") != "WEAK"
            and taxonomy.get("projected_cost_bucket") != "EXTREME_COST",
        ),
    )
    rows: list[dict[str, Any]] = []
    for draft_id, label, expression, predicate in drafts:
        selected: list[dict[str, Any]] = []
        discarded: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
            (selected if predicate(item, taxonomy) else discarded).append(item)
        row = _mid_long_perf_row(
            draft_id,
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
                "draft_id": draft_id,
                "draft_status": _mid_long_breakout_draft_status(row, precise_ready=precise_ready, min_sample=min_sample),
                "discarded_count": len(discarded),
                "discarded_tp_count": discarded_perf["tp_count"],
                "discarded_sl_count": discarded_perf["sl_count"],
                "discarded_realistic_total_r_closed": discarded_perf["realistic_total_r_closed"],
                "retained_path_mix": _mid_long_path_mix(selected),
                "discarded_path_mix": _mid_long_path_mix(discarded),
                "draft_read": _mid_long_breakout_draft_read(row, precise_ready=precise_ready),
            }
        )
        rows.append(row)
    return rows


def _mid_long_breakout_precise_zone_ready(field_rows: list[dict[str, Any]]) -> bool:
    precise = [row for row in field_rows if row.get("source") in {"precise_zone_metric", "missing_precise_zone_metric"}]
    return bool(precise) and all(int(row.get("available_count") or 0) > 0 for row in precise)


def _mid_long_breakout_draft_status(
    row: dict[str, Any],
    *,
    precise_ready: bool,
    min_sample: int,
) -> str:
    if int(row.get("closed_count") or 0) < min_sample:
        return "SAMPLE_TOO_SMALL"
    if not precise_ready:
        return "PROXY_ONLY_NEEDS_ZONE_FIELDS"
    total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    sl_delta = _decimal_or_none_snapshot(row.get("sl_share_delta_vs_baseline"))
    if total > 0 and avg_delta > Decimal("0.10") and (sl_delta is None or sl_delta <= 0):
        return "READY_FOR_WALK_FORWARD"
    if avg_delta > 0:
        return "WATCH_MORE"
    return "NOT_IMPROVING"


def _mid_long_breakout_draft_read(row: dict[str, Any], *, precise_ready: bool) -> str:
    if not precise_ready:
        return "Use as proxy research only; exact breakout close/body/zone-width metrics are not in current log."
    if str(row.get("draft_status")) == "READY_FOR_WALK_FORWARD":
        return "Candidate for chronological validation, not live rule."
    if _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")) > 0:
        return "Improves average, but not enough for promotion."
    return "Does not improve breakout accepted control."


def _mid_long_breakout_summary(
    *,
    control: dict[str, Any],
    field_rows: list[dict[str, Any]],
    label_purity_rows: list[dict[str, Any]],
    mechanism_rows: list[dict[str, Any]],
    single_filter_rows: list[dict[str, Any]],
    draft_rows: list[dict[str, Any]],
    shadow_arm_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    precise_missing = [
        row
        for row in field_rows
        if row.get("source") in {"precise_zone_metric", "missing_precise_zone_metric"}
        and int(row.get("available_count") or 0) <= 0
    ]
    best_filter = max(
        single_filter_rows,
        key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
        default=None,
    )
    worst_mechanism = min(
        mechanism_rows,
        key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_total_r_closed")),
        default=None,
    )
    best_draft = max(
        draft_rows,
        key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
        default=None,
    )
    best_shadow = max(
        [row for row in shadow_arm_rows if row.get("arm_id") != "SHADOW_CONTROL"],
        key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")),
        default=None,
    )
    if precise_missing:
        label_purity_read = "PROXY_LABEL_ONLY_NEEDS_ZONE_FIELDS"
    elif any(str(row.get("status")) == "FAIL" for row in label_purity_rows):
        label_purity_read = "PURITY_CHECK_HAS_FAILURES"
    else:
        label_purity_read = "PRE_ENTRY_ZONE_PURITY_PASS"
    return {
        "read": _mid_long_breakout_deep_dive_read(
            control=control,
            best_filter=best_filter,
            best_draft=best_draft,
            precise_missing=precise_missing,
        ),
        "label_purity_read": label_purity_read,
        "precise_zone_fields_missing_count": len(precise_missing),
        "label_purity_failed_count": sum(1 for row in label_purity_rows if str(row.get("status")) == "FAIL"),
        "best_filter": _mid_long_breakout_summary_row(best_filter),
        "worst_mechanism": _mid_long_breakout_summary_row(worst_mechanism),
        "best_draft": _mid_long_breakout_summary_row(best_draft),
        "best_shadow_arm": _mid_long_breakout_summary_row(best_shadow),
    }


def _mid_long_breakout_deep_dive_read(
    *,
    control: dict[str, Any],
    best_filter: dict[str, Any] | None,
    best_draft: dict[str, Any] | None,
    precise_missing: list[dict[str, Any]],
) -> str:
    if int(control.get("closed_count") or 0) <= 0:
        return "NO_BREAKOUT_SAMPLE"
    if precise_missing:
        return "BREAKOUT_PROXY_ONLY"
    if best_draft and str(best_draft.get("draft_status")) == "READY_FOR_WALK_FORWARD":
        return "BREAKOUT_DRAFT_READY_FOR_VALIDATION"
    if best_filter and _decimal_or_zero_snapshot(best_filter.get("realistic_avg_r_delta_vs_baseline")) > 0:
        return "BREAKOUT_FILTER_WATCH_ONLY"
    return "BREAKOUT_NOT_IMPROVING"


def _mid_long_breakout_summary_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row.get("filter_id") or row.get("draft_id") or row.get("mechanism"),
        "label": row.get("label"),
        "closed_count": row.get("closed_count"),
        "tp_count": row.get("tp_count"),
        "sl_count": row.get("sl_count"),
        "realistic_total_r_closed": row.get("realistic_total_r_closed"),
        "realistic_avg_r_closed": row.get("realistic_avg_r_closed"),
        "realistic_avg_r_delta_vs_baseline": row.get("realistic_avg_r_delta_vs_baseline"),
        "status": row.get("draft_status") or row.get("verdict") or row.get("mechanism"),
    }


def _mid_long_taxonomy_mix(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    taxonomy_key: str,
) -> dict[str, int]:
    values: Counter[str] = Counter()
    for idx, item in enumerate(items):
        taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
        values[str(taxonomy.get(taxonomy_key) or "UNKNOWN")] += 1
    return dict(values)


def _mid_long_dominant_counter_key(values: dict[str, int]) -> str | None:
    if not values:
        return None
    return max(values.items(), key=lambda item: item[1])[0]


def _mid_long_economic_rows_by_path(
    items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[_mid_long_path_label_050(item)].append(item)
    rows = [
        _mid_long_economic_row(
            f"PATH_ECON:{label}",
            label,
            f"path_label_050 == {label}",
            label_items,
            baseline=baseline,
            min_sample=min_sample,
        )
        for label, label_items in grouped.items()
    ]
    for row in rows:
        row["path_label"] = row["label"]
        row["path_read"] = _mid_long_path_sequence_read(str(row["label"]))
    rows.sort(
        key=lambda row: (
            _mid_long_path_priority(str(row.get("path_label") or "")),
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
        ),
        reverse=True,
    )
    return rows


def _mid_long_economic_rows_by_taxonomy(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    taxonomy_key: str,
    label_prefix: str,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
        grouped[str(taxonomy.get(taxonomy_key) or "UNKNOWN")].append(item)
    rows = [
        _mid_long_economic_row(
            f"ECON:{taxonomy_key}:{state}",
            state,
            f"{taxonomy_key} == {state}",
            state_items,
            baseline=baseline,
            min_sample=min_sample,
        )
        for state, state_items in grouped.items()
    ]
    for row in rows:
        row["taxonomy_key"] = taxonomy_key
        row["taxonomy_label"] = label_prefix
        row["state"] = row["label"]
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0),
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
        ),
        reverse=True,
    )
    return rows


def _mid_long_economic_row(
    filter_id: str,
    label: str,
    expression: str,
    row_items: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    row = _mid_long_perf_row(
        filter_id,
        label,
        expression,
        row_items,
        baseline=baseline,
        required_fields=(),
        min_sample=min_sample,
    )
    closed_count = int(row.get("closed_count") or 0)
    ideal_total = _decimal_or_zero_snapshot(row.get("ideal_total_r_closed"))
    realistic_total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    row.update(
        {
            "ideal_avg_r_closed": ideal_total / Decimal(closed_count) if closed_count > 0 else None,
            "execution_drag_r": ideal_total - realistic_total,
            "execution_drag_avg_r": (ideal_total - realistic_total) / Decimal(closed_count) if closed_count > 0 else None,
            "median_cost_r": _median_decimal_snapshot(_mid_long_item_decimal_values(row_items, "realistic_cost_r_estimate")),
            "median_stop_pct": _median_decimal_snapshot(_mid_long_stop_pct_values(row_items)),
            "median_mfe_r": _median_decimal_snapshot(_mid_long_item_decimal_values(row_items, "mfe_r")),
            "median_mae_r": _median_decimal_snapshot(_mid_long_item_decimal_values(row_items, "mae_r")),
            "median_time_to_tp_bars": _median_decimal_snapshot(
                _mid_long_path_event_decimal_values(row_items, "tp_hit_bar")
            ),
            "touch_050_count": _mid_long_path_event_count(row_items, "first_touch_050_bar"),
            "close_050_count": _mid_long_path_event_count(row_items, "first_close_050_bar"),
            "close_acceptance_conversion_pct": _pct_decimal(
                _mid_long_path_event_count(row_items, "first_close_050_bar"),
                _mid_long_path_event_count(row_items, "first_touch_050_bar"),
            ),
        }
    )
    return row


def _mid_long_integrity_flags(
    items: list[dict[str, Any]],
    *,
    path_rows: list[dict[str, Any]],
    room_rows: list[dict[str, Any]],
    min_sample: int,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    clean = next((row for row in path_rows if row.get("path_label") == "CLEAN_CONTINUATION_TP"), None)
    if clean and int(clean.get("closed_count") or 0) >= min_sample:
        clean_avg = _decimal_or_zero_snapshot(clean.get("realistic_avg_r_closed"))
        if clean_avg < Decimal("1.0"):
            flags.append(
                {
                    "flag_id": "CLEAN_CONTINUATION_LOW_REALISTIC_R",
                    "severity": "HIGH",
                    "read": "CLEAN_CONTINUATION_TP exists, but realistic average is far below the nominal target.",
                    "sample_count": clean.get("closed_count"),
                    "realistic_avg_r_closed": clean.get("realistic_avg_r_closed"),
                    "execution_drag_avg_r": clean.get("execution_drag_avg_r"),
                    "next_check": "Check cost_R, stop_pct, same-bar handling, and path classifier priority.",
                }
            )
    room_unavailable = next((row for row in room_rows if row.get("state") == "ROOM_UNAVAILABLE"), None)
    if room_unavailable and _decimal_or_zero_snapshot(room_unavailable.get("sample_retention_pct")) >= Decimal("50"):
        flags.append(
            {
                "flag_id": "ROOM_UNAVAILABLE_HIGH",
                "severity": "MEDIUM",
                "read": "Most MID_LONG rows do not have usable room-to-resistance data yet.",
                "sample_count": room_unavailable.get("closed_count"),
                "sample_retention_pct": room_unavailable.get("sample_retention_pct"),
                "next_check": "Do not make room a gate until coverage and zone anchoring are audited.",
            }
        )
    room_by_state = {str(row.get("state")): row for row in room_rows}
    low_avg = _decimal_or_none_snapshot((room_by_state.get("LOW_ROOM") or {}).get("realistic_avg_r_closed"))
    moderate_avg = _decimal_or_none_snapshot((room_by_state.get("MODERATE_ROOM") or {}).get("realistic_avg_r_closed"))
    high_avg = _decimal_or_none_snapshot((room_by_state.get("HIGH_ROOM") or {}).get("realistic_avg_r_closed"))
    if low_avg is not None and moderate_avg is not None and high_avg is not None and moderate_avg < low_avg and moderate_avg < high_avg:
        flags.append(
            {
                "flag_id": "ROOM_BUCKET_NON_MONOTONIC",
                "severity": "MEDIUM",
                "read": "Moderate room is worse than both low and high room; zone selection/bucket boundaries need audit.",
                "low_room_avg_r": low_avg,
                "moderate_room_avg_r": moderate_avg,
                "high_room_avg_r": high_avg,
                "next_check": "Audit nearest resistance zone, room distance, stop distance, cost, and zone confidence.",
            }
        )
    same_bar = [item for item in items if item.get("result_status") == "BOTH_HIT_SAME_CANDLE"]
    if same_bar:
        flags.append(
            {
                "flag_id": "SAME_BAR_AMBIGUITY_PRESENT",
                "severity": "LOW",
                "read": "Some rows touch TP and SL in the same candle; keep conservative handling.",
                "sample_count": len(same_bar),
                "next_check": "Use lower timeframe ordering only if available; never assume favorable ordering.",
            }
        )
    return flags


def _mid_long_integrity_read(flags: list[dict[str, Any]]) -> str:
    if any(flag.get("severity") == "HIGH" for flag in flags):
        return "INTEGRITY_AUDIT_REQUIRED"
    if flags:
        return "INTEGRITY_WARNINGS_PRESENT"
    return "INTEGRITY_NO_MAJOR_ANOMALY"


def _mid_long_damage_experiment_row(
    experiment_id: str,
    label: str,
    expression: str,
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    baseline: dict[str, Any],
    min_sample: int,
) -> dict[str, Any]:
    retained: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
        (retained if _mid_long_damage_retains(experiment_id, taxonomy) else removed).append(item)
    row = _mid_long_perf_row(
        experiment_id,
        label,
        expression,
        retained,
        baseline=baseline if experiment_id != "DI-00" else None,
        required_fields=(),
        min_sample=min_sample,
    )
    retained_closed = int(row.get("closed_count") or 0)
    ideal_total = _decimal_or_zero_snapshot(row.get("ideal_total_r_closed"))
    realistic_total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    removed_perf = aggregate_signal_performance_items(removed)
    baseline_paths = _mid_long_path_mix(items)
    removed_paths = _mid_long_path_mix(removed)
    row.update(
        {
            "experiment_id": experiment_id,
            "retained_count": len(retained),
            "removed_count": len(removed),
            "retained_ideal_avg_r_closed": ideal_total / Decimal(retained_closed) if retained_closed > 0 else None,
            "retained_realistic_avg_r_closed": row.get("realistic_avg_r_closed"),
            "retained_execution_drag_r": ideal_total - realistic_total,
            "retained_execution_drag_avg_r": (ideal_total - realistic_total) / Decimal(retained_closed) if retained_closed > 0 else None,
            "removed_tp_count": removed_perf["tp_count"],
            "removed_sl_count": removed_perf["sl_count"],
            "removed_realistic_total_r_closed": removed_perf["realistic_total_r_closed"],
            "removed_realistic_avg_r_closed": removed_perf["realistic_avg_r_closed"],
            "retained_path_mix": _mid_long_path_mix(retained),
            "removed_path_mix": removed_paths,
            "close_profit_then_fail_removed_count": removed_paths.get("CLOSE_PROFIT_THEN_FAIL", 0),
            "close_profit_then_fail_removed_pct": _pct_decimal(
                removed_paths.get("CLOSE_PROFIT_THEN_FAIL", 0),
                baseline_paths.get("CLOSE_PROFIT_THEN_FAIL", 0),
            ),
            "pullback_tp_removed_count": removed_paths.get("PULLBACK_TP", 0),
            "pullback_tp_removed_pct": _pct_decimal(
                removed_paths.get("PULLBACK_TP", 0),
                baseline_paths.get("PULLBACK_TP", 0),
            ),
            "instant_sl_removed_count": removed_paths.get("INSTANT_SL", 0),
            "instant_sl_removed_pct": _pct_decimal(
                removed_paths.get("INSTANT_SL", 0),
                baseline_paths.get("INSTANT_SL", 0),
            ),
            "month_rows": _mid_long_month_rows(retained),
            "damage_read": _mid_long_damage_row_read(row, removed_perf),
        }
    )
    return row


def _mid_long_damage_retains(experiment_id: str, taxonomy: dict[str, Any]) -> bool:
    if experiment_id == "DI-00":
        return True
    if experiment_id == "DI-01":
        return taxonomy.get("setup_family") != "MID_RANGE"
    if experiment_id == "DI-02":
        return taxonomy.get("flow_state_provisional") != "WEAK"
    if experiment_id == "DI-03":
        return taxonomy.get("setup_family") != "MID_RANGE" and taxonomy.get("flow_state_provisional") != "WEAK"
    if experiment_id == "DI-04":
        return (
            taxonomy.get("setup_family") != "MID_RANGE"
            and taxonomy.get("flow_state_provisional") != "WEAK"
            and taxonomy.get("projected_cost_bucket") != "EXTREME_COST"
        )
    if experiment_id == "DI-05":
        crowding = taxonomy.get("crowding_bucket") in {"HIGH_CROWDING", "EXTREME_CROWDING"}
        danger_pair = (
            taxonomy.get("extension_bucket") in {"HIGH_EXTENSION", "EXTREME_EXTENSION"}
            or taxonomy.get("flow_state_provisional") in {"MIXED", "WEAK"}
            or taxonomy.get("room_to_resistance_bucket") == "LOW_ROOM"
        )
        return (
            taxonomy.get("setup_family") != "MID_RANGE"
            and taxonomy.get("flow_state_provisional") != "WEAK"
            and taxonomy.get("projected_cost_bucket") != "EXTREME_COST"
            and not (crowding and danger_pair)
        )
    return True


def _mid_long_subset_dimension_rows(
    items: list[dict[str, Any]],
    *,
    taxonomy_by_id: dict[str, dict[str, Any]],
    anchor_key: str,
    anchor_value: str,
    dimension_key: str,
    dimension_label: str,
    baseline: dict[str, Any],
    min_sample: int,
) -> list[dict[str, Any]]:
    anchored: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for idx, item in enumerate(items):
        taxonomy = taxonomy_by_id[str(item.get("signal_id") or idx)]
        if taxonomy.get(anchor_key) != anchor_value:
            continue
        anchored.append(item)
        grouped[str(taxonomy.get(dimension_key) or "UNKNOWN")].append(item)
    rows = [
        _mid_long_perf_row(
            f"{anchor_key}:{anchor_value}:{dimension_key}:{state}",
            state,
            f"{anchor_key} == {anchor_value} AND {dimension_key} == {state}",
            state_items,
            baseline=baseline,
            required_fields=(),
            min_sample=min_sample,
        )
        for state, state_items in grouped.items()
    ]
    for row in rows:
        row.update(
            {
                "anchor_key": anchor_key,
                "anchor_value": anchor_value,
                "dimension_key": dimension_key,
                "dimension_label": dimension_label,
                "state": row.get("label"),
                "anchor_sample_count": len(anchored),
                "anchor_retention_pct": _pct_decimal(int(row.get("sample_count") or 0), len(anchored)),
                "path_mix": _mid_long_path_mix(grouped[str(row.get("label"))]),
            }
        )
    rows.sort(
        key=lambda row: (
            int(row.get("closed_count") or 0),
            abs(_decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))),
        ),
        reverse=True,
    )
    return rows


def _mid_long_damage_row_read(row: dict[str, Any], removed_perf: dict[str, Any]) -> str:
    if str(row.get("experiment_id")) == "DI-00":
        return "Baseline control."
    avg_delta = _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline"))
    removed_total = _decimal_or_zero_snapshot(removed_perf.get("realistic_total_r_closed"))
    retained_total = _decimal_or_zero_snapshot(row.get("realistic_total_r_closed"))
    if avg_delta > Decimal("0.10") and removed_total < 0 and retained_total > 0:
        return "Strong damage isolation candidate; still needs chronological validation."
    if avg_delta > 0 and removed_total < 0:
        return "Damage is reduced, but survivor total/sample/path mix still needs review."
    if avg_delta > 0:
        return "Average improves but removed set is not clearly the only damage source."
    return "Does not isolate damage yet."


def _mid_long_damage_isolation_read(rows: list[dict[str, Any]]) -> str:
    candidates = [
        row
        for row in rows
        if str(row.get("experiment_id")) != "DI-00"
        and _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")) > 0
        and _decimal_or_zero_snapshot(row.get("removed_realistic_total_r_closed")) < 0
    ]
    if not candidates:
        return "NO_DAMAGE_FILTER_READY"
    best = max(candidates, key=lambda row: _decimal_or_zero_snapshot(row.get("realistic_avg_r_delta_vs_baseline")))
    return f"{best.get('experiment_id')} is the strongest read-only damage-isolation candidate."


def _mid_long_item_decimal_values(items: list[dict[str, Any]], key: str) -> list[Decimal]:
    return [value for item in items if (value := _decimal_or_none_snapshot(item.get(key))) is not None]


def _mid_long_path_event_decimal_values(items: list[dict[str, Any]], key: str) -> list[Decimal]:
    values: list[Decimal] = []
    for item in items:
        events = item.get("path_events") if isinstance(item.get("path_events"), dict) else {}
        value = _decimal_or_none_snapshot(events.get(key))
        if value is not None:
            values.append(value)
    return values


def _mid_long_path_event_count(items: list[dict[str, Any]], key: str) -> int:
    count = 0
    for item in items:
        events = item.get("path_events") if isinstance(item.get("path_events"), dict) else {}
        if events.get(key) not in (None, ""):
            count += 1
    return count


def _mid_long_stop_pct_values(items: list[dict[str, Any]]) -> list[Decimal]:
    values: list[Decimal] = []
    for item in items:
        entry = _decimal_or_none_snapshot(item.get("price_at_signal"))
        stop = _decimal_or_none_snapshot(item.get("sl_ref"))
        if entry is None or stop is None or entry <= 0:
            continue
        values.append(abs(entry - stop) / entry * Decimal("100"))
    return values


def _mid_long_month_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        stamp = str(item.get("signal_timestamp") or item.get("window_close_time") or "UNKNOWN")
        grouped[stamp[:7] if len(stamp) >= 7 else "UNKNOWN"].append(item)
    rows: list[dict[str, Any]] = []
    for month, month_items in grouped.items():
        perf = aggregate_signal_performance_items(month_items)
        rows.append(
            {
                "month": month,
                "sample_count": len(month_items),
                "tp_count": perf["tp_count"],
                "sl_count": perf["sl_count"],
                "realistic_total_r_closed": perf["realistic_total_r_closed"],
                "realistic_avg_r_closed": perf["realistic_avg_r_closed"],
                "top_symbol_share_pct": _mid_long_top_n_symbol_share(month_items, n=1),
            }
        )
    rows.sort(key=lambda row: str(row.get("month") or ""))
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
