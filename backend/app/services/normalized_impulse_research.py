from __future__ import annotations

import json
import math
import sqlite3
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from app.services.multitimeframe_features import DEFAULT_DB_PATH, REPO_ROOT, json_safe


DEFAULT_ARTIFACT_DIR = REPO_ROOT / "backend" / "artifacts" / "threshold_research" / "normalized_impulse_v1"
DEFAULT_DOC_PATH = REPO_ROOT / "backend" / "docs" / "normalized_impulse_research_v1.md"
LOOKBACK_BARS = 20
FRESHNESS_BARS = 4
ATR_PERIOD = 14
EARLY_HORIZON_BARS = 4
MID_HORIZON_BARS = 16


@dataclass(frozen=True)
class FeatureRow:
    symbol: str
    window_open_time: datetime
    window_close_time: datetime
    universe_rank: int | None
    collection_tier: str | None
    price_open: float
    price_high: float
    price_low: float
    price_close: float
    price_return_pct: float
    range_pct: float
    close_position: float | None
    futures_quote_volume: float | None
    kline_taker_buy_ratio: float | None
    kline_taker_sell_ratio: float | None
    oi_change_pct: float | None
    spot_support_status: str | None
    spot_futures_volume_ratio: float | None
    futures_led_score: float | None
    spot_support_score: float | None
    price_return_pct_1h: float | None
    close_position_1h: float | None
    kline_taker_buy_ratio_1h: float | None
    funding_status: str | None
    funding_rate: float | None
    futures_spread_pct: float | None


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class NormalizedImpulseRow:
    symbol: str
    window_open_time: datetime
    window_close_time: datetime
    universe_rank: int | None
    collection_tier: str | None
    price_close: float
    price_return_pct: float
    range_pct: float
    close_position: float | None
    volume_spike_ratio_20: float | None
    range_spike_ratio_20: float | None
    oi_spike_ratio_20: float | None
    oi_change_pct: float | None
    taker_buy_ratio: float | None
    taker_sell_ratio: float | None
    atr_1h: float | None
    atr_1h_pct: float | None
    price_move_atr_1h: float | None
    distance_from_recent_low_atr_20: float | None
    distance_from_recent_high_atr_20: float | None
    same_direction_impulse_age_bars: int | None
    is_fresh_impulse: bool
    spot_support_status: str | None
    spot_futures_volume_ratio: float | None
    futures_led_score: float | None
    spot_support_score: float | None
    price_return_pct_1h: float | None
    close_position_1h: float | None
    kline_taker_buy_ratio_1h: float | None
    funding_status: str | None
    funding_rate: float | None
    futures_spread_pct: float | None
    early_long_v0: bool
    early_short_v0: bool
    mid_long_v0: bool
    mid_short_v0: bool


class NormalizedImpulseResearchRunner:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
        doc_path: Path = DEFAULT_DOC_PATH,
        symbol_limit: int | None = None,
        max_rows_per_setup: int = 500,
    ) -> None:
        self.db_path = db_path
        self.artifact_dir = artifact_dir
        self.doc_path = doc_path
        self.symbol_limit = symbol_limit
        self.max_rows_per_setup = max_rows_per_setup

    def run(self) -> dict[str, Any]:
        features, candles_15m, candles_1h = load_inputs(self.db_path, self.symbol_limit)
        normalized = build_normalized_rows(features, candles_1h)
        setup_rows = {
            "EARLY_LONG_V0": [row for row in normalized if row.early_long_v0],
            "EARLY_SHORT_V0": [row for row in normalized if row.early_short_v0],
            "MID_LONG_V0": [row for row in normalized if row.mid_long_v0],
            "MID_SHORT_V0": [row for row in normalized if row.mid_short_v0],
        }
        setup_configs = {
            "EARLY_LONG_V0": {"direction": "LONG", "horizon_bars": EARLY_HORIZON_BARS, "rr": 1.5},
            "EARLY_SHORT_V0": {"direction": "SHORT", "horizon_bars": EARLY_HORIZON_BARS, "rr": 1.5},
            "MID_LONG_V0": {"direction": "LONG", "horizon_bars": MID_HORIZON_BARS, "rr": 2.0},
            "MID_SHORT_V0": {"direction": "SHORT", "horizon_bars": MID_HORIZON_BARS, "rr": 2.0},
        }
        setup_results: dict[str, Any] = {}
        token_results: dict[str, list[dict[str, Any]]] = {}
        for setup_name, rows in setup_rows.items():
            config = setup_configs[setup_name]
            evaluated = [
                evaluate_rr_path(row, candles_15m, direction=config["direction"], horizon_bars=config["horizon_bars"], rr=config["rr"])
                for row in rows
            ]
            evaluated = [row for row in evaluated if row is not None]
            setup_results[setup_name] = summarize_setup(rows, evaluated, config)
            token_results[setup_name] = evaluated[: self.max_rows_per_setup]

        payload = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "db_path": str(self.db_path),
            "method": "Per-symbol normalized impulse research with ATR 1h RR path evaluation.",
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "parameters": {
                "lookback_bars": LOOKBACK_BARS,
                "freshness_bars": FRESHNESS_BARS,
                "atr_period": ATR_PERIOD,
                "early_horizon_bars": EARLY_HORIZON_BARS,
                "mid_horizon_bars": MID_HORIZON_BARS,
                "early_rr": 1.5,
                "mid_rr": 2.0,
            },
            "coverage": {
                "feature_rows": len(features),
                "normalized_rows": len(normalized),
                "symbols": len({row.symbol for row in normalized}),
                "candles_15m": sum(len(rows) for rows in candles_15m.values()),
                "candles_1h": sum(len(rows) for rows in candles_1h.values()),
            },
            "setup_results": setup_results,
            "token_results": token_results,
            "guardrails": [
                "This is a diagnostic research artifact, not a production classifier.",
                "No scanner, classifier, Phase 6, Phase 7, Strategy Arena, or execution logic is changed.",
                "Thresholds in v0 are seed definitions for measuring behavior and must not be promoted directly.",
            ],
        }
        self.write_outputs(payload)
        return payload

    def write_outputs(self, payload: dict[str, Any]) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        (self.artifact_dir / "results.json").write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")
        (self.artifact_dir / "token_results.json").write_text(
            json.dumps(json_safe(payload["token_results"]), indent=2),
            encoding="utf-8",
        )
        self.doc_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_path.write_text(render_markdown(payload), encoding="utf-8")


def load_inputs(
    db_path: Path,
    symbol_limit: int | None = None,
) -> tuple[list[FeatureRow], dict[str, list[Candle]], dict[str, list[Candle]]]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        symbol_filter = ""
        params: list[Any] = []
        if symbol_limit:
            symbol_filter = "AND f.symbol IN (SELECT symbol FROM marketlab_active_universe WHERE is_active = 1 ORDER BY rank ASC LIMIT ?)"
            params.append(symbol_limit)
        feature_rows = conn.execute(
            f"""
            SELECT f.symbol, f.window_open_time, f.window_close_time,
                   u.rank AS universe_rank, u.collection_tier,
                   f.price_open, f.price_high, f.price_low, f.price_close,
                   f.price_return_pct, f.range_pct, f.close_position,
                   f.futures_quote_volume, f.kline_taker_buy_ratio, f.kline_taker_sell_ratio,
                   f.oi_change_pct, f.funding_rate, f.futures_spread_pct,
                   ctx.spot_support_status_15m, ctx.spot_futures_volume_ratio_15m,
                   ctx.futures_led_score_15m, ctx.spot_support_score_15m,
                   ctx.price_return_pct_1h, ctx.close_position_1h, ctx.kline_taker_buy_ratio_1h,
                   ctx.funding_status_15m
            FROM market_features_15m f
            JOIN market_feature_context_15m_1h ctx
              ON ctx.symbol = f.symbol
             AND ctx.feature_15m_window_open_time = f.window_open_time
            LEFT JOIN marketlab_active_universe u
              ON u.symbol = f.symbol
            WHERE f.feature_status IN ('FEATURE_READY', 'FEATURE_PARTIAL')
              AND ctx.context_status IN ('CONTEXT_READY', 'CONTEXT_PARTIAL')
              AND COALESCE(u.is_active, 1) = 1
              AND f.price_close IS NOT NULL
              AND f.price_open IS NOT NULL
              AND f.price_high IS NOT NULL
              AND f.price_low IS NOT NULL
              {symbol_filter}
            ORDER BY f.symbol, f.window_close_time
            """,
            params,
        ).fetchall()
        candles_15m = load_candles(conn, "futures_klines_15m")
        candles_1h = load_candles(conn, "futures_klines_1h")
    return [feature_from_row(row) for row in feature_rows], candles_15m, candles_1h


def load_candles(conn: sqlite3.Connection, table_name: str) -> dict[str, list[Candle]]:
    rows = conn.execute(
        f"""
        SELECT symbol, open_time, close_time, open, high, low, close
        FROM {table_name}
        WHERE aggregation_status = 'AGG_READY'
          AND open IS NOT NULL
          AND high IS NOT NULL
          AND low IS NOT NULL
          AND close IS NOT NULL
        ORDER BY symbol, open_time
        """
    ).fetchall()
    candles: dict[str, list[Candle]] = {}
    for row in rows:
        candles.setdefault(row["symbol"], []).append(
            Candle(
                open_time=parse_dt(row["open_time"]),
                close_time=parse_dt(row["close_time"]),
                open=flt(row["open"]) or 0.0,
                high=flt(row["high"]) or 0.0,
                low=flt(row["low"]) or 0.0,
                close=flt(row["close"]) or 0.0,
            )
        )
    return candles


def feature_from_row(row: sqlite3.Row) -> FeatureRow:
    return FeatureRow(
        symbol=row["symbol"],
        window_open_time=parse_dt(row["window_open_time"]),
        window_close_time=parse_dt(row["window_close_time"]),
        universe_rank=row["universe_rank"],
        collection_tier=row["collection_tier"],
        price_open=flt(row["price_open"]) or 0.0,
        price_high=flt(row["price_high"]) or 0.0,
        price_low=flt(row["price_low"]) or 0.0,
        price_close=flt(row["price_close"]) or 0.0,
        price_return_pct=flt(row["price_return_pct"]) or 0.0,
        range_pct=flt(row["range_pct"]) or 0.0,
        close_position=flt(row["close_position"]),
        futures_quote_volume=flt(row["futures_quote_volume"]),
        kline_taker_buy_ratio=flt(row["kline_taker_buy_ratio"]),
        kline_taker_sell_ratio=flt(row["kline_taker_sell_ratio"]),
        oi_change_pct=flt(row["oi_change_pct"]),
        spot_support_status=row["spot_support_status_15m"],
        spot_futures_volume_ratio=flt(row["spot_futures_volume_ratio_15m"]),
        futures_led_score=flt(row["futures_led_score_15m"]),
        spot_support_score=flt(row["spot_support_score_15m"]),
        price_return_pct_1h=flt(row["price_return_pct_1h"]),
        close_position_1h=flt(row["close_position_1h"]),
        kline_taker_buy_ratio_1h=flt(row["kline_taker_buy_ratio_1h"]),
        funding_status=row["funding_status_15m"],
        funding_rate=flt(row["funding_rate"]),
        futures_spread_pct=flt(row["futures_spread_pct"]),
    )


def build_normalized_rows(features: list[FeatureRow], candles_1h: dict[str, list[Candle]]) -> list[NormalizedImpulseRow]:
    rows_by_symbol: dict[str, list[FeatureRow]] = {}
    for row in features:
        rows_by_symbol.setdefault(row.symbol, []).append(row)

    output: list[NormalizedImpulseRow] = []
    for symbol, rows in rows_by_symbol.items():
        rows = sorted(rows, key=lambda item: item.window_close_time)
        last_bullish_impulse_index: int | None = None
        last_bearish_impulse_index: int | None = None
        for index, row in enumerate(rows):
            history = rows[max(0, index - LOOKBACK_BARS) : index]
            if len(history) < 5:
                continue
            atr = atr_at(candles_1h.get(symbol, []), row.window_close_time)
            atr_pct = atr / row.price_close * 100.0 if atr and row.price_close else None
            volume_ratio = safe_ratio(row.futures_quote_volume, robust_median([item.futures_quote_volume for item in history]))
            range_ratio = safe_ratio(row.range_pct, robust_median([item.range_pct for item in history]))
            oi_ratio = safe_ratio(abs(row.oi_change_pct), robust_median([abs_or_none(item.oi_change_pct) for item in history]))
            price_move_atr = safe_ratio(abs(row.price_return_pct), atr_pct)
            recent_low = min(item.price_low for item in history if item.price_low)
            recent_high = max(item.price_high for item in history if item.price_high)
            distance_low_atr = safe_ratio((row.price_close - recent_low) / row.price_close * 100.0, atr_pct)
            distance_high_atr = safe_ratio((recent_high - row.price_close) / row.price_close * 100.0, atr_pct)
            bullish_seed = is_bullish_fresh_seed(row, volume_ratio, range_ratio, price_move_atr)
            bearish_seed = is_bearish_fresh_seed(row, volume_ratio, range_ratio, price_move_atr)
            age = None
            if bullish_seed:
                age = None if last_bullish_impulse_index is None else index - last_bullish_impulse_index
                last_bullish_impulse_index = index
            elif bearish_seed:
                age = None if last_bearish_impulse_index is None else index - last_bearish_impulse_index
                last_bearish_impulse_index = index
            is_fresh = age is None or age > FRESHNESS_BARS
            early_long = bullish_seed and is_fresh and spot_not_weak(row) and not funding_crowded_against_long(row)
            early_short = bearish_seed and is_fresh and not funding_crowded_against_short(row)
            mid_long = is_mid_long(row, volume_ratio, range_ratio, price_move_atr, distance_low_atr, early_long)
            mid_short = is_mid_short(row, volume_ratio, range_ratio, price_move_atr, distance_high_atr, early_short)
            output.append(
                NormalizedImpulseRow(
                    symbol=row.symbol,
                    window_open_time=row.window_open_time,
                    window_close_time=row.window_close_time,
                    universe_rank=row.universe_rank,
                    collection_tier=row.collection_tier,
                    price_close=row.price_close,
                    price_return_pct=row.price_return_pct,
                    range_pct=row.range_pct,
                    close_position=row.close_position,
                    volume_spike_ratio_20=volume_ratio,
                    range_spike_ratio_20=range_ratio,
                    oi_spike_ratio_20=oi_ratio,
                    oi_change_pct=row.oi_change_pct,
                    taker_buy_ratio=row.kline_taker_buy_ratio,
                    taker_sell_ratio=row.kline_taker_sell_ratio,
                    atr_1h=atr,
                    atr_1h_pct=atr_pct,
                    price_move_atr_1h=price_move_atr,
                    distance_from_recent_low_atr_20=distance_low_atr,
                    distance_from_recent_high_atr_20=distance_high_atr,
                    same_direction_impulse_age_bars=age,
                    is_fresh_impulse=is_fresh and (bullish_seed or bearish_seed),
                    spot_support_status=row.spot_support_status,
                    spot_futures_volume_ratio=row.spot_futures_volume_ratio,
                    futures_led_score=row.futures_led_score,
                    spot_support_score=row.spot_support_score,
                    price_return_pct_1h=row.price_return_pct_1h,
                    close_position_1h=row.close_position_1h,
                    kline_taker_buy_ratio_1h=row.kline_taker_buy_ratio_1h,
                    funding_status=row.funding_status,
                    funding_rate=row.funding_rate,
                    futures_spread_pct=row.futures_spread_pct,
                    early_long_v0=early_long,
                    early_short_v0=early_short,
                    mid_long_v0=mid_long,
                    mid_short_v0=mid_short,
                )
            )
    return output


def is_bullish_fresh_seed(
    row: FeatureRow,
    volume_ratio: float | None,
    range_ratio: float | None,
    price_move_atr: float | None,
) -> bool:
    return (
        row.price_return_pct > 0
        and value_gte(row.close_position, 0.65)
        and value_gte(row.kline_taker_buy_ratio, 0.55)
        and value_gte(volume_ratio, 1.5)
        and value_gte(range_ratio, 1.2)
        and value_lte(price_move_atr, 1.2)
    )


def is_bearish_fresh_seed(
    row: FeatureRow,
    volume_ratio: float | None,
    range_ratio: float | None,
    price_move_atr: float | None,
) -> bool:
    return (
        row.price_return_pct < 0
        and value_lte(row.close_position, 0.35)
        and value_gte(row.kline_taker_sell_ratio, 0.55)
        and value_gte(volume_ratio, 1.5)
        and value_gte(range_ratio, 1.2)
        and value_lte(price_move_atr, 1.2)
    )


def is_mid_long(
    row: FeatureRow,
    volume_ratio: float | None,
    range_ratio: float | None,
    price_move_atr: float | None,
    distance_low_atr: float | None,
    early_long: bool,
) -> bool:
    return (
        not early_long
        and row.price_return_pct > 0
        and value_gte(row.price_return_pct_1h, 0.25)
        and value_gte(row.close_position, 0.58)
        and value_gte(row.kline_taker_buy_ratio, 0.53)
        and value_gte(volume_ratio, 0.8)
        and value_gte(range_ratio, 0.8)
        and value_lte(price_move_atr, 1.5)
        and value_lte(distance_low_atr, 3.5)
        and spot_not_weak(row)
    )


def is_mid_short(
    row: FeatureRow,
    volume_ratio: float | None,
    range_ratio: float | None,
    price_move_atr: float | None,
    distance_high_atr: float | None,
    early_short: bool,
) -> bool:
    return (
        not early_short
        and row.price_return_pct < 0
        and value_lte(row.price_return_pct_1h, -0.25)
        and value_lte(row.close_position, 0.42)
        and value_gte(row.kline_taker_sell_ratio, 0.53)
        and value_gte(volume_ratio, 0.8)
        and value_gte(range_ratio, 0.8)
        and value_lte(price_move_atr, 1.5)
        and value_lte(distance_high_atr, 3.5)
    )


def evaluate_rr_path(
    row: NormalizedImpulseRow,
    candles_15m: dict[str, list[Candle]],
    direction: str,
    horizon_bars: int,
    rr: float,
    risk_atr_mult: float = 1.0,
) -> dict[str, Any] | None:
    if not row.atr_1h or row.atr_1h <= 0:
        return None
    candles = future_candles(candles_15m.get(row.symbol, []), row.window_close_time, horizon_bars)
    if candles is None:
        return None
    entry = row_to_entry_price(row)
    risk = row.atr_1h * risk_atr_mult
    target_distance = risk * rr
    if direction == "LONG":
        stop = entry - risk
        target = entry + target_distance
    else:
        stop = entry + risk
        target = entry - target_distance
    max_high = max(candle.high for candle in candles)
    min_low = min(candle.low for candle in candles)
    max_favorable_r = (max_high - entry) / risk if direction == "LONG" else (entry - min_low) / risk
    max_adverse_r = (min_low - entry) / risk if direction == "LONG" else (entry - max_high) / risk
    outcome = "NEITHER"
    realized_r = (candles[-1].close - entry) / risk if direction == "LONG" else (entry - candles[-1].close) / risk
    for candle in candles:
        if direction == "LONG":
            tp_hit = candle.high >= target
            sl_hit = candle.low <= stop
        else:
            tp_hit = candle.low <= target
            sl_hit = candle.high >= stop
        if tp_hit and sl_hit:
            outcome = "BOTH_SAME_CANDLE"
            realized_r = 0.0
            break
        if tp_hit:
            outcome = "TP_FIRST"
            realized_r = rr
            break
        if sl_hit:
            outcome = "SL_FIRST"
            realized_r = -1.0
            break
    return {
        "symbol": row.symbol,
        "window_close_time": row.window_close_time.isoformat(),
        "direction": direction,
        "entry_reference": entry,
        "atr_1h": row.atr_1h,
        "atr_1h_pct": row.atr_1h_pct,
        "risk_atr_mult": risk_atr_mult,
        "rr": rr,
        "horizon_bars": horizon_bars,
        "outcome": outcome,
        "realized_r": realized_r,
        "max_favorable_r": max_favorable_r,
        "max_adverse_r": max_adverse_r,
        "price_return_pct": row.price_return_pct,
        "volume_spike_ratio_20": row.volume_spike_ratio_20,
        "range_spike_ratio_20": row.range_spike_ratio_20,
        "oi_spike_ratio_20": row.oi_spike_ratio_20,
        "oi_change_pct": row.oi_change_pct,
        "price_move_atr_1h": row.price_move_atr_1h,
        "same_direction_impulse_age_bars": row.same_direction_impulse_age_bars,
        "is_fresh_impulse": row.is_fresh_impulse,
        "spot_support_status": row.spot_support_status,
        "price_return_pct_1h": row.price_return_pct_1h,
        "not_live_signal": True,
        "not_execution_instruction": True,
    }


def summarize_setup(source_rows: list[NormalizedImpulseRow], evaluated: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    outcomes = Counter(row["outcome"] for row in evaluated)
    realized = [row["realized_r"] for row in evaluated if row["realized_r"] is not None]
    favorable = [row["max_favorable_r"] for row in evaluated if row["max_favorable_r"] is not None]
    adverse = [row["max_adverse_r"] for row in evaluated if row["max_adverse_r"] is not None]
    symbols = Counter(row["symbol"] for row in evaluated)
    return {
        "source_candidate_count": len(source_rows),
        "evaluated_count": len(evaluated),
        "direction": config["direction"],
        "horizon_bars": config["horizon_bars"],
        "rr": config["rr"],
        "outcome_counts": dict(outcomes),
        "tp_first_share": share(outcomes.get("TP_FIRST", 0), len(evaluated)),
        "sl_first_share": share(outcomes.get("SL_FIRST", 0), len(evaluated)),
        "neither_share": share(outcomes.get("NEITHER", 0), len(evaluated)),
        "median_realized_r": robust_median(realized),
        "avg_realized_r": sum(realized) / len(realized) if realized else None,
        "median_max_favorable_r": robust_median(favorable),
        "median_max_adverse_r": robust_median(adverse),
        "top_symbols": symbols.most_common(15),
        "top_symbol_share": share(symbols.most_common(1)[0][1], len(evaluated)) if evaluated else 0.0,
        "read_only_verdict": setup_verdict(evaluated, outcomes, realized),
    }


def setup_verdict(evaluated: list[dict[str, Any]], outcomes: Counter, realized: list[float]) -> str:
    if len(evaluated) < 30:
        return "SAMPLE_TOO_SMALL"
    med = robust_median(realized)
    if med is None or med <= 0:
        return "NO_POSITIVE_MEDIAN_R"
    if outcomes.get("SL_FIRST", 0) >= outcomes.get("TP_FIRST", 0):
        return "RISK_NOT_SEPARATED"
    return "PROMISING_FOR_FURTHER_RESEARCH"


def atr_at(candles: list[Candle], signal_close_time: datetime, period: int = ATR_PERIOD) -> float | None:
    if len(candles) < period + 1:
        return None
    close_times = [candle.close_time for candle in candles]
    pos = bisect_right(close_times, signal_close_time) - 1
    if pos < period:
        return None
    window = candles[pos - period : pos + 1]
    ranges = []
    for index in range(1, len(window)):
        candle = window[index]
        prev_close = window[index - 1].close
        ranges.append(max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close)))
    return sum(ranges) / period if len(ranges) == period else None


def future_candles(candles: list[Candle], signal_close_time: datetime, expected_count: int) -> list[Candle] | None:
    if not candles:
        return None
    open_times = [candle.open_time for candle in candles]
    start = bisect_right(open_times, signal_close_time - timedelta(microseconds=1))
    window = candles[start : start + expected_count]
    if len(window) != expected_count:
        return None
    for offset, candle in enumerate(window):
        expected_open = signal_close_time + timedelta(minutes=15 * offset)
        if candle.open_time != expected_open:
            return None
    return window


def row_to_entry_price(row: NormalizedImpulseRow) -> float:
    return row.price_close


def spot_not_weak(row: FeatureRow) -> bool:
    return row.spot_support_status not in {"WEAK_SPOT_SUPPORT"}


def funding_crowded_against_long(row: FeatureRow) -> bool:
    return row.funding_rate is not None and row.funding_rate > 0.0005


def funding_crowded_against_short(row: FeatureRow) -> bool:
    return row.funding_rate is not None and row.funding_rate < -0.0005


def robust_median(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return median(clean) if clean else None


def safe_ratio(value: float | None, denominator: float | None) -> float | None:
    if value is None or denominator is None or denominator == 0:
        return None
    if not math.isfinite(value) or not math.isfinite(denominator):
        return None
    return value / denominator


def share(count: int, total: int) -> float:
    return count / total * 100.0 if total else 0.0


def value_gte(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def value_lte(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def abs_or_none(value: float | None) -> float | None:
    return abs(value) if value is not None else None


def flt(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Normalized Impulse Research v1",
        "",
        "Read-only research layer for per-symbol normalized impulse behavior. This is not a production classifier and does not change scanner, Phase 6, Phase 7, Strategy Arena, or execution behavior.",
        "",
        f"- generated_at: `{payload['generated_at']}`",
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
            "## Diagnostic Setup Results",
            "",
            "| setup | candidates | evaluated | horizon bars | RR | TP_FIRST | SL_FIRST | median R | verdict |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for setup, result in payload["setup_results"].items():
        outcomes = result["outcome_counts"]
        lines.append(
            f"| {setup} | {result['source_candidate_count']} | {result['evaluated_count']} | "
            f"{result['horizon_bars']} | {result['rr']} | {outcomes.get('TP_FIRST', 0)} | "
            f"{outcomes.get('SL_FIRST', 0)} | {fmt(result['median_realized_r'])} | {result['read_only_verdict']} |"
        )
    lines.extend(["", "## Interpretation", ""])
    lines.extend(
        [
            "- EARLY v0 is defined as a fresh per-symbol impulse: volume/range anomaly, directional taker pressure, close location, and limited ATR extension.",
            "- MID v0 is defined as continuation: 1h direction supports the 15m move, moderate volume/range participation, and limited ATR extension.",
            "- These v0 thresholds are intentionally diagnostic seeds; the next research step should optimize normalized features only after this layer is measured.",
            "",
            "## Guardrails",
            "",
            "- No production rule changed.",
            "- No live signal or execution instruction is created.",
            "- ATR is calculated from closed 1h candles only.",
            "- Per-token normalization is used for volume, range, and OI baseline comparisons.",
            "",
        ]
    )
    return "\n".join(lines)


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"
