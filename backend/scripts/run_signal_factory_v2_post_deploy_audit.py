from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.market import SignalForwardReturnLog  # noqa: E402
from app.services.anomaly_signal_factory import DEFAULT_SIGNAL_FACTORY_DIR  # noqa: E402


DEFAULT_OUTPUT_PATH = BACKEND_DIR / "artifacts" / "signal_factory" / "v1" / "post_deploy_audit_v2.json"
DEFAULT_DOC_PATH = BACKEND_DIR / "docs" / "signal_factory_v2_post_deploy_audit.md"
MISSING_FIELDS = [
    "oi_zscore",
    "funding_percentile_30d",
    "futures_spread_pct",
    "spot_spread_pct",
    "global_long_short_ratio",
    "top_trader_position_ratio",
    "top_trader_account_ratio",
    "rich_alignment_status",
    "one_hour_return_pct",
    "range_ratio_vs_atr",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Signal Factory V2 post-deployment quality.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_SIGNAL_FACTORY_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC_PATH)
    args = parser.parse_args()
    audit = build_audit(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(render_doc(audit), encoding="utf-8")
    print(
        "signal_factory_v2_post_deploy_audit complete "
        f"features={audit['totals']['features']} "
        f"candidates={audit['totals']['candidates']} "
        f"signals={audit['funnel']['SIGNAL_CANDIDATE']} "
        f"forward_log_rows={audit['forward_return_logging']['total_rows']}"
    )


def build_audit(artifact_dir: Path) -> dict[str, Any]:
    features_payload = read_json(artifact_dir / "features.json")
    candidates_payload = read_json(artifact_dir / "candidates.json")
    features = features_payload.get("items") or []
    candidates = candidates_payload.get("items") or []
    conflict_symbols = {
        item.get("symbol")
        for item in candidates
        if item.get("conflict_status") == "TIMEFRAME_CONFLICT"
    }
    missing_by_field = {field: 0 for field in MISSING_FIELDS}
    missing_symbols: dict[str, Counter] = defaultdict(Counter)
    for feature in features:
        for field in MISSING_FIELDS:
            if feature.get(field) in (None, "", []):
                missing_by_field[field] += 1
                missing_symbols[str(feature.get("symbol"))][field] += 1
    symbols_with_missing = set(missing_symbols)
    evidence_zero = {"genuine_neutral": 0, "unavailable_or_low_completeness": 0}
    evidence_completeness = Counter()
    for candidate in candidates:
        evidence = candidate.get("evidence") or {}
        completeness = evidence.get("evidence_data_completeness")
        evidence_completeness[str(completeness)] += 1
        if candidate.get("evidence_score") == 0 or evidence.get("evidence_score") == 0:
            if completeness is None or int(completeness or 0) < 2:
                evidence_zero["unavailable_or_low_completeness"] += 1
            else:
                evidence_zero["genuine_neutral"] += 1
    signal_candidates = [item for item in candidates if item.get("candidate_status") == "SIGNAL_CANDIDATE"]
    watch_only = Counter()
    for item in signal_candidates:
        evidence = item.get("evidence") or {}
        flags = evidence.get("execution_risk_flags") or []
        if evidence.get("execution_risk_status") != "WATCH_ONLY":
            continue
        if "SPREAD_UNKNOWN" in flags:
            watch_only["spread_unavailable"] += 1
        elif "WIDE_SPREAD" in flags:
            watch_only["wide_spread"] += 1
        else:
            watch_only["other_watch_only"] += 1
    with SessionLocal() as db:
        forward_total = db.query(SignalForwardReturnLog).count()
        forward_latest = db.query(SignalForwardReturnLog.updated_at).order_by(SignalForwardReturnLog.updated_at.desc()).limit(1).scalar()
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "artifact_generated_at": candidates_payload.get("generated_at"),
        "totals": {
            "features": len(features),
            "candidates": len(candidates),
            "symbols_with_missing": len(symbols_with_missing),
            "conflict_symbols": len(conflict_symbols),
        },
        "missing_data": {
            "field_counts": dict(missing_by_field),
            "top_symbols": top_missing_symbols(missing_symbols),
            "conflict_overlap": {
                "symbols_with_missing_and_conflict": len(symbols_with_missing & conflict_symbols),
                "conflict_symbols": sorted(symbol for symbol in conflict_symbols if symbol),
            },
        },
        "evidence_score_zero": evidence_zero,
        "evidence_data_completeness": dict(sorted(evidence_completeness.items())),
        "funnel": build_funnel(candidates),
        "watch_only": dict(watch_only),
        "forward_return_logging": {
            "total_rows": forward_total,
            "latest_update": forward_latest,
            "table": "signal_forward_return_logs",
            "running": forward_total > 0,
        },
        "guardrails": {
            "read_only": True,
            "no_order_execution": True,
            "no_rule_threshold_change": True,
        },
    }


def build_funnel(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(item.get("candidate_status") for item in candidates)
    fail_layer = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        if item.get("candidate_status") == "SIGNAL_CANDIDATE":
            continue
        evidence = item.get("evidence") or {}
        if item.get("feature_status") in {"MISSING_CANDLES", "MISSING_OI", "MISSING_ATR", "STALE_DATA"}:
            layer = "missing_data"
        elif evidence.get("base_trigger") is False:
            layer = "base_trigger"
        elif evidence.get("core_score") is not None and evidence.get("core_score") < 7:
            layer = "core_score_threshold"
        elif item.get("candidate_status") == "CONFLICTED":
            layer = "conflict"
        else:
            layer = "radar_or_other"
        fail_layer[layer] += 1
        if len(examples[layer]) < 5:
            examples[layer].append(
                {
                    "symbol": item.get("symbol"),
                    "timeframe": item.get("timeframe"),
                    "setup_type": item.get("setup_type"),
                    "candidate_status": item.get("candidate_status"),
                    "core_score": evidence.get("core_score"),
                    "feature_status": item.get("feature_status"),
                }
            )
    return {
        "TOTAL_CANDIDATES": len(candidates),
        "SIGNAL_CANDIDATE": counts.get("SIGNAL_CANDIDATE", 0),
        "NON_SIGNAL": len(candidates) - counts.get("SIGNAL_CANDIDATE", 0),
        "candidate_status_counts": dict(counts),
        "non_signal_fail_layer_counts": dict(fail_layer),
        "examples": examples,
    }


def top_missing_symbols(missing_symbols: dict[str, Counter]) -> list[dict[str, Any]]:
    rows = []
    for symbol, counter in missing_symbols.items():
        rows.append({"symbol": symbol, "missing_count": sum(counter.values()), "fields": dict(counter)})
    return sorted(rows, key=lambda row: row["missing_count"], reverse=True)[:15]


def render_doc(audit: dict[str, Any]) -> str:
    lines = [
        "# Signal Factory V2 Post-Deployment Audit",
        "",
        "Read-only audit. No rule, threshold, order, or execution behavior is changed by this report.",
        "",
        f"- generated_at_utc: `{audit['generated_at_utc']}`",
        f"- artifact_generated_at: `{audit.get('artifact_generated_at')}`",
        f"- features: `{audit['totals']['features']}`",
        f"- candidates: `{audit['totals']['candidates']}`",
        f"- signal_candidates: `{audit['funnel']['SIGNAL_CANDIDATE']}`",
        "",
        "## 1. Missing Data Breakdown",
        "",
        "| field | missing_count |",
        "|---|---:|",
    ]
    for field, count in audit["missing_data"]["field_counts"].items():
        lines.append(f"| {field} | {count} |")
    lines.extend(
        [
            "",
            f"- symbols_with_missing: `{audit['totals']['symbols_with_missing']}`",
            f"- symbols_with_missing_and_conflict: `{audit['missing_data']['conflict_overlap']['symbols_with_missing_and_conflict']}`",
            "",
            "## 2. Evidence Score Zero Split",
            "",
            f"- genuine_neutral: `{audit['evidence_score_zero']['genuine_neutral']}`",
            f"- unavailable_or_low_completeness: `{audit['evidence_score_zero']['unavailable_or_low_completeness']}`",
            f"- evidence_data_completeness_counts: `{audit['evidence_data_completeness']}`",
            "",
            "## 3. Funnel",
            "",
            f"- total_candidates: `{audit['funnel']['TOTAL_CANDIDATES']}`",
            f"- signal_candidate: `{audit['funnel']['SIGNAL_CANDIDATE']}`",
            f"- non_signal: `{audit['funnel']['NON_SIGNAL']}`",
            f"- candidate_status_counts: `{audit['funnel']['candidate_status_counts']}`",
            f"- non_signal_fail_layer_counts: `{audit['funnel']['non_signal_fail_layer_counts']}`",
            "",
            "## 4. Forward-Return Logging",
            "",
            f"- table: `{audit['forward_return_logging']['table']}`",
            f"- running: `{audit['forward_return_logging']['running']}`",
            f"- total_rows: `{audit['forward_return_logging']['total_rows']}`",
            f"- latest_update: `{audit['forward_return_logging']['latest_update']}`",
            "",
            "## 5. WATCH_ONLY Breakdown",
            "",
            f"- spread_unavailable: `{audit['watch_only'].get('spread_unavailable', 0)}`",
            f"- wide_spread: `{audit['watch_only'].get('wide_spread', 0)}`",
            f"- other_watch_only: `{audit['watch_only'].get('other_watch_only', 0)}`",
            "",
            "## Verdict",
            "",
            "- Stage 7 audit artifact created.",
            "- Forward-return logging is active if total_rows > 0.",
            "- If spread_unavailable dominates WATCH_ONLY, spread ingestion/alignment should be fixed before using risk gate as a reliable discriminator.",
        ]
    )
    return "\n".join(lines) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
