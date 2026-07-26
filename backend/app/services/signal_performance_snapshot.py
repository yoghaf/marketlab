from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import (
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
FORWARD_INTEGRITY_FILE = "forward_integrity.json"
PERFORMANCE_1H_FILE = "performance_closed_1h.json"
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
            _atomic_write_json(self.artifact_dir / FORWARD_INTEGRITY_FILE, json_safe(forward_integrity))
            _atomic_write_json(self.artifact_dir / QUALITY_LAB_FILE, json_safe(quality_lab))
            result.update(
                {
                    "performance_path": str(self.artifact_dir / PERFORMANCE_FILE),
                    "forward_integrity_path": str(self.artifact_dir / FORWARD_INTEGRITY_FILE),
                    "quality_lab_path": str(self.artifact_dir / QUALITY_LAB_FILE),
                    "performance_items": len(performance.get("items") or []),
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
                    "forward_integrity_1h_path": str(self.artifact_dir / FORWARD_INTEGRITY_1H_FILE),
                    "mid_short_filter_combo_1h_path": str(self.artifact_dir / MID_SHORT_FILTER_COMBO_1H_FILE),
                    "performance_1h_items": len(performance_1h.get("items") or []),
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
        payload = self._read(PERFORMANCE_FILE)
        return _slice_payload(payload, limit=max(1, limit), list_keys=("items",))

    def performance_1h(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(PERFORMANCE_1H_FILE)
        return _slice_payload(payload, limit=max(1, limit), list_keys=("items",))

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
        rr_distribution = Counter(_distribution_key(item.get("rr")) for item in evaluated)
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
