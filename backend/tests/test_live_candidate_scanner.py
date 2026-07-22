from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.market import FuturesKline15m, FuturesKline1h, MarketCandidateOutcome15m, MarketSignalCandidateReadonly15m, MarketlabActiveUniverse
from app.services.live_candidate_scanner import LiveCandidateScannerService, scanner_tier_for
from app.services.signal_forward_return_logger import SignalForwardReturnLogger


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

    def test_early_signal_candidate_payload_includes_futures_entry_plan(self) -> None:
        open_time = self.window_open
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_universe("BBBUSDT", rank=2)
        self._insert_candidate(
            "AAAUSDT",
            open_time,
            "EARLY_LONG_CANDIDATE_READONLY",
            "BULLISH_CONTEXT",
            evidence={
                "early_long_quality_score": 7,
                "early_long_quality_bucket": "MEDIUM_QUALITY",
                "early_long_quality_reasons": ["volume spike", "spot supports long impulse"],
                "early_signal_logic_version": "normalized_impulse_early_v1",
                "entry_market": "futures",
                "entry_price_source": "futures_klines_15m.close",
                "spot_usage": "filter/evidence_only",
            },
        )
        self._insert_futures_15m("AAAUSDT", open_time, close=Decimal("100"))
        self._insert_futures_1h_history("AAAUSDT", open_time + timedelta(minutes=15))
        self.db.commit()

        items = LiveCandidateScannerService(self.db).list_live()

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["scanner_tier"], "SIGNAL_CANDIDATE")
        self.assertEqual(item["signal_status"], "SIGNAL_CANDIDATE")
        self.assertEqual(item["entry_market"], "futures")
        self.assertEqual(item["entry_price_source"], "futures_klines_15m.close")
        self.assertEqual(item["entry_price"], "100.000000000000000000")
        self.assertEqual(item["rr"], "1.5")
        self.assertEqual(item["timeout_minutes"], 60)
        self.assertEqual(item["quality_score"], 7)
        self.assertEqual(item["position_lock_mode"], "LOCK_BY_SYMBOL")
        self.assertTrue(item["not_execution_instruction"])
        self.assertIsNotNone(item["stop_loss_reference"])
        self.assertIsNotNone(item["take_profit_reference"])

    def test_signal_factory_candidate_is_visible_when_db_classifier_has_no_signal(self) -> None:
        open_time = self.window_open
        self._insert_universe("AAAUSDT", rank=1)
        self._insert_candidate(
            "AAAUSDT",
            open_time,
            "DATA_BLOCKED",
            "BLOCKED_CONTEXT",
            classifier_status="CLASSIFIER_BLOCKED",
        )
        self._insert_futures_15m("AAAUSDT", open_time, close=Decimal("100"))
        self._insert_futures_1h_history("AAAUSDT", open_time + timedelta(minutes=15))
        self.db.commit()

        with TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "candidates.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-01-01T00:20:00+00:00",
                        "items": [
                            {
                                "symbol": "AAAUSDT",
                                "timeframe": "15m",
                                "window_start": "2026-01-01T00:00:00",
                                "window_end": "2026-01-01T00:15:00",
                                "setup_type": "EARLY_LONG",
                                "direction": "BULLISH_CONTEXT",
                                "confidence": "MEDIUM",
                                "reason": "Normalized early long quality 6/10 (MEDIUM_QUALITY)",
                                "candidate_status": "SIGNAL_CANDIDATE",
                                "atr_reference_timeframe": "1h",
                                "atr_reference_status": "AVAILABLE",
                                "not_live_signal": True,
                                "not_execution_instruction": True,
                                "evidence": {
                                    "price_return": "0.8",
                                    "oi_change_pct": "0.2",
                                    "entry_market": "futures",
                                    "entry_price_source": "futures_klines_15m.close",
                                    "spot_usage": "filter/evidence_only",
                                    "early_quality_score": 6,
                                    "early_quality_bucket": "MEDIUM_QUALITY",
                                    "early_quality_reasons": ["volume spike"],
                                },
                            }
                        ],
                    }
                )
            )

            SignalForwardReturnLogger(self.db, artifact_dir=artifact_dir).run()

            items = LiveCandidateScannerService(self.db, signal_factory_artifact_dir=artifact_dir).list_live()
            signal_items = LiveCandidateScannerService(
                self.db,
                signal_factory_artifact_dir=artifact_dir,
            ).list_live(tier="SIGNAL_CANDIDATE")

        self.assertEqual(len(items), 1)
        self.assertEqual(len(signal_items), 1)
        item = signal_items[0]
        self.assertEqual(item["symbol"], "AAAUSDT")
        self.assertEqual(item["timeframe"], "15m")
        self.assertEqual(item["scanner_tier"], "SIGNAL_CANDIDATE")
        self.assertEqual(item["candidate_type"], "EARLY_LONG_CANDIDATE_READONLY")
        self.assertEqual(item["signal_status"], "SIGNAL_CANDIDATE")
        self.assertEqual(item["entry_market"], "futures")
        self.assertEqual(item["entry_price"], "100.000000000000000000")
        self.assertEqual(item["quality_score"], 6)
        self.assertEqual(item["evidence_summary"]["source"], "signal_factory_v1")
        self.assertIn("V2", item["strategy_version"])
        self.assertEqual(item["shadow_strategy_version"], "SIGNAL_FACTORY_V3_SHADOW_CALIBRATION")
        self.assertEqual(item["v3_shadow_status"], "V3_SHADOW_NO_FILTER")
        self.assertEqual(item["structure_zone_status"], "ZONE_UNAVAILABLE")
        self.assertEqual(item["structure_zone_primary_timeframe"], "1h")
        self.assertTrue(item["structure_zone_read_only"])
        self.assertTrue(item["structure_zone_not_signal_gate"])
        self.assertTrue(item["not_entry_signal"])
        self.assertTrue(item["not_execution_instruction"])

    def test_signal_factory_signal_candidates_include_non_15m_timeframes(self) -> None:
        self._insert_universe("BBBUSDT", rank=2)
        self.db.commit()

        with TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "candidates.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-01-01T01:20:00+00:00",
                        "items": [
                            {
                                "symbol": "BBBUSDT",
                                "timeframe": "1h",
                                "window_start": "2026-01-01T00:00:00",
                                "window_end": "2026-01-01T01:00:00",
                                "setup_type": "MID_SHORT",
                                "direction": "BEARISH_CONTEXT",
                                "confidence": "HIGH",
                                "reason": "Signal Factory V2 normalized bearish impulse with OI expansion",
                                "candidate_status": "SIGNAL_CANDIDATE",
                                "entry_price": "50",
                                "stop_loss_reference": "52",
                                "take_profit_reference": "47",
                                "rr": "1.5",
                                "timeout_minutes": 240,
                                "atr_reference_timeframe": "4h",
                                "atr_reference_status": "AVAILABLE",
                                "not_live_signal": True,
                                "not_execution_instruction": True,
                                "evidence": {
                                    "entry_market": "futures",
                                    "entry_price_source": "futures_klines_1h.close",
                                    "spot_usage": "filter/evidence_only",
                                    "core_score": 7,
                                    "evidence_score": 2,
                                    "range_ratio_vs_atr": "1.10",
                                    "futures_spread_pct": "0.01",
                                },
                            }
                        ],
                    }
                )
            )

            signal_items = LiveCandidateScannerService(self.db, signal_factory_artifact_dir=artifact_dir).list_live(
                tier="SIGNAL_CANDIDATE"
            )

        self.assertEqual(len(signal_items), 1)
        item = signal_items[0]
        self.assertEqual(item["symbol"], "BBBUSDT")
        self.assertEqual(item["timeframe"], "1h")
        self.assertEqual(item["scanner_tier"], "SIGNAL_CANDIDATE")
        self.assertEqual(item["candidate_type"], "MID_SHORT_CONTEXT_READONLY")
        self.assertEqual(item["signal_status"], "SIGNAL_CANDIDATE")
        self.assertEqual(item["entry_market"], "futures")
        self.assertEqual(item["entry_price"], "50")
        self.assertEqual(item["stop_loss_reference"], "52")
        self.assertEqual(item["take_profit_reference"], "47")
        self.assertEqual(item["timeout_minutes"], 240)
        self.assertEqual(item["atr_reference_timeframe"], "4h")
        self.assertEqual(item["quality_shadow_status"], "SHADOW_PASS")
        self.assertEqual(item["quality_shadow_filter_id"], "MID_SHORT_1H_FILL_GOOD_RANGE_OK")
        self.assertTrue(item["quality_shadow_pass"])
        self.assertEqual(item["quality_shadow_range_ratio_vs_atr"], "1.10")
        self.assertEqual(item["quality_shadow_fill_quality"], "FILL_GOOD")
        self.assertTrue(item["not_entry_signal"])
        self.assertTrue(item["not_execution_instruction"])

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

    def test_latest_per_symbol_query_count_is_bounded_for_full_universe(self) -> None:
        for rank in range(1, 76):
            symbol = f"S{rank:03d}USDT"
            self._insert_universe(symbol, rank=rank)
            self._insert_candidate(symbol, self.window_open, "MID_SHORT_CONTEXT_READONLY", "BEARISH_CONTEXT")
        self.db.commit()

        query_count = 0

        def count_query(*_args, **_kwargs) -> None:
            nonlocal query_count
            query_count += 1

        event.listen(self.engine, "before_cursor_execute", count_query)
        try:
            items = LiveCandidateScannerService(self.db).list_live(limit=75)
        finally:
            event.remove(self.engine, "before_cursor_execute", count_query)

        self.assertEqual(len(items), 75)
        self.assertEqual(len({item["symbol"] for item in items}), 75)
        self.assertLessEqual(query_count, 3)

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
        evidence: dict | None = None,
    ) -> None:
        default_evidence = {
            "supporting_psychology_labels": ["BEARISH_PRESSURE"],
            "context_status": "CONTEXT_READY",
            "feature_15m_status": "FEATURE_PARTIAL",
            "feature_1h_status": "FEATURE_PARTIAL",
            "price_return_pct_15m": "0.12",
            "oi_change_pct_15m": "-0.34",
        }
        if evidence:
            default_evidence.update(evidence)
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
                evidence=default_evidence,
                block_reason=None,
                not_entry_signal=True,
                created_at=self.now,
                updated_at=self.now,
            )
        )

    def _insert_futures_15m(self, symbol: str, open_time: datetime, close: Decimal) -> None:
        self.db.add(
            FuturesKline15m(
                symbol=symbol,
                open_time=open_time,
                close_time=open_time + timedelta(minutes=15),
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("1000"),
                quote_volume=Decimal("100000"),
                number_of_trades=100,
                taker_buy_base_volume=Decimal("500"),
                taker_buy_quote_volume=Decimal("50000"),
                taker_sell_base_volume=Decimal("500"),
                taker_sell_quote_volume=Decimal("50000"),
                source_interval="15m",
                expected_1m_count=15,
                actual_1m_count=15,
                missing_1m_count=0,
                aggregation_status="AGG_READY",
                created_at=self.now,
                updated_at=self.now,
            )
        )

    def _insert_futures_1h_history(self, symbol: str, signal_close_time: datetime) -> None:
        start = signal_close_time - timedelta(hours=15)
        for index in range(15):
            open_time = start + timedelta(hours=index)
            close = Decimal("100") + Decimal(index)
            self.db.add(
                FuturesKline1h(
                    symbol=symbol,
                    open_time=open_time,
                    close_time=open_time + timedelta(hours=1),
                    open=close,
                    high=close + Decimal("2"),
                    low=close - Decimal("1"),
                    close=close + Decimal("1"),
                    volume=Decimal("1000"),
                    quote_volume=Decimal("100000"),
                    number_of_trades=100,
                    taker_buy_base_volume=Decimal("500"),
                    taker_buy_quote_volume=Decimal("50000"),
                    taker_sell_base_volume=Decimal("500"),
                    taker_sell_quote_volume=Decimal("50000"),
                    source_interval="1h",
                    expected_1m_count=60,
                    actual_1m_count=60,
                    missing_1m_count=0,
                    aggregation_status="AGG_READY",
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
