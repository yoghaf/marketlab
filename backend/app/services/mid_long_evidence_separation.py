from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.mid_long_geometry_validation import (
    ATR_MULTIPLIER,
    REWARD_RISK,
    Lab63PreparedDataset,
    MidLongGeometryValidationService,
    _aggregate_policy,
    _evaluate_policy,
)
from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_candidate_performance import EVIDENCE_FIELDS, _evidence_snapshot_from_mapping
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import json_safe, utcnow


POLICY_ID = "TIMEOUT_120M"
TIMEOUT_MINUTES = 120
MINIMUM_AUC_DISTANCE = Decimal("0.02")
WEAK_SEPARATION = Decimal("0.10")
MODERATE_SEPARATION = Decimal("0.20")
DEFAULT_ARTIFACT_PATH = (
    REPO_ROOT / "backend" / "artifacts" / "strategy_optimization" / "v1" / "mid_long_lab64.json"
)

LAB64_EVIDENCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("core_score", "Core score"),
    ("evidence_score", "Evidence score"),
    ("evidence_data_completeness", "Evidence completeness"),
    *tuple(EVIDENCE_FIELDS),
    ("body_pct", "Body %"),
    ("upper_wick_pct", "Upper wick %"),
    ("lower_wick_pct", "Lower wick %"),
    ("funding_rate", "Funding rate"),
)


class MidLongEvidenceSeparationService:
    """Read-only TP/SL evidence separation for the fixed LAB-63 policy."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_group_sample: int = 20,
        limit: int = 20,
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
        signal_by_id = {signal.signal_id: signal for signal in prepared.signals}
        research_rows = [
            _research_row(outcome, signal_by_id[str(outcome["signal_id"])])
            for outcome in outcomes
            if str(outcome.get("signal_id")) in signal_by_id
        ]
        field_rows = [
            _field_comparison_row(
                research_rows,
                field=field,
                label=label,
                train_ids=prepared.train_ids,
                validation_ids=prepared.validation_ids,
                min_group_sample=max(1, min_group_sample),
            )
            for field, label in LAB64_EVIDENCE_FIELDS
        ]
        field_rows.sort(key=_field_rank_key, reverse=True)

        all_ids = {signal.signal_id for signal in prepared.signals}
        outcome_summary = {
            "all": _aggregate_policy(outcomes, skipped, source_ids=all_ids),
            "train": _aggregate_policy(outcomes, skipped, source_ids=prepared.train_ids),
            "validation": _aggregate_policy(outcomes, skipped, source_ids=prepared.validation_ids),
        }
        verdict_counts = Counter(str(row["verdict"]) for row in field_rows)
        stable_fields = [
            row
            for row in field_rows
            if row["verdict"] in {"VALIDATION_CONSISTENT_MODERATE", "VALIDATION_CONSISTENT_WEAK"}
        ]
        top_fields = [str(row["field"]) for row in stable_fields[:5]]

        return {
            "generated_at_utc": utcnow(),
            "lab": "LAB-64",
            "study_scope": "mid_long_1h_tp_sl_evidence_separation",
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
                "min_group_sample": max(1, min_group_sample),
                "limit": max(1, limit),
            },
            "policy": {
                "policy_id": POLICY_ID,
                "timeout_minutes": TIMEOUT_MINUTES,
                "atr_source": "ATR14 futures_klines_1h closed at or before signal",
                "atr_multiplier": ATR_MULTIPLIER,
                "reward_risk": REWARD_RISK,
                "realistic_model": "Binance taker fee + signal futures spread + slippage",
            },
            "split": {
                "method": "chronological_70_30",
                "source_signal_count": len(prepared.signals),
                "train_source_count": len(prepared.train_ids),
                "validation_source_count": len(prepared.validation_ids),
            },
            "latest_futures_15m_close_time": prepared.latest_candle_time,
            "outcome_summary": outcome_summary,
            "field_summary": {
                "field_count": len(field_rows),
                "stable_field_count": len(stable_fields),
                "moderate_field_count": verdict_counts["VALIDATION_CONSISTENT_MODERATE"],
                "weak_field_count": verdict_counts["VALIDATION_CONSISTENT_WEAK"],
                "direction_flip_count": verdict_counts["DIRECTION_FLIPPED"],
                "insufficient_count": verdict_counts["INSUFFICIENT_SAMPLE"],
                "no_clear_separation_count": verdict_counts["NO_CLEAR_SEPARATION"],
            },
            "verdict": (
                "HAS_VALIDATION_CONSISTENT_EVIDENCE"
                if stable_fields
                else "NO_STABLE_EVIDENCE_SEPARATOR"
            ),
            "best_observed_field": stable_fields[0] if stable_fields else None,
            "field_rows": field_rows,
            "latest_tp_examples": _latest_examples(
                research_rows,
                result_status="TP_HIT",
                fields=top_fields,
                limit=max(1, limit),
            ),
            "latest_sl_examples": _latest_examples(
                research_rows,
                result_status="SL_HIT",
                fields=top_fields,
                limit=max(1, limit),
            ),
            "guardrails": [
                "Every evidence value is read from the snapshot persisted at signal time.",
                "Forward prices, future returns, result time, MFE, and MAE are never used as input evidence.",
                "TP and SL distributions exclude timeout, same-candle ambiguity, waiting, and incomplete rows.",
                "A consistent field is descriptive evidence only; it is not an automatic filter or threshold.",
                "No Signal Factory, scanner, candidate, entry, TP/SL, outcome, or execution rule changed.",
            ],
        }


class MidLongEvidenceSeparationArtifactRunner:
    def __init__(self, db: Session, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.db = db
        self.artifact_path = artifact_path

    def run(self, **kwargs: Any) -> dict[str, Any]:
        payload = json_safe(MidLongEvidenceSeparationService(self.db).summary(**kwargs))
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


class MidLongEvidenceSeparationArtifactService:
    def __init__(self, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.artifact_path = artifact_path

    def summary(self) -> dict[str, Any]:
        if not self.artifact_path.exists():
            raise FileNotFoundError(f"LAB-64 artifact not found: {self.artifact_path}")
        return json.loads(self.artifact_path.read_text(encoding="utf-8"))


def _research_row(outcome: dict[str, Any], signal: Any) -> dict[str, Any]:
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
            "body_pct": _decimal_or_none(signal.evidence.get("body_pct")),
            "upper_wick_pct": _decimal_or_none(signal.evidence.get("upper_wick_pct")),
            "lower_wick_pct": _decimal_or_none(signal.evidence.get("lower_wick_pct")),
            "funding_rate": _decimal_or_none(signal.evidence.get("funding_rate")),
        }
    )
    return {
        "signal_id": signal.signal_id,
        "symbol": signal.symbol,
        "signal_timestamp": signal.signal_timestamp,
        "result_status": str(outcome.get("result_status") or "UNKNOWN"),
        "result_time_utc": outcome.get("result_time_utc"),
        "entry": outcome.get("entry"),
        "realistic_realized_r": outcome.get("realistic_realized_r"),
        "evidence_snapshot": evidence,
    }


def _field_comparison_row(
    rows: list[dict[str, Any]],
    *,
    field: str,
    label: str,
    train_ids: set[str],
    validation_ids: set[str],
    min_group_sample: int,
) -> dict[str, Any]:
    all_stats = _field_stats(rows, field=field)
    train_stats = _field_stats(
        [row for row in rows if str(row["signal_id"]) in train_ids],
        field=field,
    )
    validation_stats = _field_stats(
        [row for row in rows if str(row["signal_id"]) in validation_ids],
        field=field,
    )
    train_direction = _auc_direction(train_stats.get("auc_tp_above_sl"))
    validation_direction = _auc_direction(validation_stats.get("auc_tp_above_sl"))
    direction_consistent = (
        train_direction == validation_direction
        if train_direction not in {None, "NEUTRAL"} and validation_direction not in {None, "NEUTRAL"}
        else None
    )
    verdict = _field_verdict(
        train=train_stats,
        validation=validation_stats,
        train_direction=train_direction,
        validation_direction=validation_direction,
        min_group_sample=min_group_sample,
    )
    return {
        "field": field,
        "label": label,
        "all": all_stats,
        "train": train_stats,
        "validation": validation_stats,
        "train_direction": train_direction,
        "validation_direction": validation_direction,
        "direction_consistent": direction_consistent,
        "verdict": verdict,
        "research_read": _research_read(
            label=label,
            verdict=verdict,
            validation_direction=validation_direction,
            availability_pct=validation_stats.get("available_pct"),
        ),
    }


def _field_stats(rows: list[dict[str, Any]], *, field: str) -> dict[str, Any]:
    available: list[tuple[str, Decimal]] = []
    for row in rows:
        value = (row.get("evidence_snapshot") or {}).get(field)
        if value is not None:
            available.append((str(row.get("result_status") or "UNKNOWN"), Decimal(value)))
    tp_values = [value for status, value in available if status == "TP_HIT"]
    sl_values = [value for status, value in available if status == "SL_HIT"]
    tp_median = _median(tp_values)
    sl_median = _median(sl_values)
    auc = _auc_tp_above_sl(tp_values, sl_values)
    return {
        "source_count": len(rows),
        "available_count": len(available),
        "missing_count": len(rows) - len(available),
        "available_pct": (
            Decimal(len(available)) / Decimal(len(rows)) * Decimal("100")
            if rows
            else None
        ),
        "tp_count": len(tp_values),
        "sl_count": len(sl_values),
        "tp_median": tp_median,
        "sl_median": sl_median,
        "delta_tp_minus_sl": (
            tp_median - sl_median
            if tp_median is not None and sl_median is not None
            else None
        ),
        "tp_q1": _percentile(tp_values, Decimal("0.25")),
        "tp_q3": _percentile(tp_values, Decimal("0.75")),
        "sl_q1": _percentile(sl_values, Decimal("0.25")),
        "sl_q3": _percentile(sl_values, Decimal("0.75")),
        "auc_tp_above_sl": auc,
        "separation_strength": abs(auc - Decimal("0.5")) * Decimal("2") if auc is not None else None,
    }


def _field_verdict(
    *,
    train: dict[str, Any],
    validation: dict[str, Any],
    train_direction: str | None,
    validation_direction: str | None,
    min_group_sample: int,
) -> str:
    if min(
        int(train.get("tp_count") or 0),
        int(train.get("sl_count") or 0),
        int(validation.get("tp_count") or 0),
        int(validation.get("sl_count") or 0),
    ) < min_group_sample:
        return "INSUFFICIENT_SAMPLE"
    if train_direction == "NEUTRAL" or validation_direction == "NEUTRAL":
        return "NO_CLEAR_SEPARATION"
    if train_direction != validation_direction:
        return "DIRECTION_FLIPPED"
    train_strength = Decimal(train.get("separation_strength") or 0)
    validation_strength = Decimal(validation.get("separation_strength") or 0)
    if min(train_strength, validation_strength) >= MODERATE_SEPARATION:
        return "VALIDATION_CONSISTENT_MODERATE"
    if min(train_strength, validation_strength) >= WEAK_SEPARATION:
        return "VALIDATION_CONSISTENT_WEAK"
    return "NO_CLEAR_SEPARATION"


def _auc_direction(auc: Any) -> str | None:
    if auc is None:
        return None
    value = Decimal(auc)
    if abs(value - Decimal("0.5")) <= MINIMUM_AUC_DISTANCE:
        return "NEUTRAL"
    return "TP_HIGHER" if value > Decimal("0.5") else "TP_LOWER"


def _auc_tp_above_sl(tp_values: list[Decimal], sl_values: list[Decimal]) -> Decimal | None:
    if not tp_values or not sl_values:
        return None
    wins = 0
    ties = 0
    for tp_value in tp_values:
        for sl_value in sl_values:
            if tp_value > sl_value:
                wins += 1
            elif tp_value == sl_value:
                ties += 1
    pair_count = len(tp_values) * len(sl_values)
    return (Decimal(wins) + (Decimal(ties) / Decimal("2"))) / Decimal(pair_count)


def _field_rank_key(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, Decimal]:
    verdict_rank = {
        "VALIDATION_CONSISTENT_MODERATE": 5,
        "VALIDATION_CONSISTENT_WEAK": 4,
        "NO_CLEAR_SEPARATION": 3,
        "DIRECTION_FLIPPED": 2,
        "INSUFFICIENT_SAMPLE": 1,
    }
    validation = row.get("validation") or {}
    train = row.get("train") or {}
    return (
        verdict_rank.get(str(row.get("verdict")), 0),
        min(
            Decimal(validation.get("separation_strength") or 0),
            Decimal(train.get("separation_strength") or 0),
        ),
        Decimal(validation.get("available_pct") or 0),
        Decimal(validation.get("available_count") or 0),
    )


def _latest_examples(
    rows: list[dict[str, Any]],
    *,
    result_status: str,
    fields: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    selected = sorted(
        [row for row in rows if row.get("result_status") == result_status],
        key=lambda row: (row.get("signal_timestamp"), str(row.get("symbol"))),
        reverse=True,
    )
    return [
        {
            "signal_id": row["signal_id"],
            "symbol": row["symbol"],
            "signal_timestamp": row["signal_timestamp"],
            "result_status": row["result_status"],
            "result_time_utc": row["result_time_utc"],
            "entry": row["entry"],
            "realistic_realized_r": row["realistic_realized_r"],
            "evidence": {
                field: (row.get("evidence_snapshot") or {}).get(field)
                for field in fields
            },
        }
        for row in selected[:limit]
    ]


def _research_read(
    *,
    label: str,
    verdict: str,
    validation_direction: str | None,
    availability_pct: Any,
) -> str:
    availability = Decimal(availability_pct or 0)
    missing_note = " Evidence availability is limited." if availability < Decimal("80") else ""
    if verdict == "VALIDATION_CONSISTENT_MODERATE":
        direction = "higher" if validation_direction == "TP_HIGHER" else "lower"
        return f"{label} remained {direction} for TP in train and validation.{missing_note}"
    if verdict == "VALIDATION_CONSISTENT_WEAK":
        direction = "higher" if validation_direction == "TP_HIGHER" else "lower"
        return f"{label} showed a weak but consistent {direction} TP relationship.{missing_note}"
    if verdict == "DIRECTION_FLIPPED":
        return f"{label} changed direction between train and validation; do not use it as a filter."
    if verdict == "INSUFFICIENT_SAMPLE":
        return f"{label} does not have enough TP and SL values in both time splits."
    return f"{label} did not show useful TP/SL separation."


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


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
