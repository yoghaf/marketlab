from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import asc, or_, select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline15m, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import utcnow


COMPLETED_OUTCOMES = {"TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE"}


@dataclass(frozen=True)
class PerfCandle:
    open_time: datetime
    close_time: datetime
    high: Decimal
    low: Decimal
    close: Decimal


class SignalCandidatePerformanceService:
    """Read-only live-style performance view for logged Signal Factory candidates."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        stage: str | None = None,
        timeframe: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        signals = self._load_signals(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
        )
        candles = self._load_candles({row.symbol for row in signals})
        evaluated, skipped = self._evaluate(signals, candles, position_lock=position_lock)
        aggregate = self._aggregate(evaluated, skipped)
        items = sorted(evaluated, key=lambda item: item["signal_timestamp"] or datetime.min, reverse=True)[:limit]
        latest_candle_time = max(
            (candle.close_time for rows in candles.values() for candle in rows),
            default=None,
        )
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": stage,
                "timeframe": timeframe,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "entry_market": "futures",
            "entry_price_source": "signal_forward_return_logs.price_at_signal",
            "latest_futures_15m_close_time": latest_candle_time,
            "aggregate": aggregate,
            "items": items,
        }

    def _load_signals(
        self,
        *,
        epoch: str,
        include_watch_only: bool,
        stage: str | None,
        timeframe: str | None,
    ) -> list[SignalForwardReturnLog]:
        query = (
            select(SignalForwardReturnLog)
            .where(
                SignalForwardReturnLog.candidate_status == "SIGNAL_CANDIDATE",
                SignalForwardReturnLog.observation_epoch == epoch,
                SignalForwardReturnLog.price_at_signal.is_not(None),
                SignalForwardReturnLog.sl_ref.is_not(None),
                SignalForwardReturnLog.tp_ref.is_not(None),
            )
            .order_by(asc(SignalForwardReturnLog.signal_timestamp), asc(SignalForwardReturnLog.symbol))
        )
        if not include_watch_only:
            query = query.where(
                or_(
                    SignalForwardReturnLog.execution_flag.is_(None),
                    SignalForwardReturnLog.execution_flag != "WATCH_ONLY",
                )
            )
        if stage:
            query = query.where(SignalForwardReturnLog.stage == stage)
        if timeframe:
            query = query.where(SignalForwardReturnLog.timeframe == timeframe)
        return list(self.db.scalars(query).all())

    def _load_candles(self, symbols: set[str]) -> dict[str, list[PerfCandle]]:
        if not symbols:
            return {}
        rows = self.db.scalars(
            select(FuturesKline15m)
            .where(
                FuturesKline15m.symbol.in_(symbols),
                FuturesKline15m.aggregation_status == "AGG_READY",
            )
            .order_by(asc(FuturesKline15m.symbol), asc(FuturesKline15m.open_time))
        ).all()
        output: dict[str, list[PerfCandle]] = defaultdict(list)
        for row in rows:
            output[row.symbol].append(
                PerfCandle(
                    open_time=_naive(row.open_time),
                    close_time=_naive(row.close_time),
                    high=Decimal(row.high),
                    low=Decimal(row.low),
                    close=Decimal(row.close),
                )
            )
        return dict(output)

    def _evaluate(
        self,
        signals: list[SignalForwardReturnLog],
        candles: dict[str, list[PerfCandle]],
        *,
        position_lock: bool,
    ) -> tuple[list[dict[str, Any]], Counter[str]]:
        items: list[dict[str, Any]] = []
        skipped: Counter[str] = Counter()
        locked_until: dict[str, datetime | None] = {}
        for signal in signals:
            signal_time = _naive(signal.signal_timestamp)
            lock_time = locked_until.get(signal.symbol)
            if position_lock and signal.symbol in locked_until and (lock_time is None or signal_time < lock_time):
                skipped["ACTIVE_POSITION_LOCK"] += 1
                continue
            item = self._evaluate_signal(signal, candles.get(signal.symbol, []))
            items.append(item)
            if position_lock:
                if item["result_status"] in COMPLETED_OUTCOMES and item.get("result_time_utc"):
                    locked_until[signal.symbol] = _parse_dt(item["result_time_utc"])
                else:
                    locked_until[signal.symbol] = None
        return items, skipped

    def _evaluate_signal(self, signal: SignalForwardReturnLog, candles: list[PerfCandle]) -> dict[str, Any]:
        entry = Decimal(signal.price_at_signal)
        stop = Decimal(signal.sl_ref)
        target = Decimal(signal.tp_ref)
        risk = abs(entry - stop)
        signal_time = _naive(signal.signal_timestamp)
        direction = signal.direction
        future = [candle for candle in candles if candle.open_time >= signal_time]
        base = {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "signal_timestamp": signal_time,
            "signal_time_wib": _wib_string(signal_time),
            "stage": signal.stage,
            "direction": direction,
            "candidate_status": signal.candidate_status,
            "confidence_tier": signal.confidence_tier,
            "execution_flag": signal.execution_flag,
            "core_score": signal.core_score,
            "evidence_score": signal.evidence_score,
            "evidence_data_completeness": signal.evidence_data_completeness,
            "entry": entry,
            "stop_loss": stop,
            "take_profit": target,
            "risk": risk,
            "rr": abs(target - entry) / risk if risk > 0 else None,
            "result_status": "WAITING_DATA",
            "result_time_utc": None,
            "result_time_wib": None,
            "exit_price": None,
            "realized_r": None,
            "unrealized_r": None,
            "mfe_r": None,
            "mae_r": None,
            "candles_seen": 0,
            "not_live_signal": True,
            "not_execution_instruction": True,
        }
        if risk <= 0:
            return {**base, "result_status": "INVALID_RISK"}
        if direction not in {"LONG", "SHORT"}:
            return {**base, "result_status": "NON_DIRECTIONAL"}
        if not future:
            return base

        mfe = Decimal("0")
        mae = Decimal("0")
        for index, candle in enumerate(future, start=1):
            if direction == "LONG":
                tp_hit = candle.high >= target
                sl_hit = candle.low <= stop
                mfe = max(mfe, (candle.high - entry) / risk)
                mae = min(mae, (candle.low - entry) / risk)
            else:
                tp_hit = candle.low <= target
                sl_hit = candle.high >= stop
                mfe = max(mfe, (entry - candle.low) / risk)
                mae = min(mae, (entry - candle.high) / risk)
            if tp_hit and sl_hit:
                return {
                    **base,
                    "result_status": "BOTH_HIT_SAME_CANDLE",
                    "result_time_utc": candle.close_time,
                    "result_time_wib": _wib_string(candle.close_time),
                    "exit_price": candle.close,
                    "realized_r": Decimal("0"),
                    "unrealized_r": None,
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": index,
                }
            if tp_hit:
                return {
                    **base,
                    "result_status": "TP_HIT",
                    "result_time_utc": candle.close_time,
                    "result_time_wib": _wib_string(candle.close_time),
                    "exit_price": target,
                    "realized_r": abs(target - entry) / risk,
                    "unrealized_r": None,
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": index,
                }
            if sl_hit:
                return {
                    **base,
                    "result_status": "SL_HIT",
                    "result_time_utc": candle.close_time,
                    "result_time_wib": _wib_string(candle.close_time),
                    "exit_price": stop,
                    "realized_r": Decimal("-1"),
                    "unrealized_r": None,
                    "mfe_r": mfe,
                    "mae_r": mae,
                    "candles_seen": index,
                }

        latest = future[-1]
        unrealized = (latest.close - entry) / risk if direction == "LONG" else (entry - latest.close) / risk
        return {
            **base,
            "result_status": "OPEN",
            "result_time_utc": latest.close_time,
            "result_time_wib": _wib_string(latest.close_time),
            "exit_price": latest.close,
            "unrealized_r": unrealized,
            "mfe_r": mfe,
            "mae_r": mae,
            "candles_seen": len(future),
        }

    def _aggregate(self, items: list[dict[str, Any]], skipped: Counter[str]) -> dict[str, Any]:
        status_counts = Counter(str(item["result_status"]) for item in items)
        by_stage = Counter(str(item["stage"]) for item in items)
        by_timeframe = Counter(str(item["timeframe"]) for item in items)
        by_confidence = Counter(str(item.get("confidence_tier") or "UNKNOWN") for item in items)
        closed = [item for item in items if item["result_status"] in COMPLETED_OUTCOMES]
        wins = [item for item in closed if item["result_status"] == "TP_HIT"]
        losses = [item for item in closed if item["result_status"] == "SL_HIT"]
        realized_values = [Decimal(item["realized_r"]) for item in closed if item.get("realized_r") is not None]
        open_values = [Decimal(item["unrealized_r"]) for item in items if item["result_status"] == "OPEN" and item.get("unrealized_r") is not None]
        completed_for_winrate = len(wins) + len(losses)
        total_r_closed = sum(realized_values, Decimal("0"))
        total_unrealized_r = sum(open_values, Decimal("0"))
        return {
            "signals_evaluated": len(items),
            "signals_skipped": sum(skipped.values()),
            "skip_reasons": dict(skipped),
            "open_count": status_counts.get("OPEN", 0),
            "waiting_count": status_counts.get("WAITING_DATA", 0),
            "tp_count": status_counts.get("TP_HIT", 0),
            "sl_count": status_counts.get("SL_HIT", 0),
            "both_hit_count": status_counts.get("BOTH_HIT_SAME_CANDLE", 0),
            "closed_count": len(closed),
            "winrate_pct": (Decimal(len(wins)) / Decimal(completed_for_winrate) * Decimal("100")) if completed_for_winrate else None,
            "total_r_closed": total_r_closed,
            "open_unrealized_r": total_unrealized_r,
            "total_r_with_open": total_r_closed + total_unrealized_r,
            "fixed_risk_return_pct_1pct_closed": total_r_closed,
            "fixed_risk_return_pct_1pct_with_open": total_r_closed + total_unrealized_r,
            "avg_r_closed": total_r_closed / Decimal(len(realized_values)) if realized_values else None,
            "status_counts": dict(status_counts),
            "by_stage": dict(by_stage),
            "by_timeframe": dict(by_timeframe),
            "by_confidence": dict(by_confidence),
        }


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _naive(value)
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _wib_string(value: datetime | None) -> str | None:
    if not value:
        return None
    wib = _naive(value) + timedelta(hours=7)
    return f"{wib:%Y-%m-%d %H:%M:%S} WIB"
