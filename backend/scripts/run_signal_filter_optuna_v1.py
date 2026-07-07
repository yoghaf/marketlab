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
from app.services.signal_filter_optuna import (  # noqa: E402
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_DOC_PATH,
    SignalFilterOptunaRunner,
)
from app.services.utils import json_safe  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only Optuna filter discovery for Signal Candidate logs.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--doc-path", type=Path, default=DEFAULT_DOC_PATH)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top-trials", type=int, default=20)
    parser.add_argument("--include-watch-only", action="store_true")
    parser.add_argument("--no-position-lock", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = args.db_path if args.db_path.is_absolute() else (REPO_ROOT / args.db_path).resolve()
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
        payload = SignalFilterOptunaRunner(
            db,
            artifact_dir=args.output_dir,
            doc_path=args.doc_path,
            trials=max(1, args.trials),
            seed=args.seed,
            include_watch_only=args.include_watch_only,
            position_lock=not args.no_position_lock,
            top_trials=max(1, args.top_trials),
        ).run()
    summary = {
        "generated_at": payload["generated_at"],
        "results_path": str(args.output_dir / "results.json"),
        "doc_path": str(args.doc_path),
        "lanes": {
            lane: {
                "status": result.get("status"),
                "sample_count": result.get("sample_count", 0),
                "baseline_validation_avg_r": result.get("baseline_validation", {}).get("avg_r_closed"),
                "best_validation_status": (result.get("best_candidate") or {}).get("validation_status"),
                "best_validation_avg_r": (result.get("best_candidate") or {}).get("validation_metrics", {}).get("avg_r_closed"),
                "best_validation_tp": (result.get("best_candidate") or {}).get("validation_metrics", {}).get("tp_count"),
                "best_validation_sl": (result.get("best_candidate") or {}).get("validation_metrics", {}).get("sl_count"),
                "active_filters": (result.get("best_candidate") or {}).get("active_filter_count"),
            }
            for lane, result in payload["lanes"].items()
        },
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
    }
    print(json.dumps(json_safe(summary), indent=2))


if __name__ == "__main__":
    main()
