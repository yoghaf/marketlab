import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.market import BinanceFuturesSymbol, BinanceSpotSymbol  # noqa: E402
from app.services.collectors import MarketCollector  # noqa: E402
from app.services.utils import json_safe, utcnow  # noqa: E402


async def run_once(refresh_exchange_info: bool = False) -> dict[str, Any]:
    db = SessionLocal()
    try:
        collector = MarketCollector(db)
        runs = []
        if refresh_exchange_info or db.scalar(select(func.count()).select_from(BinanceFuturesSymbol)) == 0:
            runs.append(await collector.collect_futures_exchange_info())
        if refresh_exchange_info or db.scalar(select(func.count()).select_from(BinanceSpotSymbol)) == 0:
            runs.append(await collector.collect_spot_exchange_info())
        runs.append(await collector.collect_active_top_150())
        health_rows = collector.run_data_health_snapshot()
        return json_safe(
            {
                "status": "SUCCESS" if all(run.status == "SUCCESS" for run in runs) else "PARTIAL",
                "generated_at_utc": utcnow(),
                "health_rows": len(health_rows),
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh MarketLab active universe without running full collectors.")
    parser.add_argument("--refresh-exchange-info", action="store_true")
    args = parser.parse_args()

    configure_logging()
    print(json.dumps(asyncio.run(run_once(refresh_exchange_info=args.refresh_exchange_info))))


if __name__ == "__main__":
    main()
