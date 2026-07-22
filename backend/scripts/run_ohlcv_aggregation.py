import argparse
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.market import CollectorError, CollectorRun  # noqa: E402
from app.services.ohlcv_aggregation import MARKETS, TIMEFRAMES, OhlcvAggregationService  # noqa: E402
from app.services.run_lock import JsonRunLock  # noqa: E402
from app.services.utils import duration_seconds, json_safe, utcnow  # noqa: E402

LOCK_PATH = ROOT / "data" / "ohlcv_aggregation.lock"
LOCK_STALE_SECONDS = int(os.getenv("MARKETLAB_OHLCV_LOCK_STALE_SECONDS", "3600"))


def run_cycle(
    timeframes: list[str],
    markets: list[str],
    symbols: list[str] | None,
    limit_windows: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    db = SessionLocal()
    run = CollectorRun(
        collector_name="ohlcv_aggregation",
        status="RUNNING",
        started_at=utcnow(),
        finished_at=None,
        target=",".join(f"{market}:{timeframe}" for market in markets for timeframe in timeframes),
        request_count=0,
        inserted_count=0,
        updated_count=0,
        error_count=0,
        duration_seconds=None,
        details_json=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id
    started_at = run.started_at
    try:
        service = OhlcvAggregationService(db)
        results = service.run(
            timeframes=timeframes,
            markets=markets,
            symbols=symbols,
            limit_windows=limit_windows,
            dry_run=dry_run,
        )
        inserted = sum(result.inserted_count for result in results)
        updated = sum(result.updated_count for result in results)
        run.status = "SUCCESS"
        run.inserted_count = inserted
        run.updated_count = updated
        run.details_json = {
            "dry_run": dry_run,
            "limit_windows": limit_windows,
            "results": [
                {
                    "market": result.market,
                    "timeframe": result.timeframe,
                    "symbols": result.symbols,
                    "inserted_count": result.inserted_count,
                    "updated_count": result.updated_count,
                    "status_counts": result.status_counts,
                }
                for result in results
            ],
        }
    except Exception as exc:
        db.rollback()
        persisted_run = db.get(CollectorRun, run_id)
        finished_at = utcnow()
        if persisted_run is not None:
            persisted_run.status = "ERROR"
            persisted_run.error_count = int(persisted_run.error_count or 0) + 1
            persisted_run.finished_at = finished_at
            persisted_run.duration_seconds = duration_seconds(started_at, finished_at)
        db.add(
            CollectorError(
                collector_run_id=run_id,
                collector_name="ohlcv_aggregation",
                symbol=None,
                endpoint=None,
                status_code=None,
                error_type=type(exc).__name__,
                message=str(exc),
                raw_json=None,
                created_at=utcnow(),
            )
        )
        db.commit()
        db.close()
        raise
    else:
        run.finished_at = utcnow()
        run.duration_seconds = duration_seconds(run.started_at, run.finished_at)
        db.commit()
        payload = {
            "id": run.id,
            "status": run.status,
            "duration_seconds": run.duration_seconds,
            "rows_inserted": run.inserted_count,
            "rows_updated": run.updated_count,
            "errors_count": run.error_count,
            "details": run.details_json,
        }
        db.close()
        return json_safe(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local-only OHLCV aggregation from 1m candles.")
    parser.add_argument("--timeframes", nargs="+", choices=sorted(TIMEFRAMES), required=True)
    parser.add_argument("--markets", nargs="+", choices=sorted(MARKETS), required=True)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--limit-windows", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    stop_requested = False

    def request_stop(*_args) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    completed = 0
    while not stop_requested:
        lock = JsonRunLock(LOCK_PATH, "ohlcv_aggregation", stale_seconds=LOCK_STALE_SECONDS)
        if not lock.acquire():
            print(f"{utcnow().isoformat()} ohlcv_aggregation skipped: lock exists at {LOCK_PATH}")
        else:
            try:
                result = run_cycle(
                    args.timeframes,
                    args.markets,
                    args.symbols,
                    args.limit_windows or None,
                    args.dry_run,
                )
                print(json.dumps(result))
            finally:
                lock.release()
        completed += 1
        if completed >= args.cycles:
            break


if __name__ == "__main__":
    main()
