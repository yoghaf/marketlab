from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from app.services.mid_long_failure_anatomy import (
    Lab65PreparedAnalysis,
    MidLongFailureAnatomyService,
    POLICY_ID,
    TIMEOUT_MINUTES,
)
from app.services.mid_long_geometry_validation import (
    ATR_MULTIPLIER,
    REWARD_RISK,
    Lab63PreparedDataset,
    MidLongGeometryValidationService,
    _aggregate_policy,
)
from app.services.multitimeframe_features import REPO_ROOT
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.utils import json_safe, utcnow


DEFAULT_ARTIFACT_PATH = (
    REPO_ROOT / "backend" / "artifacts" / "strategy_optimization" / "v1" / "mid_long_lab66.json"
)

NUMERIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("volume_ratio_vs_lookback", "Volume vs lookback"),
    ("range_ratio_vs_atr", "Range / ATR"),
    ("atr_extension_normalized", "ATR extension"),
    ("price_atr_multiple", "Price / ATR"),
    ("futures_spread_pct", "Futures spread"),
    ("kline_taker_buy_ratio", "Taker buy ratio"),
    ("oi_zscore", "OI z-score"),
    ("evidence_score", "Evidence score"),
    ("core_score", "Core score"),
)


@dataclass(frozen=True)
class FilterAtom:
    atom_id: str
    label: str
    expression: str
    field: str
    operator: str
    threshold: Decimal | None = None
    source: str = "train_only"


class MidLongFilterCombinationService:
    """Chronological fixed-cohort filter study for MID_LONG 1h."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(
        self,
        *,
        epoch: str = OBSERVATION_EPOCH,
        include_watch_only: bool = False,
        position_lock: bool = True,
        min_validation_sample: int = 40,
        limit: int = 30,
        prepared_dataset: Lab63PreparedDataset | None = None,
        prepared_analysis: Lab65PreparedAnalysis | None = None,
    ) -> dict[str, Any]:
        prepared = prepared_dataset or MidLongGeometryValidationService(self.db).prepare_dataset(
            epoch=epoch,
            include_watch_only=include_watch_only,
        )
        analysis = prepared_analysis or MidLongFailureAnatomyService(self.db).prepare_analysis(
            prepared_dataset=prepared,
            position_lock=position_lock,
        )
        rows = analysis.annotated
        outcomes = analysis.outcomes
        skipped = analysis.skipped
        all_ids = {signal.signal_id for signal in prepared.signals}
        baseline = {
            "all": _aggregate_policy(outcomes, skipped, source_ids=all_ids),
            "train": _aggregate_policy(outcomes, skipped, source_ids=prepared.train_ids),
            "validation": _aggregate_policy(
                outcomes,
                skipped,
                source_ids=prepared.validation_ids,
            ),
        }

        atoms, threshold_rows = _discover_atoms(
            rows,
            train_ids=prepared.train_ids,
        )
        single_rows = [
            _filter_row(
                [atom],
                rows=rows,
                outcomes=outcomes,
                train_ids=prepared.train_ids,
                validation_ids=prepared.validation_ids,
                baseline=baseline,
                min_validation_sample=max(1, min_validation_sample),
            )
            for atom in atoms
        ]
        combo_atoms = _select_combination_atoms(atoms, single_rows)
        combo_specs: list[list[FilterAtom]] = []
        for size in (2, 3):
            for parts in combinations(combo_atoms, size):
                if len({part.field for part in parts}) != len(parts):
                    continue
                combo_specs.append(list(parts))
        combination_rows = [
            _filter_row(
                parts,
                rows=rows,
                outcomes=outcomes,
                train_ids=prepared.train_ids,
                validation_ids=prepared.validation_ids,
                baseline=baseline,
                min_validation_sample=max(1, min_validation_sample),
            )
            for parts in combo_specs
        ]
        filter_rows = single_rows + combination_rows
        filter_rows.sort(key=_row_rank_key, reverse=True)
        candidate_rows = [
            row
            for row in filter_rows
            if row["verdict"] in {"VALIDATION_PROMISING", "VALIDATION_DAMAGE_REDUCTION"}
        ]
        best_observed = filter_rows[0] if filter_rows else None
        top_candidate = candidate_rows[0] if candidate_rows else None
        top_atoms = _atoms_for_row(top_candidate or best_observed, atoms)
        pass_rows, fail_rows = _top_examples(
            rows,
            top_atoms,
            limit=max(1, limit),
        )

        return {
            "generated_at_utc": utcnow(),
            "lab": "LAB-66",
            "study_scope": "mid_long_1h_fixed_cohort_filter_combination",
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
                "min_validation_sample": max(1, min_validation_sample),
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
                "evaluated_fixed_cohort_count": len(rows),
            },
            "latest_futures_15m_close_time": prepared.latest_candle_time,
            "baseline": baseline,
            "threshold_discovery": {
                "method": "Train-only positive-vs-nonpositive median direction with train quantile thresholds",
                "field_rows": threshold_rows,
                "atom_count": len(atoms),
                "combination_atom_count": len(combo_atoms),
            },
            "summary": {
                "single_filter_count": len(single_rows),
                "combination_count": len(combination_rows),
                "candidate_count": len(candidate_rows),
                "promising_count": sum(
                    1 for row in filter_rows if row["verdict"] == "VALIDATION_PROMISING"
                ),
                "damage_reduction_count": sum(
                    1
                    for row in filter_rows
                    if row["verdict"] == "VALIDATION_DAMAGE_REDUCTION"
                ),
                "overfit_count": sum(
                    1 for row in filter_rows if row["verdict"] == "TRAIN_ONLY_OVERFIT"
                ),
                "verdict": _study_verdict(candidate_rows),
            },
            "top_candidate": top_candidate,
            "best_observed": best_observed,
            "filter_rows": filter_rows,
            "candidate_rows": candidate_rows,
            "latest_pass_examples": pass_rows,
            "latest_fail_examples": fail_rows,
            "next_step": _next_step(candidate_rows),
            "guardrails": [
                "Every numeric threshold and direction is learned from the chronological train cohort only.",
                "Validation outcomes are never used to create or tune a filter candidate.",
                "Structure and BTC/ETH regime inputs use only information available at the signal timestamp.",
                "Forward path, failure cause, MFE, MAE, TP/SL status, and future return are never filter inputs.",
                "The fixed position-locked LAB-63 cohort is filtered after evaluation; promotion requires a separate forward shadow run.",
                "No Signal Factory, scanner, entry, TP/SL, outcome, or execution rule changed.",
            ],
        }


class MidLongFilterCombinationArtifactRunner:
    def __init__(self, db: Session, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.db = db
        self.artifact_path = artifact_path

    def run(self, **kwargs: Any) -> dict[str, Any]:
        payload = json_safe(MidLongFilterCombinationService(self.db).summary(**kwargs))
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


class MidLongFilterCombinationArtifactService:
    def __init__(self, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.artifact_path = artifact_path

    def summary(self) -> dict[str, Any]:
        if not self.artifact_path.exists():
            raise FileNotFoundError(f"LAB-66 artifact not found: {self.artifact_path}")
        return json.loads(self.artifact_path.read_text(encoding="utf-8"))


def _discover_atoms(
    rows: list[dict[str, Any]],
    *,
    train_ids: set[str],
) -> tuple[list[FilterAtom], list[dict[str, Any]]]:
    train_rows = [
        row
        for row in rows
        if str(row.get("signal_id")) in train_ids
        and _decimal_or_none(row.get("realistic_realized_r")) is not None
    ]
    atoms = [
        FilterAtom(
            atom_id="structure_no_conflict",
            label="Structure available, no conflict",
            expression="structure_status is available and not ZONE_CONFLICT",
            field="structure_status",
            operator="NO_CONFLICT",
            source="causal_structure_snapshot",
        ),
        FilterAtom(
            atom_id="regime_no_conflict",
            label="BTC/ETH regime not conflicting",
            expression="BTC or ETH 1h return is available and regime_conflict is false",
            field="regime_conflict",
            operator="NO_CONFLICT",
            source="causal_btc_eth_1h",
        ),
    ]
    threshold_rows: list[dict[str, Any]] = []
    for field, label in NUMERIC_FIELDS:
        values: list[Decimal] = []
        positive: list[Decimal] = []
        nonpositive: list[Decimal] = []
        for row in train_rows:
            value = _numeric_value(row, field)
            if value is None:
                continue
            values.append(value)
            realized = _decimal_or_none(row.get("realistic_realized_r"))
            if realized is not None and realized > 0:
                positive.append(value)
            else:
                nonpositive.append(value)
        positive_median = _median(positive)
        nonpositive_median = _median(nonpositive)
        direction = None
        if positive_median is not None and nonpositive_median is not None:
            if positive_median > nonpositive_median:
                direction = "HIGHER"
            elif positive_median < nonpositive_median:
                direction = "LOWER"
        q25 = _percentile(values, Decimal("0.25"))
        q50 = _percentile(values, Decimal("0.50"))
        q75 = _percentile(values, Decimal("0.75"))
        threshold_rows.append(
            {
                "field": field,
                "label": label,
                "train_available_count": len(values),
                "train_positive_count": len(positive),
                "train_nonpositive_count": len(nonpositive),
                "positive_median": positive_median,
                "nonpositive_median": nonpositive_median,
                "direction": direction,
                "q25": q25,
                "q50": q50,
                "q75": q75,
            }
        )
        if direction is None or len(positive) < 10 or len(nonpositive) < 10 or q50 is None:
            continue
        median_operator = "GE" if direction == "HIGHER" else "LE"
        strict_threshold = q75 if direction == "HIGHER" else q25
        atoms.append(
            FilterAtom(
                atom_id=f"{field}_{median_operator.lower()}_train_q50",
                label=f"{label} {'>=' if median_operator == 'GE' else '<='} train median",
                expression=f"{field} {'>=' if median_operator == 'GE' else '<='} {q50}",
                field=field,
                operator=median_operator,
                threshold=q50,
            )
        )
        if strict_threshold is not None and strict_threshold != q50:
            atoms.append(
                FilterAtom(
                    atom_id=f"{field}_{median_operator.lower()}_train_strict",
                    label=f"{label} {'>=' if median_operator == 'GE' else '<='} train strict quartile",
                    expression=(
                        f"{field} {'>=' if median_operator == 'GE' else '<='} {strict_threshold}"
                    ),
                    field=field,
                    operator=median_operator,
                    threshold=strict_threshold,
                )
            )
    return atoms, threshold_rows


def _filter_row(
    atoms: list[FilterAtom],
    *,
    rows: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    train_ids: set[str],
    validation_ids: set[str],
    baseline: dict[str, dict[str, Any]],
    min_validation_sample: int,
) -> dict[str, Any]:
    available = [row for row in rows if all(_atom_available(row, atom) for atom in atoms)]
    matched = [row for row in available if all(_atom_matches(row, atom) for atom in atoms)]
    all_matched_ids = {str(row["signal_id"]) for row in matched}
    train_matched_ids = all_matched_ids & train_ids
    validation_matched_ids = all_matched_ids & validation_ids
    metrics = {
        "all": _aggregate_policy(outcomes, [], source_ids=all_matched_ids),
        "train": _aggregate_policy(outcomes, [], source_ids=train_matched_ids),
        "validation": _aggregate_policy(outcomes, [], source_ids=validation_matched_ids),
    }
    all_available_ids = {str(row["signal_id"]) for row in available}
    availability = {
        "all": _availability(rows, available, matched),
        "train": _availability(
            [row for row in rows if str(row["signal_id"]) in train_ids],
            [row for row in available if str(row["signal_id"]) in train_ids],
            [row for row in matched if str(row["signal_id"]) in train_ids],
        ),
        "validation": _availability(
            [row for row in rows if str(row["signal_id"]) in validation_ids],
            [row for row in available if str(row["signal_id"]) in validation_ids],
            [row for row in matched if str(row["signal_id"]) in validation_ids],
        ),
    }
    deltas = {
        split: _metric_deltas(metrics[split], baseline[split])
        for split in ("all", "train", "validation")
    }
    verdict = _filter_verdict(
        metrics,
        deltas,
        min_validation_sample=min_validation_sample,
    )
    filter_id = "__and__".join(atom.atom_id for atom in atoms)
    return {
        "filter_id": filter_id,
        "label": " + ".join(atom.label for atom in atoms),
        "expression": " AND ".join(atom.expression for atom in atoms),
        "component_ids": [atom.atom_id for atom in atoms],
        "fields": [atom.field for atom in atoms],
        "threshold_source": "chronological_train_only",
        "availability": availability,
        "all_available_signal_count": len(all_available_ids),
        "all": metrics["all"],
        "train": metrics["train"],
        "validation": metrics["validation"],
        "deltas": deltas,
        "verdict": verdict,
        "risk_notes": _risk_notes(metrics, availability, verdict),
    }


def _select_combination_atoms(
    atoms: list[FilterAtom],
    single_rows: list[dict[str, Any]],
) -> list[FilterAtom]:
    row_by_id = {row["filter_id"]: row for row in single_rows}
    candidates = []
    for atom in atoms:
        row = row_by_id.get(atom.atom_id) or {}
        train = row.get("train") or {}
        availability = (row.get("availability") or {}).get("train") or {}
        if int(train.get("closed_count") or 0) < 30:
            continue
        if Decimal(availability.get("retention_pct") or 0) < Decimal("15"):
            continue
        candidates.append(atom)
    candidates.sort(
        key=lambda atom: (
            Decimal(
                (((row_by_id.get(atom.atom_id) or {}).get("deltas") or {}).get("train") or {}).get(
                    "realistic_avg_r", 0
                )
                or 0
            ),
            Decimal(
                (((row_by_id.get(atom.atom_id) or {}).get("deltas") or {}).get("train") or {}).get(
                    "max_drawdown_r", 0
                )
                or 0
            ),
            int(((row_by_id.get(atom.atom_id) or {}).get("train") or {}).get("closed_count") or 0),
        ),
        reverse=True,
    )
    selected: list[FilterAtom] = []
    seen_fields: set[str] = set()
    for atom in candidates:
        if atom.field in seen_fields:
            continue
        selected.append(atom)
        seen_fields.add(atom.field)
        if len(selected) >= 6:
            break
    return selected


def _atom_available(row: dict[str, Any], atom: FilterAtom) -> bool:
    if atom.field == "structure_status":
        return str(row.get("structure_status") or "ZONE_UNAVAILABLE") != "ZONE_UNAVAILABLE"
    if atom.field == "regime_conflict":
        return row.get("btc_1h_return_pct") is not None or row.get("eth_1h_return_pct") is not None
    return _numeric_value(row, atom.field) is not None


def _atom_matches(row: dict[str, Any], atom: FilterAtom) -> bool:
    if not _atom_available(row, atom):
        return False
    if atom.field == "structure_status":
        return str(row.get("structure_status")) != "ZONE_CONFLICT"
    if atom.field == "regime_conflict":
        return not bool(row.get("regime_conflict"))
    value = _numeric_value(row, atom.field)
    if value is None or atom.threshold is None:
        return False
    return value >= atom.threshold if atom.operator == "GE" else value <= atom.threshold


def _numeric_value(row: dict[str, Any], field: str) -> Decimal | None:
    evidence = row.get("evidence_snapshot") if isinstance(row.get("evidence_snapshot"), dict) else {}
    return _decimal_or_none(evidence.get(field))


def _availability(
    source_rows: list[dict[str, Any]],
    available_rows: list[dict[str, Any]],
    matched_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "source_count": len(source_rows),
        "available_count": len(available_rows),
        "missing_count": len(source_rows) - len(available_rows),
        "matched_count": len(matched_rows),
        "available_pct": _pct(len(available_rows), len(source_rows)),
        "retention_pct": _pct(len(matched_rows), len(source_rows)),
    }


def _metric_deltas(metrics: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "realistic_total_r": _delta(
            metrics.get("realistic_total_r_closed"),
            baseline.get("realistic_total_r_closed"),
        ),
        "realistic_avg_r": _delta(
            metrics.get("realistic_avg_r_closed"),
            baseline.get("realistic_avg_r_closed"),
        ),
        "realistic_median_r": _delta(
            metrics.get("realistic_median_r_closed"),
            baseline.get("realistic_median_r_closed"),
        ),
        "max_drawdown_r": _delta(
            metrics.get("max_realistic_drawdown_r"),
            baseline.get("max_realistic_drawdown_r"),
        ),
    }


def _filter_verdict(
    metrics: dict[str, dict[str, Any]],
    deltas: dict[str, dict[str, Any]],
    *,
    min_validation_sample: int,
) -> str:
    train = metrics["train"]
    validation = metrics["validation"]
    train_delta = Decimal(deltas["train"].get("realistic_avg_r") or 0)
    validation_delta = Decimal(deltas["validation"].get("realistic_avg_r") or 0)
    validation_dd_delta = Decimal(deltas["validation"].get("max_drawdown_r") or 0)
    validation_avg = Decimal(validation.get("realistic_avg_r_closed") or 0)
    validation_total = Decimal(validation.get("realistic_total_r_closed") or 0)
    validation_concentration = Decimal(validation.get("top_symbol_share_pct") or 0)
    if int(validation.get("closed_count") or 0) < min_validation_sample:
        return "INSUFFICIENT_VALIDATION_SAMPLE"
    if train_delta > 0 and validation_delta <= 0:
        return "TRAIN_ONLY_OVERFIT"
    if (
        validation_total > 0
        and validation_avg > 0
        and validation_delta > 0
        and validation_dd_delta >= 0
        and validation_concentration <= Decimal("15")
    ):
        return "VALIDATION_PROMISING"
    if validation_delta > 0 and validation_dd_delta >= 0:
        return "VALIDATION_DAMAGE_REDUCTION"
    if Decimal(train.get("realistic_avg_r_closed") or 0) <= 0 and validation_avg <= 0:
        return "NO_POSITIVE_EDGE"
    return "VALIDATION_NO_IMPROVEMENT"


def _risk_notes(
    metrics: dict[str, dict[str, Any]],
    availability: dict[str, dict[str, Any]],
    verdict: str,
) -> list[str]:
    notes = []
    validation = metrics["validation"]
    if int(validation.get("closed_count") or 0) < 40:
        notes.append("Validation sample remains below the preferred 40 closed rows.")
    if Decimal(validation.get("top_symbol_share_pct") or 0) > Decimal("15"):
        notes.append("Validation symbol concentration exceeds 15%.")
    if Decimal(availability["validation"].get("available_pct") or 0) < Decimal("80"):
        notes.append("Validation field availability is below 80%.")
    if verdict == "TRAIN_ONLY_OVERFIT":
        notes.append("Train improvement did not persist in validation.")
    if not notes:
        notes.append("No immediate sample, concentration, or availability warning.")
    return notes


def _row_rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
    verdict_rank = {
        "VALIDATION_PROMISING": 5,
        "VALIDATION_DAMAGE_REDUCTION": 4,
        "VALIDATION_NO_IMPROVEMENT": 3,
        "NO_POSITIVE_EDGE": 2,
        "INSUFFICIENT_VALIDATION_SAMPLE": 1,
        "TRAIN_ONLY_OVERFIT": 0,
    }
    validation = row.get("validation") or {}
    deltas = (row.get("deltas") or {}).get("validation") or {}
    return (
        verdict_rank.get(str(row.get("verdict")), -1),
        Decimal(deltas.get("realistic_avg_r") or 0),
        Decimal(validation.get("realistic_avg_r_closed") or 0),
        Decimal(deltas.get("max_drawdown_r") or 0),
        int(validation.get("closed_count") or 0),
    )


def _atoms_for_row(
    row: dict[str, Any] | None,
    atoms: list[FilterAtom],
) -> list[FilterAtom]:
    if not row:
        return []
    atom_by_id = {atom.atom_id: atom for atom in atoms}
    return [atom_by_id[atom_id] for atom_id in row.get("component_ids") or [] if atom_id in atom_by_id]


def _top_examples(
    rows: list[dict[str, Any]],
    atoms: list[FilterAtom],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not atoms:
        return [], []
    ordered = sorted(
        rows,
        key=lambda row: (str(row.get("signal_timestamp") or ""), str(row.get("symbol") or "")),
        reverse=True,
    )
    passes = [row for row in ordered if all(_atom_matches(row, atom) for atom in atoms)]
    fails = [row for row in ordered if not all(_atom_matches(row, atom) for atom in atoms)]
    return (
        [_example(row) for row in passes[:limit]],
        [_example(row) for row in fails[:limit]],
    )


def _example(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": row.get("signal_id"),
        "symbol": row.get("symbol"),
        "signal_timestamp": row.get("signal_timestamp"),
        "result_status": row.get("result_status"),
        "realistic_realized_r": row.get("realistic_realized_r"),
        "structure_status": row.get("structure_status"),
        "regime_conflict": row.get("regime_conflict"),
        "evidence": row.get("evidence_snapshot") or {},
    }


def _study_verdict(candidate_rows: list[dict[str, Any]]) -> str:
    if any(row["verdict"] == "VALIDATION_PROMISING" for row in candidate_rows):
        return "FIXED_COHORT_CANDIDATE_FOUND"
    if candidate_rows:
        return "DAMAGE_REDUCTION_ONLY"
    return "NO_VALIDATED_FILTER_YET"


def _next_step(candidate_rows: list[dict[str, Any]]) -> str:
    if any(row["verdict"] == "VALIDATION_PROMISING" for row in candidate_rows):
        return "Run a separate read-only forward shadow lane before considering any rule change."
    if candidate_rows:
        return "Keep the best damage-reduction combination in monitoring and collect more validation rows."
    return "Do not promote a filter; continue causal feature research or collect more fixed-cohort data."


def _median(values: list[Decimal]) -> Decimal | None:
    return Decimal(median(values)) if values else None


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


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return None


def _delta(value: Any, baseline: Any) -> Decimal | None:
    left = _decimal_or_none(value)
    right = _decimal_or_none(baseline)
    if left is None or right is None:
        return None
    return left - right


def _pct(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return Decimal(numerator) / Decimal(denominator) * Decimal("100")
