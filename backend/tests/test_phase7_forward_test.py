import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.phase7_forward_test import Phase7ForwardTestArtifactService, Phase7ForwardTestService


class Phase7ForwardTestServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "marketlab.db"
        self.phase6_dir = self.root / "phase6"
        self.signal_factory_dir = self.root / "signal_factory"
        self.strategy_arena_dir = self.root / "arena"
        self.artifact_dir = self.root / "phase7"
        for path in (self.phase6_dir, self.signal_factory_dir, self.strategy_arena_dir, self.artifact_dir):
            path.mkdir(parents=True)
        self.observation = datetime(2026, 1, 1, 15, 0, tzinfo=UTC)
        self._create_db()
        self._write_required_artifacts([])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_no_approved_candidate_writes_waiting_artifacts(self) -> None:
        payload = self._service().run()

        self.assertEqual(payload["status"]["mode"], "WAITING_FOR_APPROVED_CANDIDATE")
        self.assertEqual(payload["status"]["approved_candidate_count"], 0)
        self.assertEqual(payload["events"]["events"], [])
        self.assertTrue((self.artifact_dir / "forward_test_status.json").exists())

    def test_approved_candidate_creates_deterministic_read_only_event(self) -> None:
        self._insert_reference_candles("AAAUSDT")
        self._write_required_artifacts([self._approved_candidate("AAAUSDT", "MID_LONG", "BULLISH_CONTEXT")])

        first = self._service().run()
        second = self._service().run()

        self.assertEqual(first["status"]["created_event_count"], 1)
        self.assertEqual(second["status"]["created_event_count"], 0)
        self.assertEqual(len(second["events"]["events"]), 1)
        event = second["events"]["events"][0]
        self.assertFalse(event["is_live_signal"])
        self.assertFalse(event["is_execution"])
        self.assertEqual(event["event_id"], first["events"]["events"][0]["event_id"])

    def test_missing_reference_prevents_active_event_creation(self) -> None:
        self._write_required_artifacts([self._approved_candidate("AAAUSDT", "MID_LONG", "BULLISH_CONTEXT")])

        payload = self._service().run()

        event = payload["events"]["events"][0]
        self.assertEqual(event["status"], "CANNOT_CREATE_EVENT_MISSING_REFERENCE")
        self.assertEqual(payload["results"]["results"][0]["result_status"], "CANNOT_EVALUATE")

    def test_long_take_profit_hit(self) -> None:
        result = self._run_single_outcome("MID_LONG", "BULLISH_CONTEXT", [(self.observation, "100", "105", "99", "104")])

        self.assertEqual(result["result_status"], "TP_HIT")
        self.assertEqual(result["realized_R"], 2.0)

    def test_long_stop_hit(self) -> None:
        result = self._run_single_outcome("MID_LONG", "BULLISH_CONTEXT", [(self.observation, "100", "101", "97", "98")])

        self.assertEqual(result["result_status"], "SL_HIT")
        self.assertEqual(result["realized_R"], -1.0)

    def test_short_take_profit_hit(self) -> None:
        result = self._run_single_outcome("MID_SHORT", "BEARISH_CONTEXT", [(self.observation, "100", "101", "95", "96")])

        self.assertEqual(result["result_status"], "TP_HIT")
        self.assertEqual(result["realized_R"], 2.0)

    def test_short_stop_hit(self) -> None:
        result = self._run_single_outcome("MID_SHORT", "BEARISH_CONTEXT", [(self.observation, "100", "103", "99", "102")])

        self.assertEqual(result["result_status"], "SL_HIT")
        self.assertEqual(result["realized_R"], -1.0)

    def test_same_candle_both_hit_is_ambiguous(self) -> None:
        result = self._run_single_outcome("MID_LONG", "BULLISH_CONTEXT", [(self.observation, "100", "105", "97", "101")])

        self.assertEqual(result["result_status"], "BOTH_HIT_SAME_CANDLE")
        self.assertTrue(result["ambiguous_same_candle"])
        self.assertIsNone(result["realized_R"])

    def test_not_enough_forward_candles_stays_unknown(self) -> None:
        self._insert_reference_candles("AAAUSDT")
        self._write_required_artifacts([self._approved_candidate("AAAUSDT", "MID_LONG", "BULLISH_CONTEXT", horizon="1h")])

        payload = self._service().run()

        self.assertEqual(payload["results"]["results"][0]["result_status"], "UNKNOWN_FORWARD_DATA")
        self.assertEqual(payload["events"]["events"][0]["status"], "WAITING_OUTCOME")

    def test_artifact_reader_returns_safe_default(self) -> None:
        service = Phase7ForwardTestArtifactService(self.root / "missing_phase7")

        self.assertEqual(service.status()["mode"], "ARTIFACT_NOT_FOUND")
        self.assertEqual(service.events()["events"], [])
        self.assertEqual(service.results()["results"], [])
        self.assertEqual(service.summary()["total_events"], 0)

    def _run_single_outcome(self, setup: str, direction: str, future_candles: list[tuple[datetime, str, str, str, str]]) -> dict:
        self._insert_reference_candles("AAAUSDT")
        self._insert_future_15m("AAAUSDT", future_candles)
        self._write_required_artifacts([self._approved_candidate("AAAUSDT", setup, direction)])

        payload = self._service().run()

        return payload["results"]["results"][0]

    def _service(self) -> Phase7ForwardTestService:
        return Phase7ForwardTestService(
            db_path=self.db_path,
            phase6_dir=self.phase6_dir,
            signal_factory_dir=self.signal_factory_dir,
            strategy_arena_dir=self.strategy_arena_dir,
            artifact_dir=self.artifact_dir,
        )

    def _create_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for table in ("futures_klines_15m", "futures_klines_1h"):
                conn.execute(
                    f"""
                    CREATE TABLE {table} (
                        symbol TEXT NOT NULL,
                        open_time TEXT NOT NULL,
                        close_time TEXT NOT NULL,
                        open TEXT NOT NULL,
                        high TEXT NOT NULL,
                        low TEXT NOT NULL,
                        close TEXT NOT NULL,
                        aggregation_status TEXT NOT NULL
                    )
                    """
                )

    def _insert_reference_candles(self, symbol: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for i in range(15):
                close_time = self.observation - timedelta(hours=14 - i)
                conn.execute(
                    """
                    INSERT INTO futures_klines_1h VALUES (?, ?, ?, ?, ?, ?, ?, 'AGG_READY')
                    """,
                    (
                        symbol,
                        self._db_time(close_time - timedelta(hours=1)),
                        self._db_time(close_time),
                        "100",
                        "101",
                        "99",
                        "100",
                    ),
                )
            conn.execute(
                """
                INSERT INTO futures_klines_15m VALUES (?, ?, ?, ?, ?, ?, ?, 'AGG_READY')
                """,
                (
                    symbol,
                    self._db_time(self.observation - timedelta(minutes=15)),
                    self._db_time(self.observation),
                    "100",
                    "101",
                    "99",
                    "100",
                ),
            )

    def _insert_future_15m(self, symbol: str, candles: list[tuple[datetime, str, str, str, str]]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for open_time, open_price, high, low, close in candles:
                conn.execute(
                    """
                    INSERT INTO futures_klines_15m VALUES (?, ?, ?, ?, ?, ?, ?, 'AGG_READY')
                    """,
                    (
                        symbol,
                        self._db_time(open_time),
                        self._db_time(open_time + timedelta(minutes=15)),
                        open_price,
                        high,
                        low,
                        close,
                    ),
                )

    def _write_required_artifacts(self, approved: list[dict]) -> None:
        edge_rows = []
        for row in approved:
            edge_rows.append(
                {
                    "symbol": row["symbol"],
                    "timeframe": row["timeframe"],
                    "setup_type": row["setup_type"],
                    "window_end": row["window_end"],
                    "direction_side": row["direction_side"],
                    "arena_match": row["arena_match"],
                    "edge_vs_baseline": row["edge_vs_baseline"],
                    "total_score": row["total_score"],
                    "phase7_verdict": row["phase7_verdict"],
                }
            )
        self._write_json(self.phase6_dir / "phase7_candidate_decision.json", {"approved_candidates": approved})
        self._write_json(self.phase6_dir / "setup_edge_audit.json", {"rows": edge_rows})
        self._write_json(self.signal_factory_dir / "candidates.json", {"items": []})
        self._write_json(self.strategy_arena_dir / "results.json", {"results": []})
        self._write_json(self.strategy_arena_dir / "leaderboard.json", {"top_by_pessimistic_avg_r": []})

    def _approved_candidate(self, symbol: str, setup: str, direction: str, horizon: str = "15m") -> dict:
        direction_side = "LONG" if direction == "BULLISH_CONTEXT" else "SHORT"
        return {
            "symbol": symbol,
            "timeframe": "15m",
            "setup_type": setup,
            "mapped_setup_family": setup,
            "direction": direction,
            "direction_side": direction_side,
            "confidence": "HIGH",
            "window_end": self.observation.isoformat(),
            "recommended_arena_horizon": horizon,
            "recommended_atr_mult": 1.0,
            "recommended_rr": 2.0,
            "arena_verdict": "MONITOR_MORE",
            "arena_match": {"verdict": "MONITOR_MORE", "horizon": horizon, "atr_mult": 1.0, "rr": 2.0},
            "edge_vs_baseline": 0.12,
            "total_score": 8,
            "phase7_verdict": "PHASE7_READY",
            "atr_reference_timeframe": "1h",
        }

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _db_time(self, value: datetime) -> str:
        return value.replace(tzinfo=None).isoformat(sep=" ")


if __name__ == "__main__":
    unittest.main()
