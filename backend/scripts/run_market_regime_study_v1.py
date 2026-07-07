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

from app.services.market_regime_study import (  # noqa: E402
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_DOC_PATH,
    MarketRegimeStudyRunner,
)
from app.services.multitimeframe_features import DEFAULT_DB_PATH  # noqa: E402
from app.services.utils import json_safe  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only Market Regime Study v1.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--doc-path", type=Path, default=DEFAULT_DOC_PATH)
    parser.add_argument("--include-watch-only", action="store_true")
    parser.add_argument("--no-position-lock", action="store_true")
    parser.add_argument("--min-sample", type=int, default=10)
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
        payload = MarketRegimeStudyRunner(
            db,
            artifact_dir=args.output_dir,
            doc_path=args.doc_path,
            include_watch_only=args.include_watch_only,
            position_lock=not args.no_position_lock,
            min_sample=max(1, args.min_sample),
        ).run()

    summary = {
        "generated_at": payload["generated_at"],
        "results_path": str(args.output_dir / "results.json"),
        "doc_path": str(args.doc_path),
        "lanes": {
            lane: {
                "sample_count": result.get("sample_count", 0),
                "closed_count": result.get("baseline", {}).get("closed_count", 0),
                "tp_count": result.get("baseline", {}).get("tp_count", 0),
                "sl_count": result.get("baseline", {}).get("sl_count", 0),
                "avg_r_closed": result.get("baseline", {}).get("avg_r_closed"),
                "top_helpful": result.get("top_helpful_regimes", [])[:3],
                "top_harmful": result.get("top_harmful_regimes", [])[:3],
                "interpretation": result.get("interpretation"),
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
