from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
import json
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline15m, MarketCandidateOutcome15m, MarketSignalCandidateReadonly15m
from app.services.outcome_tracker_15m import OutcomeTracker15mService
from app.services.utils import json_safe


class OutcomeTracker15mTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False, expire_on_commit=False)
        self.db = self.Session()
        self.now = datetime(2026, 1, 1, tzinfo=UTC)
        self.window_open = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        self.window_close = self.window_open + timedelta(minutes=15)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_json_safe_handles_nested_datetime_decimal_and_tuple(self) -> None:
        payload = {
            "dt": self.window_close,
            "date": date(2026, 1, 2),
            "time": time(3, 4, 5),
            "decimal": Decimal("1.23"),
            "nested": [{"values": (self.window_open, Decimal("4.56"))}],
        }

        safe = json_safe(payload)

        json.dumps(safe)
        self.assertEqual(safe["dt"], "2026-01-01T00:15:00+00:00")
        self.assertEqual(safe["date"], "2026-01-02")
        self.assertEqual(safe["time"], "03:04:05")
        self.assertEqual(safe["decimal"], "1.23")
        self.assertEqual(safe["nested"][0]["values"], ["2026-01-01T00:00:00+00:00", "4.56"])

    def test_incomplete_outcome_persists_json_safe_missing_windows(self) -> None:
        self._insert_candidate()
        self._insert_kline(self.window_open, self.window_close)
        self._insert_kline(
            self.window_open + timedelta(hours=4),
            self.window_close + timedelta(hours=4),
        )
        self.db.commit()

        result = OutcomeTracker15mService(self.db).run()
        row = self.db.scalar(select(MarketCandidateOutcome15m).where(MarketCandidateOutcome15m.symbol == "TESTUSDT"))

        self.assertEqual(result.status_counts["OUTCOME_INCOMPLETE"], 1)
        self.assertIsNotNone(row)
        self.assertEqual(row.outcome_status, "OUTCOME_INCOMPLETE")
        self.assertGreater(len(row.missing_window_list), 0)
        self.assertIsInstance(row.missing_window_list[0]["expected_close_time"], str)
        self.assertIsInstance(row.evidence["horizons"]["15m"]["required_close_times"][0], str)
        json.dumps(row.missing_window_list)
        json.dumps(row.evidence)

    def _insert_candidate(self) -> None:
        self.db.add(
            MarketSignalCandidateReadonly15m(
                symbol="TESTUSDT",
                window_open_time=self.window_open,
                window_close_time=self.window_close,
                classifier_status="CLASSIFIER_PARTIAL",
                candidate_type="NO_SIGNAL_CONTEXT",
                candidate_direction="MIXED_CONTEXT",
                confidence_level="LOW",
                confidence_score=Decimal("0.1000"),
                evidence={"test": True},
                block_reason=None,
                not_entry_signal=True,
                created_at=self.now,
                updated_at=self.now,
            )
        )

    def _insert_kline(self, open_time: datetime, close_time: datetime) -> None:
        self.db.add(
            FuturesKline15m(
                symbol="TESTUSDT",
                open_time=open_time,
                close_time=close_time,
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("95"),
                close=Decimal("101"),
                volume=Decimal("10"),
                quote_volume=Decimal("1000"),
                number_of_trades=10,
                taker_buy_base_volume=Decimal("4"),
                taker_buy_quote_volume=Decimal("400"),
                taker_sell_base_volume=Decimal("6"),
                taker_sell_quote_volume=Decimal("600"),
                source_interval="1m",
                expected_1m_count=15,
                actual_1m_count=15,
                missing_1m_count=0,
                aggregation_status="AGG_READY",
                created_at=self.now,
                updated_at=self.now,
            )
        )


if __name__ == "__main__":
    unittest.main()
