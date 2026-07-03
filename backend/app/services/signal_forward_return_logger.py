from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline15m, SignalForwardReturnLog
from app.services.anomaly_signal_factory import DEFAULT_SIGNAL_FACTORY_DIR
from app.services.utils import json_safe, utcnow


HORIZONS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "24h": timedelta(hours=24),
}
OBSERVATION_START_UTC = datetime(2026, 7, 3, 6, 15, 20)
OBSERVATION_EPOCH = "STAGE8_OBSERVATION"
PRE_OBSERVATION_EPOCH = "PRE_STAGE8_FIX"


@dataclass(frozen=True)
class ForwardReturnLoggerResult:
    artifact_generated_at: str | None
    candidates_seen: int
    inserted_count: int
    updated_count: int
    ready_counts: dict[str, int]


class SignalForwardReturnLogger:
    def __init__(self, db: Session, artifact_dir: Path = DEFAULT_SIGNAL_FACTORY_DIR) -> None:
        self.db = db
        self.artifact_dir = artifact_dir

    def run(self, limit: int | None = None, dry_run: bool = False) -> ForwardReturnLoggerResult:
        payload = self._read_candidates()
        candidates = payload.get("items") or []
        if limit is not None:
            candidates = candidates[: max(0, limit)]
        inserted = 0
        updated = 0
        ready_counts = {key: 0 for key in HORIZONS}
        now = utcnow()
        generated_at = payload.get("generated_at")
        for candidate in candidates:
            row_payload = self._payload(candidate, generated_at, now)
            for horizon in HORIZONS:
                ready_counts[horizon] += int(row_payload[f"status_{horizon}"] == "READY")
            action = self._upsert(row_payload, dry_run=dry_run)
            inserted += int(action == "inserted")
            updated += int(action == "updated")
        if not dry_run:
            self.db.commit()
        return ForwardReturnLoggerResult(
            artifact_generated_at=generated_at,
            candidates_seen=len(candidates),
            inserted_count=inserted,
            updated_count=updated,
            ready_counts=ready_counts,
        )

    def status_summary(self) -> dict[str, Any]:
        total = self.db.scalar(select(func.count()).select_from(SignalForwardReturnLog)) or 0
        return {
            "total_rows": total,
            "latest_signal_time": self.db.scalar(select(func.max(SignalForwardReturnLog.signal_timestamp))),
            "latest_update": self.db.scalar(select(func.max(SignalForwardReturnLog.updated_at))),
            "status_15m": self._counts(SignalForwardReturnLog.status_15m),
            "status_1h": self._counts(SignalForwardReturnLog.status_1h),
            "status_4h": self._counts(SignalForwardReturnLog.status_4h),
            "status_24h": self._counts(SignalForwardReturnLog.status_24h),
            "candidate_status": self._counts(SignalForwardReturnLog.candidate_status),
            "stage": self._counts(SignalForwardReturnLog.stage),
        }

    def _payload(self, candidate: dict[str, Any], generated_at: str | None, now: datetime) -> dict[str, Any]:
        evidence = candidate.get("evidence") or {}
        window_open = _parse_dt(candidate.get("window_start"))
        window_close = _parse_dt(candidate.get("window_end"))
        artifact_time = _parse_dt(generated_at)
        signal_timestamp = window_close or window_open or now
        signal_id = _signal_id(candidate)
        signal_candle = self._candle_at(candidate.get("symbol"), signal_timestamp)
        price_at_signal = _dec(candidate.get("entry_price")) or _dec(evidence.get("entry_price")) or (
            signal_candle.close if signal_candle else None
        )
        horizon_prices: dict[str, Decimal | None] = {}
        horizon_statuses: dict[str, str] = {}
        for horizon, delta in HORIZONS.items():
            candle = self._candle_at(candidate.get("symbol"), signal_timestamp + delta)
            horizon_prices[horizon] = candle.close if candle else None
            horizon_statuses[horizon] = "READY" if candle else "WAITING_DATA"
        return {
            "signal_id": signal_id,
            "symbol": candidate.get("symbol"),
            "timeframe": candidate.get("timeframe") or "15m",
            "signal_timestamp": signal_timestamp,
            "window_open_time": window_open,
            "window_close_time": window_close,
            "direction": _direction(candidate.get("direction")),
            "stage": candidate.get("setup_type") or candidate.get("stage") or "UNKNOWN",
            "candidate_status": candidate.get("candidate_status") or "UNKNOWN",
            "core_score": _dec(candidate.get("core_score") or evidence.get("core_score")),
            "evidence_score": _dec(candidate.get("evidence_score") or evidence.get("evidence_score")),
            "evidence_data_completeness": _int(candidate.get("evidence_data_completeness") or evidence.get("evidence_data_completeness")),
            "confidence_tier": candidate.get("evidence_confidence_tier") or evidence.get("evidence_confidence_tier") or candidate.get("confidence"),
            "execution_flag": candidate.get("execution_risk_status") or evidence.get("execution_risk_status"),
            "entry_ref": candidate.get("entry_mode") or evidence.get("entry_mode") or candidate.get("entry_price_source"),
            "sl_ref": _dec(candidate.get("stop_loss_reference") or evidence.get("stop_loss_reference")),
            "tp_ref": _dec(candidate.get("take_profit_reference") or evidence.get("take_profit_reference")),
            "price_at_signal": price_at_signal,
            "price_at_15m": horizon_prices["15m"],
            "price_at_1h": horizon_prices["1h"],
            "price_at_4h": horizon_prices["4h"],
            "price_at_24h": horizon_prices["24h"],
            "status_15m": horizon_statuses["15m"],
            "status_1h": horizon_statuses["1h"],
            "status_4h": horizon_statuses["4h"],
            "status_24h": horizon_statuses["24h"],
            "source_artifact_generated_at": artifact_time,
            "observation_epoch": _observation_epoch(artifact_time),
            "observation_start_utc": OBSERVATION_START_UTC,
            "observation_marker": bool(artifact_time and artifact_time >= OBSERVATION_START_UTC),
            "evidence": json_safe(
                {
                    "source": "signal_factory_v2_artifact + futures_klines_15m",
                    "read_only_forward_return_log": True,
                    "not_live_signal": True,
                    "not_execution_instruction": True,
                    "signal_factory_version": candidate.get("signal_factory_version"),
                    "reason": candidate.get("reason"),
                    "evidence": evidence,
                }
            ),
            "created_at": now,
            "updated_at": now,
        }

    def _candle_at(self, symbol: str | None, close_time: datetime) -> FuturesKline15m | None:
        if not symbol:
            return None
        return self.db.scalar(
            select(FuturesKline15m).where(
                FuturesKline15m.symbol == symbol,
                FuturesKline15m.close_time == _as_db_time(close_time),
                FuturesKline15m.aggregation_status == "AGG_READY",
            )
        )

    def _upsert(self, payload: dict[str, Any], dry_run: bool) -> str:
        existing = self.db.scalar(
            select(SignalForwardReturnLog).where(SignalForwardReturnLog.signal_id == payload["signal_id"])
        )
        if existing is None:
            if not dry_run:
                self.db.add(SignalForwardReturnLog(**payload))
            return "inserted"
        created_at = existing.created_at
        payload = dict(payload)
        payload["created_at"] = created_at
        if not dry_run:
            for key, value in payload.items():
                setattr(existing, key, value)
        return "updated"

    def _counts(self, column: Any) -> dict[str, int]:
        rows = self.db.execute(select(column, func.count()).group_by(column)).all()
        return {str(key): int(count) for key, count in rows}

    def _read_candidates(self) -> dict[str, Any]:
        path = self.artifact_dir / "candidates.json"
        if not path.exists():
            raise FileNotFoundError(f"Signal Factory candidates artifact not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))


def _signal_id(candidate: dict[str, Any]) -> str:
    raw = "|".join(
        str(candidate.get(key) or "")
        for key in ("symbol", "timeframe", "window_start", "window_end", "setup_type", "candidate_status")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _direction(value: Any) -> str:
    if value == "BULLISH_CONTEXT":
        return "LONG"
    if value == "BEARISH_CONTEXT":
        return "SHORT"
    return str(value or "MIXED")


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _as_db_time(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _observation_epoch(artifact_time: datetime | None) -> str:
    if artifact_time is not None and artifact_time >= OBSERVATION_START_UTC:
        return OBSERVATION_EPOCH
    return PRE_OBSERVATION_EPOCH
