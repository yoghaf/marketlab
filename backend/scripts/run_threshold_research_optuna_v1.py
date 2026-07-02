from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.threshold_research_optuna import (  # noqa: E402
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_DOC_PATH,
    OptunaThresholdResearchRunner,
)
from app.services.multitimeframe_features import DEFAULT_DB_PATH, json_safe  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only Optuna threshold research for MarketLab candidates.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--doc-path", type=Path, default=DEFAULT_DOC_PATH)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runner = OptunaThresholdResearchRunner(
        db_path=args.db_path,
        artifact_dir=args.output_dir,
        doc_path=args.doc_path,
        trials=args.trials,
        seed=args.seed,
    )
    payload = runner.run()
    summary = {
        "generated_at": payload["generated_at"],
        "results_path": str(args.output_dir / "results.json"),
        "doc_path": str(args.doc_path),
        "setups": {
            setup: {
                "row_count": result.get("row_count", 0),
                "selected_sample": result.get("all_selected_metrics", {}).get("sample_count", 0),
                "validation_sample": result.get("validation_metrics", {}).get("sample_count", 0),
                "validation_status": result.get("validation_status", result.get("status")),
                "validation_median_directional_return_4h": result.get("validation_metrics", {}).get(
                    "median_directional_return_4h"
                ),
            }
            for setup, result in payload["setups"].items()
        },
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
    }
    print(json.dumps(json_safe(summary), indent=2))


if __name__ == "__main__":
    main()
