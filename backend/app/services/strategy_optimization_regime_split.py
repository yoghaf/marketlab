from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from app.services.market_regime_study import (
    MarketRegimeStudyRunner,
    classify_breadth,
    classify_return,
    classify_volatility,
    combined_regime,
)
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.strategy_optimization_lab import (
    COMPLETED_RESULTS,
    StrategyContext,
    StrategyOptimizationLabService,
    _drawdown,
    _evaluate_timeout_path,
    _prepare_contexts,
    _strategy_verdict,
)
from app.services.utils import utcnow


REGIME_DIMENSIONS = (
    "combined_regime_1h",
    "btc_1h_regime",
    "btc_4h_regime",
    "eth_1h_regime",
    "eth_4h_regime",
    "breadth_1h_regime",
    "breadth_4h_regime",
    "volatility_1h_regime",
    "volatility_4h_regime",
)


class StrategyOptimizationRegimeSplitService:
    """Read-only regime split for one ATR/RR/timeout strategy parameter set."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        stage: str = "MID_SHORT",
        timeframe: str = "1h",
        atr_mult: Decimal = Decimal("0.75"),
        rr: Decimal = Decimal("2.0"),
        timeout_minutes: int = 480,
        min_sample: int = 20,
        limit: int = 80,
    ) -> dict[str, Any]:
        contexts = self._load_contexts(
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
        )
        classifier = _RegimeClassifier(self.db)
        events, skipped = _evaluated_events(
            contexts,
            classifier=classifier,
            atr_mult=float(atr_mult),
            rr=float(rr),
            timeout_minutes=timeout_minutes,
            position_lock=position_lock,
        )
        baseline = _metrics(events, min_sample=min_sample)
        dimension_rows = {
            dimension: _dimension_rows(events, dimension, baseline=baseline, min_sample=min_sample)
            for dimension in REGIME_DIMENSIONS
        }
        helpful = sorted(
            [row for rows in dimension_rows.values() for row in rows if row["verdict"] in {"REGIME_HELPFUL", "REGIME_IMPROVES"}],
            key=_regime_sort_key,
            reverse=True,
        )
        harmful = sorted(
            [row for rows in dimension_rows.values() for row in rows if row["verdict"] == "REGIME_BAD"],
            key=lambda row: (float(row.get("avg_r_delta_vs_baseline") or 0), int(row.get("sample_count") or 0)),
        )
        return {
            "generated_at_utc": utcnow(),
            "epoch": epoch,
            "filters": {
                "include_watch_only": include_watch_only,
                "position_lock": position_lock,
                "stage": stage,
                "timeframe": timeframe,
                "atr_mult": str(atr_mult),
                "rr": str(rr),
                "timeout_minutes": timeout_minutes,
                "min_sample": min_sample,
                "limit": limit,
            },
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "study_scope": "read_only_strategy_optimization_regime_split",
            "regime_inputs": {
                "btc_eth": "closed BTCUSDT/ETHUSDT futures 1h/4h candle return at or before signal timestamp",
                "breadth": "active universe futures up/down share at closed 1h/4h market window",
                "volatility": "active universe average absolute return at closed 1h/4h market window",
            },
            "strategy_reference": {
                "entry_market": "futures",
                "atr_model": "ATR14 futures_klines_1h closed before or at signal",
                "outcome_model": "futures_klines_15m after signal; timeout closes at latest timeout candle close",
            },
            "summary": {
                "signals_loaded": len(contexts),
                "evaluated_events": len(events),
                "skipped_counts": dict(skipped),
                "baseline": baseline,
                "regime_dependency": _dependency_summary(stage, helpful),
                "top_helpful_regimes": helpful[:limit],
                "top_harmful_regimes": harmful[:limit],
            },
            "dimensions": dimension_rows,
            "guardrails": [
                "No Signal Factory rule changed.",
                "No scanner behavior changed.",
                "No live signal, order, leverage, position sizing, or execution created.",
                "Regime split is diagnostic only; a regime gate needs forward validation first.",
            ],
        }

    def _load_contexts(
        self,
        *,
        epoch: str,
        include_watch_only: bool,
        stage: str,
        timeframe: str,
    ) -> list[StrategyContext]:
        optimizer = StrategyOptimizationLabService(self.db)
        signals = optimizer._load_signals(  # noqa: SLF001
            epoch=epoch,
            include_watch_only=include_watch_only,
            stage=stage,
            timeframe=timeframe,
        )
        symbols = {signal.symbol for signal in signals}
        min_time = min((signal.signal_timestamp for signal in signals), default=None)
        max_time = max((signal.signal_timestamp for signal in signals), default=None)
        candles_15m = optimizer._load_15m_candles(symbols, min_time, max_time)  # noqa: SLF001
        candles_1h = optimizer._load_1h_candles(symbols, min_time, max_time)  # noqa: SLF001
        return _prepare_contexts(
            signals,
            candles_15m=candles_15m,
            candles_1h=candles_1h,
            open_times_15m={symbol: [candle.open_time for candle in rows] for symbol, rows in candles_15m.items()},
            close_times_1h={symbol: [candle.close_time for candle in rows] for symbol, rows in candles_1h.items()},
        )


class _RegimeClassifier:
    def __init__(self, db: Session) -> None:
        self.runner = MarketRegimeStudyRunner(db)
        self.cache: dict[datetime, dict[str, Any]] = {}

    def classify(self, signal_time: datetime) -> dict[str, Any]:
        signal_time = signal_time.replace(tzinfo=None)
        if signal_time in self.cache:
            return self.cache[signal_time]
        btc_1h = self.runner._symbol_return("1h", "BTCUSDT", signal_time)  # noqa: SLF001
        btc_4h = self.runner._symbol_return("4h", "BTCUSDT", signal_time)  # noqa: SLF001
        eth_1h = self.runner._symbol_return("1h", "ETHUSDT", signal_time)  # noqa: SLF001
        eth_4h = self.runner._symbol_return("4h", "ETHUSDT", signal_time)  # noqa: SLF001
        market_1h = self.runner._market_snapshot("1h", signal_time)  # noqa: SLF001
        market_4h = self.runner._market_snapshot("4h", signal_time)  # noqa: SLF001
        regimes = {
            "btc_1h_regime": classify_return(btc_1h, bullish_threshold=0.25, bearish_threshold=-0.25),
            "btc_4h_regime": classify_return(btc_4h, bullish_threshold=0.60, bearish_threshold=-0.60),
            "eth_1h_regime": classify_return(eth_1h, bullish_threshold=0.25, bearish_threshold=-0.25),
            "eth_4h_regime": classify_return(eth_4h, bullish_threshold=0.60, bearish_threshold=-0.60),
            "breadth_1h_regime": classify_breadth(market_1h.up_pct),
            "breadth_4h_regime": classify_breadth(market_4h.up_pct),
            "volatility_1h_regime": classify_volatility(market_1h.avg_abs_return_pct, high=1.25, low=0.45),
            "volatility_4h_regime": classify_volatility(market_4h.avg_abs_return_pct, high=2.50, low=0.90),
            "btc_return_1h_pct": btc_1h,
            "btc_return_4h_pct": btc_4h,
            "eth_return_1h_pct": eth_1h,
            "eth_return_4h_pct": eth_4h,
            "breadth_1h_up_pct": market_1h.up_pct,
            "breadth_4h_up_pct": market_4h.up_pct,
            "volatility_1h_avg_abs_return_pct": market_1h.avg_abs_return_pct,
            "volatility_4h_avg_abs_return_pct": market_4h.avg_abs_return_pct,
        }
        regimes["combined_regime_1h"] = combined_regime(regimes["btc_1h_regime"], regimes["breadth_1h_regime"])
        self.cache[signal_time] = regimes
        return regimes


def _evaluated_events(
    contexts: list[StrategyContext],
    *,
    classifier: _RegimeClassifier,
    atr_mult: float,
    rr: float,
    timeout_minutes: int,
    position_lock: bool,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    events: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    locked_until: dict[str, datetime | None] = {}
    expected_count = max(1, timeout_minutes // 15)
    for context in contexts:
        signal = context.signal
        lock_time = locked_until.get(signal.symbol)
        if position_lock and signal.symbol in locked_until and (lock_time is None or signal.signal_timestamp < lock_time):
            skipped["ACTIVE_POSITION_LOCK"] += 1
            continue
        if context.atr_1h is None:
            skipped["MISSING_ATR_1H"] += 1
            continue
        future = context.futures_by_timeout.get(timeout_minutes, [])
        if not future:
            skipped["MISSING_FORWARD_15M"] += 1
            continue
        result = _evaluate_timeout_path(signal, future, risk=context.atr_1h * atr_mult, rr=rr, expected_count=expected_count)
        events.append(
            {
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "stage": signal.stage,
                "timeframe": signal.timeframe,
                "direction": signal.direction,
                "signal_timestamp": signal.signal_timestamp,
                "result_status": result["result_status"],
                "result_time_utc": result["result_time_utc"],
                "realized_r": result["realized_r"],
                "regimes": classifier.classify(signal.signal_timestamp),
            }
        )
        if position_lock:
            if result["result_status"] in COMPLETED_RESULTS and result.get("result_time_utc"):
                locked_until[signal.symbol] = result["result_time_utc"]
            else:
                locked_until[signal.symbol] = None
    return events, skipped


def _dimension_rows(events: list[dict[str, Any]], dimension: str, *, baseline: dict[str, Any], min_sample: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[str(event.get("regimes", {}).get(dimension) or "REGIME_UNKNOWN")].append(event)
    rows = []
    for bucket, bucket_events in grouped.items():
        metrics = _metrics(bucket_events, min_sample=min_sample)
        row = {
            "dimension": dimension,
            "bucket": bucket,
            **metrics,
            **_delta_metrics(metrics, baseline),
        }
        row["verdict"] = _regime_verdict(row, min_sample=min_sample)
        row["note"] = _regime_note(row)
        rows.append(row)
    return sorted(rows, key=_regime_sort_key, reverse=True)


def _metrics(events: list[dict[str, Any]], *, min_sample: int) -> dict[str, Any]:
    counts = Counter(event["result_status"] for event in events)
    realized_events = [event for event in events if event.get("realized_r") is not None]
    realized_values = [float(event["realized_r"]) for event in realized_events]
    total_r = sum(realized_values)
    closed_count = len(realized_values)
    winrate_denominator = counts["TP_HIT"] + counts["SL_HIT"]
    return {
        "sample_count": len(events),
        "closed_count": closed_count,
        "tp_count": counts["TP_HIT"],
        "sl_count": counts["SL_HIT"],
        "both_hit_count": counts["BOTH_HIT_SAME_CANDLE"],
        "timeout_count": counts["TIMEOUT_CLOSE"],
        "waiting_count": counts["WAITING_DATA"],
        "positive_timeout_count": sum(
            1 for event in realized_events if event["result_status"] == "TIMEOUT_CLOSE" and float(event["realized_r"]) > 0
        ),
        "negative_timeout_count": sum(
            1 for event in realized_events if event["result_status"] == "TIMEOUT_CLOSE" and float(event["realized_r"]) < 0
        ),
        "total_r": total_r,
        "avg_r": (total_r / closed_count) if closed_count else None,
        "median_r": float(median(realized_values)) if realized_values else None,
        "winrate_pct": (counts["TP_HIT"] / winrate_denominator * 100) if winrate_denominator else None,
        "sl_share_pct": (counts["SL_HIT"] / closed_count * 100) if closed_count else None,
        "max_drawdown_r": _drawdown(realized_events)["max_drawdown_r"],
        "current_drawdown_r": _drawdown(realized_events)["current_drawdown_r"],
        "strategy_verdict": _strategy_verdict(
            sample_count=len(events),
            total_r=total_r,
            avg_r=(total_r / closed_count) if closed_count else None,
            median_r=float(median(realized_values)) if realized_values else None,
            min_sample=min_sample,
        ),
    }


def _delta_metrics(row: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "avg_r_delta_vs_baseline": _delta(row.get("avg_r"), baseline.get("avg_r")),
        "median_r_delta_vs_baseline": _delta(row.get("median_r"), baseline.get("median_r")),
        "winrate_delta_vs_baseline": _delta(row.get("winrate_pct"), baseline.get("winrate_pct")),
        "sl_share_delta_vs_baseline": _delta(row.get("sl_share_pct"), baseline.get("sl_share_pct")),
    }


def _delta(value: Any, baseline: Any) -> float | None:
    if value is None or baseline is None:
        return None
    return float(value) - float(baseline)


def _regime_verdict(row: dict[str, Any], *, min_sample: int) -> str:
    if int(row.get("closed_count") or 0) < min_sample:
        return "SAMPLE_TOO_SMALL"
    avg = row.get("avg_r")
    avg_delta = row.get("avg_r_delta_vs_baseline")
    win_delta = row.get("winrate_delta_vs_baseline")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    if avg is not None and avg_delta is not None and win_delta is not None and float(avg) > 0 and float(avg_delta) >= 0.15 and float(win_delta) >= 5:
        return "REGIME_HELPFUL"
    if avg_delta is not None and sl_delta is not None and float(avg_delta) > 0 and float(sl_delta) <= 0:
        return "REGIME_IMPROVES"
    if avg_delta is not None and float(avg_delta) <= -0.15:
        return "REGIME_BAD"
    return "REGIME_NOISY"


def _regime_note(row: dict[str, Any]) -> str:
    verdict = row.get("verdict")
    if verdict == "REGIME_HELPFUL":
        return "Regime ini memperbaiki avg R dan winrate dibanding baseline parameter yang sama."
    if verdict == "REGIME_IMPROVES":
        return "Regime ini lebih baik dari baseline, tapi pemisahan belum sangat kuat."
    if verdict == "REGIME_BAD":
        return "Regime ini lebih buruk dari baseline; kandidat kondisi yang harus dihindari."
    if verdict == "SAMPLE_TOO_SMALL":
        return "Sample belum cukup untuk dinilai."
    return "Belum memisahkan hasil secara bersih."


def _regime_sort_key(row: dict[str, Any]) -> tuple[int, float, float, int]:
    verdict_rank = {"REGIME_HELPFUL": 4, "REGIME_IMPROVES": 3, "REGIME_NOISY": 2, "SAMPLE_TOO_SMALL": 1, "REGIME_BAD": 0}
    return (
        verdict_rank.get(str(row.get("verdict")), 0),
        float(row.get("avg_r_delta_vs_baseline") or -999),
        float(row.get("total_r") or -999),
        int(row.get("sample_count") or 0),
    )


def _dependency_summary(stage: str, helpful: list[dict[str, Any]]) -> str:
    if not helpful:
        return "NO_CLEAR_REGIME_EDGE_YET"
    top = helpful[0]
    bucket = str(top.get("bucket", ""))
    dimension = str(top.get("dimension", ""))
    if stage.endswith("SHORT"):
        if "RISK_OFF" in bucket or "BEARISH" in bucket or "BREADTH_WEAK" in bucket:
            return f"SHORT_EDGE_APPEARS_BEAR_OR_WEAK_BREADTH_DEPENDENT via {dimension}={bucket}"
        if "RISK_ON" in bucket or "BULLISH" in bucket or "BREADTH_STRONG" in bucket:
            return f"SHORT_EDGE_NOT_ONLY_BEARISH_BUT_VERIFY via {dimension}={bucket}"
    if stage.endswith("LONG"):
        if "RISK_ON" in bucket or "BULLISH" in bucket or "BREADTH_STRONG" in bucket:
            return f"LONG_EDGE_APPEARS_BULL_OR_STRONG_BREADTH_DEPENDENT via {dimension}={bucket}"
        if "RISK_OFF" in bucket or "BEARISH" in bucket or "BREADTH_WEAK" in bucket:
            return f"LONG_EDGE_NOT_ONLY_BULLISH_BUT_VERIFY via {dimension}={bucket}"
    return f"REGIME_DEPENDENCY_MIXED via {dimension}={bucket}"
