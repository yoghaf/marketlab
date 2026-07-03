from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.early_backtest_lab import EarlyBacktestLabArtifactService


class EarlyBacktestLabArtifactServiceTest(unittest.TestCase):
    def test_summary_filters_early_events_and_computes_horizon_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "results.json").write_text(json.dumps({"metadata": {"epoch": "TEST"}, "events": self._events()}))

            summary = EarlyBacktestLabArtifactService(artifact_dir).summary()

            self.assertEqual(summary["summary"]["total_events"], 2)
            self.assertEqual(summary["summary"]["by_stage"], {"EARLY_LONG": 1, "EARLY_SHORT": 1})
            self.assertEqual(summary["summary"]["by_horizon"]["4h"]["ready"], 2)
            self.assertEqual(summary["summary"]["by_horizon"]["4h"]["tp"], 1)
            self.assertEqual(summary["summary"]["by_horizon"]["4h"]["sl"], 1)
            self.assertEqual(summary["summary"]["by_horizon"]["4h"]["median_r"], 0.5)

    def test_events_can_filter_stage_horizon_and_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "results.json").write_text(json.dumps({"metadata": {"epoch": "TEST"}, "events": self._events()}))

            payload = EarlyBacktestLabArtifactService(artifact_dir).events(stage="EARLY_LONG", horizon="4h", outcome="TP_FIRST")

            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["items"][0]["symbol"], "AAAUSDT")
            self.assertEqual(payload["items"][0]["entry_market"], "futures")
            self.assertTrue(payload["items"][0]["not_live_signal"])

    def _events(self) -> list[dict]:
        return [
            {
                "signal_id": "1",
                "symbol": "AAAUSDT",
                "timeframe": "15m",
                "signal_time_utc": "2026-07-03T00:00:00",
                "signal_time_wib": "2026-07-03 07:00:00 WIB",
                "stage": "EARLY_LONG",
                "direction": "LONG",
                "confidence_tier": "HIGH_CONF",
                "core_score": "8",
                "evidence_score": "2",
                "evidence_data_completeness": 4,
                "execution_flag": "ACTIVE",
                "entry_market": "futures",
                "entry": "100",
                "stop": "99",
                "target": "102",
                "risk": "1",
                "horizons": {
                    "4h": {
                        "status": "READY",
                        "outcome": "TP_FIRST",
                        "realized_r": "2",
                        "mfe_r": "2.5",
                        "mae_r": "-0.3",
                    }
                },
            },
            {
                "signal_id": "2",
                "symbol": "BBBUSDT",
                "timeframe": "15m",
                "signal_time_utc": "2026-07-03T00:15:00",
                "signal_time_wib": "2026-07-03 07:15:00 WIB",
                "stage": "EARLY_SHORT",
                "direction": "SHORT",
                "confidence_tier": "MEDIUM_CONF",
                "core_score": "7",
                "evidence_score": "1",
                "evidence_data_completeness": 4,
                "execution_flag": "ACTIVE",
                "entry_market": "futures",
                "entry": "100",
                "stop": "101",
                "target": "98.5",
                "risk": "1",
                "horizons": {
                    "4h": {
                        "status": "READY",
                        "outcome": "SL_FIRST",
                        "realized_r": "-1",
                        "mfe_r": "0.2",
                        "mae_r": "-1",
                    }
                },
            },
            {
                "signal_id": "3",
                "symbol": "CCCUSDT",
                "stage": "MID_LONG",
                "horizons": {"4h": {"status": "READY", "outcome": "TP_FIRST", "realized_r": "2"}},
            },
        ]


if __name__ == "__main__":
    unittest.main()
