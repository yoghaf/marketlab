from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.multitimeframe_features import DEFAULT_DB_PATH  # noqa: E402
from app.services.signal_performance_snapshot import (  # noqa: E402
    DEFAULT_FORWARD_INTEGRITY_LIMIT,
    DEFAULT_PERFORMANCE_LIMIT,
    DEFAULT_SIGNAL_PERFORMANCE_SNAPSHOT_DIR,
    SignalPerformanceSnapshotRunner,
)
from app.services.utils import json_safe  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist Signal History read-only performance snapshots.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_SIGNAL_PERFORMANCE_SNAPSHOT_DIR)
    parser.add_argument("--performance-limit", type=int, default=DEFAULT_PERFORMANCE_LIMIT)
    parser.add_argument("--forward-integrity-limit", type=int, default=DEFAULT_FORWARD_INTEGRITY_LIMIT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = args.db_path if args.db_path.is_absolute() else (REPO_ROOT / args.db_path).resolve()
    output_dir = args.output_dir if args.output_dir.is_absolute() else (REPO_ROOT / args.output_dir).resolve()
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    with Session() as db:
        result = SignalPerformanceSnapshotRunner(db, artifact_dir=output_dir).run(
            performance_limit=max(1, args.performance_limit),
            forward_integrity_limit=max(1, args.forward_integrity_limit),
        )

    print(json.dumps(json_safe(result), indent=2))


if __name__ == "__main__":
    main()
