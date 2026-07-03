from dataclasses import dataclass
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from app.models.market import FuturesKline15m, FuturesKline1h, MarketCandidateOutcome15m, MarketSignalCandidateReadonly15m, MarketlabActiveUniverse
from app.services.utils import json_safe

SIGNAL_CANDIDATE_TYPES = {"EARLY_LONG_CANDIDATE_READONLY", "EARLY_SHORT_CANDIDATE_READONLY"}
WATCHLIST_CONTEXT_TYPES = {"MID_SHORT_CONTEXT_READONLY", "MID_LONG_CONTEXT_READONLY"}
RADAR_ONLY_TYPES = {"EARLY_LONG_CANDIDATE_READONLY", "EARLY_SHORT_CANDIDATE_READONLY"}
RISK_CONTEXT_TYPES = {"SQUEEZE_RISK_CONTEXT_READONLY", "TRAP_RISK_CONTEXT_READONLY"}
BLOCKED_TYPES = {"DATA_BLOCKED"}
BASELINE_CONTEXT_TYPES = {"NO_SIGNAL_CONTEXT"}


@dataclass(frozen=True)
class ScannerTier:
    tier: str
    reason: str
    warning: str | None


def scanner_tier_for(candidate_type: str, classifier_status: str) -> ScannerTier:
    if classifier_status == "CLASSIFIER_BLOCKED" or candidate_type in BLOCKED_TYPES:
        return ScannerTier(
            tier="BLOCKED",
            reason="candidate/context row is blocked by upstream data readiness",
            warning="blocked row; not usable for live radar",
        )
    if candidate_type == "MID_SHORT_CONTEXT_READONLY":
        return ScannerTier(
            tier="WATCHLIST_CONTEXT",
            reason="mid short context from read-only classifier",
            warning=None,
        )
    if candidate_type == "MID_LONG_CONTEXT_READONLY":
        return ScannerTier(
            tier="WATCHLIST_CONTEXT",
            reason="mid long context from read-only classifier",
            warning="behavior review marks mid long as noisy; monitor only",
        )
    if candidate_type in RADAR_ONLY_TYPES:
        return ScannerTier(
            tier="RADAR_ONLY",
            reason="early read-only context",
            warning="small sample category; radar only",
        )
    if candidate_type in RISK_CONTEXT_TYPES:
        return ScannerTier(
            tier="RISK_CONTEXT",
            reason="risk/read-only context category",
            warning="risk context; not a directional instruction",
        )
    if candidate_type in BASELINE_CONTEXT_TYPES:
        return ScannerTier(
            tier="BASELINE_CONTEXT",
            reason="baseline/control context",
            warning="control group; no active scanner context",
        )
    return ScannerTier(
        tier="RADAR_ONLY",
        reason="unmapped read-only candidate type",
        warning="unmapped type; monitor only",
    )


class LiveCandidateScannerService:
    def __init__(self, db: Session, signal_factory_artifact_dir: Path | None = None) -> None:
        self.db = db
        self.signal_factory_artifact_dir = signal_factory_artifact_dir

    def list_live(
        self,
        tier: str | None = None,
        candidate_type: str | None = None,
        limit: int = 100,
        include_blocked: bool = False,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        rows = self._latest_candidate_rows(
            include_blocked=include_blocked,
            include_inactive=include_inactive,
        )
        raw_items: list[dict[str, Any]] = []
        normalized_tier = tier.upper() if tier else None
        normalized_type = candidate_type.upper() if candidate_type else None
        for row, latest_actual_row, universe in rows:
            raw_items.append(
                self._candidate_payload(
                    row,
                    latest_actual_row,
                    universe,
                    include_blocked=include_blocked,
                    include_inactive=include_inactive,
                )
            )
        raw_items.extend(self._signal_factory_signal_items(include_inactive=include_inactive))

        items: list[dict[str, Any]] = []
        for item in sorted(_dedupe_by_symbol(raw_items), key=_item_sort_key, reverse=True):
            if normalized_type and item["candidate_type"] != normalized_type:
                continue
            if normalized_tier and item["scanner_tier"] != normalized_tier:
                continue
            if not include_blocked and item["scanner_tier"] == "BLOCKED":
                continue
            items.append(item)
            if len(items) >= min(max(limit, 1), 500):
                break
        return items

    def _signal_factory_signal_items(self, include_inactive: bool) -> list[dict[str, Any]]:
        artifact_dir = self.signal_factory_artifact_dir
        if artifact_dir is None:
            return []
        path = artifact_dir / "candidates.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        universe_by_symbol = self._universe_by_symbol(include_inactive=include_inactive)
        items: list[dict[str, Any]] = []
        for candidate in payload.get("items", []):
            if candidate.get("candidate_status") != "SIGNAL_CANDIDATE":
                continue
            if candidate.get("timeframe") != "15m":
                continue
            symbol = str(candidate.get("symbol") or "").upper()
            if not symbol:
                continue
            universe = universe_by_symbol.get(symbol)
            if not include_inactive and not (universe and universe.is_active):
                continue
            item = self._signal_factory_payload(candidate, universe, include_inactive=include_inactive)
            if item is not None:
                items.append(item)
        return items

    def _signal_factory_payload(
        self,
        candidate: dict[str, Any],
        universe: MarketlabActiveUniverse | None,
        include_inactive: bool,
    ) -> dict[str, Any] | None:
        symbol = str(candidate.get("symbol") or "").upper()
        window_open = _parse_dt(candidate.get("window_start"))
        window_close = _parse_dt(candidate.get("window_end"))
        if window_open is None or window_close is None:
            return None
        evidence = candidate.get("evidence") or {}
        direction = candidate.get("direction") or "MIXED_CONTEXT"
        entry_candle = self.db.scalar(
            select(FuturesKline15m).where(
                FuturesKline15m.symbol == symbol,
                FuturesKline15m.open_time == window_open,
                FuturesKline15m.aggregation_status == "AGG_READY",
            )
        )
        atr = self._atr_1h(symbol, window_close)
        entry = Decimal(str(entry_candle.close)) if entry_candle is not None and entry_candle.close is not None else None
        risk = Decimal(str(atr)) if atr is not None and atr > 0 else None
        rr = Decimal("1.5")
        stop = None
        target = None
        if entry is not None and risk is not None:
            if direction == "BULLISH_CONTEXT":
                stop = entry - risk
                target = entry + risk * rr
            elif direction == "BEARISH_CONTEXT":
                stop = entry + risk
                target = entry - risk * rr
        is_active = bool(universe and universe.is_active)
        inactive_warning = None if is_active else "Symbol is not in active universe"
        warning_reason = inactive_warning or "read-only signal candidate; not an execution instruction"
        return json_safe(
            {
                "symbol": symbol,
                "is_active": is_active,
                "collection_tier": universe.collection_tier if universe else "NOT_ACTIVE",
                "universe_rank": universe.rank if universe else None,
                "inactive_warning": inactive_warning if include_inactive else None,
                "scanner_visibility_reason": "signal factory final read-only candidate",
                "latest_actual_status": candidate.get("candidate_status"),
                "latest_actual_observation_timestamp": window_close,
                "using_fallback_usable_row": False,
                "fallback_reason": None,
                "observation_time": window_close,
                "window_open_time": window_open,
                "window_close_time": window_close,
                "candidate_type": _factory_candidate_type(candidate.get("setup_type")),
                "candidate_direction": direction,
                "classifier_status": candidate.get("candidate_status"),
                "confidence": candidate.get("confidence") or "MEDIUM",
                "confidence_score": None,
                "scanner_tier": "SIGNAL_CANDIDATE",
                "tier_reason": candidate.get("reason") or "signal factory final read-only candidate",
                "warning_reason": warning_reason,
                "evidence_summary": _factory_evidence_summary(candidate),
                "signal_status": "SIGNAL_CANDIDATE",
                "signal_reason": candidate.get("reason") or evidence.get("early_signal_logic_version") or "signal_factory_v1",
                "entry_market": "futures",
                "entry_price_source": "futures_klines_15m.close",
                "entry_price": entry,
                "stop_loss_reference": stop,
                "take_profit_reference": target,
                "rr": rr,
                "timeout_minutes": 60,
                "atr_reference_timeframe": candidate.get("atr_reference_timeframe") or "1h",
                "atr_reference_value": atr,
                "quality_score": evidence.get("early_quality_score"),
                "quality_bucket": evidence.get("early_quality_bucket"),
                "quality_reasons": evidence.get("early_quality_reasons") or [],
                "position_lock_mode": "LOCK_BY_SYMBOL",
                "not_execution_instruction": True,
                "latest_outcome_status": None,
                "latest_outcome_update": None,
                "not_entry_signal": True,
            }
        )

    def _universe_by_symbol(self, include_inactive: bool) -> dict[str, MarketlabActiveUniverse]:
        query = select(MarketlabActiveUniverse)
        if not include_inactive:
            query = query.where(MarketlabActiveUniverse.is_active.is_(True))
        return {row.symbol: row for row in self.db.scalars(query).all()}

    def _latest_candidate_rows(
        self,
        include_blocked: bool,
        include_inactive: bool = False,
    ) -> list[
        tuple[
            MarketSignalCandidateReadonly15m,
            MarketSignalCandidateReadonly15m,
            MarketlabActiveUniverse | None,
        ]
    ]:
        latest_actual_ranked = (
            select(
                MarketSignalCandidateReadonly15m.id.label("id"),
                MarketSignalCandidateReadonly15m.symbol.label("symbol"),
                func.row_number()
                .over(
                    partition_by=MarketSignalCandidateReadonly15m.symbol,
                    order_by=(
                        desc(MarketSignalCandidateReadonly15m.window_close_time),
                        desc(MarketSignalCandidateReadonly15m.window_open_time),
                        desc(MarketSignalCandidateReadonly15m.id),
                    ),
                )
                .label("row_rank"),
            )
            .subquery()
        )
        latest_usable_ranked = (
            select(
                MarketSignalCandidateReadonly15m.id.label("id"),
                MarketSignalCandidateReadonly15m.symbol.label("symbol"),
                func.row_number()
                .over(
                    partition_by=MarketSignalCandidateReadonly15m.symbol,
                    order_by=(
                        desc(MarketSignalCandidateReadonly15m.window_close_time),
                        desc(MarketSignalCandidateReadonly15m.window_open_time),
                        desc(MarketSignalCandidateReadonly15m.id),
                    ),
                )
                .label("row_rank"),
            )
            .where(_usable_candidate_filter(MarketSignalCandidateReadonly15m))
            .subquery()
        )
        latest_actual = aliased(MarketSignalCandidateReadonly15m)
        latest_usable = aliased(MarketSignalCandidateReadonly15m)
        query = (
            select(latest_actual, latest_usable, MarketlabActiveUniverse)
            .join(latest_actual_ranked, latest_actual.id == latest_actual_ranked.c.id)
            .join(
                MarketlabActiveUniverse,
                latest_actual.symbol == MarketlabActiveUniverse.symbol,
                isouter=include_inactive,
            )
            .join(
                latest_usable_ranked,
                (latest_usable_ranked.c.symbol == latest_actual.symbol)
                & (latest_usable_ranked.c.row_rank == 1),
                isouter=True,
            )
            .join(latest_usable, latest_usable.id == latest_usable_ranked.c.id, isouter=True)
            .where(latest_actual_ranked.c.row_rank == 1)
        )
        if not include_inactive:
            query = query.where(MarketlabActiveUniverse.is_active.is_(True))
        records = []
        for latest_actual_row, latest_usable_row, universe in self.db.execute(query).all():
            selected = latest_actual_row if include_blocked else latest_usable_row
            if selected is None:
                continue
            records.append((selected, latest_actual_row, universe))
        return sorted(
            records,
            key=lambda item: (item[0].window_close_time, item[0].window_open_time, item[0].symbol),
            reverse=True,
        )

    def _candidate_payload(
        self,
        candidate: MarketSignalCandidateReadonly15m,
        latest_actual_candidate: MarketSignalCandidateReadonly15m,
        universe: MarketlabActiveUniverse | None,
        include_blocked: bool,
        include_inactive: bool,
    ) -> dict[str, Any]:
        tier = scanner_tier_for(candidate.candidate_type, candidate.classifier_status)
        outcome = self._matching_outcome(candidate)
        signal_plan = self._signal_candidate_plan(candidate)
        if signal_plan["signal_status"] == "SIGNAL_CANDIDATE":
            tier = ScannerTier(
                tier="SIGNAL_CANDIDATE",
                reason="final read-only signal candidate with futures entry reference and risk references",
                warning="read-only signal candidate; not an execution instruction",
            )
        is_active = bool(universe and universe.is_active)
        inactive_warning = None if is_active else "Symbol is not in active universe"
        warning_reason = tier.warning or "No scanner warning"
        if inactive_warning:
            warning_reason = inactive_warning
        using_fallback = candidate.id != latest_actual_candidate.id
        fallback_reason = None
        if using_fallback:
            fallback_reason = "latest cycle is blocked; showing latest usable non-blocked scanner row"
        return json_safe(
            {
                "symbol": candidate.symbol,
                "is_active": is_active,
                "collection_tier": universe.collection_tier if universe else "NOT_ACTIVE",
                "universe_rank": universe.rank if universe else None,
                "inactive_warning": inactive_warning if include_inactive else None,
                "scanner_visibility_reason": _visibility_reason(
                    is_active=is_active,
                    scanner_tier=tier.tier,
                    include_blocked=include_blocked,
                    include_inactive=include_inactive,
                    using_fallback_usable_row=using_fallback,
                ),
                "latest_actual_status": latest_actual_candidate.classifier_status,
                "latest_actual_observation_timestamp": latest_actual_candidate.window_close_time,
                "using_fallback_usable_row": using_fallback,
                "fallback_reason": fallback_reason,
                "observation_time": candidate.window_close_time,
                "window_open_time": candidate.window_open_time,
                "window_close_time": candidate.window_close_time,
                "candidate_type": candidate.candidate_type,
                "candidate_direction": candidate.candidate_direction,
                "classifier_status": candidate.classifier_status,
                "confidence": candidate.confidence_level,
                "confidence_score": candidate.confidence_score,
                "scanner_tier": tier.tier,
                "tier_reason": tier.reason,
                "warning_reason": warning_reason,
                "evidence_summary": _evidence_summary(candidate.evidence or {}),
                "signal_status": signal_plan["signal_status"],
                "signal_reason": signal_plan["signal_reason"],
                "entry_market": signal_plan["entry_market"],
                "entry_price_source": signal_plan["entry_price_source"],
                "entry_price": signal_plan["entry_price"],
                "stop_loss_reference": signal_plan["stop_loss_reference"],
                "take_profit_reference": signal_plan["take_profit_reference"],
                "rr": signal_plan["rr"],
                "timeout_minutes": signal_plan["timeout_minutes"],
                "atr_reference_timeframe": signal_plan["atr_reference_timeframe"],
                "atr_reference_value": signal_plan["atr_reference_value"],
                "quality_score": signal_plan["quality_score"],
                "quality_bucket": signal_plan["quality_bucket"],
                "quality_reasons": signal_plan["quality_reasons"],
                "position_lock_mode": "LOCK_BY_SYMBOL",
                "not_execution_instruction": True,
                "latest_outcome_status": outcome.outcome_status if outcome else None,
                "latest_outcome_update": outcome.updated_at if outcome else None,
                "not_entry_signal": True,
            }
        )

    def _signal_candidate_plan(self, candidate: MarketSignalCandidateReadonly15m) -> dict[str, Any]:
        empty = {
            "signal_status": "RADAR_OR_CONTEXT_ONLY",
            "signal_reason": "row is not final signal candidate",
            "entry_market": "futures",
            "entry_price_source": "futures_klines_15m.close",
            "entry_price": None,
            "stop_loss_reference": None,
            "take_profit_reference": None,
            "rr": None,
            "timeout_minutes": None,
            "atr_reference_timeframe": "1h",
            "atr_reference_value": None,
            "quality_score": None,
            "quality_bucket": None,
            "quality_reasons": [],
        }
        if candidate.candidate_type not in SIGNAL_CANDIDATE_TYPES:
            return empty
        evidence = candidate.evidence or {}
        quality_score = _early_quality_score(candidate)
        quality_bucket = _early_quality_bucket(candidate)
        quality_reasons = _early_quality_reasons(candidate)
        if quality_score is None or quality_score < 6:
            return {
                **empty,
                "signal_status": "CANDIDATE_NEEDS_QUALITY",
                "signal_reason": "early candidate quality score is below final signal threshold",
                "quality_score": quality_score,
                "quality_bucket": quality_bucket,
                "quality_reasons": quality_reasons,
            }
        entry_candle = self.db.scalar(
            select(FuturesKline15m).where(
                FuturesKline15m.symbol == candidate.symbol,
                FuturesKline15m.open_time == candidate.window_open_time,
                FuturesKline15m.aggregation_status == "AGG_READY",
            )
        )
        if entry_candle is None or entry_candle.close is None:
            return {
                **empty,
                "signal_status": "CANDIDATE_MISSING_ENTRY_REFERENCE",
                "signal_reason": "missing futures 15m entry close",
                "quality_score": quality_score,
                "quality_bucket": quality_bucket,
                "quality_reasons": quality_reasons,
            }
        atr = self._atr_1h(candidate.symbol, candidate.window_close_time)
        if atr is None or atr <= 0:
            return {
                **empty,
                "signal_status": "CANDIDATE_MISSING_ATR_REFERENCE",
                "signal_reason": "missing closed 1h ATR reference",
                "entry_price": entry_candle.close,
                "quality_score": quality_score,
                "quality_bucket": quality_bucket,
                "quality_reasons": quality_reasons,
            }
        entry = Decimal(str(entry_candle.close))
        risk = Decimal(str(atr))
        rr = Decimal("1.5")
        if candidate.candidate_direction == "BULLISH_CONTEXT":
            stop = entry - risk
            target = entry + risk * rr
        elif candidate.candidate_direction == "BEARISH_CONTEXT":
            stop = entry + risk
            target = entry - risk * rr
        else:
            return {
                **empty,
                "signal_status": "CANDIDATE_UNSUPPORTED_DIRECTION",
                "signal_reason": "candidate direction is not bullish/bearish",
                "entry_price": entry,
                "atr_reference_value": atr,
                "quality_score": quality_score,
                "quality_bucket": quality_bucket,
                "quality_reasons": quality_reasons,
            }
        return {
            "signal_status": "SIGNAL_CANDIDATE",
            "signal_reason": evidence.get("early_signal_logic_version") or "normalized_impulse_early_v1",
            "entry_market": "futures",
            "entry_price_source": "futures_klines_15m.close",
            "entry_price": entry,
            "stop_loss_reference": stop,
            "take_profit_reference": target,
            "rr": rr,
            "timeout_minutes": 60,
            "atr_reference_timeframe": "1h",
            "atr_reference_value": atr,
            "quality_score": quality_score,
            "quality_bucket": quality_bucket,
            "quality_reasons": quality_reasons,
        }

    def _atr_1h(self, symbol: str, signal_close_time: Any, period: int = 14) -> Decimal | None:
        rows = list(
            self.db.scalars(
                select(FuturesKline1h)
                .where(
                    FuturesKline1h.symbol == symbol,
                    FuturesKline1h.close_time <= signal_close_time,
                    FuturesKline1h.aggregation_status == "AGG_READY",
                )
                .order_by(desc(FuturesKline1h.close_time))
                .limit(period + 1)
            ).all()
        )
        rows.reverse()
        if len(rows) < period + 1:
            return None
        ranges: list[Decimal] = []
        for index in range(1, len(rows)):
            candle = rows[index]
            previous = rows[index - 1]
            if candle.high is None or candle.low is None or previous.close is None:
                return None
            ranges.append(
                max(
                    Decimal(str(candle.high)) - Decimal(str(candle.low)),
                    abs(Decimal(str(candle.high)) - Decimal(str(previous.close))),
                    abs(Decimal(str(candle.low)) - Decimal(str(previous.close))),
                )
            )
        return sum(ranges, Decimal("0")) / Decimal(period)

    def _matching_outcome(self, candidate: MarketSignalCandidateReadonly15m) -> MarketCandidateOutcome15m | None:
        return self.db.scalar(
            select(MarketCandidateOutcome15m)
            .where(
                MarketCandidateOutcome15m.symbol == candidate.symbol,
                MarketCandidateOutcome15m.candidate_window_open_time == candidate.window_open_time,
            )
            .limit(1)
        )


def _evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "supporting_psychology_labels",
        "psychology_label_status",
        "context_status",
        "feature_15m_status",
        "feature_1h_status",
        "price_return_pct_15m",
        "price_return",
        "close_position_15m",
        "close_position_in_range",
        "oi_change_pct_15m",
        "oi_change_pct",
        "volume_ratio_vs_lookback",
        "range_ratio_vs_atr",
        "atr_extension_normalized",
        "price_atr_multiple",
        "kline_taker_buy_ratio",
        "kline_taker_sell_ratio",
        "kline_taker_buy_base",
        "kline_taker_sell_base",
        "price_return_pct_1h",
        "one_hour_return_pct",
        "global_long_short_ratio_15m",
        "global_long_short_ratio",
        "top_trader_position_ratio_15m",
        "top_trader_position_ratio",
        "top_trader_account_ratio",
        "top_trader_account_ratio_15m",
        "rich_alignment_status",
        "funding_status_15m",
        "funding_rate",
        "funding_pressure",
        "funding_percentile_30d",
        "spot_support_status_15m",
        "spot_context",
        "futures_spread_pct",
        "spot_spread_pct",
        "core_score",
        "core_score_max",
        "core_reasons",
        "evidence_score",
        "evidence_confidence_tier",
        "evidence_data_completeness",
        "evidence_flags",
        "evidence_reasons",
        "execution_risk_status",
        "execution_risk_reasons",
        "early_signal_logic_version",
        "early_long_quality_score",
        "early_long_quality_bucket",
        "early_short_quality_score",
        "early_short_quality_bucket",
        "entry_market",
        "entry_price_source",
        "spot_usage",
    )
    return {
        key: _decimal_to_plain(evidence.get(key))
        for key in keys
        if key in evidence
    }


def _decimal_to_plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_decimal_to_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_decimal_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _decimal_to_plain(item) for key, item in value.items()}
    return value


def _early_quality_score(candidate: MarketSignalCandidateReadonly15m) -> int | None:
    evidence = candidate.evidence or {}
    if candidate.candidate_type == "EARLY_LONG_CANDIDATE_READONLY":
        return _int_or_none(evidence.get("early_long_quality_score") or evidence.get("early_quality_score"))
    if candidate.candidate_type == "EARLY_SHORT_CANDIDATE_READONLY":
        return _int_or_none(evidence.get("early_short_quality_score") or evidence.get("early_quality_score"))
    return None


def _early_quality_bucket(candidate: MarketSignalCandidateReadonly15m) -> str | None:
    evidence = candidate.evidence or {}
    if candidate.candidate_type == "EARLY_LONG_CANDIDATE_READONLY":
        return evidence.get("early_long_quality_bucket") or evidence.get("early_quality_bucket")
    if candidate.candidate_type == "EARLY_SHORT_CANDIDATE_READONLY":
        return evidence.get("early_short_quality_bucket") or evidence.get("early_quality_bucket")
    return None


def _early_quality_reasons(candidate: MarketSignalCandidateReadonly15m) -> list[Any]:
    evidence = candidate.evidence or {}
    if candidate.candidate_type == "EARLY_LONG_CANDIDATE_READONLY":
        return evidence.get("early_long_quality_reasons") or evidence.get("early_quality_reasons") or []
    if candidate.candidate_type == "EARLY_SHORT_CANDIDATE_READONLY":
        return evidence.get("early_short_quality_reasons") or evidence.get("early_quality_reasons") or []
    return []


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _usable_candidate_filter(model) -> Any:
    return ~or_(
        model.classifier_status == "CLASSIFIER_BLOCKED",
        model.candidate_type.in_(BLOCKED_TYPES),
    )


def _visibility_reason(
    is_active: bool,
    scanner_tier: str,
    include_blocked: bool,
    include_inactive: bool,
    using_fallback_usable_row: bool,
) -> str:
    if using_fallback_usable_row:
        return "active universe fallback to latest usable non-blocked scanner row"
    if not is_active and include_inactive:
        return "shown because include_inactive=true"
    if scanner_tier == "BLOCKED" and include_blocked:
        return "shown because include_blocked=true"
    return "active universe latest non-blocked scanner row"


def _dedupe_by_symbol(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for item in items:
        symbol = item.get("symbol")
        if not symbol:
            continue
        current = selected.get(symbol)
        if current is None or _item_priority(item) > _item_priority(current):
            selected[symbol] = item
            continue
        if _item_priority(item) == _item_priority(current) and _item_sort_key(item) > _item_sort_key(current):
            selected[symbol] = item
    return list(selected.values())


def _item_priority(item: dict[str, Any]) -> int:
    tier = item.get("scanner_tier")
    priorities = {
        "SIGNAL_CANDIDATE": 6,
        "WATCHLIST_CONTEXT": 5,
        "RADAR_ONLY": 4,
        "RISK_CONTEXT": 3,
        "BASELINE_CONTEXT": 2,
        "BLOCKED": 1,
    }
    return priorities.get(tier, 0)


def _item_sort_key(item: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(item.get("window_close_time") or item.get("observation_time") or ""),
        _item_priority(item),
        str(item.get("symbol") or ""),
    )


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _factory_candidate_type(setup_type: Any) -> str:
    mapping = {
        "EARLY_LONG": "EARLY_LONG_CANDIDATE_READONLY",
        "EARLY_SHORT": "EARLY_SHORT_CANDIDATE_READONLY",
        "MID_LONG": "MID_LONG_CONTEXT_READONLY",
        "MID_SHORT": "MID_SHORT_CONTEXT_READONLY",
        "SQUEEZE": "SQUEEZE_RISK_CONTEXT_READONLY",
        "TRAP_FADE": "TRAP_RISK_CONTEXT_READONLY",
        "NO_SETUP": "NO_SIGNAL_CONTEXT",
        "BLOCKED_DATA": "DATA_BLOCKED",
    }
    return mapping.get(str(setup_type or ""), str(setup_type or "NO_SIGNAL_CONTEXT"))


def _factory_evidence_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("evidence") or {}
    keys = (
        "anomalies",
        "price_return",
        "close_position_in_range",
        "volume_spike",
        "volume_ratio_vs_lookback",
        "range_ratio_vs_atr",
        "atr_extension_normalized",
        "price_atr_multiple",
        "kline_taker_buy_ratio",
        "kline_taker_sell_ratio",
        "kline_taker_buy_base",
        "kline_taker_sell_base",
        "oi_change_pct",
        "oi_zscore",
        "funding_percentile_30d",
        "funding_rate",
        "funding_pressure",
        "spot_context",
        "relative_strength",
        "one_hour_return_pct",
        "futures_led_flag",
        "spot_led_flag",
        "global_long_short_ratio",
        "top_trader_position_ratio",
        "top_trader_account_ratio",
        "rich_alignment_status",
        "futures_spread_pct",
        "spot_spread_pct",
        "core_score",
        "core_score_max",
        "core_reasons",
        "evidence_score",
        "evidence_confidence_tier",
        "evidence_data_completeness",
        "evidence_flags",
        "evidence_reasons",
        "execution_risk_status",
        "execution_risk_reasons",
        "feature_status",
        "status_reasons",
        "entry_market",
        "entry_price_source",
        "spot_usage",
        "early_signal_logic_version",
        "early_quality_score",
        "early_quality_bucket",
        "early_quality_reasons",
        "atr_extension",
    )
    summary = {
        key: _decimal_to_plain(evidence.get(key))
        for key in keys
        if key in evidence
    }
    summary["source"] = candidate.get("signal_factory_version") or "signal_factory_v1"
    summary["timeframe"] = candidate.get("timeframe")
    summary["setup_type"] = candidate.get("setup_type")
    summary["candidate_status"] = candidate.get("candidate_status")
    summary["atr_reference_status"] = candidate.get("atr_reference_status")
    return summary
