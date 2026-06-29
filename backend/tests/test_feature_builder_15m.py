from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import (
    FuturesKline15m,
    MarketFeature15m,
    MarketStateAlignment,
    MarketlabActiveUniverse,
    RichFutures5mAlignment,
    SpotKline15m,
)
from app.services.feature_builder_15m import FeatureBuilder15mService


class FeatureBuilder15mTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False, expire_on_commit=False)
        self.db = self.Session()
        self.now = datetime(2026, 1, 1, tzinfo=UTC)
        self.window_open = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        self.window_close = self.window_open + timedelta(minutes=15)
        self._insert_universe()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_complete_ready_input_creates_feature_ready(self) -> None:
        self._insert_inputs(funding_status="FUNDING_ALIGNED")

        FeatureBuilder15mService(self.db).run()
        row = self._feature()

        self.assertEqual(row.feature_status, "FEATURE_READY")
        self.assertIsNone(row.feature_block_reason)
        self.assertEqual(row.price_return_pct, Decimal("5.00"))
        self.assertEqual(row.range_pct, Decimal("20.0"))
        self.assertEqual(row.close_position, Decimal("0.75"))
        self._assert_decimal_close(row.kline_taker_buy_ratio, Decimal("0.40"))
        self._assert_decimal_close(row.kline_taker_sell_ratio, Decimal("0.60"))
        self.assertEqual(row.oi_change_pct, Decimal("10.0"))
        self.assertEqual(row.spot_futures_volume_ratio, Decimal("0.50"))

    def test_carried_forward_funding_creates_feature_partial(self) -> None:
        self._insert_inputs(funding_status="FUNDING_CARRIED_FORWARD")

        FeatureBuilder15mService(self.db).run()
        row = self._feature()

        self.assertEqual(row.feature_status, "FEATURE_PARTIAL")
        self.assertEqual(row.feature_block_reason, "funding carried forward")

    def test_incomplete_ohlcv_creates_feature_blocked(self) -> None:
        self._insert_inputs(ohlcv_status="AGG_INCOMPLETE", funding_status="FUNDING_ALIGNED")

        FeatureBuilder15mService(self.db).run()
        row = self._feature()

        self.assertEqual(row.feature_status, "FEATURE_BLOCKED")
        self.assertIn("futures OHLCV status AGG_INCOMPLETE", row.feature_block_reason)

    def test_stale_snapshot_creates_feature_blocked(self) -> None:
        self._insert_inputs(snapshot_status="STALE", funding_status="FUNDING_ALIGNED")

        FeatureBuilder15mService(self.db).run()
        row = self._feature()

        self.assertEqual(row.feature_status, "FEATURE_BLOCKED")
        self.assertIn("snapshot status STALE", row.feature_block_reason)

    def test_incomplete_rich_alignment_creates_feature_blocked(self) -> None:
        self._insert_inputs(rich_status="INCOMPLETE", funding_status="FUNDING_ALIGNED")

        FeatureBuilder15mService(self.db).run()
        row = self._feature()

        self.assertEqual(row.feature_status, "FEATURE_BLOCKED")
        self.assertIn("rich alignment status INCOMPLETE", row.feature_block_reason)

    def test_stale_funding_creates_feature_blocked(self) -> None:
        self._insert_inputs(funding_status="FUNDING_STALE")

        FeatureBuilder15mService(self.db).run()
        row = self._feature()

        self.assertEqual(row.feature_status, "FEATURE_BLOCKED")
        self.assertIn("funding status FUNDING_STALE", row.feature_block_reason)

    def _insert_universe(self) -> None:
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
                entered_at=self.now,
                exited_at=None,
                last_seen_at=self.now,
                created_at=self.now,
                updated_at=self.now,
            )
        )
        self.db.commit()

    def _insert_inputs(
        self,
        ohlcv_status: str = "AGG_READY",
        rich_status: str = "ALIGNED",
        snapshot_status: str = "FRESH",
        funding_status: str = "FUNDING_ALIGNED",
    ) -> None:
        self.db.add(
            FuturesKline15m(
                symbol="TESTUSDT",
                open_time=self.window_open,
                close_time=self.window_close,
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=Decimal("1000"),
                quote_volume=Decimal("10000"),
                number_of_trades=100,
                taker_buy_base_volume=Decimal("400"),
                taker_buy_quote_volume=Decimal("4000"),
                taker_sell_base_volume=Decimal("600"),
                taker_sell_quote_volume=Decimal("6000"),
                source_interval="1m",
                expected_1m_count=15,
                actual_1m_count=15 if ohlcv_status == "AGG_READY" else 14,
                missing_1m_count=0 if ohlcv_status == "AGG_READY" else 1,
                aggregation_status=ohlcv_status,
                created_at=self.now,
                updated_at=self.now,
            )
        )
        self.db.add(
            SpotKline15m(
                symbol="TESTUSDT",
                open_time=self.window_open,
                close_time=self.window_close,
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10.5"),
                volume=Decimal("500"),
                quote_volume=Decimal("5000"),
                number_of_trades=50,
                taker_buy_base_volume=Decimal("250"),
                taker_buy_quote_volume=Decimal("2500"),
                taker_sell_base_volume=Decimal("250"),
                taker_sell_quote_volume=Decimal("2500"),
                source_interval="1m",
                expected_1m_count=15,
                actual_1m_count=15,
                missing_1m_count=0,
                aggregation_status="AGG_READY",
                created_at=self.now,
                updated_at=self.now,
            )
        )
        self.db.add(
            RichFutures5mAlignment(
                symbol="TESTUSDT",
                timeframe="15m",
                window_open_time=self.window_open,
                window_close_time=self.window_close,
                expected_5m_count=3,
                actual_5m_count=3,
                missing_5m_count=0,
                alignment_status=rich_status,
                oi_open=Decimal("1000"),
                oi_close=Decimal("1100"),
                oi_change=Decimal("100"),
                oi_change_pct=Decimal("0.1"),
                oi_value_open=Decimal("2000"),
                oi_value_close=Decimal("2200"),
                global_long_short_ratio_avg=Decimal("1.2"),
                global_long_account_avg=Decimal("0.55"),
                global_short_account_avg=Decimal("0.45"),
                top_trader_position_ratio_avg=Decimal("1.3"),
                top_trader_long_position_avg=Decimal("0.57"),
                top_trader_short_position_avg=Decimal("0.43"),
                top_trader_account_ratio_avg=Decimal("1.1"),
                top_trader_long_account_avg=Decimal("0.52"),
                top_trader_short_account_avg=Decimal("0.48"),
                taker_buy_volume_sum=Decimal("700"),
                taker_sell_volume_sum=Decimal("300"),
                taker_buy_sell_ratio_avg=Decimal("2.333333333333333333"),
                source_timestamps_json=[],
                missing_timestamps_json=[],
                created_at=self.now,
                updated_at=self.now,
            )
        )
        self.db.add(
            MarketStateAlignment(
                symbol="TESTUSDT",
                timeframe="15m",
                window_open_time=self.window_open,
                window_close_time=self.window_close,
                snapshot_alignment_status=snapshot_status,
                funding_alignment_status=funding_status,
                current_oi_status="FRESH" if snapshot_status == "FRESH" else snapshot_status,
                mark_status="FRESH" if snapshot_status == "FRESH" else snapshot_status,
                futures_book_status="FRESH" if snapshot_status == "FRESH" else snapshot_status,
                spot_book_status="FRESH" if snapshot_status == "FRESH" else snapshot_status,
                current_oi=Decimal("1100"),
                current_oi_event_time=self.window_close - timedelta(seconds=30),
                current_oi_age_seconds=30,
                mark_price=Decimal("105"),
                index_price=Decimal("104"),
                last_funding_rate=Decimal("0.0001"),
                next_funding_time=self.window_close + timedelta(hours=8),
                mark_event_time=self.window_close - timedelta(seconds=20),
                mark_age_seconds=20,
                futures_bid_price=Decimal("104.9"),
                futures_ask_price=Decimal("105.1"),
                futures_spread_pct=Decimal("0.190476190476190476"),
                futures_book_event_time=self.window_close - timedelta(seconds=10),
                futures_book_age_seconds=10,
                spot_bid_price=Decimal("104.8"),
                spot_ask_price=Decimal("105.2"),
                spot_spread_pct=Decimal("0.380952380952380952"),
                spot_book_event_time=self.window_close - timedelta(seconds=11),
                spot_book_age_seconds=11,
                latest_funding_rate=Decimal("0.0001"),
                latest_funding_time=self.window_open,
                latest_funding_mark_price=Decimal("104"),
                funding_age_seconds=900,
                funding_carry_forward_status="IN_WINDOW"
                if funding_status == "FUNDING_ALIGNED"
                else "CARRIED_FORWARD",
                details_json={},
                created_at=self.now,
                updated_at=self.now,
            )
        )
        self.db.commit()

    def _feature(self) -> MarketFeature15m:
        row = self.db.scalar(select(MarketFeature15m).where(MarketFeature15m.symbol == "TESTUSDT"))
        self.assertIsNotNone(row)
        return row

    def _assert_decimal_close(self, actual: Decimal, expected: Decimal) -> None:
        self.assertLessEqual(abs(actual - expected), Decimal("0.000000000000001"))


if __name__ == "__main__":
    unittest.main()
