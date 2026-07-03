from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from app.services.multitimeframe_features import REPO_ROOT, json_safe


DEFAULT_EARLY_BACKTEST_DIR = REPO_ROOT / "backend" / "artifacts" / "signal_factory" / "v2_backtest"
RESULTS_FILE = "results.json"
EVENTS_FILE = "events.json"
EARLY_STAGES = {"EARLY_LONG", "EARLY_SHORT"}
HORIZONS = ("15m", "1h", "4h", "24h")


class EarlyBacktestLabArtifactService:
    def __init__(self, artifact_dir: Path = DEFAULT_EARLY_BACKTEST_DIR) -> None:
        self.artifact_dir = artifact_dir

    def summary(self) -> dict[str, Any]:
        payload = self._results_payload()
        events = self._early_events(payload)
        return json_safe(
            {
                "metadata": payload.get("metadata") or {},
                "source": {
                    "artifact_dir": str(self.artifact_dir),
                    "results_file": RESULTS_FILE,
                    "events_file": EVENTS_FILE,
                    "filter": "stage in EARLY_LONG, EARLY_SHORT",
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
        events = payload.get("events")
        if events is None:
            events_path = self.artifact_dir / EVENTS_FILE
            events = json.loads(events_path.read_text()) if events_path.exists() else []
        return [event for event in events if event.get("stage") in EARLY_STAGES]

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
        ready = 0
        waiting = 0
        for event in events:
            result = (event.get("horizons") or {}).get(horizon) or {}
            status = result.get("status")
            outcome = str(result.get("outcome") or status or "UNKNOWN")
            outcomes[outcome] += 1
            realized = _dec(result.get("realized_r"))
            if realized is None:
                waiting += 1
                continue
            ready += 1
            values.append(realized)
        return {
            "events": len(events),
            "ready": ready,
            "waiting": waiting,
            "tp": outcomes.get("TP_FIRST", 0),
            "sl": outcomes.get("SL_FIRST", 0),
            "both": outcomes.get("BOTH_HIT_SAME_CANDLE", 0),
            "neither": outcomes.get("NEITHER_CLOSE_AT_HORIZON", 0),
            "outcomes": dict(outcomes),
            "avg_r": _avg(values),
            "median_r": median(values) if values else None,
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
                    "horizon": horizon,
                    "outcome": row_outcome,
                    "status": result.get("status"),
                    "realized_r": result.get("realized_r"),
                    "mfe_r": result.get("mfe_r"),
                    "mae_r": result.get("mae_r"),
                    "result_time_utc": result.get("result_time_utc"),
                    "result_time_wib": result.get("result_time_wib"),
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
