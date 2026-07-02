from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


EARLY_SIGNAL_LOGIC_VERSION = "normalized_impulse_early_v1"


@dataclass(frozen=True)
class EarlySignalQuality:
    is_early_long: bool
    is_early_short: bool
    quality_score: int
    quality_bucket: str
    reasons: list[str]
    logic_version: str = EARLY_SIGNAL_LOGIC_VERSION


def evaluate_early_signal_quality(
    *,
    price_return_pct: Any,
    close_position: Any,
    taker_buy_ratio: Any,
    oi_change_pct: Any = None,
    volume_ratio_vs_baseline: Any = None,
    range_ratio_vs_baseline: Any = None,
    atr_extension: Any = None,
    spot_support_status: str | None = None,
    spot_context: str | None = None,
    one_hour_return_pct: Any = None,
    funding_rate: Any = None,
    direction_hint: str | None = None,
) -> EarlySignalQuality:
    price_return = _dec(price_return_pct)
    close_pos = _dec(close_position)
    taker_buy = _dec(taker_buy_ratio)
    taker_sell = Decimal("1") - taker_buy if taker_buy is not None else None
    oi_change = _dec(oi_change_pct)
    volume_ratio = _dec(volume_ratio_vs_baseline)
    range_ratio = _dec(range_ratio_vs_baseline)
    extension = _dec(atr_extension)
    one_hour_return = _dec(one_hour_return_pct)
    funding = _dec(funding_rate)
    spot = (spot_support_status or spot_context or "").upper()

    bullish_base = (
        price_return is not None
        and price_return > 0
        and _gte(close_pos, Decimal("0.65"))
        and (taker_buy is None or _gte(taker_buy, Decimal("0.55")))
    )
    bearish_base = (
        price_return is not None
        and price_return < 0
        and _lte(close_pos, Decimal("0.35"))
        and (taker_sell is None or _gte(taker_sell, Decimal("0.55")))
    )

    if direction_hint == "LONG":
        score, reasons = _score_long(
            volume_ratio=volume_ratio,
            range_ratio=range_ratio,
            oi_change=oi_change,
            extension=extension,
            spot=spot,
            one_hour_return=one_hour_return,
            funding=funding,
            price_return=price_return,
        )
        return EarlySignalQuality(
            is_early_long=bullish_base,
            is_early_short=False,
            quality_score=score,
            quality_bucket=_bucket(score),
            reasons=reasons,
        )
    if direction_hint == "SHORT":
        score, reasons = _score_short(
            volume_ratio=volume_ratio,
            range_ratio=range_ratio,
            oi_change=oi_change,
            extension=extension,
            spot=spot,
            one_hour_return=one_hour_return,
            funding=funding,
            price_return=price_return,
        )
        return EarlySignalQuality(
            is_early_long=False,
            is_early_short=bearish_base,
            quality_score=score,
            quality_bucket=_bucket(score),
            reasons=reasons,
        )

    if bullish_base:
        score, reasons = _score_long(
            volume_ratio=volume_ratio,
            range_ratio=range_ratio,
            oi_change=oi_change,
            extension=extension,
            spot=spot,
            one_hour_return=one_hour_return,
            funding=funding,
            price_return=price_return,
        )
        return EarlySignalQuality(True, False, score, _bucket(score), reasons)
    if bearish_base:
        score, reasons = _score_short(
            volume_ratio=volume_ratio,
            range_ratio=range_ratio,
            oi_change=oi_change,
            extension=extension,
            spot=spot,
            one_hour_return=one_hour_return,
            funding=funding,
            price_return=price_return,
        )
        return EarlySignalQuality(False, True, score, _bucket(score), reasons)
    return EarlySignalQuality(False, False, 0, "LOW_QUALITY", ["base early impulse conditions not met"])


def _score_long(
    *,
    volume_ratio: Decimal | None,
    range_ratio: Decimal | None,
    oi_change: Decimal | None,
    extension: Decimal | None,
    spot: str,
    one_hour_return: Decimal | None,
    funding: Decimal | None,
    price_return: Decimal | None,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    score += _spike_points("volume", volume_ratio, reasons)
    score += _spike_points("range", range_ratio, reasons)
    if oi_change is not None and oi_change > 0:
        score += 1
        reasons.append("OI expands with long impulse")
    if "SPOT_SUPPORTING" in spot or "SPOT_SUPPORTING_MOVE" in spot:
        score += 2
        reasons.append("spot supports long impulse")
    elif "WEAK_SPOT_SUPPORT" not in spot:
        score += 1
        reasons.append("spot is not weak")
    if one_hour_return is not None and one_hour_return >= Decimal("-0.15"):
        score += 1
        reasons.append("1h context is not strongly against long")
    score += _extension_points(extension, reasons)
    if funding is not None and funding <= Decimal("0.0005"):
        score += 1
        reasons.append("funding not crowded against long")
    if price_return is not None and abs(price_return) >= Decimal("0.35"):
        score += 1
        reasons.append("15m impulse is meaningful")
    return min(score, 10), reasons


def _score_short(
    *,
    volume_ratio: Decimal | None,
    range_ratio: Decimal | None,
    oi_change: Decimal | None,
    extension: Decimal | None,
    spot: str,
    one_hour_return: Decimal | None,
    funding: Decimal | None,
    price_return: Decimal | None,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    score += _spike_points("volume", volume_ratio, reasons)
    score += _spike_points("range", range_ratio, reasons)
    if oi_change is not None and oi_change > 0:
        score += 1
        reasons.append("OI expands with short pressure")
    if "WEAK_SPOT_SUPPORT" in spot:
        score += 2
        reasons.append("spot support is weak")
    elif "SPOT_SUPPORTING" not in spot:
        score += 1
        reasons.append("spot is not clearly supporting against short")
    if one_hour_return is not None and one_hour_return <= Decimal("0.15"):
        score += 1
        reasons.append("1h context is not strongly against short")
    score += _extension_points(extension, reasons)
    if funding is not None and funding >= Decimal("0"):
        score += 1
        reasons.append("funding/long crowding does not block short")
    if price_return is not None and abs(price_return) >= Decimal("0.35"):
        score += 1
        reasons.append("15m impulse is meaningful")
    return min(score, 10), reasons


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


def _extension_points(value: Decimal | None, reasons: list[str]) -> int:
    if value is None:
        return 0
    if value <= Decimal("0.8"):
        reasons.append("not overextended versus ATR reference")
        return 2
    if value <= Decimal("1.2"):
        reasons.append("acceptable extension versus ATR reference")
        return 1
    return 0


def _bucket(score: int) -> str:
    if score >= 8:
        return "HIGH_QUALITY"
    if score >= 6:
        return "MEDIUM_QUALITY"
    return "LOW_QUALITY"


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _gte(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value >= threshold


def _lte(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value <= threshold
