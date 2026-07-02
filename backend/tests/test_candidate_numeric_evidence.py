from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.candidate_numeric_evidence import CandidateNumericEvidenceArtifactService, CandidateNumericEvidenceBuilder


class CandidateNumericEvidenceTests(unittest.TestCase):
    def test_builder_explains_signal_candidate_with_numbers_and_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sf = root / "sf"
            arena = root / "arena"
            phase6 = root / "phase6"
            sf.mkdir()
            arena.mkdir()
            phase6.mkdir()
            self._write_artifacts(sf, arena, phase6)

            payload = CandidateNumericEvidenceBuilder(sf, arena, phase6).build()

            self.assertEqual(payload["aggregate"]["total_candidates"], 1)
            self.assertEqual(payload["aggregate"]["signal_candidate_count"], 1)
            item = payload["items"][0]
            self.assertEqual(item["symbol"], "AAAUSDT")
            self.assertTrue(item["not_live_signal"])
            edge = self._find_metric(item, "edge_vs_baseline")
            self.assertEqual(edge["required_operator"], ">")
            self.assertEqual(edge["required_value"], 0.10)
            self.assertEqual(edge["actual_value"], 0.0649)
            self.assertEqual(edge["result"], "FAIL")
            score = self._find_gate(item, "Score")
            self.assertEqual(score["required"], "score >= 7")
            self.assertEqual(score["actual"], 4)
            self.assertEqual(score["result"], "FAIL")
            self.assertIn("EDGE_BELOW_THRESHOLD", item["blocking_reasons"])
            self.assertIn("Arena verdict harus naik", " ".join(item["what_needs_to_improve"]))

    def test_missing_fields_are_reported_not_faked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sf = root / "sf"
            arena = root / "arena"
            phase6 = root / "phase6"
            sf.mkdir()
            arena.mkdir()
            phase6.mkdir()
            self._write_artifacts(sf, arena, phase6, with_oi=False)

            item = CandidateNumericEvidenceBuilder(sf, arena, phase6).build()["items"][0]

            oi = self._find_metric(item, "oi_change_pct")
            self.assertEqual(oi["result"], "UNAVAILABLE")
            self.assertEqual(oi["actual_detail"], "EVIDENCE_FIELD_NOT_EXPOSED")
            self.assertIn("oi_change_pct", item["missing_evidence_fields"])

    def test_endpoint_reads_artifact_without_db_or_binance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "candidate_numeric_evidence_audit.json"
            artifact.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-01-01T00:00:00+00:00",
                        "aggregate": {"total_candidates": 1},
                        "rule_thresholds": {},
                        "field_availability": {},
                        "glossary": {},
                        "items": [{"symbol": "AAAUSDT", "timeframe": "15m", "candidate_status": "SIGNAL_CANDIDATE"}],
                    }
                )
            )
            with patch("app.api.routes.CandidateNumericEvidenceArtifactService", lambda: CandidateNumericEvidenceArtifactService(artifact)):
                response = TestClient(app).get("/api/phase7/candidate-evidence?symbol=AAAUSDT")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["count"], 1)
            self.assertTrue(payload["not_live_signal"])
            self.assertEqual(payload["items"][0]["symbol"], "AAAUSDT")

    def _find_metric(self, item: dict, metric: str) -> dict:
        return next(row for row in item["numeric_evidence"] if row["metric"] == metric)

    def _find_gate(self, item: dict, gate: str) -> dict:
        return next(row for row in item["phase7_checklist"] if row["gate"] == gate)

    def _write_artifacts(self, sf: Path, arena: Path, phase6: Path, with_oi: bool = True) -> None:
        feature = {
            "symbol": "AAAUSDT",
            "timeframe": "15m",
            "window_start": "2026-01-01T00:00:00",
            "window_end": "2026-01-01T00:15:00",
            "price_return": 0.42,
            "volume_sum": 1000,
            "volume_ratio_vs_lookback": 2.0,
            "close_position_in_range": 0.8,
            "relative_return": 0.6,
            "relative_strength": "OUTPERFORMING",
            "funding_rate": 0.0,
            "futures_led_flag": True,
            "atr": 1.2,
            "feature_status": "PARTIAL_DATA",
        }
        if with_oi:
            feature["oi_change_pct"] = 0.2
        candidate = {
            "symbol": "AAAUSDT",
            "timeframe": "15m",
            "window_start": "2026-01-01T00:00:00",
            "window_end": "2026-01-01T00:15:00",
            "setup_type": "MID_LONG",
            "direction": "BULLISH_CONTEXT",
            "confidence": "LOW",
            "candidate_status": "SIGNAL_CANDIDATE",
            "feature_status": "PARTIAL_DATA",
            "atr_reference_timeframe": "1h",
            "atr_reference_status": "AVAILABLE",
            "conflict_status": "NONE",
            "not_live_signal": True,
            "not_execution_instruction": True,
            "evidence": {},
            "reason": "Price up impulse with open interest expansion",
        }
        arena_row = {
            "setup_family": "MID_LONG",
            "horizon": "15m",
            "atr_mult": 0.75,
            "rr": 2.5,
            "sample_size": 100,
            "pessimistic_avg_r": 0.0429,
            "tp_first_share": 1.1,
            "sl_first_share": 2.7,
            "verdict": "NOISY",
        }
        baseline_row = {
            "setup_family": "NO_SIGNAL_BASELINE_LONG",
            "horizon": "15m",
            "atr_mult": 0.75,
            "rr": 2.5,
            "sample_size": 200,
            "pessimistic_avg_r": -0.022,
            "verdict": "REJECT",
        }
        edge = {
            **candidate,
            "mapped_setup_family": "MID_LONG",
            "direction_side": "LONG",
            "arena_match": arena_row,
            "baseline_match": baseline_row,
            "setup_pessR": 0.0429,
            "baseline_pessR": -0.022,
            "edge_vs_baseline": 0.0649,
            "beats_baseline": True,
            "total_score": 4,
            "phase7_verdict": "WATCHLIST_FOR_MORE_DATA",
            "rejection_reasons": [],
        }
        (sf / "features.json").write_text(json.dumps({"items": [feature]}))
        (sf / "candidates.json").write_text(json.dumps({"items": [candidate]}))
        (sf / "summary.json").write_text(json.dumps({"candidate_count": 1}))
        (arena / "results.json").write_text(json.dumps({"results": [arena_row, baseline_row]}))
        (arena / "leaderboard.json").write_text(json.dumps({"summary": {}}))
        (phase6 / "setup_edge_audit.json").write_text(json.dumps({"rows": [edge]}))
        (phase6 / "readiness_summary.json").write_text(json.dumps({}))
        (phase6 / "phase7_candidate_decision.json").write_text(
            json.dumps({"phase7_decision": "NO_PHASE7_CANDIDATE_YET", "approved_candidates": []})
        )


if __name__ == "__main__":
    unittest.main()
