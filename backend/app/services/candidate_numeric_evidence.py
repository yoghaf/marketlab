from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SIGNAL_FACTORY_DIR = REPO_ROOT / "backend" / "artifacts" / "signal_factory" / "v1"
DEFAULT_STRATEGY_ARENA_DIR = REPO_ROOT / "backend" / "artifacts" / "strategy_arena" / "v1"
DEFAULT_PHASE6_DIR = REPO_ROOT / "backend" / "artifacts" / "phase6"
DEFAULT_PHASE7_DIR = REPO_ROOT / "backend" / "artifacts" / "phase7"
DEFAULT_ARTIFACT_PATH = DEFAULT_PHASE7_DIR / "candidate_numeric_evidence_audit.json"

PRICE_IMPULSE_THRESHOLD = 0.35
VOLUME_SPIKE_RATIO_THRESHOLD = 1.5
OI_EXPANSION_THRESHOLD_PCT = 0.10
OI_CONTRACTION_THRESHOLD_PCT = -0.10
CLOSE_NEAR_HIGH_THRESHOLD = 0.70
CLOSE_NEAR_LOW_THRESHOLD = 0.30
FUTURES_LED_PRICE_THRESHOLD_PCT = 0.25
RELATIVE_OUTPERFORM_THRESHOLD_PCT = 0.50
RELATIVE_UNDERPERFORM_THRESHOLD_PCT = -0.50
PHASE7_EDGE_THRESHOLD_R = 0.10
PHASE7_SCORE_THRESHOLD = 7
PHASE7_ARENA_OK = {"MONITOR_MORE", "PROMISING_FOR_FORWARD_TEST"}

REQUESTED_FIELD_GROUPS = {
    "price": [
        "open",
        "close",
        "high",
        "low",
        "price_change_pct",
        "move_pct",
        "candle_return_pct",
        "distance_from_high_pct",
        "distance_from_low_pct",
    ],
    "volume": [
        "quote_volume_current",
        "quote_volume_avg",
        "quote_volume_avg_20",
        "volume_ratio",
        "volume_zscore",
        "current_15m_volume_usd",
        "avg_15m_volume_usd",
    ],
    "oi": ["oi_current", "oi_previous", "oi_delta", "oi_delta_pct", "oi_delta_zscore"],
    "relative_strength": [
        "symbol_return_pct",
        "btc_return_pct",
        "eth_return_pct",
        "relative_strength_vs_btc",
        "relative_strength_vs_market",
        "market_rank_change",
    ],
    "funding_flow": ["funding_rate", "funding_delta", "futures_spot_divergence", "taker_buy_ratio", "futures_led_flag"],
    "atr_risk": ["atr_reference_timeframe", "atr_reference_value", "atr_reference_status", "atr_15m", "atr_1h", "atr_4h", "atr_24h"],
    "strategy_edge": [
        "arena_verdict",
        "setup_pessR",
        "baseline_pessR",
        "edge_vs_baseline",
        "beats_baseline",
        "sample_count",
        "win_rate",
        "expectancy",
    ],
    "phase6": ["score", "score_required", "reason_codes", "approved", "watchlist"],
}


class CandidateNumericEvidenceBuilder:
    def __init__(
        self,
        signal_factory_dir: Path = DEFAULT_SIGNAL_FACTORY_DIR,
        strategy_arena_dir: Path = DEFAULT_STRATEGY_ARENA_DIR,
        phase6_dir: Path = DEFAULT_PHASE6_DIR,
    ) -> None:
        self.signal_factory_dir = signal_factory_dir
        self.strategy_arena_dir = strategy_arena_dir
        self.phase6_dir = phase6_dir

    def build(self) -> dict[str, Any]:
        features_payload = read_json(self.signal_factory_dir / "features.json")
        candidates_payload = read_json(self.signal_factory_dir / "candidates.json")
        arena_payload = read_json(self.strategy_arena_dir / "results.json")
        phase6_payload = read_json(self.phase6_dir / "setup_edge_audit.json")
        decision_payload = read_json(self.phase6_dir / "phase7_candidate_decision.json")

        features = features_payload.get("items", [])
        candidates = candidates_payload.get("items", [])
        edge_rows = phase6_payload.get("rows", [])
        arena_rows = arena_payload.get("results", [])
        feature_index = {(row.get("symbol"), row.get("timeframe")): row for row in features}
        edge_index = {(row.get("symbol"), row.get("timeframe")): row for row in edge_rows}
        arena_index = build_arena_index(arena_rows)

        items = [
            self._candidate_payload(candidate, feature_index, edge_index, arena_index)
            for candidate in candidates
        ]
        aggregate = aggregate_report(items)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "artifact_sources": {
                "features": str(self.signal_factory_dir / "features.json"),
                "candidates": str(self.signal_factory_dir / "candidates.json"),
                "strategy_arena": str(self.strategy_arena_dir / "results.json"),
                "phase6_edge": str(self.phase6_dir / "setup_edge_audit.json"),
                "phase6_decision": str(self.phase6_dir / "phase7_candidate_decision.json"),
            },
            "rule_thresholds": rule_thresholds(),
            "field_availability": field_availability(features, candidates, edge_rows, arena_rows),
            "aggregate": {
                **aggregate,
                "phase7_decision": decision_payload.get("phase7_decision"),
                "production_approved": len(decision_payload.get("approved_candidates") or []),
            },
            "items": items,
            "glossary": glossary(),
            "guardrails": {
                "read_only": True,
                "not_live_signal": True,
                "not_execution_instruction": True,
                "no_order": True,
                "no_final_tp_sl": True,
                "no_fake_data": True,
                "no_rule_change": True,
            },
        }

    def _candidate_payload(
        self,
        candidate: dict[str, Any],
        feature_index: dict[tuple[Any, Any], dict[str, Any]],
        edge_index: dict[tuple[Any, Any], dict[str, Any]],
        arena_index: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        symbol = candidate.get("symbol")
        timeframe = candidate.get("timeframe")
        feature = feature_index.get((symbol, timeframe), {})
        edge_row = edge_index.get((symbol, timeframe), {})
        arena_match = edge_row.get("arena_match") or {}
        baseline_match = edge_row.get("baseline_match") or {}
        arena_full = lookup_arena(arena_match, arena_index) or {}
        baseline_full = lookup_arena(baseline_match, arena_index) or {}
        numeric_evidence = self._numeric_evidence(candidate, feature, edge_row, arena_full, baseline_full)
        checklist = phase7_checklist(candidate, edge_row)
        blocking_reasons = blocking_reasons_from(numeric_evidence, checklist, candidate, edge_row)
        final_decision = edge_row.get("phase7_verdict") or phase7_decision_from(candidate)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "window_start": candidate.get("window_start"),
            "window_end": candidate.get("window_end"),
            "setup": candidate.get("setup_type"),
            "mapped_setup_family": edge_row.get("mapped_setup_family"),
            "candidate_status": candidate.get("candidate_status"),
            "direction": candidate.get("direction"),
            "confidence": candidate.get("confidence"),
            "final_decision": final_decision,
            "is_phase7_ready": final_decision == "PHASE7_READY",
            "not_live_signal": True,
            "not_execution_instruction": True,
            "numeric_evidence": numeric_evidence,
            "phase7_checklist": checklist,
            "blocking_reasons": blocking_reasons,
            "what_needs_to_improve": what_needs_to_improve(edge_row, candidate, checklist),
            "missing_evidence_fields": missing_evidence_fields(numeric_evidence),
            "label_explanation": setup_label_explanation(candidate, feature, edge_row),
        }

    def _numeric_evidence(
        self,
        candidate: dict[str, Any],
        feature: dict[str, Any],
        edge_row: dict[str, Any],
        arena_full: dict[str, Any],
        baseline_full: dict[str, Any],
    ) -> list[dict[str, Any]]:
        direction = candidate.get("direction")
        setup = candidate.get("setup_type")
        rows = [
            price_evidence(direction, feature),
            volume_evidence(feature),
            oi_evidence(setup, feature),
            close_position_evidence(direction, setup, feature),
            relative_strength_evidence(direction, feature),
            futures_led_evidence(feature),
            atr_evidence(candidate, edge_row, feature),
            candidate_status_evidence(candidate),
            arena_mapping_evidence(edge_row),
            baseline_mapping_evidence(edge_row),
            edge_evidence(edge_row),
            arena_verdict_evidence(edge_row, arena_full),
            score_evidence(edge_row),
            conflict_evidence(candidate),
            arena_sample_evidence(edge_row, arena_full),
            setup_vs_baseline_evidence(edge_row, baseline_full),
        ]
        return rows


class CandidateNumericEvidenceArtifactService:
    def __init__(self, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.artifact_path = artifact_path

    def read(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        payload = read_json(self.artifact_path)
        items = payload.get("items", [])
        if symbol:
            items = [item for item in items if item.get("symbol") == symbol.upper()]
        if timeframe:
            items = [item for item in items if item.get("timeframe") == timeframe]
        if status:
            items = [item for item in items if item.get("candidate_status") == status or item.get("final_decision") == status]
        return {
            "generated_at": payload.get("generated_at"),
            "count": min(len(items), limit),
            "total_matching": len(items),
            "aggregate": payload.get("aggregate", {}),
            "rule_thresholds": payload.get("rule_thresholds", {}),
            "field_availability": payload.get("field_availability", {}),
            "glossary": payload.get("glossary", {}),
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "items": items[:limit],
        }


def evidence(
    category: str,
    metric: str,
    label: str,
    required_operator: str,
    required_value: Any,
    actual_value: Any,
    unit: str,
    result: str,
    explanation: str,
    actual_detail: str | None = None,
    source: str = "artifact",
) -> dict[str, Any]:
    return {
        "category": category,
        "metric": metric,
        "label": label,
        "required_operator": required_operator,
        "required_value": required_value,
        "actual_value": actual_value,
        "unit": unit,
        "actual_detail": actual_detail or detail_value(actual_value, unit),
        "result": result,
        "explanation": explanation,
        "source": source,
    }


def unavailable(category: str, metric: str, label: str, required: Any = None, unit: str = "") -> dict[str, Any]:
    return evidence(
        category,
        metric,
        label,
        "exists",
        required,
        None,
        unit,
        "UNAVAILABLE",
        f"{metric} belum tersedia di artifact.",
        "EVIDENCE_FIELD_NOT_EXPOSED",
    )


def price_evidence(direction: str | None, feature: dict[str, Any]) -> dict[str, Any]:
    actual = feature.get("price_return")
    if actual is None:
        return unavailable("price", "price_return", "Price impulse", f"+/-{PRICE_IMPULSE_THRESHOLD}")
    if direction == "BULLISH_CONTEXT":
        passed = actual >= PRICE_IMPULSE_THRESHOLD
        required_operator = ">="
        required_value = PRICE_IMPULSE_THRESHOLD
    elif direction == "BEARISH_CONTEXT":
        passed = actual <= -PRICE_IMPULSE_THRESHOLD
        required_operator = "<="
        required_value = -PRICE_IMPULSE_THRESHOLD
    else:
        passed = abs(actual) >= PRICE_IMPULSE_THRESHOLD
        required_operator = "abs >="
        required_value = PRICE_IMPULSE_THRESHOLD
    return evidence(
        "price",
        "price_return",
        "Price impulse",
        required_operator,
        required_value,
        actual,
        "%",
        pass_fail(passed),
        f"Price return aktual {format_number(actual)}%; rule impulse membutuhkan {required_operator} {required_value}%.",
    )


def volume_evidence(feature: dict[str, Any]) -> dict[str, Any]:
    actual = feature.get("volume_ratio_vs_lookback")
    volume = feature.get("volume_sum")
    if actual is None:
        return unavailable("volume", "volume_ratio_vs_lookback", "Volume spike", VOLUME_SPIKE_RATIO_THRESHOLD, "x_avg")
    avg = volume / actual if volume is not None and actual else None
    detail = f"current volume {format_number(volume)} vs avg {format_number(avg)}" if avg is not None else None
    return evidence(
        "volume",
        "volume_ratio_vs_lookback",
        "Volume spike",
        ">=",
        VOLUME_SPIKE_RATIO_THRESHOLD,
        actual,
        "x_avg",
        pass_fail(actual >= VOLUME_SPIKE_RATIO_THRESHOLD),
        f"Volume ratio aktual {format_number(actual)}x; rule spike membutuhkan >= {VOLUME_SPIKE_RATIO_THRESHOLD}x.",
        detail,
    )


def oi_evidence(setup: str | None, feature: dict[str, Any]) -> dict[str, Any]:
    actual = feature.get("oi_change_pct")
    if actual is None:
        return unavailable("oi", "oi_change_pct", "OI support", OI_EXPANSION_THRESHOLD_PCT, "%")
    if setup == "SQUEEZE":
        required_operator = "<="
        required_value = OI_CONTRACTION_THRESHOLD_PCT
        passed = actual <= OI_CONTRACTION_THRESHOLD_PCT
    else:
        required_operator = ">="
        required_value = OI_EXPANSION_THRESHOLD_PCT
        passed = actual >= OI_EXPANSION_THRESHOLD_PCT
    return evidence(
        "oi",
        "oi_change_pct",
        "OI support",
        required_operator,
        required_value,
        actual,
        "%",
        pass_fail(passed),
        f"OI change aktual {format_number(actual)}%; threshold rule {required_operator} {required_value}%.",
    )


def close_position_evidence(direction: str | None, setup: str | None, feature: dict[str, Any]) -> dict[str, Any]:
    actual = feature.get("close_position_in_range")
    if actual is None:
        return unavailable("price", "close_position_in_range", "Close location", None, "0_to_1")
    if direction == "BULLISH_CONTEXT" or setup == "EARLY_LONG":
        return evidence(
            "price",
            "close_position_in_range",
            "Close near high",
            ">=",
            CLOSE_NEAR_HIGH_THRESHOLD,
            actual,
            "0_to_1",
            pass_fail(actual >= CLOSE_NEAR_HIGH_THRESHOLD),
            f"Close position aktual {format_number(actual)}; close-near-high threshold >= {CLOSE_NEAR_HIGH_THRESHOLD}.",
        )
    if direction == "BEARISH_CONTEXT" or setup == "EARLY_SHORT":
        return evidence(
            "price",
            "close_position_in_range",
            "Close near low",
            "<=",
            CLOSE_NEAR_LOW_THRESHOLD,
            actual,
            "0_to_1",
            pass_fail(actual <= CLOSE_NEAR_LOW_THRESHOLD),
            f"Close position aktual {format_number(actual)}; close-near-low threshold <= {CLOSE_NEAR_LOW_THRESHOLD}.",
        )
    return evidence(
        "price",
        "close_position_in_range",
        "Close location",
        "RULE_THRESHOLD_NOT_EXPLICIT",
        None,
        actual,
        "0_to_1",
        "INFO",
        "Close location tersedia, tapi label mixed/no-setup tidak punya threshold final eksplisit.",
    )


def relative_strength_evidence(direction: str | None, feature: dict[str, Any]) -> dict[str, Any]:
    actual = feature.get("relative_return")
    label = feature.get("relative_strength")
    if actual is None:
        return unavailable("relative_strength", "relative_return", "Relative strength", None, "%")
    if direction == "BULLISH_CONTEXT":
        passed = actual >= RELATIVE_OUTPERFORM_THRESHOLD_PCT
        operator = ">="
        required = RELATIVE_OUTPERFORM_THRESHOLD_PCT
    elif direction == "BEARISH_CONTEXT":
        passed = actual <= RELATIVE_UNDERPERFORM_THRESHOLD_PCT
        operator = "<="
        required = RELATIVE_UNDERPERFORM_THRESHOLD_PCT
    else:
        passed = label in {"OUTPERFORMING", "UNDERPERFORMING", "INLINE_WITH_MARKET"}
        operator = "classified"
        required = "OUTPERFORMING/UNDERPERFORMING/INLINE_WITH_MARKET"
    return evidence(
        "relative_strength",
        "relative_return",
        "Relative strength",
        operator,
        required,
        actual,
        "%",
        pass_fail(passed),
        f"Relative return aktual {format_number(actual)}%, label {label}.",
    )


def futures_led_evidence(feature: dict[str, Any]) -> dict[str, Any]:
    actual = feature.get("futures_led_flag")
    if actual is None:
        return unavailable("flow", "futures_led_flag", "Futures-led context", "boolean", "bool")
    return evidence(
        "flow",
        "futures_led_flag",
        "Futures-led context",
        "equals",
        True,
        actual,
        "bool",
        pass_fail(actual is True),
        f"Futures-led flag aktual {actual}; rule futures-led juga membutuhkan price abs >= {FUTURES_LED_PRICE_THRESHOLD_PCT}%, volume spike, dan OI > 0.",
    )


def atr_evidence(candidate: dict[str, Any], edge_row: dict[str, Any], feature: dict[str, Any]) -> dict[str, Any]:
    status = candidate.get("atr_reference_status") or edge_row.get("atr_reference_status")
    timeframe = candidate.get("atr_reference_timeframe") or edge_row.get("atr_reference_timeframe")
    value = feature.get("atr") if timeframe == candidate.get("timeframe") else None
    detail = f"reference timeframe {timeframe}; ATR value current timeframe {format_number(value) if value is not None else 'EVIDENCE_FIELD_NOT_EXPOSED'}"
    return evidence(
        "atr_risk",
        "atr_reference_status",
        "ATR reference",
        "equals",
        "AVAILABLE",
        status,
        "status",
        pass_fail(status == "AVAILABLE"),
        f"ATR reference status aktual {status}; candidate memakai reference {timeframe}.",
        detail,
    )


def candidate_status_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    status = candidate.get("candidate_status")
    return evidence(
        "candidate",
        "candidate_status",
        "Signal Factory candidate status",
        "equals",
        "SIGNAL_CANDIDATE",
        status,
        "status",
        pass_fail(status == "SIGNAL_CANDIDATE"),
        f"Candidate status aktual {status}.",
    )


def arena_mapping_evidence(edge_row: dict[str, Any]) -> dict[str, Any]:
    actual = bool(edge_row.get("arena_match"))
    return evidence(
        "phase7",
        "arena_match",
        "Arena mapping",
        "exists",
        True,
        actual,
        "bool",
        pass_fail(actual),
        f"Arena mapping {'tersedia' if actual else 'tidak tersedia'}.",
    )


def baseline_mapping_evidence(edge_row: dict[str, Any]) -> dict[str, Any]:
    actual = bool(edge_row.get("baseline_match"))
    return evidence(
        "phase7",
        "baseline_match",
        "Baseline mapping",
        "exists",
        True,
        actual,
        "bool",
        pass_fail(actual),
        f"Baseline mapping {'tersedia' if actual else 'tidak tersedia'}.",
    )


def edge_evidence(edge_row: dict[str, Any]) -> dict[str, Any]:
    actual = edge_row.get("edge_vs_baseline")
    if actual is None:
        return unavailable("edge", "edge_vs_baseline", "Edge vs baseline", PHASE7_EDGE_THRESHOLD_R, "R")
    return evidence(
        "edge",
        "edge_vs_baseline",
        "Edge vs baseline",
        ">",
        PHASE7_EDGE_THRESHOLD_R,
        actual,
        "R",
        pass_fail(actual > PHASE7_EDGE_THRESHOLD_R),
        f"edge_vs_baseline aktual {format_number(actual)}R; required > {PHASE7_EDGE_THRESHOLD_R}R.",
        f"setup {format_number(edge_row.get('setup_pessR'))}R vs baseline {format_number(edge_row.get('baseline_pessR'))}R",
    )


def arena_verdict_evidence(edge_row: dict[str, Any], arena_full: dict[str, Any]) -> dict[str, Any]:
    verdict = (edge_row.get("arena_match") or {}).get("verdict")
    detail = f"sample {arena_full.get('sample_size')}; pessR {format_number(arena_full.get('pessimistic_avg_r'))}R"
    return evidence(
        "arena",
        "arena_verdict",
        "Arena verdict",
        "in",
        sorted(PHASE7_ARENA_OK),
        verdict,
        "status",
        pass_fail(verdict in PHASE7_ARENA_OK),
        f"Arena verdict aktual {verdict}; required minimal MONITOR_MORE.",
        detail,
    )


def score_evidence(edge_row: dict[str, Any]) -> dict[str, Any]:
    score = edge_row.get("total_score")
    if score is None:
        return unavailable("phase6", "total_score", "Phase 6 score", PHASE7_SCORE_THRESHOLD, "points")
    return evidence(
        "phase6",
        "total_score",
        "Phase 6 score",
        ">=",
        PHASE7_SCORE_THRESHOLD,
        score,
        "points",
        pass_fail(score >= PHASE7_SCORE_THRESHOLD),
        f"Score aktual {score}; required >= {PHASE7_SCORE_THRESHOLD}.",
    )


def conflict_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    conflict = candidate.get("conflict_status") or "NONE"
    return evidence(
        "candidate",
        "conflict_status",
        "Conflict status",
        "equals",
        "NONE",
        conflict,
        "status",
        pass_fail(conflict == "NONE"),
        f"Conflict status aktual {conflict}.",
    )


def arena_sample_evidence(edge_row: dict[str, Any], arena_full: dict[str, Any]) -> dict[str, Any]:
    sample = (edge_row.get("arena_match") or {}).get("sample_size") or arena_full.get("sample_size")
    if sample is None:
        return unavailable("arena", "sample_size", "Arena sample size", "min_sample from Strategy Arena", "rows")
    return evidence(
        "arena",
        "sample_size",
        "Arena sample size",
        "RULE_THRESHOLD_NOT_EXPLICIT",
        "Strategy Arena min_sample config",
        sample,
        "rows",
        "INFO",
        "Sample size tersedia. Threshold sample berasal dari konfigurasi Strategy Arena, bukan Phase 7 candidate gate langsung.",
    )


def setup_vs_baseline_evidence(edge_row: dict[str, Any], baseline_full: dict[str, Any]) -> dict[str, Any]:
    setup = edge_row.get("setup_pessR")
    baseline = edge_row.get("baseline_pessR")
    if setup is None or baseline is None:
        return unavailable("edge", "setup_pessR_vs_baseline_pessR", "Setup vs baseline pessR", None, "R")
    return evidence(
        "edge",
        "setup_pessR_vs_baseline_pessR",
        "Setup pessR vs baseline pessR",
        ">",
        "baseline_pessR",
        setup,
        "R",
        pass_fail(setup > baseline),
        f"Setup pessR {format_number(setup)}R dibanding baseline {format_number(baseline)}R.",
        f"baseline sample {baseline_full.get('sample_size')}",
    )


def phase7_checklist(candidate: dict[str, Any], edge_row: dict[str, Any]) -> list[dict[str, Any]]:
    arena_verdict = (edge_row.get("arena_match") or {}).get("verdict")
    edge = edge_row.get("edge_vs_baseline")
    score = edge_row.get("total_score")
    conflict = candidate.get("conflict_status") or "NONE"
    status = candidate.get("candidate_status")
    return [
        gate("ATR reference available", "atr_reference_status = AVAILABLE", candidate.get("atr_reference_status"), candidate.get("atr_reference_status") == "AVAILABLE"),
        gate("Arena mapping", "arena_match exists", bool(edge_row.get("arena_match")), bool(edge_row.get("arena_match"))),
        gate("Baseline mapping", "baseline_match exists", bool(edge_row.get("baseline_match")), bool(edge_row.get("baseline_match"))),
        gate("Edge", f"edge_vs_baseline > +{PHASE7_EDGE_THRESHOLD_R}R", edge, edge is not None and edge > PHASE7_EDGE_THRESHOLD_R),
        gate("Arena verdict", "MONITOR_MORE or PROMISING_FOR_FORWARD_TEST", arena_verdict, arena_verdict in PHASE7_ARENA_OK),
        gate("Score", f"score >= {PHASE7_SCORE_THRESHOLD}", score, score is not None and score >= PHASE7_SCORE_THRESHOLD),
        gate("Conflict", "conflict_status = NONE", conflict, conflict == "NONE"),
        gate("Candidate status", "candidate_status = SIGNAL_CANDIDATE", status, status == "SIGNAL_CANDIDATE"),
    ]


def gate(name: str, required: str, actual: Any, passed: bool) -> dict[str, Any]:
    return {
        "gate": name,
        "required": required,
        "actual": actual,
        "result": pass_fail(passed),
    }


def blocking_reasons_from(
    numeric_evidence: list[dict[str, Any]],
    checklist: list[dict[str, Any]],
    candidate: dict[str, Any],
    edge_row: dict[str, Any],
) -> list[str]:
    reasons = []
    if candidate.get("atr_reference_status") != "AVAILABLE":
        reasons.append("ATR_MISSING")
    edge = edge_row.get("edge_vs_baseline")
    if edge is None:
        reasons.append("EDGE_MISSING")
    elif edge <= PHASE7_EDGE_THRESHOLD_R:
        reasons.append("EDGE_BELOW_THRESHOLD")
    arena_verdict = (edge_row.get("arena_match") or {}).get("verdict")
    if arena_verdict == "NOISY":
        reasons.append("ARENA_NOISY")
    elif arena_verdict == "REJECT":
        reasons.append("ARENA_REJECT")
    elif arena_verdict not in PHASE7_ARENA_OK:
        reasons.append("ARENA_NOT_OK")
    score = edge_row.get("total_score")
    if score is None or score < PHASE7_SCORE_THRESHOLD:
        reasons.append("SCORE_BELOW_7")
    if candidate.get("confidence") == "LOW":
        reasons.append("LOW_CONFIDENCE")
    if candidate.get("feature_status") == "PARTIAL_DATA":
        reasons.append("DATA_PARTIAL")
    if candidate.get("candidate_status") != "SIGNAL_CANDIDATE":
        reasons.append("NOT_SIGNAL_CANDIDATE")
    if candidate.get("conflict_status") not in {None, "NONE"}:
        reasons.append("CONFLICTED")
    for item in numeric_evidence:
        if item["result"] == "UNAVAILABLE":
            reasons.append("EVIDENCE_FIELD_NOT_EXPOSED")
            break
    return sorted(set(reasons))


def what_needs_to_improve(edge_row: dict[str, Any], candidate: dict[str, Any], checklist: list[dict[str, Any]]) -> list[str]:
    items = []
    edge = edge_row.get("edge_vs_baseline")
    if edge is None:
        items.append("edge_vs_baseline harus tersedia di artifact Phase 6.")
    elif edge <= PHASE7_EDGE_THRESHOLD_R:
        items.append(f"edge_vs_baseline harus naik dari {format_number(edge)}R ke > {PHASE7_EDGE_THRESHOLD_R}R.")
    arena = (edge_row.get("arena_match") or {}).get("verdict")
    if arena not in PHASE7_ARENA_OK:
        items.append(f"Arena verdict harus naik dari {arena or 'missing'} ke minimal MONITOR_MORE.")
    score = edge_row.get("total_score")
    if score is None or score < PHASE7_SCORE_THRESHOLD:
        items.append(f"Score harus naik dari {score if score is not None else 'missing'} ke >= {PHASE7_SCORE_THRESHOLD}.")
    if candidate.get("confidence") == "LOW":
        items.append("Confidence harus membaik dari LOW melalui evidence price/OI/flow yang lebih jelas.")
    if candidate.get("feature_status") == "PARTIAL_DATA":
        items.append("Data partial harus membaik menjadi READY atau penalty data tetap menahan score.")
    if not items and all(row["result"] == "PASS" for row in checklist):
        items.append("Semua gate pass.")
    return items


def setup_label_explanation(candidate: dict[str, Any], feature: dict[str, Any], edge_row: dict[str, Any]) -> dict[str, Any]:
    setup = candidate.get("setup_type")
    status = candidate.get("candidate_status")
    messages = []
    if setup == "MID_LONG":
        messages.append("MID_LONG muncul saat price impulse naik dan OI expansion memenuhi rule.")
    elif setup == "MID_SHORT":
        family = edge_row.get("mapped_setup_family") or "MID_SHORT"
        messages.append(f"{family} muncul saat price impulse turun dan OI expansion memenuhi rule; futures-led ditentukan dari flag futures_led.")
    elif setup == "EARLY_LONG":
        messages.append("EARLY_LONG muncul saat price naik dan close dekat high, tanpa full OI expansion confirmation.")
    elif setup == "EARLY_SHORT":
        messages.append("EARLY_SHORT muncul saat price turun dan close dekat low, tanpa full OI expansion confirmation.")
    elif setup == "SQUEEZE":
        messages.append("SQUEEZE muncul saat price bergerak berlawanan dengan OI contraction; ini risk/context, bukan directional approval.")
    elif setup == "BLOCKED_DATA":
        messages.append("BLOCKED_DATA muncul karena feature_status masuk kategori blocking atau missing.")
    else:
        messages.append("Setup tidak punya rule directional eksplisit atau belum memenuhi anomaly utama.")
    if status == "RADAR_ONLY":
        messages.append("RADAR_ONLY berarti evidence belum cukup menjadi SIGNAL_CANDIDATE, ATR missing, weak evidence, atau context masih campuran.")
    if status == "SIGNAL_CANDIDATE":
        messages.append("SIGNAL_CANDIDATE berarti data usable, direction valid, setup evidence cukup, dan ATR reference tersedia; ini belum otomatis Phase 7 ready.")
    return {
        "setup": setup,
        "candidate_status": status,
        "feature_status": candidate.get("feature_status"),
        "numeric_context": {
            "price_return": feature.get("price_return"),
            "volume_ratio_vs_lookback": feature.get("volume_ratio_vs_lookback"),
            "oi_change_pct": feature.get("oi_change_pct"),
            "relative_return": feature.get("relative_return"),
            "edge_vs_baseline": edge_row.get("edge_vs_baseline"),
            "total_score": edge_row.get("total_score"),
        },
        "explanation": messages,
    }


def missing_evidence_fields(numeric_evidence: list[dict[str, Any]]) -> list[str]:
    return [item["metric"] for item in numeric_evidence if item["result"] == "UNAVAILABLE"]


def field_availability(
    features: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    edge_rows: list[dict[str, Any]],
    arena_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    sample_feature = features[0] if features else {}
    sample_candidate = candidates[0] if candidates else {}
    sample_edge = edge_rows[0] if edge_rows else {}
    sample_arena = arena_rows[0] if arena_rows else {}
    available_aliases = {
        "price_change_pct": "price_return" in sample_feature,
        "move_pct": "price_return_abs" in sample_feature,
        "candle_return_pct": "price_return" in sample_feature,
        "volume_ratio": "volume_ratio_vs_lookback" in sample_feature,
        "current_15m_volume_usd": "volume_sum" in sample_feature,
        "avg_15m_volume_usd": "volume_ratio_vs_lookback" in sample_feature and "volume_sum" in sample_feature,
        "oi_delta": "oi_change" in sample_feature,
        "oi_delta_pct": "oi_change_pct" in sample_feature,
        "symbol_return_pct": "symbol_return" in sample_feature,
        "btc_return_pct": "benchmark_return" in sample_feature,
        "relative_strength_vs_btc": "relative_return" in sample_feature,
        "relative_strength_vs_market": "relative_strength" in sample_feature,
        "funding_rate": "funding_rate" in sample_feature,
        "futures_led_flag": "futures_led_flag" in sample_feature,
        "atr_reference_timeframe": "atr_reference_timeframe" in sample_candidate,
        "atr_reference_status": "atr_reference_status" in sample_candidate,
        "atr_15m": "atr" in sample_feature,
        "arena_verdict": bool(sample_edge.get("arena_match")),
        "setup_pessR": "setup_pessR" in sample_edge,
        "baseline_pessR": "baseline_pessR" in sample_edge,
        "edge_vs_baseline": "edge_vs_baseline" in sample_edge,
        "beats_baseline": "beats_baseline" in sample_edge,
        "sample_count": "sample_size" in sample_arena,
        "score": "total_score" in sample_edge,
        "score_required": True,
        "reason_codes": "rejection_reasons" in sample_edge,
        "approved": "phase7_verdict" in sample_edge,
        "watchlist": "phase7_verdict" in sample_edge,
    }
    grouped = {}
    missing_counter = Counter()
    for group, fields in REQUESTED_FIELD_GROUPS.items():
        grouped[group] = {}
        for field in fields:
            available = available_aliases.get(field, field in sample_feature or field in sample_candidate or field in sample_edge or field in sample_arena)
            grouped[group][field] = "AVAILABLE" if available else "EVIDENCE_FIELD_NOT_EXPOSED"
            if not available:
                missing_counter[field] += 1
    return {
        "groups": grouped,
        "top_missing_fields": dict(missing_counter.most_common(20)),
    }


def rule_thresholds() -> dict[str, Any]:
    explicit = [
        threshold("PRICE_UP_IMPULSE", "price_return", ">=", PRICE_IMPULSE_THRESHOLD, "%", "anomaly_signal_factory.py"),
        threshold("PRICE_DOWN_IMPULSE", "price_return", "<=", -PRICE_IMPULSE_THRESHOLD, "%", "anomaly_signal_factory.py"),
        threshold("VOLUME_SPIKE", "volume_ratio_vs_lookback", ">=", VOLUME_SPIKE_RATIO_THRESHOLD, "x_avg", "multitimeframe_features.py"),
        threshold("OI_EXPANSION", "oi_change_pct", ">=", OI_EXPANSION_THRESHOLD_PCT, "%", "anomaly_signal_factory.py"),
        threshold("OI_CONTRACTION", "oi_change_pct", "<=", OI_CONTRACTION_THRESHOLD_PCT, "%", "anomaly_signal_factory.py"),
        threshold("CLOSE_NEAR_HIGH", "close_position_in_range", ">=", CLOSE_NEAR_HIGH_THRESHOLD, "0_to_1", "anomaly_signal_factory.py"),
        threshold("CLOSE_NEAR_LOW", "close_position_in_range", "<=", CLOSE_NEAR_LOW_THRESHOLD, "0_to_1", "anomaly_signal_factory.py"),
        threshold("FUTURES_LED", "abs(price_return)", ">=", FUTURES_LED_PRICE_THRESHOLD_PCT, "%", "multitimeframe_features.py"),
        threshold("RELATIVE_OUTPERFORM", "relative_return", ">=", RELATIVE_OUTPERFORM_THRESHOLD_PCT, "%", "multitimeframe_features.py"),
        threshold("RELATIVE_UNDERPERFORM", "relative_return", "<=", RELATIVE_UNDERPERFORM_THRESHOLD_PCT, "%", "multitimeframe_features.py"),
        threshold("PHASE7_EDGE", "edge_vs_baseline", ">", PHASE7_EDGE_THRESHOLD_R, "R", "phase6_readiness_audit.py"),
        threshold("PHASE7_SCORE", "total_score", ">=", PHASE7_SCORE_THRESHOLD, "points", "phase6_readiness_audit.py"),
        threshold("ARENA_NOISY", "pessimistic_avg_r", "<", 0.10, "R", "strategy_arena.py"),
    ]
    implicit = [
        "EARLY_LONG final confidence threshold",
        "EARLY_SHORT final confidence threshold",
        "SQUEEZE volatility compression threshold",
        "RADAR_ONLY promotion threshold beyond coded branch order",
        "WATCHLIST_FOR_MORE_DATA semantic threshold beyond score bands",
        "win_rate",
        "expectancy",
    ]
    return {
        "explicit_count": len(explicit),
        "missing_or_implicit_count": len(implicit),
        "explicit": explicit,
        "missing_or_implicit": [{"rule": item, "status": "RULE_THRESHOLD_NOT_EXPLICIT"} for item in implicit],
    }


def threshold(rule: str, metric: str, operator: str, value: Any, unit: str, source: str) -> dict[str, Any]:
    return {
        "rule": rule,
        "metric": metric,
        "operator": operator,
        "value": value,
        "unit": unit,
        "source": source,
        "status": "EXPLICIT",
    }


def aggregate_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    signal_items = [item for item in items if item["candidate_status"] == "SIGNAL_CANDIDATE"]
    complete = [item for item in items if not item["missing_evidence_fields"]]
    missing_fields = Counter(field for item in items for field in item["missing_evidence_fields"])
    failure_reasons = Counter(reason for item in items for reason in item["blocking_reasons"])
    return {
        "total_candidates": len(items),
        "signal_candidate_count": len(signal_items),
        "numeric_evidence_complete_count": len(complete),
        "numeric_evidence_incomplete_count": len(items) - len(complete),
        "missing_evidence_fields": dict(missing_fields.most_common()),
        "top_failure_reasons": dict(failure_reasons.most_common(20)),
        "phase7_checklist_available": True,
        "items_with_phase7_ready": sum(1 for item in items if item["is_phase7_ready"]),
    }


def build_arena_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    return {
        (str(row.get("setup_family")), str(row.get("horizon")), str(row.get("atr_mult")), str(row.get("rr"))): row
        for row in rows
    }


def lookup_arena(payload: dict[str, Any], index: dict[tuple[str, str, str, str], dict[str, Any]]) -> dict[str, Any] | None:
    if not payload:
        return None
    return index.get((str(payload.get("setup_family")), str(payload.get("horizon")), str(payload.get("atr_mult")), str(payload.get("rr"))))


def phase7_decision_from(candidate: dict[str, Any]) -> str:
    status = candidate.get("candidate_status")
    if status == "SIGNAL_CANDIDATE":
        return "WATCHLIST_FOR_MORE_DATA"
    if status == "RADAR_ONLY":
        return "RADAR_ONLY"
    return "REJECT_FOR_PHASE7"


def detail_value(value: Any, unit: str) -> str:
    if value is None:
        return "EVIDENCE_FIELD_NOT_EXPOSED"
    return f"{format_number(value)} {unit}".strip()


def pass_fail(value: bool) -> str:
    return "PASS" if value else "FAIL"


def format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def glossary() -> dict[str, str]:
    return {
        "RR": "Risk reward ratio dari test setup. Contoh target 2R dan stop 1R berarti RR 2.",
        "R": "Unit risiko. Kalau entry 100 dan stop 98, maka 1R = 2.",
        "edge_vs_baseline": "Selisih performa setup dibanding baseline dalam satuan R. Ini bukan TP dan bukan RR.",
        "pessR": "Conservative R performance metric dari Strategy Arena.",
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Candidate numeric evidence input artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
