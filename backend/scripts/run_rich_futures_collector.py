import argparse
import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.rich_futures_collectors import RICH_PERIODS, RichFuturesCollector  # noqa: E402
from app.services.utils import utcnow  # noqa: E402

LOCK_PATH = ROOT / "data" / "rich_futures_collector.lock"


class RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        payload = {"pid": os.getpid(), "acquired_at": utcnow().isoformat()}
        os.write(fd, json.dumps(payload).encode("utf-8"))
        os.close(fd)
        return True

    def release(self) -> None:
        if self.path.exists():
            self.path.unlink()


def due_periods(now: datetime) -> list[str]:
    periods = ["5m"] if now.minute % 5 == 0 else []
    if now.minute % 15 == 0:
        periods.append("15m")
    if now.minute == 0:
        periods.append("1h")
    if now.minute == 0 and now.hour % 4 == 0:
        periods.append("4h")
    if now.minute == 0 and now.hour == 0:
        periods.append("1d")
    return periods


async def run_once(periods: list[str], include_funding: bool, symbols_limit: int | None) -> list[dict]:
    db = SessionLocal()
    try:
        collector = RichFuturesCollector(db)
        runs = await collector.run_periods(periods, include_funding=include_funding, symbols_limit=symbols_limit)
        return [
            {
                "id": run.id,
                "collector_name": run.collector_name,
                "target": run.target,
                "status": run.status,
                "duration_seconds": run.duration_seconds,
                "rows_inserted": run.inserted_count,
                "rows_updated": run.updated_count,
                "errors_count": run.error_count,
                "request_count": run.request_count,
            }
            for run in runs
        ]
    finally:
        db.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run MarketLab rich futures collectors with separate cadence.")
    parser.add_argument("--cycles", type=int, default=0, help="0 means run forever.")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--periods", default="", help="Comma-separated periods. Overrides cadence when set.")
    parser.add_argument("--include-funding", action="store_true", help="Collect /fapi/v1/fundingRate in this run.")
    parser.add_argument("--symbols-limit", type=int, default=0, help="Limit active symbols for smoke tests. 0 means all.")
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
        now = datetime.now(UTC)
        periods = [period.strip() for period in args.periods.split(",") if period.strip()] if args.periods else due_periods(now)
        periods = [period for period in periods if period in RICH_PERIODS]
        include_funding = args.include_funding or ("1h" in periods)
        symbols_limit = args.symbols_limit or None

        if not periods and not include_funding:
            print(f"{utcnow().isoformat()} rich_futures skipped: no cadence due")
        else:
            lock = RunLock(LOCK_PATH)
            if not lock.acquire():
                print(f"{utcnow().isoformat()} rich_futures skipped: lock exists at {LOCK_PATH}")
            else:
                try:
                    result = await run_once(periods, include_funding, symbols_limit)
                    print(f"{utcnow().isoformat()} rich_futures complete: {json.dumps(result)}")
                finally:
                    lock.release()

        completed += 1
        if args.cycles and completed >= args.cycles:
            break
        await asyncio.sleep(args.interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
