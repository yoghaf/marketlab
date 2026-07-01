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
        feature = self._feature(price_return=-0.8, oi_change_pct=0.4, futures_led=True, close_position=0.15)

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
    ) -> dict:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "window_start": "2026-01-01T00:00:00+00:00",
            "window_end": "2026-01-01T00:15:00+00:00",
            "price_return": price_return,
            "volume_spike": futures_led,
            "oi_change_pct": oi_change_pct,
            "funding_pressure": "NEUTRAL",
            "close_position_in_range": close_position,
            "relative_strength": "INLINE_WITH_MARKET",
            "futures_led_flag": futures_led,
            "spot_led_flag": False,
            "feature_status": "READY",
            "status_reasons": [],
        }


if __name__ == "__main__":
    unittest.main()
