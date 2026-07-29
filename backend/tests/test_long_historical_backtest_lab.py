import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal

from app.services.long_historical_backtest_lab import LongHistoricalBacktestLab
from app.services.signal_performance_snapshot import SignalPerformanceSnapshotService


def test_long_historical_backtest_replays_all_available_candles(tmp_path) -> None:
    db_path = tmp_path / "marketlab.db"
    _make_schema(db_path)
    _seed_replay_dataset(db_path)

    output_path = tmp_path / "long_historical_backtest_1h.json"
    report = LongHistoricalBacktestLab(db_path).run(output_path=output_path, latest_limit=20)

    assert output_path.exists()
    assert report["artifact_type"] == "long_1h_historical_backtest_v1"
    assert report["read_only"] is True
    assert report["production_rule_change"] is False
    assert report["filters"]["source"] == "futures_klines_1h + futures_klines_15m + evidence tables"
    assert report["coverage"]["symbol_count"] == 1
    assert report["coverage"]["futures_1h_candle_count"] == 20
    assert report["coverage"]["raw_long_candidate_count_before_lock"] >= 1
    assert report["coverage"]["events_evaluated_after_lock"] >= 1
    assert {row["family_id"] for row in report["family_rows"]} >= {
        "BREAKOUT_LONG_PROXY",
        "RETEST_LONG_PROXY",
        "SQUEEZE_LONG_PROXY",
        "LATE_CHASE_LONG",
        "CROWDED_LONG",
        "UNCLASSIFIED_LONG",
    }

    item = report["latest_items"][0]
    assert item["symbol"] == "TESTUSDT"
    assert item["timeframe"] == "1h"
    assert item["direction"] == "LONG"
    assert item["source_stage"] == "HISTORICAL_REPLAY"
    assert item["entry_market"] == "futures"
    assert item["entry_price_source"] == "futures_klines_1h.close"
    assert item["candidate_status"] == "HISTORICAL_LONG_PROXY"
    assert item["not_live_signal"] is True
    assert item["not_execution_instruction"] is True
    assert item["result_status"] in {"TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE", "OPEN"}
    assert Decimal(str(item["price_return"])) > 0
    assert Decimal(str(item["kline_taker_buy_ratio"])) >= Decimal("0.55")

    served = SignalPerformanceSnapshotService(artifact_dir=tmp_path).long_historical_backtest_1h(limit=1)
    assert served["artifact_type"] == "long_1h_historical_backtest_v1"
    assert len(served["latest_items"]) == 1


def _make_schema(db_path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE marketlab_active_universe (
                symbol TEXT PRIMARY KEY,
                rank INTEGER,
                collection_tier TEXT,
                is_active INTEGER
            );
            CREATE TABLE futures_klines_1h (
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
                taker_buy_base_volume TEXT,
                taker_sell_base_volume TEXT,
                aggregation_status TEXT
            );
            CREATE TABLE futures_klines_15m (
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
                taker_buy_base_volume TEXT,
                taker_sell_base_volume TEXT,
                aggregation_status TEXT
            );
            """
        )


def _seed_replay_dataset(db_path) -> None:
    start = datetime(2026, 1, 1, 0, 0)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO marketlab_active_universe VALUES (?, ?, ?, ?)",
            ("TESTUSDT", 1, "FULL_ACTIVE", 1),
        )
        for idx in range(19):
            open_time = start + timedelta(hours=idx)
            _insert_candle(
                conn,
                "futures_klines_1h",
                open_time,
                open_price="100",
                high="101",
                low="99",
                close="100",
                volume="100",
                buy="45",
                sell="55",
            )

        signal_open = start + timedelta(hours=19)
        _insert_candle(
            conn,
            "futures_klines_1h",
            signal_open,
            open_price="100",
            high="101.30",
            low="99.50",
            close="101.20",
            volume="250",
            buy="175",
            sell="75",
        )

        first_forward = signal_open + timedelta(hours=1)
        _insert_candle(
            conn,
            "futures_klines_15m",
            first_forward,
            minutes=15,
            open_price="101.20",
            high="105.50",
            low="100.80",
            close="104.90",
            volume="80",
            buy="60",
            sell="20",
        )
        for offset in range(1, 4):
            _insert_candle(
                conn,
                "futures_klines_15m",
                first_forward + timedelta(minutes=15 * offset),
                minutes=15,
                open_price="104.90",
                high="105.20",
                low="104.20",
                close="104.80",
                volume="60",
                buy="35",
                sell="25",
            )


def _insert_candle(
    conn,
    table: str,
    open_time: datetime,
    *,
    minutes: int = 60,
    open_price: str,
    high: str,
    low: str,
    close: str,
    volume: str,
    buy: str,
    sell: str,
) -> None:
    conn.execute(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "TESTUSDT",
            open_time.isoformat(),
            (open_time + timedelta(minutes=minutes)).isoformat(),
            open_price,
            high,
            low,
            close,
            volume,
            str(Decimal(volume) * Decimal(close)),
            100,
            buy,
            sell,
            "AGG_READY",
        ),
    )
