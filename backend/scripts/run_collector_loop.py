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

from sqlalchemy import func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.market import (  # noqa: E402
    BinanceFuturesSymbol,
    BinanceSpotSymbol,
    CollectorError,
    CollectorRun,
)
from app.services.collectors import MarketCollector  # noqa: E402
from app.services.utils import duration_seconds, utcnow  # noqa: E402

LOCK_PATH = ROOT / "data" / "collector_loop.lock"


class RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        payload = {"pid": os.getpid(), "acquired_at": utcnow().isoformat()}
        os.write(self.fd, json.dumps(payload).encode("utf-8"))
        os.close(self.fd)
        self.fd = None
        return True

    def release(self) -> None:
        if self.path.exists():
            self.path.unlink()


async def run_cycle() -> dict[str, Any]:
    db = SessionLocal()
    cycle_run = CollectorRun(
        collector_name="collector_loop",
        status="RUNNING",
        started_at=utcnow(),
        finished_at=None,
        target="continuous_cycle",
        request_count=0,
        inserted_count=0,
        updated_count=0,
        error_count=0,
        duration_seconds=None,
        details_json=None,
    )
    db.add(cycle_run)
    db.commit()
    db.refresh(cycle_run)

    sub_runs: list[CollectorRun] = []
    try:
        collector = MarketCollector(db)
        if db.scalar(select(func.count()).select_from(BinanceFuturesSymbol)) == 0:
            sub_runs.append(await collector.collect_futures_exchange_info())
        if db.scalar(select(func.count()).select_from(BinanceSpotSymbol)) == 0:
            sub_runs.append(await collector.collect_spot_exchange_info())

        sub_runs.append(await collector.collect_active_top_150())
        sub_runs.append(await collector.collect_futures_klines_1m())
        sub_runs.append(await collector.collect_spot_klines_1m())
        sub_runs.append(await collector.collect_futures_open_interest())
        sub_runs.append(await collector.collect_futures_mark_funding())
        sub_runs.append(await collector.collect_futures_book_tickers())
        sub_runs.append(await collector.collect_spot_book_tickers())
        health_rows = collector.run_data_health_snapshot()

        cycle_run.status = "SUCCESS" if all(run.status == "SUCCESS" for run in sub_runs) else "PARTIAL"
        cycle_run.request_count = sum(run.request_count for run in sub_runs)
        cycle_run.inserted_count = sum(run.inserted_count for run in sub_runs)
        cycle_run.updated_count = sum(run.updated_count for run in sub_runs)
        cycle_run.error_count = sum(run.error_count for run in sub_runs)
        cycle_run.details_json = {
            "sub_run_ids": [run.id for run in sub_runs],
            "health_rows": len(health_rows),
            "interval_seconds": settings.collector_interval_seconds,
        }
    except Exception as exc:
        cycle_run.status = "ERROR"
        cycle_run.error_count += 1
        db.add(
            CollectorError(
                collector_run_id=cycle_run.id,
                collector_name="collector_loop",
                symbol=None,
                endpoint=None,
                status_code=getattr(exc, "status_code", None),
                error_type=type(exc).__name__,
                message=str(exc),
                raw_json=getattr(exc, "payload", None) if isinstance(getattr(exc, "payload", None), dict) else None,
                created_at=utcnow(),
            )
        )
        raise
    finally:
        cycle_run.finished_at = utcnow()
        cycle_run.duration_seconds = duration_seconds(cycle_run.started_at, cycle_run.finished_at)
        db.commit()
        result = {
            "id": cycle_run.id,
            "status": cycle_run.status,
            "duration_seconds": cycle_run.duration_seconds,
            "rows_inserted": cycle_run.inserted_count,
            "rows_updated": cycle_run.updated_count,
            "errors_count": cycle_run.error_count,
            "request_count": cycle_run.request_count,
        }
        db.close()
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run MarketLab continuous collector loop.")
    parser.add_argument("--interval-seconds", type=int, default=settings.collector_interval_seconds)
    parser.add_argument("--cycles", type=int, default=0, help="0 means run forever.")
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
        lock = RunLock(LOCK_PATH)
        if not lock.acquire():
            print(f"{utcnow().isoformat()} collector_loop skipped: lock exists at {LOCK_PATH}")
            completed += 1
            if args.cycles and completed >= args.cycles:
                break
            if args.interval_seconds:
                await asyncio.sleep(args.interval_seconds)
        else:
            started = utcnow()
            try:
                result = await run_cycle()
                print(f"{utcnow().isoformat()} collector_loop cycle complete: {json.dumps(result)}")
            finally:
                lock.release()

            completed += 1
            if args.cycles and completed >= args.cycles:
                break

            elapsed = (utcnow() - started).total_seconds()
            sleep_seconds = max(0, args.interval_seconds - elapsed)
            if sleep_seconds:
                await asyncio.sleep(sleep_seconds)


if __name__ == "__main__":
    asyncio.run(main())
