import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.collectors import MarketCollector  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run MarketLab collectors once.")
    parser.add_argument(
        "collector",
        nargs="?",
        default="all",
        choices=[
            "all",
            "futures_exchange_info",
            "spot_exchange_info",
            "futures_24h_ticker",
            "spot_24h_ticker",
            "active_top_150",
            "futures_klines_1m",
            "spot_klines_1m",
            "futures_open_interest",
            "futures_mark_funding",
            "futures_book_tickers",
            "spot_book_tickers",
            "data_health",
        ],
    )
    args = parser.parse_args()
    configure_logging()
    db = SessionLocal()
    try:
        collector = MarketCollector(db)
        if args.collector == "all":
            await collector.run_all_once()
        elif args.collector == "data_health":
            collector.run_data_health_snapshot()
        else:
            method_name = "collect_" + args.collector
            result = getattr(collector, method_name)()
            await result
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
