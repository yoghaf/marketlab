from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline1h, FuturesKline4h, MarketlabActiveUniverse
from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import SignalCandidatePerformanceService, _parse_dt
from app.services.signal_filter_optuna import apply_position_lock, evaluate_items, with_deltas
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import json_safe


DEFAULT_ARTIFACT_DIR = REPO_ROOT / "backend" / "artifacts" / "market_regime_study" / "v1"
DEFAULT_DOC_PATH = REPO_ROOT / "backend" / "docs" / "market_regime_study_v1.md"

LANES = {
    "MID_SHORT_1H": {"stage": "MID_SHORT", "timeframe": "1h", "direction": "SHORT"},
    "MID_LONG_1H": {"stage": "MID_LONG", "timeframe": "1h", "direction": "LONG"},
}

REGIME_DIMENSIONS = [
    "combined_regime_1h",
    "btc_1h_regime",
    "btc_4h_regime",
    "eth_1h_regime",
    "breadth_1h_regime",
    "breadth_4h_regime",
    "volatility_1h_regime",
    "volatility_4h_regime",
    "btc_breadth_1h_pair",
]


@dataclass(frozen=True)
class MarketSnapshot:
    timeframe: str
    close_time: datetime | None
    symbol_count: int
    up_count: int
    down_count: int
    flat_count: int
    up_pct: float | None
    avg_return_pct: float | None
    avg_abs_return_pct: float | None


class MarketRegimeStudyRunner:
    """Read-only study that splits Signal Candidate outcomes by market regime."""

    def __init__(
        self,
        db: Session,
        *,
        artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
        doc_path: Path = DEFAULT_DOC_PATH,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_sample: int = 10,
    ) -> None:
        self.db = db
        self.artifact_dir = artifact_dir
        self.doc_path = doc_path
        self.epoch = epoch
        self.include_watch_only = include_watch_only
        self.position_lock = position_lock
        self.min_sample = min_sample
        self._active_symbols_cache: set[str] | None = None
        self._market_snapshot_cache: dict[tuple[str, datetime | None], MarketSnapshot] = {}
        self._symbol_return_cache: dict[tuple[str, str, datetime | None], float | None] = {}

    def run(self) -> dict[str, Any]:
        generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        lanes: dict[str, Any] = {}
        for lane, config in LANES.items():
            lanes[lane] = self._run_lane(lane, config)
        payload = {
            "generated_at": generated_at,
            "epoch": self.epoch,
            "include_watch_only": self.include_watch_only,
            "position_lock": self.position_lock,
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "method": "Market regime split study for logged Signal Candidate outcomes",
            "regime_inputs": {
                "btc_1h_4h": "closed futures BTCUSDT 1h/4h candle return at or before signal timestamp",
                "eth_1h_4h": "closed futures ETHUSDT 1h/4h candle return at or before signal timestamp",
                "breadth": "active universe futures candle up/down share at same closed 1h/4h market window",
                "volatility": "average absolute return across active universe at same closed 1h/4h market window",
            },
            "lanes": lanes,
            "guardrails": [
                "No Signal Factory rule changed.",
                "No classifier/scanner/outcome logic changed.",
                "No live signal, order, execution, final TP/SL, leverage, or position sizing is created.",
                "Regime buckets are read-only diagnostics before any V3 rule proposal.",
            ],
        }
        self.write_outputs(payload)
        return payload

    def _run_lane(self, lane: str, config: dict[str, str]) -> dict[str, Any]:
        raw_items, skipped, latest_candle = SignalCandidatePerformanceService(self.db)._evaluated_context(  # noqa: SLF001
            epoch=self.epoch,
            include_watch_only=self.include_watch_only,
            stage=config["stage"],
            timeframe=config["timeframe"],
            symbol=None,
            position_lock=False,
        )
        raw_items = sorted(raw_items, key=lambda item: (_parse_dt(item.get("signal_timestamp")) or datetime.min, str(item.get("symbol"))))
        items, lock_skipped = apply_position_lock(raw_items) if self.position_lock else (raw_items, 0)
        enriched = [self._enrich_item(item) for item in items]
        baseline = evaluate_items(enriched, direction=config["direction"])
        dimensions = {
            dimension: self._dimension_rows(enriched, dimension, direction=config["direction"], baseline=baseline)
            for dimension in REGIME_DIMENSIONS
        }
        helpful = sorted(
            [row for rows in dimensions.values() for row in rows if row["verdict"] in {"REGIME_HELPFUL", "REGIME_IMPROVES"}],
            key=lambda row: (
                row.get("avg_r_delta_vs_baseline") if row.get("avg_r_delta_vs_baseline") is not None else -999,
                row.get("sample_count", 0),
            ),
            reverse=True,
        )
        harmful = sorted(
            [row for rows in dimensions.values() for row in rows if row["verdict"] == "REGIME_BAD"],
            key=lambda row: (
                row.get("avg_r_delta_vs_baseline") if row.get("avg_r_delta_vs_baseline") is not None else 0,
                row.get("sample_count", 0),
            ),
        )
        return {
            "lane": lane,
            "stage": config["stage"],
            "timeframe": config["timeframe"],
            "direction": config["direction"],
            "raw_count": len(raw_items),
            "sample_count": len(enriched),
            "lock_skipped": lock_skipped,
            "load_skipped": dict(skipped),
            "latest_futures_15m_close_time": latest_candle,
            "baseline": baseline,
            "dimensions": dimensions,
            "top_helpful_regimes": helpful[:10],
            "top_harmful_regimes": harmful[:10],
            "interpretation": interpret_lane(lane, baseline, helpful, harmful),
        }

    def _enrich_item(self, item: dict[str, Any]) -> dict[str, Any]:
        signal_time = _parse_dt(item.get("signal_timestamp"))
        btc_1h = self._symbol_return("1h", "BTCUSDT", signal_time)
        btc_4h = self._symbol_return("4h", "BTCUSDT", signal_time)
        eth_1h = self._symbol_return("1h", "ETHUSDT", signal_time)
        eth_4h = self._symbol_return("4h", "ETHUSDT", signal_time)
        market_1h = self._market_snapshot("1h", signal_time)
        market_4h = self._market_snapshot("4h", signal_time)
        regimes = {
            "btc_1h_regime": classify_return(btc_1h, bullish_threshold=0.25, bearish_threshold=-0.25),
            "btc_4h_regime": classify_return(btc_4h, bullish_threshold=0.60, bearish_threshold=-0.60),
            "eth_1h_regime": classify_return(eth_1h, bullish_threshold=0.25, bearish_threshold=-0.25),
            "eth_4h_regime": classify_return(eth_4h, bullish_threshold=0.60, bearish_threshold=-0.60),
            "breadth_1h_regime": classify_breadth(market_1h.up_pct),
            "breadth_4h_regime": classify_breadth(market_4h.up_pct),
            "volatility_1h_regime": classify_volatility(market_1h.avg_abs_return_pct, high=1.25, low=0.45),
            "volatility_4h_regime": classify_volatility(market_4h.avg_abs_return_pct, high=2.50, low=0.90),
        }
        regimes["combined_regime_1h"] = combined_regime(regimes["btc_1h_regime"], regimes["breadth_1h_regime"])
        regimes["btc_breadth_1h_pair"] = f"{regimes['btc_1h_regime']}__{regimes['breadth_1h_regime']}"
        enriched = dict(item)
        enriched["market_regime"] = {
            **regimes,
            "btc_return_1h_pct": btc_1h,
            "btc_return_4h_pct": btc_4h,
            "eth_return_1h_pct": eth_1h,
            "eth_return_4h_pct": eth_4h,
            "market_1h": asdict(market_1h),
            "market_4h": asdict(market_4h),
        }
        return enriched

    def _dimension_rows(self, items: list[dict[str, Any]], dimension: str, *, direction: str, baseline: dict[str, Any]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            bucket = str((item.get("market_regime") or {}).get(dimension) or "REGIME_UNKNOWN")
            grouped[bucket].append(item)
        rows = []
        for bucket, bucket_items in grouped.items():
            metrics = with_deltas(evaluate_items(bucket_items, direction=direction), baseline)
            row = {
                "dimension": dimension,
                "bucket": bucket,
                **metrics,
            }
            row["verdict"] = regime_verdict(row, min_sample=self.min_sample)
            row["note"] = regime_note(row)
            rows.append(row)
        rows.sort(
            key=lambda row: (
                row["verdict"] in {"REGIME_HELPFUL", "REGIME_IMPROVES"},
                row.get("avg_r_delta_vs_baseline") if row.get("avg_r_delta_vs_baseline") is not None else -999,
                row.get("sample_count", 0),
            ),
            reverse=True,
        )
        return rows

    def _symbol_return(self, timeframe: str, symbol: str, signal_time: datetime | None) -> float | None:
        key = (timeframe, symbol, signal_time)
        if key in self._symbol_return_cache:
            return self._symbol_return_cache[key]
        model = FuturesKline1h if timeframe == "1h" else FuturesKline4h
        row = self.db.execute(
            select(model.open, model.close)
            .where(
                model.symbol == symbol,
                model.aggregation_status == "AGG_READY",
                model.close_time <= signal_time,
                model.open.is_not(None),
                model.close.is_not(None),
            )
            .order_by(desc(model.close_time))
            .limit(1)
        ).first() if signal_time else None
        value = candle_return_pct(row.open, row.close) if row else None
        self._symbol_return_cache[key] = value
        return value

    def _market_snapshot(self, timeframe: str, signal_time: datetime | None) -> MarketSnapshot:
        close_time = self._latest_market_close_time(timeframe, signal_time)
        key = (timeframe, close_time)
        if key in self._market_snapshot_cache:
            return self._market_snapshot_cache[key]
        model = FuturesKline1h if timeframe == "1h" else FuturesKline4h
        if close_time is None:
            snapshot = MarketSnapshot(timeframe, None, 0, 0, 0, 0, None, None, None)
            self._market_snapshot_cache[key] = snapshot
            return snapshot
        active_symbols = self._active_symbols()
        query = select(model.symbol, model.open, model.close).where(
            model.close_time == close_time,
            model.aggregation_status == "AGG_READY",
            model.open.is_not(None),
            model.close.is_not(None),
        )
        if active_symbols:
            query = query.where(model.symbol.in_(active_symbols))
        returns = [value for row in self.db.execute(query).all() if (value := candle_return_pct(row.open, row.close)) is not None]
        up_count = sum(1 for value in returns if value > 0)
        down_count = sum(1 for value in returns if value < 0)
        flat_count = len(returns) - up_count - down_count
        snapshot = MarketSnapshot(
            timeframe=timeframe,
            close_time=close_time,
            symbol_count=len(returns),
            up_count=up_count,
            down_count=down_count,
            flat_count=flat_count,
            up_pct=(up_count / len(returns) * 100) if returns else None,
            avg_return_pct=(sum(returns) / len(returns)) if returns else None,
            avg_abs_return_pct=(sum(abs(value) for value in returns) / len(returns)) if returns else None,
        )
        self._market_snapshot_cache[key] = snapshot
        return snapshot

    def _latest_market_close_time(self, timeframe: str, signal_time: datetime | None) -> datetime | None:
        if signal_time is None:
            return None
        model = FuturesKline1h if timeframe == "1h" else FuturesKline4h
        return self.db.scalar(
            select(func.max(model.close_time)).where(
                model.aggregation_status == "AGG_READY",
                model.close_time <= signal_time,
            )
        )

    def _active_symbols(self) -> set[str]:
        if self._active_symbols_cache is None:
            self._active_symbols_cache = set(
                self.db.scalars(
                    select(MarketlabActiveUniverse.symbol).where(MarketlabActiveUniverse.is_active.is_(True))
                ).all()
            )
        return self._active_symbols_cache

    def write_outputs(self, payload: dict[str, Any]) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.joinpath("results.json").write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")
        self.doc_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc_path.write_text(render_markdown(payload), encoding="utf-8")


def candle_return_pct(open_price: Any, close_price: Any) -> float | None:
    if open_price in (None, 0, "0") or close_price is None:
        return None
    open_dec = Decimal(str(open_price))
    if open_dec == 0:
        return None
    return float((Decimal(str(close_price)) - open_dec) / open_dec * Decimal("100"))


def classify_return(value: float | None, *, bullish_threshold: float, bearish_threshold: float) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= bullish_threshold:
        return "BULLISH"
    if value <= bearish_threshold:
        return "BEARISH"
    return "FLAT"


def classify_breadth(up_pct: float | None) -> str:
    if up_pct is None:
        return "BREADTH_UNKNOWN"
    if up_pct >= 60:
        return "BREADTH_STRONG"
    if up_pct <= 40:
        return "BREADTH_WEAK"
    return "BREADTH_MIXED"


def classify_volatility(avg_abs_return_pct: float | None, *, high: float, low: float) -> str:
    if avg_abs_return_pct is None:
        return "VOL_UNKNOWN"
    if avg_abs_return_pct >= high:
        return "VOL_HIGH"
    if avg_abs_return_pct <= low:
        return "VOL_LOW"
    return "VOL_NORMAL"


def combined_regime(btc_regime: str, breadth_regime: str) -> str:
    if btc_regime == "BULLISH" and breadth_regime == "BREADTH_STRONG":
        return "RISK_ON"
    if btc_regime == "BEARISH" and breadth_regime == "BREADTH_WEAK":
        return "RISK_OFF"
    if btc_regime == "BULLISH" and breadth_regime == "BREADTH_WEAK":
        return "BTC_UP_BREADTH_WEAK"
    if btc_regime == "BEARISH" and breadth_regime == "BREADTH_STRONG":
        return "BTC_DOWN_BREADTH_STRONG"
    if btc_regime == "UNKNOWN" or breadth_regime == "BREADTH_UNKNOWN":
        return "REGIME_UNKNOWN"
    return "CHOPPY_OR_MIXED"


def regime_verdict(row: dict[str, Any], *, min_sample: int) -> str:
    if int(row.get("closed_count") or 0) < min_sample:
        return "SAMPLE_TOO_SMALL"
    avg_r = row.get("avg_r_closed")
    avg_delta = row.get("avg_r_delta_vs_baseline")
    win_delta = row.get("winrate_delta_vs_baseline")
    sl_delta = row.get("sl_share_delta_vs_baseline")
    if avg_r is not None and avg_delta is not None and win_delta is not None and float(avg_r) > 0 and float(avg_delta) >= 0.15 and float(win_delta) >= 5:
        return "REGIME_HELPFUL"
    if avg_delta is not None and sl_delta is not None and float(avg_delta) > 0 and float(sl_delta) <= 0:
        return "REGIME_IMPROVES"
    if avg_delta is not None and float(avg_delta) <= -0.15:
        return "REGIME_BAD"
    return "REGIME_NOISY"


def regime_note(row: dict[str, Any]) -> str:
    verdict = row.get("verdict")
    if verdict == "REGIME_HELPFUL":
        return "Bucket ini memperbaiki avg R dan winrate dibanding baseline; kandidat regime filter untuk forward monitoring."
    if verdict == "REGIME_IMPROVES":
        return "Bucket ini memperbaiki avg R atau damage profile, tapi belum cukup kuat."
    if verdict == "REGIME_BAD":
        return "Bucket ini lebih buruk dari baseline; kemungkinan kondisi market yang harus dihindari."
    if verdict == "SAMPLE_TOO_SMALL":
        return "Sample bucket belum cukup."
    return "Belum ada pemisahan bersih."


def interpret_lane(lane: str, baseline: dict[str, Any], helpful: list[dict[str, Any]], harmful: list[dict[str, Any]]) -> str:
    if int(baseline.get("closed_count") or 0) < 10:
        return f"{lane}: sample closed masih kecil; tunggu data tambahan."
    if helpful:
        best = helpful[0]
        return f"{lane}: regime paling membantu saat ini adalah {best['dimension']}={best['bucket']}, tetap read-only."
    if harmful:
        worst = harmful[0]
        return f"{lane}: belum ada regime membantu; bucket paling buruk {worst['dimension']}={worst['bucket']} perlu dihindari/diteliti."
    return f"{lane}: belum ada regime split yang memisahkan hasil secara jelas."


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Market Regime Study v1",
        "",
        "Read-only regime split for logged Signal Candidate outcomes. This does not change Signal Factory, scanner, classifier, outcome logic, TP/SL, execution, or strategy.",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- position_lock: `{payload['position_lock']}`",
        f"- method: `{payload['method']}`",
        "",
        "## Executive Verdict",
        "",
        "The goal is to identify whether MID_SHORT 1h and MID_LONG 1h are failing because they are used in the wrong BTC/ETH/breadth regime.",
        "",
        "## Lane Summary",
        "",
        "| lane | sample | closed | TP/SL | avg R | total R | interpretation |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for lane, result in payload["lanes"].items():
        baseline = result.get("baseline", {})
        lines.append(
            f"| {lane} | {result.get('sample_count', 0)} | {baseline.get('closed_count', 0)} | "
            f"{baseline.get('tp_count', 0)}/{baseline.get('sl_count', 0)} | {fmt(baseline.get('avg_r_closed'))} | "
            f"{fmt(baseline.get('total_r_closed'))} | {result.get('interpretation')} |"
        )
    lines.extend(["", "## Helpful Regime Buckets", ""])
    for lane, result in payload["lanes"].items():
        lines.append(f"### {lane}")
        rows = result.get("top_helpful_regimes", [])
        if not rows:
            lines.extend(["", "No helpful regime bucket yet.", ""])
            continue
        lines.extend([
            "",
            "| dimension | bucket | sample | TP/SL | avg R | avg R delta | winrate delta | verdict |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ])
        for row in rows[:8]:
            lines.append(
                f"| {row['dimension']} | {row['bucket']} | {row['sample_count']} | {row['tp_count']}/{row['sl_count']} | "
                f"{fmt(row.get('avg_r_closed'))} | {fmt(row.get('avg_r_delta_vs_baseline'))} | "
                f"{fmt(row.get('winrate_delta_vs_baseline'))} | {row['verdict']} |"
            )
        lines.append("")
    lines.extend(["## Harmful Regime Buckets", ""])
    for lane, result in payload["lanes"].items():
        lines.append(f"### {lane}")
        rows = result.get("top_harmful_regimes", [])
        if not rows:
            lines.extend(["", "No clearly harmful regime bucket yet.", ""])
            continue
        lines.extend([
            "",
            "| dimension | bucket | sample | TP/SL | avg R | avg R delta | verdict |",
            "|---|---|---:|---:|---:|---:|---|",
        ])
        for row in rows[:8]:
            lines.append(
                f"| {row['dimension']} | {row['bucket']} | {row['sample_count']} | {row['tp_count']}/{row['sl_count']} | "
                f"{fmt(row.get('avg_r_closed'))} | {fmt(row.get('avg_r_delta_vs_baseline'))} | {row['verdict']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Guardrails",
            "",
            "- No runtime rule changed.",
            "- No live signal, order, execution, final TP/SL, leverage, or position sizing is created.",
            "- Regime buckets are diagnostic only; any candidate filter requires forward monitoring.",
            "",
        ]
    )
    return "\n".join(lines)


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"
