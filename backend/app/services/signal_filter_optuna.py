from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import (
    COMPLETED_OUTCOMES,
    SignalCandidatePerformanceService,
    _parse_dt,
)
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import json_safe


DEFAULT_ARTIFACT_DIR = REPO_ROOT / "backend" / "artifacts" / "signal_filter_optuna" / "v1"
DEFAULT_DOC_PATH = REPO_ROOT / "backend" / "docs" / "signal_filter_optuna_v1.md"

LANES = {
    "MID_SHORT_1H": {
        "stage": "MID_SHORT",
        "timeframe": "1h",
        "direction": "SHORT",
        "min_train_closed": 25,
        "min_validation_closed": 10,
    },
    "MID_LONG_1H": {
        "stage": "MID_LONG",
        "timeframe": "1h",
        "direction": "LONG",
        "min_train_closed": 35,
        "min_validation_closed": 12,
    },
}

SEARCH_FIELDS = {
    "price_return": "Price return %",
    "volume_ratio_vs_lookback": "Volume vs avg",
    "range_ratio_vs_atr": "Range / ATR",
    "atr_extension_normalized": "ATR extension",
    "price_atr_multiple": "Price ATR multiple",
    "kline_taker_buy_ratio": "Taker buy ratio",
    "kline_taker_sell_ratio": "Taker sell ratio",
    "oi_change_pct": "OI change %",
    "oi_zscore": "OI z-score",
    "funding_percentile_30d": "Funding percentile",
    "futures_spread_pct": "Futures spread %",
    "spot_spread_pct": "Spot spread %",
    "global_long_short_ratio": "Global long/short",
    "top_trader_position_ratio": "Top trader position",
    "top_trader_account_ratio": "Top trader account",
    "core_score": "Core score",
    "evidence_score": "Evidence score",
}

MODE_CHOICES = ("ANY", "GE", "LE", "BETWEEN")
MAX_ACTIVE_FILTERS = 5


@dataclass(frozen=True)
class FieldBounds:
    field: str
    label: str
    low: float
    high: float
    available_count: int
    missing_count: int


class SignalFilterOptunaRunner:
    """Read-only Optuna filter discovery on logged Signal Candidate outcomes."""

    def __init__(
        self,
        db: Session,
        *,
        artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
        doc_path: Path = DEFAULT_DOC_PATH,
        trials: int = 200,
        seed: int = 42,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        top_trials: int = 20,
    ) -> None:
        self.db = db
        self.artifact_dir = artifact_dir
        self.doc_path = doc_path
        self.trials = trials
        self.seed = seed
        self.epoch = epoch
        self.include_watch_only = include_watch_only
        self.position_lock = position_lock
        self.top_trials = top_trials

    def run(self) -> dict[str, Any]:
        optuna = import_optuna()
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        lane_results: dict[str, Any] = {}
        for lane_name, config in LANES.items():
            lane_results[lane_name] = self._run_lane(optuna, lane_name, config)
        payload = {
            "generated_at": generated_at,
            "trials": self.trials,
            "seed": self.seed,
            "epoch": self.epoch,
            "include_watch_only": self.include_watch_only,
            "position_lock": self.position_lock,
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "method": "Optuna filter discovery over Signal Candidate forward logs with time split validation",
            "lanes": lane_results,
            "guardrails": [
                "No Signal Factory rule changed.",
                "No scanner behavior changed.",
                "No outcome calculation changed.",
                "No live signal, order, execution, final TP/SL, leverage, or position sizing is created.",
                "Validation is by time split; promising filters remain research-only until forward validation.",
            ],
        }
        self.write_outputs(payload)
        return payload

    def _run_lane(self, optuna: Any, lane_name: str, config: dict[str, Any]) -> dict[str, Any]:
        raw_items, skipped, latest_candle = self._load_lane_items(config)
        raw_items = sorted(raw_items, key=lambda item: (_item_time(item) or datetime.min, str(item.get("symbol"))))
        baseline_items, baseline_lock_skipped = apply_position_lock(raw_items) if self.position_lock else (raw_items, 0)
        if not raw_items:
            return {
                "status": "NO_DATA",
                "lane": lane_name,
                "stage": config["stage"],
                "timeframe": config["timeframe"],
                "direction": config["direction"],
                "raw_count": len(raw_items),
                "sample_count": 0,
                "lock_skipped": baseline_lock_skipped,
                "load_skipped": dict(skipped),
                "latest_futures_15m_close_time": latest_candle,
            }

        split_index = max(1, int(len(raw_items) * Decimal("0.70")))
        train_raw_items = raw_items[:split_index]
        validation_raw_items = raw_items[split_index:]
        train_baseline_items, train_lock_skipped = apply_position_lock(train_raw_items) if self.position_lock else (train_raw_items, 0)
        validation_baseline_items, validation_lock_skipped = (
            apply_position_lock(validation_raw_items) if self.position_lock else (validation_raw_items, 0)
        )
        bounds = build_field_bounds(train_raw_items)
        baseline_all = evaluate_items(baseline_items, direction=config["direction"])
        baseline_train = evaluate_items(train_baseline_items, direction=config["direction"])
        baseline_validation = evaluate_items(validation_baseline_items, direction=config["direction"])
        min_train = int(config["min_train_closed"])
        min_validation = int(config["min_validation_closed"])

        if not bounds:
            return {
                "status": "NO_SEARCH_FIELDS",
                "lane": lane_name,
                "stage": config["stage"],
                "timeframe": config["timeframe"],
                "direction": config["direction"],
                "raw_count": len(raw_items),
                "sample_count": len(baseline_items),
                "lock_skipped": baseline_lock_skipped,
                "train_lock_skipped": train_lock_skipped,
                "validation_lock_skipped": validation_lock_skipped,
                "load_skipped": dict(skipped),
                "latest_futures_15m_close_time": latest_candle,
                "baseline_all": baseline_all,
                "baseline_train": baseline_train,
                "baseline_validation": baseline_validation,
            }

        def objective(trial: Any) -> float:
            rule = suggest_rule(trial, bounds)
            active_filters = active_filter_count(rule)
            if active_filters < 1 or active_filters > MAX_ACTIVE_FILTERS:
                return -900.0 - active_filters
            selected_raw = apply_rule(train_raw_items, rule)
            selected, _selected_skipped = apply_position_lock(selected_raw) if self.position_lock else (selected_raw, 0)
            metrics = evaluate_items(selected, direction=config["direction"])
            if metrics["closed_count"] < min_train:
                return -1000.0 + (metrics["closed_count"] / max(min_train, 1))
            return objective_score(metrics, baseline_train, active_filters)

        sampler = optuna.samplers.TPESampler(seed=self.seed)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=self.trials, show_progress_bar=False)

        top_candidates = []
        for trial in sorted(study.trials, key=lambda item: item.value if item.value is not None else -9999, reverse=True)[: self.top_trials]:
            rule = rule_from_params(trial.params, bounds)
            top_candidates.append(
                evaluate_rule_candidate(
                    rule=rule,
                    train_items=train_raw_items,
                    validation_items=validation_raw_items,
                    all_items=raw_items,
                    direction=config["direction"],
                    baseline_train=baseline_train,
                    baseline_validation=baseline_validation,
                    baseline_all=baseline_all,
                    min_validation_closed=min_validation,
                    objective_value=trial.value,
                    position_lock=self.position_lock,
                )
            )

        best = top_candidates[0] if top_candidates else None
        return {
            "status": "COMPLETE",
            "lane": lane_name,
            "stage": config["stage"],
            "timeframe": config["timeframe"],
            "direction": config["direction"],
            "raw_count": len(raw_items),
            "sample_count": len(baseline_items),
            "train_count": len(train_baseline_items),
            "validation_count": len(validation_baseline_items),
            "lock_skipped": baseline_lock_skipped,
            "train_lock_skipped": train_lock_skipped,
            "validation_lock_skipped": validation_lock_skipped,
            "load_skipped": dict(skipped),
            "latest_futures_15m_close_time": latest_candle,
            "min_train_closed": min_train,
            "min_validation_closed": min_validation,
            "search_fields": [field.__dict__ for field in bounds],
            "baseline_all": baseline_all,
            "baseline_train": baseline_train,
            "baseline_validation": baseline_validation,
            "best_objective": study.best_value,
            "best_rule": best["rule"] if best else None,
            "best_candidate": best,
            "top_candidates": top_candidates,
            "interpretation": interpret_lane(lane_name, best, baseline_validation),
        }

    def _load_lane_items(self, config: dict[str, Any]) -> tuple[list[dict[str, Any]], Counter[str], datetime | None]:
        service = SignalCandidatePerformanceService(self.db)
        return service._evaluated_context(  # noqa: SLF001 - shared read-only evaluator used intentionally.
            epoch=self.epoch,
            include_watch_only=self.include_watch_only,
            stage=str(config["stage"]),
            timeframe=str(config["timeframe"]),
            position_lock=False,
        )

    def write_outputs(self, payload: dict[str, Any]) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.joinpath("results.json").write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")
        self.doc_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_path.write_text(render_markdown(payload), encoding="utf-8")


def import_optuna() -> Any:
    try:
        import optuna  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("Optuna is required for signal filter research. Install backend requirements first.") from exc
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    return optuna


def suggest_rule(trial: Any, bounds: list[FieldBounds]) -> dict[str, Any]:
    return {
        "conditions": [
            _suggest_condition(trial, bound)
            for bound in bounds
        ]
    }


def _suggest_condition(trial: Any, bound: FieldBounds) -> dict[str, Any]:
    use_field = trial.suggest_categorical(f"{bound.field}_use", [False, False, True])
    mode = trial.suggest_categorical(f"{bound.field}_mode", ("GE", "LE", "BETWEEN")) if use_field else "ANY"
    condition: dict[str, Any] = {"field": bound.field, "label": bound.label, "mode": mode}
    if mode == "GE":
        condition["min"] = trial.suggest_float(f"{bound.field}_min", bound.low, bound.high)
    elif mode == "LE":
        condition["max"] = trial.suggest_float(f"{bound.field}_max", bound.low, bound.high)
    elif mode == "BETWEEN":
        first = trial.suggest_float(f"{bound.field}_between_a", bound.low, bound.high)
        second = trial.suggest_float(f"{bound.field}_between_b", bound.low, bound.high)
        condition["min"] = min(first, second)
        condition["max"] = max(first, second)
    return condition


def rule_from_params(params: dict[str, Any], bounds: list[FieldBounds]) -> dict[str, Any]:
    conditions = []
    for bound in bounds:
        use_field = bool(params.get(f"{bound.field}_use", params.get(f"{bound.field}_mode", "ANY") != "ANY"))
        mode = str(params.get(f"{bound.field}_mode", "ANY")) if use_field else "ANY"
        condition: dict[str, Any] = {"field": bound.field, "label": bound.label, "mode": mode}
        if mode == "GE":
            condition["min"] = float(params[f"{bound.field}_min"])
        elif mode == "LE":
            condition["max"] = float(params[f"{bound.field}_max"])
        elif mode == "BETWEEN":
            first = float(params[f"{bound.field}_between_a"])
            second = float(params[f"{bound.field}_between_b"])
            condition["min"] = min(first, second)
            condition["max"] = max(first, second)
        conditions.append(condition)
    return {"conditions": conditions}


def apply_rule(items: list[dict[str, Any]], rule: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in items if item_matches_rule(item, rule)]


def item_matches_rule(item: dict[str, Any], rule: dict[str, Any]) -> bool:
    evidence = item.get("evidence_snapshot") or {}
    for condition in rule.get("conditions", []):
        mode = condition.get("mode", "ANY")
        if mode == "ANY":
            continue
        value = evidence.get(condition["field"])
        if value is None:
            return False
        numeric = float(value)
        if mode == "GE" and numeric < float(condition["min"]):
            return False
        if mode == "LE" and numeric > float(condition["max"]):
            return False
        if mode == "BETWEEN" and not (float(condition["min"]) <= numeric <= float(condition["max"])):
            return False
    return True


def apply_position_lock(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    selected: list[dict[str, Any]] = []
    skipped = 0
    locked_until: dict[str, datetime | None] = {}
    for item in sorted(items, key=lambda row: (_item_time(row) or datetime.min, str(row.get("symbol")))):
        symbol = str(item.get("symbol") or "")
        signal_time = _item_time(item)
        lock_time = locked_until.get(symbol)
        if symbol in locked_until and (lock_time is None or (signal_time is not None and signal_time < lock_time)):
            skipped += 1
            continue
        selected.append(item)
        if item.get("result_status") in COMPLETED_OUTCOMES and item.get("result_time_utc"):
            locked_until[symbol] = _parse_dt(item.get("result_time_utc"))
        else:
            locked_until[symbol] = None
    return selected, skipped


def evaluate_rule_candidate(
    *,
    rule: dict[str, Any],
    train_items: list[dict[str, Any]],
    validation_items: list[dict[str, Any]],
    all_items: list[dict[str, Any]],
    direction: str,
    baseline_train: dict[str, Any],
    baseline_validation: dict[str, Any],
    baseline_all: dict[str, Any],
    min_validation_closed: int,
    objective_value: float | None,
    position_lock: bool,
) -> dict[str, Any]:
    train_selected_raw = apply_rule(train_items, rule)
    validation_selected_raw = apply_rule(validation_items, rule)
    all_selected_raw = apply_rule(all_items, rule)
    train_selected, train_lock_skipped = apply_position_lock(train_selected_raw) if position_lock else (train_selected_raw, 0)
    validation_selected, validation_lock_skipped = (
        apply_position_lock(validation_selected_raw) if position_lock else (validation_selected_raw, 0)
    )
    all_selected, all_lock_skipped = apply_position_lock(all_selected_raw) if position_lock else (all_selected_raw, 0)
    train_metrics = evaluate_items(train_selected, direction=direction)
    validation_metrics = evaluate_items(validation_selected, direction=direction)
    all_metrics = evaluate_items(all_selected, direction=direction)
    validation_status = validation_verdict(validation_metrics, baseline_validation, min_validation_closed)
    return {
        "objective_value": objective_value,
        "active_filter_count": active_filter_count(rule),
        "rule": compact_rule(rule),
        "lock_skipped": {
            "train": train_lock_skipped,
            "validation": validation_lock_skipped,
            "all": all_lock_skipped,
        },
        "train_metrics": with_deltas(train_metrics, baseline_train),
        "validation_metrics": with_deltas(validation_metrics, baseline_validation),
        "all_metrics": with_deltas(all_metrics, baseline_all),
        "validation_status": validation_status,
    }


def evaluate_items(items: list[dict[str, Any]], *, direction: str) -> dict[str, Any]:
    status_counts = Counter(str(item.get("result_status") or "UNKNOWN") for item in items)
    closed = [item for item in items if item.get("result_status") in COMPLETED_OUTCOMES and item.get("realized_r") is not None]
    tp_count = status_counts.get("TP_HIT", 0)
    sl_count = status_counts.get("SL_HIT", 0)
    both_count = status_counts.get("BOTH_HIT_SAME_CANDLE", 0)
    realized_values = [float(item["realized_r"]) for item in closed if _finite(item.get("realized_r"))]
    symbols = Counter(str(item.get("symbol") or "UNKNOWN") for item in items)
    top_symbol, top_count = symbols.most_common(1)[0] if symbols else ("-", 0)
    win_denominator = tp_count + sl_count
    total_r = sum(realized_values)
    max_dd = max_drawdown(closed)
    return {
        "sample_count": len(items),
        "closed_count": len(closed),
        "tp_count": tp_count,
        "sl_count": sl_count,
        "both_hit_count": both_count,
        "open_count": status_counts.get("OPEN", 0),
        "waiting_count": status_counts.get("WAITING_DATA", 0),
        "winrate_pct": (tp_count / win_denominator * 100) if win_denominator else None,
        "sl_share_pct": (sl_count / win_denominator * 100) if win_denominator else None,
        "total_r_closed": total_r,
        "avg_r_closed": (total_r / len(realized_values)) if realized_values else None,
        "median_r_closed": median(realized_values) if realized_values else None,
        "max_drawdown_r": max_dd,
        "top_symbol": top_symbol,
        "top_symbol_count": top_count,
        "top_symbol_share_pct": (top_count / len(items) * 100) if items else None,
        "symbol_count": len(symbols),
        "direction": direction,
    }


def with_deltas(metrics: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    output = dict(metrics)
    output["avg_r_delta_vs_baseline"] = _delta(metrics.get("avg_r_closed"), baseline.get("avg_r_closed"))
    output["winrate_delta_vs_baseline"] = _delta(metrics.get("winrate_pct"), baseline.get("winrate_pct"))
    output["sl_share_delta_vs_baseline"] = _delta(metrics.get("sl_share_pct"), baseline.get("sl_share_pct"))
    output["total_r_delta_vs_baseline"] = _delta(metrics.get("total_r_closed"), baseline.get("total_r_closed"))
    return output


def objective_score(metrics: dict[str, Any], baseline: dict[str, Any], active_filters: int) -> float:
    avg_r = float(metrics.get("avg_r_closed") or -1.0)
    baseline_avg = float(baseline.get("avg_r_closed") or 0.0)
    winrate = float(metrics.get("winrate_pct") or 0.0)
    sl_share = float(metrics.get("sl_share_pct") or 100.0)
    max_dd = abs(float(metrics.get("max_drawdown_r") or 0.0))
    top_share = float(metrics.get("top_symbol_share_pct") or 100.0) / 100.0
    closed = float(metrics.get("closed_count") or 0.0)
    open_share = (float(metrics.get("open_count") or 0.0) / max(float(metrics.get("sample_count") or 1.0), 1.0))
    sample_bonus = min(closed / 80.0, 1.0) * 0.25
    improvement = avg_r - baseline_avg
    return (
        avg_r * 1.5
        + improvement * 1.2
        + ((winrate - 40.0) / 100.0) * 0.8
        - ((sl_share - 50.0) / 100.0) * 0.5
        - max_dd * 0.025
        - top_share * 0.7
        - open_share * 0.2
        + sample_bonus
        - active_filters * 0.035
    )


def validation_verdict(metrics: dict[str, Any], baseline: dict[str, Any], min_closed: int) -> str:
    if int(metrics.get("closed_count") or 0) < min_closed:
        return "VALIDATION_SAMPLE_TOO_SMALL"
    if float(metrics.get("top_symbol_share_pct") or 100.0) > 25.0:
        return "CONCENTRATION_WARNING"
    avg_delta = metrics.get("avg_r_delta_vs_baseline")
    win_delta = metrics.get("winrate_delta_vs_baseline")
    sl_delta = metrics.get("sl_share_delta_vs_baseline")
    if (metrics.get("avg_r_closed") or 0) <= 0:
        return "VALIDATION_AVG_R_NOT_POSITIVE"
    if avg_delta is not None and avg_delta >= 0.10 and win_delta is not None and win_delta >= 3:
        return "VALIDATION_PROMISING_READONLY"
    if avg_delta is not None and avg_delta > 0 and sl_delta is not None and sl_delta <= 0:
        return "VALIDATION_REDUCES_DAMAGE"
    if avg_delta is not None and avg_delta < 0:
        return "VALIDATION_WORSE_THAN_BASELINE"
    return "VALIDATION_NOISY"


def build_field_bounds(items: list[dict[str, Any]], *, min_available: int = 15) -> list[FieldBounds]:
    bounds = []
    total = len(items)
    for field, label in SEARCH_FIELDS.items():
        values = sorted(
            float(value)
            for item in items
            if (value := (item.get("evidence_snapshot") or {}).get(field)) is not None and _finite(value)
        )
        unique_values = set(round(value, 10) for value in values)
        if len(values) < min_available or len(unique_values) < 3:
            continue
        low = percentile(values, 0.05)
        high = percentile(values, 0.95)
        if not math.isfinite(low) or not math.isfinite(high) or low == high:
            continue
        bounds.append(
            FieldBounds(
                field=field,
                label=label,
                low=low,
                high=high,
                available_count=len(values),
                missing_count=total - len(values),
            )
        )
    return bounds


def compact_rule(rule: dict[str, Any]) -> dict[str, Any]:
    conditions = []
    for condition in rule.get("conditions", []):
        if condition.get("mode") == "ANY":
            continue
        compacted = {
            "field": condition["field"],
            "label": condition["label"],
            "mode": condition["mode"],
        }
        if "min" in condition:
            compacted["min"] = round(float(condition["min"]), 6)
        if "max" in condition:
            compacted["max"] = round(float(condition["max"]), 6)
        conditions.append(compacted)
    return {"conditions": conditions}


def active_filter_count(rule: dict[str, Any]) -> int:
    return sum(1 for condition in rule.get("conditions", []) if condition.get("mode") != "ANY")


def max_drawdown(closed_items: list[dict[str, Any]]) -> float:
    ordered = sorted(
        closed_items,
        key=lambda item: (_parse_dt(item.get("result_time_utc")) or _parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol"))),
    )
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for item in ordered:
        cumulative += float(item.get("realized_r") or 0.0)
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative - peak)
    return max_dd


def interpret_lane(lane_name: str, best: dict[str, Any] | None, baseline_validation: dict[str, Any]) -> str:
    if not best:
        return f"{lane_name}: no Optuna candidate generated."
    status = best["validation_status"]
    if status == "VALIDATION_PROMISING_READONLY":
        return f"{lane_name}: Optuna found a research-only filter that improves validation; keep paper-monitoring before any rule change."
    if status == "VALIDATION_REDUCES_DAMAGE":
        return f"{lane_name}: best filter improves damage profile but is not strong enough for rule promotion."
    if status == "VALIDATION_SAMPLE_TOO_SMALL":
        return f"{lane_name}: selected validation sample is too small."
    if status == "CONCENTRATION_WARNING":
        return f"{lane_name}: selected subset is too concentrated in one symbol."
    if status == "VALIDATION_WORSE_THAN_BASELINE":
        return f"{lane_name}: best train filter weakens on validation; likely overfit or noisy."
    return f"{lane_name}: no clean validation separation yet."


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * p
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _item_time(item: dict[str, Any]) -> datetime | None:
    return _parse_dt(item.get("signal_timestamp"))


def _delta(value: Any, baseline: Any) -> float | None:
    if value is None or baseline is None:
        return None
    return float(value) - float(baseline)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Signal Filter Optuna v1",
        "",
        "Read-only Optuna filter discovery for logged Signal Candidate outcomes. This report does not change live rules, classifier rules, scanner behavior, outcome logic, TP/SL, execution, or strategy.",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- trials_per_lane: `{payload['trials']}`",
        f"- position_lock: `{payload['position_lock']}`",
        f"- method: `{payload['method']}`",
        "",
        "## Executive Verdict",
        "",
        "The study runs MID_SHORT 1h and MID_LONG 1h as separate lanes. Any promising output is a research filter only and must be forward-validated before promotion.",
        "",
        "## Lane Summary",
        "",
        "| lane | status | sample | baseline val avg R | best val avg R | val TP/SL | val status | active filters |",
        "|---|---|---:|---:|---:|---:|---|---:|",
    ]
    for lane, result in payload["lanes"].items():
        if result.get("status") != "COMPLETE":
            lines.append(f"| {lane} | {result.get('status')} | {result.get('sample_count', 0)} | n/a | n/a | n/a | n/a | 0 |")
            continue
        best = result.get("best_candidate") or {}
        validation = best.get("validation_metrics") or {}
        baseline = result.get("baseline_validation") or {}
        lines.append(
            f"| {lane} | {result['status']} | {result['sample_count']} | "
            f"{fmt(baseline.get('avg_r_closed'))} | {fmt(validation.get('avg_r_closed'))} | "
            f"{validation.get('tp_count', 0)}/{validation.get('sl_count', 0)} | "
            f"{best.get('validation_status')} | {best.get('active_filter_count', 0)} |"
        )
    lines.extend(["", "## Best Rules", ""])
    for lane, result in payload["lanes"].items():
        lines.append(f"### {lane}")
        if result.get("status") != "COMPLETE":
            lines.extend(["", f"- status: `{result.get('status')}`", ""])
            continue
        best = result.get("best_candidate") or {}
        lines.extend(
            [
                "",
                f"- interpretation: {result.get('interpretation')}",
                f"- validation_status: `{best.get('validation_status')}`",
                f"- validation avg R: `{fmt((best.get('validation_metrics') or {}).get('avg_r_closed'))}`",
                f"- validation total R: `{fmt((best.get('validation_metrics') or {}).get('total_r_closed'))}`",
                f"- validation winrate: `{fmt((best.get('validation_metrics') or {}).get('winrate_pct'))}%`",
                f"- validation max drawdown R: `{fmt((best.get('validation_metrics') or {}).get('max_drawdown_r'))}`",
                "",
                "Rule:",
                "",
                "```json",
                json.dumps(json_safe(best.get("rule") or {}), indent=2),
                "```",
                "",
                "Top 5 candidates:",
                "",
                "| rank | validation status | val sample | val avg R | val TP/SL | avg R delta | rule filters |",
                "|---:|---|---:|---:|---:|---:|---|",
            ]
        )
        for index, candidate in enumerate(result.get("top_candidates", [])[:5], start=1):
            validation = candidate.get("validation_metrics") or {}
            rule_filters = "; ".join(_rule_condition_text(condition) for condition in (candidate.get("rule") or {}).get("conditions", [])) or "none"
            lines.append(
                f"| {index} | {candidate.get('validation_status')} | {validation.get('sample_count', 0)} | "
                f"{fmt(validation.get('avg_r_closed'))} | {validation.get('tp_count', 0)}/{validation.get('sl_count', 0)} | "
                f"{fmt(validation.get('avg_r_delta_vs_baseline'))} | {rule_filters} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Guardrails",
            "",
            "- No runtime rule changed.",
            "- No classifier, scanner, Signal Factory, Strategy Arena, Phase 6, or Phase 7 gate changed.",
            "- No live signal, order, execution, final TP/SL, leverage, or position sizing is created.",
            "- Use this only to decide which filters deserve forward monitoring.",
            "",
        ]
    )
    return "\n".join(lines)


def _rule_condition_text(condition: dict[str, Any]) -> str:
    field = condition.get("field")
    mode = condition.get("mode")
    if mode == "GE":
        return f"{field}>={fmt(condition.get('min'))}"
    if mode == "LE":
        return f"{field}<={fmt(condition.get('max'))}"
    if mode == "BETWEEN":
        return f"{fmt(condition.get('min'))}<={field}<={fmt(condition.get('max'))}"
    return str(field)


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"
