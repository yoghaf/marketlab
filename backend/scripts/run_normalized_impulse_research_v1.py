from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.multitimeframe_features import DEFAULT_DB_PATH, json_safe  # noqa: E402
from app.services.normalized_impulse_research import (  # noqa: E402
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_DOC_PATH,
    NormalizedImpulseResearchRunner,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only per-symbol normalized impulse research v1.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--doc-path", type=Path, default=DEFAULT_DOC_PATH)
    parser.add_argument("--symbol-limit", type=int, default=None)
    parser.add_argument("--max-rows-per-setup", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = NormalizedImpulseResearchRunner(
        db_path=args.db_path,
        artifact_dir=args.output_dir,
        doc_path=args.doc_path,
        symbol_limit=args.symbol_limit,
        max_rows_per_setup=args.max_rows_per_setup,
    ).run()
    summary = {
        "generated_at": payload["generated_at"],
        "results_path": str(args.output_dir / "results.json"),
        "token_results_path": str(args.output_dir / "token_results.json"),
        "doc_path": str(args.doc_path),
        "coverage": payload["coverage"],
        "setup_results": {
            setup: {
                "source_candidate_count": row["source_candidate_count"],
                "evaluated_count": row["evaluated_count"],
                "tp_first": row["outcome_counts"].get("TP_FIRST", 0),
                "sl_first": row["outcome_counts"].get("SL_FIRST", 0),
                "median_realized_r": row["median_realized_r"],
                "verdict": row["read_only_verdict"],
            }
            for setup, row in payload["setup_results"].items()
        },
        "read_only": True,
        "not_live_signal": True,
        "not_execution_instruction": True,
    }
    print(json.dumps(json_safe(summary), indent=2))


if __name__ == "__main__":
    main()
