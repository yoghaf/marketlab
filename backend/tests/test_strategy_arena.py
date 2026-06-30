from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.strategy_arena import (
    CandidateRow,
    Candle,
    DEFAULT_ATR_MULTIPLIERS,
    DEFAULT_RR_VALUES,
    SETUP_FAMILIES,
    StrategyArenaArtifactService,
    StrategyArenaRunner,
    calculate_atr14,
    candidate_matches_setup,
    evaluate_path,
    future_window,
)


class StrategyArenaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 1, 1, tzinfo=UTC)
        self.candidate = CandidateRow(
            symbol="AAAUSDT",
            window_open_time=self.base_time,
            window_close_time=self.base_time + timedelta(minutes=15),
            candidate_type="MID_SHORT_CONTEXT_READONLY",
            evidence={
                "spot_support_status_15m": "FUTURES_LED",
                "supporting_psychology_labels": ["FUTURES_LED_MOVE"],
                "price_return_pct_15m": "-0.5",
            },
            entry=Decimal("100"),
            universe_rank=1,
        )

    def test_atr_uses_only_closed_candles_before_or_at_signal(self) -> None:
        candles = []
        start = self.base_time
        for index in range(16):
            open_time = start + timedelta(hours=index)
            high = Decimal("2000") if index == 15 else Decimal("110")
            low = Decimal("90")
            candles.append(
                Candle(
                    open_time=open_time,
                    close_time=open_time + timedelta(hours=1),
                    open=Decimal("100"),
                    high=high,
                    low=low,
                    close=Decimal("100"),
                )
            )
        close_times = [candle.close_time for candle in candles]

        atr = calculate_atr14(candles, close_times, candles[14].close_time)

        self.assertEqual(atr, Decimal("20"))

    def test_long_tp_first(self) -> None:
        outcome, r_value, unresolved = evaluate_path(
            self.candidate,
            [self._future_candle(high="112", low="99", close="111")],
            "LONG",
            Decimal("10"),
            Decimal("1"),
        )

        self.assertEqual(outcome, "TP_FIRST")
        self.assertEqual(r_value, Decimal("1"))
        self.assertIsNone(unresolved)

    def test_long_sl_first(self) -> None:
        outcome, r_value, _unresolved = evaluate_path(
            self.candidate,
            [self._future_candle(high="101", low="89", close="90")],
            "LONG",
            Decimal("10"),
            Decimal("1"),
        )

        self.assertEqual(outcome, "SL_FIRST")
        self.assertEqual(r_value, Decimal("-1"))

    def test_short_tp_first(self) -> None:
        outcome, r_value, _unresolved = evaluate_path(
            self.candidate,
            [self._future_candle(high="101", low="89", close="90")],
            "SHORT",
            Decimal("10"),
            Decimal("1"),
        )

        self.assertEqual(outcome, "TP_FIRST")
        self.assertEqual(r_value, Decimal("1"))

    def test_short_sl_first(self) -> None:
        outcome, r_value, _unresolved = evaluate_path(
            self.candidate,
            [self._future_candle(high="111", low="99", close="110")],
            "SHORT",
            Decimal("10"),
            Decimal("1"),
        )

        self.assertEqual(outcome, "SL_FIRST")
        self.assertEqual(r_value, Decimal("-1"))

    def test_both_same_candle_is_ambiguous(self) -> None:
        outcome, r_value, unresolved = evaluate_path(
            self.candidate,
            [self._future_candle(high="111", low="89", close="100")],
            "SHORT",
            Decimal("10"),
            Decimal("1"),
        )

        self.assertEqual(outcome, "BOTH_SAME_CANDLE")
        self.assertIsNone(r_value)
        self.assertIsNone(unresolved)

    def test_neither_close_r(self) -> None:
        outcome, r_value, unresolved = evaluate_path(
            self.candidate,
            [self._future_candle(high="105", low="95", close="97")],
            "SHORT",
            Decimal("10"),
            Decimal("1"),
        )

        self.assertEqual(outcome, "NEITHER")
        self.assertEqual(r_value, Decimal("0.3"))
        self.assertEqual(unresolved, Decimal("0.3"))

    def test_insufficient_forward_data_returns_none(self) -> None:
        candles = [self._future_candle(high="101", low="99", close="100")]
        opens = [candle.open_time for candle in candles]

        self.assertIsNone(future_window(candles, opens, self.candidate.window_close_time, 4))

    def test_setup_family_mapping_and_futures_led_split(self) -> None:
        futures_led_setup = next(setup for setup in SETUP_FAMILIES if setup.setup_family == "MID_SHORT_FUTURES_LED")
        non_futures_led_setup = next(setup for setup in SETUP_FAMILIES if setup.setup_family == "MID_SHORT_NON_FUTURES_LED")

        self.assertTrue(candidate_matches_setup(self.candidate, futures_led_setup))
        self.assertFalse(candidate_matches_setup(self.candidate, non_futures_led_setup))

    def test_baseline_long_short_generation_present(self) -> None:
        names = {setup.setup_family for setup in SETUP_FAMILIES}

        self.assertIn("NO_SIGNAL_BASELINE_SHORT", names)
        self.assertIn("NO_SIGNAL_BASELINE_LONG", names)

    def test_duplicate_combo_prevention_and_verdict_basic(self) -> None:
        runner = StrategyArenaRunner(
            min_sample=1,
            horizons={"15m": 1},
            atr_multipliers=[Decimal("1.0")],
            rr_values=[Decimal("1.0")],
        )
        rows = [
            {"symbol": f"AAA{index}USDT", "universe_rank": index, "outcome": "TP_FIRST", "r": Decimal("1"), "unresolved_close_r": None}
            for index in range(1, 11)
        ]
        summary = runner._summarize(
            SETUP_FAMILIES[0],
            Decimal("1.0"),
            Decimal("1.0"),
            "15m",
            rows,
            0,
        )

        self.assertEqual(summary["verdict"], "PROMISING_FOR_FORWARD_TEST")
        keys = {(summary["setup_family"], summary["atr_mult"], summary["rr"], summary["horizon"])}
        self.assertEqual(len(keys), 1)

    def test_artifact_schema_and_api_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "leaderboard.json").write_text(json.dumps({"top_by_pessimistic_avg_r": [], "summary": {}}))
            (artifact_dir / "results.json").write_text(
                json.dumps({"results": [{"setup_family": "MID_SHORT_FUTURES_LED"}], "metadata": {}})
            )
            service = StrategyArenaArtifactService(artifact_dir)

            self.assertIn("top_by_pessimistic_avg_r", service.leaderboard())
            self.assertEqual(service.setup("MID_SHORT_FUTURES_LED")["count"], 1)

            with patch("app.api.routes.StrategyArenaArtifactService", return_value=service):
                client = TestClient(app)
                response = client.get("/api/strategy-arena/v1/leaderboard")

            self.assertEqual(response.status_code, 200)
            self.assertIn("summary", response.json())

    def _future_candle(self, high: str, low: str, close: str) -> Candle:
        return Candle(
            open_time=self.candidate.window_close_time,
            close_time=self.candidate.window_close_time + timedelta(minutes=15),
            open=Decimal("100"),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
        )


if __name__ == "__main__":
    unittest.main()
