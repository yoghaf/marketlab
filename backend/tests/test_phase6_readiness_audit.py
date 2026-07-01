from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.phase6_readiness_audit import (
    Phase6ArtifactService,
    Phase6ReadinessAuditRunner,
    StrategyArenaIndex,
    audit_candidate_readiness,
    audit_feature_readiness,
    build_phase7_decision,
    evaluate_candidates_for_phase7,
    is_candidate_eligible,
    load_phase6_inputs,
    relative_strength_flags,
)


class Phase6ReadinessAuditTest(unittest.TestCase):
    def test_artifact_missing_handled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_phase6_inputs(Path(tmp) / "sf", Path(tmp) / "arena")

        self.assertEqual(loaded["artifact_status"], "MISSING_ARTIFACT")
        self.assertTrue(loaded["missing_artifacts"])

    def test_feature_readiness_summary(self) -> None:
        features = [
            {"timeframe": "15m", "feature_status": "READY"},
            {"timeframe": "15m", "feature_status": "PARTIAL_DATA"},
            {"timeframe": "15m", "feature_status": "MISSING_CANDLES"},
            {"timeframe": "1h", "feature_status": "PARTIAL_DATA"},
        ]

        summary = audit_feature_readiness(features)

        self.assertEqual(summary["by_timeframe"]["15m"]["total_feature_rows"], 3)
        self.assertEqual(summary["by_timeframe"]["15m"]["ready_count"], 1)
        self.assertEqual(summary["by_timeframe"]["1h"]["readiness_status"], "TIMEFRAME_PARTIAL_USABLE")

    def test_candidate_eligibility_filter(self) -> None:
        candidate = self._candidate(status="SIGNAL_CANDIDATE", feature_status="PARTIAL_DATA")
        blocked = self._candidate(status="TIMEFRAME_NOT_READY", feature_status="MISSING_CANDLES")

        self.assertTrue(is_candidate_eligible(candidate))
        self.assertFalse(is_candidate_eligible(blocked))
        readiness = audit_candidate_readiness([candidate, blocked])
        self.assertEqual(readiness["eligible_candidate_count"], 1)

    def test_strategy_arena_mapping_and_baseline(self) -> None:
        index = StrategyArenaIndex(self._arena_results())
        rows = evaluate_candidates_for_phase7([self._candidate()], index)
        row = rows[0]

        self.assertEqual(row["mapped_setup_family"], "MID_SHORT_FUTURES_LED")
        self.assertEqual(row["arena_match"]["setup_family"], "MID_SHORT_FUTURES_LED")
        self.assertEqual(row["baseline_match"]["setup_family"], "NO_SIGNAL_BASELINE_SHORT")
        self.assertGreater(row["edge_vs_baseline"], 0)
        self.assertTrue(row["beats_baseline"])

    def test_relative_strength_supports_long_short_and_warns_against_direction(self) -> None:
        short = self._candidate(relative_strength="UNDERPERFORMING", direction="BEARISH_CONTEXT")
        long = self._candidate(relative_strength="OUTPERFORMING", direction="BULLISH_CONTEXT", setup_type="MID_LONG")
        bad_short = self._candidate(relative_strength="OUTPERFORMING", direction="BEARISH_CONTEXT")

        self.assertIn("RELATIVE_STRENGTH_SUPPORTS_DIRECTION", relative_strength_flags(short, "SHORT")["flags"])
        self.assertIn("RELATIVE_STRENGTH_SUPPORTS_DIRECTION", relative_strength_flags(long, "LONG")["flags"])
        self.assertIn("RELATIVE_STRENGTH_AGAINST_DIRECTION", relative_strength_flags(bad_short, "SHORT")["flags"])

    def test_score_phase7_ready_watchlist_and_reject(self) -> None:
        index = StrategyArenaIndex(self._arena_results())
        ready = evaluate_candidates_for_phase7([self._candidate(confidence="HIGH")], index)[0]
        watch = evaluate_candidates_for_phase7([self._candidate(confidence="MEDIUM", relative_strength="INLINE_WITH_MARKET")], index)[0]
        reject = evaluate_candidates_for_phase7([self._candidate(status="TIMEFRAME_NOT_READY", feature_status="MISSING_CANDLES")], index)[0]

        self.assertEqual(ready["phase7_verdict"], "PHASE7_READY")
        self.assertIn(watch["phase7_verdict"], {"PHASE7_READY", "WATCHLIST_FOR_MORE_DATA"})
        self.assertEqual(reject["phase7_verdict"], "REJECT_FOR_PHASE7")

    def test_phase7_decision_no_candidates_and_has_candidates(self) -> None:
        rejected = [{"phase7_verdict": "REJECT_FOR_PHASE7", "rejection_reasons": ["TEST"], "total_score": -1}]
        approved = [
            {
                **self._candidate(),
                "phase7_verdict": "PHASE7_READY",
                "rejection_reasons": [],
                "total_score": 8,
                "arena_match": {"horizon": "15m", "atr_mult": 1, "rr": 2, "verdict": "PROMISING_FOR_FORWARD_TEST"},
                "setup_pessR": 0.2,
                "baseline_pessR": 0.0,
                "edge_vs_baseline": 0.2,
                "mapped_setup_family": "MID_SHORT_FUTURES_LED",
            }
        ]

        self.assertEqual(build_phase7_decision("now", rejected)["phase7_decision"], "NO_PHASE7_CANDIDATE_YET")
        self.assertEqual(build_phase7_decision("now", approved)["phase7_decision"], "HAS_CANDIDATES")

    def test_runner_and_api_read_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sf = root / "sf"
            arena = root / "arena"
            out = root / "phase6"
            sf.mkdir()
            arena.mkdir()
            (sf / "features.json").write_text(json.dumps({"items": [{"timeframe": "15m", "feature_status": "READY"}]}))
            (sf / "candidates.json").write_text(json.dumps({"items": [self._candidate(confidence="HIGH")]}))
            (sf / "summary.json").write_text(json.dumps({"candidate_count": 1}))
            (arena / "results.json").write_text(json.dumps({"metadata": {}, "results": self._arena_results()}))
            (arena / "leaderboard.json").write_text(json.dumps({"summary": {}}))

            result = Phase6ReadinessAuditRunner(sf, arena, out, root / "report.md").run()
            self.assertEqual(result.readiness_summary["phase6_status"], "PASS")

            service = Phase6ArtifactService(out)
            with patch("app.api.routes.Phase6ArtifactService", return_value=service):
                response = TestClient(app).get("/api/phase6/readiness")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["artifact_status"], "OK")

    def _candidate(
        self,
        status: str = "SIGNAL_CANDIDATE",
        feature_status: str = "READY",
        confidence: str = "MEDIUM",
        relative_strength: str = "UNDERPERFORMING",
        direction: str = "BEARISH_CONTEXT",
        setup_type: str = "MID_SHORT",
    ) -> dict:
        return {
            "symbol": "AAAUSDT",
            "timeframe": "15m",
            "setup_type": setup_type,
            "direction": direction,
            "confidence": confidence,
            "candidate_status": status,
            "feature_status": feature_status,
            "atr_reference_status": "AVAILABLE",
            "atr_reference_timeframe": "1h",
            "not_live_signal": True,
            "not_execution_instruction": True,
            "reason": "test",
            "evidence": {
                "futures_led_flag": True,
                "spot_led_flag": False,
                "relative_strength": relative_strength,
                "price_return": -0.7 if direction == "BEARISH_CONTEXT" else 0.7,
                "oi_change_pct": 0.3,
                "volume_spike": True,
                "anomalies": ["TEST"],
            },
        }

    def _arena_results(self) -> list[dict]:
        return [
            {
                "setup_family": "MID_SHORT_FUTURES_LED",
                "horizon": "15m",
                "atr_mult": 1.0,
                "rr": 2.0,
                "sample_size": 100,
                "pessimistic_avg_r": 0.25,
                "resolved_avg_r": 0.2,
                "verdict": "PROMISING_FOR_FORWARD_TEST",
            },
            {
                "setup_family": "NO_SIGNAL_BASELINE_SHORT",
                "horizon": "15m",
                "atr_mult": 1.0,
                "rr": 2.0,
                "sample_size": 100,
                "pessimistic_avg_r": 0.02,
                "resolved_avg_r": 0.0,
                "verdict": "NOISY",
            },
            {
                "setup_family": "MID_LONG",
                "horizon": "15m",
                "atr_mult": 1.0,
                "rr": 2.0,
                "sample_size": 100,
                "pessimistic_avg_r": 0.03,
                "resolved_avg_r": 0.0,
                "verdict": "NOISY",
            },
            {
                "setup_family": "NO_SIGNAL_BASELINE_LONG",
                "horizon": "15m",
                "atr_mult": 1.0,
                "rr": 2.0,
                "sample_size": 100,
                "pessimistic_avg_r": 0.01,
                "resolved_avg_r": 0.0,
                "verdict": "NOISY",
            },
        ]


if __name__ == "__main__":
    unittest.main()
