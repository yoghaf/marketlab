from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import (
    MarketFeature1h,
    MarketFeature15m,
    MarketFeatureContext15m1h,
    MarketlabActiveUniverse,
)
from app.services.utils import utcnow

CONTEXT_STATUSES = ("CONTEXT_READY", "CONTEXT_PARTIAL", "CONTEXT_BLOCKED")
USABLE_FEATURE_STATUSES = {"FEATURE_READY", "FEATURE_PARTIAL"}
SPOT_SUPPORT_STATUSES = ("SPOT_SUPPORTING", "WEAK_SPOT_SUPPORT", "FUTURES_LED", "SPOT_MISSING", "SPOT_UNKNOWN")


@dataclass(frozen=True)
class SpotFuturesEvidenceConfig:
    weak_spot_ratio_threshold: Decimal = Decimal("0.20")
    strong_spot_ratio_threshold: Decimal = Decimal("0.50")
    taker_support_threshold: Decimal = Decimal("0.55")
    futures_led_score_threshold: Decimal = Decimal("0.65")
    spot_support_score_threshold: Decimal = Decimal("0.75")
    directional_move_threshold_pct: Decimal = Decimal("0.10")


@dataclass
class FeatureContextJoinResult:
    symbols: int
    inserted_count: int
    updated_count: int
    status_counts: dict[str, int]


class FeatureContextJoinService:
    def __init__(self, db: Session, evidence_config: SpotFuturesEvidenceConfig | None = None) -> None:
        self.db = db
        self.evidence_config = evidence_config or SpotFuturesEvidenceConfig()

    def run(
        self,
        symbols: list[str] | None = None,
        limit_windows: int | None = None,
        dry_run: bool = False,
    ) -> FeatureContextJoinResult:
        active_symbols = self._active_symbols(symbols)
        inserted = 0
        updated = 0
        status_counts = {status: 0 for status in CONTEXT_STATUSES}
        now = utcnow()
        for symbol in active_symbols:
            rows_15m = self._feature_15m_windows(symbol, limit_windows)
            for feature_15m in rows_15m:
                payload = self._join_window(feature_15m, now)
                action = self._upsert(payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts[payload["context_status"]] += 1
        if not dry_run:
            self.db.commit()
        return FeatureContextJoinResult(
            symbols=len(active_symbols),
            inserted_count=inserted,
            updated_count=updated,
            status_counts=status_counts,
        )

    def status_summary(self) -> dict[str, Any]:
        rows = self.db.execute(
            select(
                MarketFeatureContext15m1h.context_status,
                MarketFeatureContext15m1h.spot_support_status_15m,
                func.count(),
                func.max(MarketFeatureContext15m1h.feature_15m_window_close_time),
            ).group_by(
                MarketFeatureContext15m1h.context_status,
                MarketFeatureContext15m1h.spot_support_status_15m,
            )
        ).all()
        latest_context_time = None
        total_context_rows = 0
        counts = {status: 0 for status in CONTEXT_STATUSES}
        spot_support_counts = {status: 0 for status in SPOT_SUPPORT_STATUSES}
        for context_status, spot_status, count, latest_time in rows:
            total_context_rows += count
            counts[context_status] += count
            normalized_spot_status = spot_status or "SPOT_UNKNOWN"
            spot_support_counts[normalized_spot_status] = spot_support_counts.get(normalized_spot_status, 0) + count
            if latest_time is not None and (latest_context_time is None or latest_time > latest_context_time):
                latest_context_time = latest_time
        latest_symbols_count = 0
        if latest_context_time is not None:
            latest_symbols_count = (
                self.db.scalar(
                    select(func.count(func.distinct(MarketFeatureContext15m1h.symbol))).where(
                        MarketFeatureContext15m1h.feature_15m_window_close_time == latest_context_time,
                        MarketFeatureContext15m1h.context_status.in_(("CONTEXT_READY", "CONTEXT_PARTIAL")),
                    )
                )
                or 0
            )
        return {
            "latest_context_time": latest_context_time,
            "total_context_rows": total_context_rows,
            "context_ready_count": counts["CONTEXT_READY"],
            "context_partial_count": counts["CONTEXT_PARTIAL"],
            "context_blocked_count": counts["CONTEXT_BLOCKED"],
            "latest_symbols_count": latest_symbols_count,
            "spot_support_counts": spot_support_counts,
            "thresholds": {
                "weak_spot_ratio_threshold": self.evidence_config.weak_spot_ratio_threshold,
                "strong_spot_ratio_threshold": self.evidence_config.strong_spot_ratio_threshold,
                "taker_support_threshold": self.evidence_config.taker_support_threshold,
                "futures_led_score_threshold": self.evidence_config.futures_led_score_threshold,
                "spot_support_score_threshold": self.evidence_config.spot_support_score_threshold,
                "directional_move_threshold_pct": self.evidence_config.directional_move_threshold_pct,
            },
        }

    def list_contexts(self, status: str | None = None, limit: int = 100) -> list[MarketFeatureContext15m1h]:
        query = select(MarketFeatureContext15m1h).order_by(
            desc(MarketFeatureContext15m1h.feature_15m_window_close_time),
            MarketFeatureContext15m1h.symbol,
        )
        if status:
            query = query.where(MarketFeatureContext15m1h.context_status == status)
        return list(self.db.scalars(query.limit(min(max(limit, 1), 500))).all())

    def _join_window(self, feature_15m: MarketFeature15m, now: datetime) -> dict[str, Any]:
        context_1h = self._nearest_closed_1h(feature_15m.symbol, _as_utc(feature_15m.window_close_time))
        spot_futures_evidence = self._spot_futures_evidence(feature_15m)
        reasons: list[str] = []

        if feature_15m.feature_status not in USABLE_FEATURE_STATUSES:
            reasons.append(f"15m feature status {feature_15m.feature_status}")
        if context_1h is None:
            reasons.append("missing closed 1h context")
        else:
            if context_1h.feature_status not in USABLE_FEATURE_STATUSES:
                reasons.append(f"1h feature status {context_1h.feature_status}")
            if _as_utc(context_1h.window_close_time) > _as_utc(feature_15m.window_close_time):
                reasons.append("1h context is future relative to 15m")
            if _as_utc(context_1h.window_open_time) >= _as_utc(feature_15m.window_close_time):
                reasons.append("1h context open time is not before 15m close")

        context_status = "CONTEXT_BLOCKED" if reasons else "CONTEXT_READY"
        return {
            "symbol": feature_15m.symbol,
            "feature_15m_window_open_time": feature_15m.window_open_time,
            "feature_15m_window_close_time": feature_15m.window_close_time,
            "context_1h_window_open_time": context_1h.window_open_time if context_1h else None,
            "context_1h_window_close_time": context_1h.window_close_time if context_1h else None,
            "feature_15m_status": feature_15m.feature_status,
            "feature_1h_status": context_1h.feature_status if context_1h else None,
            "context_status": context_status,
            "context_block_reason": "; ".join(reasons) if reasons else None,
            "price_return_pct_15m": feature_15m.price_return_pct,
            "range_pct_15m": feature_15m.range_pct,
            "close_position_15m": feature_15m.close_position,
            "kline_taker_buy_ratio_15m": feature_15m.kline_taker_buy_ratio,
            **spot_futures_evidence,
            "oi_change_pct_15m": feature_15m.oi_change_pct,
            "global_long_short_ratio_15m": feature_15m.global_long_short_ratio,
            "top_trader_position_ratio_15m": feature_15m.top_trader_position_ratio,
            "funding_status_15m": feature_15m.funding_status,
            "price_return_pct_1h": context_1h.price_return_pct if context_1h else None,
            "range_pct_1h": context_1h.range_pct if context_1h else None,
            "close_position_1h": context_1h.close_position if context_1h else None,
            "kline_taker_buy_ratio_1h": context_1h.kline_taker_buy_ratio if context_1h else None,
            "oi_change_pct_1h": context_1h.oi_change_pct if context_1h else None,
            "global_long_short_ratio_1h": context_1h.global_long_short_ratio if context_1h else None,
            "top_trader_position_ratio_1h": context_1h.top_trader_position_ratio if context_1h else None,
            "funding_status_1h": context_1h.funding_status if context_1h else None,
            "created_at": now,
            "updated_at": now,
        }

    def _spot_futures_evidence(self, feature_15m: MarketFeature15m) -> dict[str, Any]:
        cfg = self.evidence_config
        direction = _direction(feature_15m.price_return_pct, cfg.directional_move_threshold_pct)
        ratio = feature_15m.spot_futures_volume_ratio
        futures_taker = feature_15m.kline_taker_buy_ratio
        spot_taker = feature_15m.spot_taker_buy_ratio
        spot_missing = bool(feature_15m.spot_missing_flag)

        spot_support_score = _spot_support_score(
            direction=direction,
            ratio=ratio,
            spot_taker=spot_taker,
            strong_spot_ratio_threshold=cfg.strong_spot_ratio_threshold,
            taker_support_threshold=cfg.taker_support_threshold,
        )
        futures_led_score = _futures_led_score(
            direction=direction,
            ratio=ratio,
            futures_taker=futures_taker,
            spot_missing=spot_missing,
            weak_spot_ratio_threshold=cfg.weak_spot_ratio_threshold,
            strong_spot_ratio_threshold=cfg.strong_spot_ratio_threshold,
            taker_support_threshold=cfg.taker_support_threshold,
        )
        status = _spot_support_status(
            direction=direction,
            ratio=ratio,
            spot_missing=spot_missing,
            spot_support_score=spot_support_score,
            futures_led_score=futures_led_score,
            config=cfg,
        )

        return {
            "futures_volume_15m": feature_15m.futures_volume,
            "spot_volume_15m": feature_15m.spot_volume,
            "futures_quote_volume_15m": feature_15m.futures_quote_volume,
            "spot_quote_volume_15m": feature_15m.spot_quote_volume,
            "spot_futures_volume_ratio_15m": ratio,
            "futures_taker_buy_ratio_15m": futures_taker,
            "spot_taker_buy_ratio_15m": spot_taker,
            "spot_missing_flag_15m": spot_missing,
            "spot_support_status_15m": status,
            "futures_led_score_15m": futures_led_score,
            "spot_support_score_15m": spot_support_score,
        }

    def _feature_15m_windows(self, symbol: str, limit_windows: int | None) -> list[MarketFeature15m]:
        query = (
            select(MarketFeature15m)
            .where(MarketFeature15m.symbol == symbol)
            .order_by(desc(MarketFeature15m.window_open_time))
        )
        if limit_windows:
            query = query.limit(limit_windows)
        rows = list(self.db.scalars(query).all())
        rows.reverse()
        return rows

    def _nearest_closed_1h(self, symbol: str, feature_15m_close: datetime) -> MarketFeature1h | None:
        return self.db.scalar(
            select(MarketFeature1h)
            .where(
                MarketFeature1h.symbol == symbol,
                MarketFeature1h.window_close_time <= feature_15m_close,
            )
            .order_by(desc(MarketFeature1h.window_close_time))
            .limit(1)
        )

    def _upsert(self, payload: dict[str, Any], dry_run: bool) -> str:
        row = self.db.scalar(
            select(MarketFeatureContext15m1h).where(
                MarketFeatureContext15m1h.symbol == payload["symbol"],
                MarketFeatureContext15m1h.feature_15m_window_open_time == payload["feature_15m_window_open_time"],
            )
        )
        if dry_run:
            return "updated" if row else "inserted"
        if row:
            for key, value in payload.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        self.db.add(MarketFeatureContext15m1h(**payload))
        return "inserted"

    def _active_symbols(self, requested: list[str] | None) -> list[str]:
        query = (
            select(MarketlabActiveUniverse.symbol)
            .where(
                MarketlabActiveUniverse.is_active.is_(True),
                MarketlabActiveUniverse.collection_tier == "FULL_ACTIVE",
                MarketlabActiveUniverse.is_full_active.is_(True),
            )
            .order_by(MarketlabActiveUniverse.rank.asc())
        )
        active = self.db.scalars(query).all()
        if not requested:
            return active
        requested_set = {symbol.upper() for symbol in requested}
        return [symbol for symbol in active if symbol in requested_set]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _direction(price_return_pct: Decimal | None, threshold: Decimal) -> int:
    if price_return_pct is None:
        return 0
    if price_return_pct >= threshold:
        return 1
    if price_return_pct <= -threshold:
        return -1
    return 0


def _supports_direction(direction: int, taker_buy_ratio: Decimal | None, threshold: Decimal) -> bool:
    if direction == 0 or taker_buy_ratio is None:
        return False
    if direction > 0:
        return taker_buy_ratio >= threshold
    return taker_buy_ratio <= Decimal("1") - threshold


def _ratio_score(value: Decimal | None, threshold: Decimal) -> Decimal:
    if value is None or threshold == Decimal("0"):
        return Decimal("0")
    return min(max(value / threshold, Decimal("0")), Decimal("1"))


def _low_ratio_score(value: Decimal | None, weak_threshold: Decimal, strong_threshold: Decimal) -> Decimal:
    if value is None:
        return Decimal("0")
    if value <= weak_threshold:
        return Decimal("1")
    if value >= strong_threshold or strong_threshold == weak_threshold:
        return Decimal("0")
    return (strong_threshold - value) / (strong_threshold - weak_threshold)


def _spot_support_score(
    direction: int,
    ratio: Decimal | None,
    spot_taker: Decimal | None,
    strong_spot_ratio_threshold: Decimal,
    taker_support_threshold: Decimal,
) -> Decimal:
    if direction == 0:
        return Decimal("0.0000")
    ratio_component = _ratio_score(ratio, strong_spot_ratio_threshold) * Decimal("0.60")
    taker_component = Decimal("0.40") if _supports_direction(direction, spot_taker, taker_support_threshold) else Decimal("0")
    return (ratio_component + taker_component).quantize(Decimal("0.0001"))


def _futures_led_score(
    direction: int,
    ratio: Decimal | None,
    futures_taker: Decimal | None,
    spot_missing: bool,
    weak_spot_ratio_threshold: Decimal,
    strong_spot_ratio_threshold: Decimal,
    taker_support_threshold: Decimal,
) -> Decimal:
    if direction == 0:
        return Decimal("0.0000")
    ratio_component = Decimal("0.50") if spot_missing else _low_ratio_score(
        ratio,
        weak_spot_ratio_threshold,
        strong_spot_ratio_threshold,
    ) * Decimal("0.50")
    taker_component = Decimal("0.50") if _supports_direction(direction, futures_taker, taker_support_threshold) else Decimal("0")
    return (ratio_component + taker_component).quantize(Decimal("0.0001"))


def _spot_support_status(
    direction: int,
    ratio: Decimal | None,
    spot_missing: bool,
    spot_support_score: Decimal,
    futures_led_score: Decimal,
    config: SpotFuturesEvidenceConfig,
) -> str:
    if spot_missing:
        return "SPOT_MISSING"
    if direction == 0 or ratio is None:
        return "SPOT_UNKNOWN"
    if spot_support_score >= config.spot_support_score_threshold:
        return "SPOT_SUPPORTING"
    if futures_led_score >= config.futures_led_score_threshold:
        return "FUTURES_LED"
    if ratio <= config.weak_spot_ratio_threshold:
        return "WEAK_SPOT_SUPPORT"
    return "SPOT_UNKNOWN"
