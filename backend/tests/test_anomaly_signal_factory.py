from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.anomaly_signal_factory import (
    SignalFactoryArtifactService,
    build_summary,
    classify_candidate,
    detect_anomalies,
)


class AnomalySignalFactoryTest(unittest.TestCase):
    def test_mid_short_candidate_mapping_is_read_only(self) -> None:
        feature = self._feature(price_return=-0.8, oi_change_pct=0.4, futures_led=True, close_position=0.45)

        candidate = classify_candidate(feature, atr_reference_status="AVAILABLE")

        self.assertEqual(candidate["setup_type"], "MID_SHORT")
        self.assertEqual(candidate["direction"], "BEARISH_CONTEXT")
        self.assertEqual(candidate["candidate_status"], "SIGNAL_CANDIDATE")
        self.assertTrue(candidate["not_live_signal"])
        self.assertTrue(candidate["not_execution_instruction"])
        self.assertIn("PRICE_DOWN_IMPULSE", candidate["evidence"]["anomalies"])
        self.assertIn("OI_EXPANSION", candidate["evidence"]["anomalies"])

    def test_missing_atr_reference_downgrades_signal_candidate_to_radar(self) -> None:
        feature = self._feature(price_return=-0.8, oi_change_pct=0.4, futures_led=True, close_position=0.15)

        candidate = classify_candidate(feature, atr_reference_status="MISSING_ATR_REFERENCE")

        self.assertEqual(candidate["candidate_status"], "RADAR_ONLY")
        self.assertEqual(candidate["atr_reference_status"], "MISSING_ATR_REFERENCE")

    def test_early_long_quality_can_be_readonly_signal_candidate(self) -> None:
        feature = self._feature(
            price_return=0.55,
            oi_change_pct=0.05,
            close_position=0.78,
            taker_buy_ratio=0.62,
            volume_ratio=2.2,
            atr_pct=1.0,
            spot_context="SPOT_SUPPORTING",
        )

        candidate = classify_candidate(feature, atr_reference_status="AVAILABLE")

        self.assertEqual(candidate["setup_type"], "EARLY_LONG")
        self.assertEqual(candidate["candidate_status"], "SIGNAL_CANDIDATE")
        self.assertEqual(candidate["direction"], "BULLISH_CONTEXT")
        self.assertEqual(candidate["evidence"]["entry_market"], "futures")
        self.assertEqual(candidate["evidence"]["spot_usage"], "filter/evidence_only")
        self.assertEqual(candidate["evidence"]["kline_taker_buy_ratio"], 0.62)
        self.assertEqual(candidate["evidence"]["kline_taker_sell_ratio"], 0.38)
        self.assertGreaterEqual(candidate["evidence"]["early_quality_score"], 6)

    def test_early_short_quality_missing_atr_stays_radar_only(self) -> None:
        feature = self._feature(
            price_return=-0.55,
            oi_change_pct=0.05,
            close_position=0.20,
            volume_ratio=2.2,
            atr_pct=1.0,
            spot_context="WEAK_SPOT_SUPPORT",
        )

        candidate = classify_candidate(feature, atr_reference_status="MISSING_ATR_REFERENCE")

        self.assertEqual(candidate["setup_type"], "EARLY_SHORT")
        self.assertEqual(candidate["candidate_status"], "RADAR_ONLY")
        self.assertEqual(candidate["atr_reference_status"], "MISSING_ATR_REFERENCE")

    def test_blocked_data_never_becomes_signal_candidate(self) -> None:
        feature = self._feature(price_return=-0.8, oi_change_pct=0.4, futures_led=True)
        feature["feature_status"] = "MISSING_CANDLES"

        candidate = classify_candidate(feature)

        self.assertEqual(candidate["candidate_status"], "TIMEFRAME_NOT_READY")
        self.assertEqual(candidate["setup_type"], "BLOCKED_DATA")
        self.assertEqual(detect_anomalies(feature), ["DATA_NOT_READY"])

    def test_summary_counts_and_api_read_artifact(self) -> None:
        candidates = [
            classify_candidate(self._feature(symbol="AAAUSDT", price_return=-0.8, oi_change_pct=0.4, futures_led=True)),
            classify_candidate(self._feature(symbol="BBBUSDT", price_return=0.8, oi_change_pct=0.4)),
        ]
        summary = build_summary("2026-01-01T00:00:00+00:00", [self._feature(), self._feature(timeframe="1h")], candidates)

        self.assertEqual(summary["candidate_count"], 2)
        self.assertEqual(summary["feature_count_by_timeframe"]["15m"], 1)

        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "summary.json").write_text(json.dumps(summary))
            (artifact_dir / "candidates.json").write_text(json.dumps({"generated_at": summary["generated_at"], "items": candidates}))
            service = SignalFactoryArtifactService(artifact_dir)
            self.assertEqual(service.candidates(setup_type="MID_SHORT")["count"], 1)

            with patch("app.api.routes.SignalFactoryArtifactService", return_value=service):
                response = TestClient(app).get("/api/signal-factory/v1/summary")

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["guardrails"]["read_only"])

    def _feature(
        self,
        symbol: str = "AAAUSDT",
        timeframe: str = "15m",
        price_return: float = 0.1,
        oi_change_pct: float = 0.0,
        futures_led: bool = False,
        close_position: float = 0.5,
        taker_buy_ratio: float = 0.52,
        volume_ratio: float = 1.0,
        atr_pct: float = 1.0,
        spot_context: str = "INLINE_SPOT_CONTEXT",
    ) -> dict:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "window_start": "2026-01-01T00:00:00+00:00",
            "window_end": "2026-01-01T00:15:00+00:00",
            "price_return": price_return,
            "price_return_abs": abs(price_return),
            "volume_spike": futures_led,
            "volume_ratio_vs_lookback": volume_ratio,
            "oi_change_pct": oi_change_pct,
            "funding_rate": 0.0,
            "funding_pressure": "NEUTRAL",
            "close_position_in_range": close_position,
            "kline_taker_buy_ratio": taker_buy_ratio,
            "kline_taker_sell_ratio": 1 - taker_buy_ratio,
            "kline_taker_buy_base": 520,
            "kline_taker_sell_base": 480,
            "atr_pct": atr_pct,
            "relative_strength": "INLINE_WITH_MARKET",
            "futures_led_flag": futures_led,
            "spot_led_flag": False,
            "spot_context": spot_context,
            "feature_status": "READY",
            "status_reasons": [],
        }


if __name__ == "__main__":
    unittest.main()
