from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.market import MarketCandidateOutcome15m, MarketSignalCandidateReadonly15m, MarketlabActiveUniverse
from app.services.live_candidate_scanner import LiveCandidateScannerService, scanner_tier_for


class LiveCandidateScannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
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

    def test_tier_mapping_is_readonly_context_only(self) -> None:
        self.assertEqual(
            scanner_tier_for("MID_SHORT_CONTEXT_READONLY", "CLASSIFIER_PARTIAL").tier,
            "WATCHLIST_CONTEXT",
        )
        self.assertEqual(
            scanner_tier_for("MID_LONG_CONTEXT_READONLY", "CLASSIFIER_PARTIAL").warning,
            "behavior review marks mid long as noisy; monitor only",
        )
        self.assertEqual(
            scanner_tier_for("EARLY_LONG_CANDIDATE_READONLY", "CLASSIFIER_PARTIAL").tier,
            "RADAR_ONLY",
        )
        self.assertEqual(
            scanner_tier_for("SQUEEZE_RISK_CONTEXT_READONLY", "CLASSIFIER_PARTIAL").tier,
            "RISK_CONTEXT",
        )
        self.assertEqual(scanner_tier_for("DATA_BLOCKED", "CLASSIFIER_BLOCKED").tier, "BLOCKED")

    def test_live_scanner_returns_latest_per_symbol_and_matching_outcome(self) -> None:
        old_open = self.window_open
        new_open = self.window_open + timedelta(minutes=15)
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_universe("BBBUSDT", rank=2)
        self._insert_candidate("AAAUSDT", old_open, "MID_LONG_CONTEXT_READONLY", "BULLISH_CONTEXT")
        self._insert_candidate("AAAUSDT", new_open, "MID_SHORT_CONTEXT_READONLY", "BEARISH_CONTEXT")
        self._insert_candidate(
            "BBBUSDT",
            new_open,
            "DATA_BLOCKED",
            "BLOCKED_CONTEXT",
            classifier_status="CLASSIFIER_BLOCKED",
        )
        self._insert_outcome("AAAUSDT", new_open, "MID_SHORT_CONTEXT_READONLY", "BEARISH_CONTEXT")
        self.db.commit()

        items = LiveCandidateScannerService(self.db).list_live()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["symbol"], "AAAUSDT")
        self.assertEqual(items[0]["candidate_type"], "MID_SHORT_CONTEXT_READONLY")
        self.assertEqual(items[0]["scanner_tier"], "WATCHLIST_CONTEXT")
        self.assertEqual(items[0]["latest_outcome_status"], "OUTCOME_READY")
        self.assertTrue(items[0]["is_active"])
        self.assertEqual(items[0]["collection_tier"], "FULL_ACTIVE")
        self.assertEqual(items[0]["universe_rank"], 1)
        self.assertEqual(items[0]["warning_reason"], "No scanner warning")
        self.assertEqual(items[0]["latest_actual_status"], "CLASSIFIER_PARTIAL")
        self.assertEqual(items[0]["latest_actual_observation_timestamp"], "2026-01-01T00:30:00")
        self.assertFalse(items[0]["using_fallback_usable_row"])
        self.assertIsNone(items[0]["fallback_reason"])
        self.assertTrue(items[0]["not_entry_signal"])
        self.assertEqual(items[0]["evidence_summary"]["price_return_pct_15m"], "0.12")

    def test_default_falls_back_to_latest_usable_when_latest_actual_is_blocked(self) -> None:
        old_open = self.window_open
        blocked_open = self.window_open + timedelta(minutes=15)
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_candidate("AAAUSDT", old_open, "MID_SHORT_CONTEXT_READONLY", "BEARISH_CONTEXT")
        self._insert_candidate(
            "AAAUSDT",
            blocked_open,
            "DATA_BLOCKED",
            "BLOCKED_CONTEXT",
            classifier_status="CLASSIFIER_BLOCKED",
        )
        self.db.commit()

        default_items = LiveCandidateScannerService(self.db).list_live()
        blocked_items = LiveCandidateScannerService(self.db).list_live(include_blocked=True)

        self.assertEqual(len(default_items), 1)
        self.assertEqual(default_items[0]["symbol"], "AAAUSDT")
        self.assertEqual(default_items[0]["candidate_type"], "MID_SHORT_CONTEXT_READONLY")
        self.assertEqual(default_items[0]["scanner_tier"], "WATCHLIST_CONTEXT")
        self.assertTrue(default_items[0]["using_fallback_usable_row"])
        self.assertEqual(default_items[0]["latest_actual_status"], "CLASSIFIER_BLOCKED")
        self.assertEqual(default_items[0]["latest_actual_observation_timestamp"], "2026-01-01T00:30:00")
        self.assertEqual(
            default_items[0]["fallback_reason"],
            "latest cycle is blocked; showing latest usable non-blocked scanner row",
        )
        self.assertEqual(
            default_items[0]["scanner_visibility_reason"],
            "active universe fallback to latest usable non-blocked scanner row",
        )

        self.assertEqual(len(blocked_items), 1)
        self.assertEqual(blocked_items[0]["candidate_type"], "DATA_BLOCKED")
        self.assertEqual(blocked_items[0]["scanner_tier"], "BLOCKED")
        self.assertFalse(blocked_items[0]["using_fallback_usable_row"])

    def test_default_hides_symbol_when_latest_actual_blocked_without_previous_usable(self) -> None:
        blocked_open = self.window_open + timedelta(minutes=15)
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_candidate(
            "AAAUSDT",
            blocked_open,
            "DATA_BLOCKED",
            "BLOCKED_CONTEXT",
            classifier_status="CLASSIFIER_BLOCKED",
        )
        self.db.commit()

        default_items = LiveCandidateScannerService(self.db).list_live()
        blocked_items = LiveCandidateScannerService(self.db).list_live(include_blocked=True)

        self.assertEqual(default_items, [])
        self.assertEqual(len(blocked_items), 1)
        self.assertEqual(blocked_items[0]["candidate_type"], "DATA_BLOCKED")

    def test_filters_and_endpoint_http_200(self) -> None:
        open_time = self.window_open
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_universe("BBBUSDT", rank=2)
        self._insert_candidate("AAAUSDT", open_time, "MID_SHORT_CONTEXT_READONLY", "BEARISH_CONTEXT")
        self._insert_candidate("BBBUSDT", open_time, "SQUEEZE_RISK_CONTEXT_READONLY", "MIXED_CONTEXT")
        self.db.commit()

        service_items = LiveCandidateScannerService(self.db).list_live(tier="RISK_CONTEXT")
        self.assertEqual(len(service_items), 1)
        self.assertEqual(service_items[0]["symbol"], "BBBUSDT")

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        response = TestClient(app).get("/api/scanner/live?tier=WATCHLIST_CONTEXT&limit=10")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["not_entry_signal"])
        self.assertEqual(payload["items"][0]["scanner_tier"], "WATCHLIST_CONTEXT")

    def test_inactive_symbol_hidden_by_default_and_visible_when_requested(self) -> None:
        open_time = self.window_open
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_universe("OLDUSDT", rank=75, is_active=False)
        self._insert_candidate("AAAUSDT", open_time, "MID_SHORT_CONTEXT_READONLY", "BEARISH_CONTEXT")
        self._insert_candidate("OLDUSDT", open_time, "MID_LONG_CONTEXT_READONLY", "BULLISH_CONTEXT")
        self.db.commit()

        default_items = LiveCandidateScannerService(self.db).list_live()
        inactive_items = LiveCandidateScannerService(self.db).list_live(include_inactive=True)

        self.assertEqual([item["symbol"] for item in default_items], ["AAAUSDT"])
        self.assertEqual({item["symbol"] for item in inactive_items}, {"AAAUSDT", "OLDUSDT"})
        old_item = next(item for item in inactive_items if item["symbol"] == "OLDUSDT")
        self.assertFalse(old_item["is_active"])
        self.assertEqual(old_item["collection_tier"], "NOT_ACTIVE")
        self.assertEqual(old_item["universe_rank"], 75)
        self.assertEqual(old_item["inactive_warning"], "Symbol is not in active universe")
        self.assertEqual(old_item["warning_reason"], "Symbol is not in active universe")

    def test_blocked_rows_are_hidden_by_default_and_visible_when_requested(self) -> None:
        open_time = self.window_open
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_universe("BBBUSDT", rank=2)
        self._insert_candidate("AAAUSDT", open_time, "MID_SHORT_CONTEXT_READONLY", "BEARISH_CONTEXT")
        self._insert_candidate(
            "BBBUSDT",
            open_time,
            "DATA_BLOCKED",
            "BLOCKED_CONTEXT",
            classifier_status="CLASSIFIER_BLOCKED",
        )
        self.db.commit()

        default_items = LiveCandidateScannerService(self.db).list_live()
        blocked_items = LiveCandidateScannerService(self.db).list_live(include_blocked=True)

        self.assertEqual([item["symbol"] for item in default_items], ["AAAUSDT"])
        self.assertEqual({item["symbol"] for item in blocked_items}, {"AAAUSDT", "BBBUSDT"})
        blocked_item = next(item for item in blocked_items if item["symbol"] == "BBBUSDT")
        self.assertEqual(blocked_item["scanner_tier"], "BLOCKED")
        self.assertEqual(blocked_item["warning_reason"], "blocked row; not usable for live radar")
        self.assertEqual(blocked_item["scanner_visibility_reason"], "shown because include_blocked=true")

    def test_fallback_does_not_duplicate_symbols(self) -> None:
        old_open = self.window_open
        blocked_open = self.window_open + timedelta(minutes=15)
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_universe("BBBUSDT", rank=2)
        self._insert_candidate("AAAUSDT", old_open, "MID_SHORT_CONTEXT_READONLY", "BEARISH_CONTEXT")
        self._insert_candidate(
            "AAAUSDT",
            blocked_open,
            "DATA_BLOCKED",
            "BLOCKED_CONTEXT",
            classifier_status="CLASSIFIER_BLOCKED",
        )
        self._insert_candidate("BBBUSDT", blocked_open, "MID_LONG_CONTEXT_READONLY", "BULLISH_CONTEXT")
        self.db.commit()

        items = LiveCandidateScannerService(self.db).list_live()
        symbols = [item["symbol"] for item in items]

        self.assertEqual(len(symbols), len(set(symbols)))
        self.assertEqual(set(symbols), {"AAAUSDT", "BBBUSDT"})

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
        classifier_status: str = "CLASSIFIER_PARTIAL",
    ) -> None:
        self.db.add(
            MarketSignalCandidateReadonly15m(
                symbol=symbol,
                window_open_time=window_open,
                window_close_time=window_open + timedelta(minutes=15),
                classifier_status=classifier_status,
                candidate_type=candidate_type,
                candidate_direction=direction,
                confidence_level="MEDIUM",
                confidence_score=Decimal("0.50"),
                evidence={
                    "supporting_psychology_labels": ["BEARISH_PRESSURE"],
                    "context_status": "CONTEXT_READY",
                    "feature_15m_status": "FEATURE_PARTIAL",
                    "feature_1h_status": "FEATURE_PARTIAL",
                    "price_return_pct_15m": "0.12",
                    "oi_change_pct_15m": "-0.34",
                },
                block_reason=None,
                not_entry_signal=True,
                created_at=self.now,
                updated_at=self.now,
            )
        )

    def _insert_outcome(self, symbol: str, window_open: datetime, candidate_type: str, direction: str) -> None:
        self.db.add(
            MarketCandidateOutcome15m(
                symbol=symbol,
                candidate_window_open_time=window_open,
                candidate_window_close_time=window_open + timedelta(minutes=15),
                candidate_type=candidate_type,
                candidate_direction=direction,
                classifier_status="CLASSIFIER_PARTIAL",
                candidate_close_price=Decimal("100"),
                outcome_status="OUTCOME_READY",
                outcome_15m_status="OUTCOME_READY",
                outcome_30m_status="OUTCOME_READY",
                outcome_1h_status="OUTCOME_READY",
                outcome_4h_status="OUTCOME_READY",
                future_return_15m=Decimal("0.1"),
                future_return_30m=Decimal("0.2"),
                future_return_1h=Decimal("0.3"),
                future_return_4h=Decimal("0.4"),
                max_up_move_1h=Decimal("0.5"),
                max_down_move_1h=Decimal("-0.1"),
                max_up_move_4h=Decimal("0.6"),
                max_down_move_4h=Decimal("-0.2"),
                max_favorable_move_1h=Decimal("0.5"),
                max_adverse_move_1h=Decimal("-0.1"),
                max_favorable_move_4h=Decimal("0.6"),
                max_adverse_move_4h=Decimal("-0.2"),
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
