from __future__ import annotations

from bisect import bisect_left
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

EVIDENCE_FIELDS = [
    ("price_return", "Price return %"),
    ("volume_ratio_vs_lookback", "Volume vs avg"),
    ("range_ratio_vs_atr", "Range / ATR"),
    ("atr_extension_normalized", "ATR extension"),
    ("price_atr_multiple", "Price ATR multiple"),
    ("kline_taker_buy_ratio", "Taker buy ratio"),
    ("kline_taker_sell_ratio", "Taker sell ratio"),
    ("oi_change_pct", "OI change %"),
    ("oi_zscore", "OI z-score"),
    ("funding_percentile_30d", "Funding percentile"),
    ("futures_spread_pct", "Futures spread %"),
    ("spot_spread_pct", "Spot spread %"),
    ("global_long_short_ratio", "Global L/S ratio"),
    ("top_trader_position_ratio", "Top trader position"),
    ("top_trader_account_ratio", "Top trader account"),
    ("core_score", "Core score"),
    ("evidence_score", "Evidence score"),
    ("evidence_data_completeness", "Evidence completeness"),
]


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
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            position_lock=position_lock,
        )
        aggregate = self._aggregate(evaluated, skipped)
        items = sorted(evaluated, key=lambda item: item["signal_timestamp"] or datetime.min, reverse=True)[:limit]
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

    def quality_lab(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        stage: str | None = None,
        timeframe: str | None = None,
        min_sample: int = 5,
        limit: int = 25,
    ) -> dict[str, Any]:
        evaluated, skipped, latest_candle_time = self._evaluated_context(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
            position_lock=position_lock,
        )
        aggregate = self._aggregate(evaluated, skipped)
        closed = [item for item in evaluated if item["result_status"] in COMPLETED_OUTCOMES and item.get("realized_r") is not None]
        best = sorted(closed, key=lambda item: Decimal(item["realized_r"]), reverse=True)[:limit]
        worst = sorted(closed, key=lambda item: Decimal(item["realized_r"]))[:limit]
        open_items = sorted(
            [item for item in evaluated if item["result_status"] == "OPEN" and item.get("unrealized_r") is not None],
            key=lambda item: Decimal(item["unrealized_r"]),
            reverse=True,
        )[:limit]

        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": stage,
                "timeframe": timeframe,
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "latest_futures_15m_close_time": latest_candle_time,
            "aggregate": aggregate,
            "drawdown": _drawdown_summary(evaluated),
            "by_stage": _bucket_rows(evaluated, key="stage", min_sample=min_sample),
            "by_confidence": _bucket_rows(evaluated, key="confidence_tier", min_sample=min_sample),
            "by_timeframe": _bucket_rows(evaluated, key="timeframe", min_sample=min_sample),
            "evidence_fields": _evidence_field_rows(evaluated, min_sample=min_sample),
            "top_symbols": _bucket_rows(evaluated, key="symbol", min_sample=min_sample, limit=limit, reverse=True),
            "weak_symbols": _bucket_rows(evaluated, key="symbol", min_sample=min_sample, limit=limit, reverse=False),
            "best_signals": best,
            "worst_signals": worst,
            "open_signals": open_items,
        }

    def _evaluated_context(
        self,
        *,
        epoch: str,
        include_watch_only: bool,
        stage: str | None,
        timeframe: str | None,
        position_lock: bool,
    ) -> tuple[list[dict[str, Any]], Counter[str], datetime | None]:
        signals = self._load_signals(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
        )
        min_signal_time = min((_naive(row.signal_timestamp) for row in signals), default=None)
        candles = self._load_candles({row.symbol for row in signals}, start_time=min_signal_time)
        evaluated, skipped = self._evaluate(signals, candles, position_lock=position_lock)
        latest_candle_time = max(
            (candle.close_time for rows in candles.values() for candle in rows),
            default=None,
        )
        return evaluated, skipped, latest_candle_time

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

    def _load_candles(self, symbols: set[str], *, start_time: datetime | None) -> dict[str, list[PerfCandle]]:
        if not symbols:
            return {}
        query = (
            select(
                FuturesKline15m.symbol,
                FuturesKline15m.open_time,
                FuturesKline15m.close_time,
                FuturesKline15m.high,
                FuturesKline15m.low,
                FuturesKline15m.close,
            )
            .where(
                FuturesKline15m.symbol.in_(symbols),
                FuturesKline15m.aggregation_status == "AGG_READY",
            )
            .order_by(asc(FuturesKline15m.symbol), asc(FuturesKline15m.open_time))
        )
        if start_time is not None:
            query = query.where(FuturesKline15m.open_time >= start_time)
        rows = self.db.execute(query).all()
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
        open_times_by_symbol = {symbol: [candle.open_time for candle in rows] for symbol, rows in candles.items()}
        for signal in signals:
            signal_time = _naive(signal.signal_timestamp)
            lock_time = locked_until.get(signal.symbol)
            if position_lock and signal.symbol in locked_until and (lock_time is None or signal_time < lock_time):
                skipped["ACTIVE_POSITION_LOCK"] += 1
                continue
            item = self._evaluate_signal(
                signal,
                candles.get(signal.symbol, []),
                open_times_by_symbol.get(signal.symbol, []),
            )
            items.append(item)
            if position_lock:
                if item["result_status"] in COMPLETED_OUTCOMES and item.get("result_time_utc"):
                    locked_until[signal.symbol] = _parse_dt(item["result_time_utc"])
                else:
                    locked_until[signal.symbol] = None
        return items, skipped

    def _evaluate_signal(
        self,
        signal: SignalForwardReturnLog,
        candles: list[PerfCandle],
        open_times: list[datetime],
    ) -> dict[str, Any]:
        entry = Decimal(signal.price_at_signal)
        stop = Decimal(signal.sl_ref)
        target = Decimal(signal.tp_ref)
        risk = abs(entry - stop)
        signal_time = _naive(signal.signal_timestamp)
        direction = signal.direction
        position = bisect_left(open_times, signal_time)
        future = candles[position:]
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
            "evidence_snapshot": _evidence_snapshot(signal),
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
        total_perf = _performance_summary(items)
        timeframe_perf = {
            timeframe: _performance_summary([item for item in items if item.get("timeframe") == timeframe])
            for timeframe in ("15m", "1h", "4h", "24h")
        }
        return {
            "signals_skipped": sum(skipped.values()),
            "skip_reasons": dict(skipped),
            **total_perf,
            "status_counts": dict(status_counts),
            "by_stage": dict(by_stage),
            "by_timeframe": dict(by_timeframe),
            "by_timeframe_performance": timeframe_perf,
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


def _performance_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(item["result_status"]) for item in items)
    closed = [item for item in items if item["result_status"] in COMPLETED_OUTCOMES]
    wins = [item for item in closed if item["result_status"] == "TP_HIT"]
    losses = [item for item in closed if item["result_status"] == "SL_HIT"]
    realized_values = [Decimal(item["realized_r"]) for item in closed if item.get("realized_r") is not None]
    open_values = [
        Decimal(item["unrealized_r"])
        for item in items
        if item["result_status"] == "OPEN" and item.get("unrealized_r") is not None
    ]
    completed_for_winrate = len(wins) + len(losses)
    total_r_closed = sum(realized_values, Decimal("0"))
    total_unrealized_r = sum(open_values, Decimal("0"))
    return {
        "signals_evaluated": len(items),
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
    }


def _evidence_snapshot(signal: SignalForwardReturnLog) -> dict[str, Decimal | None]:
    raw_evidence = signal.evidence if isinstance(signal.evidence, dict) else {}
    evidence = raw_evidence.get("evidence") if isinstance(raw_evidence.get("evidence"), dict) else raw_evidence
    snapshot: dict[str, Decimal | None] = {}
    for field, _label in EVIDENCE_FIELDS:
        if field == "core_score":
            value = signal.core_score
        elif field == "evidence_score":
            value = signal.evidence_score
        elif field == "evidence_data_completeness":
            value = signal.evidence_data_completeness
        else:
            value = evidence.get(field)
        snapshot[field] = _decimal_or_none(value)
    return snapshot


def _evidence_field_rows(items: list[dict[str, Any]], *, min_sample: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field, label in EVIDENCE_FIELDS:
        values_by_result: dict[str, list[Decimal]] = defaultdict(list)
        missing = 0
        for item in items:
            value = (item.get("evidence_snapshot") or {}).get(field)
            if value is None:
                missing += 1
                continue
            result = str(item.get("result_status") or "UNKNOWN")
            if result == "BOTH_HIT_SAME_CANDLE":
                result = "BOTH"
            values_by_result[result].append(Decimal(value))

        available_count = sum(len(values) for values in values_by_result.values())
        tp_values = values_by_result.get("TP_HIT", [])
        sl_values = values_by_result.get("SL_HIT", [])
        open_values = values_by_result.get("OPEN", [])
        waiting_values = values_by_result.get("WAITING_DATA", [])
        both_values = values_by_result.get("BOTH", [])
        tp_median = _median_decimal(tp_values)
        sl_median = _median_decimal(sl_values)
        delta = tp_median - sl_median if tp_median is not None and sl_median is not None else None
        rows.append(
            {
                "field": field,
                "label": label,
                "quality_flag": _evidence_quality_flag(
                    tp_count=len(tp_values),
                    sl_count=len(sl_values),
                    delta=delta,
                    min_sample=min_sample,
                ),
                "available_count": available_count,
                "missing_count": missing,
                "available_pct": (Decimal(available_count) / Decimal(len(items)) * Decimal("100")) if items else None,
                "tp_count": len(tp_values),
                "sl_count": len(sl_values),
                "open_count": len(open_values),
                "waiting_count": len(waiting_values),
                "both_count": len(both_values),
                "tp_median": tp_median,
                "sl_median": sl_median,
                "open_median": _median_decimal(open_values),
                "waiting_median": _median_decimal(waiting_values),
                "tp_avg": _avg_decimal(tp_values),
                "sl_avg": _avg_decimal(sl_values),
                "tp_q1": _percentile_decimal(tp_values, Decimal("0.25")),
                "tp_q3": _percentile_decimal(tp_values, Decimal("0.75")),
                "sl_q1": _percentile_decimal(sl_values, Decimal("0.25")),
                "sl_q3": _percentile_decimal(sl_values, Decimal("0.75")),
                "delta_tp_minus_sl": delta,
            }
        )
    rows.sort(
        key=lambda row: (
            row["quality_flag"] != "SAMPLE_TOO_SMALL",
            abs(Decimal(row["delta_tp_minus_sl"])) if row["delta_tp_minus_sl"] is not None else Decimal("-1"),
            row["available_count"],
        ),
        reverse=True,
    )
    return rows


def _evidence_quality_flag(*, tp_count: int, sl_count: int, delta: Decimal | None, min_sample: int) -> str:
    if tp_count < min_sample or sl_count < min_sample or delta is None:
        return "SAMPLE_TOO_SMALL"
    if abs(delta) < Decimal("0.0001"):
        return "NO_CLEAR_GAP"
    if delta > 0:
        return "TP_HIGHER"
    return "SL_HIGHER"


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _avg_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _percentile_decimal(values: list[Decimal], pct: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = pct * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _bucket_rows(
    items: list[dict[str, Any]],
    *,
    key: str,
    min_sample: int,
    limit: int | None = None,
    reverse: bool = True,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[str(item.get(key) or "UNKNOWN")].append(item)

    rows = [_bucket_summary(bucket, bucket_items, min_sample=min_sample) for bucket, bucket_items in grouped.items()]
    rows.sort(
        key=lambda row: (
            Decimal(row["total_r_closed"]),
            Decimal(row["median_r_closed"]) if row["median_r_closed"] is not None else Decimal("-999"),
            row["signals_evaluated"],
        ),
        reverse=reverse,
    )
    return rows[:limit] if limit is not None else rows


def _bucket_summary(bucket: str, items: list[dict[str, Any]], *, min_sample: int) -> dict[str, Any]:
    perf = _performance_summary(items)
    closed = [item for item in items if item["result_status"] in COMPLETED_OUTCOMES and item.get("realized_r") is not None]
    realized_values = [Decimal(item["realized_r"]) for item in closed]
    mfe_values = [Decimal(item["mfe_r"]) for item in items if item.get("mfe_r") is not None]
    mae_values = [Decimal(item["mae_r"]) for item in items if item.get("mae_r") is not None]
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    top_symbol, top_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    closed_count = int(perf["closed_count"])
    total_r = Decimal(perf["total_r_closed"])
    median_r = _median_decimal(realized_values)
    winrate = perf["winrate_pct"]
    quality_flag = _quality_flag(
        sample_size=len(items),
        closed_count=closed_count,
        total_r=total_r,
        median_r=median_r,
        winrate=winrate,
        min_sample=min_sample,
    )
    return {
        "bucket": bucket,
        "quality_flag": quality_flag,
        "signals_evaluated": len(items),
        "symbol_count": len(symbols),
        "top_symbol": top_symbol,
        "top_symbol_share_pct": (Decimal(top_count) / Decimal(len(items)) * Decimal("100")) if items else None,
        "median_r_closed": median_r,
        "median_mfe_r": _median_decimal(mfe_values),
        "median_mae_r": _median_decimal(mae_values),
        "best_r": max(realized_values) if realized_values else None,
        "worst_r": min(realized_values) if realized_values else None,
        **perf,
    }


def _quality_flag(
    *,
    sample_size: int,
    closed_count: int,
    total_r: Decimal,
    median_r: Decimal | None,
    winrate: Decimal | None,
    min_sample: int,
) -> str:
    if sample_size < min_sample or closed_count < min_sample:
        return "SAMPLE_TOO_SMALL"
    if total_r > 0 and median_r is not None and median_r > 0:
        return "QUALITY_POSITIVE"
    if total_r > 0 and winrate is not None and winrate >= Decimal("45"):
        return "TOTAL_R_POSITIVE_MEDIAN_WEAK"
    if total_r < 0 and median_r is not None and median_r < 0:
        return "QUALITY_WEAK"
    return "NOISY_MIXED"


def _median_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _drawdown_summary(items: list[dict[str, Any]], *, point_limit: int = 160) -> dict[str, Any]:
    closed = [
        item
        for item in items
        if item["result_status"] in COMPLETED_OUTCOMES and item.get("realized_r") is not None
    ]
    closed.sort(key=lambda item: (_parse_dt(item.get("result_time_utc")) or _parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol"))))

    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    points: list[dict[str, Any]] = []
    for item in closed:
        realized = Decimal(item["realized_r"])
        cumulative += realized
        peak = max(peak, cumulative)
        drawdown = cumulative - peak
        max_drawdown = min(max_drawdown, drawdown)
        points.append(
            {
                "signal_id": item.get("signal_id"),
                "symbol": item.get("symbol"),
                "stage": item.get("stage"),
                "timeframe": item.get("timeframe"),
                "result_status": item.get("result_status"),
                "result_time_utc": item.get("result_time_utc"),
                "result_time_wib": item.get("result_time_wib"),
                "realized_r": realized,
                "cumulative_r": cumulative,
                "drawdown_r": drawdown,
            }
        )

    return {
        "closed_count": len(closed),
        "total_r_closed": cumulative,
        "peak_r": peak,
        "max_drawdown_r": max_drawdown,
        "current_drawdown_r": cumulative - peak,
        "points": points[-point_limit:],
    }
