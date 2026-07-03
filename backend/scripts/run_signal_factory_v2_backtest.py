from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.multitimeframe_features import DEFAULT_DB_PATH  # noqa: E402
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH  # noqa: E402
from app.services.utils import json_safe  # noqa: E402


DEFAULT_OUTPUT_DIR = BACKEND_DIR / "artifacts" / "signal_factory" / "v2_backtest"
DEFAULT_DOC_PATH = BACKEND_DIR / "docs" / "signal_factory_v2_backtest_report.md"
HORIZONS = {"15m": 1, "1h": 4, "4h": 16, "24h": 96}


@dataclass(frozen=True)
class SignalRow:
    signal_id: str
    symbol: str
    timeframe: str
    signal_timestamp: datetime
    direction: str
    stage: str
    core_score: Decimal | None
    evidence_score: Decimal | None
    evidence_data_completeness: int | None
    confidence_tier: str | None
    execution_flag: str | None
    entry: Decimal
    stop: Decimal
    target: Decimal
    observation_epoch: str | None
    source_artifact_generated_at: datetime | None


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    close_time: datetime
    high: Decimal
    low: Decimal
    close: Decimal


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only Signal Factory V2 backtest from forward-return logs.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--doc-path", type=Path, default=DEFAULT_DOC_PATH)
    parser.add_argument("--epoch", default=OBSERVATION_EPOCH)
    parser.add_argument("--include-watch-only", action="store_true")
    args = parser.parse_args()
    report = run_backtest(
        db_path=args.db_path,
        epoch=args.epoch,
        include_watch_only=args.include_watch_only,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(json_safe(report), indent=2), encoding="utf-8")
    (args.output_dir / "events.json").write_text(json.dumps(json_safe(report["events"]), indent=2), encoding="utf-8")
    args.doc_path.parent.mkdir(parents=True, exist_ok=True)
    args.doc_path.write_text(render_markdown(report), encoding="utf-8")
    print(
        "signal_factory_v2_backtest complete "
        f"epoch={report['metadata']['epoch']} "
        f"signals={report['metadata']['signals_loaded']} "
        f"events={len(report['events'])}"
    )


def run_backtest(db_path: Path, epoch: str, include_watch_only: bool = False) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        signals = load_signals(conn, epoch, include_watch_only)
        candles = load_candles(conn)
    finally:
        conn.close()
    events = []
    skipped = Counter()
    for signal in signals:
        symbol_candles = candles.get(signal.symbol, [])
        if not symbol_candles:
            skipped["NO_FUTURES_CANDLES"] += 1
            continue
        event = {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "signal_time_utc": signal.signal_timestamp,
            "signal_time_wib": to_wib(signal.signal_timestamp),
            "stage": signal.stage,
            "direction": signal.direction,
            "confidence_tier": signal.confidence_tier,
            "core_score": signal.core_score,
            "evidence_score": signal.evidence_score,
            "evidence_data_completeness": signal.evidence_data_completeness,
            "execution_flag": signal.execution_flag,
            "entry_market": "futures",
            "entry_price_source": "futures_klines_15m.close",
            "entry": signal.entry,
            "stop": signal.stop,
            "target": signal.target,
            "risk": abs(signal.entry - signal.stop),
            "not_live_signal": True,
            "not_execution_instruction": True,
            "horizons": {},
        }
        if event["risk"] <= 0:
            skipped["INVALID_RISK"] += 1
            continue
        for horizon, count in HORIZONS.items():
            window = future_window(symbol_candles, signal.signal_timestamp, count)
            event["horizons"][horizon] = evaluate_window(signal, window)
        events.append(event)
    return {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "db_path": str(db_path),
            "epoch": epoch,
            "include_watch_only": include_watch_only,
            "signals_loaded": len(signals),
            "events_evaluated": len(events),
            "skipped": dict(skipped),
            "entry_market": "futures",
            "spot_usage": "evidence/filter only",
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
        },
        "summary": summarize(events),
        "events": events,
    }


def load_signals(conn: sqlite3.Connection, epoch: str, include_watch_only: bool) -> list[SignalRow]:
    execution_filter = "" if include_watch_only else "AND COALESCE(execution_flag, '') != 'WATCH_ONLY'"
    rows = conn.execute(
        f"""
        SELECT signal_id, symbol, timeframe, signal_timestamp, direction, stage, core_score, evidence_score,
               evidence_data_completeness, confidence_tier, execution_flag, price_at_signal, sl_ref, tp_ref,
               observation_epoch, source_artifact_generated_at
        FROM signal_forward_return_logs
        WHERE candidate_status = 'SIGNAL_CANDIDATE'
          AND observation_epoch = ?
          AND price_at_signal IS NOT NULL
          AND sl_ref IS NOT NULL
          AND tp_ref IS NOT NULL
          {execution_filter}
        ORDER BY signal_timestamp ASC, symbol ASC
        """,
        (epoch,),
    ).fetchall()
    output = []
    for row in rows:
        output.append(
            SignalRow(
                signal_id=row["signal_id"],
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                signal_timestamp=parse_dt(row["signal_timestamp"]),
                direction=row["direction"],
                stage=row["stage"],
                core_score=dec_or_none(row["core_score"]),
                evidence_score=dec_or_none(row["evidence_score"]),
                evidence_data_completeness=row["evidence_data_completeness"],
                confidence_tier=row["confidence_tier"],
                execution_flag=row["execution_flag"],
                entry=Decimal(str(row["price_at_signal"])),
                stop=Decimal(str(row["sl_ref"])),
                target=Decimal(str(row["tp_ref"])),
                observation_epoch=row["observation_epoch"],
                source_artifact_generated_at=parse_dt_or_none(row["source_artifact_generated_at"]),
            )
        )
    return output


def load_candles(conn: sqlite3.Connection) -> dict[str, list[Candle]]:
    rows = conn.execute(
        """
        SELECT symbol, open_time, close_time, high, low, close
        FROM futures_klines_15m
        WHERE aggregation_status = 'AGG_READY'
        ORDER BY symbol, open_time
        """
    ).fetchall()
    candles: dict[str, list[Candle]] = defaultdict(list)
    for row in rows:
        candles[row["symbol"]].append(
            Candle(
                open_time=parse_dt(row["open_time"]),
                close_time=parse_dt(row["close_time"]),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
            )
        )
    return dict(candles)


def future_window(candles: list[Candle], signal_time: datetime, expected_count: int) -> list[Candle] | None:
    rows = [candle for candle in candles if candle.open_time >= signal_time]
    window = rows[:expected_count]
    if len(window) != expected_count:
        return None
    current = signal_time
    for candle in window:
        if candle.open_time != current:
            return None
        current = candle.close_time
    return window


def evaluate_window(signal: SignalRow, window: list[Candle] | None) -> dict[str, Any]:
    if not window:
        return {"status": "WAITING_DATA", "outcome": "WAITING_DATA", "realized_r": None}
    risk = abs(signal.entry - signal.stop)
    mfe = Decimal("0")
    mae = Decimal("0")
    for candle in window:
        if signal.direction == "LONG":
            tp_hit = candle.high >= signal.target
            sl_hit = candle.low <= signal.stop
            mfe = max(mfe, (candle.high - signal.entry) / risk)
            mae = min(mae, (candle.low - signal.entry) / risk)
        else:
            tp_hit = candle.low <= signal.target
            sl_hit = candle.high >= signal.stop
            mfe = max(mfe, (signal.entry - candle.low) / risk)
            mae = min(mae, (signal.entry - candle.high) / risk)
        if tp_hit and sl_hit:
            return {
                "status": "READY",
                "outcome": "BOTH_SAME_CANDLE",
                "realized_r": None,
                "mfe_r": mfe,
                "mae_r": mae,
                "result_time_utc": candle.close_time,
                "result_time_wib": to_wib(candle.close_time),
            }
        if tp_hit:
            return {
                "status": "READY",
                "outcome": "TP_FIRST",
                "realized_r": abs(signal.target - signal.entry) / risk,
                "mfe_r": mfe,
                "mae_r": mae,
                "result_time_utc": candle.close_time,
                "result_time_wib": to_wib(candle.close_time),
            }
        if sl_hit:
            return {
                "status": "READY",
                "outcome": "SL_FIRST",
                "realized_r": Decimal("-1"),
                "mfe_r": mfe,
                "mae_r": mae,
                "result_time_utc": candle.close_time,
                "result_time_wib": to_wib(candle.close_time),
            }
    close = window[-1].close
    if signal.direction == "LONG":
        realized = (close - signal.entry) / risk
    else:
        realized = (signal.entry - close) / risk
    return {
        "status": "READY",
        "outcome": "NEITHER_CLOSE_AT_HORIZON",
        "realized_r": realized,
        "mfe_r": mfe,
        "mae_r": mae,
        "result_time_utc": window[-1].close_time,
        "result_time_wib": to_wib(window[-1].close_time),
    }


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_horizon = {}
    for horizon in HORIZONS:
        rows = [event["horizons"][horizon] for event in events]
        ready = [row for row in rows if row["status"] == "READY"]
        r_values = [row["realized_r"] for row in ready if row.get("realized_r") is not None]
        counts = Counter(row["outcome"] for row in rows)
        by_horizon[horizon] = {
            "events": len(rows),
            "ready": len(ready),
            "waiting": counts.get("WAITING_DATA", 0),
            "outcomes": dict(counts),
            "avg_r": sum(r_values) / Decimal(len(r_values)) if r_values else None,
            "median_r": Decimal(str(median(r_values))) if r_values else None,
            "best_r": max(r_values) if r_values else None,
            "worst_r": min(r_values) if r_values else None,
        }
    by_stage = Counter(event["stage"] for event in events)
    by_confidence = Counter(event["confidence_tier"] for event in events)
    return {
        "total_events": len(events),
        "by_stage": dict(by_stage),
        "by_confidence": dict(by_confidence),
        "by_horizon": by_horizon,
    }


def render_markdown(report: dict[str, Any]) -> str:
    meta = report["metadata"]
    summary = report["summary"]
    lines = [
        "# Signal Factory V2 Backtest Report",
        "",
        "Read-only backtest from `signal_forward_return_logs`. This is not a live signal, not an order instruction, and not execution.",
        "",
        f"- generated_at_utc: `{meta['generated_at_utc']}`",
        f"- epoch: `{meta['epoch']}`",
        f"- signals_loaded: `{meta['signals_loaded']}`",
        f"- events_evaluated: `{meta['events_evaluated']}`",
        f"- include_watch_only: `{meta['include_watch_only']}`",
        f"- entry_market: `{meta['entry_market']}`",
        f"- spot_usage: `{meta['spot_usage']}`",
        "",
        "## Summary By Horizon",
        "",
        "| horizon | events | ready | waiting | TP | SL | BOTH | neither/close | avg R | median R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for horizon, row in summary["by_horizon"].items():
        outcomes = row["outcomes"]
        lines.append(
            f"| {horizon} | {row['events']} | {row['ready']} | {row['waiting']} | "
            f"{outcomes.get('TP_FIRST', 0)} | {outcomes.get('SL_FIRST', 0)} | "
            f"{outcomes.get('BOTH_SAME_CANDLE', 0)} | {outcomes.get('NEITHER_CLOSE_AT_HORIZON', 0)} | "
            f"{fmt(row['avg_r'])} | {fmt(row['median_r'])} |"
        )
    lines.extend(
        [
            "",
            "## Events",
            "",
            "| symbol | time WIB | stage | direction | confidence | entry | stop | target | 4h outcome | 4h R | 24h outcome | 24h R |",
            "|---|---|---|---|---|---:|---:|---:|---|---:|---|---:|",
        ]
    )
    for event in report["events"]:
        h4 = event["horizons"]["4h"]
        h24 = event["horizons"]["24h"]
        lines.append(
            f"| {event['symbol']} | {event['signal_time_wib']} | {event['stage']} | {event['direction']} | "
            f"{event['confidence_tier']} | {event['entry']} | {event['stop']} | {event['target']} | "
            f"{h4['outcome']} | {fmt(h4.get('realized_r'))} | {h24['outcome']} | {fmt(h24.get('realized_r'))} |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Uses futures price for entry and outcome.",
            "- Spot is used only as evidence/filter through Signal Factory.",
            "- No live signal, order, execution, leverage, or position sizing.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def parse_dt_or_none(value: Any) -> datetime | None:
    if not value:
        return None
    return parse_dt(value)


def dec_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def to_wib(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S WIB")


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{Decimal(str(value)):.4f}"


if __name__ == "__main__":
    main()
