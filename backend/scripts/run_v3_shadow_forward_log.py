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
from app.services.utils import json_safe  # noqa: E402
from app.services.v3_shadow_forward_artifacts import (  # noqa: E402
    DEFAULT_V3_SHADOW_FORWARD_DIR,
    V3ShadowForwardArtifactRunner,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist read-only V3 shadow forward log artifact.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_V3_SHADOW_FORWARD_DIR)
    parser.add_argument("--include-watch-only", action="store_true")
    parser.add_argument("--no-position-lock", action="store_true")
    parser.add_argument("--min-sample", type=int, default=5)
    parser.add_argument("--limit", type=int, default=100)
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
        payload = V3ShadowForwardArtifactRunner(db, artifact_dir=output_dir).run(
            include_watch_only=args.include_watch_only,
            position_lock=not args.no_position_lock,
            min_sample=max(1, args.min_sample),
            limit=max(1, args.limit),
        )

    summary = payload.get("summary") or {}
    v2 = (summary.get("v2_live") or {}).get("performance") or {}
    v3 = (summary.get("v3_shadow_signal") or {}).get("performance") or {}
    print(
        json.dumps(
            json_safe(
                {
                    "generated_at_utc": payload.get("generated_at_utc"),
                    "output_path": str(output_dir / "summary.json"),
                    "v2_evaluated": v2.get("signals_evaluated", 0),
                    "v2_total_r": v2.get("total_r_closed"),
                    "v3_shadow_signal_count": summary.get("v3_shadow_signal_count", 0),
                    "v3_total_r": v3.get("total_r_closed"),
                    "read": summary.get("read"),
                    "read_only": True,
                    "not_live_signal": True,
                    "not_execution_instruction": True,
                }
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
