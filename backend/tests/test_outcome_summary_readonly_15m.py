from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import MarketCandidateOutcome15m, MarketFeatureContext15m1h
from app.services.outcome_summary_readonly_15m import OutcomeSummaryReadonly15mService


class OutcomeSummaryReadonly15mTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False, expire_on_commit=False)
        self.db = self.Session()
        self.now = datetime(2026, 1, 1, tzinfo=UTC)
        self.window_open = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_summary_uses_ready_rows_only_for_forward_metrics(self) -> None:
        self._insert_outcome(
            symbol="AAAUSDT",
            offset=0,
            status="OUTCOME_READY",
            candidate_type="MID_LONG_CONTEXT_READONLY",
            direction="BULLISH_CONTEXT",
            future_return_15m=Decimal("1"),
            spot_status="SPOT_SUPPORTING",
        )
        self._insert_outcome(
            symbol="BBBUSDT",
            offset=1,
            status="OUTCOME_READY",
            candidate_type="MID_LONG_CONTEXT_READONLY",
            direction="BULLISH_CONTEXT",
            future_return_15m=Decimal("3"),
            spot_status="WEAK_SPOT_SUPPORT",
        )
        self._insert_outcome(
            symbol="CCCUSDT",
            offset=2,
            status="OUTCOME_BLOCKED",
            candidate_type="MID_LONG_CONTEXT_READONLY",
            direction="BLOCKED_CONTEXT",
            future_return_15m=Decimal("99"),
            spot_status="SPOT_MISSING",
        )
        self.db.commit()

        summary = OutcomeSummaryReadonly15mService(self.db).summary()

        self.assertEqual(summary["overall_counts"]["OUTCOME_READY"], 2)
        self.assertEqual(summary["overall_counts"]["OUTCOME_BLOCKED"], 1)
        self.assertEqual(summary["ready_sample_size"], 2)
        medians = summary["median_metrics_by_candidate_type"][0]["medians"]
        self.assertEqual(medians["future_return_15m"], Decimal("2"))
        self.assertEqual(summary["integrity"]["blocked_rows_used_for_directional_metrics"], 0)

    def test_mixed_context_is_not_forced_directional(self) -> None:
        self._insert_outcome(
            symbol="AAAUSDT",
            offset=0,
            status="OUTCOME_READY",
            candidate_type="NO_SIGNAL_CONTEXT",
            direction="MIXED_CONTEXT",
            future_return_15m=Decimal("1"),
            spot_status="SPOT_UNKNOWN",
        )
        self.db.commit()

        summary = OutcomeSummaryReadonly15mService(self.db).summary()

        self.assertEqual(summary["direction_counts_ready"][0]["value"], "MIXED_CONTEXT")
        self.assertTrue(summary["guardrails"]["mixed_context_not_forced_directional"])
        for item in summary["directional_medians"]:
            self.assertEqual(item["sample_size"], 0)
            self.assertIsNone(item["medians"]["max_favorable_move_1h"])

    def _insert_outcome(
        self,
        symbol: str,
        offset: int,
        status: str,
        candidate_type: str,
        direction: str,
        future_return_15m: Decimal,
        spot_status: str,
    ) -> None:
        open_time = self.window_open + timedelta(minutes=15 * offset)
        close_time = open_time + timedelta(minutes=15)
        is_ready = status == "OUTCOME_READY"
        self.db.add(
            MarketCandidateOutcome15m(
                symbol=symbol,
                candidate_window_open_time=open_time,
                candidate_window_close_time=close_time,
                candidate_type=candidate_type,
                candidate_direction=direction,
                classifier_status="CLASSIFIER_READY" if is_ready else "CLASSIFIER_BLOCKED",
                candidate_close_price=Decimal("100"),
                outcome_status=status,
                outcome_15m_status=status,
                outcome_30m_status=status,
                outcome_1h_status=status,
                outcome_4h_status=status,
                future_return_15m=future_return_15m if is_ready else None,
                future_return_30m=Decimal("2") if is_ready else None,
                future_return_1h=Decimal("4") if is_ready else None,
                future_return_4h=Decimal("8") if is_ready else None,
                max_up_move_1h=Decimal("5") if is_ready else None,
                max_down_move_1h=Decimal("-2") if is_ready else None,
                max_up_move_4h=Decimal("7") if is_ready else None,
                max_down_move_4h=Decimal("-3") if is_ready else None,
                max_favorable_move_1h=Decimal("5") if direction == "BULLISH_CONTEXT" and is_ready else None,
                max_adverse_move_1h=Decimal("-2") if direction == "BULLISH_CONTEXT" and is_ready else None,
                max_favorable_move_4h=Decimal("7") if direction == "BULLISH_CONTEXT" and is_ready else None,
                max_adverse_move_4h=Decimal("-3") if direction == "BULLISH_CONTEXT" and is_ready else None,
                followthrough_status="FOLLOWTHROUGH" if direction == "BULLISH_CONTEXT" else "MIXED_CONTEXT_ONLY",
                invalidation_status="NOT_INVALIDATED" if direction == "BULLISH_CONTEXT" else "MIXED_CONTEXT_ONLY",
                source_candle_count_15m=1 if is_ready else 0,
                source_candle_count_30m=2 if is_ready else 0,
                source_candle_count_1h=4 if is_ready else 0,
                source_candle_count_4h=16 if is_ready else 0,
                missing_window_list=[],
                evidence={"test": True},
                created_at=self.now,
                updated_at=self.now,
            )
        )
        self.db.add(
            MarketFeatureContext15m1h(
                symbol=symbol,
                feature_15m_window_open_time=open_time,
                feature_15m_window_close_time=close_time,
                context_1h_window_open_time=None,
                context_1h_window_close_time=None,
                feature_15m_status="FEATURE_READY" if is_ready else "FEATURE_BLOCKED",
                feature_1h_status=None,
                context_status="CONTEXT_READY" if is_ready else "CONTEXT_BLOCKED",
                context_block_reason=None if is_ready else "test blocked",
                spot_missing_flag_15m=spot_status == "SPOT_MISSING",
                spot_support_status_15m=spot_status,
                created_at=self.now,
                updated_at=self.now,
            )
        )


if __name__ == "__main__":
    unittest.main()
