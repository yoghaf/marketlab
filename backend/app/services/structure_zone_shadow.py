from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline1h, FuturesKline4h, FuturesKline24h
from app.services.utils import json_safe, utcnow


@dataclass(frozen=True)
class ZoneCandle:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class ZoneConfig:
    timeframe: str
    lookback: timedelta
    pivot_span: int
    zone_half_width_atr: Decimal
    independent_touch_gap: timedelta
    min_history: int = 24
    min_touches: int = 2


KLINE_BY_TIMEFRAME = {
    "1h": FuturesKline1h,
    "4h": FuturesKline4h,
    "24h": FuturesKline24h,
}

ZONE_CONFIGS = {
    "1h": ZoneConfig(
        timeframe="1h",
        lookback=timedelta(hours=168),
        pivot_span=2,
        zone_half_width_atr=Decimal("0.30"),
        independent_touch_gap=timedelta(hours=4),
    ),
    "4h": ZoneConfig(
        timeframe="4h",
        lookback=timedelta(days=45),
        pivot_span=2,
        zone_half_width_atr=Decimal("0.35"),
        independent_touch_gap=timedelta(hours=16),
    ),
    "24h": ZoneConfig(
        timeframe="24h",
        lookback=timedelta(days=365),
        pivot_span=2,
        zone_half_width_atr=Decimal("0.35"),
        independent_touch_gap=timedelta(days=4),
    ),
}

TIMEFRAME_PLAN = {
    "15m": ("1h", "4h"),
    "1h": ("1h", "4h"),
    "4h": ("4h", "24h"),
    "24h": ("24h", None),
}

ALIGNED_STATES = {
    "LONG": {
        "AT_SUPPORT",
        "SUPPORT_BOUNCE",
        "RESISTANCE_BREAKOUT",
        "BREAKOUT_RETEST_HELD",
        "FAILED_BREAKDOWN_RECLAIM",
    },
    "SHORT": {
        "AT_RESISTANCE",
        "RESISTANCE_REJECTION",
        "SUPPORT_BREAK",
        "BREAK_RETEST_REJECTED",
        "FAILED_BREAKOUT_REJECT",
    },
}

CONFLICT_STATES = {
    "LONG": ALIGNED_STATES["SHORT"],
    "SHORT": ALIGNED_STATES["LONG"],
}


class StructureZoneShadowService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def snapshots_for_signals(self, signals: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        specs = [self._normalize_signal(signal) for signal in signals]
        specs = [spec for spec in specs if spec is not None]
        candles = self._load_required_candles(specs)
        close_times = {key: [candle.close_time for candle in rows] for key, rows in candles.items()}
        return {
            spec["signal_id"]: build_structure_zone_snapshot(
                signal_id=spec["signal_id"],
                symbol=spec["symbol"],
                signal_timeframe=spec["timeframe"],
                signal_time=spec["signal_time"],
                direction=spec["direction"],
                entry=spec["entry"],
                candles_by_timeframe={
                    timeframe: _slice_candles_for_signal(
                        candles.get((timeframe, spec["symbol"]), []),
                        close_times.get((timeframe, spec["symbol"]), []),
                        signal_time=spec["signal_time"],
                        config=ZONE_CONFIGS[timeframe],
                    )
                    for timeframe in KLINE_BY_TIMEFRAME
                },
            )
            for spec in specs
        }

    def _normalize_signal(self, signal: dict[str, Any]) -> dict[str, Any] | None:
        signal_id = str(signal.get("signal_id") or "")
        symbol = str(signal.get("symbol") or "").upper()
        signal_time = _as_datetime(signal.get("signal_timestamp"))
        entry = _decimal(signal.get("entry") if "entry" in signal else signal.get("price_at_signal"))
        if not signal_id or not symbol or signal_time is None:
            return None
        return {
            "signal_id": signal_id,
            "symbol": symbol,
            "timeframe": str(signal.get("timeframe") or "15m"),
            "signal_time": signal_time,
            "direction": _direction(signal.get("direction")),
            "entry": entry,
        }

    def _load_required_candles(
        self,
        specs: list[dict[str, Any]],
    ) -> dict[tuple[str, str], list[ZoneCandle]]:
        loaded: dict[tuple[str, str], list[ZoneCandle]] = {}
        for timeframe, model in KLINE_BY_TIMEFRAME.items():
            relevant = [
                spec
                for spec in specs
                if timeframe in TIMEFRAME_PLAN.get(spec["timeframe"], ("1h", "4h"))
            ]
            if not relevant:
                continue
            symbols = sorted({spec["symbol"] for spec in relevant})
            config = ZONE_CONFIGS[timeframe]
            start_time = min(spec["signal_time"] for spec in relevant) - config.lookback - config.independent_touch_gap
            end_time = max(spec["signal_time"] for spec in relevant)
            rows = self.db.scalars(
                select(model)
                .where(
                    model.symbol.in_(symbols),
                    model.close_time >= start_time,
                    model.close_time <= end_time,
                    model.aggregation_status == "AGG_READY",
                    model.open.is_not(None),
                    model.high.is_not(None),
                    model.low.is_not(None),
                    model.close.is_not(None),
                )
                .order_by(model.symbol, model.close_time)
            ).all()
            for row in rows:
                loaded.setdefault((timeframe, row.symbol), []).append(
                    ZoneCandle(
                        open_time=_naive(row.open_time),
                        close_time=_naive(row.close_time),
                        open=Decimal(row.open),
                        high=Decimal(row.high),
                        low=Decimal(row.low),
                        close=Decimal(row.close),
                    )
                )
        return loaded


def _slice_candles_for_signal(
    candles: list[ZoneCandle],
    close_times: list[datetime],
    *,
    signal_time: datetime,
    config: ZoneConfig,
) -> list[ZoneCandle]:
    if not candles:
        return []
    start_time = _naive(signal_time) - config.lookback - config.independent_touch_gap
    end_time = _naive(signal_time)
    left = bisect_left(close_times, start_time)
    right = bisect_right(close_times, end_time)
    return candles[left:right]


def build_structure_zone_snapshot(
    *,
    signal_id: str,
    symbol: str,
    signal_timeframe: str,
    signal_time: datetime,
    direction: str,
    entry: Decimal | None,
    candles_by_timeframe: dict[str, list[ZoneCandle]],
) -> dict[str, Any]:
    primary_timeframe, context_timeframe = TIMEFRAME_PLAN.get(signal_timeframe, ("1h", "4h"))
    primary = evaluate_directional_structure(
        timeframe=primary_timeframe,
        candles=candles_by_timeframe.get(primary_timeframe, []),
        signal_time=signal_time,
        direction=direction,
        entry=entry,
    )
    context = (
        evaluate_directional_structure(
            timeframe=context_timeframe,
            candles=candles_by_timeframe.get(context_timeframe, []),
            signal_time=signal_time,
            direction=direction,
            entry=entry,
        )
        if context_timeframe
        else _not_applicable_context()
    )
    status, reason = _combined_status(primary, context)
    return json_safe(
        {
            "version": "STRUCTURE_ZONE_SHADOW_V1",
            "generated_at_utc": utcnow(),
            "signal_id": signal_id,
            "symbol": symbol,
            "signal_timeframe": signal_timeframe,
            "signal_timestamp": signal_time,
            "direction": direction,
            "entry": entry,
            "status": status,
            "reason": reason,
            "primary_timeframe": primary_timeframe,
            "primary": primary,
            "context_timeframe": context_timeframe,
            "context": context,
            "read_only": True,
            "not_signal_gate": True,
            "not_execution_instruction": True,
        }
    )


def evaluate_directional_structure(
    *,
    timeframe: str,
    candles: list[ZoneCandle],
    signal_time: datetime,
    direction: str,
    entry: Decimal | None,
) -> dict[str, Any]:
    config = ZONE_CONFIGS[timeframe]
    closed = sorted(
        (candle for candle in candles if candle.close_time <= _naive(signal_time)),
        key=lambda candle: candle.close_time,
    )
    signal_candle = closed[-1] if closed else None
    prior_candle = closed[-2] if len(closed) >= 2 else None
    atr = atr_14(closed)
    history = [
        candle
        for candle in closed
        if _naive(signal_time) - config.lookback <= candle.close_time < _naive(signal_time)
    ]
    zones = detect_repeated_zones(history, atr=atr, config=config)
    unavailable_reason = None
    if entry is None or entry <= 0:
        unavailable_reason = "Futures entry reference is unavailable."
    elif direction not in {"LONG", "SHORT"}:
        unavailable_reason = "Directional context is unavailable."
    elif signal_candle is None or prior_candle is None:
        unavailable_reason = f"Two closed {timeframe} candles through signal time are required."
    elif atr is None or atr <= 0 or len(history) < config.min_history:
        unavailable_reason = f"At least {config.min_history} closed {timeframe} candles plus ATR(14) are required."
    elif not zones:
        unavailable_reason = f"No repeated {timeframe} pivot zone met the two-touch requirement."
    if unavailable_reason:
        return {
            "status": "ZONE_UNAVAILABLE",
            "state": f"{timeframe.upper()}_ZONE_UNAVAILABLE",
            "reason": unavailable_reason,
            "history_count": len(history),
            "atr_at_signal": atr,
            "zone_count": len(zones),
            "nearest_support": None,
            "nearest_resistance": None,
            "nearest_support_distance_atr": None,
            "nearest_resistance_distance_atr": None,
            "state_zone": None,
            "zones": [_public_zone(zone) for zone in zones],
        }
    classification = classify_directional_structure(
        timeframe=timeframe,
        direction=direction,
        entry=entry,
        signal_candle=signal_candle,
        prior_candle=prior_candle,
        closed_candles=closed,
        zones=zones,
        atr=atr,
    )
    return {
        **classification,
        "history_count": len(history),
        "atr_at_signal": atr,
        "zone_count": len(zones),
        "zones": [_public_zone(zone) for zone in zones],
    }


def atr_14(candles: list[ZoneCandle]) -> Decimal | None:
    if len(candles) < 15:
        return None
    ranges: list[Decimal] = []
    for index, candle in enumerate(candles):
        if index == 0:
            ranges.append(candle.high - candle.low)
            continue
        previous_close = candles[index - 1].close
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return sum(ranges[-14:], Decimal("0")) / Decimal("14")


def detect_repeated_zones(
    candles: list[ZoneCandle],
    *,
    atr: Decimal | None,
    config: ZoneConfig,
) -> list[dict[str, Any]]:
    ordered = sorted(candles, key=lambda candle: candle.close_time)
    if atr is None or atr <= 0 or len(ordered) < (config.pivot_span * 2) + 3:
        return []
    points: list[dict[str, Any]] = []
    for index in range(config.pivot_span, len(ordered) - config.pivot_span):
        candle = ordered[index]
        window = ordered[index - config.pivot_span : index + config.pivot_span + 1]
        if candle.low == min(row.low for row in window) and (
            candle.low < ordered[index - 1].low or candle.low < ordered[index + 1].low
        ):
            points.append({"price": candle.low, "kind": "LOW", "time": candle.close_time})
        if candle.high == max(row.high for row in window) and (
            candle.high > ordered[index - 1].high or candle.high > ordered[index + 1].high
        ):
            points.append({"price": candle.high, "kind": "HIGH", "time": candle.close_time})
    tolerance = atr * config.zone_half_width_atr
    clusters: list[list[dict[str, Any]]] = []
    for point in sorted(points, key=lambda row: (Decimal(row["price"]), row["time"])):
        nearest = None
        nearest_distance = None
        for cluster in clusters:
            center = sum((Decimal(row["price"]) for row in cluster), Decimal("0")) / Decimal(len(cluster))
            distance = abs(Decimal(point["price"]) - center)
            if distance <= tolerance and (nearest_distance is None or distance < nearest_distance):
                nearest = cluster
                nearest_distance = distance
        if nearest is None:
            clusters.append([point])
        else:
            nearest.append(point)
    zones: list[dict[str, Any]] = []
    for cluster in clusters:
        independent: list[dict[str, Any]] = []
        for point in sorted(cluster, key=lambda row: row["time"]):
            if not independent or point["time"] - independent[-1]["time"] >= config.independent_touch_gap:
                independent.append(point)
        if len(independent) < config.min_touches:
            continue
        center = sum((Decimal(point["price"]) for point in independent), Decimal("0")) / Decimal(len(independent))
        support_touches = sum(1 for point in independent if point["kind"] == "LOW")
        resistance_touches = sum(1 for point in independent if point["kind"] == "HIGH")
        latest = max(independent, key=lambda point: point["time"])
        zones.append(
            {
                "center": center,
                "lower": center - tolerance,
                "upper": center + tolerance,
                "touch_count": len(independent),
                "support_touch_count": support_touches,
                "resistance_touch_count": resistance_touches,
                "origin_role": (
                    "ROLE_FLIP"
                    if support_touches and resistance_touches
                    else "SUPPORT_ORIGIN"
                    if support_touches
                    else "RESISTANCE_ORIGIN"
                ),
                "latest_pivot_kind": latest["kind"],
                "first_touch_time": min(point["time"] for point in independent),
                "last_touch_time": latest["time"],
            }
        )
    return sorted(zones, key=lambda zone: Decimal(zone["center"]))


def classify_directional_structure(
    *,
    direction: str,
    entry: Decimal,
    signal_candle: ZoneCandle,
    prior_candle: ZoneCandle,
    zones: list[dict[str, Any]],
    atr: Decimal,
    timeframe: str = "1h",
    closed_candles: list[ZoneCandle] | None = None,
) -> dict[str, Any]:
    closed_candles = closed_candles or [prior_candle, signal_candle]
    nearest_support = max(
        (zone for zone in zones if Decimal(zone["center"]) <= entry),
        key=lambda zone: Decimal(zone["center"]),
        default=None,
    )
    nearest_resistance = min(
        (zone for zone in zones if Decimal(zone["center"]) > entry),
        key=lambda zone: Decimal(zone["center"]),
        default=None,
    )
    support_distance = distance_to_zone(entry, nearest_support, atr)
    resistance_distance = distance_to_zone(entry, nearest_resistance, atr)
    events: list[tuple[str, dict[str, Any]]] = []
    for zone in zones:
        lower = Decimal(zone["lower"])
        upper = Decimal(zone["upper"])
        if prior_candle.close >= lower and signal_candle.close < lower:
            events.append(("SUPPORT_BREAK", zone))
        if prior_candle.close <= upper and signal_candle.close > upper:
            events.append(("RESISTANCE_BREAKOUT", zone))
        if prior_candle.close < lower and signal_candle.high >= lower and signal_candle.close < lower:
            events.append(("BREAK_RETEST_REJECTED", zone))
        if prior_candle.close > upper and signal_candle.low <= upper and signal_candle.close > upper:
            events.append(("BREAKOUT_RETEST_HELD", zone))
        if (
            int(zone.get("resistance_touch_count") or 0) > 0
            and signal_candle.open < lower
            and signal_candle.high >= lower
            and signal_candle.close < lower
        ):
            events.append(("RESISTANCE_REJECTION", zone))
        if (
            int(zone.get("support_touch_count") or 0) > 0
            and signal_candle.open > upper
            and signal_candle.low <= upper
            and signal_candle.close > upper
        ):
            events.append(("SUPPORT_BOUNCE", zone))
        if prior_candle.close < lower and signal_candle.close > upper:
            events.append(("FAILED_BREAKDOWN_RECLAIM", zone))
        if prior_candle.close > upper and signal_candle.close < lower:
            events.append(("FAILED_BREAKOUT_REJECT", zone))
    aligned = _nearest_event(events, ALIGNED_STATES[direction], entry, atr)
    conflicted = _nearest_event(events, CONFLICT_STATES[direction], entry, atr)
    if aligned and conflicted:
        state = "MIXED_STRUCTURE_INTERACTION"
        status = "ZONE_CONFLICT"
        reason = "The signal candle produced both aligned and conflicting repeated-zone interactions."
        state_zone = conflicted[1]
    elif aligned:
        state, state_zone = aligned
        status = "ZONE_ALIGNED"
        reason = _state_reason(state, direction)
    elif conflicted:
        state, state_zone = conflicted
        status = "ZONE_CONFLICT"
        reason = _state_reason(state, direction)
    else:
        at_support = support_distance is not None and support_distance <= Decimal("0.15")
        at_resistance = resistance_distance is not None and resistance_distance <= Decimal("0.15")
        if at_support and at_resistance:
            state = "PINCHED_BETWEEN_ZONES"
            status = "ZONE_CONFLICT"
            reason = "Entry is within 0.15 ATR of both repeated support and resistance."
            state_zone = nearest_resistance if direction == "LONG" else nearest_support
        elif at_support:
            state = "AT_SUPPORT"
            state_zone = nearest_support
            status = "ZONE_ALIGNED" if direction == "LONG" else "ZONE_CONFLICT"
            reason = _state_reason(state, direction)
        elif at_resistance:
            state = "AT_RESISTANCE"
            state_zone = nearest_resistance
            status = "ZONE_ALIGNED" if direction == "SHORT" else "ZONE_CONFLICT"
            reason = _state_reason(state, direction)
        else:
            state = "MID_RANGE"
            status = "ZONE_NEUTRAL"
            reason = "Entry is not interacting with a nearby repeated support or resistance zone."
            state_zone = None
    return {
        "status": status,
        "state": state,
        "reason": reason,
        "nearest_support": _public_zone(nearest_support),
        "nearest_resistance": _public_zone(nearest_resistance),
        "nearest_support_distance_atr": support_distance,
        "nearest_resistance_distance_atr": resistance_distance,
        "state_zone": _public_zone(state_zone),
        "breakout_state_diagnostics": breakout_state_diagnostics(
            timeframe=timeframe,
            direction=direction,
            entry=entry,
            signal_candle=signal_candle,
            prior_candle=prior_candle,
            closed_candles=closed_candles,
            zones=zones,
            atr=atr,
            state_zone=state_zone,
        ),
    }


def distance_to_zone(entry: Decimal, zone: dict[str, Any] | None, atr: Decimal) -> Decimal | None:
    if zone is None or atr <= 0:
        return None
    lower = Decimal(zone["lower"])
    upper = Decimal(zone["upper"])
    if lower <= entry <= upper:
        return Decimal("0")
    return min(abs(entry - lower), abs(entry - upper)) / atr


def breakout_state_diagnostics(
    *,
    timeframe: str,
    direction: str,
    entry: Decimal,
    signal_candle: ZoneCandle,
    prior_candle: ZoneCandle,
    closed_candles: list[ZoneCandle],
    zones: list[dict[str, Any]],
    atr: Decimal,
    state_zone: dict[str, Any] | None,
) -> dict[str, Any]:
    analysis_zone, source = _analysis_zone_for_breakout(
        direction=direction,
        entry=entry,
        signal_candle=signal_candle,
        prior_candle=prior_candle,
        zones=zones,
        state_zone=state_zone,
        atr=atr,
    )
    if analysis_zone is None or atr <= 0:
        return {
            "status": "ZONE_DIAGNOSTICS_UNAVAILABLE",
            "reason": "No pre-entry repeated zone can anchor breakout-state diagnostics.",
            "zone_source_timeframe": timeframe,
            "zone_id": None,
            "zone_lower": None,
            "zone_upper": None,
            "zone_center": None,
            "zone_width_atr": None,
            "zone_touch_count": None,
            "zone_age_bars": None,
            "close_penetration_atr": None,
            "close_penetration_zone_width": None,
            "body_above_zone_ratio": None,
            "close_location_in_candle": _close_location(signal_candle),
            "upper_wick_to_body_ratio": _upper_wick_to_body(signal_candle),
            "breakout_candle_range_atr": _safe_div(signal_candle.high - signal_candle.low, atr),
            "breakout_body_atr": _safe_div(abs(signal_candle.close - signal_candle.open), atr),
            "bars_since_breakout": None,
            "entry_distance_from_zone_atr": None,
            "entry_extension_from_zone_atr": None,
            "room_to_next_resistance_atr": None,
            "room_to_next_support_atr": None,
            "next_resistance_zone": None,
            "next_support_zone": None,
            "no_future_data": True,
        }
    lower = Decimal(analysis_zone["lower"])
    upper = Decimal(analysis_zone["upper"])
    center = Decimal(analysis_zone["center"])
    width = upper - lower
    next_resistance = _next_zone(
        zones,
        direction="UP",
        entry=entry,
        exclude=analysis_zone,
    )
    next_support = _next_zone(
        zones,
        direction="DOWN",
        entry=entry,
        exclude=analysis_zone,
    )
    close_penetration = (
        signal_candle.close - upper
        if direction == "LONG"
        else lower - signal_candle.close
        if direction == "SHORT"
        else None
    )
    entry_extension = (
        max(entry - upper, Decimal("0"))
        if direction == "LONG"
        else max(lower - entry, Decimal("0"))
        if direction == "SHORT"
        else None
    )
    return {
        "status": "ZONE_DIAGNOSTICS_AVAILABLE",
        "reason": f"Diagnostics use a pre-entry {source} zone from closed {timeframe} candles.",
        "zone_source_timeframe": timeframe,
        "zone_id": _zone_id(timeframe, analysis_zone),
        "zone_lower": lower,
        "zone_upper": upper,
        "zone_center": center,
        "zone_width_price": width,
        "zone_width_atr": _safe_div(width, atr),
        "zone_touch_count": int(analysis_zone.get("touch_count") or 0),
        "zone_reaction_count": int(analysis_zone.get("support_touch_count") or 0)
        + int(analysis_zone.get("resistance_touch_count") or 0),
        "zone_age_bars": _zone_age_bars(closed_candles, analysis_zone, signal_candle),
        "zone_created_at": analysis_zone.get("first_touch_time"),
        "zone_last_touch_at": analysis_zone.get("last_touch_time"),
        "close_penetration_atr": _safe_div(close_penetration, atr),
        "close_penetration_zone_width": _safe_div(close_penetration, width),
        "body_above_zone_ratio": _body_beyond_zone_ratio(signal_candle, analysis_zone, direction),
        "close_location_in_candle": _close_location(signal_candle),
        "upper_wick_to_body_ratio": _upper_wick_to_body(signal_candle),
        "breakout_candle_range_atr": _safe_div(signal_candle.high - signal_candle.low, atr),
        "breakout_body_atr": _safe_div(abs(signal_candle.close - signal_candle.open), atr),
        "bars_since_breakout": _bars_since_breakout(
            direction=direction,
            candles=closed_candles,
            zone=analysis_zone,
        ),
        "entry_distance_from_zone_atr": distance_to_zone(entry, analysis_zone, atr),
        "entry_extension_from_zone_atr": _safe_div(entry_extension, atr),
        "room_to_next_resistance_atr": distance_to_zone(entry, next_resistance, atr),
        "room_to_next_support_atr": distance_to_zone(entry, next_support, atr),
        "next_resistance_zone": _public_zone(next_resistance),
        "next_support_zone": _public_zone(next_support),
        "no_future_data": True,
    }


def _analysis_zone_for_breakout(
    *,
    direction: str,
    entry: Decimal,
    signal_candle: ZoneCandle,
    prior_candle: ZoneCandle,
    zones: list[dict[str, Any]],
    state_zone: dict[str, Any] | None,
    atr: Decimal,
) -> tuple[dict[str, Any] | None, str]:
    breakout_candidates: list[dict[str, Any]] = []
    for zone in zones:
        lower = Decimal(zone["lower"])
        upper = Decimal(zone["upper"])
        if direction == "LONG" and prior_candle.close <= upper and signal_candle.close > upper:
            breakout_candidates.append(zone)
        elif direction == "SHORT" and prior_candle.close >= lower and signal_candle.close < lower:
            breakout_candidates.append(zone)
    if breakout_candidates:
        return min(
            breakout_candidates,
            key=lambda zone: distance_to_zone(entry, zone, atr) or Decimal("0"),
        ), "breakout"
    if state_zone is not None:
        return state_zone, "state"
    if direction == "LONG":
        fallback = max(
            (zone for zone in zones if Decimal(zone["center"]) <= entry),
            key=lambda zone: Decimal(zone["center"]),
            default=None,
        )
    elif direction == "SHORT":
        fallback = min(
            (zone for zone in zones if Decimal(zone["center"]) >= entry),
            key=lambda zone: Decimal(zone["center"]),
            default=None,
        )
    else:
        fallback = None
    return fallback, "nearest"


def _next_zone(
    zones: list[dict[str, Any]],
    *,
    direction: str,
    entry: Decimal,
    exclude: dict[str, Any] | None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for zone in zones:
        if _same_zone(zone, exclude):
            continue
        lower = Decimal(zone["lower"])
        upper = Decimal(zone["upper"])
        center = Decimal(zone["center"])
        if direction == "UP" and (lower > entry or center > entry):
            candidates.append(zone)
        elif direction == "DOWN" and (upper < entry or center < entry):
            candidates.append(zone)
    if direction == "UP":
        return min(candidates, key=lambda zone: Decimal(zone["center"]), default=None)
    return max(candidates, key=lambda zone: Decimal(zone["center"]), default=None)


def _same_zone(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if left is None or right is None:
        return False
    return (
        Decimal(left["lower"]) == Decimal(right["lower"])
        and Decimal(left["upper"]) == Decimal(right["upper"])
        and Decimal(left["center"]) == Decimal(right["center"])
    )


def _safe_div(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _body_beyond_zone_ratio(candle: ZoneCandle, zone: dict[str, Any], direction: str) -> Decimal | None:
    body_low = min(candle.open, candle.close)
    body_high = max(candle.open, candle.close)
    body = body_high - body_low
    if body <= 0:
        return None
    lower = Decimal(zone["lower"])
    upper = Decimal(zone["upper"])
    if direction == "LONG":
        beyond = max(body_high - max(body_low, upper), Decimal("0"))
    elif direction == "SHORT":
        beyond = max(min(body_high, lower) - body_low, Decimal("0"))
    else:
        return None
    return min(max(beyond / body, Decimal("0")), Decimal("1"))


def _close_location(candle: ZoneCandle) -> Decimal | None:
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return None
    return (candle.close - candle.low) / candle_range


def _upper_wick_to_body(candle: ZoneCandle) -> Decimal | None:
    body = abs(candle.close - candle.open)
    if body <= 0:
        return None
    upper_wick = candle.high - max(candle.open, candle.close)
    return upper_wick / body


def _bars_since_breakout(
    *,
    direction: str,
    candles: list[ZoneCandle],
    zone: dict[str, Any],
) -> int | None:
    ordered = sorted(candles, key=lambda candle: candle.close_time)
    if not ordered:
        return None
    lower = Decimal(zone["lower"])
    upper = Decimal(zone["upper"])
    last_breakout_index = None
    for index, candle in enumerate(ordered):
        prior = ordered[index - 1] if index > 0 else None
        if direction == "LONG":
            crossed = candle.close > upper and (prior is None or prior.close <= upper)
        elif direction == "SHORT":
            crossed = candle.close < lower and (prior is None or prior.close >= lower)
        else:
            crossed = False
        if crossed:
            last_breakout_index = index
    if last_breakout_index is None:
        return None
    return len(ordered) - 1 - last_breakout_index


def _zone_age_bars(candles: list[ZoneCandle], zone: dict[str, Any], signal_candle: ZoneCandle) -> int | None:
    last_touch = _as_datetime(zone.get("last_touch_time"))
    if last_touch is None:
        return None
    return sum(1 for candle in candles if last_touch < candle.close_time <= signal_candle.close_time)


def _zone_id(timeframe: str, zone: dict[str, Any]) -> str:
    first_touch = zone.get("first_touch_time")
    center = Decimal(zone["center"]).normalize()
    return f"{timeframe}:{center}:{first_touch}"


def structure_zone_chart_zones(
    snapshot: dict[str, Any] | None,
    *,
    chart_start: datetime,
    chart_end: datetime,
    min_price: Decimal,
    max_price: Decimal,
) -> list[dict[str, Any]]:
    primary = snapshot.get("primary") if isinstance(snapshot, dict) else None
    zones = primary.get("zones") if isinstance(primary, dict) else None
    primary_timeframe = str(snapshot.get("primary_timeframe") or "") if isinstance(snapshot, dict) else ""
    primary_state = str(primary.get("state") or "") if isinstance(primary, dict) else ""
    state_zone = primary.get("state_zone") if isinstance(primary, dict) else None
    state_zone_center = _decimal(state_zone.get("center")) if isinstance(state_zone, dict) else None
    if not isinstance(zones, list):
        return []
    visible: list[dict[str, Any]] = []
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        lower = _decimal(zone.get("lower"))
        upper = _decimal(zone.get("upper"))
        if lower is None or upper is None or upper < min_price or lower > max_price:
            continue
        first_touch = _as_datetime(zone.get("first_touch_time")) or chart_start
        visible.append(
            {
                **zone,
                "source_timeframe": primary_timeframe,
                "signal_state": primary_state if state_zone_center is not None and lower <= state_zone_center <= upper else None,
                "is_signal_zone": state_zone_center is not None and lower <= state_zone_center <= upper,
                "start_time": max(_naive(first_touch), _naive(chart_start)),
                "end_time": _naive(chart_end),
            }
        )
    return json_safe(visible)


def pending_structure_zone_shadow(reason: str = "Signal has not been persisted by the research cycle yet.") -> dict[str, Any]:
    return {
        "version": "STRUCTURE_ZONE_SHADOW_V1",
        "status": "ZONE_PENDING",
        "reason": reason,
        "primary_timeframe": None,
        "primary": None,
        "context_timeframe": None,
        "context": None,
        "read_only": True,
        "not_signal_gate": True,
        "not_execution_instruction": True,
    }


def _nearest_event(
    events: list[tuple[str, dict[str, Any]]],
    states: set[str],
    entry: Decimal,
    atr: Decimal,
) -> tuple[str, dict[str, Any]] | None:
    matching = [event for event in events if event[0] in states]
    return min(
        matching,
        key=lambda event: distance_to_zone(entry, event[1], atr) or Decimal("0"),
        default=None,
    )


def _state_reason(state: str, direction: str) -> str:
    reasons = {
        "AT_SUPPORT": f"{direction.title()} entry is within 0.15 ATR of repeated support.",
        "AT_RESISTANCE": f"{direction.title()} entry is within 0.15 ATR of repeated resistance.",
        "SUPPORT_BOUNCE": "The signal candle tested repeated support and closed back above it.",
        "RESISTANCE_REJECTION": "The signal candle tested repeated resistance and closed back below it.",
        "SUPPORT_BREAK": "The signal candle closed below support held by the prior candle.",
        "RESISTANCE_BREAKOUT": "The signal candle closed above resistance held by the prior candle.",
        "BREAK_RETEST_REJECTED": "Price retested broken support and closed below the repeated zone.",
        "BREAKOUT_RETEST_HELD": "Price retested broken resistance and closed above the repeated zone.",
        "FAILED_BREAKDOWN_RECLAIM": "Price moved below the zone then reclaimed it on the signal candle.",
        "FAILED_BREAKOUT_REJECT": "Price moved above the zone then rejected below it on the signal candle.",
    }
    return reasons.get(state, "Repeated-zone structure was classified at signal time.")


def _combined_status(primary: dict[str, Any], context: dict[str, Any]) -> tuple[str, str]:
    primary_status = str(primary.get("status") or "ZONE_UNAVAILABLE")
    context_status = str(context.get("status") or "ZONE_UNAVAILABLE")
    if primary_status == "ZONE_UNAVAILABLE":
        return "ZONE_UNAVAILABLE", str(primary.get("reason") or "Primary structure is unavailable.")
    if primary_status == "ZONE_CONFLICT":
        return "ZONE_CONFLICT", str(primary.get("reason") or "Primary structure conflicts with direction.")
    if context_status == "ZONE_CONFLICT":
        return "ZONE_CONFLICT", f"Primary: {primary.get('reason')} Higher context: {context.get('reason')}"
    if primary_status == "ZONE_ALIGNED":
        suffix = " Higher-timeframe context is unavailable." if context_status == "ZONE_UNAVAILABLE" else ""
        return "ZONE_ALIGNED", f"{primary.get('reason')}{suffix}"
    return "ZONE_NEUTRAL", str(primary.get("reason") or "Primary structure is neutral.")


def _not_applicable_context() -> dict[str, Any]:
    return {
        "status": "ZONE_NOT_APPLICABLE",
        "state": "NO_HIGHER_TIMEFRAME_CONTEXT",
        "reason": "No higher context timeframe is configured for this signal timeframe.",
        "history_count": 0,
        "atr_at_signal": None,
        "zone_count": 0,
        "zones": [],
    }


def _public_zone(zone: dict[str, Any] | None) -> dict[str, Any] | None:
    if zone is None:
        return None
    return {key: value for key, value in zone.items() if not str(key).startswith("_")}


def _direction(value: Any) -> str:
    normalized = str(value or "").upper()
    if normalized in {"LONG", "BULLISH_CONTEXT", "BULLISH"}:
        return "LONG"
    if normalized in {"SHORT", "BEARISH_CONTEXT", "BEARISH"}:
        return "SHORT"
    return normalized or "MIXED"


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _naive(value)
    if not value:
        return None
    try:
        return _naive(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
