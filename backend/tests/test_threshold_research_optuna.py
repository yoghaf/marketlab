from __future__ import annotations

from app.services.threshold_research_optuna import (
    ThresholdRow,
    evaluate_rows,
    render_markdown,
    row_matches,
    validation_verdict,
)


def make_row(
    *,
    symbol: str = "BTCUSDT",
    direction: str = "SHORT",
    future_return_4h: float = -1.0,
    price_return_pct_15m: float = -0.5,
    close_position_15m: float = 0.2,
    taker_buy_ratio_15m: float = 0.4,
    taker_sell_ratio_15m: float = 0.6,
    price_return_pct_1h: float = -0.8,
    spot_missing_flag_15m: bool | None = False,
    spot_support_status_15m: str | None = "FUTURES_LED",
) -> ThresholdRow:
    return ThresholdRow(
        symbol=symbol,
        window_close_time="2026-07-01T00:15:00Z",
        candidate_type="MID_SHORT_CONTEXT_READONLY" if direction == "SHORT" else "MID_LONG_CONTEXT_READONLY",
        direction="BEARISH_CONTEXT" if direction == "SHORT" else "BULLISH_CONTEXT",
        price_return_pct_15m=price_return_pct_15m,
        close_position_15m=close_position_15m,
        taker_buy_ratio_15m=taker_buy_ratio_15m,
        taker_sell_ratio_15m=taker_sell_ratio_15m,
        oi_change_pct_15m=0.1,
        futures_led_score_15m=1.0,
        spot_support_score_15m=0.2,
        spot_futures_volume_ratio_15m=0.5,
        spot_missing_flag_15m=spot_missing_flag_15m,
        spot_support_status_15m=spot_support_status_15m,
        global_long_short_ratio_15m=1.1,
        top_trader_position_ratio_15m=1.2,
        funding_rate=0.01,
        futures_spread_pct=0.02,
        price_return_pct_1h=price_return_pct_1h,
        taker_buy_ratio_1h=0.45,
        oi_change_pct_1h=0.05,
        future_return_4h=future_return_4h,
        max_favorable_move_4h=1.6,
        max_adverse_move_4h=-0.9,
    )


def test_evaluate_rows_inverts_short_directional_return() -> None:
    rows = [
        make_row(symbol="AUSDT", future_return_4h=-1.2),
        make_row(symbol="BUSDT", future_return_4h=0.4),
        make_row(symbol="CUSDT", future_return_4h=-0.6),
    ]

    metrics = evaluate_rows(rows, "SHORT")

    assert metrics["sample_count"] == 3
    assert metrics["favorable_count"] == 2
    assert metrics["adverse_count"] == 1
    assert metrics["median_directional_return_4h"] == 0.6


def test_row_matches_short_rule_filters_spot_and_directional_fields() -> None:
    rule = {
        "direction": "SHORT",
        "price_return_pct_15m": {"operator": "<=", "value": -0.2},
        "close_position_15m": {"operator": "<=", "value": 0.3},
        "taker_ratio_15m": {"operator": ">=", "value": 0.55},
        "price_return_pct_1h": {"operator": "<=", "value": -0.5},
        "use_oi_min": False,
        "oi_change_pct_15m_min": 0.0,
        "use_futures_led_min": True,
        "futures_led_score_15m_min": 0.8,
        "use_spot_score_min": False,
        "spot_support_score_15m_min": 0.0,
        "exclude_spot_supporting": True,
        "require_spot_supporting": False,
        "allow_spot_missing": False,
        "use_max_spread": True,
        "futures_spread_pct_max": 0.05,
    }

    assert row_matches(make_row(), rule)
    assert not row_matches(make_row(spot_support_status_15m="SPOT_SUPPORTING"), rule)
    assert not row_matches(make_row(spot_missing_flag_15m=True), rule)
    assert not row_matches(make_row(taker_sell_ratio_15m=0.45), rule)


def test_validation_verdict_promising_only_when_sample_and_adverse_are_ok() -> None:
    metrics = {
        "sample_count": 50,
        "top_symbol_concentration": 0.10,
        "median_directional_return_4h": 0.4,
        "adverse_share": 0.35,
        "favorable_share": 0.55,
    }

    assert validation_verdict(metrics, min_validation=40) == "VALIDATION_PROMISING_READONLY"

    metrics["sample_count"] = 10
    assert validation_verdict(metrics, min_validation=40) == "VALIDATION_SAMPLE_TOO_SMALL"


def test_render_markdown_keeps_research_guardrails() -> None:
    payload = {
        "generated_at": "2026-07-01T00:00:00Z",
        "trials": 10,
        "method": "test",
        "setups": {"MID_SHORT": {"status": "NO_DATA", "row_count": 0}},
    }

    markdown = render_markdown(payload)

    assert "No runtime rule changed" in markdown
    assert "No live signal" in markdown
    assert "read-only" in markdown.lower()
