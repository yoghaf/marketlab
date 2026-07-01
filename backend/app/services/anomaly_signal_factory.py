from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.multitimeframe_features import DEFAULT_DB_PATH, REPO_ROOT, MultiTimeframeFeatureService, json_safe


DEFAULT_SIGNAL_FACTORY_DIR = REPO_ROOT / "backend" / "artifacts" / "signal_factory" / "v1"
DEFAULT_TIMEFRAMES = ["15m", "1h", "4h", "24h"]
BLOCKING_FEATURE_STATUSES = {"MISSING_CANDLES", "MISSING_OI", "MISSING_ATR", "STALE_DATA"}
ATR_REFERENCE_TIMEFRAME = {"15m": "1h", "1h": "4h", "4h": "24h", "24h": "24h"}


@dataclass(frozen=True)
class FactoryRunResult:
    generated_at: str
    features: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    summary: dict[str, Any]


def detect_anomalies(feature: dict[str, Any]) -> list[str]:
    if feature["feature_status"] in BLOCKING_FEATURE_STATUSES:
        return ["DATA_NOT_READY"]

    anomalies: list[str] = []
    price_return = _decimal(feature.get("price_return"))
    oi_change_pct = _decimal(feature.get("oi_change_pct"))
    close_position = _decimal(feature.get("close_position_in_range"))
    volume_spike = bool(feature.get("volume_spike"))

    if price_return is not None and price_return >= Decimal("0.35"):
        anomalies.append("PRICE_UP_IMPULSE")
    if price_return is not None and price_return <= Decimal("-0.35"):
        anomalies.append("PRICE_DOWN_IMPULSE")
    if volume_spike:
        anomalies.append("VOLUME_SPIKE")
    if oi_change_pct is not None and oi_change_pct >= Decimal("0.10"):
        anomalies.append("OI_EXPANSION")
    if oi_change_pct is not None and oi_change_pct <= Decimal("-0.10"):
        anomalies.append("OI_CONTRACTION")
    if feature.get("futures_led_flag"):
        anomalies.append("FUTURES_LED")
    if feature.get("spot_led_flag"):
        anomalies.append("SPOT_LED")
    if feature.get("relative_strength") == "OUTPERFORMING":
        anomalies.append("RELATIVE_OUTPERFORM")
    if feature.get("relative_strength") == "UNDERPERFORMING":
        anomalies.append("RELATIVE_UNDERPERFORM")
    if close_position is not None and close_position >= Decimal("0.70"):
        anomalies.append("CLOSE_NEAR_HIGH")
    if close_position is not None and close_position <= Decimal("0.30"):
        anomalies.append("CLOSE_NEAR_LOW")
    if not anomalies:
        anomalies.append("NO_MATERIAL_ANOMALY")
    return anomalies


def classify_candidate(feature: dict[str, Any], atr_reference_status: str | None = None) -> dict[str, Any]:
    anomalies = detect_anomalies(feature)
    feature_status = feature["feature_status"]
    timeframe = feature["timeframe"]
    setup_type = "NO_SETUP"
    direction = "MIXED_CONTEXT"
    confidence = "LOW"
    candidate_status = "RADAR_ONLY"
    reason = "No material directional anomaly"

    if feature_status in BLOCKING_FEATURE_STATUSES:
        setup_type = "BLOCKED_DATA"
        candidate_status = "TIMEFRAME_NOT_READY" if feature_status == "MISSING_CANDLES" else "BLOCKED_DATA"
        reason = "; ".join(feature.get("status_reasons") or [feature_status])
    else:
        up = "PRICE_UP_IMPULSE" in anomalies
        down = "PRICE_DOWN_IMPULSE" in anomalies
        oi_expansion = "OI_EXPANSION" in anomalies
        oi_contraction = "OI_CONTRACTION" in anomalies
        futures_led = "FUTURES_LED" in anomalies
        close_high = "CLOSE_NEAR_HIGH" in anomalies
        close_low = "CLOSE_NEAR_LOW" in anomalies

        if down and oi_expansion:
            setup_type = "MID_SHORT"
            direction = "BEARISH_CONTEXT"
            candidate_status = "SIGNAL_CANDIDATE"
            confidence = "HIGH" if futures_led and feature_status == "READY" else "MEDIUM"
            reason = "Price down impulse with open interest expansion"
        elif up and oi_expansion:
            setup_type = "MID_LONG"
            direction = "BULLISH_CONTEXT"
            candidate_status = "SIGNAL_CANDIDATE"
            confidence = "MEDIUM" if feature_status == "READY" else "LOW"
            reason = "Price up impulse with open interest expansion"
        elif down and close_low:
            setup_type = "EARLY_SHORT"
            direction = "BEARISH_CONTEXT"
            candidate_status = "RADAR_ONLY"
            confidence = "LOW"
            reason = "Early bearish impulse without full expansion confirmation"
        elif up and close_high:
            setup_type = "EARLY_LONG"
            direction = "BULLISH_CONTEXT"
            candidate_status = "RADAR_ONLY"
            confidence = "LOW"
            reason = "Early bullish impulse without full expansion confirmation"
        elif up and oi_contraction:
            setup_type = "SQUEEZE"
            direction = "MIXED_CONTEXT"
            candidate_status = "RADAR_ONLY"
            confidence = "MEDIUM" if feature_status == "READY" else "LOW"
            reason = "Price up while open interest contracts; squeeze risk context"
        elif (up and close_low) or (down and close_high):
            setup_type = "TRAP_FADE"
            direction = "MIXED_CONTEXT"
            candidate_status = "RADAR_ONLY"
            confidence = "LOW"
            reason = "Impulse and close-location evidence conflict; trap/fade context"

    if atr_reference_status == "MISSING_ATR_REFERENCE" and candidate_status == "SIGNAL_CANDIDATE":
        candidate_status = "RADAR_ONLY"
        confidence = "MEDIUM" if confidence == "HIGH" else confidence

    setup_family = f"{setup_type}_{timeframe.upper().replace('M', 'M').replace('H', 'H')}"
    evidence = {
        "anomalies": anomalies,
        "price_return": feature.get("price_return"),
        "volume_spike": feature.get("volume_spike"),
        "oi_change_pct": feature.get("oi_change_pct"),
        "funding_pressure": feature.get("funding_pressure"),
        "relative_strength": feature.get("relative_strength"),
        "futures_led_flag": feature.get("futures_led_flag"),
        "spot_led_flag": feature.get("spot_led_flag"),
        "feature_status": feature_status,
        "status_reasons": feature.get("status_reasons") or [],
    }
    return {
        "symbol": feature["symbol"],
        "timeframe": timeframe,
        "window_start": feature.get("window_start"),
        "window_end": feature.get("window_end"),
        "setup_type": setup_type,
        "setup_family": setup_family,
        "setup_name": setup_family.replace("_", " ").title(),
        "direction": direction,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence,
        "feature_status": feature_status,
        "candidate_status": candidate_status,
        "atr_reference_timeframe": ATR_REFERENCE_TIMEFRAME[timeframe],
        "atr_reference_status": atr_reference_status or "AVAILABLE",
        "not_live_signal": True,
        "not_execution_instruction": True,
    }


class SignalFactoryRunner:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        output_dir: Path = DEFAULT_SIGNAL_FACTORY_DIR,
        timeframes: list[str] | None = None,
        symbol_limit: int | None = None,
    ) -> None:
        self.feature_service = MultiTimeframeFeatureService(db_path)
        self.output_dir = output_dir
        self.timeframes = timeframes or DEFAULT_TIMEFRAMES
        self.symbol_limit = symbol_limit

    def run(self) -> FactoryRunResult:
        symbols = self.feature_service.get_active_symbols(limit=self.symbol_limit)
        features = self.feature_service.build_snapshots(symbols, self.timeframes)
        by_symbol_timeframe = {(item["symbol"], item["timeframe"]): item for item in features}
        candidates = []
        for feature in features:
            atr_reference_timeframe = ATR_REFERENCE_TIMEFRAME[feature["timeframe"]]
            atr_feature = by_symbol_timeframe.get((feature["symbol"], atr_reference_timeframe))
            atr_status = None
            if not atr_feature or atr_feature.get("atr") is None:
                atr_status = "MISSING_ATR_REFERENCE"
            candidates.append(classify_candidate(feature, atr_status))

        candidates = _apply_conflict_markers(candidates)
        generated_at = datetime.now(UTC).isoformat()
        summary = build_summary(generated_at, features, candidates)
        result = FactoryRunResult(generated_at=generated_at, features=features, candidates=candidates, summary=summary)
        self.write_artifacts(result)
        self.write_report(result)
        return result

    def write_artifacts(self, result: FactoryRunResult) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "features.json").write_text(json.dumps(json_safe({"generated_at": result.generated_at, "items": result.features}), indent=2))
        (self.output_dir / "candidates.json").write_text(json.dumps(json_safe({"generated_at": result.generated_at, "items": result.candidates}), indent=2))
        (self.output_dir / "summary.json").write_text(json.dumps(json_safe(result.summary), indent=2))

    def write_report(self, result: FactoryRunResult) -> None:
        doc_path = REPO_ROOT / "backend" / "docs" / "multitimeframe_signal_factory_v1_report.md"
        summary = result.summary
        lines = [
            "# Multi-Timeframe Signal Factory v1 Report",
            "",
            "Read-only anomaly/signal-candidate factory for MarketLab multi-timeframe context. This report is not a live signal, not an entry instruction, and not an execution system.",
            "",
            f"- generated_at: `{result.generated_at}`",
            f"- feature_rows: `{summary['feature_count']}`",
            f"- candidate_rows: `{summary['candidate_count']}`",
            f"- conflict_count: `{summary['conflict_count']}`",
            f"- missing_data_count: `{summary['missing_data_count']}`",
            "",
            "## Feature Count Per Timeframe",
            "",
            "| timeframe | count |",
            "|---|---:|",
        ]
        for timeframe, count in summary["feature_count_by_timeframe"].items():
            lines.append(f"| {timeframe} | {count} |")
        lines.extend(["", "## Candidate Count Per Setup", "", "| setup_type | count |", "|---|---:|"])
        for setup, count in summary["candidate_count_by_setup"].items():
            lines.append(f"| {setup} | {count} |")
        lines.extend(["", "## Guardrails", "", "- Read-only artifact output only.", "- `not_live_signal=true` on every candidate.", "- `not_execution_instruction=true` on every candidate.", "- No order, TP/SL, leverage, position sizing, or execution logic."])
        doc_path.write_text("\n".join(lines) + "\n")


class SignalFactoryArtifactService:
    def __init__(self, artifact_dir: Path = DEFAULT_SIGNAL_FACTORY_DIR) -> None:
        self.artifact_dir = artifact_dir

    def summary(self) -> dict[str, Any]:
        return self._read_json("summary.json")

    def candidates(
        self,
        timeframe: str | None = None,
        setup_type: str | None = None,
        direction: str | None = None,
        confidence: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        payload = self._read_json("candidates.json")
        items = payload.get("items", [])
        if timeframe:
            items = [item for item in items if item.get("timeframe") == timeframe]
        if setup_type:
            items = [item for item in items if item.get("setup_type") == setup_type]
        if direction:
            items = [item for item in items if item.get("direction") == direction]
        if confidence:
            items = [item for item in items if item.get("confidence") == confidence]
        if symbol:
            items = [item for item in items if item.get("symbol") == symbol.upper()]
        if status:
            items = [item for item in items if item.get("candidate_status") == status]
        items = sorted(items, key=lambda item: (item.get("window_end") or "", item.get("symbol") or ""), reverse=True)
        return {
            "generated_at": payload.get("generated_at"),
            "count": min(len(items), limit),
            "total_matching": len(items),
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "items": items[:limit],
        }

    def candidates_for_symbol(self, symbol: str) -> dict[str, Any]:
        return self.candidates(symbol=symbol, limit=100)

    def _read_json(self, filename: str) -> dict[str, Any]:
        path = self.artifact_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Signal factory artifact not found: {path}")
        return json.loads(path.read_text())


def build_summary(generated_at: str, features: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    feature_by_timeframe = Counter(feature["timeframe"] for feature in features)
    feature_status = Counter(feature["feature_status"] for feature in features)
    candidate_by_timeframe = Counter(candidate["timeframe"] for candidate in candidates)
    candidate_by_setup = Counter(candidate["setup_type"] for candidate in candidates)
    candidate_by_status = Counter(candidate["candidate_status"] for candidate in candidates)
    conflicts = sum(1 for candidate in candidates if candidate.get("conflict_status") == "TIMEFRAME_CONFLICT")
    missing_data = sum(1 for feature in features if feature["feature_status"] in BLOCKING_FEATURE_STATUSES)
    return {
        "generated_at": generated_at,
        "feature_count": len(features),
        "candidate_count": len(candidates),
        "feature_count_by_timeframe": dict(sorted(feature_by_timeframe.items())),
        "feature_status_counts": dict(sorted(feature_status.items())),
        "candidate_count_by_timeframe": dict(sorted(candidate_by_timeframe.items())),
        "candidate_count_by_setup": dict(sorted(candidate_by_setup.items())),
        "candidate_status_counts": dict(sorted(candidate_by_status.items())),
        "conflict_count": conflicts,
        "missing_data_count": missing_data,
        "guardrails": {
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
        },
    }


def _apply_conflict_markers(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    directions_by_symbol: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        if candidate["candidate_status"] in {"SIGNAL_CANDIDATE", "RADAR_ONLY"}:
            directions_by_symbol[candidate["symbol"]].add(candidate["direction"])
    conflicted = {
        symbol
        for symbol, directions in directions_by_symbol.items()
        if "BULLISH_CONTEXT" in directions and "BEARISH_CONTEXT" in directions
    }
    output = []
    for candidate in candidates:
        row = dict(candidate)
        if row["symbol"] in conflicted and row["direction"] in {"BULLISH_CONTEXT", "BEARISH_CONTEXT"}:
            row["conflict_status"] = "TIMEFRAME_CONFLICT"
            if row["candidate_status"] == "SIGNAL_CANDIDATE":
                row["candidate_status"] = "CONFLICTED"
            row["reason"] = f"{row['reason']}; conflicting directional context exists across timeframes"
        else:
            row["conflict_status"] = "NONE"
        output.append(row)
    return output


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
