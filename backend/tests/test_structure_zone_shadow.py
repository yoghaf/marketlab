from datetime import datetime, timedelta
from decimal import Decimal

from app.services.structure_zone_shadow import (
    ZoneCandle,
    build_structure_zone_snapshot,
    classify_directional_structure,
)


def _candle(index: int, *, open_: str, high: str, low: str, close: str) -> ZoneCandle:
    start = datetime(2026, 1, 1) + timedelta(hours=index)
    return ZoneCandle(
        open_time=start,
        close_time=start + timedelta(hours=1),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def _zone() -> dict:
    return {
        "center": Decimal("100"),
        "lower": Decimal("99"),
        "upper": Decimal("101"),
        "touch_count": 4,
        "support_touch_count": 2,
        "resistance_touch_count": 2,
        "origin_role": "ROLE_FLIP",
        "latest_pivot_kind": "LOW",
        "first_touch_time": datetime(2026, 1, 1),
        "last_touch_time": datetime(2026, 1, 2),
    }


def test_support_break_aligns_short_and_conflicts_long() -> None:
    prior = _candle(0, open_="102", high="103", low="100", close="100")
    signal = _candle(1, open_="100", high="100.5", low="97", close="98")

    short = classify_directional_structure(
        direction="SHORT",
        entry=Decimal("98"),
        signal_candle=signal,
        prior_candle=prior,
        zones=[_zone()],
        atr=Decimal("4"),
    )
    long = classify_directional_structure(
        direction="LONG",
        entry=Decimal("98"),
        signal_candle=signal,
        prior_candle=prior,
        zones=[_zone()],
        atr=Decimal("4"),
    )

    assert short["status"] == "ZONE_ALIGNED"
    assert short["state"] == "SUPPORT_BREAK"
    assert long["status"] == "ZONE_CONFLICT"
    assert long["state"] == "SUPPORT_BREAK"


def test_resistance_breakout_aligns_long_and_conflicts_short() -> None:
    prior = _candle(0, open_="99", high="100", low="98", close="100")
    signal = _candle(1, open_="100", high="103", low="99.5", close="102")

    long = classify_directional_structure(
        direction="LONG",
        entry=Decimal("102"),
        signal_candle=signal,
        prior_candle=prior,
        zones=[_zone()],
        atr=Decimal("4"),
    )
    short = classify_directional_structure(
        direction="SHORT",
        entry=Decimal("102"),
        signal_candle=signal,
        prior_candle=prior,
        zones=[_zone()],
        atr=Decimal("4"),
    )

    assert long["status"] == "ZONE_ALIGNED"
    assert long["state"] == "RESISTANCE_BREAKOUT"
    assert short["status"] == "ZONE_CONFLICT"
    assert short["state"] == "RESISTANCE_BREAKOUT"


def test_snapshot_ignores_candles_after_signal_time() -> None:
    candles: list[ZoneCandle] = []
    pivot_indexes = {4, 8, 12, 16, 20, 24}
    for index in range(29):
        low = "100" if index in pivot_indexes else "104"
        close = "101" if index == 28 else "105"
        candles.append(_candle(index, open_=close, high="106", low=low, close=close))
    signal = _candle(29, open_="101", high="102", low="97", close="98")
    signal_time = signal.close_time
    before = candles + [signal]
    after = before + [_candle(30, open_="98", high="140", low="60", close="130")]

    first = build_structure_zone_snapshot(
        signal_id="signal-1",
        symbol="AAAUSDT",
        signal_timeframe="1h",
        signal_time=signal_time,
        direction="SHORT",
        entry=Decimal("98"),
        candles_by_timeframe={"1h": before, "4h": []},
    )
    second = build_structure_zone_snapshot(
        signal_id="signal-1",
        symbol="AAAUSDT",
        signal_timeframe="1h",
        signal_time=signal_time,
        direction="SHORT",
        entry=Decimal("98"),
        candles_by_timeframe={"1h": after, "4h": []},
    )

    assert first["status"] == "ZONE_ALIGNED"
    assert first["primary"]["state"] == "SUPPORT_BREAK"
    assert first["primary"] == second["primary"]
    assert first["context"]["status"] == "ZONE_UNAVAILABLE"
    assert first["not_signal_gate"] is True
