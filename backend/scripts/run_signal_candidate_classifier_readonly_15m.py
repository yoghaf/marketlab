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
from app.services.signal_candidate_classifier_readonly_15m import (  # noqa: E402
    SignalCandidateClassifierReadonly15mService,
)
from app.services.run_lock import JsonRunLock  # noqa: E402
from app.services.utils import duration_seconds, json_safe, utcnow  # noqa: E402

LOCK_PATH = ROOT / "data" / "signal_candidate_classifier_readonly_15m.lock"


class RunLock:
    def __init__(self, path: Path) -> None:
        self.lock = JsonRunLock(path, "signal_candidate_classifier_readonly_15m", stale_seconds=3600)

    def acquire(self) -> bool:
        return self.lock.acquire()

    def release(self) -> None:
        self.lock.release()


def run_cycle(symbols: list[str] | None, limit_windows: int | None, dry_run: bool) -> dict[str, Any]:
    db = SessionLocal()
    run = CollectorRun(
        collector_name="signal_candidate_classifier_readonly_15m",
        status="RUNNING",
        started_at=utcnow(),
        finished_at=None,
        target="15m",
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
    try:
        service = SignalCandidateClassifierReadonly15mService(db)
        result = service.run(symbols=symbols, limit_windows=limit_windows, dry_run=dry_run)
        run.status = "SUCCESS"
        run.inserted_count = result.inserted_count
        run.updated_count = result.updated_count
        run.details_json = {
            "dry_run": dry_run,
            "symbols": result.symbols,
            "limit_windows": limit_windows,
            "status_counts": result.status_counts,
        }
    except Exception as exc:
        run.status = "ERROR"
        run.error_count += 1
        db.add(
            CollectorError(
                collector_run_id=run.id,
                collector_name="signal_candidate_classifier_readonly_15m",
                symbol=None,
                endpoint=None,
                status_code=None,
                error_type=type(exc).__name__,
                message=str(exc),
                raw_json=None,
                created_at=utcnow(),
            )
        )
        raise
    finally:
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
    parser = argparse.ArgumentParser(description="Build read-only 15m signal candidate classifications.")
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
        lock = RunLock(LOCK_PATH)
        if not lock.acquire():
            print(f"{utcnow().isoformat()} signal_candidate_classifier_readonly_15m skipped: lock exists at {LOCK_PATH}")
        else:
            try:
                result = run_cycle(args.symbols, args.limit_windows or None, args.dry_run)
                print(json.dumps(result))
            finally:
                lock.release()
        completed += 1
        if completed >= args.cycles:
            break


if __name__ == "__main__":
    main()
