from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from app.services.phase7_forward_test import DEFAULT_DB_PATH, DEFAULT_PHASE7_DIR, Phase7ForwardTestService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MarketLab Phase 7 shadow forward-test once.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_PHASE7_DIR)
    args = parser.parse_args()

    payload = Phase7ForwardTestService(db_path=args.db_path, artifact_dir=args.artifact_dir).run()
    status = payload["status"]
    print(
        json.dumps(
            {
                "mode": status["mode"],
                "verdict": status["verdict"],
                "approved_candidate_count": status["approved_candidate_count"],
                "approved_shadow_event_count": status.get("approved_shadow_event_count"),
                "lab_shadow_candidate_count": status.get("lab_shadow_candidate_count"),
                "lab_shadow_event_count": status.get("lab_shadow_event_count"),
                "active_event_count": status["active_event_count"],
                "completed_event_count": status["completed_event_count"],
                "waiting_event_count": status["waiting_event_count"],
                "error_count": status["error_count"],
                "reason": status["reason"],
                "is_live_signal": status["is_live_signal"],
                "is_execution_enabled": status["is_execution_enabled"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
