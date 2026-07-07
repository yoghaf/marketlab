from __future__ import annotations

from datetime import datetime, timedelta

from app.services.signal_filter_optuna import (
    apply_position_lock,
    apply_rule,
    evaluate_items,
    item_matches_rule,
    validation_verdict,
)


def test_item_matches_rule_with_between_and_missing_data() -> None:
    rule = {
        "conditions": [
            {"field": "funding_percentile_30d", "mode": "GE", "min": 75},
            {"field": "volume_ratio_vs_lookback", "mode": "BETWEEN", "min": 0.8, "max": 1.5},
            {"field": "spot_spread_pct", "mode": "LE", "max": 0.03},
        ]
    }

    assert item_matches_rule(
        _item(
            evidence={
                "funding_percentile_30d": 88,
                "volume_ratio_vs_lookback": 1.2,
                "spot_spread_pct": 0.02,
            }
        ),
        rule,
    )
    assert not item_matches_rule(
        _item(
            evidence={
                "funding_percentile_30d": 55,
                "volume_ratio_vs_lookback": 1.2,
                "spot_spread_pct": 0.02,
            }
        ),
        rule,
    )
    assert not item_matches_rule(
        _item(
            evidence={
                "funding_percentile_30d": 88,
                "volume_ratio_vs_lookback": 1.2,
            }
        ),
        rule,
    )


def test_filter_then_position_lock_keeps_later_symbol_signal_when_first_is_filtered_out() -> None:
    rule = {"conditions": [{"field": "funding_percentile_30d", "mode": "GE", "min": 75}]}
    first = _item(signal_id="first", symbol="AAAUSDT", minutes=0, status="OPEN", evidence={"funding_percentile_30d": 20})
    second = _item(signal_id="second", symbol="AAAUSDT", minutes=15, status="TP_HIT", r=1.5, evidence={"funding_percentile_30d": 90})

    filtered = apply_rule([first, second], rule)
    locked, skipped = apply_position_lock(filtered)

    assert [item["signal_id"] for item in filtered] == ["second"]
    assert [item["signal_id"] for item in locked] == ["second"]
    assert skipped == 0


def test_evaluate_items_counts_r_and_drawdown() -> None:
    items = [
        _item(signal_id="tp", symbol="AAAUSDT", minutes=0, status="TP_HIT", r=1.5),
        _item(signal_id="sl", symbol="BBBUSDT", minutes=15, status="SL_HIT", r=-1),
        _item(signal_id="open", symbol="CCCUSDT", minutes=30, status="OPEN", r=None),
    ]

    metrics = evaluate_items(items, direction="SHORT")

    assert metrics["sample_count"] == 3
    assert metrics["closed_count"] == 2
    assert metrics["tp_count"] == 1
    assert metrics["sl_count"] == 1
    assert metrics["total_r_closed"] == 0.5
    assert metrics["avg_r_closed"] == 0.25
    assert metrics["winrate_pct"] == 50
    assert metrics["max_drawdown_r"] == -1


def test_validation_verdict_requires_validation_improvement() -> None:
    baseline = {"avg_r_closed": 0.10, "winrate_pct": 42, "sl_share_pct": 58}
    metrics = {
        "closed_count": 20,
        "top_symbol_share_pct": 10,
        "avg_r_closed": 0.25,
        "avg_r_delta_vs_baseline": 0.15,
        "winrate_delta_vs_baseline": 5,
        "sl_share_delta_vs_baseline": -4,
    }

    assert validation_verdict(metrics, baseline, min_closed=10) == "VALIDATION_PROMISING_READONLY"

    metrics["closed_count"] = 4
    assert validation_verdict(metrics, baseline, min_closed=10) == "VALIDATION_SAMPLE_TOO_SMALL"


def _item(
    *,
    signal_id: str = "sig",
    symbol: str = "AAAUSDT",
    minutes: int = 0,
    status: str = "TP_HIT",
    r: float | None = 1.5,
    evidence: dict | None = None,
) -> dict:
    signal_time = datetime(2026, 1, 1, 0, 0) + timedelta(minutes=minutes)
    return {
        "signal_id": signal_id,
        "symbol": symbol,
        "signal_timestamp": signal_time,
        "result_time_utc": signal_time + timedelta(minutes=15),
        "result_status": status,
        "realized_r": r,
        "evidence_snapshot": evidence or {},
    }
