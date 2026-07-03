from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


SIGNAL_FACTORY_V2_VERSION = "signal_factory_v2_layered_scoring_2026_07"
EARLY_SIGNAL_THRESHOLD = 7
MID_ATR_MULTIPLIER = Decimal("0.5")
OI_ZSCORE_THRESHOLD = Decimal("1.0")
SPREAD_WATCH_ONLY_PCT = Decimal("0.10")
ATR_REFERENCE_TIMEFRAME = {"15m": "1h", "1h": "4h", "4h": "24h", "24h": "24h"}
EXPECTED_ATR_RATIO = {
    ("15m", "1h"): Decimal("0.50"),
    ("1h", "4h"): Decimal("0.50"),
    ("4h", "24h"): Decimal("0.41"),
    ("24h", "24h"): Decimal("1.00"),
}


@dataclass(frozen=True)
class CoreScore:
    direction: str
    base_trigger: bool
    score: int
    max_score: int
    reasons: list[str]
    atr_extension_normalized: Decimal | None
    price_atr_multiple: Decimal | None
    oi_signal_source: str


@dataclass(frozen=True)
class EvidenceScore:
    score: int
    confidence_tier: str
    data_completeness: int
    flags: list[str]
    reasons: list[str]


@dataclass(frozen=True)
class RiskGate:
    execution: str
    flags: list[str]
    reasons: list[str]


@dataclass(frozen=True)
class EntryPlan:
    entry_mode: str
    entry_price: Decimal | None
    stop_loss_reference: Decimal | None
    take_profit_reference: Decimal | None
    rr: Decimal | None
    timeout_minutes: int
    notes: list[str]


def calculate_core_score(feature: dict[str, Any], direction: str, atr_reference_pct: Any = None) -> CoreScore:
    price_return = _dec(feature.get("price_return"))
    close_position = _dec(feature.get("close_position_in_range"))
    taker_buy = _dec(feature.get("kline_taker_buy_ratio"))
    taker_sell = Decimal("1") - taker_buy if taker_buy is not None else _dec(feature.get("kline_taker_sell_ratio"))
    atr_pct = _dec(feature.get("atr_pct"))
    volume_ratio = _dec(feature.get("volume_ratio_vs_lookback"))
    range_ratio = _dec(feature.get("range_ratio_vs_atr"))
    oi_zscore = _dec(feature.get("oi_zscore"))
    oi_change = _dec(feature.get("oi_change_pct"))
    funding_percentile = _dec(feature.get("funding_percentile_30d"))
    funding_rate = _dec(feature.get("funding_rate"))
    one_hour_return = _dec(feature.get("one_hour_return_pct"))
    spot = str(feature.get("spot_context") or "").upper()
    atr_extension = calculate_atr_extension_normalized(feature, atr_reference_pct)
    price_atr_multiple = abs(price_return) / atr_pct if price_return is not None and atr_pct and atr_pct > 0 else None
    score = 0
    reasons: list[str] = []

    if direction == "LONG":
        base_trigger = bool(price_return is not None and price_return > 0 and _gte(close_position, "0.65") and (taker_buy is None or _gte(taker_buy, "0.55")))
    else:
        base_trigger = bool(price_return is not None and price_return < 0 and _lte(close_position, "0.35") and (taker_sell is None or _gte(taker_sell, "0.55")))

    score += _spike_points("volume", volume_ratio, reasons)
    if range_ratio is not None and range_ratio <= Decimal("0.6"):
        score += 1
        reasons.append("range is efficient versus ATR")

    oi_signal_source = "missing"
    if oi_zscore is not None:
        oi_signal_source = "oi_zscore_30d"
        if oi_zscore >= OI_ZSCORE_THRESHOLD:
            score += 1
            reasons.append("OI z-score >= 1.0 versus token history")
    elif oi_change is not None:
        oi_signal_source = "oi_change_pct_fallback"
        if oi_change > 0:
            score += 1
            reasons.append("OI expands; z-score unavailable")

    if direction == "LONG":
        if "SPOT_SUPPORTING" in spot or "SPOT_SUPPORTING_MOVE" in spot:
            score += 2
            reasons.append("spot supports long impulse")
        elif "WEAK_SPOT_SUPPORT" not in spot:
            score += 1
            reasons.append("spot is not weak")
        if one_hour_return is not None and one_hour_return > 0:
            score += 1
            reasons.append("1h context aligns with long")
    else:
        if "WEAK_SPOT_SUPPORT" in spot:
            score += 2
            reasons.append("spot support is weak")
        elif "SPOT_SUPPORTING" not in spot:
            score += 1
            reasons.append("spot is not clearly supporting against short")
        if one_hour_return is not None and one_hour_return < 0:
            score += 1
            reasons.append("1h context aligns with short")

    if atr_extension is not None:
        if atr_extension <= Decimal("0.8"):
            score += 2
            reasons.append("not overextended versus normalized ATR reference")
        elif atr_extension <= Decimal("1.2"):
            score += 1
            reasons.append("acceptable extension versus normalized ATR reference")

    if funding_percentile is not None:
        if funding_percentile <= Decimal("70"):
            score += 1
            reasons.append("funding percentile is not crowded")
    elif funding_rate is not None:
        if (direction == "LONG" and funding_rate <= Decimal("0.0005")) or (direction == "SHORT" and funding_rate >= 0):
            score += 1
            reasons.append("funding fallback does not block direction")

    if price_atr_multiple is not None and price_atr_multiple >= MID_ATR_MULTIPLIER:
        score += 1
        reasons.append("price impulse >= 0.5 ATR")

    return CoreScore(
        direction=direction,
        base_trigger=base_trigger,
        score=min(score, 13),
        max_score=13,
        reasons=reasons,
        atr_extension_normalized=atr_extension,
        price_atr_multiple=price_atr_multiple,
        oi_signal_source=oi_signal_source,
    )


def calculate_evidence_score(feature: dict[str, Any], direction: str) -> EvidenceScore:
    global_ratio = _dec(feature.get("global_long_short_ratio"))
    top_position_ratio = _dec(feature.get("top_trader_position_ratio"))
    top_account_ratio = _dec(feature.get("top_trader_account_ratio"))
    rich_status = feature.get("rich_alignment_status")
    data_completeness = sum(
        1
        for available in (
            global_ratio is not None,
            top_position_ratio is not None,
            top_account_ratio is not None,
            rich_status is not None,
        )
        if available
    )
    score = 0
    flags: list[str] = []
    reasons: list[str] = []

    if global_ratio is not None:
        if direction == "LONG" and global_ratio >= Decimal("1.5"):
            score -= 1
            flags.append("RETAIL_CROWDED_CAUTION")
            reasons.append("global long/short ratio shows crowded long side")
        elif direction == "SHORT" and global_ratio <= Decimal("0.67"):
            score -= 1
            flags.append("RETAIL_CROWDED_CAUTION")
            reasons.append("global long/short ratio shows crowded short side")

    if top_position_ratio is not None:
        if direction == "LONG" and top_position_ratio >= Decimal("1.05"):
            score += 1
            reasons.append("top trader positioning confirms long context")
        elif direction == "SHORT" and top_position_ratio <= Decimal("0.95"):
            score += 1
            reasons.append("top trader positioning confirms short context")
        else:
            flags.append("CONFLICT_WITH_SMART_MONEY")
            reasons.append("top trader positioning does not confirm direction")

    if rich_status == "ALIGNED":
        score += 1
        reasons.append("rich 5m alignment is complete")
    elif rich_status:
        flags.append(f"RICH_ALIGNMENT_{rich_status}")

    if data_completeness == 0:
        confidence_tier = "EVIDENCE_UNAVAILABLE"
        flags.append("EVIDENCE_UNAVAILABLE")
        reasons.append("no external evidence source available")
    elif "CONFLICT_WITH_SMART_MONEY" in flags:
        confidence_tier = "CONFLICT"
    elif score >= 2:
        confidence_tier = "HIGH_CONF"
    elif score <= -1:
        confidence_tier = "LOW_CONF"
    else:
        confidence_tier = "MEDIUM_CONF"

    return EvidenceScore(
        score=score,
        confidence_tier=confidence_tier,
        data_completeness=data_completeness,
        flags=flags,
        reasons=reasons,
    )


def check_execution_risk(feature: dict[str, Any]) -> RiskGate:
    spread = _dec(feature.get("futures_spread_pct"))
    if spread is None:
        return RiskGate(execution="WATCH_ONLY", flags=["SPREAD_UNKNOWN"], reasons=["futures spread unavailable"])
    if spread > SPREAD_WATCH_ONLY_PCT:
        return RiskGate(execution="WATCH_ONLY", flags=["WIDE_SPREAD"], reasons=["futures spread above watch-only threshold"])
    return RiskGate(execution="ACTIVE", flags=[], reasons=["futures spread within threshold"])


def calculate_entry_sl_tp(feature: dict[str, Any], direction: str, stage: str, confidence_tier: str) -> EntryPlan:
    entry = _dec(feature.get("entry_price"))
    atr_pct = _dec(feature.get("atr_pct"))
    atr_extension = _dec(feature.get("atr_extension_normalized"))
    if entry is None or atr_pct is None:
        return EntryPlan(
            entry_mode="NO_PRICE_REFERENCE",
            entry_price=entry,
            stop_loss_reference=None,
            take_profit_reference=None,
            rr=None,
            timeout_minutes=60,
            notes=["missing entry price or ATR"],
        )
    k_sl = Decimal("0.8") if stage.startswith("EARLY") else Decimal("1.2")
    if confidence_tier == "LOW_CONF":
        k_sl = min(k_sl, Decimal("0.8"))
    rr = Decimal("2.0") if confidence_tier == "HIGH_CONF" else Decimal("1.5")
    risk = entry * (atr_pct / Decimal("100")) * k_sl
    if direction == "LONG":
        stop = entry - risk
        target = entry + (risk * rr)
    else:
        stop = entry + risk
        target = entry - (risk * rr)
    entry_mode = "MARKET_REFERENCE_OK"
    if stage.startswith("MID") and atr_extension is not None and atr_extension > Decimal("1.5"):
        entry_mode = "WAIT_PULLBACK_REFERENCE"
    return EntryPlan(
        entry_mode=entry_mode,
        entry_price=entry,
        stop_loss_reference=stop,
        take_profit_reference=target,
        rr=rr,
        timeout_minutes=60,
        notes=["read-only reference only", "not execution instruction"],
    )


def calculate_atr_extension_normalized(feature: dict[str, Any], atr_reference_pct: Any = None) -> Decimal | None:
    price_return_abs = _dec(feature.get("price_return_abs"))
    ref_pct = _dec(atr_reference_pct) or _dec(feature.get("atr_reference_pct")) or _dec(feature.get("atr_pct"))
    timeframe = str(feature.get("timeframe") or "15m")
    ref_timeframe = str(feature.get("atr_reference_timeframe") or ATR_REFERENCE_TIMEFRAME.get(timeframe, timeframe))
    expected_ratio = EXPECTED_ATR_RATIO.get((timeframe, ref_timeframe), Decimal("1.0"))
    if price_return_abs is None or ref_pct is None or ref_pct == 0 or expected_ratio == 0:
        return None
    return (price_return_abs / ref_pct) / expected_ratio


def is_mid_trigger(feature: dict[str, Any], direction: str) -> bool:
    price_return = _dec(feature.get("price_return"))
    atr_pct = _dec(feature.get("atr_pct"))
    oi_zscore = _dec(feature.get("oi_zscore"))
    oi_change = _dec(feature.get("oi_change_pct"))
    if price_return is None or atr_pct is None:
        return False
    price_ok = price_return >= (MID_ATR_MULTIPLIER * atr_pct) if direction == "LONG" else price_return <= -(MID_ATR_MULTIPLIER * atr_pct)
    if not price_ok:
        return False
    if oi_zscore is not None:
        return oi_zscore >= OI_ZSCORE_THRESHOLD
    return oi_change is not None and oi_change >= Decimal("0.10")


def to_payload(core: CoreScore, evidence: EvidenceScore, risk: RiskGate, entry: EntryPlan) -> dict[str, Any]:
    return {
        "logic_version": SIGNAL_FACTORY_V2_VERSION,
        "core_score": core.score,
        "core_score_max": core.max_score,
        "core_reasons": core.reasons,
        "base_trigger": core.base_trigger,
        "atr_extension_normalized": core.atr_extension_normalized,
        "price_atr_multiple": core.price_atr_multiple,
        "oi_signal_source": core.oi_signal_source,
        "evidence_score": evidence.score,
        "evidence_confidence_tier": evidence.confidence_tier,
        "evidence_data_completeness": evidence.data_completeness,
        "evidence_flags": evidence.flags,
        "evidence_reasons": evidence.reasons,
        "execution_risk_status": risk.execution,
        "execution_risk_flags": risk.flags,
        "execution_risk_reasons": risk.reasons,
        "entry_mode": entry.entry_mode,
        "entry_price": entry.entry_price,
        "stop_loss_reference": entry.stop_loss_reference,
        "take_profit_reference": entry.take_profit_reference,
        "rr": entry.rr,
        "timeout_minutes": entry.timeout_minutes,
        "entry_plan_notes": entry.notes,
    }


def _spike_points(name: str, value: Decimal | None, reasons: list[str]) -> int:
    if value is None:
        return 0
    if value >= Decimal("3.0"):
        reasons.append(f"{name} spike >= 3.0x token baseline")
        return 2
    if value >= Decimal("1.5"):
        reasons.append(f"{name} spike >= 1.5x token baseline")
        return 1
    return 0


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _gte(value: Decimal | None, threshold: str) -> bool:
    return value is not None and value >= Decimal(threshold)


def _lte(value: Decimal | None, threshold: str) -> bool:
    return value is not None and value <= Decimal(threshold)
