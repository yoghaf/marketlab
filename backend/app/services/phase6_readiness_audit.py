from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SIGNAL_FACTORY_DIR = REPO_ROOT / "backend" / "artifacts" / "signal_factory" / "v1"
DEFAULT_STRATEGY_ARENA_DIR = REPO_ROOT / "backend" / "artifacts" / "strategy_arena" / "v1"
DEFAULT_PHASE6_DIR = REPO_ROOT / "backend" / "artifacts" / "phase6"
DEFAULT_PHASE6_DOC = REPO_ROOT / "backend" / "docs" / "phase6_signal_factory_readiness_edge_audit.md"

FEATURE_STATUSES = ["READY", "PARTIAL_DATA", "MISSING_CANDLES", "MISSING_ATR", "MISSING_OI", "STALE_DATA"]
TIMEFRAMES = ["15m", "1h", "4h", "24h"]
BLOCKING_FEATURE_STATUSES = {"MISSING_CANDLES", "MISSING_ATR", "MISSING_OI", "STALE_DATA"}
BLOCKING_CANDIDATE_STATUSES = {"BLOCKED_DATA", "TIMEFRAME_NOT_READY"}
SIGNAL_FACTORY_FILES = ["features.json", "candidates.json", "summary.json"]
STRATEGY_ARENA_FILES = ["results.json", "leaderboard.json"]


@dataclass(frozen=True)
class Phase6RunResult:
    readiness_summary: dict[str, Any]
    setup_edge_audit: dict[str, Any]
    phase7_candidate_decision: dict[str, Any]


class Phase6ReadinessAuditRunner:
    def __init__(
        self,
        signal_factory_dir: Path = DEFAULT_SIGNAL_FACTORY_DIR,
        strategy_arena_dir: Path = DEFAULT_STRATEGY_ARENA_DIR,
        output_dir: Path = DEFAULT_PHASE6_DIR,
        doc_path: Path = DEFAULT_PHASE6_DOC,
    ) -> None:
        self.signal_factory_dir = signal_factory_dir
        self.strategy_arena_dir = strategy_arena_dir
        self.output_dir = output_dir
        self.doc_path = doc_path

    def run(self) -> Phase6RunResult:
        generated_at = datetime.now(UTC).isoformat()
        loaded = load_phase6_inputs(self.signal_factory_dir, self.strategy_arena_dir)
        if loaded["artifact_status"] != "OK":
            result = build_missing_artifact_result(generated_at, loaded)
            self.write_outputs(result)
            return result

        features = loaded["features"].get("items", [])
        candidates = loaded["candidates"].get("items", [])
        arena_results = loaded["arena_results"].get("results", [])
        leaderboard = loaded["leaderboard"]

        feature_readiness = audit_feature_readiness(features)
        candidate_readiness = audit_candidate_readiness(candidates)
        arena_index = StrategyArenaIndex(arena_results)
        edge_rows = evaluate_candidates_for_phase7(candidates, arena_index)
        decision = build_phase7_decision(generated_at, edge_rows)
        readiness_summary = {
            "generated_at": generated_at,
            "phase6_status": "PASS",
            "artifact_status": "OK",
            "missing_artifacts": [],
            "refresh_commands": refresh_commands(),
            "feature_readiness": feature_readiness,
            "candidate_readiness": candidate_readiness,
            "strategy_arena_summary": {
                "generated_at": (loaded["arena_results"].get("metadata") or {}).get("generated_at"),
                "total_results": len(arena_results),
                "leaderboard_summary": leaderboard.get("summary", {}),
            },
            "phase7_decision": decision["phase7_decision"],
            "approved_count": len(decision["approved_candidates"]),
            "watchlist_count": len(decision["watchlist_candidates"]),
            "rejected_count": len(decision["rejected_candidates"]),
            "best_setup": decision.get("best_setup"),
            "most_blocked_timeframe": feature_readiness.get("most_blocked_timeframe"),
            "guardrails": {
                "read_only": True,
                "not_live_signal": True,
                "not_execution_instruction": True,
                "no_order_execution": True,
            },
        }
        setup_edge_audit = {
            "generated_at": generated_at,
            "phase6_status": "PASS",
            "artifact_status": "OK",
            "rows": edge_rows,
            "summary": summarize_edge_rows(edge_rows),
            "guardrails": readiness_summary["guardrails"],
        }
        result = Phase6RunResult(readiness_summary, setup_edge_audit, decision)
        self.write_outputs(result)
        return result

    def write_outputs(self, result: Phase6RunResult) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "readiness_summary.json").write_text(json.dumps(json_safe(result.readiness_summary), indent=2))
        (self.output_dir / "setup_edge_audit.json").write_text(json.dumps(json_safe(result.setup_edge_audit), indent=2))
        (self.output_dir / "phase7_candidate_decision.json").write_text(
            json.dumps(json_safe(result.phase7_candidate_decision), indent=2)
        )
        self.doc_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_path.write_text(render_phase6_report(result))


class Phase6ArtifactService:
    def __init__(self, artifact_dir: Path = DEFAULT_PHASE6_DIR) -> None:
        self.artifact_dir = artifact_dir

    def readiness(self) -> dict[str, Any]:
        return self._read("readiness_summary.json")

    def edge_audit(self) -> dict[str, Any]:
        return self._read("setup_edge_audit.json")

    def phase7_decision(self) -> dict[str, Any]:
        return self._read("phase7_candidate_decision.json")

    def _read(self, filename: str) -> dict[str, Any]:
        path = self.artifact_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Phase 6 artifact not found: {path}")
        return json.loads(path.read_text())


class StrategyArenaIndex:
    def __init__(self, arena_results: list[dict[str, Any]]) -> None:
        self.results = arena_results
        self.by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in arena_results:
            family = row.get("setup_family")
            if family:
                self.by_family[family].append(row)
            key = (
                str(row.get("setup_family")),
                str(row.get("horizon")),
                str(row.get("atr_mult")),
                str(row.get("rr")),
            )
            existing = self.by_key.get(key)
            if existing is None or dec(row.get("pessimistic_avg_r"), Decimal("-999")) > dec(existing.get("pessimistic_avg_r"), Decimal("-999")):
                self.by_key[key] = row

    def best_match(self, setup_family: str | None, timeframe: str) -> dict[str, Any] | None:
        if not setup_family:
            return None
        horizons = horizon_priority(timeframe)
        rows = [row for row in self.by_family.get(setup_family, []) if row.get("horizon") in horizons]
        if not rows:
            return None
        return max(rows, key=lambda row: (horizon_rank(row.get("horizon"), horizons), dec(row.get("pessimistic_avg_r"), Decimal("-999"))))

    def baseline_for(self, direction_side: str | None, arena_row: dict[str, Any] | None) -> dict[str, Any] | None:
        if direction_side not in {"LONG", "SHORT"} or not arena_row:
            return None
        baseline_family = "NO_SIGNAL_BASELINE_LONG" if direction_side == "LONG" else "NO_SIGNAL_BASELINE_SHORT"
        key = (
            baseline_family,
            str(arena_row.get("horizon")),
            str(arena_row.get("atr_mult")),
            str(arena_row.get("rr")),
        )
        return self.by_key.get(key)


def load_phase6_inputs(signal_factory_dir: Path, strategy_arena_dir: Path) -> dict[str, Any]:
    missing = []
    for filename in SIGNAL_FACTORY_FILES:
        path = signal_factory_dir / filename
        if not path.exists():
            missing.append(str(path))
    for filename in STRATEGY_ARENA_FILES:
        path = strategy_arena_dir / filename
        if not path.exists():
            missing.append(str(path))
    if missing:
        return {"artifact_status": "MISSING_ARTIFACT", "missing_artifacts": missing, "refresh_commands": refresh_commands()}
    return {
        "artifact_status": "OK",
        "missing_artifacts": [],
        "refresh_commands": refresh_commands(),
        "features": json.loads((signal_factory_dir / "features.json").read_text()),
        "candidates": json.loads((signal_factory_dir / "candidates.json").read_text()),
        "summary": json.loads((signal_factory_dir / "summary.json").read_text()),
        "arena_results": json.loads((strategy_arena_dir / "results.json").read_text()),
        "leaderboard": json.loads((strategy_arena_dir / "leaderboard.json").read_text()),
    }


def audit_feature_readiness(features: list[dict[str, Any]]) -> dict[str, Any]:
    by_timeframe: dict[str, dict[str, Any]] = {}
    for timeframe in TIMEFRAMES:
        rows = [row for row in features if row.get("timeframe") == timeframe]
        total = len(rows)
        counts = Counter(row.get("feature_status") or "UNKNOWN" for row in rows)
        missing_total = sum(counts.get(status, 0) for status in ["MISSING_CANDLES", "MISSING_ATR", "MISSING_OI", "STALE_DATA"])
        ready_share = share(counts.get("READY", 0), total)
        usable_share = share(counts.get("READY", 0) + counts.get("PARTIAL_DATA", 0), total)
        missing_share = share(missing_total, total)
        if ready_share >= Decimal("60"):
            status = "TIMEFRAME_READY"
        elif usable_share >= Decimal("60"):
            status = "TIMEFRAME_PARTIAL_USABLE"
        else:
            status = "TIMEFRAME_NOT_READY"
        by_timeframe[timeframe] = {
            "timeframe": timeframe,
            "total_feature_rows": total,
            **{f"{status_name.lower()}_count": counts.get(status_name, 0) for status_name in FEATURE_STATUSES},
            **{f"{status_name.lower()}_share": float(share(counts.get(status_name, 0), total)) for status_name in FEATURE_STATUSES},
            "missing_total_count": missing_total,
            "missing_total_share": float(missing_share),
            "readiness_status": status,
        }
    most_ready = max(by_timeframe.values(), key=lambda row: (row["ready_share"] + row["partial_data_share"], -row["missing_total_share"]), default=None)
    most_blocked = max(by_timeframe.values(), key=lambda row: row["missing_total_share"], default=None)
    return {
        "by_timeframe": by_timeframe,
        "most_ready_timeframe": most_ready["timeframe"] if most_ready else None,
        "most_blocked_timeframe": most_blocked["timeframe"] if most_blocked else None,
    }


def audit_candidate_readiness(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(row.get("candidate_status") or "UNKNOWN" for row in candidates)
    setup_counts = Counter(row.get("setup_type") or "UNKNOWN" for row in candidates)
    timeframe_counts = Counter(row.get("timeframe") or "UNKNOWN" for row in candidates)
    direction_counts = Counter(row.get("direction") or "UNKNOWN" for row in candidates)
    confidence_counts = Counter(row.get("confidence") or "UNKNOWN" for row in candidates)
    symbol_counts = Counter(row.get("symbol") or "UNKNOWN" for row in candidates)
    eligible = [row for row in candidates if is_candidate_eligible(row)]
    return {
        "total_candidates": len(candidates),
        "status_counts": dict(status_counts),
        "status_shares": {key: float(share(count, len(candidates))) for key, count in status_counts.items()},
        "setup_counts": dict(setup_counts),
        "timeframe_counts": dict(timeframe_counts),
        "direction_counts": dict(direction_counts),
        "confidence_counts": dict(confidence_counts),
        "top_symbol_counts": dict(symbol_counts.most_common(15)),
        "eligible_candidate_count": len(eligible),
        "blocked_candidate_count": status_counts.get("BLOCKED_DATA", 0) + status_counts.get("TIMEFRAME_NOT_READY", 0),
        "radar_only_count": status_counts.get("RADAR_ONLY", 0),
        "conflicted_count": status_counts.get("CONFLICTED", 0),
    }


def evaluate_candidates_for_phase7(candidates: list[dict[str, Any]], arena_index: StrategyArenaIndex) -> list[dict[str, Any]]:
    rows = []
    for candidate in candidates:
        setup_family = map_setup_family(candidate)
        direction_side = direction_side_for_candidate(candidate)
        arena_row = arena_index.best_match(setup_family, candidate.get("timeframe") or "")
        baseline_row = arena_index.baseline_for(direction_side, arena_row)
        relative = relative_strength_flags(candidate, direction_side)
        score = score_candidate(candidate, arena_row, baseline_row, relative)
        rows.append(
            {
                "symbol": candidate.get("symbol"),
                "timeframe": candidate.get("timeframe"),
                "setup_type": candidate.get("setup_type"),
                "mapped_setup_family": setup_family,
                "direction": candidate.get("direction"),
                "direction_side": direction_side,
                "confidence": candidate.get("confidence"),
                "candidate_status": candidate.get("candidate_status"),
                "feature_status": candidate.get("feature_status"),
                "atr_reference_timeframe": candidate.get("atr_reference_timeframe"),
                "atr_reference_status": candidate.get("atr_reference_status"),
                "reason": candidate.get("reason"),
                "window_end": candidate.get("window_end"),
                "evidence_summary": evidence_summary(candidate),
                "relative_strength_flags": relative,
                "arena_match": arena_payload(arena_row),
                "baseline_match": arena_payload(baseline_row),
                "setup_pessR": safe_float(arena_row.get("pessimistic_avg_r")) if arena_row else None,
                "baseline_pessR": safe_float(baseline_row.get("pessimistic_avg_r")) if baseline_row else None,
                "edge_vs_baseline": edge_vs_baseline(arena_row, baseline_row),
                "beats_baseline": beats_baseline(arena_row, baseline_row),
                **score,
                "not_live_signal": True,
                "not_execution_instruction": True,
            }
        )
    return rows


def score_candidate(
    candidate: dict[str, Any],
    arena_row: dict[str, Any] | None,
    baseline_row: dict[str, Any] | None,
    relative_flags: dict[str, Any],
) -> dict[str, Any]:
    rejection_reasons = []
    candidate_status = candidate.get("candidate_status")
    feature_status = candidate.get("feature_status")
    if candidate_status in BLOCKING_CANDIDATE_STATUSES:
        rejection_reasons.append(candidate_status)
    if feature_status in {"MISSING_CANDLES", "MISSING_ATR", "MISSING_OI", "STALE_DATA"}:
        rejection_reasons.append(feature_status)
    if candidate.get("atr_reference_status") == "MISSING_ATR_REFERENCE":
        rejection_reasons.append("MISSING_ATR_REFERENCE")
    if not is_candidate_eligible(candidate):
        rejection_reasons.append("NOT_ELIGIBLE_SIGNAL_FACTORY_CANDIDATE")

    readiness_score = 2 if is_candidate_eligible(candidate) else 0
    arena_score = arena_score_for(arena_row)
    baseline_score = baseline_score_for(arena_row, baseline_row)
    relative_score = relative_flags.get("score", 0)
    confidence_score = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(candidate.get("confidence"), 0)
    data_quality_penalty = -1 if candidate.get("feature_status") == "PARTIAL_DATA" else 0
    conflict_penalty = -3 if candidate.get("candidate_status") == "CONFLICTED" or candidate.get("conflict_status") == "TIMEFRAME_CONFLICT" else 0
    total_score = readiness_score + arena_score + baseline_score + relative_score + confidence_score + data_quality_penalty + conflict_penalty

    if rejection_reasons:
        phase7_verdict = "REJECT_FOR_PHASE7"
    elif total_score >= 7:
        phase7_verdict = "PHASE7_READY"
    elif total_score >= 4:
        phase7_verdict = "WATCHLIST_FOR_MORE_DATA"
    elif total_score >= 1:
        phase7_verdict = "RADAR_ONLY"
    else:
        phase7_verdict = "REJECT_FOR_PHASE7"
    return {
        "readiness_score": readiness_score,
        "arena_score": arena_score,
        "baseline_score": baseline_score,
        "relative_strength_score": relative_score,
        "confidence_score": confidence_score,
        "data_quality_penalty": data_quality_penalty,
        "conflict_penalty": conflict_penalty,
        "total_score": total_score,
        "phase7_verdict": phase7_verdict,
        "rejection_reasons": sorted(set(rejection_reasons)),
    }


def build_phase7_decision(generated_at: str, edge_rows: list[dict[str, Any]]) -> dict[str, Any]:
    approved = [candidate_decision_payload(row) for row in edge_rows if row["phase7_verdict"] == "PHASE7_READY"]
    watchlist = [candidate_decision_payload(row) for row in edge_rows if row["phase7_verdict"] == "WATCHLIST_FOR_MORE_DATA"]
    rejected = [candidate_decision_payload(row) for row in edge_rows if row["phase7_verdict"] == "REJECT_FOR_PHASE7"]
    blocked_reasons = Counter(reason for row in edge_rows for reason in row.get("rejection_reasons", []))
    best_candidates = sorted(approved or watchlist, key=lambda row: row.get("total_score") or 0, reverse=True)
    return {
        "phase6_status": "PASS",
        "phase7_decision": "HAS_CANDIDATES" if approved else "NO_PHASE7_CANDIDATE_YET",
        "approved_candidates": approved,
        "watchlist_candidates": watchlist,
        "rejected_candidates": rejected,
        "blocked_reasons": dict(blocked_reasons),
        "best_setup": best_candidates[0] if best_candidates else None,
        "generated_at": generated_at,
        "guardrails": {
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
        },
    }


def build_missing_artifact_result(generated_at: str, loaded: dict[str, Any]) -> Phase6RunResult:
    readiness = {
        "generated_at": generated_at,
        "phase6_status": "BLOCKED",
        "artifact_status": "MISSING_ARTIFACT",
        "missing_artifacts": loaded["missing_artifacts"],
        "refresh_commands": loaded["refresh_commands"],
        "feature_readiness": {"by_timeframe": {}},
        "candidate_readiness": {},
        "phase7_decision": "NO_PHASE7_CANDIDATE_YET",
        "approved_count": 0,
        "watchlist_count": 0,
        "rejected_count": 0,
    }
    edge = {
        "generated_at": generated_at,
        "phase6_status": "BLOCKED",
        "artifact_status": "MISSING_ARTIFACT",
        "missing_artifacts": loaded["missing_artifacts"],
        "rows": [],
        "summary": {},
    }
    decision = {
        "phase6_status": "BLOCKED",
        "phase7_decision": "NO_PHASE7_CANDIDATE_YET",
        "approved_candidates": [],
        "watchlist_candidates": [],
        "rejected_candidates": [],
        "blocked_reasons": {"MISSING_ARTIFACT": len(loaded["missing_artifacts"])},
        "missing_artifacts": loaded["missing_artifacts"],
        "refresh_commands": loaded["refresh_commands"],
        "generated_at": generated_at,
    }
    return Phase6RunResult(readiness, edge, decision)


def is_candidate_eligible(candidate: dict[str, Any]) -> bool:
    return (
        candidate.get("candidate_status") == "SIGNAL_CANDIDATE"
        and candidate.get("not_live_signal") is True
        and candidate.get("not_execution_instruction") is True
        and bool(candidate.get("direction"))
        and bool(candidate.get("setup_type"))
        and bool(candidate.get("timeframe"))
        and candidate.get("feature_status") not in BLOCKING_FEATURE_STATUSES
    )


def map_setup_family(candidate: dict[str, Any]) -> str | None:
    setup = candidate.get("setup_type")
    evidence = candidate.get("evidence") or {}
    if setup == "EARLY_LONG":
        return "EARLY_LONG"
    if setup == "EARLY_SHORT":
        return "EARLY_SHORT"
    if setup == "MID_LONG":
        return "MID_LONG"
    if setup == "MID_SHORT":
        return "MID_SHORT_FUTURES_LED" if evidence.get("futures_led_flag") else "MID_SHORT_NON_FUTURES_LED"
    if setup == "SQUEEZE":
        price_return = dec(evidence.get("price_return"), Decimal("0"))
        return "SQUEEZE_CONTINUATION" if price_return >= 0 else "SQUEEZE_FADE"
    if setup == "TRAP_FADE":
        return "TRAP_FADE"
    return None


def direction_side_for_candidate(candidate: dict[str, Any]) -> str | None:
    direction = candidate.get("direction")
    setup = candidate.get("setup_type")
    if direction == "BULLISH_CONTEXT":
        return "LONG"
    if direction == "BEARISH_CONTEXT":
        return "SHORT"
    if setup == "TRAP_FADE":
        price_return = dec((candidate.get("evidence") or {}).get("price_return"), Decimal("0"))
        return "SHORT" if price_return > 0 else "LONG" if price_return < 0 else None
    if setup == "SQUEEZE":
        price_return = dec((candidate.get("evidence") or {}).get("price_return"), Decimal("0"))
        return "LONG" if price_return > 0 else "SHORT" if price_return < 0 else None
    return None


def relative_strength_flags(candidate: dict[str, Any], direction_side: str | None) -> dict[str, Any]:
    evidence = candidate.get("evidence") or {}
    relative = evidence.get("relative_strength") or "UNKNOWN"
    flags = []
    score = 0
    if direction_side == "SHORT":
        if relative == "UNDERPERFORMING":
            flags.append("RELATIVE_STRENGTH_SUPPORTS_DIRECTION")
            score = 2
        elif relative == "OUTPERFORMING":
            flags.append("RELATIVE_STRENGTH_AGAINST_DIRECTION")
            score = -2
        elif relative == "INLINE_WITH_MARKET":
            score = 1
    elif direction_side == "LONG":
        if relative == "OUTPERFORMING":
            flags.append("RELATIVE_STRENGTH_SUPPORTS_DIRECTION")
            score = 2
        elif relative == "UNDERPERFORMING":
            flags.append("RELATIVE_STRENGTH_AGAINST_DIRECTION")
            score = -2
        elif relative == "INLINE_WITH_MARKET":
            score = 1
    else:
        score = 0

    price_return = dec(evidence.get("price_return"), Decimal("0"))
    futures_led = evidence.get("futures_led_flag") is True
    spot_led = evidence.get("spot_led_flag") is True
    if direction_side == "SHORT" and futures_led and price_return < 0:
        flags.append("FLOW_SUPPORTS_DIRECTION")
    elif direction_side == "LONG" and (spot_led or futures_led) and price_return > 0:
        flags.append("FLOW_SUPPORTS_DIRECTION")
    elif futures_led or spot_led:
        flags.append("FLOW_MIXED")
    if "RELATIVE_STRENGTH_AGAINST_DIRECTION" in flags:
        flags.append("ANOMALY_WARNING")
    return {"relative_strength": relative, "flags": flags, "score": score}


def arena_score_for(row: dict[str, Any] | None) -> int:
    if not row:
        return -1
    return {
        "PROMISING_FOR_FORWARD_TEST": 3,
        "MONITOR_MORE": 1,
        "NOISY": 0,
        "REJECT": -3,
        "INSUFFICIENT_SAMPLE": -1,
    }.get(row.get("verdict"), -1)


def baseline_score_for(arena_row: dict[str, Any] | None, baseline_row: dict[str, Any] | None) -> int:
    edge = edge_vs_baseline(arena_row, baseline_row)
    if edge is None:
        return 0
    edge_decimal = Decimal(str(edge))
    if edge_decimal > Decimal("0.10"):
        return 3
    if edge_decimal > Decimal("0"):
        return 1
    return -2


def edge_vs_baseline(arena_row: dict[str, Any] | None, baseline_row: dict[str, Any] | None) -> float | None:
    if not arena_row or not baseline_row:
        return None
    return safe_float(dec(arena_row.get("pessimistic_avg_r"), Decimal("0")) - dec(baseline_row.get("pessimistic_avg_r"), Decimal("0")))


def beats_baseline(arena_row: dict[str, Any] | None, baseline_row: dict[str, Any] | None) -> bool | None:
    edge = edge_vs_baseline(arena_row, baseline_row)
    if edge is None:
        return None
    return edge > 0


def candidate_decision_payload(row: dict[str, Any]) -> dict[str, Any]:
    arena = row.get("arena_match") or {}
    return {
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "setup_type": row.get("setup_type"),
        "mapped_setup_family": row.get("mapped_setup_family"),
        "direction": row.get("direction"),
        "confidence": row.get("confidence"),
        "reason": row.get("reason"),
        "atr_reference_timeframe": row.get("atr_reference_timeframe"),
        "recommended_arena_horizon": arena.get("horizon"),
        "recommended_atr_mult": arena.get("atr_mult"),
        "recommended_rr": arena.get("rr"),
        "arena_verdict": arena.get("verdict"),
        "setup_pessR": row.get("setup_pessR"),
        "baseline_pessR": row.get("baseline_pessR"),
        "edge_vs_baseline": row.get("edge_vs_baseline"),
        "total_score": row.get("total_score"),
        "phase7_verdict": row.get("phase7_verdict"),
        "rejection_reasons": row.get("rejection_reasons", []),
        "not_live_signal": True,
        "not_execution_instruction": True,
    }


def summarize_edge_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total_rows": len(rows),
        "phase7_verdict_counts": dict(Counter(row["phase7_verdict"] for row in rows)),
        "setup_counts": dict(Counter(row.get("mapped_setup_family") or "UNMAPPED" for row in rows)),
        "arena_verdict_counts": dict(Counter((row.get("arena_match") or {}).get("verdict") or "ARENA_RESULT_MISSING" for row in rows)),
        "baseline_beats_counts": dict(Counter(str(row.get("beats_baseline")) for row in rows)),
        "relative_flag_counts": dict(Counter(flag for row in rows for flag in row.get("relative_strength_flags", {}).get("flags", []))),
    }


def render_phase6_report(result: Phase6RunResult) -> str:
    readiness = result.readiness_summary
    decision = result.phase7_candidate_decision
    edge_summary = result.setup_edge_audit.get("summary", {})
    lines = [
        "# Phase 6 Signal Factory Readiness + Edge Audit",
        "",
        "This is a read-only audit gate. It is not a live signal, not an entry instruction, and not an execution system.",
        "",
        "## Executive Verdict",
        "",
        f"- phase6_status: `{readiness.get('phase6_status')}`",
        f"- phase7_decision: `{decision.get('phase7_decision')}`",
        f"- approved_candidates: `{len(decision.get('approved_candidates', []))}`",
        f"- watchlist_candidates: `{len(decision.get('watchlist_candidates', []))}`",
        f"- rejected_candidates: `{len(decision.get('rejected_candidates', []))}`",
        "",
        "## Feature Readiness Per Timeframe",
        "",
        "| timeframe | total | ready | partial | missing candles | missing ATR | missing OI | status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for timeframe, row in (readiness.get("feature_readiness", {}).get("by_timeframe") or {}).items():
        lines.append(
            f"| {timeframe} | {row.get('total_feature_rows', 0)} | {row.get('ready_count', 0)} | "
            f"{row.get('partial_data_count', 0)} | {row.get('missing_candles_count', 0)} | "
            f"{row.get('missing_atr_count', 0)} | {row.get('missing_oi_count', 0)} | {row.get('readiness_status')} |"
        )
    candidate = readiness.get("candidate_readiness", {})
    lines.extend(
        [
            "",
            "## Candidate Readiness Summary",
            "",
            f"- total_candidates: `{candidate.get('total_candidates', 0)}`",
            f"- eligible_candidate_count: `{candidate.get('eligible_candidate_count', 0)}`",
            f"- radar_only_count: `{candidate.get('radar_only_count', 0)}`",
            f"- conflicted_count: `{candidate.get('conflicted_count', 0)}`",
            f"- blocked_candidate_count: `{candidate.get('blocked_candidate_count', 0)}`",
            "",
            "## Strategy Arena Mapping Summary",
            "",
            f"- arena rows evaluated: `{edge_summary.get('total_rows', 0)}`",
            f"- arena verdict counts: `{edge_summary.get('arena_verdict_counts', {})}`",
            "",
            "## Baseline Comparison Summary",
            "",
            f"- beats baseline counts: `{edge_summary.get('baseline_beats_counts', {})}`",
            "",
            "## Relative Strength / Anomaly Warning",
            "",
            f"- relative/anomaly flags: `{edge_summary.get('relative_flag_counts', {})}`",
            "",
            "## Approved Phase 7 Candidates",
            "",
        ]
    )
    lines.extend(candidate_lines(decision.get("approved_candidates", [])))
    lines.extend(["", "## Watchlist Candidates", ""])
    lines.extend(candidate_lines(decision.get("watchlist_candidates", [])))
    lines.extend(["", "## Rejected Candidates", ""])
    lines.extend(candidate_lines(decision.get("rejected_candidates", [])[:25]))
    lines.extend(
        [
            "",
            "## Blockers",
            "",
            f"`{decision.get('blocked_reasons', {})}`",
            "",
            "## What To Do Next",
            "",
            "If `HAS_CANDIDATES`, move only approved rows into a shadow forward-test tracker. If `NO_PHASE7_CANDIDATE_YET`, let data grow and rerun Signal Factory, Strategy Arena, and Phase 6.",
            "",
            "## What Not To Do Yet",
            "",
            "- Do not create live execution.",
            "- Do not finalize TP/SL.",
            "- Do not mutate old classifier, scanner, outcome tracker, collectors, or Strategy Arena formula.",
        ]
    )
    return "\n".join(lines) + "\n"


def candidate_lines(candidates: list[dict[str, Any]]) -> list[str]:
    if not candidates:
        return ["No candidates."]
    lines = ["| symbol | timeframe | setup | direction | score | edge_vs_baseline | verdict |", "|---|---|---|---|---:|---:|---|"]
    for row in candidates[:50]:
        lines.append(
            f"| {row.get('symbol')} | {row.get('timeframe')} | {row.get('mapped_setup_family') or row.get('setup_type')} | "
            f"{row.get('direction')} | {row.get('total_score')} | {row.get('edge_vs_baseline')} | {row.get('phase7_verdict')} |"
        )
    return lines


def arena_payload(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "setup_family": row.get("setup_family"),
        "horizon": row.get("horizon"),
        "atr_mult": row.get("atr_mult"),
        "rr": row.get("rr"),
        "sample_size": row.get("sample_size"),
        "pessimistic_avg_r": row.get("pessimistic_avg_r"),
        "resolved_avg_r": row.get("resolved_avg_r"),
        "verdict": row.get("verdict"),
        "verdict_label": row.get("verdict_label"),
        "top_symbol_share": row.get("top_symbol_share"),
    }


def evidence_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("evidence") or {}
    return {
        "relative_strength": evidence.get("relative_strength"),
        "futures_led_flag": evidence.get("futures_led_flag"),
        "spot_led_flag": evidence.get("spot_led_flag"),
        "volume_spike": evidence.get("volume_spike"),
        "oi_change_pct": evidence.get("oi_change_pct"),
        "price_return": evidence.get("price_return"),
        "anomalies": evidence.get("anomalies") or [],
    }


def horizon_priority(timeframe: str) -> list[str]:
    return {
        "15m": ["15m", "1h"],
        "1h": ["1h", "4h"],
        "4h": ["4h"],
        "24h": ["24h"],
    }.get(timeframe, ["15m", "1h", "4h", "24h"])


def horizon_rank(horizon: str | None, priority: list[str]) -> int:
    try:
        return len(priority) - priority.index(str(horizon))
    except ValueError:
        return 0


def refresh_commands() -> list[str]:
    return [
        "backend/.venv/bin/python backend/scripts/run_multitimeframe_signal_factory_v1.py --db-path data/marketlab.db --output-dir backend/artifacts/signal_factory/v1",
        "backend/.venv/bin/python backend/scripts/run_strategy_arena_v1_atr_r_all_labels.py --db-path data/marketlab.db --output-dir backend/artifacts/strategy_arena/v1",
    ]


def dec(value: Any, fallback: Decimal) -> Decimal:
    if value is None:
        return fallback
    return Decimal(str(value))


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def share(count: int, total: int) -> Decimal:
    if not total:
        return Decimal("0")
    return Decimal(count) * Decimal("100") / Decimal(total)


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value
