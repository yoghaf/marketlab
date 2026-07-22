import argparse
import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.market import CollectorRun  # noqa: E402
from app.services.collectors import MarketCollector  # noqa: E402
from app.services.run_lock import JsonRunLock  # noqa: E402
from app.services.utils import json_safe, utcnow  # noqa: E402

LOCK_PATH = ROOT / "data" / "kline_collector.lock"
LOCK_STALE_SECONDS = int(os.getenv("MARKETLAB_KLINE_LOCK_STALE_SECONDS", "1800"))


async def run_cycle(markets: list[str]) -> dict[str, Any]:
    db = SessionLocal()
    try:
        collector = MarketCollector(db)
        runs: list[CollectorRun] = []
        if "futures" in markets:
            runs.append(await collector.collect_futures_klines_1m())
        if "spot" in markets:
            runs.append(await collector.collect_spot_klines_1m())

        return json_safe(
            {
                "status": "SUCCESS" if all(run.status == "SUCCESS" for run in runs) else "PARTIAL",
                "runs": [
                    {
                        "id": run.id,
                        "collector_name": run.collector_name,
                        "status": run.status,
                        "duration_seconds": run.duration_seconds,
                        "rows_inserted": run.inserted_count,
                        "rows_updated": run.updated_count,
                        "errors_count": run.error_count,
                        "request_count": run.request_count,
                        "details": run.details_json,
                    }
                    for run in runs
                ],
            }
        )
    finally:
        db.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run MarketLab gap-safe 1m kline collectors.")
    parser.add_argument("--markets", nargs="+", choices=["futures", "spot"], default=["futures", "spot"])
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval-seconds", type=int, default=settings.collector_interval_seconds)
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
        lock = JsonRunLock(LOCK_PATH, "kline_collector", stale_seconds=LOCK_STALE_SECONDS)
        if not lock.acquire():
            print(f"{utcnow().isoformat()} kline_collector skipped: lock exists at {LOCK_PATH}")
            completed += 1
            if completed >= args.cycles:
                break
            if args.interval_seconds:
                await asyncio.sleep(args.interval_seconds)
        else:
            started = utcnow()
            try:
                result = await run_cycle(args.markets)
                print(json.dumps(result))
            finally:
                lock.release()

            completed += 1
            if completed >= args.cycles:
                break

            elapsed = (utcnow() - started).total_seconds()
            sleep_seconds = max(0, args.interval_seconds - elapsed)
            if sleep_seconds:
                await asyncio.sleep(sleep_seconds)


if __name__ == "__main__":
    asyncio.run(main())
