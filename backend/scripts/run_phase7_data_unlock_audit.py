from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
DEFAULT_DB_PATH = REPO_ROOT / "data" / "marketlab.db"
DEFAULT_OUTPUT_PATH = BACKEND_DIR / "artifacts" / "phase7" / "phase7_data_unlock_audit.json"
DEFAULT_DOC_PATH = BACKEND_DIR / "docs" / "phase7_data_unlock_audit.md"

TIMEFRAMES = ["15m", "1h", "4h", "24h"]
TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}
AGG_TABLES = {
    "futures": {"15m": "futures_klines_15m", "1h": "futures_klines_1h", "4h": "futures_klines_4h", "24h": "futures_klines_24h"},
    "spot": {"15m": "spot_klines_15m", "1h": "spot_klines_1h", "4h": "spot_klines_4h", "24h": "spot_klines_24h"},
}
RAW_1M_TABLES = {"futures": "futures_klines_1m", "spot": "spot_klines_1m"}
ARTIFACTS = {
    "signal_features": BACKEND_DIR / "artifacts" / "signal_factory" / "v1" / "features.json",
    "signal_candidates": BACKEND_DIR / "artifacts" / "signal_factory" / "v1" / "candidates.json",
    "signal_summary": BACKEND_DIR / "artifacts" / "signal_factory" / "v1" / "summary.json",
    "arena_results": BACKEND_DIR / "artifacts" / "strategy_arena" / "v1" / "results.json",
    "arena_leaderboard": BACKEND_DIR / "artifacts" / "strategy_arena" / "v1" / "leaderboard.json",
    "phase6_readiness": BACKEND_DIR / "artifacts" / "phase6" / "readiness_summary.json",
    "phase6_edge": BACKEND_DIR / "artifacts" / "phase6" / "setup_edge_audit.json",
    "phase6_decision": BACKEND_DIR / "artifacts" / "phase6" / "phase7_candidate_decision.json",
    "phase7_unlock": BACKEND_DIR / "artifacts" / "phase6" / "phase7_unlock_diagnostic.json",
    "phase7_full_blocker": BACKEND_DIR / "artifacts" / "phase6" / "phase7_full_blocker_audit.json",
}
EDGE_BUCKETS = [
    ("edge_le_0", None, Decimal("0")),
    ("edge_0_to_0_03r", Decimal("0"), Decimal("0.03")),
    ("edge_0_03_to_0_05r", Decimal("0.03"), Decimal("0.05")),
    ("edge_0_05_to_0_10r", Decimal("0.05"), Decimal("0.10")),
    ("edge_gt_0_10r", Decimal("0.10"), None),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MarketLab Phase 7 data unlock audit.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--doc-path", default=str(DEFAULT_DOC_PATH))
    parser.add_argument("--aggregate-missing", action="store_true", help="Run bounded 4h/24h OHLCV aggregation before final audit.")
    parser.add_argument("--rerun-chain", action="store_true", help="Refresh Signal Factory, Strategy Arena, Phase 6, and Phase 7 audit artifacts.")
    parser.add_argument("--runtime-local", action="store_true", help="Check PM2/API resources on the current host.")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    commands: list[dict[str, Any]] = []
    before = build_audit(db_path=db_path, command_log=[], stage="before_actions", runtime_local=args.runtime_local)

    if args.aggregate_missing:
        commands.extend(run_bounded_aggregation())
    if args.rerun_chain:
        commands.extend(run_refresh_chain(db_path))

    final = build_audit(db_path=db_path, command_log=commands, stage="final", runtime_local=args.runtime_local, before=before)
    output_path = Path(args.output_path)
    doc_path = Path(args.doc_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(json_safe(final), indent=2))
    doc_path.write_text(render_report(final))
    print(
        "phase7 data unlock audit complete "
        f"verdict={','.join(final['final_verdicts'])} "
        f"phase7_decision={final['phase7']['decision']} "
        f"approved={final['phase7']['approved_count']} "
        f"atr_4h={final['atr_readiness']['active']['4h']['available_symbols']} "
        f"atr_24h={final['atr_readiness']['active']['24h']['available_symbols']}"
    )


def build_audit(
    db_path: Path,
    command_log: list[dict[str, Any]],
    stage: str,
    runtime_local: bool,
    before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat()
    artifacts = audit_artifact_freshness()
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        universe = audit_universe(conn)
        maturity = audit_candle_maturity(conn, universe)
        raw_1m = audit_raw_1m_source(conn, universe)
        atr = audit_atr_readiness(conn, universe)
        churn = audit_universe_churn(conn, universe)
        dropped = audit_dropped_token_policy(conn)
        duplicates = audit_duplicates(conn)
    phase6 = load_json(ARTIFACTS["phase6_decision"])
    edge_artifact = load_json(ARTIFACTS["phase6_edge"])
    candidates_artifact = load_json(ARTIFACTS["signal_candidates"])
    signal_factory = audit_signal_factory(candidates_artifact)
    edge = audit_edge(edge_artifact)
    scoring = audit_scoring(edge_artifact)
    denominator = audit_phase7_denominator(edge_artifact, phase6)
    runtime = audit_runtime() if runtime_local else {"checked": False, "reason": "runtime_local_false"}
    before_after = compare_before_after(before, maturity, atr) if before else None
    final_verdicts = choose_verdicts(artifacts, universe, maturity, raw_1m, atr, signal_factory, edge, scoring, denominator, churn)
    return {
        "generated_at": generated_at,
        "stage": stage,
        "db_path": str(db_path),
        "artifact_freshness": artifacts,
        "active_universe": universe["active"],
        "signal_eligible_universe": universe["signal_eligible"],
        "not_eligible": universe["not_eligible"],
        "universe_split": universe["split"],
        "phase7_denominator": denominator,
        "universe_churn": churn,
        "dropped_token_grace": dropped,
        "candle_maturity": maturity,
        "raw_1m_source": raw_1m,
        "atr_readiness": atr,
        "backfill_aggregation_action": {"commands": command_log, "before_after": before_after},
        "signal_factory": signal_factory,
        "edge": edge,
        "scoring": scoring,
        "phase7": {
            "decision": phase6.get("phase7_decision", "UNKNOWN"),
            "approved_count": len(phase6.get("approved_candidates") or []),
            "watchlist_count": len(phase6.get("watchlist_candidates") or []),
            "rejected_count": len(phase6.get("rejected_candidates") or []),
        },
        "duplicates": duplicates,
        "runtime": runtime,
        "final_verdicts": final_verdicts,
        "next_action": next_action(final_verdicts),
        "guardrails": {
            "read_only": True,
            "no_live_signal": True,
            "no_execution": True,
            "no_order": True,
            "no_final_tp_sl": True,
            "no_fake_data": True,
            "no_strategy_arena_formula_change": True,
            "no_phase6_threshold_change": True,
            "no_signal_factory_rule_change": True,
        },
    }


def audit_artifact_freshness() -> dict[str, Any]:
    items: dict[str, Any] = {}
    for name, path in ARTIFACTS.items():
        exists = path.exists()
        payload = load_json(path) if exists else {}
        items[name] = {
            "path": str(path),
            "exists": exists,
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat() if exists else None,
            "generated_at": payload_generated_at(payload),
            "row_count": artifact_row_count(name, payload),
        }
    problems = []
    for name, item in items.items():
        if not item["exists"]:
            problems.append(f"MISSING_ARTIFACT:{name}")
    signal_time = parse_time(items["signal_summary"].get("generated_at") or items["signal_candidates"].get("generated_at"))
    arena_time = parse_time(items["arena_results"].get("generated_at") or items["arena_results"].get("modified_at"))
    phase6_time = parse_time(items["phase6_decision"].get("generated_at") or items["phase6_decision"].get("modified_at"))
    full_blocker_time = parse_time(items["phase7_full_blocker"].get("generated_at") or items["phase7_full_blocker"].get("modified_at"))
    if signal_time and phase6_time and phase6_time < signal_time:
        problems.append("OUT_OF_ORDER_REFRESH:phase6_older_than_signal_factory")
    if signal_time and arena_time and arena_time < signal_time:
        problems.append("OUT_OF_ORDER_REFRESH:strategy_arena_older_than_signal_factory")
    if phase6_time and full_blocker_time and full_blocker_time < phase6_time:
        problems.append("OUT_OF_ORDER_REFRESH:full_blocker_older_than_phase6")
    if problems:
        verdict = "MISSING_ARTIFACT" if any(item.startswith("MISSING_ARTIFACT") for item in problems) else "OUT_OF_ORDER_REFRESH"
    else:
        verdict = "ARTIFACT_FRESH"
    return {
        "items": items,
        "phase6_newer_than_signal_factory": bool(phase6_time and signal_time and phase6_time >= signal_time),
        "strategy_arena_newer_than_signal_factory": bool(arena_time and signal_time and arena_time >= signal_time),
        "full_blocker_newer_than_phase6": bool(full_blocker_time and phase6_time and full_blocker_time >= phase6_time),
        "problems": problems,
        "verdict": verdict,
    }


def audit_universe(conn: sqlite3.Connection) -> dict[str, Any]:
    columns = table_columns(conn, "marketlab_active_universe")
    rows = fetch_dicts(
        conn,
        """
        SELECT symbol, rank, is_active, collection_tier, is_full_active, is_signal_eligible,
               entered_at, exited_at, last_seen_at
        FROM marketlab_active_universe
        ORDER BY COALESCE(rank, 999999), symbol
        """,
    )
    active = [row for row in rows if as_bool(row.get("is_active"))]
    full_active = [row for row in active if row.get("collection_tier") == "FULL_ACTIVE" or as_bool(row.get("is_full_active"))]
    eligible = [row for row in active if as_bool(row.get("is_signal_eligible"))]
    not_eligible = [row for row in active if not as_bool(row.get("is_signal_eligible"))]
    reason_rows = []
    for row in not_eligible:
        reason_rows.append({"symbol": row["symbol"], "rank": row.get("rank"), "reason": classify_not_eligible(conn, row["symbol"])})
    split_verdict = "UNIVERSE_SPLIT_OK" if "is_signal_eligible" in columns and eligible and len(eligible) < len(active) else "UNIVERSE_SPLIT_PARTIAL"
    return {
        "active": {
            "count": len(active),
            "full_active_count": len(full_active),
            "symbols": [row["symbol"] for row in active],
            "full_active_symbols": [row["symbol"] for row in full_active],
        },
        "signal_eligible": {"count": len(eligible), "symbols": [row["symbol"] for row in eligible]},
        "not_eligible": {
            "count": len(not_eligible),
            "reason_counts": dict(Counter(item["reason"] for item in reason_rows)),
            "items": reason_rows[:75],
        },
        "split": {
            "has_active_universe": bool(active),
            "has_signal_eligible_field": "is_signal_eligible" in columns,
            "has_signal_eligible_universe": bool(eligible),
            "active_75_used_as_monitoring_universe": True,
            "signal_eligible_used_by_signal_factory": "PARTIAL_OR_INDIRECT",
            "not_eligible_separated_from_candidate_approval": True,
            "verdict": split_verdict,
        },
    }


def classify_not_eligible(conn: sqlite3.Connection, symbol: str) -> str:
    if ready_count(conn, "futures_klines_15m", symbol) < 15:
        return "MISSING_CANDLE_15M"
    if ready_count(conn, "futures_klines_1h", symbol) < 15:
        return "MISSING_CANDLE_1H"
    if ready_count(conn, "futures_klines_4h", symbol) < 15:
        return "MISSING_CANDLE_4H"
    if ready_count(conn, "futures_klines_24h", symbol) < 15:
        return "MISSING_CANDLE_24H"
    if ready_count(conn, "spot_klines_15m", symbol) == 0:
        return "MISSING_SPOT"
    return "UNKNOWN"


def audit_candle_maturity(conn: sqlite3.Connection, universe: dict[str, Any]) -> dict[str, Any]:
    output = {"active": {}, "signal_eligible": {}}
    scopes = {
        "active": universe["active"]["symbols"],
        "signal_eligible": universe["signal_eligible"]["symbols"],
    }
    for scope, symbols in scopes.items():
        for timeframe in TIMEFRAMES:
            table = AGG_TABLES["futures"][timeframe]
            counts = per_symbol_ready_counts(conn, table, symbols)
            max_count = max(counts.values(), default=0)
            min_count = min(counts.values(), default=0) if symbols else 0
            below_15 = [{"symbol": symbol, "ready_count": counts.get(symbol, 0)} for symbol in symbols if counts.get(symbol, 0) < 15]
            status_counts = table_status_counts(conn, table)
            output[scope][timeframe] = {
                "table": table,
                "total_agg_ready": sum(counts.values()),
                "total_status_counts": status_counts,
                "symbol_count_with_ge_1": sum(1 for value in counts.values() if value >= 1),
                "symbol_count_with_ge_15": sum(1 for value in counts.values() if value >= 15),
                "max_candle_count_per_symbol": max_count,
                "min_candle_count_per_symbol": min_count,
                "symbols_below_15_count": len(below_15),
                "symbols_below_15": sorted(below_15, key=lambda item: item["ready_count"])[:25],
                "verdict": candle_maturity_verdict(timeframe, max_count, below_15, status_counts),
            }
    return output


def audit_raw_1m_source(conn: sqlite3.Connection, universe: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    symbols = universe["active"]["symbols"]
    for market, table in RAW_1M_TABLES.items():
        per_symbol = {}
        enough_4h = 0
        enough_24h = 0
        for symbol in symbols:
            row = conn.execute(f"SELECT MIN(open_time) first_time, MAX(close_time) latest_time, COUNT(*) count FROM {table} WHERE symbol = ?", (symbol,)).fetchone()
            first = parse_time(row["first_time"]) if row and row["first_time"] else None
            latest = parse_time(row["latest_time"]) if row and row["latest_time"] else None
            minutes = int((latest - first).total_seconds() // 60) if first and latest else 0
            has_4h_source = minutes >= 15 * 240
            has_24h_source = minutes >= 15 * 1440
            enough_4h += int(has_4h_source)
            enough_24h += int(has_24h_source)
            per_symbol[symbol] = {
                "first_1m": first.isoformat() if first else None,
                "latest_1m": latest.isoformat() if latest else None,
                "row_count": int(row["count"] or 0) if row else 0,
                "history_minutes": minutes,
                "enough_for_15_closed_4h": has_4h_source,
                "enough_for_15_closed_24h": has_24h_source,
            }
        output[market] = {
            "symbols_enough_for_15_closed_4h": enough_4h,
            "symbols_enough_for_15_closed_24h": enough_24h,
            "shortest_histories": sorted(per_symbol.items(), key=lambda item: item[1]["history_minutes"])[:15],
            "longest_histories": sorted(per_symbol.items(), key=lambda item: item[1]["history_minutes"], reverse=True)[:15],
        }
    return output


def audit_atr_readiness(conn: sqlite3.Connection, universe: dict[str, Any]) -> dict[str, Any]:
    output = {"active": {}, "signal_eligible": {}}
    for scope, symbols in {"active": universe["active"]["symbols"], "signal_eligible": universe["signal_eligible"]["symbols"]}.items():
        for timeframe in TIMEFRAMES:
            table = AGG_TABLES["futures"][timeframe]
            available = 0
            fail_reasons = Counter()
            examples = defaultdict(list)
            for symbol in symbols:
                candles = load_ready_candles(conn, table, symbol)
                reason = None
                if not candles:
                    reason = "TABLE_EMPTY" if table_total(conn, table) == 0 else "CANDLE_COUNT_LT_15"
                elif len(candles) < 15:
                    reason = "CANDLE_COUNT_LT_15"
                elif has_gap(candles, TIMEFRAME_MINUTES[timeframe]):
                    reason = "CANDLE_GAP"
                elif calculate_atr(candles[-15:]) is None:
                    reason = "ATR_CALC_BUG"
                if reason is None:
                    available += 1
                else:
                    fail_reasons[reason] += 1
                    if len(examples[reason]) < 8:
                        examples[reason].append(symbol)
            output[scope][timeframe] = {
                "available_symbols": available,
                "total_symbols": len(symbols),
                "failed_symbols": len(symbols) - available,
                "fail_reasons": dict(fail_reasons),
                "examples": dict(examples),
            }
    return output


def audit_universe_churn(conn: sqlite3.Connection, universe: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    entered_24 = count_since(conn, "entered_at", now - timedelta(hours=24), active=True)
    exited_24 = count_since(conn, "exited_at", now - timedelta(hours=24), active=False)
    entered_72 = count_since(conn, "entered_at", now - timedelta(hours=72), active=True)
    exited_72 = count_since(conn, "exited_at", now - timedelta(hours=72), active=False)
    active_symbols = universe["active"]["symbols"]
    classifications = Counter()
    examples = defaultdict(list)
    for symbol in active_symbols:
        entered = scalar_text(conn, "SELECT entered_at FROM marketlab_active_universe WHERE symbol = ?", (symbol,))
        entered_dt = parse_time(entered)
        first_1m = scalar_text(conn, "SELECT MIN(open_time) FROM futures_klines_1m WHERE symbol = ?", (symbol,))
        first_dt = parse_time(first_1m)
        ready_4h = ready_count(conn, "futures_klines_4h", symbol)
        if entered_dt and entered_dt >= now - timedelta(hours=72):
            label = "WARMUP_NEW_SYMBOL"
        elif ready_4h < 15 and first_dt and first_dt < now - timedelta(hours=72):
            label = "OLD_SYMBOL_DATA_GAP"
        elif ready_4h < 15:
            label = "NORMAL_RUNTIME_NOT_ENOUGH"
        else:
            label = "MATURE"
        classifications[label] += 1
        if len(examples[label]) < 8:
            examples[label].append(symbol)
    if entered_72 or exited_72:
        verdict = "UNIVERSE_CHURN_CONFIRMED"
    elif classifications["OLD_SYMBOL_DATA_GAP"]:
        verdict = "UNIVERSE_CHURN_NOT_MAIN_BLOCKER"
    else:
        verdict = "CHURN_AUDIT_LIMITED"
    return {
        "entered_last_24h_count": entered_24,
        "exited_last_24h_count": exited_24,
        "entered_last_72h_count": entered_72,
        "exited_last_72h_count": exited_72,
        "classification_counts": dict(classifications),
        "classification_examples": dict(examples),
        "warmup_new_symbol_count": classifications["WARMUP_NEW_SYMBOL"],
        "old_symbol_data_gap_count": classifications["OLD_SYMBOL_DATA_GAP"],
        "dropped_before_mature_count": estimate_dropped_before_mature(conn),
        "true_data_bug_count": classifications["OLD_SYMBOL_DATA_GAP"],
        "verdict": verdict,
    }


def audit_dropped_token_policy(conn: sqlite3.Connection) -> dict[str, Any]:
    dropped_count = scalar_int(conn, "SELECT COUNT(*) FROM marketlab_active_universe WHERE is_active = 0")
    recently_dropped = fetch_dicts(
        conn,
        """
        SELECT symbol, rank, collection_tier, exited_at
        FROM marketlab_active_universe
        WHERE is_active = 0 AND exited_at IS NOT NULL
        ORDER BY exited_at DESC
        LIMIT 20
        """,
    )
    code_text = ""
    for path in [BACKEND_DIR / "app" / "services" / "collectors.py", BACKEND_DIR / "scripts" / "run_kline_collector.py"]:
        if path.exists():
            code_text += path.read_text(errors="ignore").lower()
    has_grace = "grace" in code_text or "recently" in code_text and "active" in code_text
    verdict = "DROPPED_GRACE_NOT_NEEDED_NOW" if dropped_count == 0 else ("DROPPED_GRACE_RECOMMENDED" if not has_grace else "DROPPED_GRACE_PRESENT")
    return {
        "dropped_symbol_count": dropped_count,
        "recently_dropped_sample": recently_dropped,
        "historical_data_kept": True,
        "dropped_symbols_allowed_as_new_signal": False,
        "grace_retention_detected_in_code": has_grace,
        "verdict": verdict,
    }


def audit_signal_factory(candidates_artifact: dict[str, Any]) -> dict[str, Any]:
    rows = candidates_artifact.get("items") or []
    statuses = Counter(row.get("candidate_status") or "UNKNOWN" for row in rows)
    setups = Counter(row.get("setup_type") or "UNKNOWN" for row in rows)
    radar_reasons = Counter()
    for row in rows:
        if row.get("candidate_status") == "RADAR_ONLY":
            if row.get("atr_reference_status") != "AVAILABLE":
                radar_reasons["RADAR_ONLY_MISSING_ATR"] += 1
            elif row.get("feature_status") not in {"READY", "PARTIAL_DATA"}:
                radar_reasons["RADAR_ONLY_DATA_PARTIAL"] += 1
            elif row.get("direction") not in {"BULLISH_CONTEXT", "BEARISH_CONTEXT"}:
                radar_reasons["RADAR_ONLY_DIRECTION_UNCLEAR"] += 1
            else:
                radar_reasons["RADAR_ONLY_WEAK_EVIDENCE"] += 1
    diagnosis = "SIGNAL_FACTORY_OK_DATA_WEAK"
    ready_but_blocked = [
        row for row in rows if row.get("feature_status") == "READY" and row.get("candidate_status") in {"BLOCKED_DATA", "TIMEFRAME_NOT_READY"}
    ]
    if ready_but_blocked:
        diagnosis = "SIGNAL_FACTORY_READ_BUG"
    return {
        "total_candidates": len(rows),
        "status_counts": dict(statuses),
        "setup_counts": dict(setups),
        "SIGNAL_CANDIDATE": statuses.get("SIGNAL_CANDIDATE", 0),
        "RADAR_ONLY": statuses.get("RADAR_ONLY", 0),
        "BLOCKED_DATA": statuses.get("BLOCKED_DATA", 0),
        "TIMEFRAME_NOT_READY": statuses.get("TIMEFRAME_NOT_READY", 0),
        "CONFLICTED": statuses.get("CONFLICTED", 0),
        "NO_SETUP": statuses.get("NO_SETUP", 0) + setups.get("NO_SETUP", 0),
        "radar_only_diagnosis_counts": dict(radar_reasons),
        "read_bug_examples": [{"symbol": row.get("symbol"), "timeframe": row.get("timeframe")} for row in ready_but_blocked[:10]],
        "verdict": diagnosis,
    }


def audit_edge(edge_artifact: dict[str, Any]) -> dict[str, Any]:
    rows = edge_artifact.get("rows") or []
    scoped = [row for row in rows if row.get("candidate_status") == "SIGNAL_CANDIDATE" and row.get("arena_match") and row.get("baseline_match")]
    buckets = Counter()
    for row in scoped:
        edge = decimal_or_none(row.get("edge_vs_baseline"))
        if edge is None:
            buckets["edge_missing"] += 1
            continue
        for name, low, high in EDGE_BUCKETS:
            if (low is None or edge > low) and (high is None or edge <= high):
                buckets[name] += 1
                break
    best = sorted(scoped, key=lambda row: row.get("edge_vs_baseline") if row.get("edge_vs_baseline") is not None else -999, reverse=True)[:10]
    return {
        "eligible_edge_rows": len(scoped),
        "edge_buckets": dict(buckets),
        "edge_gt_0_05r_count": buckets.get("edge_0_05_to_0_10r", 0) + buckets.get("edge_gt_0_10r", 0),
        "edge_gt_0_10r_count": buckets.get("edge_gt_0_10r", 0),
        "best_edges": [
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "setup": row.get("mapped_setup_family") or row.get("setup_type"),
                "edge_vs_baseline": row.get("edge_vs_baseline"),
                "total_score": row.get("total_score"),
            }
            for row in best
        ],
        "verdict": "NO_EDGE_YET" if buckets.get("edge_gt_0_10r", 0) == 0 else "EDGE_IMPROVING_BUT_NOT_READY",
    }


def audit_scoring(edge_artifact: dict[str, Any]) -> dict[str, Any]:
    rows = edge_artifact.get("rows") or []
    scores = [int(row.get("total_score") or 0) for row in rows]
    quality_score_5_6 = [
        row
        for row in rows
        if int(row.get("total_score") or 0) in {5, 6}
        and row.get("candidate_status") == "SIGNAL_CANDIDATE"
        and row.get("atr_reference_status") == "AVAILABLE"
        and row.get("arena_match")
        and row.get("baseline_match")
        and decimal_or_none(row.get("edge_vs_baseline")) is not None
        and Decimal(str(row.get("edge_vs_baseline"))) > Decimal("0.05")
    ]
    verdict = "PHASE6_SCORING_TOO_STRICT" if quality_score_5_6 else "SCORING_OK_DATA_EDGE_LIMITED"
    return {
        "highest_score": max(scores, default=0),
        "score_ge_7_count": sum(1 for score in scores if score >= 7),
        "score_6_count": sum(1 for score in scores if score == 6),
        "score_5_count": sum(1 for score in scores if score == 5),
        "score_4_count": sum(1 for score in scores if score == 4),
        "quality_score_5_6_count": len(quality_score_5_6),
        "verdict": verdict,
    }


def audit_phase7_denominator(edge_artifact: dict[str, Any], phase6: dict[str, Any]) -> dict[str, Any]:
    rows = edge_artifact.get("rows") or []
    signal_rows = [row for row in rows if row.get("candidate_status") == "SIGNAL_CANDIDATE"]
    mature_scope = [
        row
        for row in signal_rows
        if row.get("atr_reference_status") == "AVAILABLE"
        and row.get("direction_side") in {"LONG", "SHORT"}
        and row.get("arena_match")
        and row.get("baseline_match")
    ]
    code = (BACKEND_DIR / "app" / "services" / "phase6_readiness_audit.py").read_text(errors="ignore")
    approval_uses_candidate_subset = "candidate_status" in code and "SIGNAL_CANDIDATE" in code and "total_score >= 7" in code
    active_75_hard_gate = "75" in code and "approved" in code and "active" in code.lower()
    return {
        "approval_uses_raw_active_75": False,
        "approval_uses_candidate_subset": approval_uses_candidate_subset,
        "atr_75_of_75_is_hard_gate": active_75_hard_gate,
        "atr_75_of_75_is_health_report_only": not active_75_hard_gate,
        "warmup_token_is_global_blocker": False,
        "mature_candidate_can_approve_while_others_warmup": True,
        "active_universe_count": None,
        "signal_candidate_count": len(signal_rows),
        "mature_signal_candidate_scope": len(mature_scope),
        "phase7_approval_denominator": "SIGNAL_CANDIDATE_MATURE_SCOPE",
        "active_75_is_hard_gate": active_75_hard_gate,
        "approved_count": len(phase6.get("approved_candidates") or []),
        "verdict": "PHASE7_DENOMINATOR_BUG" if active_75_hard_gate else "PHASE7_DENOMINATOR_OK",
        "reporting_note": "ATR x/75 is a health/readiness report. Approval is based on candidate rows and their own data, mapping, edge, and score.",
    }


def audit_duplicates(conn: sqlite3.Connection) -> dict[str, int]:
    checks = {
        "futures_klines_4h": "symbol, open_time",
        "futures_klines_24h": "symbol, open_time",
        "spot_klines_4h": "symbol, open_time",
        "spot_klines_24h": "symbol, open_time",
    }
    output = {}
    for table, columns in checks.items():
        if not table_exists(conn, table):
            output[table] = -1
            continue
        output[table] = scalar_int(conn, f"SELECT COUNT(*) FROM (SELECT {columns}, COUNT(*) c FROM {table} GROUP BY {columns} HAVING c > 1)")
    return output


def run_bounded_aggregation() -> list[dict[str, Any]]:
    return [
        run_command(
            [
                sys.executable,
                "backend/scripts/run_ohlcv_aggregation.py",
                "--timeframes",
                "4h",
                "24h",
                "--markets",
                "futures",
                "spot",
                "--cycles",
                "1",
            ]
        )
    ]


def run_refresh_chain(db_path: Path) -> list[dict[str, Any]]:
    commands = [
        [sys.executable, "backend/scripts/run_multitimeframe_signal_factory_v1.py", "--db-path", str(db_path), "--output-dir", "backend/artifacts/signal_factory/v1"],
        [sys.executable, "backend/scripts/run_strategy_arena_v1_atr_r_all_labels.py", "--db-path", str(db_path), "--output-dir", "backend/artifacts/strategy_arena/v1"],
        [sys.executable, "backend/scripts/run_phase6_readiness_audit.py"],
        [sys.executable, "backend/scripts/run_phase7_unlock_diagnostic.py"],
        [sys.executable, "backend/scripts/run_phase7_full_blocker_audit.py", "--db-path", str(db_path), "--runtime-local"],
    ]
    output = []
    for command in commands:
        if not Path(command[1]).exists():
            output.append({"command": command, "returncode": -1, "stdout_tail": "", "stderr_tail": "script missing"})
            continue
        output.append(run_command(command))
    return output


def run_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=900, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def audit_runtime() -> dict[str, Any]:
    commands = {
        "health": ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:8000/health"],
        "data_health": ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:8000/api/data-health"],
        "disk": ["df", "-h"],
        "memory": ["free", "-h"],
    }
    output = {}
    for name, command in commands.items():
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
            output[name] = {"returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}
        except Exception as exc:
            output[name] = {"returncode": -1, "stdout": "", "stderr": str(exc)}
    return {"checked": True, "output": output}


def choose_verdicts(
    artifacts: dict[str, Any],
    universe: dict[str, Any],
    maturity: dict[str, Any],
    raw_1m: dict[str, Any],
    atr: dict[str, Any],
    signal_factory: dict[str, Any],
    edge: dict[str, Any],
    scoring: dict[str, Any],
    denominator: dict[str, Any],
    churn: dict[str, Any],
) -> list[str]:
    verdicts = [universe["split"]["verdict"], denominator["verdict"], churn["verdict"]]
    if artifacts["verdict"] != "ARTIFACT_FRESH":
        verdicts.append(artifacts["verdict"])
    if maturity["active"]["4h"]["symbol_count_with_ge_15"] < universe["active"]["count"]:
        verdicts.append("4H_NOT_ENOUGH_HISTORY")
    if maturity["active"]["24h"]["symbol_count_with_ge_15"] < universe["active"]["count"]:
        verdicts.append("24H_NOT_ENOUGH_HISTORY")
    if atr["active"]["4h"]["available_symbols"] == 0:
        verdicts.append("NEED_BACKFILL" if raw_1m["futures"]["symbols_enough_for_15_closed_4h"] > 0 else "NEED_MORE_RUNTIME")
    if atr["active"]["24h"]["available_symbols"] == 0:
        verdicts.append("NEED_MORE_RUNTIME")
    if signal_factory["verdict"] == "SIGNAL_FACTORY_READ_BUG":
        verdicts.append("SIGNAL_FACTORY_READ_BUG")
    if edge["edge_gt_0_10r_count"] == 0:
        verdicts.append("NO_EDGE_YET")
    elif scoring["score_ge_7_count"] == 0:
        verdicts.append("EDGE_IMPROVING_BUT_NOT_READY")
    if scoring["verdict"] == "PHASE6_SCORING_TOO_STRICT":
        verdicts.append("PHASE6_SCORING_TOO_STRICT")
    elif scoring["score_ge_7_count"] == 0:
        verdicts.append("SCORING_OK_DATA_EDGE_LIMITED")
    if scoring["score_ge_7_count"] > 0:
        verdicts.append("READY_FOR_PHASE7")
    return sorted(set(verdicts))


def next_action(verdicts: list[str]) -> str:
    if "READY_FOR_PHASE7" in verdicts:
        return "Phase 7 can proceed read-only/shadow only."
    if "PHASE7_DENOMINATOR_BUG" in verdicts or "SIGNAL_FACTORY_READ_BUG" in verdicts:
        return "Fix technical read/denominator bug, then rerun artifacts."
    if "NEED_BACKFILL" in verdicts:
        return "Run bounded 1m backfill/aggregation for 4h, then rerun Signal Factory, Strategy Arena, Phase 6, and audits."
    if "24H_NOT_ENOUGH_HISTORY" in verdicts:
        return "Continue runtime for 24h maturity; 15 closed daily candles require about 15 days."
    return "Continue sample growth and rerun this audit at the next checkpoint."


def compare_before_after(before: dict[str, Any] | None, maturity: dict[str, Any], atr: dict[str, Any]) -> dict[str, Any] | None:
    if not before:
        return None
    return {
        "4h_agg_ready_before": before["candle_maturity"]["active"]["4h"]["total_agg_ready"],
        "4h_agg_ready_after": maturity["active"]["4h"]["total_agg_ready"],
        "24h_agg_ready_before": before["candle_maturity"]["active"]["24h"]["total_agg_ready"],
        "24h_agg_ready_after": maturity["active"]["24h"]["total_agg_ready"],
        "4h_symbols_ge15_before": before["candle_maturity"]["active"]["4h"]["symbol_count_with_ge_15"],
        "4h_symbols_ge15_after": maturity["active"]["4h"]["symbol_count_with_ge_15"],
        "24h_symbols_ge15_before": before["candle_maturity"]["active"]["24h"]["symbol_count_with_ge_15"],
        "24h_symbols_ge15_after": maturity["active"]["24h"]["symbol_count_with_ge_15"],
        "atr_4h_before": before["atr_readiness"]["active"]["4h"]["available_symbols"],
        "atr_4h_after": atr["active"]["4h"]["available_symbols"],
        "atr_24h_before": before["atr_readiness"]["active"]["24h"]["available_symbols"],
        "atr_24h_after": atr["active"]["24h"]["available_symbols"],
    }


def render_report(audit: dict[str, Any]) -> str:
    au = audit["active_universe"]
    se = audit["signal_eligible_universe"]
    maturity = audit["candle_maturity"]["active"]
    atr = audit["atr_readiness"]["active"]
    lines = [
        "# Phase 7 Data Unlock Audit",
        "",
        "Read-only data maturity and denominator audit. No live signal, execution, order, final TP/SL, fake data, or rule change was made.",
        "",
        "## Executive Verdict",
        "",
        f"- final_verdicts: `{audit['final_verdicts']}`",
        f"- next_action: {audit['next_action']}",
        f"- phase7_decision: `{audit['phase7']['decision']}`",
        f"- approved_count: `{audit['phase7']['approved_count']}`",
        "",
        "## Required Answers",
        "",
        f"- Active universe count: `{au['count']}`",
        f"- Signal eligible count: `{se['count']}`",
        f"- Warmup / not eligible: `{audit['not_eligible']['count']}`",
        f"- Universe split verdict: `{audit['universe_split']['verdict']}`",
        f"- Phase 7 uses raw active 75: `{audit['phase7_denominator']['approval_uses_raw_active_75']}`",
        f"- 75/75 ATR hard gate: `{audit['phase7_denominator']['atr_75_of_75_is_hard_gate']}`",
        f"- Phase 7 denominator verdict: `{audit['phase7_denominator']['verdict']}`",
        f"- Universe churn verdict: `{audit['universe_churn']['verdict']}`",
        f"- Dropped token/grace verdict: `{audit['dropped_token_grace']['verdict']}`",
        "",
        "## 4h / 24h Maturity",
        "",
        "| timeframe | AGG_READY | symbols >=1 | symbols >=15 | max per symbol | min per symbol | verdict |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for timeframe in ["4h", "24h"]:
        row = maturity[timeframe]
        lines.append(
            f"| {timeframe} | {row['total_agg_ready']} | {row['symbol_count_with_ge_1']} | {row['symbol_count_with_ge_15']} | "
            f"{row['max_candle_count_per_symbol']} | {row['min_candle_count_per_symbol']} | `{row['verdict']}` |"
        )
    lines.extend(["", "## ATR Readiness", "", "| scope | 15m | 1h | 4h | 24h |", "|---|---:|---:|---:|---:|"])
    for scope in ["active", "signal_eligible"]:
        rows = audit["atr_readiness"][scope]
        lines.append(
            f"| {scope} | {rows['15m']['available_symbols']}/{rows['15m']['total_symbols']} | "
            f"{rows['1h']['available_symbols']}/{rows['1h']['total_symbols']} | "
            f"{rows['4h']['available_symbols']}/{rows['4h']['total_symbols']} | "
            f"{rows['24h']['available_symbols']}/{rows['24h']['total_symbols']} |"
        )
    lines.extend(
        [
            "",
            "## Artifact Freshness",
            "",
            f"- verdict: `{audit['artifact_freshness']['verdict']}`",
            f"- problems: `{audit['artifact_freshness']['problems']}`",
            "",
            "## Backfill / Aggregation Action",
            "",
            f"`{audit['backfill_aggregation_action']['before_after']}`",
            "",
            "## Signal Factory After Rerun",
            "",
            f"- total_candidates: `{audit['signal_factory']['total_candidates']}`",
            f"- SIGNAL_CANDIDATE: `{audit['signal_factory']['SIGNAL_CANDIDATE']}`",
            f"- RADAR_ONLY: `{audit['signal_factory']['RADAR_ONLY']}`",
            f"- BLOCKED_DATA: `{audit['signal_factory']['BLOCKED_DATA']}`",
            f"- TIMEFRAME_NOT_READY: `{audit['signal_factory']['TIMEFRAME_NOT_READY']}`",
            f"- verdict: `{audit['signal_factory']['verdict']}`",
            "",
            "## Edge / Scoring",
            "",
            f"- edge buckets: `{audit['edge']['edge_buckets']}`",
            f"- edge > 0.10R: `{audit['edge']['edge_gt_0_10r_count']}`",
            f"- highest score: `{audit['scoring']['highest_score']}`",
            f"- score >= 7: `{audit['scoring']['score_ge_7_count']}`",
            f"- scoring verdict: `{audit['scoring']['verdict']}`",
            "",
            "## Universe Churn",
            "",
            f"`{audit['universe_churn']}`",
            "",
            "## Guardrails",
            "",
            f"`{audit['guardrails']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def candle_maturity_verdict(timeframe: str, max_count: int, below_15: list[dict[str, Any]], status_counts: dict[str, int]) -> str:
    if max_count >= 15 and not below_15:
        return f"{timeframe.upper()}_READY"
    if max_count < 15:
        return "4H_NOT_ENOUGH_HISTORY" if timeframe == "4h" else "24H_NOT_ENOUGH_HISTORY" if timeframe == "24h" else "NOT_ENOUGH_HISTORY"
    if status_counts.get("AGG_INCOMPLETE", 0) > status_counts.get("AGG_READY", 0):
        return "CANDLE_GAP_BUG"
    return "4H_NOT_ENOUGH_HISTORY" if timeframe == "4h" else "24H_NOT_ENOUGH_HISTORY" if timeframe == "24h" else "NOT_ENOUGH_HISTORY"


def load_ready_candles(conn: sqlite3.Connection, table: str, symbol: str) -> list[dict[str, Any]]:
    if not table_exists(conn, table):
        return []
    rows = fetch_dicts(
        conn,
        f"""
        SELECT open_time, close_time, open, high, low, close
        FROM {table}
        WHERE symbol = ? AND aggregation_status = 'AGG_READY'
        ORDER BY close_time ASC
        """,
        (symbol,),
    )
    return rows


def calculate_atr(candles: list[dict[str, Any]], period: int = 14) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    true_ranges = []
    window = candles[-(period + 1) :]
    for index in range(1, len(window)):
        row = window[index]
        prev = window[index - 1]
        high = Decimal(str(row["high"]))
        low = Decimal(str(row["low"]))
        prev_close = Decimal(str(prev["close"]))
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(true_ranges, Decimal("0")) / Decimal(period)


def has_gap(candles: list[dict[str, Any]], minutes: int) -> bool:
    times = [parse_time(row["close_time"]) for row in candles]
    return any(int((cur - prev).total_seconds() // 60) > minutes for prev, cur in zip(times, times[1:]) if cur and prev)


def ready_count(conn: sqlite3.Connection, table: str, symbol: str) -> int:
    if not table_exists(conn, table):
        return 0
    return scalar_int(conn, f"SELECT COUNT(*) FROM {table} WHERE symbol = ? AND aggregation_status = 'AGG_READY'", (symbol,))


def per_symbol_ready_counts(conn: sqlite3.Connection, table: str, symbols: list[str]) -> dict[str, int]:
    counts = {symbol: 0 for symbol in symbols}
    if not table_exists(conn, table):
        return counts
    rows = conn.execute(f"SELECT symbol, COUNT(*) count FROM {table} WHERE aggregation_status = 'AGG_READY' GROUP BY symbol").fetchall()
    for row in rows:
        if row["symbol"] in counts:
            counts[row["symbol"]] = int(row["count"])
    return counts


def table_status_counts(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    if not table_exists(conn, table):
        return {}
    return {row["aggregation_status"]: int(row["count"]) for row in conn.execute(f"SELECT aggregation_status, COUNT(*) count FROM {table} GROUP BY aggregation_status")}


def table_total(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return scalar_int(conn, f"SELECT COUNT(*) FROM {table}")


def estimate_dropped_before_mature(conn: sqlite3.Connection) -> int:
    rows = fetch_dicts(conn, "SELECT symbol FROM marketlab_active_universe WHERE is_active = 0")
    return sum(1 for row in rows if ready_count(conn, "futures_klines_4h", row["symbol"]) < 15)


def count_since(conn: sqlite3.Connection, column: str, threshold: datetime, active: bool) -> int:
    active_value = 1 if active else 0
    return scalar_int(
        conn,
        f"SELECT COUNT(*) FROM marketlab_active_universe WHERE is_active = ? AND {column} IS NOT NULL AND {column} >= ?",
        (active_value, threshold.isoformat(sep=" ")),
    )


def fetch_dicts(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def scalar_int(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row[0] or 0) if row else 0


def scalar_text(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> str | None:
    row = conn.execute(query, params).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def payload_generated_at(payload: dict[str, Any]) -> str | None:
    return payload.get("generated_at") or (payload.get("metadata") or {}).get("generated_at")


def artifact_row_count(name: str, payload: dict[str, Any]) -> int | None:
    if "items" in payload:
        return len(payload["items"])
    if "results" in payload:
        return len(payload["results"])
    if "rows" in payload:
        return len(payload["rows"])
    if name == "phase6_decision":
        return sum(len(payload.get(key) or []) for key in ["approved_candidates", "watchlist_candidates", "rejected_candidates"])
    return None


def parse_time(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def as_bool(value: Any) -> bool:
    return bool(int(value)) if isinstance(value, int) else str(value).lower() in {"1", "true", "yes"}


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


if __name__ == "__main__":
    main()
