from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.market import MarketCandidateOutcome15m, MarketSignalCandidateReadonly15m, MarketlabActiveUniverse
from app.services.paper_signal_evaluator import PaperSignalEvaluatorService


class PaperSignalEvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False, expire_on_commit=False)
        self.db = self.Session()
        self.now = datetime(2026, 1, 1, tzinfo=UTC)
        self.window_open = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_mid_short_futures_led_is_paper_short_candidate(self) -> None:
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_candidate(
            "AAAUSDT",
            self.window_open,
            "MID_SHORT_CONTEXT_READONLY",
            "BEARISH_CONTEXT",
            evidence={
                "spot_support_status_15m": "FUTURES_LED",
                "supporting_psychology_labels": ["BEARISH_PRESSURE", "FUTURES_LED_MOVE"],
            },
        )
        self._insert_outcome("AAAUSDT", self.window_open, "OUTCOME_READY")
        self.db.commit()

        payload = PaperSignalEvaluatorService(self.db).list_short_candidates()

        self.assertEqual(payload["count"], 1)
        item = payload["items"][0]
        self.assertEqual(item["paper_candidate_status"], "PAPER_SHORT_CANDIDATE")
        self.assertEqual(item["paper_direction"], "BEARISH_CONTEXT")
        self.assertEqual(item["rejection_reasons"], [])
        self.assertTrue(item["futures_led_context"])
        self.assertTrue(item["not_live_signal"])
        self.assertTrue(item["not_execution_instruction"])
        self.assertEqual(item["threshold_reference"]["favorable_threshold_pct"], "1.6076")
        self.assertEqual(item["threshold_reference"]["adverse_threshold_pct"], "0.9022")

    def test_rejection_reasons_for_non_matching_candidate(self) -> None:
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_candidate(
            "AAAUSDT",
            self.window_open,
            "MID_LONG_CONTEXT_READONLY",
            "BULLISH_CONTEXT",
            evidence={"spot_support_status_15m": "SPOT_SUPPORTING", "supporting_psychology_labels": []},
        )
        self._insert_outcome("AAAUSDT", self.window_open, "OUTCOME_READY")
        self.db.commit()

        item = PaperSignalEvaluatorService(self.db).list_short_candidates()["items"][0]

        self.assertEqual(item["paper_candidate_status"], "PAPER_CANDIDATE_REJECTED")
        self.assertIn("NOT_MID_SHORT", item["rejection_reasons"])
        self.assertIn("NOT_BEARISH_CONTEXT", item["rejection_reasons"])
        self.assertIn("NOT_FUTURES_LED", item["rejection_reasons"])
        self.assertIsNone(item["paper_direction"])

    def test_endpoint_http_200_and_can_hide_rejected(self) -> None:
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_universe("BBBUSDT", rank=2)
        self._insert_candidate(
            "AAAUSDT",
            self.window_open,
            "MID_SHORT_CONTEXT_READONLY",
            "BEARISH_CONTEXT",
            evidence={"spot_support_status_15m": "FUTURES_LED", "supporting_psychology_labels": []},
        )
        self._insert_outcome("AAAUSDT", self.window_open, "OUTCOME_READY")
        self._insert_candidate(
            "BBBUSDT",
            self.window_open,
            "NO_SIGNAL_CONTEXT",
            "MIXED_CONTEXT",
            evidence={"spot_support_status_15m": "SPOT_UNKNOWN", "supporting_psychology_labels": []},
        )
        self._insert_outcome("BBBUSDT", self.window_open, "OUTCOME_READY")
        self.db.commit()

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        response = TestClient(app).get("/api/paper-signals/short-candidates?include_rejected=false&limit=10")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["not_live_signal"])
        self.assertTrue(payload["not_execution_instruction"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["symbol"], "AAAUSDT")
        self.assertEqual(payload["items"][0]["paper_candidate_status"], "PAPER_SHORT_CANDIDATE")

    def _insert_universe(self, symbol: str, rank: int, is_active: bool = True) -> None:
        self.db.add(
            MarketlabActiveUniverse(
                symbol=symbol,
                rank=rank,
                quote_volume=Decimal("1000000"),
                collection_tier="FULL_ACTIVE" if is_active else "NOT_ACTIVE",
                is_full_active=is_active,
                is_light_watch=False,
                is_signal_eligible=is_active,
                is_active=is_active,
                entered_at=self.now,
                exited_at=None if is_active else self.now,
                last_seen_at=self.now,
                created_at=self.now,
                updated_at=self.now,
            )
        )

    def _insert_candidate(
        self,
        symbol: str,
        window_open: datetime,
        candidate_type: str,
        direction: str,
        evidence: dict,
    ) -> None:
        self.db.add(
            MarketSignalCandidateReadonly15m(
                symbol=symbol,
                window_open_time=window_open,
                window_close_time=window_open + timedelta(minutes=15),
                classifier_status="CLASSIFIER_PARTIAL",
                candidate_type=candidate_type,
                candidate_direction=direction,
                confidence_level="MEDIUM",
                confidence_score=Decimal("0.60"),
                evidence=evidence,
                block_reason=None,
                not_entry_signal=True,
                created_at=self.now,
                updated_at=self.now,
            )
        )

    def _insert_outcome(self, symbol: str, window_open: datetime, status: str) -> None:
        self.db.add(
            MarketCandidateOutcome15m(
                symbol=symbol,
                candidate_window_open_time=window_open,
                candidate_window_close_time=window_open + timedelta(minutes=15),
                candidate_type="MID_SHORT_CONTEXT_READONLY",
                candidate_direction="BEARISH_CONTEXT",
                classifier_status="CLASSIFIER_PARTIAL",
                candidate_close_price=Decimal("100"),
                outcome_status=status,
                outcome_15m_status=status,
                outcome_30m_status=status,
                outcome_1h_status=status,
                outcome_4h_status=status,
                future_return_15m=Decimal("-0.1"),
                future_return_30m=Decimal("-0.2"),
                future_return_1h=Decimal("-0.3"),
                future_return_4h=Decimal("-0.4"),
                max_up_move_1h=Decimal("0.1"),
                max_down_move_1h=Decimal("-0.5"),
                max_up_move_4h=Decimal("0.6"),
                max_down_move_4h=Decimal("-2.0"),
                max_favorable_move_1h=Decimal("0.5"),
                max_adverse_move_1h=Decimal("0.1"),
                max_favorable_move_4h=Decimal("2.0"),
                max_adverse_move_4h=Decimal("0.6"),
                followthrough_status="FOLLOWTHROUGH",
                invalidation_status="NOT_INVALIDATED",
                source_candle_count_15m=1,
                source_candle_count_30m=2,
                source_candle_count_1h=4,
                source_candle_count_4h=16,
                missing_window_list=[],
                evidence={"test": True},
                created_at=self.now,
                updated_at=self.now,
            )
        )


if __name__ == "__main__":
    unittest.main()
