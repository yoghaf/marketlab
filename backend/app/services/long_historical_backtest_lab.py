from __future__ import annotations

import sqlite3
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from app.services.multitimeframe_features import DEFAULT_DB_PATH, REPO_ROOT
from app.services.signal_candidate_performance import (
    COMPLETED_OUTCOMES,
    _realistic_assumptions,
    _realistic_result_fields,
)
from app.services.signal_factory_v2_scoring import (
    calculate_evidence_score,
    calculate_entry_sl_tp,
    check_execution_risk,
)
from app.services.signal_performance_snapshot import (
    LONG_DEFINITION_FAMILIES,
    _long_definition_classification,
)
from app.services.structure_zone_shadow import (
    ZONE_CONFIGS,
    ZoneCandle,
    evaluate_directional_structure,
)
from app.services.utils import json_safe


DEFAULT_LONG_HISTORICAL_BACKTEST_PATH = (
    REPO_ROOT / "backend" / "artifacts" / "signal_performance" / "live" / "long_historical_backtest_1h.json"
)
LOOKBACK_1H = 24
MIN_LOOKBACK_1H = 15
RAW_LONG_MIN_TAKER_BUY = Decimal("0.55")
RAW_LONG_MIN_CLOSE_POSITION = Decimal("0.65")
RAW_LONG_MIN_PRICE_RETURN = Decimal("0")
LONG_HISTORICAL_CLOSED_OUTCOMES = COMPLETED_OUTCOMES | {"TIMEOUT_EXIT"}


@dataclass(frozen=True)
class Candle:
    symbol: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal | None
    number_of_trades: int | None
    taker_buy_base_volume: Decimal | None
    taker_sell_base_volume: Decimal | None


@dataclass(frozen=True)
class Point:
    timestamp: datetime
    value: Decimal


class LongHistoricalBacktestLab:
    """Replay long-definition proxy rules from DB candles, not from logged signals."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def run(
        self,
        *,
        output_path: Path = DEFAULT_LONG_HISTORICAL_BACKTEST_PATH,
        active_only: bool = False,
        position_lock: bool = True,
        since_days: int | None = None,
        latest_limit: int = 300,
    ) -> dict[str, Any]:
        report = self.build(
            active_only=active_only,
            position_lock=position_lock,
            since_days=since_days,
            latest_limit=latest_limit,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp_path.write_text(_json_dumps(report), encoding="utf-8")
        tmp_path.replace(output_path)
        return report

    def build(
        self,
        *,
        active_only: bool = False,
        position_lock: bool = True,
        since_days: int | None = None,
        latest_limit: int = 300,
    ) -> dict[str, Any]:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            active = _load_active_universe(conn)
            symbols = _load_symbols(conn, active_only=active_only, active=active)
            latest_candle_time = _latest_close_time(conn, "futures_klines_1h", symbols)
            since_cutoff = (
                latest_candle_time - timedelta(days=max(1, since_days))
                if latest_candle_time is not None and since_days is not None
                else None
            )
            structure_lookback = ZONE_CONFIGS["1h"].lookback + ZONE_CONFIGS["1h"].independent_touch_gap
            candle_load_cutoff = (
                since_cutoff - max(structure_lookback, timedelta(hours=LOOKBACK_1H + 1))
                if since_cutoff is not None
                else None
            )
            evidence_load_cutoff = since_cutoff - timedelta(days=31) if since_cutoff is not None else None
            futures_1h = _load_candles(conn, "futures_klines_1h", symbols=symbols, start_time=candle_load_cutoff)
            futures_15m = _load_candles(conn, "futures_klines_15m", symbols=symbols, start_time=since_cutoff)
            spot_1h = (
                _load_candles(conn, "spot_klines_1h", symbols=symbols, start_time=candle_load_cutoff)
                if _has_table(conn, "spot_klines_1h")
                else {}
            )
            oi = _load_points(
                conn,
                "futures_open_interest_history",
                "timestamp",
                "sum_open_interest",
                symbols,
                start_time=evidence_load_cutoff,
            )
            funding = _load_points(
                conn,
                "futures_funding_history",
                "funding_time",
                "funding_rate",
                symbols,
                start_time=evidence_load_cutoff,
            )
            rich = _load_rich_alignment(conn, symbols, start_time=since_cutoff)
            state = _load_market_state_alignment(conn, symbols, start_time=since_cutoff)
        finally:
            conn.close()

        events: list[dict[str, Any]] = []
        raw_candidates = 0
        skipped = Counter()
        locked_until: dict[str, datetime | None] = {}

        for symbol in sorted(futures_1h):
            candles = futures_1h[symbol]
            future_15m = futures_15m.get(symbol, [])
            future_15m_open_times = [c.open_time for c in future_15m]
            zone_candles = [
                ZoneCandle(c.open_time, c.close_time, c.open, c.high, c.low, c.close)
                for c in candles
            ]
            zone_close_times = [c.close_time for c in zone_candles]
            for index, current in enumerate(candles):
                if since_cutoff is not None and current.close_time < since_cutoff:
                    skipped["BEFORE_SINCE_WINDOW"] += 1
                    continue
                if index + 1 < MIN_LOOKBACK_1H:
                    skipped["WARMUP_CANDLES"] += 1
                    continue
                if not _is_raw_long_candle(current):
                    continue
                feature = _feature_for_candle(
                    symbol=symbol,
                    candles=candles,
                    index=index,
                    spot_candles=spot_1h.get(symbol, []),
                    oi_points=oi.get(symbol, []),
                    funding_points=funding.get(symbol, []),
                    rich_map=rich,
                    state_map=state,
                )
                if not _is_raw_long_feature(feature):
                    continue
                raw_candidates += 1
                locked = locked_until.get(symbol)
                if position_lock and locked is not None and current.close_time < locked:
                    skipped["POSITION_LOCKED"] += 1
                    continue
                structure = _structure_for_candle(
                    symbol=symbol,
                    signal_time=current.close_time,
                    entry=current.close,
                    zone_candles=zone_candles,
                    zone_close_times=zone_close_times,
                )
                event = _event_from_feature(
                    feature=feature,
                    current=current,
                    structure=structure,
                    future_15m=future_15m,
                    future_15m_open_times=future_15m_open_times,
                    active=active.get(symbol),
                    latest_candle_time=latest_candle_time,
                )
                if event["result_status"] == "INVALID_RISK":
                    skipped["INVALID_RISK"] += 1
                    continue
                events.append(event)
                if position_lock:
                    if event["result_status"] in LONG_HISTORICAL_CLOSED_OUTCOMES and event.get("result_time_utc"):
                        locked_until[symbol] = _parse_dt(event["result_time_utc"])
                    else:
                        locked_until[symbol] = None

        family_rows = _family_rows(events, raw_candidates)
        candidate_rows = [row for row in family_rows if row["family_role"] == "candidate"]
        rejection_rows = [row for row in family_rows if row["family_role"] == "reject"]
        latest_items = sorted(events, key=lambda item: str(item.get("signal_timestamp") or ""), reverse=True)[:latest_limit]
        best_candidate = _best_family(candidate_rows)
        worst_bucket = _worst_family(rejection_rows)
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "artifact_type": "long_1h_historical_backtest_v1",
            "lab_id": "LONG_1H_HISTORICAL_BACKTEST_V1",
            "scope": "all_available_1h_futures_candles_replayed_from_db",
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "production_rule_change": False,
            "db_path": str(self.db_path),
            "filters": {
                "timeframe": "1h",
                "direction": "LONG",
                "active_only": active_only,
                "position_lock": position_lock,
                "since_days": since_days,
                "since_cutoff_utc": since_cutoff,
                "since_cutoff_wib": _wib(since_cutoff),
                "source": "futures_klines_1h + futures_klines_15m + evidence tables",
                "raw_long_definition": (
                    "price_return > 0, close_position >= 0.65, taker_buy >= 55% when available, "
                    "ATR available, then Long Definition V2 family mapping"
                ),
            },
            "coverage": {
                "symbol_count": len(symbols),
                "active_symbol_count": len(active),
                "futures_1h_candle_count": sum(len(rows) for rows in futures_1h.values()),
                "futures_15m_candle_count": sum(len(rows) for rows in futures_15m.values()),
                "raw_long_candidate_count_before_lock": raw_candidates,
                "events_evaluated_after_lock": len(events),
                "skipped": dict(skipped),
                "latest_futures_1h_close_time": latest_candle_time,
                "latest_futures_1h_close_time_wib": _wib(latest_candle_time),
            },
            "summary": {
                "read": _report_read(best_candidate, worst_bucket, len(events)),
                "best_candidate_family": best_candidate,
                "worst_rejection_bucket": worst_bucket,
                "candidate_family_count": sum(1 for row in candidate_rows if int(row.get("sample_count") or 0) > 0),
                "rejection_bucket_count": sum(1 for row in rejection_rows if int(row.get("sample_count") or 0) > 0),
                "next_action": (
                    "Use historical replay to decide which long family deserves shadow forward logging; "
                    "do not promote until it also survives forward samples."
                ),
            },
            "family_definitions": list(LONG_DEFINITION_FAMILIES),
            "family_rows": family_rows,
            "candidate_rows": candidate_rows,
            "rejection_rows": rejection_rows,
            "latest_items": latest_items,
            "guardrails": [
                "This is a historical replay from DB candles, not a live signal rule.",
                "Entry is futures 1h close; spot and rich data are evidence only.",
                "Outcome uses available futures 15m candles after entry, matching paper-live directionality.",
                "TP/SL geometry uses the current V2 read-only entry reference model for comparability.",
                "No Signal Factory, scanner, TP/SL, outcome, or execution code is changed by this artifact.",
            ],
        }


def _event_from_feature(
    *,
    feature: dict[str, Any],
    current: Candle,
    structure: dict[str, Any],
    future_15m: list[Candle],
    future_15m_open_times: list[datetime],
    active: dict[str, Any] | None,
    latest_candle_time: datetime | None,
) -> dict[str, Any]:
    feature.update(_structure_fields(structure))
    family = _long_definition_classification({"evidence_snapshot": feature, **feature})
    evidence = calculate_evidence_score(feature, "LONG")
    risk_gate = check_execution_risk(feature)
    entry_plan = calculate_entry_sl_tp(feature, "LONG", "MID_LONG", evidence.confidence_tier)
    entry = entry_plan.entry_price or current.close
    stop = entry_plan.stop_loss_reference
    target = entry_plan.take_profit_reference
    signal_id = f"hist-long-v1:{feature['symbol']}:{current.close_time.isoformat()}"
    base = {
        "signal_id": signal_id,
        "symbol": feature["symbol"],
        "timeframe": "1h",
        "signal_timestamp": current.close_time,
        "signal_time_wib": _wib(current.close_time),
        "window_open_time": current.open_time,
        "window_close_time": current.close_time,
        "direction": "LONG",
        "stage": family["family_id"],
        "candidate_status": "HISTORICAL_LONG_PROXY",
        "family_id": family["family_id"],
        "family_label": family["family_label"],
        "family_role": family["family_role"],
        "family_reason": family["family_reason"],
        "crowding_flags": family["crowding_flags"],
        "anti_chase_flags": family["anti_chase_flags"],
        "source_stage": "HISTORICAL_REPLAY",
        "confidence_tier": evidence.confidence_tier,
        "execution_flag": risk_gate.execution,
        "core_score": None,
        "evidence_score": evidence.score,
        "evidence_data_completeness": evidence.data_completeness,
        "evidence_snapshot": feature,
        "entry": entry,
        "stop_loss": stop,
        "take_profit": target,
        "rr": entry_plan.rr,
        "timeout_minutes": entry_plan.timeout_minutes,
        "risk": abs(entry - stop) if stop is not None else None,
        "entry_market": "futures",
        "entry_price_source": "futures_klines_1h.close",
        "active_universe": bool(active),
        "collection_tier": (active or {}).get("collection_tier"),
        "universe_rank": (active or {}).get("rank"),
        "result_status": "WAITING_DATA",
        "result_time_utc": None,
        "result_time_wib": None,
        "exit_price": None,
        "realized_r": None,
        "unrealized_r": None,
        "realistic_realized_r": None,
        "realistic_unrealized_r": None,
        "mfe_r": None,
        "mae_r": None,
        "latest_evaluation_candle_time": latest_candle_time,
        "latest_evaluation_candle_time_wib": _wib(latest_candle_time),
        "not_live_signal": True,
        "not_execution_instruction": True,
    }
    base.update(_flat_evidence_fields(feature))
    if stop is None or target is None or base["risk"] is None or base["risk"] <= 0:
        return {**base, "result_status": "INVALID_RISK"}
    assumptions = _realistic_assumptions(entry=entry, risk=base["risk"], evidence_snapshot=feature)
    base = {**base, **assumptions}
    return _evaluate_forward_path(
        base,
        entry=entry,
        stop=stop,
        target=target,
        future_15m=future_15m,
        open_times=future_15m_open_times,
        timeout_minutes=entry_plan.timeout_minutes,
    )


def _evaluate_forward_path(
    base: dict[str, Any],
    *,
    entry: Decimal,
    stop: Decimal,
    target: Decimal,
    future_15m: list[Candle],
    open_times: list[datetime],
    timeout_minutes: int | None = None,
) -> dict[str, Any]:
    signal_time = _parse_dt(base["signal_timestamp"])
    risk = abs(entry - stop)
    start = bisect_left(open_times, signal_time)
    deadline = signal_time + timedelta(minutes=timeout_minutes) if timeout_minutes and timeout_minutes > 0 else None
    window: list[Candle] = []
    for candle in future_15m[start:]:
        if deadline is not None and candle.close_time > deadline:
            break
        window.append(candle)
    if not window:
        return base
    mfe = Decimal("0")
    mae = Decimal("0")
    for index, candle in enumerate(window, start=1):
        tp_hit = candle.high >= target
        sl_hit = candle.low <= stop
        mfe = max(mfe, (candle.high - entry) / risk)
        mae = min(mae, (candle.low - entry) / risk)
        if tp_hit and sl_hit:
            realistic = _realistic_result_fields(
                base,
                entry=entry,
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
                "result_time_wib": _wib(candle.close_time),
                "exit_price": candle.close,
                "realized_r": Decimal("0"),
                **realistic,
                "mfe_r": mfe,
                "mae_r": mae,
                "candles_seen": index,
            }
        if tp_hit:
            ideal_r = abs(target - entry) / risk
            realistic = _realistic_result_fields(
                base,
                entry=entry,
                exit_reference=target,
                risk=risk,
                direction="LONG",
                ideal_status="TP_HIT",
                ideal_r=ideal_r,
            )
            return {
                **base,
                "result_status": "TP_HIT",
                "result_time_utc": candle.close_time,
                "result_time_wib": _wib(candle.close_time),
                "exit_price": target,
                "realized_r": ideal_r,
                **realistic,
                "mfe_r": mfe,
                "mae_r": mae,
                "candles_seen": index,
            }
        if sl_hit:
            realistic = _realistic_result_fields(
                base,
                entry=entry,
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
                "result_time_wib": _wib(candle.close_time),
                "exit_price": stop,
                "realized_r": Decimal("-1"),
                **realistic,
                "mfe_r": mfe,
                "mae_r": mae,
                "candles_seen": index,
            }
    latest = window[-1]
    unrealized = (latest.close - entry) / risk
    if deadline is not None and latest.close_time >= deadline:
        realistic = _realistic_result_fields(
            base,
            entry=entry,
            exit_reference=latest.close,
            risk=risk,
            direction="LONG",
            ideal_status="TIMEOUT_EXIT",
            ideal_r=unrealized,
        )
        return {
            **base,
            "result_status": "TIMEOUT_EXIT",
            "result_time_utc": latest.close_time,
            "result_time_wib": _wib(latest.close_time),
            "exit_price": latest.close,
            "realized_r": unrealized,
            **realistic,
            "mfe_r": mfe,
            "mae_r": mae,
            "candles_seen": len(window),
        }
    realistic = _realistic_result_fields(
        base,
        entry=entry,
        exit_reference=latest.close,
        risk=risk,
        direction="LONG",
        ideal_status="OPEN",
        ideal_r=unrealized,
        realized=False,
    )
    return {
        **base,
        "result_status": "OPEN",
        "result_time_utc": latest.close_time,
        "result_time_wib": _wib(latest.close_time),
        "exit_price": latest.close,
        "unrealized_r": unrealized,
        **realistic,
        "mfe_r": mfe,
        "mae_r": mae,
        "candles_seen": len(window),
    }


def _feature_for_candle(
    *,
    symbol: str,
    candles: list[Candle],
    index: int,
    spot_candles: list[Candle],
    oi_points: list[Point],
    funding_points: list[Point],
    rich_map: dict[tuple[str, datetime, datetime], dict[str, Any]],
    state_map: dict[tuple[str, datetime, datetime], dict[str, Any]],
) -> dict[str, Any]:
    current = candles[index]
    history = candles[max(0, index - LOOKBACK_1H) : index + 1]
    previous = history[:-1]
    avg_volume = sum((c.volume for c in previous), Decimal("0")) / Decimal(len(previous)) if previous else None
    volume_ratio = current.volume / avg_volume if avg_volume and avg_volume > 0 else None
    price_return = _pct_change(current.open, current.close)
    taker_total = (current.taker_buy_base_volume or Decimal("0")) + (current.taker_sell_base_volume or Decimal("0"))
    taker_buy_ratio = current.taker_buy_base_volume / taker_total if current.taker_buy_base_volume is not None and taker_total > 0 else None
    taker_sell_ratio = current.taker_sell_base_volume / taker_total if current.taker_sell_base_volume is not None and taker_total > 0 else None
    candle_range = current.high - current.low
    close_position = (current.close - current.low) / candle_range if candle_range > 0 else None
    range_pct = candle_range / current.open * Decimal("100") if current.open > 0 else None
    atr = _atr(history)
    atr_pct = atr / current.close * Decimal("100") if atr and current.close > 0 else None
    range_ratio = range_pct / atr_pct if range_pct is not None and atr_pct and atr_pct > 0 else None
    oi_start = _point_near(oi_points, current.open_time)
    oi_end = _point_near(oi_points, current.close_time)
    oi_change = oi_end - oi_start if oi_start is not None and oi_end is not None else None
    oi_change_pct = oi_change / oi_start * Decimal("100") if oi_change is not None and oi_start else None
    oi_mean, oi_std = _oi_change_stats(oi_points, current.close_time)
    oi_zscore = (oi_change_pct - oi_mean) / oi_std if oi_change_pct is not None and oi_mean is not None and oi_std else None
    funding = _point_near(funding_points, current.close_time)
    funding_percentile = _funding_percentile(funding_points, current.close_time, funding)
    spot_context = _spot_context(spot_candles, current, avg_volume)
    rich = rich_map.get((symbol, current.open_time, current.close_time), {})
    state = state_map.get((symbol, current.open_time, current.close_time), {})
    status_reasons = []
    feature_status = "READY"
    if len(history) < MIN_LOOKBACK_1H:
        feature_status = "MISSING_CANDLES"
        status_reasons.append("not enough 1h candles for ATR/lookback")
    if atr_pct is None:
        feature_status = "MISSING_ATR"
        status_reasons.append("missing ATR")
    if oi_change_pct is None:
        feature_status = "MISSING_OI"
        status_reasons.append("missing OI")
    if funding is None or spot_context["spot_context"] == "MISSING_OR_INCOMPLETE":
        feature_status = "PARTIAL_DATA" if feature_status == "READY" else feature_status
    futures_led = bool(price_return is not None and abs(price_return) >= Decimal("0.25") and volume_ratio is not None and volume_ratio >= Decimal("1.5") and oi_change_pct is not None and oi_change_pct > 0)
    return {
        "symbol": symbol,
        "timeframe": "1h",
        "window_start": current.open_time,
        "window_end": current.close_time,
        "price_return": price_return,
        "price_return_abs": abs(price_return) if price_return is not None else None,
        "entry_price": current.close,
        "volume_sum": current.volume,
        "volume_ratio_vs_lookback": volume_ratio,
        "volume_spike": volume_ratio is not None and volume_ratio >= Decimal("1.5"),
        "kline_taker_buy_ratio": taker_buy_ratio,
        "kline_taker_sell_ratio": taker_sell_ratio,
        "kline_taker_buy_base": current.taker_buy_base_volume,
        "kline_taker_sell_base": current.taker_sell_base_volume,
        "oi_change": oi_change,
        "oi_change_pct": oi_change_pct,
        "funding_rate": funding,
        "funding_percentile_30d": funding_percentile,
        "high_low_range": candle_range,
        "range_pct": range_pct,
        "range_ratio_vs_atr": range_ratio,
        "close_position_in_range": close_position,
        "atr": atr,
        "atr_pct": atr_pct,
        "atr_extension_normalized": abs(price_return) / atr_pct if price_return is not None and atr_pct and atr_pct > 0 else None,
        "price_atr_multiple": abs(price_return) / atr_pct if price_return is not None and atr_pct and atr_pct > 0 else None,
        "oi_change_mean_30d": oi_mean,
        "oi_change_std_30d": oi_std,
        "oi_zscore": oi_zscore,
        "futures_led_flag": futures_led,
        "spot_context": spot_context["spot_context"],
        "spot_volume_spike": spot_context["spot_volume_spike"],
        "global_long_short_ratio": rich.get("global_long_short_ratio_avg"),
        "top_trader_position_ratio": rich.get("top_trader_position_ratio_avg"),
        "top_trader_account_ratio": rich.get("top_trader_account_ratio_avg"),
        "rich_alignment_status": rich.get("alignment_status"),
        "futures_spread_pct": state.get("futures_spread_pct"),
        "spot_spread_pct": state.get("spot_spread_pct"),
        "snapshot_alignment_status": state.get("snapshot_alignment_status"),
        "feature_status": feature_status,
        "status_reasons": status_reasons,
    }


def _is_raw_long_feature(feature: dict[str, Any]) -> bool:
    price_return = _dec(feature.get("price_return"))
    close_position = _dec(feature.get("close_position_in_range"))
    taker_buy = _dec(feature.get("kline_taker_buy_ratio"))
    atr_pct = _dec(feature.get("atr_pct"))
    if price_return is None or price_return <= RAW_LONG_MIN_PRICE_RETURN:
        return False
    if close_position is None or close_position < RAW_LONG_MIN_CLOSE_POSITION:
        return False
    if taker_buy is not None and taker_buy < RAW_LONG_MIN_TAKER_BUY:
        return False
    return atr_pct is not None and atr_pct > 0


def _is_raw_long_candle(candle: Candle) -> bool:
    price_return = _pct_change(candle.open, candle.close)
    candle_range = candle.high - candle.low
    close_position = (candle.close - candle.low) / candle_range if candle_range > 0 else None
    taker_total = (candle.taker_buy_base_volume or Decimal("0")) + (candle.taker_sell_base_volume or Decimal("0"))
    taker_buy = candle.taker_buy_base_volume / taker_total if candle.taker_buy_base_volume is not None and taker_total > 0 else None
    if price_return is None or price_return <= RAW_LONG_MIN_PRICE_RETURN:
        return False
    if close_position is None or close_position < RAW_LONG_MIN_CLOSE_POSITION:
        return False
    if taker_buy is not None and taker_buy < RAW_LONG_MIN_TAKER_BUY:
        return False
    return True


def _structure_for_candle(
    *,
    symbol: str,
    signal_time: datetime,
    entry: Decimal,
    zone_candles: list[ZoneCandle],
    zone_close_times: list[datetime],
) -> dict[str, Any]:
    config = ZONE_CONFIGS["1h"]
    start = signal_time - config.lookback - config.independent_touch_gap
    left = bisect_left(zone_close_times, start)
    right = bisect_right(zone_close_times, signal_time)
    primary = evaluate_directional_structure(
        timeframe="1h",
        candles=zone_candles[left:right],
        signal_time=signal_time,
        direction="LONG",
        entry=entry,
    )
    return {
        "symbol": symbol,
        "signal_timeframe": "1h",
        "primary_timeframe": "1h",
        "primary": primary,
        "status": primary.get("status"),
        "reason": primary.get("reason"),
    }


def _structure_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    primary = snapshot.get("primary") if isinstance(snapshot, dict) else {}
    diagnostics = primary.get("breakout_state_diagnostics") if isinstance(primary, dict) else {}
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    return {
        "structure_zone_shadow": snapshot,
        "structure_zone_status": snapshot.get("status"),
        "structure_zone_reason": snapshot.get("reason"),
        "structure_zone_primary_state": primary.get("state"),
        "structure_zone_primary_reason": primary.get("reason"),
        "structure_zone_primary_zone_count": primary.get("zone_count"),
        "room_to_next_resistance_atr": diagnostics.get("room_to_next_resistance_atr"),
        "room_to_next_support_atr": diagnostics.get("room_to_next_support_atr"),
        "entry_distance_from_zone_atr": diagnostics.get("entry_distance_from_zone_atr"),
        "close_penetration_atr": diagnostics.get("close_penetration_atr"),
        "body_above_zone_ratio": diagnostics.get("body_above_zone_ratio"),
        "zone_touch_count": diagnostics.get("zone_touch_count"),
        "zone_age_bars": diagnostics.get("zone_age_bars"),
    }


def _flat_evidence_fields(feature: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "price_return",
        "volume_ratio_vs_lookback",
        "kline_taker_buy_ratio",
        "kline_taker_sell_ratio",
        "oi_change_pct",
        "oi_zscore",
        "funding_percentile_30d",
        "global_long_short_ratio",
        "top_trader_position_ratio",
        "top_trader_account_ratio",
        "atr_extension_normalized",
        "range_ratio_vs_atr",
        "room_to_next_resistance_atr",
        "room_to_next_support_atr",
        "entry_distance_from_zone_atr",
        "close_penetration_atr",
        "body_above_zone_ratio",
        "structure_zone_status",
        "structure_zone_primary_state",
        "structure_zone_primary_reason",
    )
    return {key: feature.get(key) for key in keys}


def _family_rows(events: list[dict[str, Any]], raw_candidates: int) -> list[dict[str, Any]]:
    specs = {spec["family_id"]: spec for spec in LONG_DEFINITION_FAMILIES}
    rows = []
    for family_id, spec in specs.items():
        items = [item for item in events if item.get("family_id") == family_id]
        perf = _perf(items)
        top_symbol, top_count = _top_symbol(items)
        rows.append(
            {
                "family_id": family_id,
                "family_label": spec["family_label"],
                "family_role": spec["family_role"],
                "description": spec["description"],
                "sample_count": len(items),
                "sample_retention_pct": _pct(len(items), raw_candidates),
                **perf,
                "top_symbol": top_symbol,
                "top_symbol_count": top_count,
                "top_symbol_share_pct": _pct(top_count, len(items)),
                "research_status": _family_status(perf, str(spec["family_role"])),
            }
        )
    return rows


def _perf(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(item.get("result_status")) for item in items)
    closed = [item for item in items if item.get("result_status") in LONG_HISTORICAL_CLOSED_OUTCOMES]
    tp = [item for item in closed if item.get("result_status") == "TP_HIT"]
    sl = [item for item in closed if item.get("result_status") == "SL_HIT"]
    timeout = [item for item in closed if item.get("result_status") == "TIMEOUT_EXIT"]
    r_values = [_dec(item.get("realistic_realized_r")) for item in closed if _dec(item.get("realistic_realized_r")) is not None]
    open_values = [_dec(item.get("realistic_unrealized_r")) for item in items if item.get("result_status") == "OPEN" and _dec(item.get("realistic_unrealized_r")) is not None]
    total = sum((value for value in r_values if value is not None), Decimal("0"))
    open_total = sum((value for value in open_values if value is not None), Decimal("0"))
    directional = len(tp) + len(sl)
    return {
        "signals_evaluated": len(items),
        "closed_count": len(closed),
        "open_count": counts.get("OPEN", 0),
        "waiting_count": counts.get("WAITING_DATA", 0),
        "tp_count": len(tp),
        "sl_count": len(sl),
        "timeout_count": len(timeout),
        "both_hit_count": counts.get("BOTH_HIT_SAME_CANDLE", 0),
        "winrate_pct": Decimal(len(tp)) / Decimal(directional) * Decimal("100") if directional else None,
        "realistic_total_r_closed": total,
        "realistic_open_unrealized_r": open_total,
        "realistic_total_r_with_open": total + open_total,
        "realistic_avg_r_closed": total / Decimal(len(r_values)) if r_values else None,
        "median_realistic_r_closed": Decimal(str(median(r_values))) if r_values else None,
        "max_realistic_drawdown_r": _drawdown([value for value in r_values if value is not None]),
    }


def _family_status(perf: dict[str, Any], role: str) -> str:
    closed = int(perf.get("closed_count") or 0)
    total = _dec(perf.get("realistic_total_r_closed")) or Decimal("0")
    avg = _dec(perf.get("realistic_avg_r_closed"))
    if closed < 20:
        return "SAMPLE_TOO_SMALL"
    if role == "reject":
        return "DAMAGE_BUCKET" if total < 0 else "REJECT_BUCKET_NOT_CONFIRMED"
    if role == "candidate" and total > 0 and avg is not None and avg > 0:
        return "LONG_RESEARCH_CANDIDATE"
    if role == "unknown":
        return "NEEDS_REDEFINITION"
    return "NO_LONG_EDGE_YET"


def _report_read(best: dict[str, Any] | None, worst: dict[str, Any] | None, event_count: int) -> str:
    if event_count == 0:
        return "NO_HISTORICAL_LONG_CANDIDATE"
    if best and best.get("research_status") == "LONG_RESEARCH_CANDIDATE":
        return "HISTORICAL_LONG_FAMILY_CANDIDATE_FOUND"
    if worst and (_dec(worst.get("realistic_total_r_closed")) or Decimal("0")) < 0:
        return "HISTORICAL_LONG_DAMAGE_BUCKETS_IDENTIFIED"
    return "HISTORICAL_LONG_INCONCLUSIVE"


def _best_family(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    readable = [row for row in rows if int(row.get("closed_count") or 0) >= 20]
    if not readable:
        return None
    return sorted(readable, key=lambda row: (_dec(row.get("realistic_avg_r_closed")) or Decimal("-999"), _dec(row.get("realistic_total_r_closed")) or Decimal("-999")), reverse=True)[0]


def _worst_family(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    readable = [row for row in rows if int(row.get("closed_count") or 0) >= 20]
    if not readable:
        return None
    return sorted(readable, key=lambda row: (_dec(row.get("realistic_avg_r_closed")) or Decimal("999"), _dec(row.get("realistic_total_r_closed")) or Decimal("999")))[0]


def _load_symbols(conn: sqlite3.Connection, *, active_only: bool, active: dict[str, dict[str, Any]]) -> list[str]:
    if active_only:
        return sorted(active)
    rows = conn.execute("SELECT DISTINCT symbol FROM futures_klines_1h WHERE aggregation_status = 'AGG_READY' ORDER BY symbol").fetchall()
    return [row["symbol"] for row in rows]


def _load_active_universe(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    if not _has_table(conn, "marketlab_active_universe"):
        return {}
    rows = conn.execute(
        "SELECT symbol, rank, collection_tier FROM marketlab_active_universe WHERE is_active = 1"
    ).fetchall()
    return {row["symbol"]: {"rank": row["rank"], "collection_tier": row["collection_tier"]} for row in rows}


def _load_candles(
    conn: sqlite3.Connection,
    table: str,
    *,
    symbols: list[str],
    start_time: datetime | None = None,
) -> dict[str, list[Candle]]:
    if not symbols or not _has_table(conn, table):
        return {}
    placeholders = ",".join("?" for _ in symbols)
    params: list[Any] = list(symbols)
    time_clause = ""
    if start_time is not None:
        time_clause = "AND close_time >= ?"
        params.append(_db_time(start_time))
    rows = conn.execute(
        f"""
        SELECT symbol, open_time, close_time, open, high, low, close, volume, quote_volume,
               number_of_trades, taker_buy_base_volume, taker_sell_base_volume
        FROM {table}
        WHERE aggregation_status = 'AGG_READY'
          AND symbol IN ({placeholders})
          AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL
          {time_clause}
        ORDER BY symbol, open_time
        """,
        params,
    ).fetchall()
    output: dict[str, list[Candle]] = defaultdict(list)
    for row in rows:
        output[row["symbol"]].append(
            Candle(
                symbol=row["symbol"],
                open_time=_parse_dt(row["open_time"]),
                close_time=_parse_dt(row["close_time"]),
                open=_dec(row["open"]) or Decimal("0"),
                high=_dec(row["high"]) or Decimal("0"),
                low=_dec(row["low"]) or Decimal("0"),
                close=_dec(row["close"]) or Decimal("0"),
                volume=_dec(row["volume"]) or Decimal("0"),
                quote_volume=_dec(row["quote_volume"]),
                number_of_trades=row["number_of_trades"],
                taker_buy_base_volume=_dec(row["taker_buy_base_volume"]),
                taker_sell_base_volume=_dec(row["taker_sell_base_volume"]),
            )
        )
    return dict(output)


def _load_points(
    conn: sqlite3.Connection,
    table: str,
    time_col: str,
    value_col: str,
    symbols: list[str],
    *,
    start_time: datetime | None = None,
) -> dict[str, list[Point]]:
    if not symbols or not _has_table(conn, table):
        return {}
    placeholders = ",".join("?" for _ in symbols)
    period_clause = "AND period = '5m'" if "period" in _table_columns(conn, table) else ""
    params: list[Any] = list(symbols)
    time_clause = ""
    if start_time is not None:
        time_clause = f"AND {time_col} >= ?"
        params.append(_db_time(start_time))
    rows = conn.execute(
        f"""
        SELECT symbol, {time_col} AS timestamp, {value_col} AS value
        FROM {table}
        WHERE symbol IN ({placeholders})
          {period_clause}
          AND {value_col} IS NOT NULL
          {time_clause}
        ORDER BY symbol, {time_col}
        """,
        params,
    ).fetchall()
    output: dict[str, list[Point]] = defaultdict(list)
    for row in rows:
        output[row["symbol"]].append(Point(timestamp=_parse_dt(row["timestamp"]), value=_dec(row["value"]) or Decimal("0")))
    return dict(output)


def _load_rich_alignment(
    conn: sqlite3.Connection,
    symbols: list[str],
    *,
    start_time: datetime | None = None,
) -> dict[tuple[str, datetime, datetime], dict[str, Any]]:
    if not symbols or not _has_table(conn, "rich_futures_5m_alignment"):
        return {}
    placeholders = ",".join("?" for _ in symbols)
    params: list[Any] = list(symbols)
    time_clause = ""
    if start_time is not None:
        time_clause = "AND window_close_time >= ?"
        params.append(_db_time(start_time))
    rows = conn.execute(
        f"""
        SELECT symbol, window_open_time, window_close_time, alignment_status,
               global_long_short_ratio_avg, top_trader_position_ratio_avg, top_trader_account_ratio_avg
        FROM rich_futures_5m_alignment
        WHERE timeframe = '1h' AND symbol IN ({placeholders})
          {time_clause}
        """,
        params,
    ).fetchall()
    return {
        (row["symbol"], _parse_dt(row["window_open_time"]), _parse_dt(row["window_close_time"])): {
            "alignment_status": row["alignment_status"],
            "global_long_short_ratio_avg": _dec(row["global_long_short_ratio_avg"]),
            "top_trader_position_ratio_avg": _dec(row["top_trader_position_ratio_avg"]),
            "top_trader_account_ratio_avg": _dec(row["top_trader_account_ratio_avg"]),
        }
        for row in rows
    }


def _load_market_state_alignment(
    conn: sqlite3.Connection,
    symbols: list[str],
    *,
    start_time: datetime | None = None,
) -> dict[tuple[str, datetime, datetime], dict[str, Any]]:
    if not symbols or not _has_table(conn, "market_state_alignment"):
        return {}
    placeholders = ",".join("?" for _ in symbols)
    params: list[Any] = list(symbols)
    time_clause = ""
    if start_time is not None:
        time_clause = "AND window_close_time >= ?"
        params.append(_db_time(start_time))
    rows = conn.execute(
        f"""
        SELECT symbol, window_open_time, window_close_time, snapshot_alignment_status, futures_spread_pct, spot_spread_pct
        FROM market_state_alignment
        WHERE timeframe = '1h' AND symbol IN ({placeholders})
          {time_clause}
        """,
        params,
    ).fetchall()
    return {
        (row["symbol"], _parse_dt(row["window_open_time"]), _parse_dt(row["window_close_time"])): {
            "snapshot_alignment_status": row["snapshot_alignment_status"],
            "futures_spread_pct": _dec(row["futures_spread_pct"]),
            "spot_spread_pct": _dec(row["spot_spread_pct"]),
        }
        for row in rows
    }


def _spot_context(spot_candles: list[Candle], current: Candle, futures_avg_volume: Decimal | None) -> dict[str, Any]:
    if not spot_candles:
        return {"spot_volume_spike": None, "spot_context": "MISSING_OR_INCOMPLETE"}
    opens = [c.open_time for c in spot_candles]
    pos = bisect_left(opens, current.open_time)
    if pos >= len(spot_candles) or spot_candles[pos].open_time != current.open_time:
        return {"spot_volume_spike": None, "spot_context": "MISSING_OR_INCOMPLETE"}
    previous = spot_candles[max(0, pos - LOOKBACK_1H) : pos]
    avg_spot = sum((c.volume for c in previous), Decimal("0")) / Decimal(len(previous)) if previous else None
    ratio = spot_candles[pos].volume / avg_spot if avg_spot and avg_spot > 0 else None
    spike = ratio is not None and ratio >= Decimal("1.5")
    if spike and futures_avg_volume and current.volume <= futures_avg_volume:
        context = "SPOT_LED"
    elif spike:
        context = "SPOT_SUPPORTING"
    else:
        context = "SPOT_PRESENT"
    return {"spot_volume_spike": spike, "spot_context": context}


def _point_near(points: list[Point], when: datetime) -> Decimal | None:
    if not points:
        return None
    times = [point.timestamp for point in points]
    index = bisect_right(times, when) - 1
    return points[index].value if index >= 0 else None


def _oi_change_stats(points: list[Point], when: datetime) -> tuple[Decimal | None, Decimal | None]:
    if len(points) < 3:
        return None, None
    start = when - timedelta(days=30)
    times = [point.timestamp for point in points]
    left = max(1, bisect_left(times, start))
    right = bisect_right(times, when)
    changes = []
    for index in range(left, right):
        previous = points[index - 1].value
        current = points[index].value
        if previous > 0:
            changes.append((current - previous) / previous * Decimal("100"))
    if len(changes) < 2:
        return None, None
    mean = sum(changes, Decimal("0")) / Decimal(len(changes))
    variance = sum(((value - mean) ** 2 for value in changes), Decimal("0")) / Decimal(len(changes))
    std = Decimal(str(float(variance) ** 0.5))
    return mean, std if std > 0 else None


def _funding_percentile(points: list[Point], when: datetime, current: Decimal | None) -> Decimal | None:
    if current is None or not points:
        return None
    start = when - timedelta(days=30)
    rates = [point.value for point in points if start <= point.timestamp <= when]
    if not rates:
        return None
    return Decimal(sum(1 for rate in rates if rate <= current)) / Decimal(len(rates)) * Decimal("100")


def _atr(candles: list[Candle]) -> Decimal | None:
    if len(candles) < 15:
        return None
    ranges = []
    for index, candle in enumerate(candles):
        if index == 0:
            ranges.append(candle.high - candle.low)
        else:
            prev_close = candles[index - 1].close
            ranges.append(max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close)))
    return sum(ranges[-14:], Decimal("0")) / Decimal("14")


def _pct_change(start: Decimal, end: Decimal) -> Decimal | None:
    if start == 0:
        return None
    return (end - start) / start * Decimal("100")


def _top_symbol(items: list[dict[str, Any]]) -> tuple[str | None, int]:
    if not items:
        return None, 0
    counter = Counter(str(item.get("symbol") or "") for item in items)
    return counter.most_common(1)[0]


def _drawdown(values: list[Decimal]) -> Decimal:
    equity = Decimal("0")
    peak = Decimal("0")
    worst = Decimal("0")
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def _pct(part: int, whole: int) -> Decimal | None:
    if whole <= 0:
        return None
    return Decimal(part) / Decimal(whole) * Decimal("100")


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _latest_close_time(conn: sqlite3.Connection, table: str, symbols: list[str]) -> datetime | None:
    if not symbols or not _has_table(conn, table):
        return None
    placeholders = ",".join("?" for _ in symbols)
    row = conn.execute(
        f"""
        SELECT MAX(close_time) AS latest
        FROM {table}
        WHERE aggregation_status = 'AGG_READY'
          AND symbol IN ({placeholders})
        """,
        symbols,
    ).fetchone()
    return _parse_dt(row["latest"]) if row and row["latest"] is not None else None


def _db_time(value: datetime) -> str:
    return f"{_parse_dt(value):%Y-%m-%d %H:%M:%S}"


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _wib(value: datetime | None) -> str | None:
    if value is None:
        return None
    return f"{(_parse_dt(value) + timedelta(hours=7)):%Y-%m-%d %H:%M:%S} WIB"


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(json_safe(value), indent=2, sort_keys=True)
