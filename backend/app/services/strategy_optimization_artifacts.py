from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import SignalCandidatePerformanceService
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.strategy_optimization_lab import StrategyOptimizationLabService
from app.services.strategy_optimization_regime_split import StrategyOptimizationRegimeSplitService
from app.services.utils import json_safe


DEFAULT_STRATEGY_OPTIMIZATION_ARTIFACT_DIR = REPO_ROOT / "backend" / "artifacts" / "strategy_optimization" / "v1"
SUMMARY_FILE = "summary.json"
DEFAULT_LANE_PAIRS = (
    ("MID_SHORT", "1h"),
    ("MID_LONG", "1h"),
    ("EARLY_LONG", "15m"),
    ("EARLY_SHORT", "15m"),
)


class StrategyOptimizationArtifactRunner:
    """Precompute read-only strategy optimization diagnostics for fast UI reads."""

    def __init__(self, db: Session, artifact_dir: Path = DEFAULT_STRATEGY_OPTIMIZATION_ARTIFACT_DIR) -> None:
        self.db = db
        self.artifact_dir = artifact_dir

    def run(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 20,
        limit: int = 200,
        lane_pairs: tuple[tuple[str, str], ...] = DEFAULT_LANE_PAIRS,
    ) -> dict[str, Any]:
        optimizer = StrategyOptimizationLabService(self.db)
        splitter = StrategyOptimizationRegimeSplitService(self.db)
        optimization_by_lane: dict[str, dict[str, Any]] = {}
        regime_by_lane: dict[str, dict[str, Any]] = {}
        errors: list[dict[str, str]] = []

        for stage, timeframe in lane_pairs:
            key = lane_key(stage, timeframe)
            try:
                optimization = optimizer.summary(
                    epoch=epoch,
                    include_watch_only=include_watch_only,
                    position_lock=position_lock,
                    stage=stage,
                    timeframe=timeframe,
                    min_sample=min_sample,
                    limit=limit,
                )
                optimization_by_lane[key] = optimization
                best = (optimization.get("summary") or {}).get("best_row")
                if best:
                    regime_by_lane[key] = splitter.summary(
                        epoch=epoch,
                        include_watch_only=include_watch_only,
                        position_lock=position_lock,
                        stage=stage,
                        timeframe=timeframe,
                        atr_mult=Decimal(str(best["atr_mult"])),
                        rr=Decimal(str(best["rr"])),
                        timeout_minutes=int(best["timeout_minutes"]),
                        min_sample=min_sample,
                        limit=limit,
                    )
            except Exception as exc:  # pragma: no cover - defensive artifact runner boundary
                errors.append({"lane": key, "error": str(exc)})

        calibration = SignalCandidatePerformanceService(self.db).calibration_lab(
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=max(5, min_sample // 4),
            limit=100,
        )
        payload = {
            "generated_at_utc": datetime.now(UTC),
            "epoch": epoch,
            "artifact_type": "read_only_strategy_optimization_precompute",
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "min_sample": min_sample,
                "limit": limit,
                "lane_pairs": [list(pair) for pair in lane_pairs],
            },
            "optimization_by_lane": optimization_by_lane,
            "regime_by_lane": regime_by_lane,
            "v3_shadow": _v3_shadow_summary(calibration),
            "errors": errors,
            "guardrails": [
                "No Signal Factory rule changed.",
                "No scanner behavior changed.",
                "No outcome logic changed.",
                "No live signal, order, leverage, position sizing, or execution created.",
                "V3 shadow filters are research-only until forward validation is explicitly approved.",
            ],
        }
        safe_payload = json_safe(payload)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        (self.artifact_dir / SUMMARY_FILE).write_text(json.dumps(safe_payload, indent=2), encoding="utf-8")
        return safe_payload


class StrategyOptimizationArtifactService:
    def __init__(self, artifact_dir: Path = DEFAULT_STRATEGY_OPTIMIZATION_ARTIFACT_DIR) -> None:
        self.artifact_dir = artifact_dir

    def summary(self) -> dict[str, Any]:
        return self._read()

    def optimization_for(
        self,
        *,
        stage: str | None,
        timeframe: str | None,
        include_watch_only: bool,
        position_lock: bool,
        min_sample: int,
        limit: int,
    ) -> dict[str, Any] | None:
        if not stage or not timeframe:
            return None
        payload = self._read_optional()
        if not payload or not self._filters_match(payload, include_watch_only, position_lock, min_sample):
            return None
        row = deepcopy((payload.get("optimization_by_lane") or {}).get(lane_key(stage, timeframe)))
        if not row:
            return None
        row["rows"] = list(row.get("rows") or [])[:limit]
        row["filters"] = {**(row.get("filters") or {}), "limit": limit}
        row["artifact"] = _artifact_meta(payload, source="strategy_optimization_summary")
        return row

    def regime_for(
        self,
        *,
        stage: str,
        timeframe: str,
        atr_mult: Decimal,
        rr: Decimal,
        timeout_minutes: int,
        include_watch_only: bool,
        position_lock: bool,
        min_sample: int,
        limit: int,
    ) -> dict[str, Any] | None:
        payload = self._read_optional()
        if not payload or not self._filters_match(payload, include_watch_only, position_lock, min_sample):
            return None
        row = deepcopy((payload.get("regime_by_lane") or {}).get(lane_key(stage, timeframe)))
        if not row:
            return None
        filters = row.get("filters") or {}
        if not (
            _decimal_equal(filters.get("atr_mult"), atr_mult)
            and _decimal_equal(filters.get("rr"), rr)
            and int(filters.get("timeout_minutes") or 0) == int(timeout_minutes)
        ):
            return None
        summary = row.get("summary") or {}
        summary["top_helpful_regimes"] = list(summary.get("top_helpful_regimes") or [])[:limit]
        summary["top_harmful_regimes"] = list(summary.get("top_harmful_regimes") or [])[:limit]
        row["summary"] = summary
        row["filters"] = {**filters, "limit": limit}
        row["artifact"] = _artifact_meta(payload, source="strategy_optimization_summary")
        return row

    def _filters_match(self, payload: dict[str, Any], include_watch_only: bool, position_lock: bool, min_sample: int) -> bool:
        filters = payload.get("filters") or {}
        return (
            bool(filters.get("include_watch_only")) == bool(include_watch_only)
            and bool(filters.get("position_lock")) == bool(position_lock)
            and int(filters.get("min_sample") or 0) == int(min_sample)
        )

    def _read(self) -> dict[str, Any]:
        path = self.artifact_dir / SUMMARY_FILE
        if not path.exists():
            raise FileNotFoundError(f"Strategy optimization artifact not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_optional(self) -> dict[str, Any] | None:
        try:
            return self._read()
        except FileNotFoundError:
            return None


def lane_key(stage: str, timeframe: str) -> str:
    return f"{stage}:{timeframe}"


def parse_lane_pairs(values: list[str] | None) -> tuple[tuple[str, str], ...]:
    if not values:
        return DEFAULT_LANE_PAIRS
    output: list[tuple[str, str]] = []
    for raw in values:
        parts = raw.replace("/", ":").split(":")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid lane pair: {raw}. Use STAGE:TIMEFRAME, e.g. MID_SHORT:1h")
        output.append((parts[0].strip().upper(), parts[1].strip()))
    return tuple(output)


def _v3_shadow_summary(calibration: dict[str, Any]) -> dict[str, Any]:
    top_candidates = calibration.get("top_candidates") or []
    promotion_counts = Counter(str(row.get("promotion_status") or "UNKNOWN") for row in top_candidates)
    lane_filters: list[dict[str, Any]] = []
    for lane in calibration.get("lanes") or []:
        selected = [
            candidate
            for candidate in lane.get("filter_candidates") or []
            if candidate.get("promotion_status") in {"V3_CANDIDATE", "MONITOR_MORE"}
        ]
        if selected:
            lane_filters.append(
                {
                    "stage": lane.get("stage"),
                    "timeframe": lane.get("timeframe"),
                    "sample_count": lane.get("sample_count"),
                    "status": lane.get("status"),
                    "selected_filters": selected[:5],
                }
            )
    return {
        "generated_at_utc": calibration.get("generated_at_utc"),
        "strategy_version": calibration.get("strategy_version"),
        "shadow_strategy_version": calibration.get("shadow_strategy_version"),
        "promotion_counts": dict(promotion_counts),
        "v3_candidate_count": promotion_counts.get("V3_CANDIDATE", 0),
        "monitor_more_count": promotion_counts.get("MONITOR_MORE", 0),
        "reject_overfit_count": promotion_counts.get("REJECT_OVERFIT", 0),
        "weak_filter_count": promotion_counts.get("WEAK_FILTER", 0),
        "top_candidates": top_candidates[:20],
        "lane_filters": lane_filters,
        "guardrail": "Research-only V3 shadow filter map; does not change Signal Factory V2 live rules.",
    }


def _artifact_meta(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "generated_at_utc": payload.get("generated_at_utc"),
        "artifact_type": payload.get("artifact_type"),
        "read_from_artifact": True,
    }


def _decimal_equal(left: Any, right: Decimal) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError, TypeError):
        return False
