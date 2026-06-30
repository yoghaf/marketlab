from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import MarketCandidateOutcome15m, MarketSignalCandidateReadonly15m
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
    ) -> list[dict[str, Any]]:
        rows = self._latest_candidate_rows()
        items: list[dict[str, Any]] = []
        normalized_tier = tier.upper() if tier else None
        normalized_type = candidate_type.upper() if candidate_type else None
        for row in rows:
            item = self._candidate_payload(row)
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

    def _latest_candidate_rows(self) -> list[MarketSignalCandidateReadonly15m]:
        ranked = (
            select(
                MarketSignalCandidateReadonly15m.id.label("id"),
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
        query = (
            select(MarketSignalCandidateReadonly15m)
            .join(ranked, MarketSignalCandidateReadonly15m.id == ranked.c.id)
            .where(ranked.c.row_rank == 1)
            .order_by(desc(MarketSignalCandidateReadonly15m.window_close_time), MarketSignalCandidateReadonly15m.symbol)
        )
        return list(self.db.scalars(query).all())

    def _candidate_payload(self, candidate: MarketSignalCandidateReadonly15m) -> dict[str, Any]:
        tier = scanner_tier_for(candidate.candidate_type, candidate.classifier_status)
        outcome = self._matching_outcome(candidate)
        return json_safe(
            {
                "symbol": candidate.symbol,
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
                "warning_reason": tier.warning,
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
