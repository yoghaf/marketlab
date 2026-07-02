from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from app.services.candidate_numeric_evidence import (
    DEFAULT_ARTIFACT_PATH,
    REPO_ROOT,
    CandidateNumericEvidenceBuilder,
)


DEFAULT_DOC_PATH = REPO_ROOT / "backend" / "docs" / "candidate_numeric_evidence_audit.md"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build read-only candidate numeric evidence audit artifact.")
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_PATH)
    parser.add_argument("--doc-path", type=Path, default=DEFAULT_DOC_PATH)
    args = parser.parse_args()

    payload = CandidateNumericEvidenceBuilder().build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.doc_path.parent.mkdir(parents=True, exist_ok=True)
    args.doc_path.write_text(render_markdown(payload), encoding="utf-8")
    aggregate = payload["aggregate"]
    print(
        "candidate numeric evidence audit complete "
        f"candidates={aggregate['total_candidates']} "
        f"signal={aggregate['signal_candidate_count']} "
        f"complete={aggregate['numeric_evidence_complete_count']}"
    )


def render_markdown(payload: dict[str, Any]) -> str:
    aggregate = payload["aggregate"]
    thresholds = payload["rule_thresholds"]
    signal_items = [item for item in payload["items"] if item["candidate_status"] == "SIGNAL_CANDIDATE"]
    example = signal_items[0] if signal_items else (payload["items"][0] if payload["items"] else None)
    lines = [
        "# Candidate Numeric Evidence Audit",
        "",
        "Read-only explanation layer. This document explains labels with actual numbers, required thresholds, pass/fail status, and missing evidence fields. It is not a live signal, not final TP/SL, and not execution logic.",
        "",
        "## Aggregate",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- total_candidates: `{aggregate['total_candidates']}`",
        f"- signal_candidate_count: `{aggregate['signal_candidate_count']}`",
        f"- numeric_evidence_complete_count: `{aggregate['numeric_evidence_complete_count']}`",
        f"- numeric_evidence_incomplete_count: `{aggregate['numeric_evidence_incomplete_count']}`",
        f"- production_approved: `{aggregate.get('production_approved')}`",
        f"- phase7_decision: `{aggregate.get('phase7_decision')}`",
        f"- phase7_checklist_available: `{aggregate['phase7_checklist_available']}`",
        "",
        "## Threshold Audit",
        "",
        f"- thresholds_extracted: `{thresholds['explicit_count']}`",
        f"- thresholds_missing_or_implicit: `{thresholds['missing_or_implicit_count']}`",
        "",
        "| rule | metric | required | unit | source |",
        "|---|---|---|---|---|",
    ]
    for row in thresholds["explicit"]:
        lines.append(f"| {row['rule']} | {row['metric']} | {row['operator']} {row['value']} | {row['unit']} | {row['source']} |")
    lines.extend(["", "## Missing / Implicit Thresholds", "", "| rule | status |", "|---|---|"])
    for row in thresholds["missing_or_implicit"]:
        lines.append(f"| {row['rule']} | {row['status']} |")
    lines.extend(["", "## Top Failure Reasons", "", "| reason | count |", "|---|---:|"])
    for reason, count in aggregate["top_failure_reasons"].items():
        lines.append(f"| {reason} | {count} |")
    lines.extend(["", "## Top Missing Evidence Fields", "", "| field | count |", "|---|---:|"])
    for field, count in aggregate["missing_evidence_fields"].items():
        lines.append(f"| {field} | {count} |")
    if example:
        lines.extend(
            [
                "",
                "## Example Candidate Explanation",
                "",
                f"- symbol: `{example['symbol']}`",
                f"- timeframe: `{example['timeframe']}`",
                f"- setup: `{example['setup']}`",
                f"- candidate_status: `{example['candidate_status']}`",
                f"- final_decision: `{example['final_decision']}`",
                f"- phase7_ready: `{example['is_phase7_ready']}`",
                "",
                "### Numeric Evidence",
                "",
                "| category | metric | required | actual | result | explanation |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in example["numeric_evidence"]:
            required = f"{item['required_operator']} {item['required_value']}"
            lines.append(
                f"| {item['category']} | {item['metric']} | {required} {item['unit']} | "
                f"{item['actual_detail']} | {item['result']} | {item['explanation']} |"
            )
        lines.extend(["", "### Phase 7 Checklist", "", "| gate | required | actual | result |", "|---|---|---|---|"])
        for item in example["phase7_checklist"]:
            lines.append(f"| {item['gate']} | {item['required']} | {item['actual']} | {item['result']} |")
        lines.extend(["", "### What Needs To Improve", ""])
        for item in example["what_needs_to_improve"]:
            lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Glossary",
            "",
            f"- RR: {payload['glossary']['RR']}",
            f"- R: {payload['glossary']['R']}",
            f"- edge_vs_baseline: {payload['glossary']['edge_vs_baseline']}",
            f"- pessR: {payload['glossary']['pessR']}",
            "",
            "## Guardrails",
            "",
            "- No live signal.",
            "- No execution or order.",
            "- No final TP/SL.",
            "- No fake data.",
            "- No Signal Factory rule change.",
            "- No Phase 6 threshold change.",
            "- No Strategy Arena formula change.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
