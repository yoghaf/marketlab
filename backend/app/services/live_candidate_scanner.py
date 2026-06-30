from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from app.models.market import MarketCandidateOutcome15m, MarketSignalCandidateReadonly15m, MarketlabActiveUniverse
from app.services.utils import json_safe

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
    def __init__(self, db: Session) -> None:
        self.db = db

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
        items: list[dict[str, Any]] = []
        normalized_tier = tier.upper() if tier else None
        normalized_type = candidate_type.upper() if candidate_type else None
        for row, latest_actual_row, universe in rows:
            item = self._candidate_payload(
                row,
                latest_actual_row,
                universe,
                include_blocked=include_blocked,
                include_inactive=include_inactive,
            )
            if normalized_type and row.candidate_type != normalized_type:
                continue
            if normalized_tier and item["scanner_tier"] != normalized_tier:
                continue
            if not include_blocked and item["scanner_tier"] == "BLOCKED":
                continue
            items.append(item)
            if len(items) >= min(max(limit, 1), 500):
                break
        return items

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
                "latest_outcome_status": outcome.outcome_status if outcome else None,
                "latest_outcome_update": outcome.updated_at if outcome else None,
                "not_entry_signal": True,
            }
        )

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
        "close_position_15m",
        "oi_change_pct_15m",
        "price_return_pct_1h",
        "global_long_short_ratio_15m",
        "top_trader_position_ratio_15m",
        "funding_status_15m",
        "spot_support_status_15m",
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
