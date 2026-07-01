from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.phase6_readiness_audit import (  # noqa: E402
    DEFAULT_PHASE6_DIR,
    DEFAULT_SIGNAL_FACTORY_DIR,
    DEFAULT_STRATEGY_ARENA_DIR,
    Phase6ReadinessAuditRunner,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MarketLab Phase 6 read-only readiness and edge audit.")
    parser.add_argument("--signal-factory-dir", default=str(DEFAULT_SIGNAL_FACTORY_DIR))
    parser.add_argument("--strategy-arena-dir", default=str(DEFAULT_STRATEGY_ARENA_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_PHASE6_DIR))
    args = parser.parse_args()

    result = Phase6ReadinessAuditRunner(
        signal_factory_dir=Path(args.signal_factory_dir),
        strategy_arena_dir=Path(args.strategy_arena_dir),
        output_dir=Path(args.output_dir),
    ).run()
    print(
        "phase6 readiness audit complete "
        f"status={result.readiness_summary.get('phase6_status')} "
        f"decision={result.phase7_candidate_decision.get('phase7_decision')} "
        f"approved={len(result.phase7_candidate_decision.get('approved_candidates', []))} "
        f"watchlist={len(result.phase7_candidate_decision.get('watchlist_candidates', []))}"
    )


if __name__ == "__main__":
    main()
