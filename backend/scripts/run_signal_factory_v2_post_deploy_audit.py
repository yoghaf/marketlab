from __future__ import annotations

import argparse
import json
import sqlite3
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
from app.services.multitimeframe_features import DEFAULT_DB_PATH  # noqa: E402


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
EXTERNAL_FIELDS = {
    "futures_spread_pct": {
        "source_table": "futures_book_tickers",
        "source_time": "event_time",
        "alignment_table": "market_state_alignment",
        "alignment_time": "window_close_time",
        "alignment_field": "futures_spread_pct",
    },
    "spot_spread_pct": {
        "source_table": "spot_book_tickers",
        "source_time": "event_time",
        "alignment_table": "market_state_alignment",
        "alignment_time": "window_close_time",
        "alignment_field": "spot_spread_pct",
    },
    "global_long_short_ratio": {
        "source_table": "futures_global_long_short_account_ratio",
        "source_time": "timestamp",
        "alignment_table": "rich_futures_5m_alignment",
        "alignment_time": "window_close_time",
        "alignment_field": "global_long_short_ratio_avg",
    },
    "top_trader_position_ratio": {
        "source_table": "futures_top_trader_position_ratio",
        "source_time": "timestamp",
        "alignment_table": "rich_futures_5m_alignment",
        "alignment_time": "window_close_time",
        "alignment_field": "top_trader_position_ratio_avg",
    },
    "top_trader_account_ratio": {
        "source_table": "futures_top_trader_account_ratio",
        "source_time": "timestamp",
        "alignment_table": "rich_futures_5m_alignment",
        "alignment_time": "window_close_time",
        "alignment_field": "top_trader_account_ratio_avg",
    },
    "rich_alignment_status": {
        "source_table": "rich_futures_5m_alignment",
        "source_time": "window_close_time",
        "alignment_table": "rich_futures_5m_alignment",
        "alignment_time": "window_close_time",
        "alignment_field": "alignment_status",
    },
}


def field_applicable(field: str, feature: dict[str, Any]) -> bool:
    if field == "one_hour_return_pct":
        return feature.get("timeframe") == "15m"
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Signal Factory V2 post-deployment quality.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_SIGNAL_FACTORY_DIR)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC_PATH)
    args = parser.parse_args()
    audit = build_audit(args.artifact_dir, args.db_path)
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


def build_audit(artifact_dir: Path, db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
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
    applicable_missing_by_field = {field: 0 for field in MISSING_FIELDS}
    applicable_total_by_field = {field: 0 for field in MISSING_FIELDS}
    missing_symbols: dict[str, Counter] = defaultdict(Counter)
    for feature in features:
        for field in MISSING_FIELDS:
            is_missing = feature.get(field) in (None, "", [])
            if is_missing:
                missing_by_field[field] += 1
                missing_symbols[str(feature.get("symbol"))][field] += 1
            if field_applicable(field, feature):
                applicable_total_by_field[field] += 1
                if is_missing:
                    applicable_missing_by_field[field] += 1
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
    telemetry = build_ingestion_telemetry(db_path, features)
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
            "applicable_field_counts": dict(applicable_missing_by_field),
            "applicable_field_totals": dict(applicable_total_by_field),
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
        "ingestion_telemetry": telemetry,
        "internal_field_diagnosis": build_internal_diagnosis(features, applicable_missing_by_field, applicable_total_by_field),
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


def build_ingestion_telemetry(db_path: Path, features: list[dict[str, Any]]) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    feature_non_missing = Counter()
    for feature in features:
        for field in EXTERNAL_FIELDS:
            if feature.get(field) not in (None, "", []):
                feature_non_missing[field] += 1
    output: dict[str, Any] = {}
    symbols = [row["symbol"] for row in conn.execute(
        "SELECT symbol FROM marketlab_active_universe WHERE is_active = 1 ORDER BY rank ASC"
    ).fetchall()]
    for field, config in EXTERNAL_FIELDS.items():
        source = table_summary(conn, config["source_table"], config["source_time"], symbols)
        alignment = table_summary(
            conn,
            config["alignment_table"],
            config["alignment_time"],
            symbols,
            config["alignment_field"],
        )
        output[field] = {
            "source_table": config["source_table"],
            "alignment_table": config["alignment_table"],
            "source": source,
            "alignment": alignment,
            "feature_non_missing_count": int(feature_non_missing[field]),
            "breakpoint": diagnose_breakpoint(source, alignment, int(feature_non_missing[field])),
        }
    conn.close()
    return output


def table_summary(
    conn: sqlite3.Connection,
    table: str,
    time_column: str,
    symbols: list[str],
    value_column: str | None = None,
) -> dict[str, Any]:
    value_filter = f" AND {value_column} IS NOT NULL" if value_column else ""
    total = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
    successful = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE 1=1{value_filter}").fetchone()["count"]
    latest = conn.execute(f"SELECT MAX({time_column}) AS latest FROM {table} WHERE 1=1{value_filter}").fetchone()["latest"]
    symbol_rows = []
    for symbol in symbols:
        row = conn.execute(
            f"SELECT COUNT(*) AS count, MAX({time_column}) AS latest FROM {table} WHERE symbol = ?{value_filter}",
            (symbol,),
        ).fetchone()
        symbol_rows.append(
            {
                "symbol": symbol,
                "fetch_success_count": row["count"],
                "last_successful_fetch_timestamp": row["latest"],
            }
        )
    missing_symbols = [row["symbol"] for row in symbol_rows if row["fetch_success_count"] == 0]
    return {
        "row_count": total,
        "fetch_success_count": successful,
        "last_successful_fetch_timestamp": latest,
        "symbols_with_success": len(symbols) - len(missing_symbols),
        "symbols_missing": missing_symbols[:25],
        "per_symbol": symbol_rows,
    }


def diagnose_breakpoint(source: dict[str, Any], alignment: dict[str, Any], feature_non_missing: int) -> str:
    if source["fetch_success_count"] == 0:
        return "REQUEST_OR_SOURCE_EMPTY"
    if alignment["fetch_success_count"] == 0:
        return "ALIGNMENT_OR_PARSE_EMPTY"
    if feature_non_missing == 0:
        return "FEATURE_MAPPING_EMPTY"
    if feature_non_missing < alignment["fetch_success_count"]:
        return "PARTIAL_FEATURE_MAPPING"
    return "OK"


def build_internal_diagnosis(
    features: list[dict[str, Any]],
    applicable_missing: dict[str, int],
    applicable_totals: dict[str, int],
) -> dict[str, Any]:
    by_timeframe: dict[str, Counter] = defaultdict(Counter)
    for feature in features:
        timeframe = str(feature.get("timeframe"))
        for field in ("one_hour_return_pct", "range_ratio_vs_atr"):
            if feature.get(field) in (None, "", []):
                by_timeframe[field][timeframe] += 1
    return {
        "one_hour_return_pct": {
            "applicability": "15m only; non-15m null values are expected and should not be treated as missing ingestion.",
            "applicable_missing": applicable_missing.get("one_hour_return_pct", 0),
            "applicable_total": applicable_totals.get("one_hour_return_pct", 0),
            "raw_missing_by_timeframe": dict(by_timeframe["one_hour_return_pct"]),
            "diagnosis": "WARMUP_OR_CANDLE_GAP" if applicable_missing.get("one_hour_return_pct", 0) else "NOT_MISSING_FOR_APPLICABLE_15M",
        },
        "range_ratio_vs_atr": {
            "applicability": "requires ATR lookback for the same timeframe.",
            "applicable_missing": applicable_missing.get("range_ratio_vs_atr", 0),
            "applicable_total": applicable_totals.get("range_ratio_vs_atr", 0),
            "raw_missing_by_timeframe": dict(by_timeframe["range_ratio_vs_atr"]),
            "diagnosis": "ATR_WARMUP_OR_CANDLE_GAP" if applicable_missing.get("range_ratio_vs_atr", 0) else "FILLED",
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
    lines.extend(["", "### Applicable Missing Counts", "", "| field | applicable_missing | applicable_total |", "|---|---:|---:|"])
    for field, count in audit["missing_data"]["applicable_field_counts"].items():
        total = audit["missing_data"]["applicable_field_totals"].get(field, 0)
        lines.append(f"| {field} | {count} | {total} |")
    lines.extend(
        [
            "",
            f"- symbols_with_missing: `{audit['totals']['symbols_with_missing']}`",
            f"- symbols_with_missing_and_conflict: `{audit['missing_data']['conflict_overlap']['symbols_with_missing_and_conflict']}`",
            "",
            "### Ingestion Telemetry Breakpoints",
            "",
            "| field | breakpoint | source_rows | alignment_rows | feature_non_missing | latest_source | latest_alignment |",
            "|---|---|---:|---:|---:|---|---|",
        ]
    )
    for field, telemetry in audit["ingestion_telemetry"].items():
        lines.append(
            "| "
            f"{field} | "
            f"{telemetry['breakpoint']} | "
            f"{telemetry['source']['fetch_success_count']} | "
            f"{telemetry['alignment']['fetch_success_count']} | "
            f"{telemetry['feature_non_missing_count']} | "
            f"{telemetry['source']['last_successful_fetch_timestamp']} | "
            f"{telemetry['alignment']['last_successful_fetch_timestamp']} |"
        )
    lines.extend(
        [
            "",
            "### Internal Field Diagnosis",
            "",
            f"- one_hour_return_pct: `{audit['internal_field_diagnosis']['one_hour_return_pct']}`",
            f"- range_ratio_vs_atr: `{audit['internal_field_diagnosis']['range_ratio_vs_atr']}`",
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
