from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "marketlab.db"
TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}
LOOKBACKS = {"15m": 16, "1h": 24, "4h": 12, "24h": 14}
MIN_LOOKBACKS = {"15m": 4, "1h": 4, "4h": 3, "24h": 3}
FEATURE_STATUSES = {"READY", "PARTIAL_DATA", "MISSING_CANDLES", "MISSING_OI", "MISSING_ATR", "STALE_DATA"}
AGG_TABLES = {
    "futures": {"15m": "futures_klines_15m", "1h": "futures_klines_1h", "4h": "futures_klines_4h", "24h": "futures_klines_24h"},
    "spot": {"15m": "spot_klines_15m", "1h": "spot_klines_1h", "4h": "spot_klines_4h", "24h": "spot_klines_24h"},
}


@dataclass(frozen=True)
class TimeframeCandle:
    symbol: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal | None = None
    number_of_trades: int | None = None
    taker_buy_base_volume: Decimal | None = None
    taker_sell_base_volume: Decimal | None = None
    taker_buy_quote_volume: Decimal | None = None
    taker_sell_quote_volume: Decimal | None = None


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    timeframe: str
    window_start: datetime | None
    window_end: datetime | None
    price_return: Decimal | None
    price_return_abs: Decimal | None
    volume_sum: Decimal | None
    volume_ratio_vs_lookback: Decimal | None
    volume_spike: bool
    kline_taker_buy_ratio: Decimal | None
    kline_taker_sell_ratio: Decimal | None
    kline_taker_buy_base: Decimal | None
    kline_taker_sell_base: Decimal | None
    oi_change: Decimal | None
    oi_change_pct: Decimal | None
    funding_rate: Decimal | None
    funding_pressure: str
    high_low_range: Decimal | None
    range_pct: Decimal | None
    close_position_in_range: Decimal | None
    atr: Decimal | None
    atr_pct: Decimal | None
    futures_volume_spike: bool
    spot_volume_spike: bool | None
    oi_expansion: bool
    price_move_with_oi: bool
    futures_led_flag: bool
    spot_led_flag: bool
    mixed_flow_flag: bool
    spot_context: str
    benchmark_return: Decimal | None
    symbol_return: Decimal | None
    relative_return: Decimal | None
    relative_strength: str
    feature_status: str
    status_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def aggregate_candles(candles: list[TimeframeCandle], timeframe: str) -> list[TimeframeCandle]:
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    if not candles:
        return []
    minutes = TIMEFRAME_MINUTES[timeframe]
    grouped: dict[datetime, list[TimeframeCandle]] = {}
    for candle in sorted(candles, key=lambda item: item.open_time):
        bucket = floor_time(candle.open_time, minutes)
        grouped.setdefault(bucket, []).append(candle)
    output: list[TimeframeCandle] = []
    expected = max(1, minutes // 15)
    for bucket, rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda item: item.open_time)
        if len(rows) != expected:
            continue
        contiguous = all(rows[idx].close_time == rows[idx + 1].open_time for idx in range(len(rows) - 1))
        if not contiguous:
            continue
        output.append(
            TimeframeCandle(
                symbol=rows[0].symbol,
                open_time=bucket,
                close_time=bucket + timedelta(minutes=minutes),
                open=rows[0].open,
                high=max(row.high for row in rows),
                low=min(row.low for row in rows),
                close=rows[-1].close,
                volume=sum((row.volume for row in rows), Decimal("0")),
                quote_volume=sum((row.quote_volume or Decimal("0") for row in rows), Decimal("0")),
                number_of_trades=sum((row.number_of_trades or 0 for row in rows)),
                taker_buy_base_volume=sum((row.taker_buy_base_volume or Decimal("0") for row in rows), Decimal("0")),
                taker_sell_base_volume=sum((row.taker_sell_base_volume or Decimal("0") for row in rows), Decimal("0")),
                taker_buy_quote_volume=sum((row.taker_buy_quote_volume or Decimal("0") for row in rows), Decimal("0")),
                taker_sell_quote_volume=sum((row.taker_sell_quote_volume or Decimal("0") for row in rows), Decimal("0")),
            )
        )
    return output


def floor_time(value: datetime, minutes: int) -> datetime:
    day_start = value.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((value - day_start).total_seconds() // 60)
    floored = elapsed - (elapsed % minutes)
    return day_start + timedelta(minutes=floored)


def calculate_atr(candles: list[TimeframeCandle], period: int = 14) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    window = candles[-(period + 1) :]
    true_ranges: list[Decimal] = []
    for index in range(1, len(window)):
        candle = window[index]
        prev_close = window[index - 1].close
        true_ranges.append(max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close)))
    return sum(true_ranges, Decimal("0")) / Decimal(period)


class MultiTimeframeFeatureService:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_active_symbols(self, limit: int | None = None) -> list[str]:
        with closing(self.connect()) as conn:
            query = "SELECT symbol FROM marketlab_active_universe WHERE is_active = 1 ORDER BY rank ASC"
            if limit:
                query += f" LIMIT {int(limit)}"
            return [row["symbol"] for row in conn.execute(query).fetchall()]

    def get_timeframe_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        market: str = "futures",
    ) -> list[TimeframeCandle]:
        if timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        with closing(self.connect()) as conn:
            rows = self._load_aggregate(conn, symbol, timeframe, start, end, market)
            if rows:
                return rows
            if timeframe == "15m":
                return []
            raw_15m = self._load_aggregate(conn, symbol, "15m", start, end, market)
            return aggregate_candles(raw_15m, timeframe)

    def latest_feature_snapshot(self, symbol: str, timeframe: str) -> FeatureSnapshot:
        with closing(self.connect()) as conn:
            candles = self._load_aggregate(conn, symbol, timeframe, None, None, "futures")
            if not candles and timeframe != "15m":
                candles = aggregate_candles(self._load_aggregate(conn, symbol, "15m", None, None, "futures"), timeframe)
            if not candles:
                return empty_snapshot(symbol, timeframe, "MISSING_CANDLES")
            lookback = LOOKBACKS[timeframe]
            min_lookback = MIN_LOOKBACKS[timeframe]
            current = candles[-1]
            history = candles[-(lookback + 1) :]
            status_reasons: list[str] = []
            feature_status = "READY"
            if len(history) < min_lookback + 1:
                feature_status = "MISSING_CANDLES"
                status_reasons.append("not enough candles for lookback")
            prev_volumes = [row.volume for row in history[:-1] if row.volume is not None]
            avg_volume = sum(prev_volumes, Decimal("0")) / Decimal(len(prev_volumes)) if prev_volumes else None
            volume_ratio = current.volume / avg_volume if avg_volume and avg_volume > 0 else None
            volume_spike = volume_ratio is not None and volume_ratio >= Decimal("1.5")
            price_return = _pct_change(current.open, current.close)
            taker_total = (current.taker_buy_base_volume or Decimal("0")) + (current.taker_sell_base_volume or Decimal("0"))
            taker_buy_ratio = current.taker_buy_base_volume / taker_total if taker_total > 0 and current.taker_buy_base_volume is not None else None
            taker_sell_ratio = current.taker_sell_base_volume / taker_total if taker_total > 0 and current.taker_sell_base_volume is not None else None
            high_low_range = current.high - current.low
            range_pct = high_low_range / current.open * Decimal("100") if current.open else None
            close_position = (current.close - current.low) / high_low_range if high_low_range else None
            atr = calculate_atr(history)
            atr_pct = atr / current.close * Decimal("100") if atr and current.close else None
            if atr is None:
                feature_status = _worse_feature_status(feature_status, "MISSING_ATR")
                status_reasons.append("missing ATR lookback")
            oi_start = self._open_interest_near(conn, symbol, current.open_time)
            oi_end = self._open_interest_near(conn, symbol, current.close_time)
            oi_change = (oi_end - oi_start) if oi_start is not None and oi_end is not None else None
            oi_change_pct = oi_change / oi_start * Decimal("100") if oi_change is not None and oi_start else None
            if oi_change is None:
                feature_status = _worse_feature_status(feature_status, "MISSING_OI")
                status_reasons.append("missing OI")
            funding_rate = self._funding_near(conn, symbol, current.close_time)
            funding_pressure = _funding_pressure(funding_rate)
            if funding_rate is None:
                feature_status = _worse_feature_status(feature_status, "PARTIAL_DATA")
                status_reasons.append("missing funding")
            spot_snapshot = self._spot_context(conn, symbol, timeframe, current, avg_volume)
            if spot_snapshot["spot_context"] == "MISSING_OR_INCOMPLETE":
                feature_status = _worse_feature_status(feature_status, "PARTIAL_DATA")
                status_reasons.append("missing spot context")
            futures_led_flag = bool(price_return and abs(price_return) >= Decimal("0.25") and volume_spike and oi_change_pct is not None and oi_change_pct > 0)
            spot_led_flag = spot_snapshot["spot_volume_spike"] is True and not futures_led_flag
            mixed_flow_flag = futures_led_flag and spot_led_flag
            benchmark_return = self._benchmark_return(conn, timeframe, current.close_time)
            relative_return = price_return - benchmark_return if price_return is not None and benchmark_return is not None else None
            relative_strength = _relative_strength(relative_return)
            if benchmark_return is None:
                feature_status = _worse_feature_status(feature_status, "PARTIAL_DATA")
                status_reasons.append("missing benchmark return")
            return FeatureSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                window_start=current.open_time,
                window_end=current.close_time,
                price_return=price_return,
                price_return_abs=abs(price_return) if price_return is not None else None,
                volume_sum=current.volume,
                volume_ratio_vs_lookback=volume_ratio,
                volume_spike=volume_spike,
                kline_taker_buy_ratio=taker_buy_ratio,
                kline_taker_sell_ratio=taker_sell_ratio,
                kline_taker_buy_base=current.taker_buy_base_volume,
                kline_taker_sell_base=current.taker_sell_base_volume,
                oi_change=oi_change,
                oi_change_pct=oi_change_pct,
                funding_rate=funding_rate,
                funding_pressure=funding_pressure,
                high_low_range=high_low_range,
                range_pct=range_pct,
                close_position_in_range=close_position,
                atr=atr,
                atr_pct=atr_pct,
                futures_volume_spike=volume_spike,
                spot_volume_spike=spot_snapshot["spot_volume_spike"],
                oi_expansion=oi_change_pct is not None and oi_change_pct > 0,
                price_move_with_oi=price_return is not None and oi_change_pct is not None and abs(price_return) >= Decimal("0.25") and oi_change_pct > 0,
                futures_led_flag=futures_led_flag,
                spot_led_flag=spot_led_flag,
                mixed_flow_flag=mixed_flow_flag,
                spot_context=spot_snapshot["spot_context"],
                benchmark_return=benchmark_return,
                symbol_return=price_return,
                relative_return=relative_return,
                relative_strength=relative_strength,
                feature_status=feature_status,
                status_reasons=status_reasons,
            )

    def build_snapshots(self, symbols: list[str], timeframes: list[str]) -> list[dict[str, Any]]:
        return [self.latest_feature_snapshot(symbol, timeframe).to_dict() for symbol in symbols for timeframe in timeframes]

    def _load_aggregate(
        self,
        conn: sqlite3.Connection,
        symbol: str,
        timeframe: str,
        start: datetime | None,
        end: datetime | None,
        market: str,
    ) -> list[TimeframeCandle]:
        table = AGG_TABLES[market][timeframe]
        params: list[Any] = [symbol]
        where = ["symbol = ?", "aggregation_status = 'AGG_READY'"]
        if start is not None:
            where.append("open_time >= ?")
            params.append(start.isoformat(sep=" "))
        if end is not None:
            where.append("close_time <= ?")
            params.append(end.isoformat(sep=" "))
        columns = self._table_columns(conn, table)
        taker_selects = [
            column if column in columns else f"NULL AS {column}"
            for column in (
                "taker_buy_base_volume",
                "taker_sell_base_volume",
                "taker_buy_quote_volume",
                "taker_sell_quote_volume",
            )
        ]
        rows = conn.execute(
            f"""
            SELECT symbol, open_time, close_time, open, high, low, close, volume, quote_volume, number_of_trades,
                   {", ".join(taker_selects)}
            FROM {table}
            WHERE {" AND ".join(where)}
            ORDER BY open_time ASC
            """,
            params,
        ).fetchall()
        return [
            TimeframeCandle(
                symbol=row["symbol"],
                open_time=parse_dt(row["open_time"]),
                close_time=parse_dt(row["close_time"]),
                open=dec(row["open"]),
                high=dec(row["high"]),
                low=dec(row["low"]),
                close=dec(row["close"]),
                volume=dec(row["volume"] or 0),
                quote_volume=dec(row["quote_volume"]) if row["quote_volume"] is not None else None,
                number_of_trades=row["number_of_trades"],
                taker_buy_base_volume=dec(row["taker_buy_base_volume"]) if row["taker_buy_base_volume"] is not None else None,
                taker_sell_base_volume=dec(row["taker_sell_base_volume"]) if row["taker_sell_base_volume"] is not None else None,
                taker_buy_quote_volume=dec(row["taker_buy_quote_volume"]) if row["taker_buy_quote_volume"] is not None else None,
                taker_sell_quote_volume=dec(row["taker_sell_quote_volume"]) if row["taker_sell_quote_volume"] is not None else None,
            )
            for row in rows
        ]

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _open_interest_near(self, conn: sqlite3.Connection, symbol: str, when: datetime) -> Decimal | None:
        row = conn.execute(
            """
            SELECT sum_open_interest
            FROM futures_open_interest_history
            WHERE symbol = ? AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (symbol, when.isoformat(sep=" ")),
        ).fetchone()
        return dec(row["sum_open_interest"]) if row and row["sum_open_interest"] is not None else None

    def _funding_near(self, conn: sqlite3.Connection, symbol: str, when: datetime) -> Decimal | None:
        row = conn.execute(
            """
            SELECT funding_rate
            FROM futures_funding_history
            WHERE symbol = ? AND funding_time <= ?
            ORDER BY funding_time DESC
            LIMIT 1
            """,
            (symbol, when.isoformat(sep=" ")),
        ).fetchone()
        return dec(row["funding_rate"]) if row and row["funding_rate"] is not None else None

    def _spot_context(
        self,
        conn: sqlite3.Connection,
        symbol: str,
        timeframe: str,
        current: TimeframeCandle,
        futures_avg_volume: Decimal | None,
    ) -> dict[str, Any]:
        spot = self._load_aggregate(conn, symbol, timeframe, current.open_time, current.close_time, "spot")
        if not spot:
            return {"spot_volume_spike": None, "spot_context": "MISSING_OR_INCOMPLETE"}
        spot_current = spot[-1]
        spot_prev = self._load_aggregate(conn, symbol, timeframe, None, current.open_time, "spot")[-LOOKBACKS[timeframe] :]
        avg_spot = (
            sum((row.volume for row in spot_prev), Decimal("0")) / Decimal(len(spot_prev))
            if spot_prev
            else None
        )
        spot_ratio = spot_current.volume / avg_spot if avg_spot and avg_spot > 0 else None
        spot_spike = spot_ratio is not None and spot_ratio >= Decimal("1.5")
        if spot_spike and futures_avg_volume and current.volume <= futures_avg_volume:
            context = "SPOT_LED"
        elif spot_spike:
            context = "SPOT_SUPPORTING"
        else:
            context = "SPOT_PRESENT"
        return {"spot_volume_spike": spot_spike, "spot_context": context}

    def _benchmark_return(self, conn: sqlite3.Connection, timeframe: str, close_time: datetime) -> Decimal | None:
        btc = self._load_aggregate(conn, "BTCUSDT", timeframe, None, close_time, "futures")
        if btc:
            candle = btc[-1]
            return _pct_change(candle.open, candle.close)
        table = AGG_TABLES["futures"][timeframe]
        rows = conn.execute(
            f"""
            SELECT open, close
            FROM {table}
            WHERE close_time = ? AND aggregation_status = 'AGG_READY'
            """,
            (close_time.isoformat(sep=" "),),
        ).fetchall()
        returns = [_pct_change(dec(row["open"]), dec(row["close"])) for row in rows if row["open"]]
        return Decimal(str(median(returns))) if returns else None


def empty_snapshot(symbol: str, timeframe: str, status: str) -> FeatureSnapshot:
    return FeatureSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        window_start=None,
        window_end=None,
        price_return=None,
        price_return_abs=None,
        volume_sum=None,
        volume_ratio_vs_lookback=None,
        volume_spike=False,
        kline_taker_buy_ratio=None,
        kline_taker_sell_ratio=None,
        kline_taker_buy_base=None,
        kline_taker_sell_base=None,
        oi_change=None,
        oi_change_pct=None,
        funding_rate=None,
        funding_pressure="UNKNOWN",
        high_low_range=None,
        range_pct=None,
        close_position_in_range=None,
        atr=None,
        atr_pct=None,
        futures_volume_spike=False,
        spot_volume_spike=None,
        oi_expansion=False,
        price_move_with_oi=False,
        futures_led_flag=False,
        spot_led_flag=False,
        mixed_flow_flag=False,
        spot_context="MISSING_OR_INCOMPLETE",
        benchmark_return=None,
        symbol_return=None,
        relative_return=None,
        relative_strength="UNKNOWN",
        feature_status=status,
        status_reasons=[status.lower()],
    )


def _pct_change(start: Decimal, end: Decimal) -> Decimal | None:
    if start == 0:
        return None
    return (end - start) / start * Decimal("100")


def _funding_pressure(rate: Decimal | None) -> str:
    if rate is None:
        return "UNKNOWN"
    if rate >= Decimal("0.0005"):
        return "POSITIVE_PRESSURE"
    if rate <= Decimal("-0.0005"):
        return "NEGATIVE_PRESSURE"
    return "NEUTRAL"


def _relative_strength(relative_return: Decimal | None) -> str:
    if relative_return is None:
        return "UNKNOWN"
    if relative_return >= Decimal("0.5"):
        return "OUTPERFORMING"
    if relative_return <= Decimal("-0.5"):
        return "UNDERPERFORMING"
    return "INLINE_WITH_MARKET"


def _worse_feature_status(current: str, candidate: str) -> str:
    priority = {
        "READY": 0,
        "PARTIAL_DATA": 1,
        "MISSING_OI": 2,
        "MISSING_ATR": 3,
        "MISSING_CANDLES": 4,
        "STALE_DATA": 5,
    }
    return candidate if priority[candidate] > priority[current] else current
