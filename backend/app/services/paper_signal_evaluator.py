from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.market import MarketCandidateOutcome15m, MarketSignalCandidateReadonly15m, MarketlabActiveUniverse
from app.services.utils import json_safe

PAPER_CANDIDATE_TYPE = "MID_SHORT_CONTEXT_READONLY"
PAPER_DIRECTION = "BEARISH_CONTEXT"
PAPER_STATUS_INCLUDED = "PAPER_SHORT_CANDIDATE"
PAPER_STATUS_REJECTED = "PAPER_CANDIDATE_REJECTED"
FAVORABLE_THRESHOLD_4H = Decimal("1.6076")
ADVERSE_THRESHOLD_4H = Decimal("0.9022")
RISK_ONLY_TYPES = {"SQUEEZE_RISK_CONTEXT_READONLY", "TRAP_RISK_CONTEXT_READONLY"}
RADAR_ONLY_TYPES = {"EARLY_LONG_CANDIDATE_READONLY", "EARLY_SHORT_CANDIDATE_READONLY"}


class PaperSignalEvaluatorService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_short_candidates(self, limit: int = 100, include_rejected: bool = True) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        normalized_limit = min(max(limit, 1), 500)
        scan_limit = normalized_limit if include_rejected else 5000
        for candidate, universe, outcome in self._candidate_rows(scan_limit=scan_limit):
            item = self._evaluate(candidate, universe, outcome)
            counts[item["paper_candidate_status"]] = counts.get(item["paper_candidate_status"], 0) + 1
            if item["paper_candidate_status"] == PAPER_STATUS_INCLUDED or include_rejected:
                items.append(item)
            if len(items) >= normalized_limit:
                break
        return json_safe(
            {
                "read_only": True,
                "not_live_signal": True,
                "not_execution_instruction": True,
                "threshold_reference": _threshold_reference(),
                "count": len(items),
                "scan_limit": scan_limit,
                "status_counts": counts,
                "items": items,
            }
        )

    def _candidate_rows(
        self,
        scan_limit: int,
    ) -> list[
        tuple[
            MarketSignalCandidateReadonly15m,
            MarketlabActiveUniverse | None,
            MarketCandidateOutcome15m | None,
        ]
    ]:
        query = (
            select(MarketSignalCandidateReadonly15m, MarketlabActiveUniverse, MarketCandidateOutcome15m)
            .join(
                MarketlabActiveUniverse,
                MarketSignalCandidateReadonly15m.symbol == MarketlabActiveUniverse.symbol,
                isouter=True,
            )
            .join(
                MarketCandidateOutcome15m,
                (MarketCandidateOutcome15m.symbol == MarketSignalCandidateReadonly15m.symbol)
                & (
                    MarketCandidateOutcome15m.candidate_window_open_time
                    == MarketSignalCandidateReadonly15m.window_open_time
                ),
                isouter=True,
            )
            .order_by(desc(MarketSignalCandidateReadonly15m.window_close_time), MarketSignalCandidateReadonly15m.symbol)
            .limit(scan_limit)
        )
        return list(self.db.execute(query).all())

    def _evaluate(
        self,
        candidate: MarketSignalCandidateReadonly15m,
        universe: MarketlabActiveUniverse | None,
        outcome: MarketCandidateOutcome15m | None,
    ) -> dict[str, Any]:
        rejection_reasons = _rejection_reasons(candidate, universe, outcome)
        status = PAPER_STATUS_REJECTED if rejection_reasons else PAPER_STATUS_INCLUDED
        evidence = candidate.evidence or {}
        return {
            "symbol": candidate.symbol,
            "candidate_type": candidate.candidate_type,
            "direction": candidate.candidate_direction,
            "paper_direction": PAPER_DIRECTION if status == PAPER_STATUS_INCLUDED else None,
            "paper_candidate_status": status,
            "paper_reason": _paper_reason(status, rejection_reasons),
            "paper_warning": _paper_warning(status),
            "rejection_reasons": rejection_reasons,
            "threshold_reference": _threshold_reference(),
            "window_open_time": candidate.window_open_time,
            "window_close_time": candidate.window_close_time,
            "classifier_status": candidate.classifier_status,
            "confidence": candidate.confidence_level,
            "confidence_score": candidate.confidence_score,
            "is_active": bool(universe and universe.is_active),
            "collection_tier": universe.collection_tier if universe else "NOT_ACTIVE",
            "universe_rank": universe.rank if universe else None,
            "futures_led_context": _has_futures_led_context(evidence),
            "spot_support_status_15m": evidence.get("spot_support_status_15m"),
            "outcome_status": outcome.outcome_status if outcome else None,
            "favorable_hit_4h": _favorable_hit(outcome),
            "adverse_breach_4h": _adverse_breach(outcome),
            "not_live_signal": True,
            "not_execution_instruction": True,
        }


def _rejection_reasons(
    candidate: MarketSignalCandidateReadonly15m,
    universe: MarketlabActiveUniverse | None,
    outcome: MarketCandidateOutcome15m | None,
) -> list[str]:
    reasons: list[str] = []
    evidence = candidate.evidence or {}
    if candidate.candidate_type in RISK_ONLY_TYPES:
        reasons.append("RISK_ONLY_CATEGORY")
    if candidate.candidate_type in RADAR_ONLY_TYPES:
        reasons.append("RADAR_ONLY_CATEGORY")
    if candidate.candidate_type == "NO_SIGNAL_CONTEXT":
        reasons.append("BASELINE_ONLY_CATEGORY")
    if candidate.candidate_type != PAPER_CANDIDATE_TYPE:
        reasons.append("NOT_MID_SHORT")
    if candidate.candidate_direction != PAPER_DIRECTION:
        reasons.append("NOT_BEARISH_CONTEXT")
    if candidate.classifier_status == "CLASSIFIER_BLOCKED":
        reasons.append("BLOCKED_CONTEXT")
    if not evidence:
        reasons.append("MISSING_EVIDENCE")
    if not _has_futures_led_context(evidence):
        reasons.append("NOT_FUTURES_LED")
    if not universe or not universe.is_active or universe.rank is None:
        reasons.append("INACTIVE_OR_MISSING_UNIVERSE")
    if outcome is None:
        reasons.append("OUTCOME_MISSING")
    elif outcome.outcome_status != "OUTCOME_READY":
        reasons.append("OUTCOME_NOT_READY")
    return reasons


def _has_futures_led_context(evidence: dict[str, Any]) -> bool:
    labels = evidence.get("supporting_psychology_labels") or []
    return evidence.get("spot_support_status_15m") == "FUTURES_LED" or "FUTURES_LED_MOVE" in labels


def _favorable_hit(outcome: MarketCandidateOutcome15m | None) -> bool | None:
    if outcome is None or outcome.max_favorable_move_4h is None:
        return None
    return abs(outcome.max_favorable_move_4h) >= FAVORABLE_THRESHOLD_4H


def _adverse_breach(outcome: MarketCandidateOutcome15m | None) -> bool | None:
    if outcome is None or outcome.max_adverse_move_4h is None:
        return None
    return abs(outcome.max_adverse_move_4h) >= ADVERSE_THRESHOLD_4H


def _paper_reason(status: str, rejection_reasons: list[str]) -> str:
    if status == PAPER_STATUS_INCLUDED:
        return "MID_SHORT futures-led paper candidate using read-only median 4h threshold reference"
    return "Rejected from paper candidate study: " + ", ".join(rejection_reasons)


def _paper_warning(status: str) -> str:
    if status == PAPER_STATUS_INCLUDED:
        return "Read-only paper candidate only; not a live signal and not an execution instruction"
    return "Rejected row is audit context only"


def _threshold_reference() -> dict[str, Any]:
    return {
        "source_phase": "8C",
        "source_filter_phase": "8D",
        "band": "median_4h",
        "candidate_type": PAPER_CANDIDATE_TYPE,
        "direction": PAPER_DIRECTION,
        "favorable_threshold_pct": str(FAVORABLE_THRESHOLD_4H),
        "adverse_threshold_pct": str(ADVERSE_THRESHOLD_4H),
        "final_tp_sl": False,
    }
