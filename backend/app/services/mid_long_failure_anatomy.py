from __future__ import annotations

import json
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.models.market import FuturesKline1h
from app.services.mid_long_geometry_validation import (
    ATR_MULTIPLIER,
    REWARD_RISK,
    Lab63Context,
    Lab63PreparedDataset,
    MidLongGeometryValidationService,
    _aggregate_policy,
    _evaluate_policy,
)
from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import _evidence_snapshot_from_mapping
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.structure_zone_shadow import StructureZoneShadowService
from app.services.utils import json_safe, utcnow


POLICY_ID = "TIMEOUT_120M"
TIMEOUT_MINUTES = 120
REGIME_CONFLICT_THRESHOLD_PCT = Decimal("-0.50")
NEAR_TARGET_R = Decimal("0.75")
FAVORABLE_MOVE_R = Decimal("0.25")
DEFAULT_ARTIFACT_PATH = (
    REPO_ROOT / "backend" / "artifacts" / "strategy_optimization" / "v1" / "mid_long_lab65.json"
)

TRAIN_THRESHOLD_FIELDS = (
    "atr_extension_normalized",
    "range_ratio_vs_atr",
    "price_atr_multiple",
    "futures_spread_pct",
)

ANATOMY_EVIDENCE_FIELDS = (
    "price_return",
    "close_position_in_range",
    "volume_ratio_vs_lookback",
    "range_ratio_vs_atr",
    "atr_extension_normalized",
    "price_atr_multiple",
    "kline_taker_buy_ratio",
    "kline_taker_sell_ratio",
    "oi_change_pct",
    "oi_zscore",
    "funding_percentile_30d",
    "futures_spread_pct",
    "global_long_short_ratio",
    "top_trader_position_ratio",
    "top_trader_account_ratio",
    "core_score",
    "evidence_score",
    "evidence_data_completeness",
)

CAUSE_METADATA = {
    "STOP_THEN_TARGET_WITHIN_4H": (
        "Stop dahulu, target kemudian",
        "Stop tersentuh, tetapi target awal kemudian tercapai pada candle berikutnya dalam empat jam.",
        "Uji penempatan stop atau entry timing secara shadow; jangan langsung melebarkan stop live.",
    ),
    "NEAR_TARGET_REVERSAL": (
        "Hampir target lalu reversal",
        "Harga sudah mencapai minimal +0.75R sebelum berbalik dan menyentuh stop.",
        "Uji profit protection atau target geometry secara shadow.",
    ),
    "FAVORABLE_THEN_REVERSAL": (
        "Sempat favorable lalu reversal",
        "Harga bergerak +0.25R sampai di bawah +0.75R sebelum berbalik ke stop.",
        "Teliti exit dinamis setelah follow-through awal tanpa memotong kelompok TP.",
    ),
    "IMMEDIATE_WRONG_DIRECTION": (
        "Salah arah langsung",
        "Stop tersentuh dalam dua candle 15m pertama tanpa gerak favorable minimal +0.25R.",
        "Cari evidence pre-entry atau konfirmasi awal yang membedakan kegagalan langsung.",
    ),
    "STRUCTURE_CONFLICT": (
        "Konflik structure zone",
        "Signal long masuk saat repeated support/resistance 1h atau 4h berkonflik dengan arah.",
        "Uji structure-zone conflict sebagai filter shadow dengan train/validation terpisah.",
    ),
    "REGIME_CONFLICT": (
        "Konflik regime BTC/ETH",
        "BTC atau ETH turun minimal 0.50% pada satu jam sebelum signal long.",
        "Uji regime conflict sebagai filter shadow, bukan sebagai pembalik arah otomatis.",
    ),
    "NO_FOLLOWTHROUGH": (
        "Tidak ada follow-through",
        "Tidak ada pola path, structure, atau regime tunggal yang lebih kuat sebelum loss.",
        "Bandingkan kombinasi evidence pre-entry dan candle konfirmasi pada LAB berikutnya.",
    ),
    "TIMEOUT_NEGATIVE_DRIFT": (
        "Timeout dengan drift negatif",
        "Posisi tidak menyentuh target/stop tetapi berakhir negatif saat batas 120 menit.",
        "Teliti kondisi yang membuat momentum long kehilangan follow-through sebelum timeout.",
    ),
    "COST_DOMINATED_TIMEOUT": (
        "Timeout positif ideal, negatif setelah biaya",
        "Harga timeout tidak negatif secara ideal, tetapi fee, spread, dan slippage mengubah hasil menjadi loss.",
        "Uji batas biaya/fill secara shadow tanpa mengubah arah signal.",
    ),
    "COST_DOMINATED_TP": (
        "Target tidak menutup biaya",
        "Target tersentuh tetapi risk terlalu kecil terhadap biaya realistis.",
        "Tahan geometry dengan cost-to-risk ekstrem sebelum promosi.",
    ),
    "AMBIGUOUS_BOTH_SAME_CANDLE": (
        "Target dan stop satu candle",
        "Urutan intrabar tidak diketahui sehingga hasil diperlakukan konservatif.",
        "Butuh resolusi lebih kecil untuk mengurangi ambiguitas; jangan mengasumsikan target lebih dulu.",
    ),
    "OTHER_REALISTIC_LOSS": (
        "Loss lain belum terklasifikasi",
        "Loss realistis tidak cocok dengan kategori utama yang tersedia.",
        "Audit contoh individual sebelum menambah kategori baru.",
    ),
}


class MidLongFailureAnatomyService:
    """Read-only failure anatomy for the fixed LAB-63 MID_LONG policy."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_failure_sample: int = 20,
        limit: int = 30,
        prepared_dataset: Lab63PreparedDataset | None = None,
    ) -> dict[str, Any]:
        prepared = prepared_dataset or MidLongGeometryValidationService(self.db).prepare_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
        )
        outcomes, skipped = _evaluate_policy(
            prepared.contexts,
            policy_id=POLICY_ID,
            timeout_minutes=TIMEOUT_MINUTES,
            position_lock=position_lock,
        )
        context_by_id = {context.signal.signal_id: context for context in prepared.contexts}
        signal_by_id = {signal.signal_id: signal for signal in prepared.signals}
        zone_snapshots = StructureZoneShadowService(self.db).snapshots_for_signals(
            [
                {
                    "signal_id": outcome["signal_id"],
                    "symbol": outcome["symbol"],
                    "signal_timestamp": outcome["signal_timestamp"],
                    "timeframe": "1h",
                    "direction": "LONG",
                    "entry": outcome.get("entry"),
                }
                for outcome in outcomes
            ]
        )
        regime_rows = self._load_regime_rows(prepared)
        train_thresholds = _train_thresholds(prepared)
        annotated = [
            _annotate_outcome(
                outcome,
                context=context_by_id[str(outcome["signal_id"])],
                signal=signal_by_id[str(outcome["signal_id"])],
                zone_snapshot=zone_snapshots.get(str(outcome["signal_id"])) or {},
                regime_rows=regime_rows,
                train_thresholds=train_thresholds,
            )
            for outcome in outcomes
            if str(outcome.get("signal_id")) in context_by_id
            and str(outcome.get("signal_id")) in signal_by_id
        ]
        failures = [row for row in annotated if row["is_realistic_loss"]]
        all_ids = {signal.signal_id for signal in prepared.signals}
        all_failures = failures
        train_failures = [row for row in failures if row["signal_id"] in prepared.train_ids]
        validation_failures = [row for row in failures if row["signal_id"] in prepared.validation_ids]
        cause_rows = _cause_rows(
            all_failures,
            train_failures=train_failures,
            validation_failures=validation_failures,
        )
        dominant = cause_rows[0] if cause_rows else None
        min_sample = max(1, min_failure_sample)

        return {
            "generated_at_utc": utcnow(),
            "lab": "LAB-65",
            "study_scope": "mid_long_1h_failure_anatomy",
            "read_only": True,
            "not_live_signal": True,
            "not_execution_instruction": True,
            "filters": {
                "epoch": prepared.epoch,
                "stage": "MID_LONG",
                "timeframe": "1h",
                "direction": "LONG",
                "include_watch_only": prepared.include_watch_only,
                "position_lock": position_lock,
                "min_failure_sample": min_sample,
                "limit": max(1, limit),
            },
            "policy": {
                "policy_id": POLICY_ID,
                "timeout_minutes": TIMEOUT_MINUTES,
                "atr_source": "ATR14 futures_klines_1h closed at or before signal",
                "atr_multiplier": ATR_MULTIPLIER,
                "reward_risk": REWARD_RISK,
                "forward_source": "contiguous closed AGG_READY futures_klines_15m",
                "realistic_model": "Binance taker fee + signal futures spread + slippage",
            },
            "split": {
                "method": "chronological_70_30",
                "source_signal_count": len(prepared.signals),
                "train_source_count": len(prepared.train_ids),
                "validation_source_count": len(prepared.validation_ids),
            },
            "latest_futures_15m_close_time": prepared.latest_candle_time,
            "outcome_summary": {
                "all": _aggregate_policy(outcomes, skipped, source_ids=all_ids),
                "train": _aggregate_policy(outcomes, skipped, source_ids=prepared.train_ids),
                "validation": _aggregate_policy(outcomes, skipped, source_ids=prepared.validation_ids),
            },
            "failure_summary": {
                "all": _failure_total_stats(all_failures),
                "train": _failure_total_stats(train_failures),
                "validation": _failure_total_stats(validation_failures),
                "dominant_cause": dominant["cause"] if dominant else None,
                "dominant_cause_share_pct": (
                    (dominant.get("all") or {}).get("share_pct") if dominant else None
                ),
            },
            "train_thresholds": {
                "method": "chronological train cohort q75; diagnostic contributor only",
                "values": train_thresholds,
            },
            "cause_rows": cause_rows,
            "contributor_rows": _contributor_rows(
                all_failures,
                train_failures=train_failures,
                validation_failures=validation_failures,
            ),
            "outcome_path_rows": _outcome_path_rows(annotated),
            "latest_failure_examples": _latest_failure_examples(failures, limit=max(1, limit)),
            "verdict": _verdict(
                failure_count=len(failures),
                dominant=dominant,
                min_failure_sample=min_sample,
            ),
            "next_research_targets": _next_research_targets(cause_rows),
            "guardrails": [
                "Failure categories are mutually exclusive; contributor tags may overlap.",
                "Forward 15m path is used only to diagnose the realized outcome and is never a signal input.",
                "Structure zones, BTC/ETH regime, and evidence contributors use only data available at signal time.",
                "Same-candle target/stop order is unknown and remains conservatively ambiguous.",
                "No Signal Factory, scanner, candidate, entry, TP/SL, outcome, or execution rule changed.",
            ],
        }

    def _load_regime_rows(
        self,
        prepared: Lab63PreparedDataset,
    ) -> dict[str, list[tuple[datetime, Decimal]]]:
        if not prepared.signals:
            return {}
        min_time = min(signal.signal_timestamp for signal in prepared.signals) - timedelta(hours=5)
        max_time = max(signal.signal_timestamp for signal in prepared.signals)
        rows = self.db.execute(
            select(FuturesKline1h.symbol, FuturesKline1h.close_time, FuturesKline1h.close)
            .where(
                FuturesKline1h.symbol.in_(("BTCUSDT", "ETHUSDT")),
                FuturesKline1h.aggregation_status == "AGG_READY",
                FuturesKline1h.close_time >= min_time,
                FuturesKline1h.close_time <= max_time,
                FuturesKline1h.close.is_not(None),
            )
            .order_by(asc(FuturesKline1h.symbol), asc(FuturesKline1h.close_time))
        ).all()
        output: dict[str, list[tuple[datetime, Decimal]]] = defaultdict(list)
        for row in rows:
            item = row._mapping
            output[str(item["symbol"])].append(
                (_naive(item["close_time"]), Decimal(item["close"]))
            )
        return dict(output)


class MidLongFailureAnatomyArtifactRunner:
    def __init__(self, db: Session, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.db = db
        self.artifact_path = artifact_path

    def run(self, **kwargs: Any) -> dict[str, Any]:
        payload = json_safe(MidLongFailureAnatomyService(self.db).summary(**kwargs))
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


class MidLongFailureAnatomyArtifactService:
    def __init__(self, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.artifact_path = artifact_path

    def summary(self) -> dict[str, Any]:
        if not self.artifact_path.exists():
            raise FileNotFoundError(f"LAB-65 artifact not found: {self.artifact_path}")
        return json.loads(self.artifact_path.read_text(encoding="utf-8"))


def _annotate_outcome(
    outcome: dict[str, Any],
    *,
    context: Lab63Context,
    signal: Any,
    zone_snapshot: dict[str, Any],
    regime_rows: dict[str, list[tuple[datetime, Decimal]]],
    train_thresholds: dict[str, Decimal | None],
) -> dict[str, Any]:
    entry = Decimal(outcome.get("entry") or 0)
    risk = Decimal(outcome.get("risk") or 0)
    result_status = str(outcome.get("result_status") or "UNKNOWN")
    result_time = _as_datetime(outcome.get("result_time_utc"))
    policy_future = context.future[: max(1, TIMEOUT_MINUTES // 15)]
    result_index = _result_candle_index(policy_future, result_time)
    if result_status == "TIMEOUT_CLOSE" and result_index is None and policy_future:
        result_index = len(policy_future)
    path_before_result = (
        policy_future[: max(0, result_index - 1)]
        if result_index is not None and result_status in {"TP_HIT", "SL_HIT", "BOTH_HIT_SAME_CANDLE"}
        else policy_future[: result_index or len(policy_future)]
    )
    mfe_before = _mfe_r(path_before_result, entry=entry, risk=risk)
    mae_before = _mae_r(path_before_result, entry=entry, risk=risk)
    first_15m_close_r = _close_r(policy_future, index=0, entry=entry, risk=risk)
    first_30m_close_r = _close_r(policy_future, index=1, entry=entry, risk=risk)
    after_sl_target_time = (
        _after_sl_target_time(
            context,
            result_index=result_index,
            target=Decimal(outcome.get("take_profit") or 0),
        )
        if result_status == "SL_HIT"
        else None
    )
    evidence = _evidence_snapshot_from_mapping(signal.evidence)
    evidence.update(
        {
            "core_score": signal.core_score,
            "evidence_score": signal.evidence_score,
            "evidence_data_completeness": (
                Decimal(signal.evidence_data_completeness)
                if signal.evidence_data_completeness is not None
                else None
            ),
        }
    )
    btc_1h = _prior_return_pct(regime_rows.get("BTCUSDT", []), signal.signal_timestamp, hours=1)
    eth_1h = _prior_return_pct(regime_rows.get("ETHUSDT", []), signal.signal_timestamp, hours=1)
    structure_status = str(zone_snapshot.get("status") or "ZONE_UNAVAILABLE")
    structure_conflict = structure_status == "ZONE_CONFLICT"
    regime_conflict = any(
        value is not None and value <= REGIME_CONFLICT_THRESHOLD_PCT
        for value in (btc_1h, eth_1h)
    )
    extension_hits = sum(
        1
        for field in TRAIN_THRESHOLD_FIELDS[:3]
        if _meets_train_high(evidence.get(field), train_thresholds.get(field))
    )
    entry_extended = extension_hits >= 2
    spread_high = _meets_train_high(
        evidence.get("futures_spread_pct"),
        train_thresholds.get("futures_spread_pct"),
    )
    ideal_r = _decimal_or_none(outcome.get("ideal_realized_r"))
    realistic_r = _decimal_or_none(outcome.get("realistic_realized_r"))
    is_loss = realistic_r is not None and realistic_r < 0
    cause = _primary_cause(
        result_status=result_status,
        is_loss=is_loss,
        ideal_r=ideal_r,
        result_index=result_index,
        mfe_before=mfe_before,
        after_sl_target=after_sl_target_time is not None,
        structure_conflict=structure_conflict,
        regime_conflict=regime_conflict,
    )
    contributors = _contributors(
        result_status=result_status,
        ideal_r=ideal_r,
        realistic_r=realistic_r,
        result_index=result_index,
        mfe_before=mfe_before,
        first_15m_close_r=first_15m_close_r,
        after_sl_target=after_sl_target_time is not None,
        structure_conflict=structure_conflict,
        regime_conflict=regime_conflict,
        entry_extended=entry_extended,
        spread_high=spread_high,
    )
    primary = zone_snapshot.get("primary") if isinstance(zone_snapshot.get("primary"), dict) else {}
    context_zone = zone_snapshot.get("context") if isinstance(zone_snapshot.get("context"), dict) else {}
    return {
        "signal_id": signal.signal_id,
        "symbol": signal.symbol,
        "signal_timestamp": signal.signal_timestamp,
        "result_status": result_status,
        "result_time_utc": result_time,
        "entry": entry,
        "stop_loss": outcome.get("stop_loss"),
        "take_profit": outcome.get("take_profit"),
        "risk": risk,
        "ideal_realized_r": ideal_r,
        "realistic_realized_r": realistic_r,
        "is_realistic_loss": is_loss,
        "failure_primary_cause": cause,
        "failure_contributors": contributors,
        "result_candle_index": result_index,
        "time_to_result_minutes": (
            Decimal((result_time - signal.signal_timestamp).total_seconds()) / Decimal("60")
            if result_time is not None
            else None
        ),
        "mfe_before_result_r": mfe_before,
        "mae_before_result_r": mae_before,
        "first_15m_close_r": first_15m_close_r,
        "first_30m_close_r": first_30m_close_r,
        "after_sl_would_hit_target_within_4h": after_sl_target_time is not None,
        "after_sl_target_time_utc": after_sl_target_time,
        "structure_status": structure_status,
        "structure_primary_state": primary.get("state"),
        "structure_context_state": context_zone.get("state"),
        "structure_reason": zone_snapshot.get("reason"),
        "btc_1h_return_pct": btc_1h,
        "eth_1h_return_pct": eth_1h,
        "regime_conflict": regime_conflict,
        "entry_extension_high": entry_extended,
        "entry_extension_high_field_count": extension_hits,
        "spread_high_vs_train_q75": spread_high,
        "evidence_snapshot": evidence,
    }


def _primary_cause(
    *,
    result_status: str,
    is_loss: bool,
    ideal_r: Decimal | None,
    result_index: int | None,
    mfe_before: Decimal,
    after_sl_target: bool,
    structure_conflict: bool,
    regime_conflict: bool,
) -> str:
    if not is_loss:
        return "NOT_REALISTIC_LOSS"
    if result_status == "BOTH_HIT_SAME_CANDLE":
        return "AMBIGUOUS_BOTH_SAME_CANDLE"
    if result_status == "TP_HIT":
        return "COST_DOMINATED_TP"
    if result_status == "TIMEOUT_CLOSE":
        return "COST_DOMINATED_TIMEOUT" if ideal_r is not None and ideal_r >= 0 else "TIMEOUT_NEGATIVE_DRIFT"
    if result_status != "SL_HIT":
        return "OTHER_REALISTIC_LOSS"
    if after_sl_target:
        return "STOP_THEN_TARGET_WITHIN_4H"
    if mfe_before >= NEAR_TARGET_R:
        return "NEAR_TARGET_REVERSAL"
    if mfe_before >= FAVORABLE_MOVE_R:
        return "FAVORABLE_THEN_REVERSAL"
    if result_index is not None and result_index <= 2:
        return "IMMEDIATE_WRONG_DIRECTION"
    if structure_conflict:
        return "STRUCTURE_CONFLICT"
    if regime_conflict:
        return "REGIME_CONFLICT"
    return "NO_FOLLOWTHROUGH"


def _contributors(
    *,
    result_status: str,
    ideal_r: Decimal | None,
    realistic_r: Decimal | None,
    result_index: int | None,
    mfe_before: Decimal,
    first_15m_close_r: Decimal | None,
    after_sl_target: bool,
    structure_conflict: bool,
    regime_conflict: bool,
    entry_extended: bool,
    spread_high: bool,
) -> list[str]:
    output: list[str] = []
    if result_index is not None and result_index <= 2:
        output.append("HIT_WITHIN_30M")
    if first_15m_close_r is not None and first_15m_close_r < 0:
        output.append("FIRST_CANDLE_ADVERSE")
    if mfe_before < FAVORABLE_MOVE_R:
        output.append("LOW_FOLLOWTHROUGH")
    if mfe_before >= NEAR_TARGET_R:
        output.append("NEAR_TARGET_BEFORE_LOSS")
    elif mfe_before >= FAVORABLE_MOVE_R:
        output.append("FAVORABLE_MOVE_BEFORE_LOSS")
    if after_sl_target:
        output.append("TARGET_AFTER_STOP_WITHIN_4H")
    if structure_conflict:
        output.append("STRUCTURE_CONFLICT_AT_SIGNAL")
    if regime_conflict:
        output.append("BTC_ETH_REGIME_CONFLICT")
    if entry_extended:
        output.append("ENTRY_EXTENSION_ABOVE_TRAIN_Q75")
    if spread_high:
        output.append("SPREAD_ABOVE_TRAIN_Q75")
    if ideal_r is not None and ideal_r >= 0 and realistic_r is not None and realistic_r < 0:
        output.append("COST_FLIPPED_NONNEGATIVE_IDEAL")
    if result_status == "BOTH_HIT_SAME_CANDLE":
        output.append("INTRABAR_ORDER_UNKNOWN")
    return output


def _cause_rows(
    all_failures: list[dict[str, Any]],
    *,
    train_failures: list[dict[str, Any]],
    validation_failures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    causes = sorted(
        {str(row["failure_primary_cause"]) for row in all_failures},
        key=lambda cause: (
            -sum(1 for row in all_failures if row["failure_primary_cause"] == cause),
            cause,
        ),
    )
    rows = []
    for cause in causes:
        metadata = CAUSE_METADATA.get(cause, (cause, "", ""))
        rows.append(
            {
                "cause": cause,
                "label": metadata[0],
                "definition": metadata[1],
                "research_action": metadata[2],
                "all": _failure_group_stats(
                    [row for row in all_failures if row["failure_primary_cause"] == cause],
                    denominator=len(all_failures),
                ),
                "train": _failure_group_stats(
                    [row for row in train_failures if row["failure_primary_cause"] == cause],
                    denominator=len(train_failures),
                ),
                "validation": _failure_group_stats(
                    [row for row in validation_failures if row["failure_primary_cause"] == cause],
                    denominator=len(validation_failures),
                ),
            }
        )
    return rows


def _failure_group_stats(rows: list[dict[str, Any]], *, denominator: int) -> dict[str, Any]:
    realistic = [Decimal(row["realistic_realized_r"]) for row in rows if row.get("realistic_realized_r") is not None]
    symbols = Counter(str(row["symbol"]) for row in rows)
    top_symbol, top_count = symbols.most_common(1)[0] if symbols else (None, 0)
    return {
        "count": len(rows),
        "share_pct": _pct(len(rows), denominator),
        "total_realistic_r": sum(realistic, Decimal("0")),
        "avg_realistic_r": sum(realistic, Decimal("0")) / len(realistic) if realistic else None,
        "median_realistic_r": _median(realistic),
        "median_mfe_before_result_r": _median_values(rows, "mfe_before_result_r"),
        "median_mae_before_result_r": _median_values(rows, "mae_before_result_r"),
        "median_first_15m_close_r": _median_values(rows, "first_15m_close_r"),
        "median_first_30m_close_r": _median_values(rows, "first_30m_close_r"),
        "median_time_to_result_minutes": _median_values(rows, "time_to_result_minutes"),
        "target_after_stop_count": sum(1 for row in rows if row.get("after_sl_would_hit_target_within_4h")),
        "structure_conflict_count": sum(1 for row in rows if row.get("structure_status") == "ZONE_CONFLICT"),
        "regime_conflict_count": sum(1 for row in rows if row.get("regime_conflict")),
        "entry_extension_high_count": sum(1 for row in rows if row.get("entry_extension_high")),
        "top_symbol": top_symbol,
        "top_symbol_count": top_count,
        "top_symbol_share_pct": _pct(top_count, len(rows)),
        "evidence_medians": {
            field: _evidence_median(rows, field)
            for field in ANATOMY_EVIDENCE_FIELDS
        },
    }


def _failure_total_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [Decimal(row["realistic_realized_r"]) for row in rows if row.get("realistic_realized_r") is not None]
    return {
        "count": len(rows),
        "total_realistic_r": sum(values, Decimal("0")),
        "avg_realistic_r": sum(values, Decimal("0")) / len(values) if values else None,
        "median_realistic_r": _median(values),
    }


def _contributor_rows(
    all_failures: list[dict[str, Any]],
    *,
    train_failures: list[dict[str, Any]],
    validation_failures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    contributors = Counter(
        contributor
        for row in all_failures
        for contributor in row.get("failure_contributors") or []
    )
    return [
        {
            "contributor": contributor,
            "all_count": count,
            "all_share_pct": _pct(count, len(all_failures)),
            "train_count": sum(
                1 for row in train_failures if contributor in (row.get("failure_contributors") or [])
            ),
            "validation_count": sum(
                1 for row in validation_failures if contributor in (row.get("failure_contributors") or [])
            ),
        }
        for contributor, count in contributors.most_common()
    ]


def _outcome_path_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        status = str(row.get("result_status") or "UNKNOWN")
        if status == "TIMEOUT_CLOSE":
            realistic = _decimal_or_none(row.get("realistic_realized_r"))
            status = "TIMEOUT_POSITIVE" if realistic is not None and realistic > 0 else "TIMEOUT_NONPOSITIVE"
        groups[status].append(row)
    return [
        {
            "status": status,
            "count": len(group),
            "median_mfe_before_result_r": _median_values(group, "mfe_before_result_r"),
            "median_mae_before_result_r": _median_values(group, "mae_before_result_r"),
            "median_first_15m_close_r": _median_values(group, "first_15m_close_r"),
            "median_time_to_result_minutes": _median_values(group, "time_to_result_minutes"),
        }
        for status, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _latest_failure_examples(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
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
        "realistic_realized_r",
        "failure_primary_cause",
        "failure_contributors",
        "result_candle_index",
        "time_to_result_minutes",
        "mfe_before_result_r",
        "mae_before_result_r",
        "first_15m_close_r",
        "first_30m_close_r",
        "after_sl_would_hit_target_within_4h",
        "after_sl_target_time_utc",
        "structure_status",
        "structure_primary_state",
        "structure_context_state",
        "btc_1h_return_pct",
        "eth_1h_return_pct",
        "regime_conflict",
        "entry_extension_high",
        "spread_high_vs_train_q75",
    )
    return [
        {
            **{field: row.get(field) for field in fields},
            "evidence": {
                field: (row.get("evidence_snapshot") or {}).get(field)
                for field in ANATOMY_EVIDENCE_FIELDS
            },
        }
        for row in ordered[:limit]
    ]


def _train_thresholds(prepared: Lab63PreparedDataset) -> dict[str, Decimal | None]:
    output: dict[str, Decimal | None] = {}
    for field in TRAIN_THRESHOLD_FIELDS:
        values = []
        for signal in prepared.signals:
            if signal.signal_id not in prepared.train_ids:
                continue
            evidence = _evidence_snapshot_from_mapping(signal.evidence)
            value = _decimal_or_none(evidence.get(field))
            if value is not None:
                values.append(value)
        output[field] = _percentile(values, Decimal("0.75"))
    return output


def _next_research_targets(cause_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets = []
    for row in cause_rows:
        validation_count = int((row.get("validation") or {}).get("count") or 0)
        if validation_count < 10:
            continue
        targets.append(
            {
                "cause": row["cause"],
                "label": row["label"],
                "validation_count": validation_count,
                "research_action": row["research_action"],
            }
        )
    return targets[:4]


def _verdict(
    *,
    failure_count: int,
    dominant: dict[str, Any] | None,
    min_failure_sample: int,
) -> str:
    if failure_count < min_failure_sample:
        return "INSUFFICIENT_FAILURE_SAMPLE"
    if not dominant:
        return "NO_REALISTIC_LOSS"
    share = Decimal((dominant.get("all") or {}).get("share_pct") or 0)
    validation_count = int((dominant.get("validation") or {}).get("count") or 0)
    if share >= Decimal("30") and validation_count >= max(10, min_failure_sample // 2):
        return "DOMINANT_FAILURE_CAUSE_FOUND"
    return "MIXED_FAILURE_CAUSES"


def _result_candle_index(candles: list[Any], result_time: datetime | None) -> int | None:
    if result_time is None:
        return None
    for index, candle in enumerate(candles, start=1):
        if _naive(candle.close_time) == _naive(result_time):
            return index
    return None


def _mfe_r(candles: list[Any], *, entry: Decimal, risk: Decimal) -> Decimal:
    if not candles or risk <= 0:
        return Decimal("0")
    return max(Decimal("0"), max((candle.high - entry) / risk for candle in candles))


def _mae_r(candles: list[Any], *, entry: Decimal, risk: Decimal) -> Decimal:
    if not candles or risk <= 0:
        return Decimal("0")
    return min(Decimal("0"), min((candle.low - entry) / risk for candle in candles))


def _close_r(candles: list[Any], *, index: int, entry: Decimal, risk: Decimal) -> Decimal | None:
    if risk <= 0 or index >= len(candles):
        return None
    return (candles[index].close - entry) / risk


def _after_sl_target_time(
    context: Lab63Context,
    *,
    result_index: int | None,
    target: Decimal,
) -> datetime | None:
    if result_index is None or target <= 0:
        return None
    for candle in context.future[result_index:16]:
        if candle.high >= target:
            return candle.close_time
    return None


def _prior_return_pct(
    rows: list[tuple[datetime, Decimal]],
    signal_time: datetime,
    *,
    hours: int,
) -> Decimal | None:
    if not rows:
        return None
    times = [row[0] for row in rows]
    current_index = bisect_right(times, _naive(signal_time)) - 1
    previous_index = bisect_right(times, _naive(signal_time) - timedelta(hours=hours)) - 1
    if current_index < 0 or previous_index < 0:
        return None
    current = rows[current_index][1]
    previous = rows[previous_index][1]
    if previous <= 0:
        return None
    return (current - previous) / previous * Decimal("100")


def _meets_train_high(value: Any, threshold: Any) -> bool:
    parsed = _decimal_or_none(value)
    parsed_threshold = _decimal_or_none(threshold)
    return parsed is not None and parsed_threshold is not None and parsed >= parsed_threshold


def _evidence_median(rows: list[dict[str, Any]], field: str) -> Decimal | None:
    values = [
        value
        for value in (
            _decimal_or_none((row.get("evidence_snapshot") or {}).get(field))
            for row in rows
        )
        if value is not None
    ]
    return _median(values)


def _median_values(rows: list[dict[str, Any]], field: str) -> Decimal | None:
    values = [
        value
        for value in (_decimal_or_none(row.get(field)) for row in rows)
        if value is not None
    ]
    return _median(values)


def _median(values: list[Decimal]) -> Decimal | None:
    return Decimal(str(median(values))) if values else None


def _percentile(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = percentile * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _pct(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return Decimal(numerator) / Decimal(denominator) * Decimal("100")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _naive(value)
    try:
        return _naive(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value
