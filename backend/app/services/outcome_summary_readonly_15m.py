from __future__ import annotations

from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import MarketCandidateOutcome15m, MarketFeatureContext15m1h

READY_STATUS = "OUTCOME_READY"
DIRECTIONAL_CONTEXTS = ("BULLISH_CONTEXT", "BEARISH_CONTEXT")
SMALL_SAMPLE_THRESHOLD = 10
EXPECTED_CANDIDATE_TYPES = (
    "MID_LONG_CONTEXT_READONLY",
    "MID_SHORT_CONTEXT_READONLY",
    "EARLY_LONG_CANDIDATE_READONLY",
    "EARLY_SHORT_CANDIDATE_READONLY",
    "SQUEEZE_RISK_CONTEXT_READONLY",
    "TRAP_RISK_CONTEXT_READONLY",
    "NO_SIGNAL_CONTEXT",
)

SUMMARY_METRICS = (
    "future_return_15m",
    "future_return_30m",
    "future_return_1h",
    "future_return_4h",
    "max_up_move_1h",
    "max_down_move_1h",
    "max_up_move_4h",
    "max_down_move_4h",
)

DIRECTIONAL_METRICS = (
    "max_favorable_move_1h",
    "max_adverse_move_1h",
    "max_favorable_move_4h",
    "max_adverse_move_4h",
)


class OutcomeSummaryReadonly15mService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(self) -> dict[str, Any]:
        ready_rows = self._ready_rows()
        total_ready = len(ready_rows)
        candidate_type_counts = self._counts_by(ready_rows, "candidate_type")
        direction_counts = self._counts_by(ready_rows, "candidate_direction")
        top_candidate_type = candidate_type_counts[0] if candidate_type_counts else None
        top_symbol = self._top_symbols(ready_rows, limit=1)
        max_symbol_count = top_symbol[0]["count"] if top_symbol else 0

        return {
            "summary_type": "read-only outcome summary",
            "scope": "candidate behavior and forward movement from closed candles only",
            "not_a_backtest": True,
            "not_trading_performance": True,
            "sample_size_limited": True,
            "overall_counts": self._overall_counts(),
            "ready_sample_size": total_ready,
            "candidate_type_counts_ready": self._candidate_type_counts_ready(ready_rows),
            "direction_counts_ready": direction_counts,
            "median_metrics_by_candidate_type": self._median_metrics_by_candidate_type(ready_rows),
            "directional_medians": self._directional_medians(ready_rows),
            "followthrough_counts_ready": self._counts_by(ready_rows, "followthrough_status"),
            "invalidation_counts_ready": self._counts_by(ready_rows, "invalidation_status"),
            "concentration": {
                "top_symbols_by_candidate_count": self._top_symbols(ready_rows, limit=10),
                "max_symbol_share_pct": _share_pct(max_symbol_count, total_ready),
                "top_candidate_type_share_pct": _share_pct(
                    top_candidate_type["count"] if top_candidate_type else 0,
                    total_ready,
                ),
                "max_symbol_concentrated": _share_pct(max_symbol_count, total_ready) > Decimal("20"),
                "top_candidate_type_concentrated": _share_pct(
                    top_candidate_type["count"] if top_candidate_type else 0,
                    total_ready,
                )
                > Decimal("50"),
                "small_sample_warning": total_ready < 1000,
            },
            "spot_futures_evidence_breakdown_ready": self._spot_futures_breakdown_ready(),
            "integrity": {
                "duplicate_outcome_rows": self.duplicate_outcome_rows(),
                "evidence_empty_rows": self.evidence_empty_rows(),
                "ready_rows_used_for_metrics": total_ready,
                "blocked_rows_used_for_directional_metrics": 0,
                "mixed_context_directional_metrics_forced": False,
            },
            "guardrails": {
                "uses_outcome_ready_only_for_forward_metrics": True,
                "data_blocked_excluded_from_directional_metrics": True,
                "mixed_context_not_forced_directional": True,
            },
        }

    def duplicate_outcome_rows(self) -> int:
        duplicate_query = (
            select(
                MarketCandidateOutcome15m.symbol,
                MarketCandidateOutcome15m.candidate_window_open_time,
                func.count().label("row_count"),
            )
            .group_by(MarketCandidateOutcome15m.symbol, MarketCandidateOutcome15m.candidate_window_open_time)
            .having(func.count() > 1)
            .subquery()
        )
        return self.db.scalar(select(func.count()).select_from(duplicate_query)) or 0

    def evidence_empty_rows(self) -> int:
        rows = self.db.scalars(select(MarketCandidateOutcome15m)).all()
        return sum(1 for row in rows if not row.evidence)

    def _overall_counts(self) -> dict[str, int]:
        statuses = ("OUTCOME_READY", "OUTCOME_BLOCKED", "OUTCOME_WAITING_DATA", "OUTCOME_INCOMPLETE")
        counts = {status: 0 for status in statuses}
        rows = self.db.execute(
            select(MarketCandidateOutcome15m.outcome_status, func.count()).group_by(
                MarketCandidateOutcome15m.outcome_status
            )
        ).all()
        for status, count in rows:
            counts[status] = count
        counts["total_outcome_rows"] = sum(counts.values())
        return counts

    def _ready_rows(self) -> list[MarketCandidateOutcome15m]:
        return list(
            self.db.scalars(
                select(MarketCandidateOutcome15m).where(MarketCandidateOutcome15m.outcome_status == READY_STATUS)
            ).all()
        )

    def _counts_by(self, rows: list[MarketCandidateOutcome15m], attr: str) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for row in rows:
            value = getattr(row, attr) or "UNKNOWN"
            counts[value] = counts.get(value, 0) + 1
        return [
            {"value": value, "count": count, "sample_size_warning": count < SMALL_SAMPLE_THRESHOLD}
            for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _candidate_type_counts_ready(self, rows: list[MarketCandidateOutcome15m]) -> list[dict[str, Any]]:
        counts = {candidate_type: 0 for candidate_type in EXPECTED_CANDIDATE_TYPES}
        for row in rows:
            counts[row.candidate_type] = counts.get(row.candidate_type, 0) + 1
        return [
            {"value": value, "count": count, "sample_size_warning": count < SMALL_SAMPLE_THRESHOLD}
            for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _median_metrics_by_candidate_type(self, rows: list[MarketCandidateOutcome15m]) -> list[dict[str, Any]]:
        by_type: dict[str, list[MarketCandidateOutcome15m]] = {}
        for row in rows:
            by_type.setdefault(row.candidate_type, []).append(row)
        return [
            {
                "candidate_type": candidate_type,
                "sample_size": len(type_rows),
                "sample_size_warning": len(type_rows) < SMALL_SAMPLE_THRESHOLD,
                "medians": {metric: _median_value(getattr(row, metric) for row in type_rows) for metric in SUMMARY_METRICS},
            }
            for candidate_type, type_rows in sorted(by_type.items(), key=lambda item: (-len(item[1]), item[0]))
        ]

    def _directional_medians(self, rows: list[MarketCandidateOutcome15m]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for direction in DIRECTIONAL_CONTEXTS:
            direction_rows = [row for row in rows if row.candidate_direction == direction]
            items.append(
                {
                    "direction": direction,
                    "sample_size": len(direction_rows),
                    "sample_size_warning": len(direction_rows) < SMALL_SAMPLE_THRESHOLD,
                    "medians": {
                        metric: _median_value(getattr(row, metric) for row in direction_rows)
                        for metric in DIRECTIONAL_METRICS
                    },
                }
            )
        return items

    def _top_symbols(self, rows: list[MarketCandidateOutcome15m], limit: int) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.symbol] = counts.get(row.symbol, 0) + 1
        return [
            {"symbol": symbol, "count": count}
            for symbol, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    def _spot_futures_breakdown_ready(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(
                func.coalesce(MarketFeatureContext15m1h.spot_support_status_15m, "SPOT_UNKNOWN"),
                func.count(),
            )
            .select_from(MarketCandidateOutcome15m)
            .join(
                MarketFeatureContext15m1h,
                (
                    MarketFeatureContext15m1h.symbol == MarketCandidateOutcome15m.symbol
                )
                & (
                    MarketFeatureContext15m1h.feature_15m_window_open_time
                    == MarketCandidateOutcome15m.candidate_window_open_time
                ),
                isouter=True,
            )
            .where(MarketCandidateOutcome15m.outcome_status == READY_STATUS)
            .group_by(func.coalesce(MarketFeatureContext15m1h.spot_support_status_15m, "SPOT_UNKNOWN"))
            .order_by(func.count().desc())
        ).all()
        return [{"status": status, "count": count} for status, count in rows]


def _median_value(values) -> Decimal | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return median(clean)


def _share_pct(count: int, total: int) -> Decimal:
    if total <= 0:
        return Decimal("0")
    return (Decimal(count) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))
