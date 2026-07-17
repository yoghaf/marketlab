from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.market import SignalForwardReturnLog  # noqa: E402
from app.services.structure_zone_shadow import StructureZoneShadowService  # noqa: E402
from app.services.utils import json_safe  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill causal read-only structure-zone snapshots.")
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = list(db.scalars(select(SignalForwardReturnLog).order_by(SignalForwardReturnLog.id)).all())
        pending = [
            row
            for row in rows
            if args.force
            or not isinstance((row.evidence or {}).get("structure_zone_shadow"), dict)
        ]
        if args.limit is not None:
            pending = pending[: max(0, args.limit)]
        updated = 0
        status_counts: dict[str, int] = {}
        batch_size = max(1, min(args.batch_size, 1000))
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            snapshots = StructureZoneShadowService(db).snapshots_for_signals(
                {
                    "signal_id": row.signal_id,
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "signal_timestamp": row.signal_timestamp,
                    "direction": row.direction,
                    "price_at_signal": row.price_at_signal,
                }
                for row in batch
            )
            for row in batch:
                snapshot = snapshots.get(row.signal_id)
                if snapshot is None:
                    continue
                status = str(snapshot.get("status") or "ZONE_UNAVAILABLE")
                status_counts[status] = status_counts.get(status, 0) + 1
                if not args.dry_run:
                    evidence = dict(row.evidence or {})
                    evidence["structure_zone_shadow"] = json_safe(snapshot)
                    row.evidence = evidence
                updated += 1
            if not args.dry_run:
                db.commit()

    print(
        "structure_zone_shadow_backfill complete "
        f"scanned={len(rows)} eligible={len(pending)} updated={updated} "
        f"dry_run={args.dry_run} status_counts={status_counts}"
    )


if __name__ == "__main__":
    main()
