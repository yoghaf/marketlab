from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "marketlab.db"
DEFAULT_PHASE6_DIR = REPO_ROOT / "backend" / "artifacts" / "phase6"
DEFAULT_SIGNAL_FACTORY_DIR = REPO_ROOT / "backend" / "artifacts" / "signal_factory" / "v1"
DEFAULT_STRATEGY_ARENA_DIR = REPO_ROOT / "backend" / "artifacts" / "strategy_arena" / "v1"
DEFAULT_PHASE7_DIR = REPO_ROOT / "backend" / "artifacts" / "phase7"

HORIZON_BARS = {"15m": 1, "1h": 4, "4h": 16, "24h": 96}
TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}
PHASE7_EDGE_THRESHOLD_R = Decimal("0.10")
LAB_SHADOW_EDGE_THRESHOLD_R = Decimal("0.05")
PHASE7_SCORE_THRESHOLD = 7
ARENA_VERDICT_OK = {"MONITOR_MORE", "PROMISING_FOR_FORWARD_TEST"}
LAB_REJECT_VERDICTS = {"REJECT"}
ACTIVE_STATUSES = {"WAITING_OUTCOME", "UNKNOWN_FORWARD_DATA"}
COMPLETED_STATUSES = {"TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE", "EXPIRED", "INVALIDATED", "CANNOT_EVALUATE"}
APPROVED_SHADOW = "APPROVED_SHADOW"
LAB_SHADOW = "LAB_SHADOW"


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class Phase7ForwardTestService:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        phase6_dir: Path = DEFAULT_PHASE6_DIR,
        signal_factory_dir: Path = DEFAULT_SIGNAL_FACTORY_DIR,
        strategy_arena_dir: Path = DEFAULT_STRATEGY_ARENA_DIR,
        artifact_dir: Path = DEFAULT_PHASE7_DIR,
    ) -> None:
        self.db_path = db_path
        self.phase6_dir = phase6_dir
        self.signal_factory_dir = signal_factory_dir
        self.strategy_arena_dir = strategy_arena_dir
        self.artifact_dir = artifact_dir

    def run(self) -> dict[str, Any]:
        generated_at = iso_utc(utcnow())
        try:
            decision = self.load_phase6_decision()
            edge_rows = self.load_phase6_edge_rows()
            signal_candidates = self.load_signal_factory_candidates()
            self.load_strategy_arena()
        except FileNotFoundError as exc:
            payload = self._missing_artifact_payload(generated_at, str(exc))
            self.write_artifacts(payload)
            return payload

        existing_events = self.load_existing_events()
        approved = self.get_approved_candidates(decision, edge_rows)
        lab_candidates = self.get_lab_shadow_candidates(edge_rows, signal_candidates, approved)
        events_by_id = {event["event_id"]: event for event in existing_events}
        create_errors = []
        created_count = 0
        for candidate in approved:
            event = self.build_shadow_event(candidate, APPROVED_SHADOW)
            event_id = event["event_id"]
            if event_id in events_by_id and events_by_id[event_id].get("status") != "CANNOT_CREATE_EVENT_MISSING_REFERENCE":
                continue
            events_by_id[event_id] = event
            created_count += 1
            if event["status"] == "CANNOT_CREATE_EVENT_MISSING_REFERENCE":
                create_errors.append({"event_id": event_id, "symbol": event["symbol"], "reason": event.get("cannot_create_reason")})
        for candidate in lab_candidates:
            event = self.build_shadow_event(candidate, LAB_SHADOW)
            event_id = event["event_id"]
            if event_id in events_by_id and events_by_id[event_id].get("status") != "CANNOT_CREATE_EVENT_MISSING_REFERENCE":
                continue
            events_by_id[event_id] = event
            created_count += 1
            if event["status"] == "CANNOT_CREATE_EVENT_MISSING_REFERENCE":
                create_errors.append({"event_id": event_id, "symbol": event["symbol"], "reason": event.get("cannot_create_reason")})

        events = sorted(events_by_id.values(), key=lambda item: (item.get("observation_timestamp") or "", item.get("symbol") or ""))
        results = self.update_forward_outcomes(events)
        for event in events:
            result = next((item for item in results if item["event_id"] == event["event_id"]), None)
            if result and result["result_status"] not in {"UNKNOWN_FORWARD_DATA", "CANNOT_EVALUATE"}:
                event["status"] = result["result_status"]
            elif result and result["result_status"] == "UNKNOWN_FORWARD_DATA" and event["status"] in ACTIVE_STATUSES:
                event["status"] = "WAITING_OUTCOME"

        status = self.build_status(generated_at, approved, lab_candidates, events, results, len(create_errors))
        status["created_event_count"] = created_count
        summary = self.build_summary(generated_at, events, results)
        payload = {
            "status": status,
            "events": {
                "generated_at": generated_at,
                "generated_at_utc": generated_at,
                "display_timezone_hint": "browser_local_or_Asia/Jakarta",
                "events": events,
            },
            "results": {
                "generated_at": generated_at,
                "generated_at_utc": generated_at,
                "display_timezone_hint": "browser_local_or_Asia/Jakarta",
                "results": results,
            },
            "summary": summary,
        }
        self.write_artifacts(payload)
        return payload

    def load_phase6_decision(self) -> dict[str, Any]:
        return read_json(self.phase6_dir / "phase7_candidate_decision.json")

    def load_phase6_edge_rows(self) -> list[dict[str, Any]]:
        return read_json(self.phase6_dir / "setup_edge_audit.json").get("rows", [])

    def load_signal_factory_candidates(self) -> list[dict[str, Any]]:
        return read_json(self.signal_factory_dir / "candidates.json").get("items", [])

    def load_strategy_arena(self) -> dict[str, Any]:
        return {
            "results": read_json(self.strategy_arena_dir / "results.json"),
            "leaderboard": read_json(self.strategy_arena_dir / "leaderboard.json"),
        }

    def get_approved_candidates(self, decision: dict[str, Any], edge_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        edge_index = {(row.get("symbol"), row.get("timeframe"), row.get("setup_type")): row for row in edge_rows}
        approved = []
        for row in decision.get("approved_candidates") or []:
            edge = edge_index.get((row.get("symbol"), row.get("timeframe"), row.get("setup_type"))) or {}
            merged = {**edge, **row}
            if not is_phase7_approved(merged):
                continue
            merged["lane"] = APPROVED_SHADOW
            merged["shadow_type"] = "STRICT_APPROVED"
            approved.append(merged)
        return approved

    def get_lab_shadow_candidates(
        self,
        edge_rows: list[dict[str, Any]],
        signal_candidates: list[dict[str, Any]],
        approved: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        signal_index = {
            (row.get("symbol"), row.get("timeframe"), row.get("setup_type")): row
            for row in signal_candidates
        }
        approved_keys = {
            (row.get("symbol"), row.get("timeframe"), row.get("setup_type"), row.get("window_end"))
            for row in approved
        }
        lab = []
        for row in edge_rows:
            merged = {**signal_index.get((row.get("symbol"), row.get("timeframe"), row.get("setup_type")), {}), **row}
            key = (merged.get("symbol"), merged.get("timeframe"), merged.get("setup_type"), merged.get("window_end"))
            if key in approved_keys:
                continue
            if not is_lab_shadow_candidate(merged):
                continue
            merged["lane"] = LAB_SHADOW
            merged["shadow_type"] = "LAB_NEAR_MISS"
            lab.append(merged)
        return lab

    def build_shadow_event(self, candidate: dict[str, Any], lane: str) -> dict[str, Any]:
        observation = parse_dt(candidate.get("window_end") or candidate.get("candidate_timestamp") or candidate.get("observation_timestamp"))
        direction = direction_side(candidate)
        event_id = deterministic_event_id(candidate, observation, direction, lane)
        created_at = iso_utc(utcnow())
        base = {
            "event_id": event_id,
            "symbol": candidate.get("symbol"),
            "timeframe": candidate.get("timeframe"),
            "setup": candidate.get("mapped_setup_family") or candidate.get("setup_type"),
            "direction": direction,
            "lane": lane,
            "shadow_type": "STRICT_APPROVED" if lane == APPROVED_SHADOW else "LAB_NEAR_MISS",
            "confidence": candidate.get("confidence"),
            "candidate_timestamp": iso_utc(observation),
            "observation_timestamp": iso_utc(observation),
            "observation_timestamp_utc": iso_utc(observation),
            "source_candidate_id": source_candidate_id(candidate, observation),
            "phase6_score": candidate.get("total_score"),
            "edge_vs_baseline": candidate.get("edge_vs_baseline"),
            "arena_verdict": candidate.get("arena_verdict") or (candidate.get("arena_match") or {}).get("verdict"),
            "atr_reference_timeframe": candidate.get("atr_reference_timeframe"),
            "created_at": created_at,
            "event_created_at_utc": created_at,
            "is_live_signal": False,
            "is_execution": False,
            "disclaimer": "READ_ONLY_SHADOW_FORWARD_TEST" if lane == APPROVED_SHADOW else "LAB_ONLY_READ_ONLY_SHADOW_FORWARD_TEST",
        }
        plan = self.build_shadow_trade_plan(candidate, observation, direction)
        if plan["status"] != "OK":
            return {
                **base,
                "status": "CANNOT_CREATE_EVENT_MISSING_REFERENCE",
                "cannot_create_reason": plan["reason"],
                "trade_plan": plan,
            }
        return {
            **base,
            **plan["trade_plan"],
            "status": "WAITING_OUTCOME",
            "trade_plan": plan["trade_plan"],
        }

    def build_shadow_trade_plan(self, candidate: dict[str, Any], observation: datetime, direction: str) -> dict[str, Any]:
        arena = candidate.get("arena_match") or {}
        horizon = candidate.get("recommended_arena_horizon") or arena.get("horizon") or "15m"
        atr_mult = decimal_or_none(candidate.get("recommended_atr_mult") or arena.get("atr_mult"))
        rr = decimal_or_none(candidate.get("recommended_rr") or arena.get("rr"))
        atr_timeframe = candidate.get("atr_reference_timeframe") or "1h"
        if atr_mult is None or rr is None:
            return {"status": "MISSING_REFERENCE", "reason": "missing Strategy Arena atr_mult or rr"}
        entry_candle = self._candle_at(candidate.get("symbol"), candidate.get("timeframe"), observation)
        if entry_candle is None:
            return {"status": "MISSING_REFERENCE", "reason": "missing entry reference candle close"}
        atr = self._atr(candidate.get("symbol"), atr_timeframe, observation)
        if atr is None or atr <= 0:
            return {"status": "MISSING_REFERENCE", "reason": "missing ATR reference value"}
        entry = entry_candle.close
        risk = atr * atr_mult
        if direction == "LONG":
            stop = entry - risk
            target = entry + risk * rr
        elif direction == "SHORT":
            stop = entry + risk
            target = entry - risk * rr
        else:
            return {"status": "MISSING_REFERENCE", "reason": "unsupported direction for shadow plan"}
        bars = HORIZON_BARS.get(horizon, 1)
        minutes = bars * 15
        return {
            "status": "OK",
            "trade_plan": {
                "entry_reference_type": "CANDIDATE_15M_CLOSE",
                "entry_reference_price": float(entry),
                "entry_reference_time": iso_utc(entry_candle.close_time),
                "entry_reference_time_utc": iso_utc(entry_candle.close_time),
                "atr_reference_timeframe": atr_timeframe,
                "atr_reference_value": float(atr),
                "atr_mult": float(atr_mult),
                "rr_target": float(rr),
                "risk_reference_value": float(risk),
                "stop_reference_price": float(stop),
                "take_profit_reference_price": float(target),
                "max_horizon_bars": bars,
                "max_horizon_minutes": minutes,
                "expiry_time": iso_utc(observation + timedelta(minutes=minutes)),
                "expiry_time_utc": iso_utc(observation + timedelta(minutes=minutes)),
                "invalidation_rule": "Forward-test expires at configured Strategy Arena horizon if TP/SL is not hit.",
                "shadow_plan_type": "SHADOW_SIMULATION_LEVELS_NOT_LIVE_ORDER",
            },
        }

    def load_existing_events(self) -> list[dict[str, Any]]:
        path = self.artifact_dir / "forward_test_events.json"
        if not path.exists():
            return []
        return read_json(path).get("events", [])

    def update_forward_outcomes(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for event in events:
            if event.get("status") == "CANNOT_CREATE_EVENT_MISSING_REFERENCE":
                results.append(cannot_evaluate_result(event, event.get("cannot_create_reason") or "missing reference"))
                continue
            results.append(self.evaluate_event(event))
        return results

    def evaluate_event(self, event: dict[str, Any]) -> dict[str, Any]:
        entry = Decimal(str(event.get("entry_reference_price")))
        stop = Decimal(str(event.get("stop_reference_price")))
        target = Decimal(str(event.get("take_profit_reference_price")))
        risk = Decimal(str(event.get("risk_reference_value")))
        observation = parse_dt(event.get("observation_timestamp"))
        bars = int(event.get("max_horizon_bars") or 1)
        direction = event.get("direction")
        candles = self._future_15m_candles(event.get("symbol"), observation, bars)
        if not candles:
            return unknown_result(event, "no forward candle available")

        max_favorable = Decimal("0")
        max_adverse = Decimal("0")
        for idx, candle in enumerate(candles, start=1):
            if direction == "LONG":
                tp_hit = candle.high >= target
                sl_hit = candle.low <= stop
                favorable = (candle.high - entry) / risk
                adverse = (candle.low - entry) / risk
            else:
                tp_hit = candle.low <= target
                sl_hit = candle.high >= stop
                favorable = (entry - candle.low) / risk
                adverse = (entry - candle.high) / risk
            max_favorable = max(max_favorable, favorable)
            max_adverse = min(max_adverse, adverse)
            if tp_hit and sl_hit:
                return completed_result(event, "BOTH_HIT_SAME_CANDLE", candle.close_time, idx, None, max_favorable, max_adverse, True)
            if tp_hit:
                return completed_result(event, "TP_HIT", candle.close_time, idx, Decimal(str(event.get("rr_target"))), max_favorable, max_adverse, False)
            if sl_hit:
                return completed_result(event, "SL_HIT", candle.close_time, idx, Decimal("-1"), max_favorable, max_adverse, False)

        if len(candles) < bars:
            return {
                **unknown_result(event, "not enough forward candles yet"),
                "max_favorable_excursion_R": float(max_favorable),
                "max_adverse_excursion_R": float(max_adverse),
            }
        last = candles[-1]
        close_r = (last.close - entry) / risk if direction == "LONG" else (entry - last.close) / risk
        return completed_result(event, "EXPIRED", last.close_time, len(candles), close_r, max_favorable, max_adverse, False)

    def build_status(
        self,
        generated_at: str,
        approved: list[dict[str, Any]],
        lab_candidates: list[dict[str, Any]],
        events: list[dict[str, Any]],
        results: list[dict[str, Any]],
        error_count: int,
    ) -> dict[str, Any]:
        active = [event for event in events if event.get("status") in ACTIVE_STATUSES]
        completed = [event for event in events if event.get("status") in COMPLETED_STATUSES]
        approved_events = [event for event in events if event.get("lane") == APPROVED_SHADOW]
        lab_events = [event for event in events if event.get("lane") == LAB_SHADOW]
        if error_count:
            mode = "ERROR"
            verdict = "PHASE7_DUAL_LANE_ERROR"
            reason = "Some Phase 7 shadow events could not be created."
            next_action = "Inspect event create errors and rerun after references are available."
        elif approved_events:
            mode = "ACTIVE_APPROVED_SHADOW"
            verdict = "PHASE7_DUAL_LANE_ACTIVE_APPROVED_SHADOW"
            reason = "Strict approved shadow events are available for forward-test tracking."
            next_action = "Rerun Phase 7 forward test after more closed candles."
        elif lab_events:
            mode = "ACTIVE_LAB_SHADOW"
            verdict = "PHASE7_DUAL_LANE_ACTIVE_LAB_SHADOW"
            reason = "No approved shadow events yet; near-miss LAB_SHADOW candidates are being tracked for forward-test learning."
            next_action = "Continue collecting forward-test outcomes; LAB_SHADOW is not a live signal."
        else:
            mode = "WAITING_FOR_CANDIDATE"
            verdict = "PHASE7_DUAL_LANE_READY_WAITING"
            reason = "No Phase 6 approved candidate and no LAB_SHADOW near-miss candidate yet."
            next_action = "Rerun after Signal Factory and Phase 6 produce eligible candidates."
        return {
            "generated_at": generated_at,
            "generated_at_utc": generated_at,
            "last_run_at_utc": generated_at,
            "display_timezone_hint": "browser_local_or_Asia/Jakarta",
            "phase": "PHASE_7_SHADOW_FORWARD_TEST",
            "mode": mode,
            "verdict": verdict,
            "approved_candidate_count": len(approved),
            "approved_shadow_event_count": len(approved_events),
            "lab_shadow_candidate_count": len(lab_candidates),
            "lab_shadow_event_count": len(lab_events),
            "active_event_count": len(active),
            "completed_event_count": len(completed),
            "waiting_event_count": len(active),
            "error_count": error_count,
            "reason": reason,
            "is_live_signal": False,
            "is_execution_enabled": False,
            "next_action": next_action,
        }

    def build_summary(self, generated_at: str, events: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
        total = lane_summary(events, results, None)
        return {
            "generated_at": generated_at,
            "generated_at_utc": generated_at,
            "last_run_at_utc": generated_at,
            "display_timezone_hint": "browser_local_or_Asia/Jakarta",
            **total,
            "approved_shadow_summary": lane_summary(events, results, APPROVED_SHADOW),
            "lab_shadow_summary": lane_summary(events, results, LAB_SHADOW),
            "verdict": "WAITING_FOR_DATA" if not events else "FORWARD_TEST_TRACKING",
            "is_live_signal": False,
            "is_execution_enabled": False,
        }

    def write_artifacts(self, payload: dict[str, Any]) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        (self.artifact_dir / "forward_test_status.json").write_text(json.dumps(json_safe(payload["status"]), indent=2), encoding="utf-8")
        (self.artifact_dir / "forward_test_events.json").write_text(json.dumps(json_safe(payload["events"]), indent=2), encoding="utf-8")
        (self.artifact_dir / "forward_test_results.json").write_text(json.dumps(json_safe(payload["results"]), indent=2), encoding="utf-8")
        (self.artifact_dir / "forward_test_summary.json").write_text(json.dumps(json_safe(payload["summary"]), indent=2), encoding="utf-8")

    def _missing_artifact_payload(self, generated_at: str, reason: str) -> dict[str, Any]:
        status = {
            "generated_at": generated_at,
            "generated_at_utc": generated_at,
            "last_run_at_utc": generated_at,
            "display_timezone_hint": "browser_local_or_Asia/Jakarta",
            "phase": "PHASE_7_SHADOW_FORWARD_TEST",
            "mode": "ERROR",
            "verdict": "PHASE7_DUAL_LANE_ERROR",
            "approved_candidate_count": 0,
            "approved_shadow_event_count": 0,
            "lab_shadow_candidate_count": 0,
            "lab_shadow_event_count": 0,
            "active_event_count": 0,
            "completed_event_count": 0,
            "waiting_event_count": 0,
            "error_count": 1,
            "reason": reason,
            "is_live_signal": False,
            "is_execution_enabled": False,
            "next_action": "Refresh required Phase 6 and Strategy Arena artifacts.",
        }
        return {
            "status": status,
            "events": {"generated_at": generated_at, "generated_at_utc": generated_at, "events": []},
            "results": {"generated_at": generated_at, "generated_at_utc": generated_at, "results": []},
            "summary": self.build_summary(generated_at, [], []),
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _candle_at(self, symbol: str, timeframe: str, close_time: datetime) -> Candle | None:
        table = f"futures_klines_{timeframe}"
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"""
                SELECT open_time, close_time, open, high, low, close
                FROM {table}
                WHERE symbol = ? AND close_time = ? AND aggregation_status = 'AGG_READY'
                LIMIT 1
                """,
                (symbol, db_time(close_time)),
            ).fetchone()
        return candle_from_row(row) if row else None

    def _candles_until(self, symbol: str, timeframe: str, close_time: datetime) -> list[Candle]:
        table = f"futures_klines_{timeframe}"
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT open_time, close_time, open, high, low, close
                FROM {table}
                WHERE symbol = ? AND close_time <= ? AND aggregation_status = 'AGG_READY'
                ORDER BY close_time ASC
                """,
                (symbol, db_time(close_time)),
            ).fetchall()
        return [candle_from_row(row) for row in rows]

    def _future_15m_candles(self, symbol: str, observation: datetime, bars: int) -> list[Candle]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT open_time, close_time, open, high, low, close
                FROM futures_klines_15m
                WHERE symbol = ?
                  AND open_time >= ?
                  AND aggregation_status = 'AGG_READY'
                ORDER BY open_time ASC
                LIMIT ?
                """,
                (symbol, db_time(observation), bars),
            ).fetchall()
        return [candle_from_row(row) for row in rows]

    def _atr(self, symbol: str, timeframe: str, close_time: datetime) -> Decimal | None:
        candles = self._candles_until(symbol, timeframe, close_time)
        if len(candles) < 15:
            return None
        window = candles[-15:]
        true_ranges = []
        for idx in range(1, len(window)):
            candle = window[idx]
            prev_close = window[idx - 1].close
            true_ranges.append(max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close)))
        if len(true_ranges) != 14:
            return None
        return sum(true_ranges, Decimal("0")) / Decimal("14")


class Phase7ForwardTestArtifactService:
    def __init__(self, artifact_dir: Path = DEFAULT_PHASE7_DIR) -> None:
        self.artifact_dir = artifact_dir

    def status(self) -> dict[str, Any]:
        return self._read_or_default("forward_test_status.json", default_status())

    def events(self) -> dict[str, Any]:
        return self._read_or_default("forward_test_events.json", {"generated_at": None, "generated_at_utc": None, "events": [], "read_only": True, "is_live_signal": False})

    def results(self) -> dict[str, Any]:
        return self._read_or_default("forward_test_results.json", {"generated_at": None, "generated_at_utc": None, "results": [], "read_only": True, "is_live_signal": False})

    def summary(self) -> dict[str, Any]:
        return self._read_or_default("forward_test_summary.json", {"generated_at": None, "generated_at_utc": None, "total_events": 0, "active_events": 0, "completed_events": 0, "verdict": "ARTIFACT_NOT_FOUND"})

    def _read_or_default(self, filename: str, default: dict[str, Any]) -> dict[str, Any]:
        path = self.artifact_dir / filename
        if not path.exists():
            return default
        return read_json(path)


def is_phase7_approved(candidate: dict[str, Any]) -> bool:
    edge = decimal_or_none(candidate.get("edge_vs_baseline"))
    score = int(candidate.get("total_score") or 0)
    arena_verdict = candidate.get("arena_verdict") or (candidate.get("arena_match") or {}).get("verdict")
    return (
        candidate.get("phase7_verdict") == "PHASE7_READY"
        and score >= PHASE7_SCORE_THRESHOLD
        and edge is not None
        and edge > PHASE7_EDGE_THRESHOLD_R
        and arena_verdict in ARENA_VERDICT_OK
    )


def is_lab_shadow_candidate(candidate: dict[str, Any]) -> bool:
    edge = decimal_or_none(candidate.get("edge_vs_baseline"))
    arena = candidate.get("arena_match") or {}
    arena_verdict = candidate.get("arena_verdict") or arena.get("verdict")
    return (
        candidate.get("candidate_status") == "SIGNAL_CANDIDATE"
        and candidate.get("timeframe") == "15m"
        and candidate.get("atr_reference_status") == "AVAILABLE"
        and bool(candidate.get("arena_match"))
        and bool(candidate.get("baseline_match"))
        and candidate.get("conflict_status") != "CONFLICTED"
        and edge is not None
        and edge > LAB_SHADOW_EDGE_THRESHOLD_R
        and arena_verdict not in LAB_REJECT_VERDICTS
    )


def deterministic_event_id(candidate: dict[str, Any], observation: datetime, direction: str, lane: str) -> str:
    raw = "|".join(
        [
            str(candidate.get("symbol")),
            str(candidate.get("timeframe")),
            str(candidate.get("mapped_setup_family") or candidate.get("setup_type")),
            direction,
            iso_utc(observation),
            lane,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def source_candidate_id(candidate: dict[str, Any], observation: datetime) -> str:
    return "|".join([str(candidate.get("symbol")), str(candidate.get("timeframe")), str(candidate.get("setup_type")), observation.isoformat()])


def direction_side(candidate: dict[str, Any]) -> str:
    if candidate.get("direction_side") in {"LONG", "SHORT"}:
        return candidate["direction_side"]
    if candidate.get("direction") == "BULLISH_CONTEXT":
        return "LONG"
    if candidate.get("direction") == "BEARISH_CONTEXT":
        return "SHORT"
    return "MIXED"


def completed_result(
    event: dict[str, Any],
    status: str,
    hit_time: datetime,
    bars: int,
    realized_r: Decimal | None,
    mfe: Decimal,
    mae: Decimal,
    ambiguous: bool,
) -> dict[str, Any]:
    evaluated_at = iso_utc(utcnow())
    return {
        "event_id": event["event_id"],
        "symbol": event["symbol"],
        "setup": event.get("setup"),
        "direction": event.get("direction"),
        "lane": event.get("lane", APPROVED_SHADOW),
        "shadow_type": event.get("shadow_type"),
        "result_status": status,
        "hit_time": iso_utc(hit_time),
        "hit_time_utc": iso_utc(hit_time),
        "expiry_time": event.get("expiry_time"),
        "expiry_time_utc": event.get("expiry_time_utc") or event.get("expiry_time"),
        "evaluated_at_utc": evaluated_at,
        "bars_to_result": bars,
        "minutes_to_result": bars * 15,
        "realized_R": float(realized_r) if realized_r is not None else None,
        "max_favorable_excursion_R": float(mfe),
        "max_adverse_excursion_R": float(mae),
        "close_return_R_at_expiry": float(realized_r) if status == "EXPIRED" and realized_r is not None else None,
        "ambiguous_same_candle": ambiguous,
        "is_live_signal": False,
        "is_execution": False,
    }


def unknown_result(event: dict[str, Any], reason: str) -> dict[str, Any]:
    evaluated_at = iso_utc(utcnow())
    return {
        "event_id": event["event_id"],
        "symbol": event.get("symbol"),
        "setup": event.get("setup"),
        "direction": event.get("direction"),
        "lane": event.get("lane", APPROVED_SHADOW),
        "shadow_type": event.get("shadow_type"),
        "result_status": "UNKNOWN_FORWARD_DATA",
        "hit_time": None,
        "hit_time_utc": None,
        "expiry_time": event.get("expiry_time"),
        "expiry_time_utc": event.get("expiry_time_utc") or event.get("expiry_time"),
        "evaluated_at_utc": evaluated_at,
        "bars_to_result": None,
        "minutes_to_result": None,
        "realized_R": None,
        "max_favorable_excursion_R": None,
        "max_adverse_excursion_R": None,
        "close_return_R_at_expiry": None,
        "ambiguous_same_candle": False,
        "reason": reason,
        "is_live_signal": False,
        "is_execution": False,
    }


def cannot_evaluate_result(event: dict[str, Any], reason: str) -> dict[str, Any]:
    payload = unknown_result(event, reason)
    payload["result_status"] = "CANNOT_EVALUATE"
    return payload


def default_status() -> dict[str, Any]:
    return {
        "generated_at": None,
        "generated_at_utc": None,
        "last_run_at_utc": None,
        "display_timezone_hint": "browser_local_or_Asia/Jakarta",
        "phase": "PHASE_7_SHADOW_FORWARD_TEST",
        "mode": "ARTIFACT_NOT_FOUND",
        "verdict": "PHASE7_DUAL_LANE_ERROR",
        "approved_candidate_count": 0,
        "approved_shadow_event_count": 0,
        "lab_shadow_candidate_count": 0,
        "lab_shadow_event_count": 0,
        "active_event_count": 0,
        "completed_event_count": 0,
        "waiting_event_count": 0,
        "error_count": 0,
        "reason": "Phase 7 artifact not found. Run run_phase7_forward_test.py.",
        "is_live_signal": False,
        "is_execution_enabled": False,
        "next_action": "Run Phase 7 forward-test script.",
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif value is None:
        raise ValueError("missing datetime")
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso_utc(value: datetime) -> str:
    return parse_dt(value).isoformat().replace("+00:00", "Z")


def db_time(value: datetime) -> str:
    return value.replace(tzinfo=None).isoformat(sep=" ")


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def candle_from_row(row: sqlite3.Row) -> Candle:
    return Candle(
        open_time=parse_dt(row["open_time"]),
        close_time=parse_dt(row["close_time"]),
        open=dec(row["open"]),
        high=dec(row["high"]),
        low=dec(row["low"]),
        close=dec(row["close"]),
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


def lane_summary(events: list[dict[str, Any]], results: list[dict[str, Any]], lane: str | None) -> dict[str, Any]:
    lane_events = [event for event in events if lane is None or event.get("lane", APPROVED_SHADOW) == lane]
    event_ids = {event["event_id"] for event in lane_events}
    lane_results = [result for result in results if result.get("event_id") in event_ids]
    completed = [result for result in lane_results if result.get("result_status") in {"TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE", "EXPIRED"}]
    realized = [Decimal(str(result["realized_R"])) for result in completed if result.get("realized_R") is not None]
    tp = sum(1 for result in lane_results if result.get("result_status") == "TP_HIT")
    sl = sum(1 for result in lane_results if result.get("result_status") == "SL_HIT")
    avg_r = float(sum(realized) / Decimal(len(realized))) if realized else None
    median_r = float(median(realized)) if realized else None
    return {
        "total_events": len(lane_events),
        "active_events": sum(1 for event in lane_events if event.get("status") in ACTIVE_STATUSES),
        "completed_events": len(completed),
        "tp_hit": tp,
        "sl_hit": sl,
        "expired": sum(1 for result in lane_results if result.get("result_status") == "EXPIRED"),
        "unknown_forward_data": sum(1 for result in lane_results if result.get("result_status") == "UNKNOWN_FORWARD_DATA"),
        "ambiguous": sum(1 for result in lane_results if result.get("ambiguous_same_candle")),
        "win_rate": None if tp + sl == 0 else tp / (tp + sl),
        "average_realized_R": avg_r,
        "median_realized_R": median_r,
        "avg_R": avg_r,
        "median_R": median_r,
    }


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
