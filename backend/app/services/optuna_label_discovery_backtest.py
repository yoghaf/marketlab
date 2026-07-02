from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from app.services.multitimeframe_features import DEFAULT_DB_PATH, REPO_ROOT, json_safe
from app.services.threshold_research_optuna import (
    SETUPS,
    ThresholdRow,
    build_search_space,
    evaluate_rows,
    flt,
    import_optuna,
    load_rows,
    objective_score,
    percentile,
    row_matches,
    suggest_rule,
    suggest_rule_from_params,
    validation_verdict,
)


DEFAULT_ARTIFACT_DIR = REPO_ROOT / "backend" / "artifacts" / "threshold_research" / "optuna_v2"
DEFAULT_DOC_PATH = REPO_ROOT / "backend" / "docs" / "optuna_label_discovery_backtest_v2.md"
HORIZON_STEPS = {"15m": 1, "30m": 2, "1h": 4, "4h": 16}


@dataclass(frozen=True)
class MarketWindow:
    symbol: str
    window_open_time: str
    window_close_time: str
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
    candidate_close_price: float
    future_return_15m: float
    future_return_30m: float
    future_return_1h: float
    future_return_4h: float
    max_up_move_1h: float
    max_down_move_1h: float
    max_up_move_4h: float
    max_down_move_4h: float


class OptunaLabelDiscoveryBacktestRunner:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
        doc_path: Path = DEFAULT_DOC_PATH,
        trials: int = 200,
        seed: int = 42,
        max_token_results_per_setup: int = 500,
    ) -> None:
        self.db_path = db_path
        self.artifact_dir = artifact_dir
        self.doc_path = doc_path
        self.trials = trials
        self.seed = seed
        self.max_token_results_per_setup = max_token_results_per_setup

    def run(self) -> dict[str, Any]:
        optuna = import_optuna()
        labeled_rows = load_rows(self.db_path)
        market_windows, coverage = load_market_windows(self.db_path)
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        setup_results: dict[str, Any] = {}
        token_results: dict[str, list[dict[str, Any]]] = {}

        for setup_name, config in SETUPS.items():
            result = self._run_setup(optuna, setup_name, config, labeled_rows, market_windows)
            setup_results[setup_name] = result["summary"]
            token_results[setup_name] = result["tokens"]

        payload = {
            "generated_at": generated_at,
            "db_path": str(self.db_path),
            "trials": self.trials,
            "seed": self.seed,
            "method": "Fit thresholds on existing-label train split, lock rule, then identify/test all market validation windows.",
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "coverage": coverage,
            "setups": setup_results,
            "token_results": token_results,
            "guardrails": [
                "Optuna only discovers research parameters on the train split.",
                "Locked rules are tested on later market windows only.",
                "This does not modify classifier, scanner, Phase 6, Phase 7, Strategy Arena, thresholds, or runtime behavior.",
                "Detected rows are historical research observations, not live signals.",
            ],
        }
        self.write_outputs(payload)
        return payload

    def _run_setup(
        self,
        optuna: Any,
        setup_name: str,
        config: dict[str, Any],
        labeled_rows: list[ThresholdRow],
        market_windows: list[MarketWindow],
    ) -> dict[str, Any]:
        setup_labeled = sorted(
            [row for row in labeled_rows if row.candidate_type == config["candidate_type"]],
            key=lambda row: row.window_close_time,
        )
        if not setup_labeled:
            return {"summary": {"status": "NO_LABELED_TRAIN_DATA", "row_count": 0}, "tokens": []}

        split_index = max(1, int(len(setup_labeled) * 0.70))
        train_rows = setup_labeled[:split_index]
        labeled_validation_rows = setup_labeled[split_index:]
        cutoff_time = train_rows[-1].window_close_time
        direction = config["direction"]
        min_train = int(config["min_train"])
        min_validation = int(config["min_validation"])
        search_space = build_search_space(train_rows, direction)

        def objective(trial: Any) -> float:
            rule = suggest_rule(trial, direction, search_space)
            selected = [row for row in train_rows if row_matches(row, rule)]
            metrics = evaluate_rows(selected, direction)
            if metrics["sample_count"] < min_train:
                return -1000.0 + metrics["sample_count"] / max(min_train, 1)
            return objective_score(metrics)

        sampler = optuna.samplers.TPESampler(seed=self.seed)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=self.trials, show_progress_bar=False)

        locked_rule = suggest_rule_from_params(study.best_trial.params, direction, search_space)
        train_selected = [row for row in train_rows if row_matches(row, locked_rule)]
        labeled_validation_selected = [row for row in labeled_validation_rows if row_matches(row, locked_rule)]
        market_validation = [
            window_to_threshold_row(window, config["candidate_type"], direction)
            for window in market_windows
            if window.window_close_time > cutoff_time
        ]
        identified = [row for row in market_validation if row_matches(row, locked_rule)]
        identified_metrics = evaluate_rows(identified, direction)
        labeled_validation_metrics = evaluate_rows(labeled_validation_selected, direction)
        token_rows = [
            token_result_payload(row, setup_name, locked_rule)
            for row in identified[: self.max_token_results_per_setup]
        ]
        summary = {
            "status": "COMPLETE",
            "setup_name": setup_name,
            "candidate_type": config["candidate_type"],
            "direction": direction,
            "train_source": "existing labeled rows before cutoff",
            "test_source": "all later market windows with complete 4h forward candles",
            "labeled_total": len(setup_labeled),
            "train_count": len(train_rows),
            "labeled_validation_count": len(labeled_validation_rows),
            "market_validation_count": len(market_validation),
            "cutoff_window_close_time": cutoff_time,
            "best_objective": study.best_value,
            "locked_rule": locked_rule,
            "train_selected_metrics": evaluate_rows(train_selected, direction),
            "labeled_validation_selected_metrics": labeled_validation_metrics,
            "market_identified_metrics": identified_metrics,
            "market_validation_status": validation_verdict(identified_metrics, min_validation),
            "sample_token_results_written": len(token_rows),
            "symbol_counts": Counter(row.symbol for row in identified).most_common(20),
            "interpretation": interpret_v2(setup_name, identified_metrics, labeled_validation_metrics, min_validation),
        }
        return {"summary": summary, "tokens": token_rows}

    def write_outputs(self, payload: dict[str, Any]) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.joinpath("results.json").write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")
        self.artifact_dir.joinpath("token_results.json").write_text(
            json.dumps(json_safe(payload["token_results"]), indent=2),
            encoding="utf-8",
        )
        self.doc_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_path.write_text(render_v2_markdown(payload), encoding="utf-8")


def load_market_windows(db_path: Path) -> tuple[list[MarketWindow], dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        feature_rows = conn.execute(
            """
            SELECT ctx.symbol, ctx.feature_15m_window_open_time, ctx.feature_15m_window_close_time,
                   ctx.price_return_pct_15m, ctx.close_position_15m,
                   ctx.kline_taker_buy_ratio_15m, (1 - ctx.kline_taker_buy_ratio_15m) AS taker_sell_ratio_15m,
                   ctx.oi_change_pct_15m, ctx.futures_led_score_15m, ctx.spot_support_score_15m,
                   ctx.spot_futures_volume_ratio_15m, ctx.spot_missing_flag_15m, ctx.spot_support_status_15m,
                   ctx.global_long_short_ratio_15m, ctx.top_trader_position_ratio_15m,
                   f.funding_rate, f.futures_spread_pct,
                   ctx.price_return_pct_1h, ctx.kline_taker_buy_ratio_1h, ctx.oi_change_pct_1h,
                   f.price_close
            FROM market_feature_context_15m_1h ctx
            JOIN market_features_15m f
              ON f.symbol = ctx.symbol
             AND f.window_open_time = ctx.feature_15m_window_open_time
             AND f.window_close_time = ctx.feature_15m_window_close_time
            WHERE ctx.context_status IN ('CONTEXT_READY', 'CONTEXT_PARTIAL')
              AND f.feature_status IN ('FEATURE_READY', 'FEATURE_PARTIAL')
              AND f.price_close IS NOT NULL
            ORDER BY ctx.feature_15m_window_close_time, ctx.symbol
            """
        ).fetchall()
        candle_rows = conn.execute(
            """
            SELECT symbol, close_time, close, high, low
            FROM futures_klines_15m
            WHERE aggregation_status = 'AGG_READY'
              AND close IS NOT NULL
              AND high IS NOT NULL
              AND low IS NOT NULL
            ORDER BY symbol, close_time
            """
        ).fetchall()

    candle_map: dict[tuple[str, datetime], sqlite3.Row] = {}
    for row in candle_rows:
        candle_map[(row["symbol"], parse_dt(row["close_time"]))] = row

    windows: list[MarketWindow] = []
    missing_forward_4h = 0
    incomplete_feature = 0
    for row in feature_rows:
        close_time = parse_dt(row["feature_15m_window_close_time"])
        candidate_close = flt(row["price_close"])
        if candidate_close in (None, 0):
            incomplete_feature += 1
            continue
        future_candles = []
        missing = False
        for offset in range(1, HORIZON_STEPS["4h"] + 1):
            candle = candle_map.get((row["symbol"], close_time + timedelta(minutes=15 * offset)))
            if candle is None:
                missing = True
                break
            future_candles.append(candle)
        if missing:
            missing_forward_4h += 1
            continue
        windows.append(market_window_from_row(row, candidate_close, future_candles))

    coverage = {
        "feature_rows": len(feature_rows),
        "agg_ready_15m_candles": len(candle_rows),
        "usable_market_windows_with_4h_forward": len(windows),
        "missing_forward_4h_windows": missing_forward_4h,
        "incomplete_feature_windows": incomplete_feature,
    }
    return windows, coverage


def market_window_from_row(row: sqlite3.Row, candidate_close: float, future_candles: list[sqlite3.Row]) -> MarketWindow:
    def close_at(step: int) -> float:
        return float(future_candles[step - 1]["close"])

    candles_1h = future_candles[: HORIZON_STEPS["1h"]]
    candles_4h = future_candles[: HORIZON_STEPS["4h"]]
    max_high_1h = max(float(candle["high"]) for candle in candles_1h)
    min_low_1h = min(float(candle["low"]) for candle in candles_1h)
    max_high_4h = max(float(candle["high"]) for candle in candles_4h)
    min_low_4h = min(float(candle["low"]) for candle in candles_4h)
    return MarketWindow(
        symbol=row["symbol"],
        window_open_time=str(row["feature_15m_window_open_time"]),
        window_close_time=str(row["feature_15m_window_close_time"]),
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
        candidate_close_price=candidate_close,
        future_return_15m=pct_change(close_at(1), candidate_close),
        future_return_30m=pct_change(close_at(2), candidate_close),
        future_return_1h=pct_change(close_at(4), candidate_close),
        future_return_4h=pct_change(close_at(16), candidate_close),
        max_up_move_1h=pct_change(max_high_1h, candidate_close),
        max_down_move_1h=pct_change(min_low_1h, candidate_close),
        max_up_move_4h=pct_change(max_high_4h, candidate_close),
        max_down_move_4h=pct_change(min_low_4h, candidate_close),
    )


def window_to_threshold_row(window: MarketWindow, candidate_type: str, direction: str) -> ThresholdRow:
    bullish = direction == "LONG"
    max_fav_4h = window.max_up_move_4h if bullish else abs(window.max_down_move_4h)
    max_adv_4h = window.max_down_move_4h if bullish else window.max_up_move_4h
    return ThresholdRow(
        symbol=window.symbol,
        window_close_time=window.window_close_time,
        candidate_type=candidate_type,
        direction="BULLISH_CONTEXT" if bullish else "BEARISH_CONTEXT",
        price_return_pct_15m=window.price_return_pct_15m,
        close_position_15m=window.close_position_15m,
        taker_buy_ratio_15m=window.taker_buy_ratio_15m,
        taker_sell_ratio_15m=window.taker_sell_ratio_15m,
        oi_change_pct_15m=window.oi_change_pct_15m,
        futures_led_score_15m=window.futures_led_score_15m,
        spot_support_score_15m=window.spot_support_score_15m,
        spot_futures_volume_ratio_15m=window.spot_futures_volume_ratio_15m,
        spot_missing_flag_15m=window.spot_missing_flag_15m,
        spot_support_status_15m=window.spot_support_status_15m,
        global_long_short_ratio_15m=window.global_long_short_ratio_15m,
        top_trader_position_ratio_15m=window.top_trader_position_ratio_15m,
        funding_rate=window.funding_rate,
        futures_spread_pct=window.futures_spread_pct,
        price_return_pct_1h=window.price_return_pct_1h,
        taker_buy_ratio_1h=window.taker_buy_ratio_1h,
        oi_change_pct_1h=window.oi_change_pct_1h,
        future_return_4h=window.future_return_4h,
        max_favorable_move_4h=max_fav_4h,
        max_adverse_move_4h=max_adv_4h,
    )


def token_result_payload(row: ThresholdRow, setup_name: str, rule: dict[str, Any]) -> dict[str, Any]:
    direction = "LONG" if row.direction == "BULLISH_CONTEXT" else "SHORT"
    return {
        "symbol": row.symbol,
        "window_close_time": row.window_close_time,
        "detected_label": f"{setup_name}_OPTUNA_LOCKED",
        "direction": row.direction,
        "future_return_4h": row.future_return_4h,
        "directional_return_4h": row.future_return_4h if direction == "LONG" else -row.future_return_4h,
        "max_favorable_move_4h": row.max_favorable_move_4h,
        "max_adverse_move_4h": row.max_adverse_move_4h,
        "reason": evidence_reason(row, rule),
        "not_live_signal": True,
        "not_execution_instruction": True,
    }


def evidence_reason(row: ThresholdRow, rule: dict[str, Any]) -> dict[str, Any]:
    taker_value = row.taker_buy_ratio_15m if rule["direction"] == "LONG" else row.taker_sell_ratio_15m
    return {
        "price_return_pct_15m": row.price_return_pct_15m,
        "price_rule": rule["price_return_pct_15m"],
        "close_position_15m": row.close_position_15m,
        "close_rule": rule["close_position_15m"],
        "taker_ratio_15m": taker_value,
        "taker_rule": rule["taker_ratio_15m"],
        "price_return_pct_1h": row.price_return_pct_1h,
        "context_rule": rule["price_return_pct_1h"],
        "oi_change_pct_15m": row.oi_change_pct_15m,
        "futures_led_score_15m": row.futures_led_score_15m,
        "spot_support_status_15m": row.spot_support_status_15m,
        "spot_missing_flag_15m": row.spot_missing_flag_15m,
    }


def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def pct_change(next_price: float, base_price: float) -> float:
    if not math.isfinite(next_price) or not math.isfinite(base_price) or base_price == 0:
        return 0.0
    return (next_price - base_price) / base_price * 100.0


def interpret_v2(
    setup_name: str,
    market_metrics: dict[str, Any],
    labeled_validation_metrics: dict[str, Any],
    min_validation: int,
) -> str:
    if market_metrics["sample_count"] < min_validation:
        return f"{setup_name} locked rule identifies too few market validation rows."
    if (market_metrics["median_directional_return_4h"] or 0) <= 0:
        return f"{setup_name} locked rule does not hold positive median directional behavior on market validation."
    if market_metrics["adverse_share"] >= market_metrics["favorable_share"]:
        return f"{setup_name} locked rule remains noisy; adverse share is not lower than favorable share."
    if labeled_validation_metrics["sample_count"] < min_validation:
        return f"{setup_name} looks interesting on market validation, but original labeled validation sample is small."
    return f"{setup_name} is a read-only rule candidate for further forward validation."


def render_v2_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Optuna Label Discovery Backtest v2",
        "",
        "Read-only locked-rule historical validation. Optuna searches parameters on older labeled rows; the locked parameters are then applied to later market windows and tested from futures 15m candles.",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- trials_per_setup: `{payload['trials']}`",
        f"- method: `{payload['method']}`",
        "",
        "## Coverage",
        "",
    ]
    for key, value in payload["coverage"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Setup Results",
            "",
            "| setup | labeled train | market test windows | identified | median dir 4h | favorable/adverse | status |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for setup, result in payload["setups"].items():
        if result.get("status") != "COMPLETE":
            lines.append(f"| {setup} | 0 | 0 | 0 | n/a | n/a | {result.get('status')} |")
            continue
        metrics = result["market_identified_metrics"]
        lines.append(
            f"| {setup} | {result['train_count']} | {result['market_validation_count']} | "
            f"{metrics['sample_count']} | {fmt(metrics['median_directional_return_4h'])} | "
            f"{metrics['favorable_count']} / {metrics['adverse_count']} | {result['market_validation_status']} |"
        )
    lines.extend(["", "## Token Samples", ""])
    for setup, rows in payload["token_results"].items():
        lines.append(f"### {setup}")
        if not rows:
            lines.extend(["", "No identified validation rows.", ""])
            continue
        lines.extend(["", "| symbol | window_close | label | directional 4h | max favorable 4h | max adverse 4h |", "|---|---|---|---:|---:|---:|"])
        for row in rows[:20]:
            lines.append(
                f"| {row['symbol']} | {row['window_close_time']} | {row['detected_label']} | "
                f"{fmt(row['directional_return_4h'])} | {fmt(row['max_favorable_move_4h'])} | {fmt(row['max_adverse_move_4h'])} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Guardrails",
            "",
            "- No production classifier rule changed.",
            "- No scanner behavior changed.",
            "- No Phase 6, Phase 7, Strategy Arena, or outcome logic changed.",
            "- Rows are historical research observations, not live signals or execution instructions.",
            "",
        ]
    )
    return "\n".join(lines)


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"
