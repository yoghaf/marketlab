import argparse
import asyncio
import json
import os
import signal
import sys
import time
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
from app.services.utils import json_safe, utcnow  # noqa: E402

LOCK_PATH = ROOT / "data" / "kline_collector.lock"
LOCK_STALE_SECONDS = int(os.getenv("MARKETLAB_KLINE_LOCK_STALE_SECONDS", "1800"))


class RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not self._remove_stale_lock():
                return False
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
        os.write(fd, json.dumps({"pid": os.getpid(), "acquired_at": utcnow().isoformat()}).encode("utf-8"))
        os.close(fd)
        return True

    def release(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def _remove_stale_lock(self) -> bool:
        pid = self._lock_pid()
        age_seconds = max(0.0, time.time() - self.path.stat().st_mtime)
        if pid is not None and self._process_exists(pid):
            return False
        if pid is not None:
            reason = f"pid {pid} is not running"
        elif age_seconds >= LOCK_STALE_SECONDS:
            reason = f"age {age_seconds:.0f}s exceeds {LOCK_STALE_SECONDS}s"
        else:
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        print(f"{utcnow().isoformat()} kline_collector removed stale lock at {self.path}: {reason}")
        return True

    def _lock_pid(self) -> int | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            pid = int(payload.get("pid"))
        except (TypeError, ValueError):
            return None
        return pid if pid > 0 else None

    @staticmethod
    def _process_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


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
        lock = RunLock(LOCK_PATH)
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
