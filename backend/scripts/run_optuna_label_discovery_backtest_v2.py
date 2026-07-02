from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.multitimeframe_features import DEFAULT_DB_PATH, json_safe  # noqa: E402
from app.services.optuna_label_discovery_backtest import (  # noqa: E402
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_DOC_PATH,
    OptunaLabelDiscoveryBacktestRunner,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only locked-rule Optuna label discovery backtest v2.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--doc-path", type=Path, default=DEFAULT_DOC_PATH)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-token-results-per-setup", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = OptunaLabelDiscoveryBacktestRunner(
        db_path=args.db_path,
        artifact_dir=args.output_dir,
        doc_path=args.doc_path,
        trials=args.trials,
        seed=args.seed,
        max_token_results_per_setup=args.max_token_results_per_setup,
    ).run()
    summary = {
        "generated_at": payload["generated_at"],
        "results_path": str(args.output_dir / "results.json"),
        "token_results_path": str(args.output_dir / "token_results.json"),
        "doc_path": str(args.doc_path),
        "coverage": payload["coverage"],
        "setups": {
            setup: {
                "identified": result.get("market_identified_metrics", {}).get("sample_count", 0),
                "median_directional_return_4h": result.get("market_identified_metrics", {}).get(
                    "median_directional_return_4h"
                ),
                "favorable_count": result.get("market_identified_metrics", {}).get("favorable_count", 0),
                "adverse_count": result.get("market_identified_metrics", {}).get("adverse_count", 0),
                "status": result.get("market_validation_status", result.get("status")),
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
