from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline15m, FuturesKline1h, SignalForwardReturnLog
from app.services.mid_long_evidence_separation import (
    MidLongEvidenceSeparationArtifactRunner,
    MidLongEvidenceSeparationArtifactService,
    MidLongEvidenceSeparationService,
    _auc_tp_above_sl,
    _field_comparison_row,
)
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH


def test_lab64_finds_same_tp_evidence_direction_in_train_and_validation() -> None:
    rows = [
        _research_item("train-tp", "TP_HIT", "2"),
        _research_item("train-sl", "SL_HIT", "0"),
        _research_item("validation-tp", "TP_HIT", "3"),
        _research_item("validation-sl", "SL_HIT", "1"),
    ]
    result = _field_comparison_row(
        rows,
        field="price_return",
        label="Price return",
        train_ids={"train-tp", "train-sl"},
        validation_ids={"validation-tp", "validation-sl"},
        min_group_sample=1,
    )

    assert result["train_direction"] == "TP_HIGHER"
    assert result["validation_direction"] == "TP_HIGHER"
    assert result["direction_consistent"] is True
    assert result["verdict"] == "VALIDATION_CONSISTENT_MODERATE"


def test_lab64_rejects_evidence_direction_that_flips_in_validation() -> None:
    rows = [
        _research_item("train-tp", "TP_HIT", "2"),
        _research_item("train-sl", "SL_HIT", "0"),
        _research_item("validation-tp", "TP_HIT", "0"),
        _research_item("validation-sl", "SL_HIT", "2"),
    ]
    result = _field_comparison_row(
        rows,
        field="price_return",
        label="Price return",
        train_ids={"train-tp", "train-sl"},
        validation_ids={"validation-tp", "validation-sl"},
        min_group_sample=1,
    )

    assert result["direction_consistent"] is False
    assert result["verdict"] == "DIRECTION_FLIPPED"


def test_lab64_auc_handles_ties_without_direction_bias() -> None:
    auc = _auc_tp_above_sl(
        [Decimal("1"), Decimal("2")],
        [Decimal("1"), Decimal("2")],
    )
    assert auc == Decimal("0.5")


def test_lab64_service_uses_fixed_120m_outcomes_and_signal_time_evidence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    base_time = datetime(2026, 1, 2, 0, 0)
    specs = [
        ("train-tp", "AAAUSDT", base_time, "2", "TP"),
        ("train-sl", "BBBUSDT", base_time + timedelta(hours=1), "0", "SL"),
        ("validation-tp", "CCCUSDT", base_time + timedelta(hours=2), "3", "TP"),
        ("validation-sl", "DDDUSDT", base_time + timedelta(hours=3), "1", "SL"),
    ]
    with Session() as db:
        for signal_id, symbol, signal_time, evidence_value, outcome in specs:
            _add_atr_history(db, symbol, signal_time)
            db.add(_signal(signal_id, symbol, signal_time, evidence_value))
            db.add(_outcome_candle(symbol, signal_time, outcome))
        db.commit()

        payload = MidLongEvidenceSeparationService(db).summary(
            min_group_sample=1,
            limit=5,
        )

    price_return = next(row for row in payload["field_rows"] if row["field"] == "price_return")
    assert payload["lab"] == "LAB-64"
    assert payload["policy"]["policy_id"] == "TIMEOUT_120M"
    assert payload["outcome_summary"]["all"]["tp_count"] == 2
    assert payload["outcome_summary"]["all"]["sl_count"] == 2
    assert price_return["verdict"] == "VALIDATION_CONSISTENT_MODERATE"
    assert payload["not_live_signal"] is True
    assert payload["not_execution_instruction"] is True
    prohibited_outcome_inputs = {
        "future_return_15m",
        "future_return_30m",
        "future_return_1h",
        "future_return_4h",
        "mfe_r",
        "mae_r",
        "result_status",
    }
    assert not prohibited_outcome_inputs.intersection(row["field"] for row in payload["field_rows"])


def test_lab64_artifact_round_trip(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    artifact_path = tmp_path / "mid_long_lab64.json"
    with Session() as db:
        payload = MidLongEvidenceSeparationArtifactRunner(db, artifact_path=artifact_path).run(
            min_group_sample=1,
        )

    loaded = MidLongEvidenceSeparationArtifactService(artifact_path=artifact_path).summary()
    assert artifact_path.exists()
    assert payload["lab"] == "LAB-64"
    assert loaded["lab"] == "LAB-64"
    assert loaded["policy"]["timeout_minutes"] == 120


def _research_item(signal_id: str, result_status: str, value: str) -> dict:
    return {
        "signal_id": signal_id,
        "result_status": result_status,
        "evidence_snapshot": {"price_return": Decimal(value)},
    }


def _add_atr_history(db, symbol: str, signal_time: datetime) -> None:
    start = signal_time - timedelta(hours=15)
    for index in range(15):
        open_time = start + timedelta(hours=index)
        db.add(
            FuturesKline1h(
                symbol=symbol,
                open_time=open_time,
                close_time=open_time + timedelta(hours=1),
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("95"),
                close=Decimal("100"),
                source_interval="1m",
                expected_1m_count=60,
                actual_1m_count=60,
                missing_1m_count=0,
                aggregation_status="AGG_READY",
                created_at=open_time,
                updated_at=open_time,
            )
        )


def _signal(
    signal_id: str,
    symbol: str,
    signal_time: datetime,
    evidence_value: str,
) -> SignalForwardReturnLog:
    return SignalForwardReturnLog(
        signal_id=signal_id,
        symbol=symbol,
        timeframe="1h",
        signal_timestamp=signal_time,
        window_open_time=signal_time - timedelta(hours=1),
        window_close_time=signal_time,
        direction="LONG",
        stage="MID_LONG",
        candidate_status="SIGNAL_CANDIDATE",
        core_score=Decimal("7"),
        evidence_score=Decimal("1"),
        evidence_data_completeness=4,
        confidence_tier="MEDIUM_CONF",
        execution_flag="ACTIVE",
        entry_ref="FUTURES_CLOSE",
        sl_ref=Decimal("0"),
        tp_ref=Decimal("0"),
        price_at_signal=Decimal("100"),
        status_15m="READY",
        status_1h="READY",
        status_4h="WAITING_DATA",
        status_24h="WAITING_DATA",
        observation_epoch=OBSERVATION_EPOCH,
        observation_start_utc=signal_time,
        observation_marker=True,
        evidence={
            "evidence": {
                "price_return": evidence_value,
                "futures_spread_pct": "0.02",
            }
        },
        created_at=signal_time,
        updated_at=signal_time,
    )


def _outcome_candle(symbol: str, signal_time: datetime, outcome: str) -> FuturesKline15m:
    high = Decimal("108") if outcome == "TP" else Decimal("101")
    low = Decimal("99") if outcome == "TP" else Decimal("92")
    return FuturesKline15m(
        symbol=symbol,
        open_time=signal_time,
        close_time=signal_time + timedelta(minutes=15),
        open=Decimal("100"),
        high=high,
        low=low,
        close=Decimal("100"),
        source_interval="1m",
        expected_1m_count=15,
        actual_1m_count=15,
        missing_1m_count=0,
        aggregation_status="AGG_READY",
        created_at=signal_time,
        updated_at=signal_time,
    )
