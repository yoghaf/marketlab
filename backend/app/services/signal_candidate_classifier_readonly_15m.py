from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import (
    MarketFeatureContext15m1h,
    MarketPsychologyLabel15m,
    MarketSignalCandidateReadonly15m,
    MarketlabActiveUniverse,
)
from app.services.early_signal_quality import evaluate_early_signal_quality
from app.services.utils import json_safe, utcnow

CLASSIFIER_STATUSES = ("CLASSIFIER_READY", "CLASSIFIER_PARTIAL", "CLASSIFIER_BLOCKED")
CANDIDATE_TYPES = (
    "EARLY_LONG_CANDIDATE_READONLY",
    "MID_LONG_CONTEXT_READONLY",
    "EARLY_SHORT_CANDIDATE_READONLY",
    "MID_SHORT_CONTEXT_READONLY",
    "SQUEEZE_RISK_CONTEXT_READONLY",
    "TRAP_RISK_CONTEXT_READONLY",
    "NO_SIGNAL_CONTEXT",
    "DATA_BLOCKED",
)
DIRECTIONS = ("BULLISH_CONTEXT", "BEARISH_CONTEXT", "MIXED_CONTEXT", "BLOCKED_CONTEXT")
BULLISH_LABELS = {"BULLISH_PRESSURE", "LONG_BUILDUP_CONTEXT", "SPOT_SUPPORTING_MOVE"}
BEARISH_LABELS = {"BEARISH_PRESSURE", "SHORT_BUILDUP_CONTEXT"}
SQUEEZE_LABELS = {"SHORT_SQUEEZE_RISK", "SHORT_UNWIND_CONTEXT"}
TRAP_LABELS = {"LONG_TRAP_RISK", "SHORT_TRAP_RISK"}


@dataclass(frozen=True)
class SignalCandidateReadonlyConfig:
    positive_return_threshold: Decimal = Decimal("0")
    negative_return_threshold: Decimal = Decimal("0")
    high_close_position: Decimal = Decimal("0.65")
    low_close_position: Decimal = Decimal("0.35")
    taker_support_threshold: Decimal = Decimal("0.55")
    strong_context_threshold: Decimal = Decimal("0.25")
    crowded_long_ratio: Decimal = Decimal("1.50")


@dataclass
class SignalCandidateReadonlyResult:
    symbols: int
    inserted_count: int
    updated_count: int
    status_counts: dict[str, int]


class SignalCandidateClassifierReadonly15mService:
    def __init__(self, db: Session, config: SignalCandidateReadonlyConfig | None = None) -> None:
        self.db = db
        self.config = config or SignalCandidateReadonlyConfig()

    def run(
        self,
        symbols: list[str] | None = None,
        limit_windows: int | None = None,
        dry_run: bool = False,
    ) -> SignalCandidateReadonlyResult:
        active_symbols = self._active_symbols(symbols)
        inserted = 0
        updated = 0
        status_counts = {status: 0 for status in CLASSIFIER_STATUSES}
        now = utcnow()
        for symbol in active_symbols:
            labels = self._psychology_rows(symbol, limit_windows)
            for label in labels:
                context = self._context_row(label)
                payload = self._classify(label, context, now)
                action = self._upsert(payload, dry_run)
                inserted += int(action == "inserted")
                updated += int(action == "updated")
                status_counts[payload["classifier_status"]] += 1
        if not dry_run:
            self.db.commit()
        return SignalCandidateReadonlyResult(
            symbols=len(active_symbols),
            inserted_count=inserted,
            updated_count=updated,
            status_counts=status_counts,
        )

    def status_summary(self) -> dict[str, Any]:
        rows = self.db.execute(
            select(
                MarketSignalCandidateReadonly15m.classifier_status,
                MarketSignalCandidateReadonly15m.candidate_type,
                MarketSignalCandidateReadonly15m.candidate_direction,
                func.count(),
                func.max(MarketSignalCandidateReadonly15m.window_close_time),
            ).group_by(
                MarketSignalCandidateReadonly15m.classifier_status,
                MarketSignalCandidateReadonly15m.candidate_type,
                MarketSignalCandidateReadonly15m.candidate_direction,
            )
        ).all()
        latest_candidate_time = None
        total_rows = 0
        status_counts = {status: 0 for status in CLASSIFIER_STATUSES}
        type_counts: dict[str, int] = {}
        direction_counts: dict[str, int] = {}
        for classifier_status, candidate_type, candidate_direction, count, latest_time in rows:
            total_rows += count
            status_counts[classifier_status] += count
            type_counts[candidate_type] = type_counts.get(candidate_type, 0) + count
            direction_counts[candidate_direction] = direction_counts.get(candidate_direction, 0) + count
            if latest_time is not None and (latest_candidate_time is None or latest_time > latest_candidate_time):
                latest_candidate_time = latest_time
        return {
            "latest_candidate_time": latest_candidate_time,
            "total_rows": total_rows,
            "classifier_ready_count": status_counts["CLASSIFIER_READY"],
            "classifier_partial_count": status_counts["CLASSIFIER_PARTIAL"],
            "classifier_blocked_count": status_counts["CLASSIFIER_BLOCKED"],
            "candidate_type_counts": [
                {"type": candidate_type, "count": count}
                for candidate_type, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "direction_counts": [
                {"direction": direction, "count": count}
                for direction, count in sorted(direction_counts.items())
            ],
        }

    def list_candidates(
        self,
        candidate_type: str | None = None,
        classifier_status: str | None = None,
        limit: int = 100,
    ) -> list[MarketSignalCandidateReadonly15m]:
        query = select(MarketSignalCandidateReadonly15m).order_by(
            desc(MarketSignalCandidateReadonly15m.window_close_time),
            MarketSignalCandidateReadonly15m.symbol,
        )
        if candidate_type:
            query = query.where(MarketSignalCandidateReadonly15m.candidate_type == candidate_type)
        if classifier_status:
            query = query.where(MarketSignalCandidateReadonly15m.classifier_status == classifier_status)
        return list(self.db.scalars(query.limit(min(max(limit, 1), 500))).all())

    def _classify(
        self,
        label: MarketPsychologyLabel15m,
        context: MarketFeatureContext15m1h | None,
        now: datetime,
    ) -> dict[str, Any]:
        labels = _label_set(label)
        evidence = self._evidence(label, context, labels)

        if label.label_status == "LABEL_BLOCKED" or context is None or context.context_status == "CONTEXT_BLOCKED":
            return self._payload(
                label=label,
                candidate_type="DATA_BLOCKED",
                candidate_direction="BLOCKED_CONTEXT",
                classifier_status="CLASSIFIER_BLOCKED",
                confidence_level="LOW",
                confidence_score=Decimal("0.10"),
                evidence=evidence,
                block_reason=label.block_reason or "blocked psychology/context evidence",
                now=now,
            )

        candidate_type, direction, reason = self._candidate_type(labels, context)
        classifier_status = "CLASSIFIER_PARTIAL" if label.label_status == "LABEL_PARTIAL" else "CLASSIFIER_READY"
        confidence_score = self._confidence_score(candidate_type, label, context)
        confidence_level = self._confidence_level(confidence_score)
        block_reason = reason

        if classifier_status == "CLASSIFIER_PARTIAL":
            confidence_score = min(confidence_score, Decimal("0.69"))
            confidence_level = "MEDIUM" if confidence_score >= Decimal("0.45") else "LOW"
            block_reason = "partial input evidence; " + reason

        return self._payload(
            label=label,
            candidate_type=candidate_type,
            candidate_direction=direction,
            classifier_status=classifier_status,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            evidence=evidence,
            block_reason=block_reason,
            now=now,
        )

    def _candidate_type(self, labels: set[str], context: MarketFeatureContext15m1h) -> tuple[str, str, str]:
        bullish = self._bullish_15m(context)
        bearish = self._bearish_15m(context)
        rich_valid = self._rich_valid(context)
        one_hour_bullish = _gt(context.price_return_pct_1h, self.config.positive_return_threshold)
        one_hour_bearish = _lt(context.price_return_pct_1h, self.config.negative_return_threshold)
        one_hour_strong_bearish = _lt(context.price_return_pct_1h, -self.config.strong_context_threshold)
        one_hour_strong_bullish = _gt(context.price_return_pct_1h, self.config.strong_context_threshold)
        spot_supporting = context.spot_support_status_15m == "SPOT_SUPPORTING"
        early_long_quality = evaluate_early_signal_quality(
            price_return_pct=context.price_return_pct_15m,
            close_position=context.close_position_15m,
            taker_buy_ratio=context.kline_taker_buy_ratio_15m,
            oi_change_pct=context.oi_change_pct_15m,
            spot_support_status=context.spot_support_status_15m,
            one_hour_return_pct=context.price_return_pct_1h,
            direction_hint="LONG",
        )
        early_short_quality = evaluate_early_signal_quality(
            price_return_pct=context.price_return_pct_15m,
            close_position=context.close_position_15m,
            taker_buy_ratio=context.kline_taker_buy_ratio_15m,
            oi_change_pct=context.oi_change_pct_15m,
            spot_support_status=context.spot_support_status_15m,
            one_hour_return_pct=context.price_return_pct_1h,
            direction_hint="SHORT",
        )

        if labels & TRAP_LABELS:
            return "TRAP_RISK_CONTEXT_READONLY", "MIXED_CONTEXT", "trap risk label is present; kept as context only"

        if labels & SQUEEZE_LABELS and not spot_supporting:
            return (
                "SQUEEZE_RISK_CONTEXT_READONLY",
                "MIXED_CONTEXT",
                "squeeze/unwind label is present without strong spot support",
            )

        if bullish and one_hour_bullish and rich_valid and (labels & BULLISH_LABELS):
            return "MID_LONG_CONTEXT_READONLY", "BULLISH_CONTEXT", "15m and 1h context both lean bullish"

        if bearish and one_hour_bearish and rich_valid and (labels & BEARISH_LABELS):
            return "MID_SHORT_CONTEXT_READONLY", "BEARISH_CONTEXT", "15m and 1h context both lean bearish"

        if (
            labels & BULLISH_LABELS
            and bullish
            and (_positive(context.oi_change_pct_15m) or spot_supporting)
            and not one_hour_strong_bearish
            and early_long_quality.is_early_long
            and early_long_quality.quality_score >= 4
        ):
            return (
                "EARLY_LONG_CANDIDATE_READONLY",
                "BULLISH_CONTEXT",
                f"normalized early long quality {early_long_quality.quality_score}/10: "
                + "; ".join(early_long_quality.reasons),
            )

        if (
            labels & BEARISH_LABELS
            and bearish
            and (_positive(context.oi_change_pct_15m) or "LONG_TRAP_RISK" in labels)
            and not one_hour_strong_bullish
            and early_short_quality.is_early_short
            and early_short_quality.quality_score >= 4
        ):
            return (
                "EARLY_SHORT_CANDIDATE_READONLY",
                "BEARISH_CONTEXT",
                f"normalized early short quality {early_short_quality.quality_score}/10: "
                + "; ".join(early_short_quality.reasons),
            )

        return "NO_SIGNAL_CONTEXT", "MIXED_CONTEXT", "context evidence is mixed or below readonly classifier thresholds"

    def _bullish_15m(self, context: MarketFeatureContext15m1h) -> bool:
        return (
            _gt(context.price_return_pct_15m, self.config.positive_return_threshold)
            and _gt(context.close_position_15m, self.config.high_close_position)
            and _gt(context.kline_taker_buy_ratio_15m, self.config.taker_support_threshold)
        )

    def _bearish_15m(self, context: MarketFeatureContext15m1h) -> bool:
        sell_ratio = Decimal("1") - context.kline_taker_buy_ratio_15m if context.kline_taker_buy_ratio_15m is not None else None
        return (
            _lt(context.price_return_pct_15m, self.config.negative_return_threshold)
            and _lt(context.close_position_15m, self.config.low_close_position)
            and _gt(sell_ratio, self.config.taker_support_threshold)
        )

    def _rich_valid(self, context: MarketFeatureContext15m1h) -> bool:
        return all(
            value is not None
            for value in (
                context.oi_change_pct_15m,
                context.global_long_short_ratio_15m,
                context.top_trader_position_ratio_15m,
            )
        )

    def _confidence_score(
        self,
        candidate_type: str,
        label: MarketPsychologyLabel15m,
        context: MarketFeatureContext15m1h,
    ) -> Decimal:
        if candidate_type in {"NO_SIGNAL_CONTEXT", "DATA_BLOCKED"}:
            return Decimal("0.20")
        score = Decimal("0.35")
        if context.context_status == "CONTEXT_READY":
            score += Decimal("0.15")
        if label.confidence_level == "MEDIUM":
            score += Decimal("0.10")
        if context.feature_15m_status == "FEATURE_READY":
            score += Decimal("0.10")
        if context.feature_1h_status == "FEATURE_READY":
            score += Decimal("0.10")
        if context.spot_support_status_15m == "SPOT_SUPPORTING":
            score += Decimal("0.10")
        return min(score, Decimal("0.95"))

    def _confidence_level(self, score: Decimal) -> str:
        if score >= Decimal("0.70"):
            return "HIGH"
        if score >= Decimal("0.45"):
            return "MEDIUM"
        return "LOW"

    def _payload(
        self,
        label: MarketPsychologyLabel15m,
        candidate_type: str,
        candidate_direction: str,
        classifier_status: str,
        confidence_level: str,
        confidence_score: Decimal,
        evidence: dict[str, Any],
        block_reason: str | None,
        now: datetime,
    ) -> dict[str, Any]:
        return {
            "symbol": label.symbol,
            "window_open_time": label.window_open_time,
            "window_close_time": label.window_close_time,
            "classifier_status": classifier_status,
            "candidate_type": candidate_type,
            "candidate_direction": candidate_direction,
            "confidence_level": confidence_level,
            "confidence_score": confidence_score,
            "evidence": json_safe(evidence),
            "block_reason": block_reason,
            "not_entry_signal": True,
            "created_at": now,
            "updated_at": now,
        }

    def _evidence(
        self,
        label: MarketPsychologyLabel15m,
        context: MarketFeatureContext15m1h | None,
        labels: set[str],
    ) -> dict[str, Any]:
        label_evidence = label.evidence or {}
        early_long_quality = None
        early_short_quality = None
        if context is not None:
            early_long_quality = evaluate_early_signal_quality(
                price_return_pct=context.price_return_pct_15m,
                close_position=context.close_position_15m,
                taker_buy_ratio=context.kline_taker_buy_ratio_15m,
                oi_change_pct=context.oi_change_pct_15m,
                spot_support_status=context.spot_support_status_15m,
                one_hour_return_pct=context.price_return_pct_1h,
                direction_hint="LONG",
            )
            early_short_quality = evaluate_early_signal_quality(
                price_return_pct=context.price_return_pct_15m,
                close_position=context.close_position_15m,
                taker_buy_ratio=context.kline_taker_buy_ratio_15m,
                oi_change_pct=context.oi_change_pct_15m,
                spot_support_status=context.spot_support_status_15m,
                one_hour_return_pct=context.price_return_pct_1h,
                direction_hint="SHORT",
            )
        return {
            "source": "market_psychology_labels_15m + market_feature_context_15m_1h",
            "not_entry_signal": True,
            "readonly_reason": "context classification only; no timing, order, target, risk, or allocation instruction",
            "supporting_psychology_labels": sorted(labels),
            "psychology_label_status": label.label_status,
            "psychology_confidence_level": label.confidence_level,
            "context_status": context.context_status if context else None,
            "feature_15m_status": context.feature_15m_status if context else label_evidence.get("feature_15m_status"),
            "feature_1h_status": context.feature_1h_status if context else label_evidence.get("feature_1h_status"),
            "price_return_pct_15m": _context_or_evidence(context, label_evidence, "price_return_pct_15m"),
            "close_position_15m": _context_or_evidence(context, label_evidence, "close_position_15m"),
            "kline_taker_buy_ratio_15m": _context_or_evidence(context, label_evidence, "kline_taker_buy_ratio_15m"),
            "kline_taker_sell_ratio_15m": label_evidence.get("kline_taker_sell_ratio_15m"),
            "oi_change_pct_15m": _context_or_evidence(context, label_evidence, "oi_change_pct_15m"),
            "price_return_pct_1h": _context_or_evidence(context, label_evidence, "price_return_pct_1h"),
            "global_long_short_ratio_15m": _context_or_evidence(context, label_evidence, "global_long_short_ratio_15m"),
            "top_trader_position_ratio_15m": _context_or_evidence(
                context,
                label_evidence,
                "top_trader_position_ratio_15m",
            ),
            "funding_status_15m": _context_or_evidence(context, label_evidence, "funding_status_15m"),
            "spot_support_status_15m": _context_or_evidence(context, label_evidence, "spot_support_status_15m"),
            "spot_futures_volume_ratio_15m": _context_or_evidence(
                context,
                label_evidence,
                "spot_futures_volume_ratio_15m",
            ),
            "futures_taker_buy_ratio_15m": _context_or_evidence(
                context,
                label_evidence,
                "futures_taker_buy_ratio_15m",
            ),
            "spot_taker_buy_ratio_15m": _context_or_evidence(context, label_evidence, "spot_taker_buy_ratio_15m"),
            "spot_missing_flag_15m": _context_or_evidence(context, label_evidence, "spot_missing_flag_15m"),
            "futures_led_score_15m": _context_or_evidence(context, label_evidence, "futures_led_score_15m"),
            "spot_support_score_15m": _context_or_evidence(context, label_evidence, "spot_support_score_15m"),
            "early_signal_logic_version": early_long_quality.logic_version if early_long_quality else None,
            "early_long_quality_score": early_long_quality.quality_score if early_long_quality else None,
            "early_long_quality_bucket": early_long_quality.quality_bucket if early_long_quality else None,
            "early_long_quality_reasons": early_long_quality.reasons if early_long_quality else [],
            "early_short_quality_score": early_short_quality.quality_score if early_short_quality else None,
            "early_short_quality_bucket": early_short_quality.quality_bucket if early_short_quality else None,
            "early_short_quality_reasons": early_short_quality.reasons if early_short_quality else [],
            "entry_market": "futures",
            "entry_price_source": "futures_klines_15m.close",
            "spot_usage": "filter/evidence_only",
        }

    def _psychology_rows(self, symbol: str, limit_windows: int | None) -> list[MarketPsychologyLabel15m]:
        query = (
            select(MarketPsychologyLabel15m)
            .where(MarketPsychologyLabel15m.symbol == symbol)
            .order_by(desc(MarketPsychologyLabel15m.window_open_time))
        )
        if limit_windows:
            query = query.limit(limit_windows)
        rows = list(self.db.scalars(query).all())
        rows.reverse()
        return rows

    def _context_row(self, label: MarketPsychologyLabel15m) -> MarketFeatureContext15m1h | None:
        return self.db.scalar(
            select(MarketFeatureContext15m1h).where(
                MarketFeatureContext15m1h.symbol == label.symbol,
                MarketFeatureContext15m1h.feature_15m_window_open_time == label.window_open_time,
            )
        )

    def _upsert(self, payload: dict[str, Any], dry_run: bool) -> str:
        row = self.db.scalar(
            select(MarketSignalCandidateReadonly15m).where(
                MarketSignalCandidateReadonly15m.symbol == payload["symbol"],
                MarketSignalCandidateReadonly15m.window_open_time == payload["window_open_time"],
            )
        )
        if dry_run:
            return "updated" if row else "inserted"
        if row:
            for key, value in payload.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        self.db.add(MarketSignalCandidateReadonly15m(**payload))
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


def _label_set(label: MarketPsychologyLabel15m) -> set[str]:
    labels = {label.primary_label}
    if label.secondary_labels:
        labels.update(str(item) for item in label.secondary_labels)
    return labels


def _context_or_evidence(
    context: MarketFeatureContext15m1h | None,
    evidence: dict[str, Any],
    key: str,
) -> Any:
    if context is None:
        return evidence.get(key)
    if key == "price_return_pct_15m":
        return context.price_return_pct_15m
    if key == "close_position_15m":
        return context.close_position_15m
    if key == "kline_taker_buy_ratio_15m":
        return context.kline_taker_buy_ratio_15m
    if key == "oi_change_pct_15m":
        return context.oi_change_pct_15m
    if key == "price_return_pct_1h":
        return context.price_return_pct_1h
    if key == "global_long_short_ratio_15m":
        return context.global_long_short_ratio_15m
    if key == "top_trader_position_ratio_15m":
        return context.top_trader_position_ratio_15m
    if key == "funding_status_15m":
        return context.funding_status_15m
    if key == "spot_support_status_15m":
        return context.spot_support_status_15m
    if key == "spot_futures_volume_ratio_15m":
        return context.spot_futures_volume_ratio_15m
    if key == "futures_taker_buy_ratio_15m":
        return context.futures_taker_buy_ratio_15m
    if key == "spot_taker_buy_ratio_15m":
        return context.spot_taker_buy_ratio_15m
    if key == "spot_missing_flag_15m":
        return context.spot_missing_flag_15m
    if key == "futures_led_score_15m":
        return context.futures_led_score_15m
    if key == "spot_support_score_15m":
        return context.spot_support_score_15m
    return evidence.get(key)


def _positive(value: Decimal | None) -> bool:
    return value is not None and value > 0


def _gt(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value > threshold


def _lt(value: Decimal | None, threshold: Decimal) -> bool:
    return value is not None and value < threshold
