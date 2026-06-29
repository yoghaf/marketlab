from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline15m, FuturesKline1m, MarketlabActiveUniverse
from app.services.ohlcv_aggregation import OhlcvAggregationService


class OhlcvAggregationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False, expire_on_commit=False)
        self.db = self.Session()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        self.db.add(
            MarketlabActiveUniverse(
                symbol="TESTUSDT",
                rank=1,
                quote_volume=Decimal("1000"),
                collection_tier="FULL_ACTIVE",
                is_full_active=True,
                is_light_watch=False,
                is_signal_eligible=False,
                is_active=True,
                entered_at=now,
                exited_at=None,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_complete_15m_window_is_ready_with_correct_ohlcv(self) -> None:
        start = datetime(2020, 1, 1, 0, 0, tzinfo=UTC)
        self._insert_1m_rows(start, count=15)

        OhlcvAggregationService(self.db).run(timeframes=["15m"], markets=["futures"])
        row = self.db.scalar(select(FuturesKline15m).where(FuturesKline15m.symbol == "TESTUSDT"))

        self.assertIsNotNone(row)
        self.assertEqual(row.open, Decimal("100"))
        self.assertEqual(row.high, Decimal("119"))
        self.assertEqual(row.low, Decimal("76"))
        self.assertEqual(row.close, Decimal("115"))
        self.assertEqual(row.volume, Decimal("120"))
        self.assertEqual(row.quote_volume, Decimal("1200"))
        self.assertEqual(row.number_of_trades, 105)
        self.assertEqual(row.taker_buy_base_volume, Decimal("7.5"))
        self.assertEqual(row.taker_buy_quote_volume, Decimal("75"))
        self.assertEqual(row.taker_sell_base_volume, Decimal("112.5"))
        self.assertEqual(row.taker_sell_quote_volume, Decimal("1125"))
        self.assertEqual(row.actual_1m_count, 15)
        self.assertEqual(row.expected_1m_count, 15)
        self.assertEqual(row.missing_1m_count, 0)
        self.assertEqual(row.aggregation_status, "AGG_READY")

    def test_incomplete_15m_window_is_not_ready(self) -> None:
        start = datetime(2020, 1, 1, 0, 0, tzinfo=UTC)
        self._insert_1m_rows(start, count=15, skip_minutes={7})

        OhlcvAggregationService(self.db).run(timeframes=["15m"], markets=["futures"])
        row = self.db.scalar(select(FuturesKline15m).where(FuturesKline15m.symbol == "TESTUSDT"))

        self.assertIsNotNone(row)
        self.assertEqual(row.actual_1m_count, 14)
        self.assertEqual(row.expected_1m_count, 15)
        self.assertEqual(row.missing_1m_count, 1)
        self.assertEqual(row.aggregation_status, "AGG_INCOMPLETE")
        self.assertGreater(row.volume, Decimal("0"))

    def test_unclosed_window_cannot_be_ready(self) -> None:
        future_start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
        self._insert_1m_rows(future_start, count=15)

        OhlcvAggregationService(self.db).run(timeframes=["15m"], markets=["futures"])
        rows = self.db.scalars(select(FuturesKline15m).where(FuturesKline15m.symbol == "TESTUSDT")).all()

        self.assertTrue(all(row.aggregation_status != "AGG_READY" for row in rows))

    def _insert_1m_rows(self, start: datetime, count: int, skip_minutes: set[int] | None = None) -> None:
        skip_minutes = skip_minutes or set()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        for minute in range(count):
            if minute in skip_minutes:
                continue
            open_time = start + timedelta(minutes=minute)
            self.db.add(
                FuturesKline1m(
                    symbol="TESTUSDT",
                    open_time=open_time,
                    close_time=open_time + timedelta(minutes=1),
                    open_price=Decimal(100 + minute),
                    high_price=Decimal(105 + minute),
                    low_price=Decimal(90 - minute),
                    close_price=Decimal(101 + minute),
                    volume=Decimal(minute + 1),
                    quote_volume=Decimal((minute + 1) * 10),
                    trade_count=minute,
                    taker_buy_base_volume=Decimal("0.5"),
                    taker_buy_quote_volume=Decimal("5"),
                    raw_json=[],
                    created_at=now,
                    updated_at=now,
                )
            )
        self.db.commit()


if __name__ == "__main__":
    unittest.main()
