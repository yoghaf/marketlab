from __future__ import annotations

from datetime import datetime, timedelta

from app.services.normalized_impulse_research import (
    Candle,
    NormalizedImpulseRow,
    atr_at,
    evaluate_rr_path,
    future_candles,
    robust_median,
)


def dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 1, hour, minute)


def make_candle(open_time: datetime, open_: float, high: float, low: float, close: float, minutes: int = 15) -> Candle:
    return Candle(open_time=open_time, close_time=open_time + timedelta(minutes=minutes), open=open_, high=high, low=low, close=close)


def make_row(direction: str = "LONG") -> NormalizedImpulseRow:
    return NormalizedImpulseRow(
        symbol="BTCUSDT",
        window_open_time=dt(1, 45),
        window_close_time=dt(2, 0),
        universe_rank=1,
        collection_tier="FULL_ACTIVE",
        price_close=100.0,
        price_return_pct=0.8 if direction == "LONG" else -0.8,
        range_pct=1.0,
        close_position=0.8 if direction == "LONG" else 0.2,
        volume_spike_ratio_20=2.0,
        range_spike_ratio_20=1.5,
        oi_spike_ratio_20=2.0,
        oi_change_pct=0.2,
        taker_buy_ratio=0.62 if direction == "LONG" else 0.38,
        taker_sell_ratio=0.38 if direction == "LONG" else 0.62,
        atr_1h=2.0,
        atr_1h_pct=2.0,
        price_move_atr_1h=0.4,
        distance_from_recent_low_atr_20=1.0,
        distance_from_recent_high_atr_20=1.0,
        same_direction_impulse_age_bars=None,
        is_fresh_impulse=True,
        spot_support_status="SPOT_SUPPORTING",
        spot_futures_volume_ratio=0.5,
        futures_led_score=0.5,
        spot_support_score=0.8,
        price_return_pct_1h=0.5 if direction == "LONG" else -0.5,
        close_position_1h=0.7 if direction == "LONG" else 0.3,
        kline_taker_buy_ratio_1h=0.6 if direction == "LONG" else 0.4,
        funding_status="FUNDING_CARRIED_FORWARD",
        funding_rate=0.0,
        futures_spread_pct=0.01,
        early_long_v0=direction == "LONG",
        early_short_v0=direction == "SHORT",
        mid_long_v0=False,
        mid_short_v0=False,
    )


def test_robust_median_keeps_negative_r_values() -> None:
    assert robust_median([-1.0, -0.5, 2.0]) == -0.5


def test_atr_at_uses_closed_1h_window_at_or_before_signal() -> None:
    candles = [
        make_candle(dt(0) + timedelta(hours=i), 100 + i, 103 + i, 99 + i, 101 + i, minutes=60)
        for i in range(16)
    ]

    atr = atr_at(candles, candles[14].close_time)

    assert atr is not None
    assert atr > 0


def test_future_candles_requires_contiguous_15m_from_signal_close() -> None:
    candles = [make_candle(dt(2, 0) + timedelta(minutes=15 * i), 100, 101, 99, 100) for i in range(4)]

    window = future_candles(candles, dt(2, 0), 4)

    assert window is not None
    assert len(window) == 4
    assert future_candles(candles[1:], dt(2, 0), 4) is None


def test_evaluate_rr_path_long_tp_first() -> None:
    candles = {
        "BTCUSDT": [
            make_candle(dt(2, 0), 100, 103.1, 99.5, 102),
            make_candle(dt(2, 15), 102, 102.5, 101, 102),
            make_candle(dt(2, 30), 102, 102.5, 101, 102),
            make_candle(dt(2, 45), 102, 102.5, 101, 102),
        ]
    }

    result = evaluate_rr_path(make_row("LONG"), candles, direction="LONG", horizon_bars=4, rr=1.5)

    assert result is not None
    assert result["outcome"] == "TP_FIRST"
    assert result["realized_r"] == 1.5
    assert result["entry_price"] == 100.0
    assert result["stop_loss_reference"] == 98.0
    assert result["take_profit_reference"] == 103.0
    assert result["result_price_reference"] == 103.0


def test_evaluate_rr_path_short_sl_first() -> None:
    candles = {
        "BTCUSDT": [
            make_candle(dt(2, 0), 100, 102.2, 99.5, 101),
            make_candle(dt(2, 15), 101, 101.5, 100, 101),
            make_candle(dt(2, 30), 101, 101.5, 100, 101),
            make_candle(dt(2, 45), 101, 101.5, 100, 101),
        ]
    }

    result = evaluate_rr_path(make_row("SHORT"), candles, direction="SHORT", horizon_bars=4, rr=1.5)

    assert result is not None
    assert result["outcome"] == "SL_FIRST"
    assert result["realized_r"] == -1.0
    assert result["entry_price"] == 100.0
    assert result["stop_loss_reference"] == 102.0
    assert result["take_profit_reference"] == 97.0
    assert result["result_price_reference"] == 102.0
