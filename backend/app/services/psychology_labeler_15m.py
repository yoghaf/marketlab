from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import MarketFeatureContext15m1h, MarketPsychologyLabel15m, MarketlabActiveUniverse
from app.services.utils import json_safe, utcnow

LABEL_STATUSES = ("LABEL_READY", "LABEL_PARTIAL", "LABEL_BLOCKED")
CONTEXT_USABLE_STATUSES = {"CONTEXT_READY", "CONTEXT_PARTIAL"}
PARTIAL_FEATURE_STATUSES = {"FEATURE_PARTIAL"}


@dataclass(frozen=True)
class PsychologyLabelConfig:
    positive_return_threshold: Decimal = Decimal("0")
    negative_return_threshold: Decimal = Decimal("0")
    high_close_position: Decimal = Decimal("0.65")
    low_close_position: Decimal = Decimal("0.35")
    high_taker_buy_ratio: Decimal = Decimal("0.55")
    high_taker_sell_ratio: Decimal = Decimal("0.55")
    crowded_long_ratio: Decimal = Decimal("1.50")
    crowded_short_ratio: Decimal = Decimal("0.85")
    positive_funding: Decimal = Decimal("0")
    negative_funding: Decimal = Decimal("0")


@dataclass
class PsychologyLabelResult:
    symbols: int
    inserted_count: int
    updated_count: int
    status_counts: dict[str, int]


class PsychologyLabeler15mService:
    def __init__(self, db: Session, config: PsychologyLabelConfig | None = None) -> None:
        self.db = db
        self.config = config or PsychologyLabelConfig()

    def run(
        self,
        symbols: list[str] | None = None,
        limit_windows: int | None = None,
        dry_run: bool = False,
    ) -> PsychologyLabelResult:
        active_symbols = self._active_symbols(symbols)
        inserted = 0
        updated = 0
        status_counts = {status: 0 for status in LABEL_STATUSES}
        now = utcnow()
        for symbol in active_symbols:
            contexts = self._context_windows(symbol, limit_windows)
            for context in contexts:
                payload = self._label_context(context, now)
                action = self._upsert(payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts[payload["label_status"]] += 1
        if not dry_run:
            self.db.commit()
        return PsychologyLabelResult(
            symbols=len(active_symbols),
            inserted_count=inserted,
            updated_count=updated,
            status_counts=status_counts,
        )

    def status_summary(self) -> dict[str, Any]:
        latest_label_time = self.db.scalar(select(func.max(MarketPsychologyLabel15m.window_close_time)))
        total_labels = self.db.scalar(select(func.count()).select_from(MarketPsychologyLabel15m)) or 0
        rows = self.db.execute(
            select(MarketPsychologyLabel15m.label_status, func.count()).group_by(MarketPsychologyLabel15m.label_status)
        ).all()
        counts = {status: 0 for status in LABEL_STATUSES}
        for status, count in rows:
            counts[status] = count
        top_rows = self.db.execute(
            select(MarketPsychologyLabel15m.primary_label, func.count())
            .group_by(MarketPsychologyLabel15m.primary_label)
            .order_by(desc(func.count()))
            .limit(10)
        ).all()
        return {
            "latest_label_time": latest_label_time,
            "total_labels": total_labels,
            "label_ready_count": counts["LABEL_READY"],
            "label_partial_count": counts["LABEL_PARTIAL"],
            "label_blocked_count": counts["LABEL_BLOCKED"],
            "top_primary_labels": [{"label": label, "count": count} for label, count in top_rows],
        }

    def list_labels(self, label_status: str | None = None, limit: int = 100) -> list[MarketPsychologyLabel15m]:
        query = select(MarketPsychologyLabel15m).order_by(
            desc(MarketPsychologyLabel15m.window_close_time),
            MarketPsychologyLabel15m.symbol,
        )
        if label_status:
            query = query.where(MarketPsychologyLabel15m.label_status == label_status)
        return list(self.db.scalars(query.limit(min(max(limit, 1), 500))).all())

    def _label_context(self, context: MarketFeatureContext15m1h, now: datetime) -> dict[str, Any]:
        evidence = self._evidence(context)
        labels: list[str] = []
        block_reason = context.context_block_reason

        if context.context_status == "CONTEXT_BLOCKED":
            return self._payload(
                context,
                primary_label="DATA_BLOCKED_CONTEXT",
                secondary_labels=[],
                confidence_level="LOW",
                confidence_score=Decimal("0.10"),
                evidence=evidence,
                label_status="LABEL_BLOCKED",
                block_reason=block_reason or "context status CONTEXT_BLOCKED",
                now=now,
            )

        if context.context_status not in CONTEXT_USABLE_STATUSES:
            return self._payload(
                context,
                primary_label="DATA_BLOCKED_CONTEXT",
                secondary_labels=[],
                confidence_level="LOW",
                confidence_score=Decimal("0.10"),
                evidence=evidence,
                label_status="LABEL_BLOCKED",
                block_reason=f"context status {context.context_status}",
                now=now,
            )

        if self._bullish_pressure(context):
            labels.append("BULLISH_PRESSURE")
        if self._bearish_pressure(context):
            labels.append("BEARISH_PRESSURE")

        price_15m = context.price_return_pct_15m
        oi_15m = context.oi_change_pct_15m
        long_short_ratio = context.global_long_short_ratio_15m
        funding_rate = self._funding_rate(evidence)

        if _positive(price_15m) and _positive(oi_15m):
            labels.append("LONG_BUILDUP_CONTEXT")
        if _negative(price_15m) and _positive(oi_15m):
            if _high(long_short_ratio, self.config.crowded_long_ratio) or _positive(funding_rate):
                labels.append("LONG_TRAP_RISK")
            else:
                labels.append("SHORT_BUILDUP_CONTEXT")
        if _positive(price_15m) and _negative(oi_15m):
            labels.append("SHORT_SQUEEZE_RISK")
            labels.append("SHORT_UNWIND_CONTEXT")
        if _negative(price_15m) and _negative(oi_15m):
            labels.append("LONG_UNWIND_CONTEXT")

        if _high(long_short_ratio, self.config.crowded_long_ratio) and _positive(funding_rate):
            labels.append("CROWDED_LONG_RISK")
        if _low(long_short_ratio, self.config.crowded_short_ratio) and _negative(funding_rate):
            labels.append("CROWDED_SHORT_RISK")

        if self._futures_led(context):
            labels.append("FUTURES_LED_MOVE")
            labels.append("WEAK_SPOT_SUPPORT")

        if not labels:
            labels.append("CHOPPY_CONTEXT")

        labels = _dedupe(labels)
        primary_label = labels[0]
        secondary_labels = labels[1:]
        partial = (
            context.feature_15m_status in PARTIAL_FEATURE_STATUSES
            or context.feature_1h_status in PARTIAL_FEATURE_STATUSES
            or "DATA_PARTIAL_CONTEXT" in labels
        )
        if partial and "DATA_PARTIAL_CONTEXT" not in secondary_labels and primary_label != "DATA_PARTIAL_CONTEXT":
            secondary_labels.append("DATA_PARTIAL_CONTEXT")

        confidence_score = self._confidence_score(context, labels)
        confidence_level = self._confidence_level(confidence_score)
        if partial and confidence_level == "HIGH":
            confidence_level = "MEDIUM"
            confidence_score = min(confidence_score, Decimal("0.69"))

        return self._payload(
            context,
            primary_label=primary_label,
            secondary_labels=secondary_labels,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            evidence=evidence,
            label_status="LABEL_PARTIAL" if partial else "LABEL_READY",
            block_reason="partial feature evidence" if partial else None,
            now=now,
        )

    def _payload(
        self,
        context: MarketFeatureContext15m1h,
        primary_label: str,
        secondary_labels: list[str],
        confidence_level: str,
        confidence_score: Decimal,
        evidence: dict[str, Any],
        label_status: str,
        block_reason: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        return {
            "symbol": context.symbol,
            "window_open_time": context.feature_15m_window_open_time,
            "window_close_time": context.feature_15m_window_close_time,
            "context_status": context.context_status,
            "primary_label": primary_label,
            "secondary_labels": secondary_labels,
            "confidence_level": confidence_level,
            "confidence_score": confidence_score,
            "evidence": json_safe(evidence),
            "label_status": label_status,
            "block_reason": block_reason,
            "created_at": now,
            "updated_at": now,
        }

    def _evidence(self, context: MarketFeatureContext15m1h) -> dict[str, Any]:
        taker_buy_15m = context.kline_taker_buy_ratio_15m
        return {
            "source": "market_feature_context_15m_1h",
            "not_a_signal": True,
            "context_status": context.context_status,
            "feature_15m_status": context.feature_15m_status,
            "feature_1h_status": context.feature_1h_status,
            "price_return_pct_15m": context.price_return_pct_15m,
            "range_pct_15m": context.range_pct_15m,
            "close_position_15m": context.close_position_15m,
            "kline_taker_buy_ratio_15m": taker_buy_15m,
            "kline_taker_sell_ratio_15m": Decimal("1") - taker_buy_15m if taker_buy_15m is not None else None,
            "oi_change_pct_15m": context.oi_change_pct_15m,
            "global_long_short_ratio_15m": context.global_long_short_ratio_15m,
            "top_trader_position_ratio_15m": context.top_trader_position_ratio_15m,
            "funding_status_15m": context.funding_status_15m,
            "price_return_pct_1h": context.price_return_pct_1h,
            "close_position_1h": context.close_position_1h,
            "kline_taker_buy_ratio_1h": context.kline_taker_buy_ratio_1h,
            "oi_change_pct_1h": context.oi_change_pct_1h,
            "global_long_short_ratio_1h": context.global_long_short_ratio_1h,
            "top_trader_position_ratio_1h": context.top_trader_position_ratio_1h,
            "funding_status_1h": context.funding_status_1h,
        }

    def _bullish_pressure(self, context: MarketFeatureContext15m1h) -> bool:
        return (
            _gt(context.price_return_pct_15m, self.config.positive_return_threshold)
            and _gt(context.close_position_15m, self.config.high_close_position)
            and _gt(context.kline_taker_buy_ratio_15m, self.config.high_taker_buy_ratio)
            and _gt(context.price_return_pct_1h, self.config.positive_return_threshold)
        )

    def _bearish_pressure(self, context: MarketFeatureContext15m1h) -> bool:
        sell_ratio = Decimal("1") - context.kline_taker_buy_ratio_15m if context.kline_taker_buy_ratio_15m is not None else None
        return (
            _lt(context.price_return_pct_15m, self.config.negative_return_threshold)
            and _lt(context.close_position_15m, self.config.low_close_position)
            and _gt(sell_ratio, self.config.high_taker_sell_ratio)
            and _lt(context.price_return_pct_1h, self.config.negative_return_threshold)
        )

    def _futures_led(self, context: MarketFeatureContext15m1h) -> bool:
        return False

    def _funding_rate(self, evidence: dict[str, Any]) -> Decimal | None:
        # Funding status is available in the context table; rate can be added later without changing label semantics.
        return None

    def _confidence_score(self, context: MarketFeatureContext15m1h, labels: list[str]) -> Decimal:
        score = Decimal("0.35")
        if context.context_status == "CONTEXT_READY":
            score += Decimal("0.20")
        if context.feature_15m_status == "FEATURE_READY":
            score += Decimal("0.15")
        if context.feature_1h_status == "FEATURE_READY":
            score += Decimal("0.15")
        if len(labels) >= 2 and labels[0] != "CHOPPY_CONTEXT":
            score += Decimal("0.10")
        return min(score, Decimal("0.95"))

    def _confidence_level(self, score: Decimal) -> str:
        if score >= Decimal("0.70"):
            return "HIGH"
        if score >= Decimal("0.45"):
            return "MEDIUM"
        return "LOW"

    def _context_windows(self, symbol: str, limit_windows: int | None) -> list[MarketFeatureContext15m1h]:
        query = (
            select(MarketFeatureContext15m1h)
            .where(MarketFeatureContext15m1h.symbol == symbol)
            .order_by(desc(MarketFeatureContext15m1h.feature_15m_window_open_time))
        )
        if limit_windows:
            query = query.limit(limit_windows)
        rows = list(self.db.scalars(query).all())
        rows.reverse()
        return rows

    def _upsert(self, payload: dict[str, Any], dry_run: bool) -> str:
        row = self.db.scalar(
            select(MarketPsychologyLabel15m).where(
                MarketPsychologyLabel15m.symbol == payload["symbol"],
                MarketPsychologyLabel15m.window_open_time == payload["window_open_time"],
            )
        )
        if dry_run:
            return "updated" if row else "inserted"
        if row:
            for key, value in payload.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        self.db.add(MarketPsychologyLabel15m(**payload))
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


def _positive(value: Decimal | None) -> bool:
    return value is not None and value > 0


def _negative(value: Decimal | None) -> bool:
    return value is not None and value < 0


def _high(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value >= threshold


def _low(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value <= threshold


def _gt(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value > threshold


def _lt(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value < threshold


def _dedupe(labels: list[str]) -> list[str]:
    seen = set()
    output = []
    for label in labels:
        if label not in seen:
            seen.add(label)
            output.append(label)
    return output
