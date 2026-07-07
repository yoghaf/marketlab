from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from app.services.native_ohlcv_backfill import native_kline_to_aggregate_values


class NativeOhlcvBackfillTest(unittest.TestCase):
    def test_native_daily_kline_payload_is_json_ready_aggregate(self) -> None:
        now = datetime(2026, 7, 7, 1, 0, tzinfo=UTC)
        row = [
            1_783_296_000_000,
            "100.0",
            "110.0",
            "90.0",
            "105.0",
            "1000.0",
            1_783_382_399_999,
            "105000.0",
            123,
            "600.0",
            "63000.0",
            "0",
        ]

        payload = native_kline_to_aggregate_values("BTCUSDT", row, "24h", "1d", 1440, now)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["symbol"], "BTCUSDT")
        self.assertEqual(payload["source_interval"], "1d")
        self.assertEqual(payload["aggregation_status"], "AGG_READY")
        self.assertEqual(payload["open"], Decimal("100.0"))
        self.assertEqual(payload["close"], Decimal("105.0"))
        self.assertEqual(payload["volume"], Decimal("1000.0"))
        self.assertEqual(payload["taker_buy_base_volume"], Decimal("600.0"))
        self.assertEqual(payload["taker_sell_base_volume"], Decimal("400.0"))
        self.assertEqual(payload["expected_1m_count"], 1)
        self.assertEqual(payload["actual_1m_count"], 1)
        self.assertEqual(payload["missing_1m_count"], 0)

    def test_unclosed_native_kline_is_skipped(self) -> None:
        now = datetime(2026, 7, 7, 1, 0, tzinfo=UTC)
        current_day_row = [
            1_783_468_800_000,
            "100.0",
            "110.0",
            "90.0",
            "105.0",
            "1000.0",
            1_783_555_199_999,
            "105000.0",
            123,
            "600.0",
            "63000.0",
            "0",
        ]

        payload = native_kline_to_aggregate_values("BTCUSDT", current_day_row, "24h", "1d", 1440, now)

        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
