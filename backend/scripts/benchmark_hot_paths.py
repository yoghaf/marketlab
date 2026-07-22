from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from sqlalchemy import event


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.routes import data_health  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.services.anomaly_signal_factory import DEFAULT_SIGNAL_FACTORY_DIR  # noqa: E402
from app.services.live_candidate_scanner import LiveCandidateScannerService  # noqa: E402
from app.services.utils import json_safe  # noqa: E402


def benchmark_call(name: str, callback: Callable[[], Any]) -> dict[str, Any]:
    query_count = 0

    def count_query(*_args: Any, **_kwargs: Any) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", count_query)
    started = perf_counter()
    try:
        payload = callback()
    finally:
        elapsed = perf_counter() - started
        event.remove(engine, "before_cursor_execute", count_query)

    serialized = json.dumps(json_safe(payload), separators=(",", ":"), ensure_ascii=True)
    return {
        "target": name,
        "elapsed_seconds": round(elapsed, 4),
        "sql_statement_count": query_count,
        "payload_bytes": len(serialized.encode("utf-8")),
    }


def run(targets: list[str], scanner_limit: int) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with SessionLocal() as db:
        if "data-health" in targets:
            results.append(benchmark_call("data-health", lambda: data_health(db)))
        if "scanner" in targets:
            service = LiveCandidateScannerService(
                db,
                signal_factory_artifact_dir=DEFAULT_SIGNAL_FACTORY_DIR,
            )
            results.append(
                benchmark_call(
                    "scanner",
                    lambda: service.list_live(limit=scanner_limit),
                )
            )
    return {"results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark MarketLab read-only API hot paths.")
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=("data-health", "scanner"),
        default=("data-health", "scanner"),
    )
    parser.add_argument("--scanner-limit", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(run(args.targets, max(1, min(args.scanner_limit, 500))), indent=2))


if __name__ == "__main__":
    main()
