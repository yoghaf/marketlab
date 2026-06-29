from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline15m, MarketCandidateOutcome15m, MarketSignalCandidateReadonly15m
from app.services.utils import json_safe, utcnow

OUTCOME_STATUSES = ("OUTCOME_READY", "OUTCOME_WAITING_DATA", "OUTCOME_INCOMPLETE", "OUTCOME_BLOCKED")
HORIZONS = {
    "15m": 1,
    "30m": 2,
    "1h": 4,
    "4h": 16,
}
DIRECTIONAL_CONTEXTS = {"BULLISH_CONTEXT", "BEARISH_CONTEXT"}


@dataclass(frozen=True)
class OutcomeTrackerConfig:
    followthrough_threshold_pct: Decimal = Decimal("0")
    invalidation_threshold_pct: Decimal = Decimal("0")


@dataclass
class OutcomeTrackerResult:
    candidates: int
    inserted_count: int
    updated_count: int
    status_counts: dict[str, int]


class OutcomeTracker15mService:
    def __init__(self, db: Session, config: OutcomeTrackerConfig | None = None) -> None:
        self.db = db
        self.config = config or OutcomeTrackerConfig()

    def run(
        self,
        symbols: list[str] | None = None,
        limit_windows: int | None = None,
        dry_run: bool = False,
    ) -> OutcomeTrackerResult:
        candidates = self._candidate_rows(symbols=symbols, limit_windows=limit_windows)
        inserted = 0
        updated = 0
        status_counts = {status: 0 for status in OUTCOME_STATUSES}
        latest_ready_close = self._latest_ready_close()
        now = utcnow()
        for candidate in candidates:
            payload = self._build_outcome(candidate, latest_ready_close, now)
            action = self._upsert(payload, dry_run)
            inserted += int(action == "inserted")
            updated += int(action == "updated")
            status_counts[payload["outcome_status"]] += 1
        if not dry_run:
            self.db.commit()
        return OutcomeTrackerResult(
            candidates=len(candidates),
            inserted_count=inserted,
            updated_count=updated,
            status_counts=status_counts,
        )

    def status_summary(self) -> dict[str, Any]:
        total_rows = self.db.scalar(select(func.count()).select_from(MarketCandidateOutcome15m)) or 0
        latest_candidate_time = self.db.scalar(select(func.max(MarketCandidateOutcome15m.candidate_window_close_time)))
        latest_outcome_update = self.db.scalar(select(func.max(MarketCandidateOutcome15m.updated_at)))
        return {
            "total_rows": total_rows,
            "latest_candidate_time": latest_candidate_time,
            "latest_outcome_update": latest_outcome_update,
            "outcome_status_counts": self._counts(MarketCandidateOutcome15m.outcome_status),
            "horizon_15m_status_counts": self._counts(MarketCandidateOutcome15m.outcome_15m_status),
            "horizon_30m_status_counts": self._counts(MarketCandidateOutcome15m.outcome_30m_status),
            "horizon_1h_status_counts": self._counts(MarketCandidateOutcome15m.outcome_1h_status),
            "horizon_4h_status_counts": self._counts(MarketCandidateOutcome15m.outcome_4h_status),
            "candidate_type_counts": self._named_counts(MarketCandidateOutcome15m.candidate_type, "type"),
            "direction_counts": self._named_counts(MarketCandidateOutcome15m.candidate_direction, "direction"),
        }

    def list_outcomes(self, symbol: str | None = None, limit: int = 100) -> list[MarketCandidateOutcome15m]:
        query = select(MarketCandidateOutcome15m).order_by(
            desc(MarketCandidateOutcome15m.candidate_window_close_time),
            MarketCandidateOutcome15m.symbol,
        )
        if symbol:
            query = query.where(MarketCandidateOutcome15m.symbol == symbol.upper())
        return list(self.db.scalars(query.limit(min(max(limit, 1), 500))).all())

    def _build_outcome(
        self,
        candidate: MarketSignalCandidateReadonly15m,
        latest_ready_close: datetime | None,
        now: datetime,
    ) -> dict[str, Any]:
        candidate_candle = self._candidate_candle(candidate)
        candidate_close_price = candidate_candle.close if candidate_candle else None
        missing_windows: list[dict[str, Any]] = []

        horizon_results = {}
        for horizon, expected_count in HORIZONS.items():
            horizon_results[horizon] = self._horizon_result(
                candidate=candidate,
                candidate_close_price=candidate_close_price,
                expected_count=expected_count,
                latest_ready_close=latest_ready_close,
                missing_windows=missing_windows,
            )

        if candidate.candidate_type == "DATA_BLOCKED" or candidate.candidate_direction == "BLOCKED_CONTEXT":
            outcome_status = "OUTCOME_BLOCKED"
            horizon_statuses = {horizon: "OUTCOME_BLOCKED" for horizon in HORIZONS}
        else:
            horizon_statuses = {horizon: result["status"] for horizon, result in horizon_results.items()}
            outcome_status = self._row_status(list(horizon_statuses.values()))
            if candidate_close_price is None or candidate_candle is None or candidate_candle.aggregation_status != "AGG_READY":
                outcome_status = "OUTCOME_INCOMPLETE"
                for horizon in HORIZONS:
                    if horizon_statuses[horizon] != "OUTCOME_WAITING_DATA":
                        horizon_statuses[horizon] = "OUTCOME_INCOMPLETE"

        metrics = self._movement_metrics(candidate, candidate_close_price, horizon_results)
        followthrough_status, invalidation_status = self._descriptive_statuses(candidate, metrics, outcome_status)
        evidence = self._evidence(
            candidate=candidate,
            candidate_candle=candidate_candle,
            latest_ready_close=latest_ready_close,
            horizon_results=horizon_results,
            missing_windows=missing_windows,
        )

        return {
            "symbol": candidate.symbol,
            "candidate_window_open_time": candidate.window_open_time,
            "candidate_window_close_time": candidate.window_close_time,
            "candidate_type": candidate.candidate_type,
            "candidate_direction": candidate.candidate_direction,
            "classifier_status": candidate.classifier_status,
            "candidate_close_price": candidate_close_price,
            "outcome_status": outcome_status,
            "outcome_15m_status": horizon_statuses["15m"],
            "outcome_30m_status": horizon_statuses["30m"],
            "outcome_1h_status": horizon_statuses["1h"],
            "outcome_4h_status": horizon_statuses["4h"],
            "future_return_15m": horizon_results["15m"]["return_pct"] if horizon_statuses["15m"] == "OUTCOME_READY" else None,
            "future_return_30m": horizon_results["30m"]["return_pct"] if horizon_statuses["30m"] == "OUTCOME_READY" else None,
            "future_return_1h": horizon_results["1h"]["return_pct"] if horizon_statuses["1h"] == "OUTCOME_READY" else None,
            "future_return_4h": horizon_results["4h"]["return_pct"] if horizon_statuses["4h"] == "OUTCOME_READY" else None,
            "max_up_move_1h": metrics["max_up_move_1h"],
            "max_down_move_1h": metrics["max_down_move_1h"],
            "max_up_move_4h": metrics["max_up_move_4h"],
            "max_down_move_4h": metrics["max_down_move_4h"],
            "max_favorable_move_1h": metrics["max_favorable_move_1h"],
            "max_adverse_move_1h": metrics["max_adverse_move_1h"],
            "max_favorable_move_4h": metrics["max_favorable_move_4h"],
            "max_adverse_move_4h": metrics["max_adverse_move_4h"],
            "followthrough_status": followthrough_status,
            "invalidation_status": invalidation_status,
            "source_candle_count_15m": horizon_results["15m"]["actual_count"],
            "source_candle_count_30m": horizon_results["30m"]["actual_count"],
            "source_candle_count_1h": horizon_results["1h"]["actual_count"],
            "source_candle_count_4h": horizon_results["4h"]["actual_count"],
            "missing_window_list": missing_windows,
            "evidence": json_safe(evidence),
            "created_at": now,
            "updated_at": now,
        }

    def _horizon_result(
        self,
        candidate: MarketSignalCandidateReadonly15m,
        candidate_close_price: Decimal | None,
        expected_count: int,
        latest_ready_close: datetime | None,
        missing_windows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        required_closes = [
            _as_utc(candidate.window_close_time) + timedelta(minutes=15 * offset)
            for offset in range(1, expected_count + 1)
        ]
        actual_candles = self._future_candles(candidate.symbol, required_closes)
        actual_by_close = {_as_utc(row.close_time): row for row in actual_candles if row.aggregation_status == "AGG_READY"}
        elapsed = latest_ready_close is not None and max(required_closes) <= _as_utc(latest_ready_close)
        missing = [close_time for close_time in required_closes if close_time not in actual_by_close]

        if candidate.candidate_type == "DATA_BLOCKED" or candidate.candidate_direction == "BLOCKED_CONTEXT":
            status = "OUTCOME_BLOCKED"
        elif candidate_close_price is None:
            status = "OUTCOME_INCOMPLETE" if elapsed else "OUTCOME_WAITING_DATA"
        elif missing:
            status = "OUTCOME_INCOMPLETE" if elapsed else "OUTCOME_WAITING_DATA"
        else:
            status = "OUTCOME_READY"

        if status == "OUTCOME_INCOMPLETE":
            for close_time in missing:
                missing_windows.append(
                    {
                        "symbol": candidate.symbol,
                        "expected_close_time": close_time,
                        "horizon_expected_count": expected_count,
                    }
                )

        candles = [actual_by_close[close_time] for close_time in required_closes if close_time in actual_by_close]
        horizon_close = candles[-1].close if status == "OUTCOME_READY" and candles else None
        return {
            "status": status,
            "expected_count": expected_count,
            "actual_count": len(candles),
            "required_closes": required_closes,
            "candles": candles,
            "return_pct": _pct_change(horizon_close, candidate_close_price) if status == "OUTCOME_READY" else None,
        }

    def _movement_metrics(
        self,
        candidate: MarketSignalCandidateReadonly15m,
        candidate_close_price: Decimal | None,
        horizon_results: dict[str, dict[str, Any]],
    ) -> dict[str, Decimal | None]:
        metrics = {
            "max_up_move_1h": None,
            "max_down_move_1h": None,
            "max_up_move_4h": None,
            "max_down_move_4h": None,
            "max_favorable_move_1h": None,
            "max_adverse_move_1h": None,
            "max_favorable_move_4h": None,
            "max_adverse_move_4h": None,
        }
        if candidate_close_price in (None, Decimal("0")):
            return metrics

        for horizon, prefix in (("1h", "1h"), ("4h", "4h")):
            result = horizon_results[horizon]
            if result["status"] != "OUTCOME_READY":
                continue
            candles = result["candles"]
            max_high = max((row.high for row in candles if row.high is not None), default=None)
            min_low = min((row.low for row in candles if row.low is not None), default=None)
            max_up = _pct_change(max_high, candidate_close_price)
            max_down = _pct_change(min_low, candidate_close_price)
            metrics[f"max_up_move_{prefix}"] = max_up
            metrics[f"max_down_move_{prefix}"] = max_down
            if candidate.candidate_direction == "BULLISH_CONTEXT":
                metrics[f"max_favorable_move_{prefix}"] = max_up
                metrics[f"max_adverse_move_{prefix}"] = max_down
            elif candidate.candidate_direction == "BEARISH_CONTEXT":
                metrics[f"max_favorable_move_{prefix}"] = abs(max_down) if max_down is not None else None
                metrics[f"max_adverse_move_{prefix}"] = max_up
        return metrics

    def _descriptive_statuses(
        self,
        candidate: MarketSignalCandidateReadonly15m,
        metrics: dict[str, Decimal | None],
        outcome_status: str,
    ) -> tuple[str, str]:
        if outcome_status == "OUTCOME_BLOCKED":
            return "NOT_APPLICABLE", "NOT_APPLICABLE"
        if candidate.candidate_direction == "MIXED_CONTEXT":
            return "MIXED_CONTEXT_ONLY", "MIXED_CONTEXT_ONLY"
        if candidate.candidate_direction not in DIRECTIONAL_CONTEXTS:
            return "NOT_APPLICABLE", "NOT_APPLICABLE"
        favorable = metrics["max_favorable_move_1h"]
        adverse = metrics["max_adverse_move_1h"]
        if favorable is None or adverse is None:
            return "NOT_APPLICABLE", "NOT_APPLICABLE"
        followthrough = "FOLLOWTHROUGH" if favorable > self.config.followthrough_threshold_pct else "NO_FOLLOWTHROUGH"
        if candidate.candidate_direction == "BULLISH_CONTEXT":
            invalidated = adverse < -self.config.invalidation_threshold_pct
        else:
            invalidated = adverse > self.config.invalidation_threshold_pct
        invalidation = "INVALIDATED" if invalidated else "NOT_INVALIDATED"
        return followthrough, invalidation

    def _evidence(
        self,
        candidate: MarketSignalCandidateReadonly15m,
        candidate_candle: FuturesKline15m | None,
        latest_ready_close: datetime | None,
        horizon_results: dict[str, dict[str, Any]],
        missing_windows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "source": "market_signal_candidates_readonly_15m + futures_klines_15m",
            "read_only_outcome": True,
            "not_entry_signal": True,
            "outcome_reason": "forward closed-candle price observation only; no order or allocation instruction",
            "candidate_id": candidate.id,
            "candidate_type": candidate.candidate_type,
            "candidate_direction": candidate.candidate_direction,
            "classifier_status": candidate.classifier_status,
            "candidate_candle_status": candidate_candle.aggregation_status if candidate_candle else None,
            "candidate_candle_close_time": candidate_candle.close_time if candidate_candle else None,
            "latest_ready_futures_15m_close": latest_ready_close,
            "horizons": {
                horizon: {
                    "status": result["status"],
                    "expected_count": result["expected_count"],
                    "actual_count": result["actual_count"],
                    "required_close_times": result["required_closes"],
                }
                for horizon, result in horizon_results.items()
            },
            "missing_window_list": missing_windows,
        }

    def _row_status(self, horizon_statuses: list[str]) -> str:
        if any(status == "OUTCOME_BLOCKED" for status in horizon_statuses):
            return "OUTCOME_BLOCKED"
        if any(status == "OUTCOME_INCOMPLETE" for status in horizon_statuses):
            return "OUTCOME_INCOMPLETE"
        if all(status == "OUTCOME_READY" for status in horizon_statuses):
            return "OUTCOME_READY"
        return "OUTCOME_WAITING_DATA"

    def _candidate_rows(self, symbols: list[str] | None, limit_windows: int | None) -> list[MarketSignalCandidateReadonly15m]:
        query = select(MarketSignalCandidateReadonly15m).order_by(
            desc(MarketSignalCandidateReadonly15m.window_open_time),
            MarketSignalCandidateReadonly15m.symbol,
        )
        if symbols:
            symbol_set = [symbol.upper() for symbol in symbols]
            query = query.where(MarketSignalCandidateReadonly15m.symbol.in_(symbol_set))
        if limit_windows:
            query = query.limit(limit_windows)
        rows = list(self.db.scalars(query).all())
        rows.reverse()
        return rows

    def _candidate_candle(self, candidate: MarketSignalCandidateReadonly15m) -> FuturesKline15m | None:
        return self.db.scalar(
            select(FuturesKline15m).where(
                FuturesKline15m.symbol == candidate.symbol,
                FuturesKline15m.open_time == candidate.window_open_time,
            )
        )

    def _future_candles(self, symbol: str, required_closes: list[datetime]) -> list[FuturesKline15m]:
        return list(
            self.db.scalars(
                select(FuturesKline15m).where(
                    FuturesKline15m.symbol == symbol,
                    FuturesKline15m.close_time.in_([_as_db_time(value) for value in required_closes]),
                )
            ).all()
        )

    def _latest_ready_close(self) -> datetime | None:
        return self.db.scalar(
            select(func.max(FuturesKline15m.close_time)).where(FuturesKline15m.aggregation_status == "AGG_READY")
        )

    def _upsert(self, payload: dict[str, Any], dry_run: bool) -> str:
        row = self.db.scalar(
            select(MarketCandidateOutcome15m).where(
                MarketCandidateOutcome15m.symbol == payload["symbol"],
                MarketCandidateOutcome15m.candidate_window_open_time == payload["candidate_window_open_time"],
            )
        )
        if dry_run:
            return "updated" if row else "inserted"
        if row:
            for key, value in payload.items():
                if key != "created_at":
                    setattr(row, key, value)
            return "updated"
        self.db.add(MarketCandidateOutcome15m(**payload))
        return "inserted"

    def _counts(self, column) -> dict[str, int]:
        counts = {status: 0 for status in OUTCOME_STATUSES}
        rows = self.db.execute(select(column, func.count()).group_by(column)).all()
        for status, count in rows:
            counts[status] = count
        return counts

    def _named_counts(self, column, key: str) -> list[dict[str, Any]]:
        rows = self.db.execute(select(column, func.count()).group_by(column).order_by(desc(func.count()))).all()
        return [{key: name, "count": count} for name, count in rows]


def _pct_change(new_value: Decimal | None, old_value: Decimal | None) -> Decimal | None:
    if new_value is None or old_value in (None, Decimal("0")):
        return None
    return ((new_value - old_value) / old_value) * Decimal("100")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_db_time(value: datetime) -> datetime:
    return _as_utc(value).replace(tzinfo=None)
