from __future__ import annotations

from app.services.optuna_label_discovery_backtest import (
    MarketWindow,
    pct_change,
    token_result_payload,
    window_to_threshold_row,
)


def make_window() -> MarketWindow:
    return MarketWindow(
        symbol="TAIKOUSDT",
        window_open_time="2026-07-01T00:00:00Z",
        window_close_time="2026-07-01T00:15:00Z",
        price_return_pct_15m=-0.7,
        close_position_15m=0.18,
        taker_buy_ratio_15m=0.39,
        taker_sell_ratio_15m=0.61,
        oi_change_pct_15m=-0.04,
        futures_led_score_15m=1.0,
        spot_support_score_15m=0.0,
        spot_futures_volume_ratio_15m=0.4,
        spot_missing_flag_15m=False,
        spot_support_status_15m="FUTURES_LED",
        global_long_short_ratio_15m=1.2,
        top_trader_position_ratio_15m=1.1,
        funding_rate=0.01,
        futures_spread_pct=0.02,
        price_return_pct_1h=-0.9,
        taker_buy_ratio_1h=0.42,
        oi_change_pct_1h=-0.05,
        candidate_close_price=100.0,
        future_return_15m=-0.4,
        future_return_30m=-0.8,
        future_return_1h=-1.1,
        future_return_4h=-1.5,
        max_up_move_1h=0.3,
        max_down_move_1h=-1.2,
        max_up_move_4h=0.6,
        max_down_move_4h=-2.2,
    )


def test_pct_change_returns_percent() -> None:
    assert pct_change(102.0, 100.0) == 2.0
    assert pct_change(98.0, 100.0) == -2.0


def test_window_to_threshold_row_short_favorable_is_down_move() -> None:
    row = window_to_threshold_row(make_window(), "MID_SHORT_CONTEXT_READONLY", "SHORT")

    assert row.direction == "BEARISH_CONTEXT"
    assert row.future_return_4h == -1.5
    assert row.max_favorable_move_4h == 2.2
    assert row.max_adverse_move_4h == 0.6


def test_window_to_threshold_row_long_favorable_is_up_move() -> None:
    row = window_to_threshold_row(make_window(), "MID_LONG_CONTEXT_READONLY", "LONG")

    assert row.direction == "BULLISH_CONTEXT"
    assert row.max_favorable_move_4h == 0.6
    assert row.max_adverse_move_4h == -2.2


def test_token_result_payload_is_read_only_and_directional() -> None:
    row = window_to_threshold_row(make_window(), "MID_SHORT_CONTEXT_READONLY", "SHORT")
    rule = {
        "direction": "SHORT",
        "price_return_pct_15m": {"operator": "<=", "value": -0.2},
        "close_position_15m": {"operator": "<=", "value": 0.3},
        "taker_ratio_15m": {"operator": ">=", "value": 0.55},
        "price_return_pct_1h": {"operator": "<=", "value": -0.5},
    }

    payload = token_result_payload(row, "MID_SHORT", rule)

    assert payload["detected_label"] == "MID_SHORT_OPTUNA_LOCKED"
    assert payload["directional_return_4h"] == 1.5
    assert payload["not_live_signal"] is True
    assert payload["not_execution_instruction"] is True
