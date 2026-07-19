from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.services.mid_long_failure_anatomy import (
    MidLongFailureAnatomyArtifactRunner,
    MidLongFailureAnatomyArtifactService,
    MidLongFailureAnatomyService,
    _primary_cause,
)
from app.services.mid_long_geometry_validation import (
    Lab63Candle,
    Lab63Context,
    Lab63PreparedDataset,
    Lab63Signal,
)
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH


def test_lab65_primary_cause_prioritizes_stop_then_target() -> None:
    cause = _primary_cause(
        result_status="SL_HIT",
        is_loss=True,
        ideal_r=Decimal("-1"),
        result_index=1,
        mfe_before=Decimal("0"),
        after_sl_target=True,
        structure_conflict=True,
        regime_conflict=True,
    )

    assert cause == "STOP_THEN_TARGET_WITHIN_4H"


def test_lab65_primary_cause_separates_path_shapes() -> None:
    immediate = _primary_cause(
        result_status="SL_HIT",
        is_loss=True,
        ideal_r=Decimal("-1"),
        result_index=2,
        mfe_before=Decimal("0.10"),
        after_sl_target=False,
        structure_conflict=False,
        regime_conflict=False,
    )
    near_target = _primary_cause(
        result_status="SL_HIT",
        is_loss=True,
        ideal_r=Decimal("-1"),
        result_index=5,
        mfe_before=Decimal("0.80"),
        after_sl_target=False,
        structure_conflict=False,
        regime_conflict=False,
    )
    timeout = _primary_cause(
        result_status="TIMEOUT_CLOSE",
        is_loss=True,
        ideal_r=Decimal("-0.10"),
        result_index=8,
        mfe_before=Decimal("0.20"),
        after_sl_target=False,
        structure_conflict=False,
        regime_conflict=False,
    )

    assert immediate == "IMMEDIATE_WRONG_DIRECTION"
    assert near_target == "NEAR_TARGET_REVERSAL"
    assert timeout == "TIMEOUT_NEGATIVE_DRIFT"


def test_lab65_service_partitions_realistic_losses_without_changing_policy() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    prepared = _prepared_dataset()

    with Session() as db:
        payload = MidLongFailureAnatomyService(db).summary(
            min_failure_sample=1,
            limit=10,
            prepared_dataset=prepared,
        )

    failure_count = payload["failure_summary"]["all"]["count"]
    partition_count = sum(row["all"]["count"] for row in payload["cause_rows"])
    causes = {row["cause"]: row["all"]["count"] for row in payload["cause_rows"]}

    assert payload["lab"] == "LAB-65"
    assert payload["policy"]["policy_id"] == "TIMEOUT_120M"
    assert payload["policy"]["atr_multiplier"] == Decimal("0.75")
    assert failure_count == 3
    assert partition_count == failure_count
    assert causes["STOP_THEN_TARGET_WITHIN_4H"] == 1
    assert causes["IMMEDIATE_WRONG_DIRECTION"] == 1
    assert causes["TIMEOUT_NEGATIVE_DRIFT"] == 1
    assert payload["outcome_summary"]["all"]["tp_count"] == 1
    assert payload["not_live_signal"] is True
    assert payload["not_execution_instruction"] is True


def test_lab65_artifact_round_trip_is_json_safe(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    artifact_path = tmp_path / "mid_long_lab65.json"

    with Session() as db:
        payload = MidLongFailureAnatomyArtifactRunner(
            db,
            artifact_path=artifact_path,
        ).run(
            min_failure_sample=1,
            prepared_dataset=_prepared_dataset(),
        )

    loaded = MidLongFailureAnatomyArtifactService(artifact_path=artifact_path).summary()
    assert artifact_path.exists()
    assert payload["lab"] == "LAB-65"
    assert loaded["failure_summary"]["all"]["count"] == 3
    assert isinstance(loaded["latest_failure_examples"][0]["signal_timestamp"], str)


def _prepared_dataset() -> Lab63PreparedDataset:
    base_time = datetime(2026, 7, 1, 0, 0)
    specs = [
        ("stop-target", "AAAUSDT", base_time, "STOP_THEN_TARGET"),
        ("immediate", "BBBUSDT", base_time + timedelta(hours=1), "IMMEDIATE_SL"),
        ("timeout", "CCCUSDT", base_time + timedelta(hours=2), "TIMEOUT_LOSS"),
        ("target", "DDDUSDT", base_time + timedelta(hours=3), "TP"),
    ]
    signals: list[Lab63Signal] = []
    contexts: list[Lab63Context] = []
    for signal_id, symbol, signal_time, path in specs:
        signal = Lab63Signal(
            signal_id=signal_id,
            symbol=symbol,
            signal_timestamp=signal_time,
            entry=Decimal("100"),
            evidence={
                "evidence": {
                    "price_return": "0.5",
                    "atr_extension_normalized": "0.8",
                    "range_ratio_vs_atr": "1.0",
                    "price_atr_multiple": "0.5",
                    "futures_spread_pct": "0.02",
                }
            },
            core_score=Decimal("7"),
            evidence_score=Decimal("1"),
            evidence_data_completeness=4,
        )
        future = _future_path(signal_time, path)
        signals.append(signal)
        contexts.append(
            Lab63Context(
                signal=signal,
                atr_1h=Decimal("4"),
                future=future,
                latest_symbol_close_time=future[-1].close_time,
            )
        )
    return Lab63PreparedDataset(
        epoch=OBSERVATION_EPOCH,
        include_watch_only=False,
        signals=signals,
        contexts=contexts,
        latest_candle_time=max(context.future[-1].close_time for context in contexts),
        train_ids={"stop-target", "immediate"},
        validation_ids={"timeout", "target"},
    )


def _future_path(signal_time: datetime, path: str) -> list[Lab63Candle]:
    candles: list[Lab63Candle] = []
    for index in range(16):
        open_time = signal_time + timedelta(minutes=15 * index)
        high = Decimal("101")
        low = Decimal("99")
        close = Decimal("100")
        if path in {"STOP_THEN_TARGET", "IMMEDIATE_SL"} and index == 0:
            low = Decimal("96")
            close = Decimal("97")
        if path == "STOP_THEN_TARGET" and index == 1:
            high = Decimal("104")
            close = Decimal("103")
        if path == "TIMEOUT_LOSS":
            high = Decimal("101")
            low = Decimal("98")
            close = Decimal("99")
        if path == "TP" and index == 0:
            high = Decimal("104")
            close = Decimal("103")
        candles.append(
            Lab63Candle(
                open_time=open_time,
                close_time=open_time + timedelta(minutes=15),
                high=high,
                low=low,
                close=close,
            )
        )
    return candles
