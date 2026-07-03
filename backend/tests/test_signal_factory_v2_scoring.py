from __future__ import annotations

from app.services.anomaly_signal_factory import classify_candidate
from app.services.signal_factory_v2_scoring import calculate_evidence_score


def test_v2_early_long_uses_layered_core_evidence_and_risk() -> None:
    candidate = classify_candidate(
        {
            "symbol": "AAAUSDT",
            "timeframe": "15m",
            "window_start": "2026-01-01T00:00:00+00:00",
            "window_end": "2026-01-01T00:15:00+00:00",
            "price_return": 0.7,
            "price_return_abs": 0.7,
            "entry_price": 1.0,
            "volume_spike": True,
            "volume_ratio_vs_lookback": 3.2,
            "range_ratio_vs_atr": 0.55,
            "oi_change_pct": 0.2,
            "oi_zscore": 1.4,
            "funding_rate": 0.0001,
            "funding_percentile_30d": 55,
            "close_position_in_range": 0.8,
            "kline_taker_buy_ratio": 0.62,
            "kline_taker_sell_ratio": 0.38,
            "atr_pct": 1.2,
            "atr_reference_pct": 1.2,
            "relative_strength": "OUTPERFORMING",
            "one_hour_return_pct": 0.3,
            "futures_led_flag": True,
            "spot_led_flag": False,
            "spot_context": "SPOT_SUPPORTING",
            "global_long_short_ratio": 1.1,
            "top_trader_position_ratio": 1.2,
            "top_trader_account_ratio": 1.1,
            "rich_alignment_status": "ALIGNED",
            "futures_spread_pct": 0.02,
            "spot_spread_pct": 0.03,
            "snapshot_alignment_status": "FRESH",
            "feature_status": "READY",
            "status_reasons": [],
        },
        atr_reference_status="AVAILABLE",
    )

    assert candidate["setup_type"] == "EARLY_LONG"
    assert candidate["candidate_status"] == "SIGNAL_CANDIDATE"
    assert candidate["core_score"] >= 7
    assert candidate["evidence_confidence_tier"] == "HIGH_CONF"
    assert candidate["execution_risk_status"] == "ACTIVE"
    assert candidate["entry_mode"] == "MARKET_REFERENCE_OK"
    assert candidate["not_live_signal"] is True
    assert candidate["not_execution_instruction"] is True
    evidence = candidate["evidence"]
    assert evidence["oi_signal_source"] == "oi_zscore_30d"
    assert evidence["funding_percentile_30d"] == 55
    assert evidence["top_trader_position_ratio"] == 1.2


def test_v2_mid_short_uses_normalized_atr_and_oi_zscore() -> None:
    candidate = classify_candidate(
        {
            "symbol": "BBBUSDT",
            "timeframe": "15m",
            "window_start": "2026-01-01T00:00:00+00:00",
            "window_end": "2026-01-01T00:15:00+00:00",
            "price_return": -0.8,
            "price_return_abs": 0.8,
            "entry_price": 2.0,
            "volume_spike": False,
            "volume_ratio_vs_lookback": 1.1,
            "range_ratio_vs_atr": 0.9,
            "oi_change_pct": 0.01,
            "oi_zscore": 1.2,
            "funding_rate": 0.0003,
            "funding_percentile_30d": 60,
            "close_position_in_range": 0.5,
            "kline_taker_buy_ratio": 0.48,
            "kline_taker_sell_ratio": 0.52,
            "atr_pct": 1.0,
            "atr_reference_pct": 1.0,
            "relative_strength": "UNDERPERFORMING",
            "one_hour_return_pct": -0.2,
            "futures_led_flag": False,
            "spot_led_flag": False,
            "spot_context": "SPOT_PRESENT",
            "global_long_short_ratio": 1.0,
            "top_trader_position_ratio": 0.8,
            "rich_alignment_status": "ALIGNED",
            "futures_spread_pct": 0.02,
            "feature_status": "READY",
            "status_reasons": [],
        },
        atr_reference_status="AVAILABLE",
    )

    assert candidate["setup_type"] == "MID_SHORT"
    assert candidate["candidate_status"] == "SIGNAL_CANDIDATE"
    assert candidate["evidence"]["oi_signal_source"] == "oi_zscore_30d"
    assert candidate["evidence"]["price_atr_multiple"] == 0.8


def test_evidence_score_zero_is_not_medium_when_sources_missing() -> None:
    evidence = calculate_evidence_score({}, "LONG")

    assert evidence.score == 0
    assert evidence.data_completeness == 0
    assert evidence.confidence_tier == "EVIDENCE_UNAVAILABLE"
    assert "EVIDENCE_UNAVAILABLE" in evidence.flags
