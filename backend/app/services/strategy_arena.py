from __future__ import annotations

import json
import sqlite3
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "marketlab.db"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "backend" / "artifacts" / "strategy_arena" / "v1"
DEFAULT_DOC_PATH = REPO_ROOT / "backend" / "docs" / "strategy_arena_v1_atr_r_all_labels_multi_horizon.md"

DEFAULT_ATR_MULTIPLIERS = [Decimal("0.75"), Decimal("1.00"), Decimal("1.25"), Decimal("1.50"), Decimal("2.00")]
DEFAULT_RR_VALUES = [Decimal("1.0"), Decimal("1.5"), Decimal("2.0"), Decimal("2.5"), Decimal("3.0")]
DEFAULT_HORIZONS = {"15m": 1, "1h": 4, "4h": 16, "24h": 96}
RESULTS_FILE = "results.json"
LEADERBOARD_FILE = "leaderboard.json"


@dataclass(frozen=True)
class SetupFamily:
    setup_family: str
    setup_label: str
    source_candidate_type: str
    direction_mode: str
    direction_label: str
    requires_futures_led: bool | None = None
    description: str = ""


SETUP_FAMILIES = [
    SetupFamily(
        "MID_SHORT_FUTURES_LED",
        "Mid Short + Futures Dominan",
        "MID_SHORT_CONTEXT_READONLY",
        "SHORT",
        "Short test",
        True,
        "Kondisi bearish yang didukung aktivitas futures lebih dominan daripada spot.",
    ),
    SetupFamily(
        "MID_SHORT_NON_FUTURES_LED",
        "Mid Short non-Futures Dominan",
        "MID_SHORT_CONTEXT_READONLY",
        "SHORT",
        "Short test",
        False,
        "Kondisi bearish tanpa bukti futures-led eksplisit.",
    ),
    SetupFamily("EARLY_SHORT", "Early Short", "EARLY_SHORT_CANDIDATE_READONLY", "SHORT", "Short test"),
    SetupFamily("MID_LONG", "Mid Long", "MID_LONG_CONTEXT_READONLY", "LONG", "Long test"),
    SetupFamily("EARLY_LONG", "Early Long", "EARLY_LONG_CANDIDATE_READONLY", "LONG", "Long test"),
    SetupFamily(
        "SQUEEZE_CONTINUATION",
        "Squeeze Continuation",
        "SQUEEZE_RISK_CONTEXT_READONLY",
        "IMPULSE",
        "Ikut impulse",
    ),
    SetupFamily("SQUEEZE_FADE", "Squeeze Fade", "SQUEEZE_RISK_CONTEXT_READONLY", "FADE_IMPULSE", "Fade impulse"),
    SetupFamily("TRAP_FADE", "Trap Fade", "TRAP_RISK_CONTEXT_READONLY", "TRAP_FADE", "Fade trap"),
    SetupFamily("NO_SIGNAL_BASELINE_SHORT", "No Signal Baseline Short", "NO_SIGNAL_CONTEXT", "SHORT", "Short baseline"),
    SetupFamily("NO_SIGNAL_BASELINE_LONG", "No Signal Baseline Long", "NO_SIGNAL_CONTEXT", "LONG", "Long baseline"),
]


@dataclass(frozen=True)
class CandidateRow:
    symbol: str
    window_open_time: datetime
    window_close_time: datetime
    candidate_type: str
    evidence: dict[str, Any]
    entry: Decimal
    universe_rank: int | None


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


def parse_decimal_list(value: str | None, default: list[Decimal]) -> list[Decimal]:
    if not value:
        return default
    return [Decimal(item.strip()) for item in value.split(",") if item.strip()]


def parse_horizons(value: str | None) -> dict[str, int]:
    if not value:
        return DEFAULT_HORIZONS.copy()
    result: dict[str, int] = {}
    for item in value.split(","):
        key = item.strip()
        if key not in DEFAULT_HORIZONS:
            raise ValueError(f"Unsupported horizon: {key}")
        result[key] = DEFAULT_HORIZONS[key]
    return result


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def dec(value: Any) -> Decimal:
    if value is None:
        raise InvalidOperation("missing decimal")
    return Decimal(str(value))


def to_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_json_value(item) for item in value]
    return value


def pct(count: int, total: int) -> Decimal:
    if total == 0:
        return Decimal("0")
    return Decimal(count) * Decimal(100) / Decimal(total)


def pct_label(value: Decimal) -> str:
    return f"{value:.2f}%"


def r_label(value: Decimal) -> str:
    return f"{value.normalize()}R"


def futures_led(evidence: dict[str, Any]) -> bool:
    labels = evidence.get("supporting_psychology_labels") or []
    return evidence.get("spot_support_status_15m") == "FUTURES_LED" or "FUTURES_LED_MOVE" in labels


def candidate_direction_for_setup(candidate: CandidateRow, setup: SetupFamily) -> tuple[str | None, str | None]:
    mode = setup.direction_mode
    if mode in {"LONG", "SHORT"}:
        return mode, None

    price_return = _optional_decimal(candidate.evidence.get("price_return_pct_15m"))
    labels = set(candidate.evidence.get("supporting_psychology_labels") or [])
    if mode in {"IMPULSE", "FADE_IMPULSE"}:
        if price_return is None or price_return == 0:
            return None, "UNKNOWN_IMPULSE_DIRECTION"
        impulse = "LONG" if price_return > 0 else "SHORT"
        if mode == "IMPULSE":
            return impulse, None
        return ("SHORT" if impulse == "LONG" else "LONG"), None

    if mode == "TRAP_FADE":
        if "LONG_TRAP_RISK" in labels:
            return "SHORT", None
        if "SHORT_SQUEEZE_RISK" in labels:
            return "LONG", None
        if price_return is None or price_return == 0:
            return None, "UNKNOWN_TRAP_DIRECTION"
        return ("SHORT" if price_return > 0 else "LONG"), None

    return None, "UNKNOWN_SETUP_DIRECTION"


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return dec(value)
    except InvalidOperation:
        return None


def candidate_matches_setup(candidate: CandidateRow, setup: SetupFamily) -> bool:
    if candidate.candidate_type != setup.source_candidate_type:
        return False
    if setup.requires_futures_led is None:
        return True
    return futures_led(candidate.evidence) is setup.requires_futures_led


def calculate_atr14(candles_1h: list[Candle], close_times_1h: list[datetime], signal_close_time: datetime) -> Decimal | None:
    pos = bisect_right(close_times_1h, signal_close_time) - 1
    if pos < 14:
        return None
    window = candles_1h[pos - 14 : pos + 1]
    true_ranges: list[Decimal] = []
    for index in range(1, len(window)):
        candle = window[index]
        prev_close = window[index - 1].close
        true_ranges.append(max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close)))
    if len(true_ranges) != 14:
        return None
    atr = sum(true_ranges) / Decimal(14)
    return atr if atr > 0 else None


def future_window(
    candles_15m: list[Candle],
    open_times_15m: list[datetime],
    signal_close_time: datetime,
    expected_count: int,
) -> list[Candle] | None:
    start = bisect_left(open_times_15m, signal_close_time)
    window = candles_15m[start : start + expected_count]
    if len(window) != expected_count:
        return None
    for offset, candle in enumerate(window):
        expected_open = signal_close_time + timedelta(minutes=15 * offset)
        if candle.open_time != expected_open or candle.close_time != expected_open + timedelta(minutes=15):
            return None
    return window


def evaluate_path(
    candidate: CandidateRow,
    future_candles: list[Candle],
    direction: str,
    risk_distance: Decimal,
    rr: Decimal,
) -> tuple[str, Decimal | None, Decimal | None]:
    entry = candidate.entry
    if direction == "LONG":
        stop = entry - risk_distance
        target = entry + (rr * risk_distance)
    else:
        stop = entry + risk_distance
        target = entry - (rr * risk_distance)

    for candle in future_candles:
        if direction == "LONG":
            tp_hit = candle.high >= target
            sl_hit = candle.low <= stop
        else:
            tp_hit = candle.low <= target
            sl_hit = candle.high >= stop
        if tp_hit and sl_hit:
            return "BOTH_SAME_CANDLE", None, None
        if tp_hit:
            return "TP_FIRST", rr, None
        if sl_hit:
            return "SL_FIRST", Decimal("-1"), None

    close_r = (future_candles[-1].close - entry) / risk_distance if direction == "LONG" else (entry - future_candles[-1].close) / risk_distance
    return "NEITHER", close_r, close_r


class StrategyArenaRunner:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
        doc_path: Path = DEFAULT_DOC_PATH,
        min_sample: int = 50,
        horizons: dict[str, int] | None = None,
        atr_multipliers: list[Decimal] | None = None,
        rr_values: list[Decimal] | None = None,
        include_baseline: bool = True,
    ) -> None:
        self.db_path = db_path
        self.artifact_dir = artifact_dir
        self.doc_path = doc_path
        self.min_sample = min_sample
        self.horizons = horizons or DEFAULT_HORIZONS.copy()
        self.atr_multipliers = atr_multipliers or DEFAULT_ATR_MULTIPLIERS
        self.rr_values = rr_values or DEFAULT_RR_VALUES
        self.setups = [setup for setup in SETUP_FAMILIES if include_baseline or not setup.setup_family.startswith("NO_SIGNAL_BASELINE")]

    def run(self) -> dict[str, Any]:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            candidates = self._load_candidates(conn)
            candles_15m = self._load_candles(conn, "futures_klines_15m")
            candles_1h = self._load_candles(conn, "futures_klines_1h")
        finally:
            conn.close()

        open_times_15m = {symbol: [candle.open_time for candle in rows] for symbol, rows in candles_15m.items()}
        close_times_1h = {symbol: [candle.close_time for candle in rows] for symbol, rows in candles_1h.items()}

        results: list[dict[str, Any]] = []
        skipped = {"MISSING_ATR": 0, "INSUFFICIENT_FORWARD_DATA": 0, "UNKNOWN_DIRECTION": 0}
        setup_counts = {setup.setup_family: 0 for setup in self.setups}

        for setup in self.setups:
            setup_candidates = [candidate for candidate in candidates if candidate_matches_setup(candidate, setup)]
            setup_counts[setup.setup_family] = len(setup_candidates)
            for atr_mult in self.atr_multipliers:
                for rr in self.rr_values:
                    for horizon, expected_count in self.horizons.items():
                        rows: list[dict[str, Any]] = []
                        insufficient_forward_data_count = 0
                        for candidate in setup_candidates:
                            direction, direction_reason = candidate_direction_for_setup(candidate, setup)
                            if direction is None:
                                skipped["UNKNOWN_DIRECTION"] += 1
                                continue
                            symbol_1h = candles_1h.get(candidate.symbol)
                            symbol_15m = candles_15m.get(candidate.symbol)
                            if not symbol_1h or not symbol_15m:
                                skipped["MISSING_ATR"] += 1
                                continue
                            atr = calculate_atr14(symbol_1h, close_times_1h[candidate.symbol], candidate.window_close_time)
                            if atr is None:
                                skipped["MISSING_ATR"] += 1
                                continue
                            future_candles = future_window(
                                symbol_15m,
                                open_times_15m[candidate.symbol],
                                candidate.window_close_time,
                                expected_count,
                            )
                            if future_candles is None:
                                insufficient_forward_data_count += 1
                                skipped["INSUFFICIENT_FORWARD_DATA"] += 1
                                continue
                            outcome, r_value, unresolved_close_r = evaluate_path(
                                candidate,
                                future_candles,
                                direction,
                                atr * atr_mult,
                                rr,
                            )
                            rows.append(
                                {
                                    "symbol": candidate.symbol,
                                    "universe_rank": candidate.universe_rank,
                                    "outcome": outcome,
                                    "r": r_value,
                                    "unresolved_close_r": unresolved_close_r,
                                }
                            )
                        results.append(self._summarize(setup, atr_mult, rr, horizon, rows, insufficient_forward_data_count))

        leaderboard = self._build_leaderboard(results)
        payload = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "db_path": str(self.db_path),
                "read_only": True,
                "not_live_signal": True,
                "not_execution_system": True,
                "entry_model": "candidate_15m_close",
                "atr_model": "ATR14 futures_klines_1h closed before or at signal",
                "min_sample": self.min_sample,
                "horizons": list(self.horizons.keys()),
                "atr_multipliers": [str(value) for value in self.atr_multipliers],
                "rr_values": [str(value) for value in self.rr_values],
                "candidate_rows_loaded": len(candidates),
                "setup_candidate_counts": setup_counts,
                "skipped_counts": skipped,
            },
            "results": results,
        }
        self._write_artifacts(payload, leaderboard)
        return {"results": payload, "leaderboard": leaderboard}

    def _load_candidates(self, conn: sqlite3.Connection) -> list[CandidateRow]:
        rows = conn.execute(
            """
            SELECT c.symbol, c.window_open_time, c.window_close_time, c.candidate_type, c.evidence, k.close, u.rank AS universe_rank
            FROM market_signal_candidates_readonly_15m c
            JOIN futures_klines_15m k
              ON k.symbol = c.symbol
             AND k.open_time = c.window_open_time
             AND k.aggregation_status = 'AGG_READY'
            LEFT JOIN marketlab_active_universe u
              ON u.symbol = c.symbol
            WHERE c.classifier_status != 'CLASSIFIER_BLOCKED'
              AND c.candidate_type IN (
                  'MID_SHORT_CONTEXT_READONLY',
                  'EARLY_SHORT_CANDIDATE_READONLY',
                  'MID_LONG_CONTEXT_READONLY',
                  'EARLY_LONG_CANDIDATE_READONLY',
                  'SQUEEZE_RISK_CONTEXT_READONLY',
                  'TRAP_RISK_CONTEXT_READONLY',
                  'NO_SIGNAL_CONTEXT'
              )
              AND COALESCE(u.is_active, 1) = 1
            ORDER BY c.window_close_time, c.symbol
            """
        ).fetchall()
        return [
            CandidateRow(
                symbol=row["symbol"],
                window_open_time=parse_dt(row["window_open_time"]),
                window_close_time=parse_dt(row["window_close_time"]),
                candidate_type=row["candidate_type"],
                evidence=json.loads(row["evidence"] or "{}"),
                entry=dec(row["close"]),
                universe_rank=row["universe_rank"],
            )
            for row in rows
        ]

    def _load_candles(self, conn: sqlite3.Connection, table_name: str) -> dict[str, list[Candle]]:
        rows = conn.execute(
            f"""
            SELECT symbol, open_time, close_time, open, high, low, close
            FROM {table_name}
            WHERE aggregation_status = 'AGG_READY'
            ORDER BY symbol, open_time
            """
        ).fetchall()
        candles: dict[str, list[Candle]] = {}
        for row in rows:
            candles.setdefault(row["symbol"], []).append(
                Candle(
                    open_time=parse_dt(row["open_time"]),
                    close_time=parse_dt(row["close_time"]),
                    open=dec(row["open"]),
                    high=dec(row["high"]),
                    low=dec(row["low"]),
                    close=dec(row["close"]),
                )
            )
        return candles

    def _summarize(
        self,
        setup: SetupFamily,
        atr_mult: Decimal,
        rr: Decimal,
        horizon: str,
        rows: list[dict[str, Any]],
        insufficient_forward_data_count: int,
    ) -> dict[str, Any]:
        sample_size = len(rows)
        counts = {"TP_FIRST": 0, "SL_FIRST": 0, "BOTH_SAME_CANDLE": 0, "NEITHER": 0}
        resolved_r: list[Decimal] = []
        pessimistic_r: list[Decimal] = []
        median_values: list[Decimal] = []
        symbol_counts: dict[str, int] = {}
        rank_buckets = {"TOP_25": [], "MID_26_50": [], "LOW_51_75": [], "UNKNOWN": []}

        for row in rows:
            outcome = row["outcome"]
            counts[outcome] += 1
            if outcome == "TP_FIRST":
                resolved_r.append(row["r"])
                pessimistic_r.append(row["r"])
                median_values.append(row["r"])
            elif outcome == "SL_FIRST":
                resolved_r.append(Decimal("-1"))
                pessimistic_r.append(Decimal("-1"))
                median_values.append(Decimal("-1"))
            elif outcome == "BOTH_SAME_CANDLE":
                pessimistic_r.append(Decimal("-1"))
                median_values.append(Decimal("-1"))
            else:
                pessimistic_r.append(row["r"])
                median_values.append(row["r"])
            symbol_counts[row["symbol"]] = symbol_counts.get(row["symbol"], 0) + 1
            bucket = _rank_bucket(row["universe_rank"])
            if pessimistic_r:
                rank_buckets[bucket].append(pessimistic_r[-1])

        top_symbol, top_symbol_count = max(symbol_counts.items(), key=lambda item: item[1], default=(None, 0))
        resolved_avg_r = sum(resolved_r) / Decimal(len(resolved_r)) if resolved_r else None
        pessimistic_avg_r = sum(pessimistic_r) / Decimal(len(pessimistic_r)) if pessimistic_r else None
        median_r = Decimal(str(median(median_values))) if median_values else None
        worst_r = min(median_values) if median_values else None
        best_r = max(median_values) if median_values else None
        shares = {key: pct(count, sample_size) for key, count in counts.items()}
        top_symbol_share = pct(top_symbol_count, sample_size)
        rank_bucket_performance = {
            bucket: {
                "sample_size": len(values),
                "pessimistic_avg_r": (sum(values) / Decimal(len(values))) if values else None,
            }
            for bucket, values in rank_buckets.items()
        }
        verdict = self._verdict(sample_size, shares, top_symbol_share, pessimistic_avg_r, counts)
        return {
            "setup_family": setup.setup_family,
            "setup_label": setup.setup_label,
            "source_candidate_type": setup.source_candidate_type,
            "direction": setup.direction_mode,
            "direction_label": setup.direction_label,
            "horizon": horizon,
            "horizon_label": horizon,
            "atr_mult": atr_mult,
            "rr": rr,
            "risk_label": f"{atr_mult}x ATR",
            "rr_label": r_label(rr),
            "sample_size": sample_size,
            "tp_first_count": counts["TP_FIRST"],
            "tp_first_share": shares["TP_FIRST"],
            "sl_first_count": counts["SL_FIRST"],
            "sl_first_share": shares["SL_FIRST"],
            "both_same_candle_count": counts["BOTH_SAME_CANDLE"],
            "both_same_candle_share": shares["BOTH_SAME_CANDLE"],
            "neither_count": counts["NEITHER"],
            "neither_share": shares["NEITHER"],
            "insufficient_forward_data_count": insufficient_forward_data_count,
            "resolved_avg_r": resolved_avg_r,
            "pessimistic_avg_r": pessimistic_avg_r,
            "median_r": median_r,
            "worst_r": worst_r,
            "best_r": best_r,
            "top_symbol": top_symbol,
            "top_symbol_count": top_symbol_count,
            "top_symbol_share": top_symbol_share,
            "distinct_symbols": len(symbol_counts),
            "rank_bucket_performance": rank_bucket_performance,
            "verdict": verdict,
            "verdict_label": VERDICT_LABELS[verdict],
            "warning_label": self._warning_label(sample_size, shares, top_symbol_share),
        }

    def _verdict(
        self,
        sample_size: int,
        shares: dict[str, Decimal],
        top_symbol_share: Decimal,
        pessimistic_avg_r: Decimal | None,
        counts: dict[str, int],
    ) -> str:
        if sample_size < self.min_sample:
            return "INSUFFICIENT_SAMPLE"
        if pessimistic_avg_r is None or pessimistic_avg_r <= 0 or shares["SL_FIRST"] >= Decimal("45") or shares["BOTH_SAME_CANDLE"] >= Decimal("25"):
            return "REJECT"
        if pessimistic_avg_r < Decimal("0.10") or shares["NEITHER"] >= Decimal("70") or shares["BOTH_SAME_CANDLE"] >= Decimal("10"):
            return "NOISY"
        if counts["TP_FIRST"] > counts["SL_FIRST"] and top_symbol_share <= Decimal("15"):
            return "PROMISING_FOR_FORWARD_TEST"
        return "MONITOR_MORE"

    def _warning_label(self, sample_size: int, shares: dict[str, Decimal], top_symbol_share: Decimal) -> str:
        warnings = []
        if sample_size < self.min_sample:
            warnings.append("Sample kurang")
        if top_symbol_share > Decimal("15"):
            warnings.append("Konsentrasi koin tinggi")
        if shares["BOTH_SAME_CANDLE"] >= Decimal("10"):
            warnings.append("Banyak candle ambigu")
        if shares["NEITHER"] >= Decimal("70"):
            warnings.append("Banyak posisi belum kena target/stop")
        return "; ".join(warnings) if warnings else "Tidak ada warning utama"

    def _build_leaderboard(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        rankable = [row for row in results if row["sample_size"] >= self.min_sample and row["pessimistic_avg_r"] is not None]
        top_pessimistic = sorted(rankable, key=lambda row: (row["pessimistic_avg_r"], row["sample_size"]), reverse=True)
        top_resolved = sorted(
            [row for row in rankable if row["resolved_avg_r"] is not None],
            key=lambda row: (row["resolved_avg_r"], row["sample_size"]),
            reverse=True,
        )
        baseline = self._baseline_comparison(results)
        leaderboard = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "ranking_metric": "pessimistic_avg_r",
                "read_only": True,
                "not_live_signal": True,
            },
            "summary": {
                "total_setups_tested": len(self.setups),
                "total_combinations": len(results),
                "promising_count": sum(1 for row in results if row["verdict"] == "PROMISING_FOR_FORWARD_TEST"),
                "noisy_count": sum(1 for row in results if row["verdict"] == "NOISY"),
                "rejected_count": sum(1 for row in results if row["verdict"] == "REJECT"),
                "best_short_setup": _leaderboard_item(next((row for row in top_pessimistic if "SHORT" in row["setup_family"] or row["direction_label"].lower().startswith("short")), None), 1),
                "best_long_setup": _leaderboard_item(next((row for row in top_pessimistic if "LONG" in row["setup_family"] or row["direction_label"].lower().startswith("long")), None), 1),
                "best_horizon": _best_horizon(top_pessimistic),
            },
            "top_by_pessimistic_avg_r": [_leaderboard_item(row, idx + 1) for idx, row in enumerate(top_pessimistic[:50])],
            "top_by_resolved_avg_r": [_leaderboard_item(row, idx + 1) for idx, row in enumerate(top_resolved[:50])],
            "best_short_setup": [_leaderboard_item(row, idx + 1) for idx, row in enumerate([row for row in top_pessimistic if row["direction_label"].lower().startswith("short")][:20])],
            "best_long_setup": [_leaderboard_item(row, idx + 1) for idx, row in enumerate([row for row in top_pessimistic if row["direction_label"].lower().startswith("long")][:20])],
            "best_by_horizon": {
                horizon: [_leaderboard_item(row, idx + 1) for idx, row in enumerate([row for row in top_pessimistic if row["horizon"] == horizon][:20])]
                for horizon in self.horizons
            },
            "worst_setups": [_leaderboard_item(row, idx + 1) for idx, row in enumerate(sorted(rankable, key=lambda row: row["pessimistic_avg_r"])[:20])],
            "noisy_setups": [_leaderboard_item(row, idx + 1) for idx, row in enumerate([row for row in results if row["verdict"] == "NOISY"][:50])],
            "rejected_setups": [_leaderboard_item(row, idx + 1) for idx, row in enumerate([row for row in results if row["verdict"] == "REJECT"][:50])],
            "baseline_comparison": baseline,
        }
        return leaderboard

    def _baseline_comparison(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        baselines = {
            (row["horizon"], row["atr_mult"], row["rr"], "SHORT"): row
            for row in results
            if row["setup_family"] == "NO_SIGNAL_BASELINE_SHORT"
        }
        baselines.update(
            {
                (row["horizon"], row["atr_mult"], row["rr"], "LONG"): row
                for row in results
                if row["setup_family"] == "NO_SIGNAL_BASELINE_LONG"
            }
        )
        comparison = []
        for row in results:
            if row["setup_family"].startswith("NO_SIGNAL_BASELINE"):
                continue
            side = "LONG" if "LONG" in row["direction_label"].upper() else "SHORT"
            baseline = baselines.get((row["horizon"], row["atr_mult"], row["rr"], side))
            if not baseline or row["pessimistic_avg_r"] is None or baseline["pessimistic_avg_r"] is None:
                status = "BASELINE_NOT_AVAILABLE"
                delta = None
            else:
                delta = row["pessimistic_avg_r"] - baseline["pessimistic_avg_r"]
                status = "BEATS_BASELINE" if delta > 0 else "DOES_NOT_BEAT_BASELINE"
            comparison.append(
                {
                    "setup_family": row["setup_family"],
                    "horizon": row["horizon"],
                    "atr_mult": row["atr_mult"],
                    "rr": row["rr"],
                    "baseline_status": status,
                    "pessimistic_avg_r_delta": delta,
                }
            )
        return comparison

    def _write_artifacts(self, payload: dict[str, Any], leaderboard: dict[str, Any]) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        (self.artifact_dir / RESULTS_FILE).write_text(json.dumps(to_json_value(payload), indent=2), encoding="utf-8")
        (self.artifact_dir / LEADERBOARD_FILE).write_text(json.dumps(to_json_value(leaderboard), indent=2), encoding="utf-8")
        self.doc_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_path.write_text(render_markdown(payload, leaderboard), encoding="utf-8")


class StrategyArenaArtifactService:
    def __init__(self, artifact_dir: Path = DEFAULT_ARTIFACT_DIR) -> None:
        self.artifact_dir = artifact_dir

    def leaderboard(self) -> dict[str, Any]:
        return self._read_json(LEADERBOARD_FILE)

    def results(self) -> dict[str, Any]:
        return self._read_json(RESULTS_FILE)

    def setup(self, setup_family: str) -> dict[str, Any]:
        payload = self.results()
        normalized = setup_family.upper()
        items = [row for row in payload.get("results", []) if row.get("setup_family") == normalized]
        if not items:
            raise FileNotFoundError(f"Strategy Arena setup not found: {setup_family}")
        return {
            "setup_family": normalized,
            "count": len(items),
            "items": items,
            "read_only": True,
            "not_live_signal": True,
        }

    def _read_json(self, filename: str) -> dict[str, Any]:
        path = self.artifact_dir / filename
        if not path.exists():
            raise FileNotFoundError("Strategy Arena artifact not found. Run arena script first.")
        return json.loads(path.read_text(encoding="utf-8"))


VERDICT_LABELS = {
    "PROMISING_FOR_FORWARD_TEST": "Layak forward test",
    "MONITOR_MORE": "Pantau lagi",
    "NOISY": "Terlalu noise",
    "REJECT": "Ditolak",
    "INSUFFICIENT_SAMPLE": "Sample kurang",
}


def _rank_bucket(rank: int | None) -> str:
    if rank is None:
        return "UNKNOWN"
    if rank <= 25:
        return "TOP_25"
    if rank <= 50:
        return "MID_26_50"
    return "LOW_51_75"


def _leaderboard_item(row: dict[str, Any] | None, rank: int) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "rank": rank,
        "setup_label": row["setup_label"],
        "setup_family": row["setup_family"],
        "direction_label": row["direction_label"],
        "horizon_label": row["horizon_label"],
        "risk_label": row["risk_label"],
        "rr_label": row["rr_label"],
        "sample_size": row["sample_size"],
        "pessimistic_avg_r": row["pessimistic_avg_r"],
        "resolved_avg_r": row["resolved_avg_r"],
        "tp_first_share": row["tp_first_share"],
        "sl_first_share": row["sl_first_share"],
        "both_same_candle_share": row["both_same_candle_share"],
        "neither_share": row["neither_share"],
        "top_symbol_share": row["top_symbol_share"],
        "verdict": row["verdict"],
        "verdict_label": row["verdict_label"],
    }


def _best_horizon(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    return rows[0]["horizon_label"]


def render_markdown(payload: dict[str, Any], leaderboard: dict[str, Any]) -> str:
    metadata = payload["metadata"]
    lines = [
        "# Strategy Arena v1 ATR/R All Labels Multi-Horizon",
        "",
        f"Generated at: `{metadata['generated_at']}`",
        "",
        "This is an offline/read-only strategy test arena. It is not a live entry signal, not an order system, and not a final TP/SL model.",
        "",
        "## Method",
        "",
        "- Entry is the close of the candidate 15m futures candle.",
        "- ATR is ATR(14) from futures 1h candles closed before or at signal time.",
        "- Forward path uses closed futures 15m candles.",
        "- BOTH_SAME_CANDLE is ambiguous and treated pessimistically as -1R in ranking.",
        "- Main ranking uses pessimistic_avg_r.",
        "",
        "## Input Coverage",
        "",
        f"- Candidate rows loaded: `{metadata['candidate_rows_loaded']}`",
        f"- Missing ATR exclusions: `{metadata['skipped_counts']['MISSING_ATR']}`",
        f"- Insufficient forward data exclusions: `{metadata['skipped_counts']['INSUFFICIENT_FORWARD_DATA']}`",
        "",
        "| setup | candidate rows |",
        "|---|---:|",
    ]
    for setup, count in metadata["setup_candidate_counts"].items():
        lines.append(f"| {setup} | {count} |")
    lines.extend(["", "## Top 10 Leaderboard", "", _markdown_table(leaderboard["top_by_pessimistic_avg_r"][:10])])
    lines.extend(
        [
            "",
            "## Baseline Comparison",
            "",
            "Rows marked DOES_NOT_BEAT_BASELINE should not be promoted. This is descriptive only and does not claim a final edge.",
            "",
            "| setup | horizon | ATR | RR | status | delta R |",
            "|---|---|---:|---:|---|---:|",
        ]
    )
    for row in leaderboard["baseline_comparison"][:80]:
        delta = row["pessimistic_avg_r_delta"]
        lines.append(
            f"| {row['setup_family']} | {row['horizon']} | {row['atr_mult']} | {row['rr']} | {row['baseline_status']} | {delta if delta is not None else 'n/a'} |"
        )
    lines.extend(["", "## Full Results", "", _markdown_results_table(payload["results"])])
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- No live signal is produced.",
            "- No exchange connection, order, execution, position sizing, or leverage logic is introduced.",
            "- Classifier, scanner, outcome, feature, context, and universe rules are unchanged.",
        ]
    )
    return "\n".join(lines) + "\n"


def _markdown_table(items: list[dict[str, Any] | None]) -> str:
    rows = [item for item in items if item]
    if not rows:
        return "No rankable rows."
    lines = [
        "| rank | setup | direction | horizon | risk | RR | sample | avg R konservatif | target dulu | stop dulu | dua arah | verdict |",
        "|---:|---|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['rank']} | {row['setup_label']} | {row['direction_label']} | {row['horizon_label']} | {row['risk_label']} | {row['rr_label']} | {row['sample_size']} | {row['pessimistic_avg_r']:.4f} | {row['tp_first_share']:.2f}% | {row['sl_first_share']:.2f}% | {row['both_same_candle_share']:.2f}% | {row['verdict_label']} |"
        )
    return "\n".join(lines)


def _markdown_results_table(results: list[dict[str, Any]]) -> str:
    lines = [
        "| setup | horizon | ATR | RR | sample | TP_FIRST | SL_FIRST | BOTH | NEITHER | avg R konservatif | resolved avg R | top symbol share | verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in results:
        resolved = row["resolved_avg_r"]
        pessimistic = row["pessimistic_avg_r"]
        lines.append(
            f"| {row['setup_family']} | {row['horizon']} | {row['atr_mult']} | {row['rr']} | {row['sample_size']} | {row['tp_first_count']} | {row['sl_first_count']} | {row['both_same_candle_count']} | {row['neither_count']} | {pessimistic if pessimistic is not None else 'n/a'} | {resolved if resolved is not None else 'n/a'} | {row['top_symbol_share']:.2f}% | {row['verdict']} |"
        )
    return "\n".join(lines)
