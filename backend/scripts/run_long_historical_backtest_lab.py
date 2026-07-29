from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.long_historical_backtest_lab import (  # noqa: E402
    DEFAULT_LONG_HISTORICAL_BACKTEST_PATH,
    LongHistoricalBacktestLab,
)
from app.services.multitimeframe_features import DEFAULT_DB_PATH  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only LONG 1h historical backtest from DB candles.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_LONG_HISTORICAL_BACKTEST_PATH)
    parser.add_argument("--active-only", action="store_true")
    parser.add_argument("--no-position-lock", action="store_true")
    parser.add_argument("--since-days", type=int, default=None)
    parser.add_argument("--latest-limit", type=int, default=300)
    args = parser.parse_args()

    db_path = args.db_path if args.db_path.is_absolute() else (REPO_ROOT / args.db_path).resolve()
    output_path = args.output_path if args.output_path.is_absolute() else (REPO_ROOT / args.output_path).resolve()
    report = LongHistoricalBacktestLab(db_path).run(
        output_path=output_path,
        active_only=args.active_only,
        position_lock=not args.no_position_lock,
        since_days=max(1, args.since_days) if args.since_days is not None else None,
        latest_limit=max(1, args.latest_limit),
    )
    print(
        "long_historical_backtest_lab complete "
        f"symbols={report['coverage']['symbol_count']} "
        f"raw_candidates={report['coverage']['raw_long_candidate_count_before_lock']} "
        f"events={report['coverage']['events_evaluated_after_lock']} "
        f"read={report['summary']['read']} "
        f"output={output_path}"
    )


if __name__ == "__main__":
    main()
