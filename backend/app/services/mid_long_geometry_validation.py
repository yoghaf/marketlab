from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline15m, FuturesKline1h, SignalForwardReturnLog
from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import (
    _evidence_snapshot_from_mapping,
    _realistic_assumptions,
    _realistic_result_fields,
)
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import json_safe, utcnow


ATR_MULTIPLIER = Decimal("0.75")
REWARD_RISK = Decimal("1.0")
POLICIES: tuple[tuple[str, int | None], ...] = (
    ("TIMEOUT_60M", 60),
    ("TIMEOUT_120M", 120),
    ("TIMEOUT_4H", 240),
    ("NO_TIMEOUT", None),
)
REFERENCE_POLICY = "TIMEOUT_4H"
COMPLETED_RESULTS = {"TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE", "TIMEOUT_CLOSE"}
DEFAULT_ARTIFACT_PATH = (
    REPO_ROOT / "backend" / "artifacts" / "strategy_optimization" / "v1" / "mid_long_lab63.json"
)


@dataclass(frozen=True)
class Lab63Signal:
    signal_id: str
    symbol: str
    signal_timestamp: datetime
    entry: Decimal
    evidence: dict[str, Any]
    core_score: Decimal | None = None
    evidence_score: Decimal | None = None
    evidence_data_completeness: int | None = None


@dataclass(frozen=True)
class Lab63Candle:
    open_time: datetime
    close_time: datetime
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Lab63Context:
    signal: Lab63Signal
    atr_1h: Decimal | None
    future: list[Lab63Candle]
    latest_symbol_close_time: datetime | None


@dataclass(frozen=True)
class Lab63PreparedDataset:
    epoch: str
    include_watch_only: bool
    signals: list[Lab63Signal]
    contexts: list[Lab63Context]
    latest_candle_time: datetime | None
    train_ids: set[str]
    validation_ids: set[str]


class MidLongGeometryValidationService:
    """Realistic, read-only timeout comparison for MID_LONG 1h."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_validation_sample: int = 20,
        limit: int = 25,
        prepared_dataset: Lab63PreparedDataset | None = None,
    ) -> dict[str, Any]:
        prepared = prepared_dataset or self.prepare_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
        )
        signals = prepared.signals
        contexts = prepared.contexts
        latest_candle_time = prepared.latest_candle_time
        train_ids = prepared.train_ids
        validation_ids = prepared.validation_ids

        policy_rows: list[dict[str, Any]] = []
        for policy_id, timeout_minutes in POLICIES:
            outcomes, skipped = _evaluate_policy(
                contexts,
                policy_id=policy_id,
                timeout_minutes=timeout_minutes,
                position_lock=position_lock,
            )
            all_metrics = _aggregate_policy(
                outcomes,
                skipped,
                source_ids={signal.signal_id for signal in signals},
            )
            train_metrics = _aggregate_policy(outcomes, skipped, source_ids=train_ids)
            validation_metrics = _aggregate_policy(outcomes, skipped, source_ids=validation_ids)
            policy_rows.append(
                {
                    "policy_id": policy_id,
                    "policy_label": _policy_label(policy_id),
                    "timeout_minutes": timeout_minutes,
                    "atr_multiplier": ATR_MULTIPLIER,
                    "reward_risk": REWARD_RISK,
                    "all": all_metrics,
                    "train": train_metrics,
                    "validation": validation_metrics,
                    "latest_results": _latest_results(outcomes, limit=limit),
                }
            )

        reference = next((row for row in policy_rows if row["policy_id"] == REFERENCE_POLICY), None)
        reference_validation = (reference or {}).get("validation") or {}
        for row in policy_rows:
            validation = row["validation"]
            validation["realistic_total_r_delta_vs_4h"] = _delta(
                validation.get("realistic_total_r_closed"),
                reference_validation.get("realistic_total_r_closed"),
            )
            validation["realistic_avg_r_delta_vs_4h"] = _delta(
                validation.get("realistic_avg_r_closed"),
                reference_validation.get("realistic_avg_r_closed"),
            )
            row["verdict"] = _validation_verdict(
                row,
                min_validation_sample=max(1, min_validation_sample),
            )

        ranked = sorted(
            [
                row
                for row in policy_rows
                if int((row.get("validation") or {}).get("closed_count") or 0) >= max(1, min_validation_sample)
            ],
            key=_policy_rank_key,
            reverse=True,
        )
        return {
            "generated_at_utc": utcnow(),
            "lab": "LAB-63",
            "study_scope": "mid_long_1h_realistic_timeout_policy_validation",
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "filters": {
                "epoch": epoch,
                "stage": "MID_LONG",
                "timeframe": "1h",
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "min_validation_sample": max(1, min_validation_sample),
                "limit": max(1, limit),
            },
            "geometry": {
                "atr_source": "ATR14 futures_klines_1h closed at or before signal",
                "atr_multiplier": ATR_MULTIPLIER,
                "reward_risk": REWARD_RISK,
                "entry_source": "signal_forward_return_logs.price_at_signal futures reference",
                "forward_source": "closed AGG_READY futures_klines_15m",
                "realistic_model": "Binance taker fee + signal futures spread + slippage",
            },
            "split": {
                "method": "chronological_70_30",
                "source_signal_count": len(signals),
                "train_source_count": len(train_ids),
                "validation_source_count": len(validation_ids),
            },
            "latest_futures_15m_close_time": latest_candle_time,
            "reference_policy": REFERENCE_POLICY,
            "best_observed_policy": ranked[0] if ranked else None,
            "policies": policy_rows,
            "guardrails": [
                "No Signal Factory, scanner, or live TP/SL rule changed.",
                "The 4h policy is the comparison reference; 60m and 120m are not assumed superior.",
                "NO_TIMEOUT keeps an unresolved position open through the latest contiguous closed candle.",
                "Missing or gapped forward candles are never forced into a completed result.",
                "Best observed means descriptive research only, not promotion to a live rule.",
            ],
        }

    def prepare_dataset(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
    ) -> Lab63PreparedDataset:
        signals = self._load_signals(epoch=epoch, include_watch_only=include_watch_only)
        contexts, latest_candle_time = self._load_contexts(signals)
        train_ids, validation_ids = _chronological_split(signals)
        return Lab63PreparedDataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
            signals=signals,
            contexts=contexts,
            latest_candle_time=latest_candle_time,
            train_ids=train_ids,
            validation_ids=validation_ids,
        )

    def _load_signals(self, *, epoch: str, include_watch_only: bool) -> list[Lab63Signal]:
        query = (
            select(
                SignalForwardReturnLog.signal_id,
                SignalForwardReturnLog.symbol,
                SignalForwardReturnLog.signal_timestamp,
                SignalForwardReturnLog.price_at_signal,
                SignalForwardReturnLog.evidence,
                SignalForwardReturnLog.core_score,
                SignalForwardReturnLog.evidence_score,
                SignalForwardReturnLog.evidence_data_completeness,
            )
            .where(
                SignalForwardReturnLog.candidate_status == "SIGNAL_CANDIDATE",
                SignalForwardReturnLog.observation_epoch == epoch,
                SignalForwardReturnLog.stage == "MID_LONG",
                SignalForwardReturnLog.timeframe == "1h",
                SignalForwardReturnLog.direction == "LONG",
                SignalForwardReturnLog.price_at_signal.is_not(None),
            )
            .order_by(asc(SignalForwardReturnLog.signal_timestamp), asc(SignalForwardReturnLog.symbol))
        )
        if not include_watch_only:
            query = query.where(
                (SignalForwardReturnLog.execution_flag.is_(None))
                | (SignalForwardReturnLog.execution_flag != "WATCH_ONLY")
            )
        output: list[Lab63Signal] = []
        for row in self.db.execute(query).all():
            item = row._mapping
            raw_evidence = item["evidence"] if isinstance(item["evidence"], dict) else {}
            evidence = raw_evidence.get("evidence") if isinstance(raw_evidence.get("evidence"), dict) else raw_evidence
            output.append(
                Lab63Signal(
                    signal_id=str(item["signal_id"]),
                    symbol=str(item["symbol"]),
                    signal_timestamp=_naive(item["signal_timestamp"]),
                    entry=Decimal(item["price_at_signal"]),
                    evidence=dict(evidence),
                    core_score=(Decimal(item["core_score"]) if item["core_score"] is not None else None),
                    evidence_score=(
                        Decimal(item["evidence_score"])
                        if item["evidence_score"] is not None
                        else None
                    ),
                    evidence_data_completeness=(
                        int(item["evidence_data_completeness"])
                        if item["evidence_data_completeness"] is not None
                        else None
                    ),
                )
            )
        return output

    def _load_contexts(self, signals: list[Lab63Signal]) -> tuple[list[Lab63Context], datetime | None]:
        if not signals:
            return [], None
        symbols = {signal.symbol for signal in signals}
        min_signal_time = min(signal.signal_timestamp for signal in signals)
        candles_15m = self._load_15m_candles(symbols, min_signal_time)
        candles_1h = self._load_1h_candles(symbols, min_signal_time, max(signal.signal_timestamp for signal in signals))
        open_times_15m = {symbol: [candle.open_time for candle in rows] for symbol, rows in candles_15m.items()}
        close_times_1h = {symbol: [candle.close_time for candle in rows] for symbol, rows in candles_1h.items()}
        contexts: list[Lab63Context] = []
        latest_candle_time = max(
            (candle.close_time for rows in candles_15m.values() for candle in rows),
            default=None,
        )
        for signal in signals:
            symbol_15m = candles_15m.get(signal.symbol, [])
            contexts.append(
                Lab63Context(
                    signal=signal,
                    atr_1h=_atr_at(
                        candles_1h.get(signal.symbol, []),
                        close_times_1h.get(signal.symbol, []),
                        signal.signal_timestamp,
                    ),
                    future=_contiguous_future(
                        symbol_15m,
                        open_times_15m.get(signal.symbol, []),
                        signal.signal_timestamp,
                    ),
                    latest_symbol_close_time=symbol_15m[-1].close_time if symbol_15m else None,
                )
            )
        return contexts, latest_candle_time

    def _load_15m_candles(
        self,
        symbols: set[str],
        min_signal_time: datetime,
    ) -> dict[str, list[Lab63Candle]]:
        rows = self.db.execute(
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
                FuturesKline15m.open_time >= min_signal_time,
            )
            .order_by(asc(FuturesKline15m.symbol), asc(FuturesKline15m.open_time))
        ).all()
        return _candle_map(rows)

    def _load_1h_candles(
        self,
        symbols: set[str],
        min_signal_time: datetime,
        max_signal_time: datetime,
    ) -> dict[str, list[Lab63Candle]]:
        rows = self.db.execute(
            select(
                FuturesKline1h.symbol,
                FuturesKline1h.open_time,
                FuturesKline1h.close_time,
                FuturesKline1h.high,
                FuturesKline1h.low,
                FuturesKline1h.close,
            )
            .where(
                FuturesKline1h.symbol.in_(symbols),
                FuturesKline1h.aggregation_status == "AGG_READY",
                FuturesKline1h.close_time >= min_signal_time - timedelta(hours=20),
                FuturesKline1h.close_time <= max_signal_time,
            )
            .order_by(asc(FuturesKline1h.symbol), asc(FuturesKline1h.open_time))
        ).all()
        return _candle_map(rows)


class MidLongGeometryValidationArtifactRunner:
    def __init__(self, db: Session, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.db = db
        self.artifact_path = artifact_path

    def run(self, **kwargs: Any) -> dict[str, Any]:
        payload = json_safe(MidLongGeometryValidationService(self.db).summary(**kwargs))
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


class MidLongGeometryValidationArtifactService:
    def __init__(self, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.artifact_path = artifact_path

    def summary(self) -> dict[str, Any]:
        if not self.artifact_path.exists():
            raise FileNotFoundError(f"LAB-63 artifact not found: {self.artifact_path}")
        return json.loads(self.artifact_path.read_text(encoding="utf-8"))


def _evaluate_policy(
    contexts: list[Lab63Context],
    *,
    policy_id: str,
    timeout_minutes: int | None,
    position_lock: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    outcomes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    locked_until: dict[str, datetime | None] = {}
    for context in contexts:
        signal = context.signal
        lock_time = locked_until.get(signal.symbol)
        if position_lock and signal.symbol in locked_until and (
            lock_time is None or signal.signal_timestamp < lock_time
        ):
            skipped.append(
                {
                    "signal_id": signal.signal_id,
                    "symbol": signal.symbol,
                    "signal_timestamp": signal.signal_timestamp,
                    "reason": "ACTIVE_POSITION_LOCK",
                }
            )
            continue
        result = _evaluate_context(context, policy_id=policy_id, timeout_minutes=timeout_minutes)
        outcomes.append(result)
        if position_lock:
            if result["result_status"] in COMPLETED_RESULTS and result.get("result_time_utc"):
                locked_until[signal.symbol] = result["result_time_utc"]
            else:
                locked_until[signal.symbol] = None
    return outcomes, skipped


def _evaluate_context(
    context: Lab63Context,
    *,
    policy_id: str,
    timeout_minutes: int | None,
) -> dict[str, Any]:
    signal = context.signal
    base = {
        "signal_id": signal.signal_id,
        "symbol": signal.symbol,
        "signal_timestamp": signal.signal_timestamp,
        "policy_id": policy_id,
        "timeout_minutes": timeout_minutes,
        "entry": signal.entry,
        "atr_1h": context.atr_1h,
        "atr_multiplier": ATR_MULTIPLIER,
        "reward_risk": REWARD_RISK,
    }
    if context.atr_1h is None or context.atr_1h <= 0:
        return {**base, "result_status": "MISSING_ATR_1H", "result_time_utc": None}
    risk = context.atr_1h * ATR_MULTIPLIER
    stop = signal.entry - risk
    target = signal.entry + (risk * REWARD_RISK)
    evidence_snapshot = _evidence_snapshot_from_mapping(signal.evidence)
    realistic_base = _realistic_assumptions(
        entry=signal.entry,
        risk=risk,
        evidence_snapshot=evidence_snapshot,
    )
    base.update(
        {
            "risk": risk,
            "stop_loss": stop,
            "take_profit": target,
            **realistic_base,
        }
    )
    expected_count = None if timeout_minutes is None else max(1, timeout_minutes // 15)
    future = context.future if expected_count is None else context.future[:expected_count]
    if not future:
        return {**base, "result_status": "WAITING_DATA", "result_time_utc": None}

    for candle in future:
        tp_hit = candle.high >= target
        sl_hit = candle.low <= stop
        if tp_hit and sl_hit:
            realistic = _realistic_result_fields(
                base,
                entry=signal.entry,
                exit_reference=stop,
                risk=risk,
                direction="LONG",
                ideal_status="BOTH_HIT_SAME_CANDLE",
                ideal_r=Decimal("0"),
                conservative_status="SL_HIT_CONSERVATIVE",
            )
            return {
                **base,
                "result_status": "BOTH_HIT_SAME_CANDLE",
                "result_time_utc": candle.close_time,
                "exit_reference": stop,
                "ideal_realized_r": Decimal("0"),
                **realistic,
            }
        if tp_hit:
            realistic = _realistic_result_fields(
                base,
                entry=signal.entry,
                exit_reference=target,
                risk=risk,
                direction="LONG",
                ideal_status="TP_HIT",
                ideal_r=REWARD_RISK,
            )
            return {
                **base,
                "result_status": "TP_HIT",
                "result_time_utc": candle.close_time,
                "exit_reference": target,
                "ideal_realized_r": REWARD_RISK,
                **realistic,
            }
        if sl_hit:
            realistic = _realistic_result_fields(
                base,
                entry=signal.entry,
                exit_reference=stop,
                risk=risk,
                direction="LONG",
                ideal_status="SL_HIT",
                ideal_r=Decimal("-1"),
            )
            return {
                **base,
                "result_status": "SL_HIT",
                "result_time_utc": candle.close_time,
                "exit_reference": stop,
                "ideal_realized_r": Decimal("-1"),
                **realistic,
            }

    latest = future[-1]
    if timeout_minutes is not None:
        if len(future) < int(expected_count or 0):
            expected_close_time = signal.signal_timestamp + timedelta(minutes=timeout_minutes)
            status = (
                "INCOMPLETE_FORWARD_DATA"
                if context.latest_symbol_close_time and context.latest_symbol_close_time >= expected_close_time
                else "WAITING_DATA"
            )
            return {**base, "result_status": status, "result_time_utc": latest.close_time}
        ideal_r = (latest.close - signal.entry) / risk
        realistic = _realistic_result_fields(
            base,
            entry=signal.entry,
            exit_reference=latest.close,
            risk=risk,
            direction="LONG",
            ideal_status="TIMEOUT_CLOSE",
            ideal_r=ideal_r,
        )
        return {
            **base,
            "result_status": "TIMEOUT_CLOSE",
            "result_time_utc": latest.close_time,
            "exit_reference": latest.close,
            "ideal_realized_r": ideal_r,
            **realistic,
        }

    if context.latest_symbol_close_time and latest.close_time < context.latest_symbol_close_time:
        return {**base, "result_status": "INCOMPLETE_FORWARD_DATA", "result_time_utc": latest.close_time}
    ideal_open_r = (latest.close - signal.entry) / risk
    realistic = _realistic_result_fields(
        base,
        entry=signal.entry,
        exit_reference=latest.close,
        risk=risk,
        direction="LONG",
        ideal_status="OPEN",
        ideal_r=ideal_open_r,
        realized=False,
    )
    return {
        **base,
        "result_status": "OPEN",
        "result_time_utc": latest.close_time,
        "exit_reference": latest.close,
        "ideal_unrealized_r": ideal_open_r,
        **realistic,
    }


def _aggregate_policy(
    outcomes: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    *,
    source_ids: set[str],
) -> dict[str, Any]:
    selected = [row for row in outcomes if row["signal_id"] in source_ids]
    selected_skipped = [row for row in skipped if row["signal_id"] in source_ids]
    counts = Counter(str(row.get("result_status") or "UNKNOWN") for row in selected)
    realistic_closed = [
        Decimal(row["realistic_realized_r"])
        for row in selected
        if row.get("realistic_realized_r") is not None
    ]
    ideal_closed = [
        Decimal(row["ideal_realized_r"])
        for row in selected
        if row.get("ideal_realized_r") is not None
    ]
    realistic_open = [
        Decimal(row["realistic_unrealized_r"])
        for row in selected
        if row.get("realistic_unrealized_r") is not None
    ]
    ordered_closed = sorted(
        [row for row in selected if row.get("realistic_realized_r") is not None],
        key=lambda row: (_naive(row["result_time_utc"]), str(row["symbol"])),
    )
    symbol_counts = Counter(str(row["symbol"]) for row in ordered_closed)
    top_symbol, top_symbol_count = symbol_counts.most_common(1)[0] if symbol_counts else (None, 0)
    realistic_total = sum(realistic_closed, Decimal("0"))
    realistic_open_total = sum(realistic_open, Decimal("0"))
    ideal_total = sum(ideal_closed, Decimal("0"))
    return {
        "source_signal_count": len(source_ids),
        "evaluated_count": len(selected),
        "skipped_count": len(selected_skipped),
        "skipped_counts": dict(Counter(str(row["reason"]) for row in selected_skipped)),
        "closed_count": len(realistic_closed),
        "tp_count": counts["TP_HIT"],
        "sl_count": counts["SL_HIT"],
        "both_hit_count": counts["BOTH_HIT_SAME_CANDLE"],
        "timeout_count": counts["TIMEOUT_CLOSE"],
        "positive_timeout_count": sum(
            1
            for row in selected
            if row.get("result_status") == "TIMEOUT_CLOSE"
            and Decimal(row.get("realistic_realized_r") or 0) > 0
        ),
        "negative_timeout_count": sum(
            1
            for row in selected
            if row.get("result_status") == "TIMEOUT_CLOSE"
            and Decimal(row.get("realistic_realized_r") or 0) < 0
        ),
        "open_count": counts["OPEN"],
        "waiting_count": counts["WAITING_DATA"],
        "incomplete_count": counts["INCOMPLETE_FORWARD_DATA"],
        "missing_atr_count": counts["MISSING_ATR_1H"],
        "ideal_total_r_closed": ideal_total,
        "realistic_total_r_closed": realistic_total,
        "realistic_avg_r_closed": realistic_total / len(realistic_closed) if realistic_closed else None,
        "realistic_median_r_closed": _median(realistic_closed),
        "realistic_open_r": realistic_open_total,
        "realistic_total_r_with_open": realistic_total + realistic_open_total,
        "realism_penalty_r_closed": ideal_total - realistic_total,
        "max_realistic_drawdown_r": _drawdown(ordered_closed),
        "spread_missing_count": sum(
            1 for row in selected if str(row.get("realistic_fill_quality") or "") == "SPREAD_UNKNOWN"
        ),
        "top_symbol": top_symbol,
        "top_symbol_count": top_symbol_count,
        "top_symbol_share_pct": (
            Decimal(top_symbol_count) / Decimal(len(ordered_closed)) * Decimal("100")
            if ordered_closed
            else None
        ),
    }


def _chronological_split(signals: list[Lab63Signal]) -> tuple[set[str], set[str]]:
    if len(signals) < 2:
        return {signal.signal_id for signal in signals}, set()
    cut = max(1, min(len(signals) - 1, int(len(signals) * 0.70)))
    return (
        {signal.signal_id for signal in signals[:cut]},
        {signal.signal_id for signal in signals[cut:]},
    )


def _latest_results(outcomes: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ordered = sorted(
        outcomes,
        key=lambda row: (_naive(row["signal_timestamp"]), str(row["symbol"])),
        reverse=True,
    )
    fields = (
        "signal_id",
        "symbol",
        "signal_timestamp",
        "result_status",
        "result_time_utc",
        "entry",
        "stop_loss",
        "take_profit",
        "ideal_realized_r",
        "ideal_unrealized_r",
        "realistic_realized_r",
        "realistic_unrealized_r",
    )
    return [{field: row.get(field) for field in fields} for row in ordered[: max(1, limit)]]


def _validation_verdict(row: dict[str, Any], *, min_validation_sample: int) -> str:
    metrics = row.get("validation") or {}
    if int(metrics.get("closed_count") or 0) < min_validation_sample:
        return "INSUFFICIENT_VALIDATION"
    total = Decimal(metrics.get("realistic_total_r_closed") or 0)
    avg = Decimal(metrics.get("realistic_avg_r_closed") or 0)
    median_r = Decimal(metrics.get("realistic_median_r_closed") or 0)
    delta_avg = Decimal(metrics.get("realistic_avg_r_delta_vs_4h") or 0)
    if total > 0 and avg > 0 and median_r >= 0:
        return "VALIDATION_POSITIVE"
    if total > 0 and avg > 0:
        return "POSITIVE_BUT_SKEWED"
    if row.get("policy_id") != REFERENCE_POLICY and delta_avg > 0:
        return "REDUCES_DAMAGE_VS_4H"
    return "VALIDATION_NEGATIVE"


def _policy_rank_key(row: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    metrics = row.get("validation") or {}
    return (
        Decimal(metrics.get("realistic_avg_r_closed") or 0),
        Decimal(metrics.get("realistic_total_r_closed") or 0),
        Decimal(metrics.get("max_realistic_drawdown_r") or 0),
    )


def _policy_label(policy_id: str) -> str:
    return {
        "TIMEOUT_60M": "Timeout 60 menit",
        "TIMEOUT_120M": "Timeout 120 menit",
        "TIMEOUT_4H": "Timeout 4 jam (reference)",
        "NO_TIMEOUT": "Tanpa timeout",
    }[policy_id]


def _delta(value: Any, baseline: Any) -> Decimal | None:
    if value is None or baseline is None:
        return None
    return Decimal(value) - Decimal(baseline)


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return Decimal(str(median(values)))


def _drawdown(rows: list[dict[str, Any]]) -> Decimal:
    equity = Decimal("0")
    peak = Decimal("0")
    maximum = Decimal("0")
    for row in rows:
        equity += Decimal(row["realistic_realized_r"])
        peak = max(peak, equity)
        maximum = min(maximum, equity - peak)
    return maximum


def _atr_at(
    candles: list[Lab63Candle],
    close_times: list[datetime],
    signal_time: datetime,
    period: int = 14,
) -> Decimal | None:
    position = bisect_right(close_times, signal_time) - 1
    if position < period:
        return None
    window = candles[position - period : position + 1]
    ranges: list[Decimal] = []
    for index in range(1, len(window)):
        candle = window[index]
        previous = window[index - 1]
        ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous.close),
                abs(candle.low - previous.close),
            )
        )
    if len(ranges) != period:
        return None
    atr = sum(ranges, Decimal("0")) / Decimal(period)
    return atr if atr > 0 else None


def _contiguous_future(
    candles: list[Lab63Candle],
    open_times: list[datetime],
    signal_time: datetime,
) -> list[Lab63Candle]:
    position = bisect_left(open_times, signal_time)
    expected = signal_time
    output: list[Lab63Candle] = []
    for candle in candles[position:]:
        if candle.open_time != expected:
            break
        output.append(candle)
        expected += timedelta(minutes=15)
    return output


def _candle_map(rows: list[Any]) -> dict[str, list[Lab63Candle]]:
    output: dict[str, list[Lab63Candle]] = defaultdict(list)
    for row in rows:
        item = row._mapping if hasattr(row, "_mapping") else row
        if item["high"] is None or item["low"] is None or item["close"] is None:
            continue
        output[str(item["symbol"])].append(
            Lab63Candle(
                open_time=_naive(item["open_time"]),
                close_time=_naive(item["close_time"]),
                high=Decimal(item["high"]),
                low=Decimal(item["low"]),
                close=Decimal(item["close"]),
            )
        )
    return output


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)
