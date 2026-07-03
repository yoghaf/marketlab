from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.services.anomaly_signal_factory import DEFAULT_SIGNAL_FACTORY_DIR  # noqa: E402
from app.services.signal_forward_return_logger import SignalForwardReturnLogger  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Log read-only Signal Factory V2 forward returns.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_SIGNAL_FACTORY_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        result = SignalForwardReturnLogger(db, artifact_dir=args.artifact_dir).run(
            limit=args.limit,
            dry_run=args.dry_run,
        )
    print(
        "signal_forward_return_logger complete "
        f"artifact_generated_at={result.artifact_generated_at} "
        f"candidates={result.candidates_seen} "
        f"inserted={result.inserted_count} "
        f"updated={result.updated_count} "
        f"ready={result.ready_counts}"
    )


if __name__ == "__main__":
    main()
