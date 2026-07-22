from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.services.mid_long_failure_anatomy import Lab65PreparedAnalysis
from app.services.mid_long_filter_combination import (
    MidLongFilterCombinationArtifactRunner,
    MidLongFilterCombinationArtifactService,
    MidLongFilterCombinationService,
)
from app.services.mid_long_geometry_validation import Lab63PreparedDataset, Lab63Signal
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH


def test_lab66_learns_threshold_from_train_and_keeps_validation_separate() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    prepared, analysis = _prepared_analysis(validation_flipped=False)

    with Session() as db:
        payload = MidLongFilterCombinationService(db).summary(
            min_validation_sample=5,
            limit=10,
            prepared_dataset=prepared,
            prepared_analysis=analysis,
        )

    volume_threshold = next(
        row
        for row in payload["threshold_discovery"]["field_rows"]
        if row["field"] == "volume_ratio_vs_lookback"
    )
    volume_filter = next(
        row
        for row in payload["filter_rows"]
        if row["filter_id"] == "volume_ratio_vs_lookback_ge_train_q50"
    )

    assert payload["lab"] == "LAB-66"
    assert volume_threshold["direction"] == "HIGHER"
    assert volume_threshold["q50"] == Decimal("1.25")
    assert volume_filter["validation"]["closed_count"] == 10
    assert volume_filter["validation"]["realistic_total_r_closed"] > 0
    assert volume_filter["verdict"] == "VALIDATION_PROMISING"
    assert payload["summary"]["promising_count"] > 0
    assert payload["not_live_signal"] is True
    assert payload["not_execution_instruction"] is True


def test_lab66_marks_train_only_filter_as_overfit_when_validation_flips() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    prepared, analysis = _prepared_analysis(validation_flipped=True)

    with Session() as db:
        payload = MidLongFilterCombinationService(db).summary(
            min_validation_sample=5,
            prepared_dataset=prepared,
            prepared_analysis=analysis,
        )

    volume_filter = next(
        row
        for row in payload["filter_rows"]
        if row["filter_id"] == "volume_ratio_vs_lookback_ge_train_q50"
    )
    assert volume_filter["train"]["realistic_avg_r_closed"] > 0
    assert volume_filter["validation"]["realistic_avg_r_closed"] < 0
    assert volume_filter["verdict"] == "TRAIN_ONLY_OVERFIT"


def test_lab66_never_uses_forward_outcomes_as_filter_inputs() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    prepared, analysis = _prepared_analysis(validation_flipped=False)

    with Session() as db:
        payload = MidLongFilterCombinationService(db).summary(
            min_validation_sample=5,
            prepared_dataset=prepared,
            prepared_analysis=analysis,
        )

    prohibited = {
        "result_status",
        "realistic_realized_r",
        "future_return_1h",
        "mfe_before_result_r",
        "mae_before_result_r",
        "failure_primary_cause",
    }
    assert not prohibited.intersection(
        field for row in payload["filter_rows"] for field in row["fields"]
    )


def test_lab66_artifact_round_trip_is_json_safe(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    prepared, analysis = _prepared_analysis(validation_flipped=False)
    artifact_path = tmp_path / "mid_long_lab66.json"

    with Session() as db:
        payload = MidLongFilterCombinationArtifactRunner(
            db,
            artifact_path=artifact_path,
        ).run(
            min_validation_sample=5,
            prepared_dataset=prepared,
            prepared_analysis=analysis,
        )

    loaded = MidLongFilterCombinationArtifactService(artifact_path=artifact_path).summary()
    assert payload["lab"] == "LAB-66"
    assert loaded["lab"] == "LAB-66"
    assert isinstance(loaded["generated_at_utc"], str)
    assert loaded["filter_rows"]


def _prepared_analysis(
    *,
    validation_flipped: bool,
) -> tuple[Lab63PreparedDataset, Lab65PreparedAnalysis]:
    base_time = datetime(2026, 7, 1, 0, 0)
    signals: list[Lab63Signal] = []
    outcomes: list[dict] = []
    annotated: list[dict] = []
    train_ids: set[str] = set()
    validation_ids: set[str] = set()
    total = 60
    train_count = 40
    for index in range(total):
        is_train = index < train_count
        group_index = index if is_train else index - train_count
        positive_outcome = group_index % 2 == 0
        signal_id = f"signal-{index:03d}"
        symbol = f"S{index:03d}USDT"
        signal_time = base_time + timedelta(hours=index)
        if is_train:
            volume = Decimal("2.0") if positive_outcome else Decimal("0.5")
        elif validation_flipped:
            volume = Decimal("0.5") if positive_outcome else Decimal("2.0")
        else:
            volume = Decimal("2.0") if positive_outcome else Decimal("0.5")
        realized = Decimal("0.8") if positive_outcome else Decimal("-1.1")
        result_status = "TP_HIT" if positive_outcome else "SL_HIT"
        evidence = {
            "volume_ratio_vs_lookback": volume,
            "range_ratio_vs_atr": Decimal("1.0"),
            "atr_extension_normalized": Decimal("0.8"),
            "price_atr_multiple": Decimal("0.6"),
            "futures_spread_pct": Decimal("0.02"),
            "kline_taker_buy_ratio": Decimal("0.55"),
            "oi_zscore": Decimal("1.0"),
            "evidence_score": Decimal("1"),
            "core_score": Decimal("6"),
        }
        signal = Lab63Signal(
            signal_id=signal_id,
            symbol=symbol,
            signal_timestamp=signal_time,
            entry=Decimal("100"),
            evidence={"evidence": evidence},
            core_score=Decimal("6"),
            evidence_score=Decimal("1"),
            evidence_data_completeness=4,
        )
        outcome = {
            "signal_id": signal_id,
            "symbol": symbol,
            "signal_timestamp": signal_time,
            "result_status": result_status,
            "result_time_utc": signal_time + timedelta(hours=1),
            "ideal_realized_r": Decimal("1") if positive_outcome else Decimal("-1"),
            "realistic_realized_r": realized,
            "realistic_fill_quality": "GOOD",
        }
        signals.append(signal)
        outcomes.append(outcome)
        annotated.append(
            {
                **outcome,
                "structure_status": "ZONE_NEUTRAL",
                "btc_1h_return_pct": Decimal("0.2"),
                "eth_1h_return_pct": Decimal("0.1"),
                "regime_conflict": False,
                "evidence_snapshot": evidence,
            }
        )
        (train_ids if is_train else validation_ids).add(signal_id)
    prepared = Lab63PreparedDataset(
        epoch=OBSERVATION_EPOCH,
        include_watch_only=False,
        signals=signals,
        contexts=[],
        latest_candle_time=base_time + timedelta(hours=total),
        train_ids=train_ids,
        validation_ids=validation_ids,
    )
    analysis = Lab65PreparedAnalysis(
        prepared_dataset=prepared,
        outcomes=outcomes,
        skipped=[],
        annotated=annotated,
        train_thresholds={},
    )
    return prepared, analysis
