import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.market import CollectorError  # noqa: E402
from app.services.native_ohlcv_backfill import (  # noqa: E402
    MARKETS,
    TIMEFRAME_CONFIG,
    NativeOhlcvBackfillService,
    finish_collector_run,
    start_collector_run,
)
from app.services.utils import json_safe, utcnow  # noqa: E402

LOCK_PATH = ROOT / "data" / "native_ohlcv_backfill.lock"
LOCK_STALE_SECONDS = int(os.getenv("MARKETLAB_NATIVE_OHLCV_LOCK_STALE_SECONDS", "3600"))


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
        try:
            if self.path.exists():
                self.path.unlink()
        except FileNotFoundError:
            pass

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
        self.path.unlink(missing_ok=True)
        print(f"{utcnow().isoformat()} native_ohlcv_backfill removed stale lock at {self.path}: {reason}")
        return True

    def _lock_pid(self) -> int | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
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


async def run_once(args: argparse.Namespace) -> dict:
    db = SessionLocal()
    run = start_collector_run(
        db,
        "native_ohlcv_backfill",
        ",".join(f"{market}:{timeframe}" for market in args.markets for timeframe in args.timeframes),
    )
    try:
        service = NativeOhlcvBackfillService(db)
        payload = await service.run(
            timeframes=args.timeframes,
            markets=args.markets,
            days=args.days,
            symbols=args.symbols,
            limit_symbols=args.limit_symbols,
            dry_run=args.dry_run,
        )
        finish_collector_run(db, run, payload, "SUCCESS")
        payload["collector_run_id"] = run.id
        payload["status"] = "SUCCESS"
        return json_safe(payload)
    except Exception as exc:
        db.rollback()
        db.add(
            CollectorError(
                collector_run_id=run.id,
                collector_name="native_ohlcv_backfill",
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
        finish_collector_run(db, run, {"inserted_count": 0, "updated_count": 0, "error_count": 1}, "ERROR")
        raise
    finally:
        db.close()


async def main_async(args: argparse.Namespace) -> None:
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
            print(f"{utcnow().isoformat()} native_ohlcv_backfill skipped: lock exists at {LOCK_PATH}")
        else:
            try:
                result = await run_once(args)
                print(json.dumps(result))
            finally:
                lock.release()
        completed += 1
        if completed >= args.cycles:
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill closed native Binance OHLCV candles into aggregate tables.")
    parser.add_argument("--timeframes", nargs="+", choices=sorted(TIMEFRAME_CONFIG), default=["24h"])
    parser.add_argument("--markets", nargs="+", choices=sorted(MARKETS), default=["futures"])
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--limit-symbols", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    configure_logging()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
