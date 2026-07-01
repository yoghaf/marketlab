from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.anomaly_signal_factory import DEFAULT_SIGNAL_FACTORY_DIR, SignalFactoryRunner  # noqa: E402
from app.services.multitimeframe_features import DEFAULT_DB_PATH  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MarketLab read-only multi-timeframe signal factory v1.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_SIGNAL_FACTORY_DIR))
    parser.add_argument("--timeframes", nargs="+", default=["15m", "1h", "4h", "24h"])
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()

    result = SignalFactoryRunner(
        db_path=Path(args.db_path),
        output_dir=Path(args.output_dir),
        timeframes=args.timeframes,
        symbol_limit=args.limit_symbols,
    ).run()

    print(
        "signal_factory_v1 complete "
        f"features={result.summary['feature_count']} "
        f"candidates={result.summary['candidate_count']} "
        f"conflicts={result.summary['conflict_count']} "
        f"missing_data={result.summary['missing_data_count']}"
    )


if __name__ == "__main__":
    main()
