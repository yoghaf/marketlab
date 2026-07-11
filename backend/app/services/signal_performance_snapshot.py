from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import SignalCandidatePerformanceService
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import json_safe, utcnow


DEFAULT_SIGNAL_PERFORMANCE_SNAPSHOT_DIR = REPO_ROOT / "backend" / "artifacts" / "signal_performance" / "live"
PERFORMANCE_FILE = "performance_closed.json"
FORWARD_INTEGRITY_FILE = "forward_integrity.json"
PERFORMANCE_1H_FILE = "performance_closed_1h.json"
FORWARD_INTEGRITY_1H_FILE = "forward_integrity_1h.json"
DEFAULT_PERFORMANCE_LIMIT = 500
DEFAULT_FORWARD_INTEGRITY_LIMIT = 200


class SignalPerformanceSnapshotRunner:
    """Persist default Signal History payloads so the web page does not recompute them on open."""

    def __init__(self, db: Session, artifact_dir: Path = DEFAULT_SIGNAL_PERFORMANCE_SNAPSHOT_DIR) -> None:
        self.db = db
        self.artifact_dir = artifact_dir

    def run(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        performance_limit: int = DEFAULT_PERFORMANCE_LIMIT,
        forward_integrity_limit: int = DEFAULT_FORWARD_INTEGRITY_LIMIT,
    ) -> dict[str, Any]:
        service = SignalCandidatePerformanceService(self.db)
        performance = _performance_payload(service, epoch=epoch, timeframe=None, limit=max(1, performance_limit))
        performance_1h = _performance_payload(service, epoch=epoch, timeframe="1h", limit=max(1, performance_limit))
        forward_integrity = _forward_integrity_payload(service, epoch=epoch, timeframe=None, limit=max(1, forward_integrity_limit))
        forward_integrity_1h = _forward_integrity_payload(
            service,
            epoch=epoch,
            timeframe="1h",
            limit=max(1, forward_integrity_limit),
        )

        generated_at = utcnow().isoformat()
        performance = _with_snapshot_meta(
            performance,
            generated_at_utc=generated_at,
            source="signal_performance_snapshot",
            filename=PERFORMANCE_FILE,
        )
        forward_integrity = _with_snapshot_meta(
            forward_integrity,
            generated_at_utc=generated_at,
            source="signal_forward_integrity_snapshot",
            filename=FORWARD_INTEGRITY_FILE,
        )
        performance_1h = _with_snapshot_meta(
            performance_1h,
            generated_at_utc=generated_at,
            source="signal_performance_snapshot_1h",
            filename=PERFORMANCE_1H_FILE,
        )
        forward_integrity_1h = _with_snapshot_meta(
            forward_integrity_1h,
            generated_at_utc=generated_at,
            source="signal_forward_integrity_snapshot_1h",
            filename=FORWARD_INTEGRITY_1H_FILE,
        )

        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.artifact_dir / PERFORMANCE_FILE, json_safe(performance))
        _atomic_write_json(self.artifact_dir / FORWARD_INTEGRITY_FILE, json_safe(forward_integrity))
        _atomic_write_json(self.artifact_dir / PERFORMANCE_1H_FILE, json_safe(performance_1h))
        _atomic_write_json(self.artifact_dir / FORWARD_INTEGRITY_1H_FILE, json_safe(forward_integrity_1h))
        return {
            "generated_at_utc": generated_at,
            "artifact_dir": str(self.artifact_dir),
            "performance_path": str(self.artifact_dir / PERFORMANCE_FILE),
            "forward_integrity_path": str(self.artifact_dir / FORWARD_INTEGRITY_FILE),
            "performance_1h_path": str(self.artifact_dir / PERFORMANCE_1H_FILE),
            "forward_integrity_1h_path": str(self.artifact_dir / FORWARD_INTEGRITY_1H_FILE),
            "performance_items": len(performance.get("items") or []),
            "forward_integrity_items": len(forward_integrity.get("items") or []),
            "performance_1h_items": len(performance_1h.get("items") or []),
            "forward_integrity_1h_items": len(forward_integrity_1h.get("items") or []),
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
        }


class SignalPerformanceSnapshotService:
    def __init__(self, artifact_dir: Path = DEFAULT_SIGNAL_PERFORMANCE_SNAPSHOT_DIR) -> None:
        self.artifact_dir = artifact_dir

    def performance(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(PERFORMANCE_FILE)
        return _slice_payload(payload, limit=max(1, limit), list_keys=("items",))

    def performance_1h(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(PERFORMANCE_1H_FILE)
        return _slice_payload(payload, limit=max(1, limit), list_keys=("items",))

    def forward_integrity(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(FORWARD_INTEGRITY_FILE)
        return _slice_payload(payload, limit=max(1, limit), list_keys=("items", "stale_items"))

    def forward_integrity_1h(self, *, limit: int) -> dict[str, Any]:
        payload = self._read(FORWARD_INTEGRITY_1H_FILE)
        return _slice_payload(payload, limit=max(1, limit), list_keys=("items", "stale_items"))

    def _read(self, filename: str) -> dict[str, Any]:
        path = self.artifact_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Signal performance snapshot not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))


def _performance_payload(
    service: SignalCandidatePerformanceService,
    *,
    epoch: str,
    timeframe: str | None,
    limit: int,
) -> dict[str, Any]:
    return service.summary(
        epoch=epoch,
        include_watch_only=False,
        position_lock=True,
        stage=None,
        timeframe=timeframe,
        symbol=None,
        result_status="closed",
        limit=limit,
    )


def _forward_integrity_payload(
    service: SignalCandidatePerformanceService,
    *,
    epoch: str,
    timeframe: str | None,
    limit: int,
) -> dict[str, Any]:
    return service.forward_integrity(
        epoch=epoch,
        include_watch_only=False,
        position_lock=True,
        stage=None,
        timeframe=timeframe,
        limit=limit,
    )


def _with_snapshot_meta(payload: dict[str, Any], *, generated_at_utc: str, source: str, filename: str) -> dict[str, Any]:
    safe_payload = dict(payload)
    safe_payload["snapshot"] = {
        "source": source,
        "filename": filename,
        "generated_at_utc": generated_at_utc,
        "refresh_owner": "marketlab_research_loop",
        "read_model": "artifact_snapshot",
    }
    return safe_payload


def _slice_payload(payload: dict[str, Any], *, limit: int, list_keys: tuple[str, ...]) -> dict[str, Any]:
    sliced = deepcopy(payload)
    for key in list_keys:
        rows = sliced.get(key)
        if isinstance(rows, list):
            sliced[key] = rows[:limit]
    filters = sliced.get("filters")
    if isinstance(filters, dict):
        filters["limit"] = limit
    sliced["cache"] = {"hit": True, "source": "artifact_snapshot", "ttl_seconds": None}
    return sliced


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)
