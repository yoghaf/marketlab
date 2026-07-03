from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.services.multitimeframe_features import (
    MultiTimeframeFeatureService,
    TimeframeCandle,
    aggregate_candles,
    calculate_atr,
)


class MultiTimeframeFeaturesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "marketlab.db"
        self.base = datetime(2026, 1, 1, tzinfo=UTC)
        self._create_db()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_1h_aggregation_uses_four_complete_15m_candles(self) -> None:
        rows = self._candles(4, minutes=15)

        agg = aggregate_candles(rows, "1h")

        self.assertEqual(len(agg), 1)
        self.assertEqual(agg[0].open, rows[0].open)
        self.assertEqual(agg[0].high, max(row.high for row in rows))
        self.assertEqual(agg[0].low, min(row.low for row in rows))
        self.assertEqual(agg[0].close, rows[-1].close)
        self.assertEqual(agg[0].volume, sum((row.volume for row in rows), Decimal("0")))

    def test_4h_and_24h_aggregation_require_complete_boundaries(self) -> None:
        self.assertEqual(len(aggregate_candles(self._candles(16, minutes=15), "4h")), 1)
        self.assertEqual(len(aggregate_candles(self._candles(96, minutes=15), "24h")), 1)
        self.assertEqual(len(aggregate_candles(self._candles(95, minutes=15), "24h")), 0)

    def test_atr_uses_only_passed_candles(self) -> None:
        candles = self._candles(16, minutes=60)
        future_spike = self._candle(16, minutes=60, high=Decimal("1000"), low=Decimal("1"))

        atr_without_future = calculate_atr(candles)
        atr_with_future_excluded = calculate_atr((candles + [future_spike])[:-1])

        self.assertEqual(atr_without_future, atr_with_future_excluded)

    def test_latest_feature_snapshot_calculates_core_fields(self) -> None:
        self._insert_symbol("BTCUSDT")
        candles = self._candles(17, minutes=15)
        for index, candle in enumerate(candles):
            volume = Decimal("400") if index == 16 else Decimal("100")
            self._insert_kline("futures_klines_15m", candle, volume=volume)
            self._insert_kline("spot_klines_15m", candle, volume=Decimal("120"))
            self._insert_oi("BTCUSDT", candle.open_time, Decimal("1000") + Decimal(index))
            self._insert_oi("BTCUSDT", candle.close_time, Decimal("1001") + Decimal(index))
        self._insert_funding("BTCUSDT", candles[-1].close_time, Decimal("0.0001"))

        feature = MultiTimeframeFeatureService(self.db_path).latest_feature_snapshot("BTCUSDT", "15m")

        self.assertEqual(feature.feature_status, "READY")
        self.assertTrue(feature.volume_spike)
        self.assertTrue(feature.oi_expansion)
        self.assertIsNotNone(feature.price_return)
        self.assertIsNotNone(feature.atr)
        self.assertEqual(feature.relative_strength, "INLINE_WITH_MARKET")

    def test_latest_feature_snapshot_reads_rich_and_state_with_sqlite_microseconds(self) -> None:
        self._insert_symbol("BTCUSDT")
        candles = self._candles(17, minutes=15)
        for index, candle in enumerate(candles):
            self._insert_kline("futures_klines_15m", candle, volume=Decimal("100"))
            self._insert_kline("spot_klines_15m", candle, volume=Decimal("100"))
            self._insert_oi("BTCUSDT", candle.open_time, Decimal("1000") + Decimal(index))
            self._insert_oi("BTCUSDT", candle.close_time, Decimal("1001") + Decimal(index))
        self._insert_funding("BTCUSDT", candles[-1].close_time, Decimal("0.0001"))
        self._insert_rich_alignment("BTCUSDT", candles[-1].open_time, candles[-1].close_time)
        self._insert_market_state("BTCUSDT", candles[-1].open_time, candles[-1].close_time)

        feature = MultiTimeframeFeatureService(self.db_path).latest_feature_snapshot("BTCUSDT", "15m")

        self.assertEqual(feature.rich_alignment_status, "ALIGNED")
        self.assertEqual(feature.global_long_short_ratio, Decimal("1.23"))
        self.assertEqual(feature.top_trader_position_ratio, Decimal("0.91"))
        self.assertEqual(feature.top_trader_account_ratio, Decimal("1.11"))
        self.assertEqual(feature.snapshot_alignment_status, "FRESH")
        self.assertEqual(feature.futures_spread_pct, Decimal("0.02"))
        self.assertEqual(feature.spot_spread_pct, Decimal("0.03"))

    def test_missing_candles_status_is_not_ready(self) -> None:
        self._insert_symbol("AAAUSDT")

        feature = MultiTimeframeFeatureService(self.db_path).latest_feature_snapshot("AAAUSDT", "15m")

        self.assertEqual(feature.feature_status, "MISSING_CANDLES")

    def _create_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE marketlab_active_universe (symbol TEXT, rank INTEGER, is_active INTEGER)")
        for market in ("futures", "spot"):
            for timeframe in ("15m", "1h", "4h", "24h"):
                conn.execute(
                    f"""
                    CREATE TABLE {market}_klines_{timeframe} (
                        symbol TEXT,
                        open_time TEXT,
                        close_time TEXT,
                        open TEXT,
                        high TEXT,
                        low TEXT,
                        close TEXT,
                        volume TEXT,
                        quote_volume TEXT,
                        number_of_trades INTEGER,
                        aggregation_status TEXT
                    )
                    """
                )
        conn.execute("CREATE TABLE futures_open_interest_history (symbol TEXT, timestamp TEXT, sum_open_interest TEXT)")
        conn.execute("CREATE TABLE futures_funding_history (symbol TEXT, funding_time TEXT, funding_rate TEXT)")
        conn.execute(
            """
            CREATE TABLE rich_futures_5m_alignment (
                symbol TEXT,
                timeframe TEXT,
                window_open_time TEXT,
                window_close_time TEXT,
                alignment_status TEXT,
                global_long_short_ratio_avg TEXT,
                top_trader_position_ratio_avg TEXT,
                top_trader_account_ratio_avg TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE market_state_alignment (
                symbol TEXT,
                timeframe TEXT,
                window_open_time TEXT,
                window_close_time TEXT,
                snapshot_alignment_status TEXT,
                futures_spread_pct TEXT,
                spot_spread_pct TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    def _insert_symbol(self, symbol: str) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("INSERT INTO marketlab_active_universe VALUES (?, ?, ?)", (symbol, 1, 1))
            conn.commit()

    def _insert_kline(self, table: str, candle: TimeframeCandle, volume: Decimal) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candle.symbol,
                    candle.open_time.isoformat(sep=" "),
                    candle.close_time.isoformat(sep=" "),
                    str(candle.open),
                    str(candle.high),
                    str(candle.low),
                    str(candle.close),
                    str(volume),
                    str(volume * Decimal("100")),
                    10,
                    "AGG_READY",
                ),
            )
            conn.commit()

    def _insert_oi(self, symbol: str, when: datetime, value: Decimal) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO futures_open_interest_history VALUES (?, ?, ?)",
                (symbol, when.isoformat(sep=" "), str(value)),
            )
            conn.commit()

    def _insert_funding(self, symbol: str, when: datetime, value: Decimal) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO futures_funding_history VALUES (?, ?, ?)",
                (symbol, when.isoformat(sep=" "), str(value)),
            )
            conn.commit()

    def _insert_rich_alignment(self, symbol: str, open_time: datetime, close_time: datetime) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO rich_futures_5m_alignment VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    symbol,
                    "15m",
                    open_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    close_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "ALIGNED",
                    "1.23",
                    "0.91",
                    "1.11",
                ),
            )
            conn.commit()

    def _insert_market_state(self, symbol: str, open_time: datetime, close_time: datetime) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO market_state_alignment VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    symbol,
                    "15m",
                    open_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    close_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "FRESH",
                    "0.02",
                    "0.03",
                ),
            )
            conn.commit()

    def _candles(self, count: int, minutes: int) -> list[TimeframeCandle]:
        return [self._candle(index, minutes=minutes) for index in range(count)]

    def _candle(
        self,
        index: int,
        minutes: int,
        high: Decimal | None = None,
        low: Decimal | None = None,
    ) -> TimeframeCandle:
        open_time = self.base + timedelta(minutes=index * minutes)
        price = Decimal("100") + Decimal(index)
        return TimeframeCandle(
            symbol="BTCUSDT",
            open_time=open_time,
            close_time=open_time + timedelta(minutes=minutes),
            open=price,
            high=high or price + Decimal("2"),
            low=low or price - Decimal("2"),
            close=price + Decimal("1"),
            volume=Decimal("100"),
            quote_volume=Decimal("10000"),
            number_of_trades=10,
        )


if __name__ == "__main__":
    unittest.main()
