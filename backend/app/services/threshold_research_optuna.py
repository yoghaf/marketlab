from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Callable

from app.services.multitimeframe_features import DEFAULT_DB_PATH, REPO_ROOT, json_safe


DEFAULT_ARTIFACT_DIR = REPO_ROOT / "backend" / "artifacts" / "threshold_research" / "optuna_v1"
DEFAULT_DOC_PATH = REPO_ROOT / "backend" / "docs" / "threshold_research_optuna_v1.md"

SETUPS = {
    "EARLY_LONG": {"candidate_type": "EARLY_LONG_CANDIDATE_READONLY", "direction": "LONG", "min_train": 40, "min_validation": 20},
    "EARLY_SHORT": {"candidate_type": "EARLY_SHORT_CANDIDATE_READONLY", "direction": "SHORT", "min_train": 40, "min_validation": 20},
    "MID_LONG": {"candidate_type": "MID_LONG_CONTEXT_READONLY", "direction": "LONG", "min_train": 100, "min_validation": 40},
    "MID_SHORT": {"candidate_type": "MID_SHORT_CONTEXT_READONLY", "direction": "SHORT", "min_train": 100, "min_validation": 40},
}


@dataclass(frozen=True)
class ThresholdRow:
    symbol: str
    window_close_time: str
    candidate_type: str
    direction: str
    price_return_pct_15m: float | None
    close_position_15m: float | None
    taker_buy_ratio_15m: float | None
    taker_sell_ratio_15m: float | None
    oi_change_pct_15m: float | None
    futures_led_score_15m: float | None
    spot_support_score_15m: float | None
    spot_futures_volume_ratio_15m: float | None
    spot_missing_flag_15m: bool | None
    spot_support_status_15m: str | None
    global_long_short_ratio_15m: float | None
    top_trader_position_ratio_15m: float | None
    funding_rate: float | None
    futures_spread_pct: float | None
    price_return_pct_1h: float | None
    taker_buy_ratio_1h: float | None
    oi_change_pct_1h: float | None
    future_return_4h: float
    max_favorable_move_4h: float | None
    max_adverse_move_4h: float | None


class OptunaThresholdResearchRunner:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
        doc_path: Path = DEFAULT_DOC_PATH,
        trials: int = 200,
        seed: int = 42,
    ) -> None:
        self.db_path = db_path
        self.artifact_dir = artifact_dir
        self.doc_path = doc_path
        self.trials = trials
        self.seed = seed

    def run(self) -> dict[str, Any]:
        optuna = import_optuna()
        rows = load_rows(self.db_path)
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        setup_results = {}
        for setup_name, config in SETUPS.items():
            setup_rows = [row for row in rows if row.candidate_type == config["candidate_type"]]
            setup_results[setup_name] = self._optimize_setup(optuna, setup_name, config, setup_rows)

        payload = {
            "generated_at": generated_at,
            "db_path": str(self.db_path),
            "trials": self.trials,
            "seed": self.seed,
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "method": "Optuna threshold search with time split validation",
            "setups": setup_results,
            "guardrails": [
                "This research does not change scanner, classifier, Phase 6, Phase 7, or Strategy Arena rules.",
                "Threshold candidates are read-only and must be forward-validated before any gate change.",
                "Trials with insufficient train/validation sample are penalized.",
                "Symbol concentration is penalized.",
            ],
        }
        self.write_outputs(payload)
        return payload

    def _optimize_setup(self, optuna: Any, setup_name: str, config: dict[str, Any], rows: list[ThresholdRow]) -> dict[str, Any]:
        if not rows:
            return {"status": "NO_DATA", "row_count": 0}
        rows = sorted(rows, key=lambda row: row.window_close_time)
        split_index = max(1, int(len(rows) * 0.70))
        train_rows = rows[:split_index]
        validation_rows = rows[split_index:]
        direction = config["direction"]
        min_train = int(config["min_train"])
        min_validation = int(config["min_validation"])
        search_space = build_search_space(rows, direction)

        def objective(trial: Any) -> float:
            rule = suggest_rule(trial, direction, search_space)
            selected = apply_rule(train_rows, rule)
            metrics = evaluate_rows(selected, direction)
            if metrics["sample_count"] < min_train:
                return -1000.0 + metrics["sample_count"] / max(min_train, 1)
            return objective_score(metrics)

        sampler = optuna.samplers.TPESampler(seed=self.seed)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=self.trials, show_progress_bar=False)

        best_rule = suggest_rule_from_params(study.best_trial.params, direction, search_space)
        train_selected = apply_rule(train_rows, best_rule)
        validation_selected = apply_rule(validation_rows, best_rule)
        all_selected = apply_rule(rows, best_rule)
        train_metrics = evaluate_rows(train_selected, direction)
        validation_metrics = evaluate_rows(validation_selected, direction)
        all_metrics = evaluate_rows(all_selected, direction)
        validation_status = validation_verdict(validation_metrics, min_validation)
        return {
            "status": "COMPLETE",
            "setup_name": setup_name,
            "candidate_type": config["candidate_type"],
            "direction": direction,
            "row_count": len(rows),
            "train_count": len(train_rows),
            "validation_count": len(validation_rows),
            "min_train_sample": min_train,
            "min_validation_sample": min_validation,
            "best_objective": study.best_value,
            "best_params": study.best_trial.params,
            "threshold_rule": best_rule,
            "baseline_all": evaluate_rows(rows, direction),
            "train_metrics": train_metrics,
            "validation_metrics": validation_metrics,
            "all_selected_metrics": all_metrics,
            "validation_status": validation_status,
            "interpretation": interpret_setup(setup_name, all_metrics, validation_metrics, validation_status),
        }

    def write_outputs(self, payload: dict[str, Any]) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.joinpath("results.json").write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")
        self.doc_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_path.write_text(render_markdown(payload), encoding="utf-8")


def import_optuna() -> Any:
    try:
        import optuna  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("Optuna is required for threshold research. Install backend requirements first.") from exc
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    return optuna


def load_rows(db_path: Path) -> list[ThresholdRow]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT c.symbol, c.window_close_time, c.candidate_type, c.candidate_direction,
                   ctx.price_return_pct_15m, ctx.close_position_15m,
                   ctx.kline_taker_buy_ratio_15m, (1 - ctx.kline_taker_buy_ratio_15m) AS taker_sell_ratio_15m,
                   ctx.oi_change_pct_15m, ctx.futures_led_score_15m, ctx.spot_support_score_15m,
                   ctx.spot_futures_volume_ratio_15m, ctx.spot_missing_flag_15m, ctx.spot_support_status_15m,
                   ctx.global_long_short_ratio_15m, ctx.top_trader_position_ratio_15m,
                   f.funding_rate, f.futures_spread_pct,
                   ctx.price_return_pct_1h, ctx.kline_taker_buy_ratio_1h, ctx.oi_change_pct_1h,
                   o.future_return_4h, o.max_favorable_move_4h, o.max_adverse_move_4h
            FROM market_signal_candidates_readonly_15m c
            JOIN market_candidate_outcomes_15m o
              ON o.symbol = c.symbol
             AND o.candidate_window_open_time = c.window_open_time
             AND o.candidate_window_close_time = c.window_close_time
             AND o.candidate_type = c.candidate_type
             AND o.outcome_status = 'OUTCOME_READY'
            LEFT JOIN market_feature_context_15m_1h ctx
              ON ctx.symbol = c.symbol
             AND ctx.feature_15m_window_open_time = c.window_open_time
             AND ctx.feature_15m_window_close_time = c.window_close_time
            LEFT JOIN market_features_15m f
              ON f.symbol = c.symbol
             AND f.window_open_time = c.window_open_time
             AND f.window_close_time = c.window_close_time
            WHERE c.candidate_type IN (
                'EARLY_LONG_CANDIDATE_READONLY',
                'EARLY_SHORT_CANDIDATE_READONLY',
                'MID_LONG_CONTEXT_READONLY',
                'MID_SHORT_CONTEXT_READONLY'
            )
              AND o.future_return_4h IS NOT NULL
            ORDER BY c.window_close_time, c.symbol
            """
        ).fetchall()
    return [row_from_db(row) for row in rows]


def row_from_db(row: sqlite3.Row) -> ThresholdRow:
    return ThresholdRow(
        symbol=row["symbol"],
        window_close_time=str(row["window_close_time"]),
        candidate_type=row["candidate_type"],
        direction=row["candidate_direction"],
        price_return_pct_15m=flt(row["price_return_pct_15m"]),
        close_position_15m=flt(row["close_position_15m"]),
        taker_buy_ratio_15m=flt(row["kline_taker_buy_ratio_15m"]),
        taker_sell_ratio_15m=flt(row["taker_sell_ratio_15m"]),
        oi_change_pct_15m=flt(row["oi_change_pct_15m"]),
        futures_led_score_15m=flt(row["futures_led_score_15m"]),
        spot_support_score_15m=flt(row["spot_support_score_15m"]),
        spot_futures_volume_ratio_15m=flt(row["spot_futures_volume_ratio_15m"]),
        spot_missing_flag_15m=bool(row["spot_missing_flag_15m"]) if row["spot_missing_flag_15m"] is not None else None,
        spot_support_status_15m=row["spot_support_status_15m"],
        global_long_short_ratio_15m=flt(row["global_long_short_ratio_15m"]),
        top_trader_position_ratio_15m=flt(row["top_trader_position_ratio_15m"]),
        funding_rate=flt(row["funding_rate"]),
        futures_spread_pct=flt(row["futures_spread_pct"]),
        price_return_pct_1h=flt(row["price_return_pct_1h"]),
        taker_buy_ratio_1h=flt(row["kline_taker_buy_ratio_1h"]),
        oi_change_pct_1h=flt(row["oi_change_pct_1h"]),
        future_return_4h=float(row["future_return_4h"]),
        max_favorable_move_4h=flt(row["max_favorable_move_4h"]),
        max_adverse_move_4h=flt(row["max_adverse_move_4h"]),
    )


def build_search_space(rows: list[ThresholdRow], direction: str) -> dict[str, tuple[float, float]]:
    def bounds(field: str, default: tuple[float, float]) -> tuple[float, float]:
        values = sorted(value for row in rows if (value := getattr(row, field)) is not None and math.isfinite(value))
        if len(values) < 5:
            return default
        low = percentile(values, 0.10)
        high = percentile(values, 0.90)
        if low == high:
            return default
        return (low, high)

    if direction == "LONG":
        price_default = (0.0, 2.0)
        context_default = (-1.0, 2.0)
        close_default = (0.55, 0.98)
        taker_default = (0.50, 0.72)
    else:
        price_default = (-2.0, 0.0)
        context_default = (-3.0, 1.0)
        close_default = (0.02, 0.45)
        taker_default = (0.50, 0.72)
    return {
        "price_return_pct_15m": bounds("price_return_pct_15m", price_default),
        "close_position_15m": bounds("close_position_15m", close_default),
        "taker_ratio_15m": bounds("taker_buy_ratio_15m" if direction == "LONG" else "taker_sell_ratio_15m", taker_default),
        "oi_change_pct_15m": bounds("oi_change_pct_15m", (-0.5, 0.5)),
        "futures_led_score_15m": bounds("futures_led_score_15m", (0.0, 1.0)),
        "spot_support_score_15m": bounds("spot_support_score_15m", (0.0, 1.0)),
        "price_return_pct_1h": bounds("price_return_pct_1h", context_default),
        "futures_spread_pct": bounds("futures_spread_pct", (0.0, 0.10)),
    }


def suggest_rule(trial: Any, direction: str, space: dict[str, tuple[float, float]]) -> dict[str, Any]:
    if direction == "LONG":
        price = trial.suggest_float("price_return_min_15m", *space["price_return_pct_15m"])
        close = trial.suggest_float("close_position_min_15m", *space["close_position_15m"])
        context = trial.suggest_float("price_return_min_1h", *space["price_return_pct_1h"])
        price_operator = ">="
        close_operator = ">="
        context_operator = ">="
    else:
        price = trial.suggest_float("price_return_max_15m", *space["price_return_pct_15m"])
        close = trial.suggest_float("close_position_max_15m", *space["close_position_15m"])
        context = trial.suggest_float("price_return_max_1h", *space["price_return_pct_1h"])
        price_operator = "<="
        close_operator = "<="
        context_operator = "<="
    rule = {
        "direction": direction,
        "price_return_pct_15m": {"operator": price_operator, "value": price},
        "close_position_15m": {"operator": close_operator, "value": close},
        "taker_ratio_15m": {"operator": ">=", "value": trial.suggest_float("taker_ratio_min_15m", *space["taker_ratio_15m"])},
        "price_return_pct_1h": {"operator": context_operator, "value": context},
        "use_oi_min": trial.suggest_categorical("use_oi_min", [False, True]),
        "oi_change_pct_15m_min": trial.suggest_float("oi_change_pct_15m_min", *space["oi_change_pct_15m"]),
        "use_futures_led_min": trial.suggest_categorical("use_futures_led_min", [False, True]),
        "futures_led_score_15m_min": trial.suggest_float("futures_led_score_15m_min", *space["futures_led_score_15m"]),
        "use_spot_score_min": trial.suggest_categorical("use_spot_score_min", [False, True]),
        "spot_support_score_15m_min": trial.suggest_float("spot_support_score_15m_min", *space["spot_support_score_15m"]),
        "exclude_spot_supporting": trial.suggest_categorical("exclude_spot_supporting", [False, True]) if direction == "SHORT" else False,
        "require_spot_supporting": trial.suggest_categorical("require_spot_supporting", [False, True]) if direction == "LONG" else False,
        "allow_spot_missing": trial.suggest_categorical("allow_spot_missing", [True, False]),
        "use_max_spread": trial.suggest_categorical("use_max_spread", [False, True]),
        "futures_spread_pct_max": trial.suggest_float("futures_spread_pct_max", *space["futures_spread_pct"]),
    }
    return rule


def suggest_rule_from_params(params: dict[str, Any], direction: str, space: dict[str, tuple[float, float]]) -> dict[str, Any]:
    class FrozenTrial:
        def suggest_float(self, name: str, *_args: Any) -> float:
            return float(params[name])

        def suggest_categorical(self, name: str, _choices: list[Any]) -> Any:
            return params[name]

    return suggest_rule(FrozenTrial(), direction, space)


def apply_rule(rows: list[ThresholdRow], rule: dict[str, Any]) -> list[ThresholdRow]:
    return [row for row in rows if row_matches(row, rule)]


def row_matches(row: ThresholdRow, rule: dict[str, Any]) -> bool:
    direction = rule["direction"]
    taker_value = row.taker_buy_ratio_15m if direction == "LONG" else row.taker_sell_ratio_15m
    checks = [
        compare(row.price_return_pct_15m, rule["price_return_pct_15m"]),
        compare(row.close_position_15m, rule["close_position_15m"]),
        compare(taker_value, rule["taker_ratio_15m"]),
        compare(row.price_return_pct_1h, rule["price_return_pct_1h"]),
    ]
    if not all(checks):
        return False
    if rule["use_oi_min"] and (row.oi_change_pct_15m is None or row.oi_change_pct_15m < rule["oi_change_pct_15m_min"]):
        return False
    if rule["use_futures_led_min"] and (row.futures_led_score_15m is None or row.futures_led_score_15m < rule["futures_led_score_15m_min"]):
        return False
    if rule["use_spot_score_min"] and (row.spot_support_score_15m is None or row.spot_support_score_15m < rule["spot_support_score_15m_min"]):
        return False
    if rule["exclude_spot_supporting"] and row.spot_support_status_15m == "SPOT_SUPPORTING":
        return False
    if rule["require_spot_supporting"] and row.spot_support_status_15m != "SPOT_SUPPORTING":
        return False
    if not rule["allow_spot_missing"] and row.spot_missing_flag_15m:
        return False
    if rule["use_max_spread"] and row.futures_spread_pct is not None and row.futures_spread_pct > rule["futures_spread_pct_max"]:
        return False
    return True


def compare(value: float | None, rule: dict[str, Any]) -> bool:
    if value is None:
        return False
    if rule["operator"] == ">=":
        return value >= rule["value"]
    if rule["operator"] == "<=":
        return value <= rule["value"]
    raise ValueError(f"Unsupported operator: {rule['operator']}")


def evaluate_rows(rows: list[ThresholdRow], direction: str) -> dict[str, Any]:
    if not rows:
        return empty_metrics()
    directional = [directional_return(row, direction) for row in rows]
    favorable = [row.max_favorable_move_4h for row in rows if row.max_favorable_move_4h is not None]
    adverse = [abs(row.max_adverse_move_4h) for row in rows if row.max_adverse_move_4h is not None]
    symbol_counts = Counter(row.symbol for row in rows)
    top_symbol, top_symbol_count = symbol_counts.most_common(1)[0]
    favorable_count = sum(1 for value in directional if value > 0)
    adverse_count = sum(1 for value in directional if value < 0)
    return {
        "sample_count": len(rows),
        "median_directional_return_4h": median(directional),
        "q25_directional_return_4h": percentile(sorted(directional), 0.25),
        "q75_directional_return_4h": percentile(sorted(directional), 0.75),
        "median_max_favorable_move_4h": median(favorable) if favorable else None,
        "median_max_adverse_move_4h": median(adverse) if adverse else None,
        "favorable_count": favorable_count,
        "adverse_count": adverse_count,
        "favorable_share": favorable_count / len(rows),
        "adverse_share": adverse_count / len(rows),
        "top_symbol": top_symbol,
        "top_symbol_count": top_symbol_count,
        "top_symbol_concentration": top_symbol_count / len(rows),
        "symbol_count": len(symbol_counts),
    }


def empty_metrics() -> dict[str, Any]:
    return {
        "sample_count": 0,
        "median_directional_return_4h": None,
        "q25_directional_return_4h": None,
        "q75_directional_return_4h": None,
        "median_max_favorable_move_4h": None,
        "median_max_adverse_move_4h": None,
        "favorable_count": 0,
        "adverse_count": 0,
        "favorable_share": 0,
        "adverse_share": 0,
        "top_symbol": None,
        "top_symbol_count": 0,
        "top_symbol_concentration": 0,
        "symbol_count": 0,
    }


def directional_return(row: ThresholdRow, direction: str) -> float:
    return row.future_return_4h if direction == "LONG" else -row.future_return_4h


def objective_score(metrics: dict[str, Any]) -> float:
    median_return = float(metrics["median_directional_return_4h"] or 0)
    favorable = float(metrics["median_max_favorable_move_4h"] or 0)
    adverse = float(metrics["median_max_adverse_move_4h"] or 0)
    favorable_share = float(metrics["favorable_share"] or 0)
    concentration = float(metrics["top_symbol_concentration"] or 0)
    sample_bonus = min(float(metrics["sample_count"]) / 300.0, 1.0) * 0.20
    return median_return + 0.20 * favorable - 0.35 * adverse + 0.60 * favorable_share + sample_bonus - 1.00 * concentration


def validation_verdict(metrics: dict[str, Any], min_validation: int) -> str:
    if metrics["sample_count"] < min_validation:
        return "VALIDATION_SAMPLE_TOO_SMALL"
    if metrics["top_symbol_concentration"] > 0.20:
        return "CONCENTRATION_WARNING"
    if (metrics["median_directional_return_4h"] or 0) <= 0:
        return "NO_POSITIVE_DIRECTIONAL_MEDIAN"
    if metrics["adverse_share"] >= metrics["favorable_share"]:
        return "ADVERSE_SHARE_NOT_IMPROVED"
    return "VALIDATION_PROMISING_READONLY"


def interpret_setup(setup_name: str, all_metrics: dict[str, Any], validation_metrics: dict[str, Any], verdict: str) -> str:
    if verdict == "VALIDATION_PROMISING_READONLY":
        return f"{setup_name} has a read-only threshold candidate worth paper monitoring; do not promote without forward validation."
    if verdict == "VALIDATION_SAMPLE_TOO_SMALL":
        return f"{setup_name} optimized subset is too small for a stable definition."
    if verdict == "CONCENTRATION_WARNING":
        return f"{setup_name} subset is too concentrated in one symbol."
    if verdict == "NO_POSITIVE_DIRECTIONAL_MEDIAN":
        return f"{setup_name} validation median does not support the intended direction."
    return f"{setup_name} remains noisy under the current objective."


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * p
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (pos - low)


def flt(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Threshold Research Optuna v1",
        "",
        "Read-only Optuna threshold research for MarketLab candidate definitions. This report does not change live rules, scanner logic, classifier logic, Strategy Arena formulas, Phase 6 scoring, or Phase 7 gates.",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- trials_per_setup: `{payload['trials']}`",
        f"- method: `{payload['method']}`",
        "",
        "## Executive Verdict",
        "",
        "Optuna is used here to discover candidate threshold definitions from production outcomes. Any promising rule remains research-only until a separate forward-validation phase.",
        "",
        "## Setup Summary",
        "",
        "| setup | rows | selected | validation selected | validation verdict | validation median dir 4h | top concentration |",
        "|---|---:|---:|---:|---|---:|---:|",
    ]
    for setup, result in payload["setups"].items():
        if result.get("status") != "COMPLETE":
            lines.append(f"| {setup} | {result.get('row_count', 0)} | 0 | 0 | {result.get('status')} | n/a | n/a |")
            continue
        all_metrics = result["all_selected_metrics"]
        validation = result["validation_metrics"]
        lines.append(
            f"| {setup} | {result['row_count']} | {all_metrics['sample_count']} | "
            f"{validation['sample_count']} | {result['validation_status']} | "
            f"{fmt(validation['median_directional_return_4h'])} | {fmt_pct(validation['top_symbol_concentration'])} |"
        )
    lines.extend(["", "## Threshold Candidates", ""])
    for setup, result in payload["setups"].items():
        lines.append(f"### {setup}")
        if result.get("status") != "COMPLETE":
            lines.extend(["", f"- status: `{result.get('status')}`", ""])
            continue
        lines.extend(
            [
                "",
                f"- candidate_type: `{result['candidate_type']}`",
                f"- direction: `{result['direction']}`",
                f"- validation_status: `{result['validation_status']}`",
                f"- interpretation: {result['interpretation']}",
                "",
                "Rule:",
                "",
                "```json",
                json.dumps(json_safe(result["threshold_rule"]), indent=2),
                "```",
                "",
                "Metrics:",
                "",
                f"- baseline sample: `{result['baseline_all']['sample_count']}`",
                f"- selected sample: `{result['all_selected_metrics']['sample_count']}`",
                f"- selected median directional return 4h: `{fmt(result['all_selected_metrics']['median_directional_return_4h'])}`",
                f"- validation sample: `{result['validation_metrics']['sample_count']}`",
                f"- validation median directional return 4h: `{fmt(result['validation_metrics']['median_directional_return_4h'])}`",
                f"- validation favorable/adverse: `{result['validation_metrics']['favorable_count']} / {result['validation_metrics']['adverse_count']}`",
                f"- validation top symbol concentration: `{fmt_pct(result['validation_metrics']['top_symbol_concentration'])}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Guardrails",
            "",
            "- No runtime rule changed.",
            "- No scanner behavior changed.",
            "- No Phase 6 or Phase 7 gate changed.",
            "- No live signal, execution, order, final TP/SL, or strategy output is created.",
            "- Promising thresholds must be paper-monitored on future data before promotion.",
            "",
        ]
    )
    return "\n".join(lines)


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"
