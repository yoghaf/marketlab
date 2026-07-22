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
from app.services.strategy_optimization_artifacts import (  # noqa: E402
    DEFAULT_STRATEGY_OPTIMIZATION_ARTIFACT_DIR,
    StrategyOptimizationArtifactRunner,
    parse_lane_pairs,
)
from app.services.utils import json_safe  # noqa: E402

RETIRED_MID_LONG_ARTIFACTS = (
    "mid_long_lab63.json",
    "mid_long_lab64.json",
    "mid_long_lab65.json",
    "mid_long_lab66.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Precompute read-only Strategy Optimization artifacts.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_STRATEGY_OPTIMIZATION_ARTIFACT_DIR)
    parser.add_argument("--include-watch-only", action="store_true")
    parser.add_argument("--no-position-lock", action="store_true")
    parser.add_argument("--min-sample", type=int, default=20)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument(
        "--lane",
        action="append",
        help="Lane pair STAGE:TIMEFRAME. Can be repeated. Default: MID_SHORT:1h, EARLY_LONG:15m, EARLY_SHORT:15m.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = args.db_path if args.db_path.is_absolute() else (REPO_ROOT / args.db_path).resolve()
    output_dir = args.output_dir if args.output_dir.is_absolute() else (REPO_ROOT / args.output_dir).resolve()
    lane_pairs = parse_lane_pairs(args.lane)
    for filename in RETIRED_MID_LONG_ARTIFACTS:
        (output_dir / filename).unlink(missing_ok=True)
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
        payload = StrategyOptimizationArtifactRunner(db, artifact_dir=output_dir).run(
            include_watch_only=args.include_watch_only,
            position_lock=not args.no_position_lock,
            min_sample=max(1, args.min_sample),
            limit=max(20, args.limit),
            lane_pairs=lane_pairs,
        )

    summary = {
        "generated_at_utc": payload.get("generated_at_utc"),
        "output_path": str(output_dir / "summary.json"),
        "lane_count": len(payload.get("optimization_by_lane") or {}),
        "regime_count": len(payload.get("regime_by_lane") or {}),
        "v3_candidate_count": (payload.get("v3_shadow") or {}).get("v3_candidate_count", 0),
        "monitor_more_count": (payload.get("v3_shadow") or {}).get("monitor_more_count", 0),
        "errors": payload.get("errors") or [],
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
    }
    print(json.dumps(json_safe(summary), indent=2))


if __name__ == "__main__":
    main()
