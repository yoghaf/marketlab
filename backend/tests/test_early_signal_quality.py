from app.services.early_signal_quality import evaluate_early_signal_quality


def test_early_long_quality_uses_futures_impulse_and_spot_as_filter() -> None:
    quality = evaluate_early_signal_quality(
        price_return_pct=0.55,
        close_position=0.78,
        taker_buy_ratio=0.61,
        oi_change_pct=0.08,
        volume_ratio_vs_baseline=2.1,
        atr_extension=0.6,
        spot_support_status="SPOT_SUPPORTING",
        one_hour_return_pct=0.1,
        funding_rate=0.0,
        direction_hint="LONG",
    )

    assert quality.is_early_long
    assert not quality.is_early_short
    assert quality.quality_score >= 6
    assert quality.quality_bucket in {"MEDIUM_QUALITY", "HIGH_QUALITY"}
    assert any("spot supports" in reason for reason in quality.reasons)


def test_early_short_quality_rejects_close_not_near_low() -> None:
    quality = evaluate_early_signal_quality(
        price_return_pct=-0.55,
        close_position=0.55,
        taker_buy_ratio=0.38,
        oi_change_pct=0.08,
        volume_ratio_vs_baseline=2.1,
        atr_extension=0.6,
        spot_support_status="WEAK_SPOT_SUPPORT",
        one_hour_return_pct=-0.1,
        funding_rate=0.0,
        direction_hint="SHORT",
    )

    assert not quality.is_early_short
    assert quality.quality_score >= 6
