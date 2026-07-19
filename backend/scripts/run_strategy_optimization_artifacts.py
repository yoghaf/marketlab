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
from app.services.mid_long_geometry_validation import (  # noqa: E402
    MidLongGeometryValidationArtifactRunner,
    MidLongGeometryValidationService,
)
from app.services.mid_long_evidence_separation import (  # noqa: E402
    MidLongEvidenceSeparationArtifactRunner,
)
from app.services.mid_long_failure_anatomy import (  # noqa: E402
    MidLongFailureAnatomyArtifactRunner,
)
from app.services.strategy_optimization_artifacts import (  # noqa: E402
    DEFAULT_STRATEGY_OPTIMIZATION_ARTIFACT_DIR,
    StrategyOptimizationArtifactRunner,
    parse_lane_pairs,
)
from app.services.utils import json_safe  # noqa: E402


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
        help="Lane pair STAGE:TIMEFRAME. Can be repeated. Default: MID_SHORT:1h, MID_LONG:1h, EARLY_LONG:15m, EARLY_SHORT:15m.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = args.db_path if args.db_path.is_absolute() else (REPO_ROOT / args.db_path).resolve()
    output_dir = args.output_dir if args.output_dir.is_absolute() else (REPO_ROOT / args.output_dir).resolve()
    lane_pairs = parse_lane_pairs(args.lane)
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
        prepared_mid_long = MidLongGeometryValidationService(db).prepare_dataset(
            include_watch_only=args.include_watch_only,
        )
        lab63 = MidLongGeometryValidationArtifactRunner(
            db,
            artifact_path=output_dir / "mid_long_lab63.json",
        ).run(
            include_watch_only=args.include_watch_only,
            position_lock=not args.no_position_lock,
            min_validation_sample=max(1, args.min_sample),
            limit=max(20, args.limit),
            prepared_dataset=prepared_mid_long,
        )
        lab64 = MidLongEvidenceSeparationArtifactRunner(
            db,
            artifact_path=output_dir / "mid_long_lab64.json",
        ).run(
            include_watch_only=args.include_watch_only,
            position_lock=not args.no_position_lock,
            min_group_sample=max(1, args.min_sample),
            limit=max(20, args.limit),
            prepared_dataset=prepared_mid_long,
        )
        lab65 = MidLongFailureAnatomyArtifactRunner(
            db,
            artifact_path=output_dir / "mid_long_lab65.json",
        ).run(
            include_watch_only=args.include_watch_only,
            position_lock=not args.no_position_lock,
            min_failure_sample=max(1, args.min_sample),
            limit=max(20, args.limit),
            prepared_dataset=prepared_mid_long,
        )

    summary = {
        "generated_at_utc": payload.get("generated_at_utc"),
        "output_path": str(output_dir / "summary.json"),
        "lane_count": len(payload.get("optimization_by_lane") or {}),
        "regime_count": len(payload.get("regime_by_lane") or {}),
        "v3_candidate_count": (payload.get("v3_shadow") or {}).get("v3_candidate_count", 0),
        "monitor_more_count": (payload.get("v3_shadow") or {}).get("monitor_more_count", 0),
        "mid_long_lab63_path": str(output_dir / "mid_long_lab63.json"),
        "mid_long_lab63_source_count": (lab63.get("split") or {}).get("source_signal_count", 0),
        "mid_long_lab63_reference_policy": lab63.get("reference_policy"),
        "mid_long_lab63_best_observed_policy": (
            (lab63.get("best_observed_policy") or {}).get("policy_id")
        ),
        "mid_long_lab64_path": str(output_dir / "mid_long_lab64.json"),
        "mid_long_lab64_verdict": lab64.get("verdict"),
        "mid_long_lab64_stable_field_count": (
            (lab64.get("field_summary") or {}).get("stable_field_count", 0)
        ),
        "mid_long_lab65_path": str(output_dir / "mid_long_lab65.json"),
        "mid_long_lab65_verdict": lab65.get("verdict"),
        "mid_long_lab65_failure_count": (
            ((lab65.get("failure_summary") or {}).get("all") or {}).get("count", 0)
        ),
        "mid_long_lab65_dominant_cause": (
            (lab65.get("failure_summary") or {}).get("dominant_cause")
        ),
        "errors": payload.get("errors") or [],
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
    }
    print(json.dumps(json_safe(summary), indent=2))


if __name__ == "__main__":
    main()
