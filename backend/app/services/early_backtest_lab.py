from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from app.services.multitimeframe_features import REPO_ROOT, json_safe


DEFAULT_EARLY_BACKTEST_DIR = REPO_ROOT / "backend" / "artifacts" / "threshold_research" / "normalized_impulse_v1"
RESULTS_FILE = "results.json"
EVENTS_FILE = "events.json"
EARLY_STAGES = {"EARLY_LONG", "EARLY_SHORT"}
NORMALIZED_EARLY_SETUPS = {"EARLY_LONG_V0": "EARLY_LONG", "EARLY_SHORT_V0": "EARLY_SHORT"}
HORIZONS = ("15m", "1h", "4h", "24h")


class EarlyBacktestLabArtifactService:
    def __init__(self, artifact_dir: Path = DEFAULT_EARLY_BACKTEST_DIR) -> None:
        self.artifact_dir = artifact_dir

    def summary(self) -> dict[str, Any]:
        payload = self._results_payload()
        events = self._early_events(payload)
        metadata = self._metadata(payload)
        return json_safe(
            {
                "metadata": metadata,
                "source": {
                    "artifact_dir": str(self.artifact_dir),
                    "results_file": RESULTS_FILE,
                    "events_file": EVENTS_FILE,
                    "filter": "stage in EARLY_LONG, EARLY_SHORT",
                    "artifact_type": metadata.get("artifact_type"),
                },
                "guardrails": {
                    "read_only": True,
                    "not_live_signal": True,
                    "not_execution_instruction": True,
                    "entry_market": "futures",
                    "spot_usage": "evidence/filter only",
                },
                "summary": self._summary(events),
                "latest_events": self._flatten_events(events, horizon="4h", limit=25),
            }
        )

    def events(
        self,
        stage: str | None = None,
        horizon: str = "4h",
        outcome: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        if horizon not in HORIZONS:
            raise ValueError(f"unsupported horizon: {horizon}")
        payload = self._results_payload()
        rows = self._flatten_events(self._early_events(payload), horizon=horizon, stage=stage, outcome=outcome, limit=limit)
        return json_safe(
            {
                "count": len(rows),
                "filters": {
                    "stage": stage,
                    "horizon": horizon,
                    "outcome": outcome,
                    "limit": limit,
                },
                "read_only": True,
                "not_live_signal": True,
                "not_execution_instruction": True,
                "items": rows,
            }
        )

    def _results_payload(self) -> dict[str, Any]:
        path = self.artifact_dir / RESULTS_FILE
        if not path.exists():
            raise FileNotFoundError(f"Early backtest artifact not found: {path}")
        return json.loads(path.read_text())

    def _early_events(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if "token_results" in payload:
            return self._normalized_impulse_events(payload)
        events = payload.get("events")
        if events is None:
            events_path = self.artifact_dir / EVENTS_FILE
            events = json.loads(events_path.read_text()) if events_path.exists() else []
        return [event for event in events if event.get("stage") in EARLY_STAGES]

    def _metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "token_results" in payload:
            coverage = payload.get("coverage") or {}
            horizon_results = payload.get("early_horizon_results") or {}
            default_token_results = (
                horizon_results.get("1h", {}).get("token_results")
                if horizon_results
                else payload.get("token_results")
            ) or {}
            return {
                "generated_at_utc": payload.get("generated_at"),
                "epoch": "NORMALIZED_IMPULSE_RESEARCH_V1",
                "artifact_type": "historical_normalized_impulse_backtest",
                "signals_loaded": sum(
                    len(default_token_results.get(setup, []))
                    for setup in NORMALIZED_EARLY_SETUPS
                ),
                "events_evaluated": sum(
                    len(default_token_results.get(setup, []))
                    for setup in NORMALIZED_EARLY_SETUPS
                ),
                "source_candidate_count": sum(
                    ((payload.get("setup_results") or {}).get(setup, {}) or {}).get("source_candidate_count", 0)
                    for setup in NORMALIZED_EARLY_SETUPS
                ),
                "position_lock_mode": ((payload.get("parameters") or {}).get("position_lock_mode")),
                "feature_rows": coverage.get("feature_rows"),
                "candles_15m": coverage.get("candles_15m"),
                "candles_1h": coverage.get("candles_1h"),
                "entry_market": "futures",
                "spot_usage": "evidence/filter only",
            }
        metadata = payload.get("metadata") or {}
        metadata.setdefault("artifact_type", "forward_log_backtest")
        return metadata

    def _normalized_impulse_events(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if payload.get("early_horizon_results"):
            return self._normalized_impulse_multi_horizon_events(payload)
        rows: list[dict[str, Any]] = []
        token_results = payload.get("token_results") or {}
        for setup, stage in NORMALIZED_EARLY_SETUPS.items():
            direction = "LONG" if stage == "EARLY_LONG" else "SHORT"
            for row in token_results.get(setup, []):
                outcome = row.get("outcome") or "UNKNOWN"
                signal_time = row.get("window_close_time") or row.get("setup_window_open_time")
                result_time = row.get("result_time")
                rows.append(
                    {
                        "signal_id": f"{setup}:{row.get('symbol')}:{row.get('window_close_time')}",
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe") or "15m",
                        "signal_time_utc": signal_time,
                        "signal_time_wib": _to_wib_string(signal_time),
                        "stage": stage,
                        "direction": direction,
                        "confidence_tier": row.get("quality_bucket") or "RESEARCH_V0",
                        "core_score": None,
                        "evidence_score": None,
                        "evidence_data_completeness": None,
                        "execution_flag": "RESEARCH_BACKTEST",
                        "entry_market": row.get("entry_market") or "futures",
                        "entry_price_source": row.get("entry_price_source") or "futures_klines_15m.close",
                        "entry": row.get("entry_price"),
                        "stop": row.get("stop_loss_reference"),
                        "target": row.get("take_profit_reference"),
                        "risk": row.get("risk_distance"),
                        "rr": row.get("rr"),
                        "target_return_pct": row.get("target_return_pct"),
                        "stop_return_pct": row.get("stop_return_pct"),
                        "horizons": {
                            "15m": {"status": "NOT_EVALUATED", "outcome": "NOT_EVALUATED", "realized_r": None},
                            "1h": {
                                "status": "READY",
                                "outcome": outcome,
                                "realized_r": row.get("realized_r"),
                                "realized_return_pct": row.get("realized_return_pct"),
                                "mfe_r": row.get("max_favorable_r"),
                                "mae_r": row.get("max_adverse_r"),
                                "max_favorable_return_pct": row.get("max_favorable_return_pct"),
                                "max_adverse_return_pct": row.get("max_adverse_return_pct"),
                                "result_time_utc": result_time,
                                "result_time_wib": _to_wib_string(result_time),
                            },
                            "4h": {"status": "NOT_EVALUATED", "outcome": "NOT_EVALUATED", "realized_r": None},
                            "24h": {"status": "NOT_EVALUATED", "outcome": "NOT_EVALUATED", "realized_r": None},
                        },
                        "evidence": {
                            "price_return_pct": row.get("price_return_pct"),
                            "volume_spike_ratio_20": row.get("volume_spike_ratio_20"),
                            "range_spike_ratio_20": row.get("range_spike_ratio_20"),
                            "oi_spike_ratio_20": row.get("oi_spike_ratio_20"),
                            "oi_change_pct": row.get("oi_change_pct"),
                            "price_move_atr_1h": row.get("price_move_atr_1h"),
                            "spot_support_status": row.get("spot_support_status"),
                            "price_return_pct_1h": row.get("price_return_pct_1h"),
                            "universe_rank": row.get("universe_rank"),
                            "position_lock_status": row.get("position_lock_status"),
                        },
                        "not_live_signal": True,
                        "not_execution_instruction": True,
                    }
                )
        return rows

    def _normalized_impulse_multi_horizon_events(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        events_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        for horizon in HORIZONS:
            horizon_payload = (payload.get("early_horizon_results") or {}).get(horizon) or {}
            token_results = horizon_payload.get("token_results") or {}
            for setup, stage in NORMALIZED_EARLY_SETUPS.items():
                direction = "LONG" if stage == "EARLY_LONG" else "SHORT"
                for row in token_results.get(setup, []):
                    key = (setup, str(row.get("symbol")), str(row.get("window_close_time")))
                    event = events_by_key.get(key)
                    if event is None:
                        signal_time = row.get("window_close_time") or row.get("setup_window_open_time")
                        event = {
                            "signal_id": f"{setup}:{row.get('symbol')}:{row.get('window_close_time')}",
                            "symbol": row.get("symbol"),
                            "timeframe": row.get("timeframe") or "15m",
                            "signal_time_utc": signal_time,
                            "signal_time_wib": _to_wib_string(signal_time),
                            "stage": stage,
                            "direction": direction,
                            "confidence_tier": row.get("quality_bucket") or "RESEARCH_V0",
                            "core_score": None,
                            "evidence_score": None,
                            "evidence_data_completeness": None,
                            "execution_flag": "RESEARCH_BACKTEST",
                            "entry_market": row.get("entry_market") or "futures",
                            "entry_price_source": row.get("entry_price_source") or "futures_klines_15m.close",
                            "entry": row.get("entry_price"),
                            "stop": row.get("stop_loss_reference"),
                            "target": row.get("take_profit_reference"),
                            "risk": row.get("risk_distance"),
                            "rr": row.get("rr"),
                            "target_return_pct": row.get("target_return_pct"),
                            "stop_return_pct": row.get("stop_return_pct"),
                            "horizons": {
                                item: {"status": "NOT_EVALUATED", "outcome": "NOT_EVALUATED", "realized_r": None}
                                for item in HORIZONS
                            },
                            "evidence": _normalized_evidence(row),
                            "not_live_signal": True,
                            "not_execution_instruction": True,
                        }
                        events_by_key[key] = event
                    result_time = row.get("result_time")
                    event["horizons"][horizon] = {
                        "status": "READY",
                        "outcome": row.get("outcome") or "UNKNOWN",
                        "realized_r": row.get("realized_r"),
                        "realized_return_pct": row.get("realized_return_pct"),
                        "mfe_r": row.get("max_favorable_r"),
                        "mae_r": row.get("max_adverse_r"),
                        "max_favorable_return_pct": row.get("max_favorable_return_pct"),
                        "max_adverse_return_pct": row.get("max_adverse_return_pct"),
                        "result_time_utc": result_time,
                        "result_time_wib": _to_wib_string(result_time),
                    }
        return list(events_by_key.values())

    def _summary(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        by_stage = Counter(str(event.get("stage") or "UNKNOWN") for event in events)
        by_confidence = Counter(str(event.get("confidence_tier") or "UNKNOWN") for event in events)
        by_horizon = {horizon: self._horizon_summary(events, horizon) for horizon in HORIZONS}
        return {
            "total_events": len(events),
            "by_stage": dict(by_stage),
            "by_confidence": dict(by_confidence),
            "by_horizon": by_horizon,
            "best_horizon": self._best_horizon(by_horizon),
        }

    def _horizon_summary(self, events: list[dict[str, Any]], horizon: str) -> dict[str, Any]:
        outcomes: Counter[str] = Counter()
        values: list[Decimal] = []
        return_values: list[Decimal] = []
        rr_values: list[Decimal] = []
        ready = 0
        waiting = 0
        for event in events:
            result = (event.get("horizons") or {}).get(horizon) or {}
            status = result.get("status")
            if status == "NOT_EVALUATED":
                continue
            outcome = str(result.get("outcome") or status or "UNKNOWN")
            outcomes[outcome] += 1
            realized = _dec(result.get("realized_r"))
            if realized is None:
                waiting += 1
                continue
            ready += 1
            values.append(realized)
            realized_return = _dec(result.get("realized_return_pct"))
            if realized_return is not None:
                return_values.append(realized_return)
            rr_value = _dec(event.get("rr"))
            if rr_value is not None:
                rr_values.append(rr_value)
        return {
            "events": ready + waiting,
            "ready": ready,
            "waiting": waiting,
            "tp": outcomes.get("TP_FIRST", 0),
            "sl": outcomes.get("SL_FIRST", 0),
            "both": outcomes.get("BOTH_HIT_SAME_CANDLE", 0),
            "neither": outcomes.get("NEITHER_CLOSE_AT_HORIZON", 0) + outcomes.get("NEITHER", 0),
            "outcomes": dict(outcomes),
            "avg_r": _avg(values),
            "median_r": median(values) if values else None,
            "avg_return_pct": _avg(return_values),
            "median_return_pct": median(return_values) if return_values else None,
            "planned_rr": median(rr_values) if rr_values else None,
            "best_r": max(values) if values else None,
            "worst_r": min(values) if values else None,
        }

    def _best_horizon(self, by_horizon: dict[str, dict[str, Any]]) -> str | None:
        ready = [
            (horizon, data)
            for horizon, data in by_horizon.items()
            if data.get("ready", 0) > 0 and data.get("median_r") is not None
        ]
        if not ready:
            return None
        return max(ready, key=lambda item: Decimal(str(item[1]["median_r"])))[0]

    def _flatten_events(
        self,
        events: list[dict[str, Any]],
        horizon: str,
        stage: str | None = None,
        outcome: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for event in events:
            if stage and event.get("stage") != stage:
                continue
            result = (event.get("horizons") or {}).get(horizon) or {}
            if result.get("status") == "NOT_EVALUATED":
                continue
            row_outcome = result.get("outcome") or result.get("status") or "UNKNOWN"
            if outcome and row_outcome != outcome:
                continue
            rows.append(
                {
                    "signal_id": event.get("signal_id"),
                    "symbol": event.get("symbol"),
                    "timeframe": event.get("timeframe"),
                    "signal_time_utc": event.get("signal_time_utc"),
                    "signal_time_wib": event.get("signal_time_wib"),
                    "stage": event.get("stage"),
                    "direction": event.get("direction"),
                    "confidence_tier": event.get("confidence_tier"),
                    "core_score": event.get("core_score"),
                    "evidence_score": event.get("evidence_score"),
                    "evidence_data_completeness": event.get("evidence_data_completeness"),
                    "execution_flag": event.get("execution_flag"),
                    "entry_market": event.get("entry_market"),
                    "entry_price_source": event.get("entry_price_source"),
                    "entry": event.get("entry"),
                    "stop": event.get("stop"),
                    "target": event.get("target"),
                    "risk": event.get("risk"),
                    "rr": event.get("rr"),
                    "target_return_pct": event.get("target_return_pct"),
                    "stop_return_pct": event.get("stop_return_pct"),
                    "horizon": horizon,
                    "outcome": row_outcome,
                    "status": result.get("status"),
                    "realized_r": result.get("realized_r"),
                    "realized_return_pct": result.get("realized_return_pct"),
                    "mfe_r": result.get("mfe_r"),
                    "mae_r": result.get("mae_r"),
                    "max_favorable_return_pct": result.get("max_favorable_return_pct"),
                    "max_adverse_return_pct": result.get("max_adverse_return_pct"),
                    "result_time_utc": result.get("result_time_utc"),
                    "result_time_wib": result.get("result_time_wib"),
                    "evidence": event.get("evidence") or {},
                    "not_live_signal": True,
                    "not_execution_instruction": True,
                }
            )
        rows.sort(key=lambda item: str(item.get("signal_time_utc") or ""), reverse=True)
        return rows[: max(1, min(int(limit), 1000))]


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _avg(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _normalized_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "price_return_pct": row.get("price_return_pct"),
        "volume_spike_ratio_20": row.get("volume_spike_ratio_20"),
        "range_spike_ratio_20": row.get("range_spike_ratio_20"),
        "oi_spike_ratio_20": row.get("oi_spike_ratio_20"),
        "oi_change_pct": row.get("oi_change_pct"),
        "price_move_atr_1h": row.get("price_move_atr_1h"),
        "spot_support_status": row.get("spot_support_status"),
        "price_return_pct_1h": row.get("price_return_pct_1h"),
        "universe_rank": row.get("universe_rank"),
        "position_lock_status": row.get("position_lock_status"),
    }


def _to_wib_string(value: Any) -> str | None:
    if not value:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S WIB")
    except Exception:
        return str(value)
