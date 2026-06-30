from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.strategy_arena import (  # noqa: E402
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_ATR_MULTIPLIERS,
    DEFAULT_DB_PATH,
    DEFAULT_DOC_PATH,
    DEFAULT_RR_VALUES,
    StrategyArenaRunner,
    parse_decimal_list,
    parse_horizons,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MarketLab Strategy Arena v1 ATR/R all-label study.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Path to SQLite MarketLab database.")
    parser.add_argument("--output-dir", default=str(DEFAULT_ARTIFACT_DIR), help="Directory for JSON artifacts.")
    parser.add_argument("--doc-path", default=str(DEFAULT_DOC_PATH), help="Markdown report output path.")
    parser.add_argument("--min-sample", type=int, default=50, help="Minimum sample for rankable verdicts.")
    parser.add_argument("--horizons", default="15m,1h,4h,24h", help="Comma-separated horizons.")
    parser.add_argument("--atr-mults", default="0.75,1.0,1.25,1.5,2.0", help="Comma-separated ATR multipliers.")
    parser.add_argument("--rr-values", default="1.0,1.5,2.0,2.5,3.0", help="Comma-separated RR values.")
    parser.add_argument("--include-baseline", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    runner = StrategyArenaRunner(
        db_path=Path(args.db_path),
        artifact_dir=Path(args.output_dir),
        doc_path=Path(args.doc_path),
        min_sample=args.min_sample,
        horizons=parse_horizons(args.horizons),
        atr_multipliers=parse_decimal_list(args.atr_mults, DEFAULT_ATR_MULTIPLIERS),
        rr_values=parse_decimal_list(args.rr_values, DEFAULT_RR_VALUES),
        include_baseline=args.include_baseline,
    )
    output = runner.run()
    print(
        json.dumps(
            {
                "status": "SUCCESS",
                "results_count": len(output["results"]["results"]),
                "artifact_dir": str(Path(args.output_dir)),
                "results_file": str(Path(args.output_dir) / "results.json"),
                "leaderboard_file": str(Path(args.output_dir) / "leaderboard.json"),
                "doc_path": str(Path(args.doc_path)),
                "metadata": output["results"]["metadata"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
