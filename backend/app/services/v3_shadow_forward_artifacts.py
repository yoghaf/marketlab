from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import SignalCandidatePerformanceService
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import json_safe


DEFAULT_V3_SHADOW_FORWARD_DIR = REPO_ROOT / "backend" / "artifacts" / "v3_shadow_forward" / "v1"
SUMMARY_FILE = "summary.json"


class V3ShadowForwardArtifactRunner:
    """Persist a read-only V3 shadow forward snapshot for ops/debugging."""

    def __init__(self, db: Session, artifact_dir: Path = DEFAULT_V3_SHADOW_FORWARD_DIR) -> None:
        self.db = db
        self.artifact_dir = artifact_dir

    def run(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 5,
        limit: int = 100,
    ) -> dict[str, Any]:
        payload = SignalCandidatePerformanceService(self.db).v3_shadow_forward_log(
            epoch=epoch,
            include_watch_only=include_watch_only,
            position_lock=position_lock,
            min_sample=min_sample,
            limit=limit,
        )
        safe_payload = json_safe(payload)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        (self.artifact_dir / SUMMARY_FILE).write_text(json.dumps(safe_payload, indent=2), encoding="utf-8")
        return safe_payload


class V3ShadowForwardArtifactService:
    def __init__(self, artifact_dir: Path = DEFAULT_V3_SHADOW_FORWARD_DIR) -> None:
        self.artifact_dir = artifact_dir

    def summary(self) -> dict[str, Any]:
        path = self.artifact_dir / SUMMARY_FILE
        if not path.exists():
            raise FileNotFoundError(f"V3 shadow forward artifact not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
