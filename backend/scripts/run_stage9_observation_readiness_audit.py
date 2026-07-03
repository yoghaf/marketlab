from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.anomaly_signal_factory import DEFAULT_SIGNAL_FACTORY_DIR  # noqa: E402
from app.services.multitimeframe_features import DEFAULT_DB_PATH  # noqa: E402
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH, OBSERVATION_START_UTC  # noqa: E402


DEFAULT_AUDIT_PATH = BACKEND_DIR / "artifacts" / "signal_factory" / "v1" / "stage9_observation_readiness_audit.json"
DEFAULT_DOC_PATH = BACKEND_DIR / "docs" / "stage9_observation_readiness_audit.md"
ATR_REQUIRED_CANDLES = 15
TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 9 observation readiness audit.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_SIGNAL_FACTORY_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC_PATH)
    args = parser.parse_args()
    audit = build_audit(args.db_path, args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(render_doc(audit), encoding="utf-8")
    print(
        "stage9_observation_readiness_audit complete "
        f"observation_start_utc={audit['observation_window']['official_start_utc']} "
        f"post_rows={audit['observation_window']['log_rows_by_epoch'].get(OBSERVATION_EPOCH, 0)}"
    )


def build_audit(db_path: Path, artifact_dir: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stage8_audit = read_json(artifact_dir / "post_deploy_audit_v2.json")
    candidates_payload = read_json(artifact_dir / "candidates.json")
    candidates = candidates_payload.get("items") or []
    output = {
        "generated_at_utc": now_utc(),
        "stage8_fix_commit": "7e5162f",
        "observation_window": observation_window(conn),
        "applicable_missing_ceiling": applicable_missing_ceiling(stage8_audit),
        "atr_warmup_checkpoint": atr_warmup_checkpoint(conn, stage8_audit),
        "confidence_tier_distribution": confidence_distribution(conn, candidates),
        "guardrails": {
            "read_only": True,
            "no_threshold_change": True,
            "no_scoring_weight_change": True,
            "no_execution": True,
        },
    }
    conn.close()
    return output


def applicable_missing_ceiling(stage8_audit: dict[str, Any]) -> dict[str, Any]:
    raw = stage8_audit.get("missing_data", {}).get("field_counts", {})
    applicable_missing = stage8_audit.get("missing_data", {}).get("applicable_field_counts", {})
    applicable_total = stage8_audit.get("missing_data", {}).get("applicable_field_totals", {})
    telemetry = stage8_audit.get("ingestion_telemetry", {})
    rows = []
    for field, total in applicable_total.items():
        missing = int(applicable_missing.get(field, 0) or 0)
        total = int(total or 0)
        filled = max(0, total - missing)
        rows.append(
            {
                "field": field,
                "raw_missing": int(raw.get(field, 0) or 0),
                "applicable_missing": missing,
                "applicable_total": total,
                "applicable_filled": filled,
                "applicable_filled_pct": round((filled / total * 100), 2) if total else None,
                "breakpoint": (telemetry.get(field) or {}).get("breakpoint"),
            }
        )
    return {
        "fields": rows,
        "notes": [
            "one_hour_return_pct is applicable only to 15m rows.",
            "range_ratio_vs_atr requires 14-period ATR plus current candle; timeframe maturity controls its ceiling.",
        ],
    }


def atr_warmup_checkpoint(conn: sqlite3.Connection, stage8_audit: dict[str, Any]) -> dict[str, Any]:
    active_symbols = [row["symbol"] for row in conn.execute(
        "SELECT symbol FROM marketlab_active_universe WHERE is_active = 1 ORDER BY rank ASC"
    ).fetchall()]
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)
    readiness = {}
    for timeframe, minutes in TIMEFRAME_MINUTES.items():
        table = f"futures_klines_{timeframe}"
        counts = []
        ready_symbols = 0
        estimated_ready_times = []
        for symbol in active_symbols:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS count, MAX(close_time) AS latest_close
                FROM {table}
                WHERE symbol = ? AND aggregation_status = 'AGG_READY'
                """,
                (symbol,),
            ).fetchone()
            count = int(row["count"] or 0)
            counts.append(count)
            if count >= ATR_REQUIRED_CANDLES:
                ready_symbols += 1
            elif row["latest_close"]:
                latest = parse_dt(row["latest_close"])
                deficit = ATR_REQUIRED_CANDLES - count
                estimated_ready_times.append(latest + timedelta(minutes=minutes * max(0, deficit)))
        latest_any = conn.execute(
            f"SELECT MAX(close_time) AS latest_close FROM {table} WHERE aggregation_status = 'AGG_READY'"
        ).fetchone()["latest_close"]
        counts_sorted = sorted(counts)
        readiness[timeframe] = {
            "active_symbols": len(active_symbols),
            "symbols_with_atr_ready_count": ready_symbols,
            "symbols_below_15_candles": len(active_symbols) - ready_symbols,
            "min_ready_candles": counts_sorted[0] if counts_sorted else 0,
            "median_ready_candles": median(counts_sorted) if counts_sorted else 0,
            "latest_close_time": latest_any,
            "estimated_all_symbols_ready_utc": max(estimated_ready_times).isoformat() if estimated_ready_times else None,
            "estimated_all_symbols_ready_wib": to_wib(max(estimated_ready_times)) if estimated_ready_times else None,
            "checkpoint_recommendation_utc": checkpoint_time(current_time, minutes).isoformat(),
            "checkpoint_recommendation_wib": to_wib(checkpoint_time(current_time, minutes)),
        }
    internal = stage8_audit.get("internal_field_diagnosis", {})
    return {
        "atr_required_closed_candles": ATR_REQUIRED_CANDLES,
        "timeframes": readiness,
        "range_ratio_vs_atr_diagnosis": internal.get("range_ratio_vs_atr"),
    }


def checkpoint_time(current_time: datetime, minutes: int) -> datetime:
    if minutes >= 1440:
        return current_time + timedelta(days=2)
    if minutes >= 240:
        return current_time + timedelta(hours=12)
    if minutes >= 60:
        return current_time + timedelta(hours=3)
    return current_time + timedelta(hours=1)


def confidence_distribution(conn: sqlite3.Connection, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    by_epoch: dict[str, Counter] = defaultdict(Counter)
    signal_by_epoch: dict[str, Counter] = defaultdict(Counter)
    if has_table(conn, "signal_forward_return_logs"):
        has_epoch = has_column(conn, "signal_forward_return_logs", "observation_epoch")
        epoch_expr = "observation_epoch" if has_epoch else (
            "CASE WHEN datetime(source_artifact_generated_at) >= datetime('2026-07-03 06:15:20.000000') "
            "THEN 'STAGE8_OBSERVATION' ELSE 'PRE_STAGE8_FIX' END"
        )
        rows = conn.execute(
            f"""
            SELECT {epoch_expr} AS epoch, COALESCE(confidence_tier, 'UNKNOWN') AS confidence_tier,
                   COALESCE(candidate_status, 'UNKNOWN') AS candidate_status, COUNT(*) AS count
            FROM signal_forward_return_logs
            GROUP BY epoch, confidence_tier, candidate_status
            """
        ).fetchall()
        for row in rows:
            by_epoch[row["epoch"]][row["confidence_tier"]] += int(row["count"])
            if row["candidate_status"] == "SIGNAL_CANDIDATE":
                signal_by_epoch[row["epoch"]][row["confidence_tier"]] += int(row["count"])
    current = Counter()
    current_signal = Counter()
    for candidate in candidates:
        tier = candidate.get("evidence_confidence_tier") or (candidate.get("evidence") or {}).get("evidence_confidence_tier") or "UNKNOWN"
        current[tier] += 1
        if candidate.get("candidate_status") == "SIGNAL_CANDIDATE":
            current_signal[tier] += 1
    return {
        "all_logged_candidates_by_epoch": {key: dict(counter) for key, counter in sorted(by_epoch.items())},
        "signal_candidates_by_epoch": {key: dict(counter) for key, counter in sorted(signal_by_epoch.items())},
        "current_artifact_all_candidates": dict(current),
        "current_artifact_signal_candidates": dict(current_signal),
        "interpretation": "Post-fix confidence should vary across EVIDENCE_UNAVAILABLE, CONFLICT, LOW_CONF, MEDIUM_CONF, and HIGH_CONF when evidence sources are populated.",
    }


def observation_window(conn: sqlite3.Connection) -> dict[str, Any]:
    start = OBSERVATION_START_UTC
    rows_by_epoch = {}
    if has_table(conn, "signal_forward_return_logs"):
        has_epoch = has_column(conn, "signal_forward_return_logs", "observation_epoch")
        if has_epoch:
            rows = conn.execute(
                "SELECT COALESCE(observation_epoch, 'UNMARKED') AS epoch, COUNT(*) AS count FROM signal_forward_return_logs GROUP BY epoch"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT CASE WHEN datetime(source_artifact_generated_at) >= datetime(?) THEN 'STAGE8_OBSERVATION' ELSE 'PRE_STAGE8_FIX' END AS epoch,
                       COUNT(*) AS count
                FROM signal_forward_return_logs
                GROUP BY epoch
                """,
                (start.strftime("%Y-%m-%d %H:%M:%S.%f"),),
            ).fetchall()
        rows_by_epoch = {row["epoch"]: int(row["count"]) for row in rows}
    return {
        "official_start_utc": start.isoformat() + "Z",
        "official_start_wib": to_wib(start),
        "stage8_fix_commit": "7e5162f",
        "observation_epoch_name": OBSERVATION_EPOCH,
        "log_rows_by_epoch": rows_by_epoch,
        "rule": "Rows before official_start_utc are retained but excluded from calibration observation windows.",
    }


def render_doc(audit: dict[str, Any]) -> str:
    lines = [
        "# Stage 9 Observation Readiness Audit",
        "",
        "Read-only audit. No threshold, score weight, execution, or strategy behavior is changed.",
        "",
        f"- generated_at_utc: `{audit['generated_at_utc']}`",
        f"- official_observation_start_utc: `{audit['observation_window']['official_start_utc']}`",
        f"- official_observation_start_wib: `{audit['observation_window']['official_start_wib']}`",
        f"- observation_epoch: `{audit['observation_window']['observation_epoch_name']}`",
        f"- log_rows_by_epoch: `{audit['observation_window']['log_rows_by_epoch']}`",
        "",
        "## 9a. Applicable Missing Ceiling",
        "",
        "| field | raw_missing | applicable_missing | applicable_total | filled_pct | breakpoint |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in audit["applicable_missing_ceiling"]["fields"]:
        lines.append(
            f"| {row['field']} | {row['raw_missing']} | {row['applicable_missing']} | "
            f"{row['applicable_total']} | {row['applicable_filled_pct']} | {row['breakpoint']} |"
        )
    lines.extend(["", "## 9b. ATR Warmup Checkpoint", "", "| timeframe | ATR ready symbols | below 15 candles | latest close | estimated all ready WIB | checkpoint WIB |", "|---|---:|---:|---|---|---|"])
    for timeframe, row in audit["atr_warmup_checkpoint"]["timeframes"].items():
        lines.append(
            f"| {timeframe} | {row['symbols_with_atr_ready_count']}/{row['active_symbols']} | "
            f"{row['symbols_below_15_candles']} | {row['latest_close_time']} | "
            f"{row['estimated_all_symbols_ready_wib']} | {row['checkpoint_recommendation_wib']} |"
        )
    lines.extend(
        [
            "",
            "## 9c. Confidence Tier Distribution",
            "",
            f"- logged_all_by_epoch: `{audit['confidence_tier_distribution']['all_logged_candidates_by_epoch']}`",
            f"- logged_signal_by_epoch: `{audit['confidence_tier_distribution']['signal_candidates_by_epoch']}`",
            f"- current_artifact_all: `{audit['confidence_tier_distribution']['current_artifact_all_candidates']}`",
            f"- current_artifact_signals: `{audit['confidence_tier_distribution']['current_artifact_signal_candidates']}`",
            "",
            "## 9d. Official Observation Window",
            "",
            f"- start_utc: `{audit['observation_window']['official_start_utc']}`",
            f"- start_wib: `{audit['observation_window']['official_start_wib']}`",
            f"- marker: `{audit['observation_window']['observation_epoch_name']}`",
            "- Calibration observation must use rows marked `STAGE8_OBSERVATION`.",
            "",
            "## Verdict",
            "",
            "- Stage 9 audit completed.",
            "- Observation clock starts after Stage 8 evidence mapping fix, not from the first logging row.",
        ]
    )
    return "\n".join(lines) + "\n"


def has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not has_table(conn, table):
        return False
    return column in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def to_wib(value: datetime) -> str:
    wib = value.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=7)))
    return wib.strftime("%Y-%m-%d %H:%M:%S WIB")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
