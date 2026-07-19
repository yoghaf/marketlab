from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline15m, FuturesKline1h, SignalForwardReturnLog
from app.services.mid_long_geometry_validation import (
    MidLongGeometryValidationArtifactRunner,
    MidLongGeometryValidationArtifactService,
    MidLongGeometryValidationService,
)
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH


def test_lab63_compares_fixed_timeouts_with_no_timeout_without_forced_close() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 2, 0, 0)
        _add_atr_history(db, "AAAUSDT", signal_time)
        db.add(_signal("s1", "AAAUSDT", signal_time))
        for index in range(4):
            db.add(
                _kline15(
                    "AAAUSDT",
                    signal_time + timedelta(minutes=15 * index),
                    high="106",
                    low="98",
                    close=str(Decimal("100") + Decimal(index + 1) / Decimal("4")),
                )
            )
        db.add(
            _kline15(
                "AAAUSDT",
                signal_time + timedelta(minutes=60),
                high="108",
                low="100",
                close="107.5",
            )
        )
        db.commit()

        payload = MidLongGeometryValidationService(db).summary(
            position_lock=True,
            min_validation_sample=1,
        )

        policies = {row["policy_id"]: row for row in payload["policies"]}
        timeout_60 = policies["TIMEOUT_60M"]["all"]
        timeout_4h = policies["TIMEOUT_4H"]["all"]
        no_timeout = policies["NO_TIMEOUT"]["all"]

        assert timeout_60["timeout_count"] == 1
        assert timeout_60["tp_count"] == 0
        assert timeout_4h["tp_count"] == 1
        assert no_timeout["tp_count"] == 1
        assert payload["reference_policy"] == "TIMEOUT_4H"
        assert payload["geometry"]["atr_multiplier"] == Decimal("0.75")
        assert payload["geometry"]["reward_risk"] == Decimal("1.0")


def test_lab63_no_timeout_stays_open_and_position_lock_skips_later_signal() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 2, 0, 0)
        second_time = signal_time + timedelta(hours=1)
        _add_atr_history(db, "BBBUSDT", signal_time)
        db.add(_signal("s1", "BBBUSDT", signal_time))
        db.add(_signal("s2", "BBBUSDT", second_time))
        for index in range(8):
            db.add(
                _kline15(
                    "BBBUSDT",
                    signal_time + timedelta(minutes=15 * index),
                    high="104",
                    low="98",
                    close="101",
                )
            )
        db.commit()

        payload = MidLongGeometryValidationService(db).summary(
            position_lock=True,
            min_validation_sample=1,
        )
        no_timeout = next(row for row in payload["policies"] if row["policy_id"] == "NO_TIMEOUT")

        assert no_timeout["all"]["open_count"] == 1
        assert no_timeout["all"]["closed_count"] == 0
        assert no_timeout["all"]["skipped_count"] == 1
        assert no_timeout["latest_results"][0]["result_status"] == "OPEN"
        assert no_timeout["latest_results"][0]["realistic_realized_r"] is None
        assert no_timeout["latest_results"][0]["realistic_unrealized_r"] is not None


def test_lab63_gap_is_incomplete_and_not_closed() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 2, 0, 0)
        _add_atr_history(db, "CCCUSDT", signal_time)
        db.add(_signal("s1", "CCCUSDT", signal_time))
        db.add(_kline15("CCCUSDT", signal_time, high="104", low="98", close="101"))
        db.add(
            _kline15(
                "CCCUSDT",
                signal_time + timedelta(minutes=30),
                high="104",
                low="98",
                close="101",
            )
        )
        db.commit()

        payload = MidLongGeometryValidationService(db).summary(
            position_lock=True,
            min_validation_sample=1,
        )
        no_timeout = next(row for row in payload["policies"] if row["policy_id"] == "NO_TIMEOUT")

        assert no_timeout["all"]["incomplete_count"] == 1
        assert no_timeout["all"]["closed_count"] == 0
        assert no_timeout["all"]["open_count"] == 0


def test_lab63_artifact_round_trip(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    artifact_path = tmp_path / "mid_long_lab63.json"
    with Session() as db:
        payload = MidLongGeometryValidationArtifactRunner(db, artifact_path=artifact_path).run(
            min_validation_sample=1,
        )

    loaded = MidLongGeometryValidationArtifactService(artifact_path=artifact_path).summary()
    assert artifact_path.exists()
    assert payload["lab"] == "LAB-63"
    assert loaded["lab"] == "LAB-63"
    assert len(loaded["policies"]) == 4


def _add_atr_history(db, symbol: str, signal_time: datetime) -> None:
    start = signal_time - timedelta(hours=15)
    for index in range(15):
        open_time = start + timedelta(hours=index)
        db.add(_kline1h(symbol, open_time, high="105", low="95", close="100"))


def _signal(signal_id: str, symbol: str, signal_time: datetime) -> SignalForwardReturnLog:
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
        evidence={"evidence": {"futures_spread_pct": "0.02"}},
        created_at=signal_time,
        updated_at=signal_time,
    )


def _kline15(symbol: str, open_time: datetime, *, high: str, low: str, close: str) -> FuturesKline15m:
    return FuturesKline15m(
        symbol=symbol,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        source_interval="1m",
        expected_1m_count=15,
        actual_1m_count=15,
        missing_1m_count=0,
        aggregation_status="AGG_READY",
        created_at=open_time,
        updated_at=open_time,
    )


def _kline1h(symbol: str, open_time: datetime, *, high: str, low: str, close: str) -> FuturesKline1h:
    return FuturesKline1h(
        symbol=symbol,
        open_time=open_time,
        close_time=open_time + timedelta(hours=1),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        source_interval="1m",
        expected_1m_count=60,
        actual_1m_count=60,
        missing_1m_count=0,
        aggregation_status="AGG_READY",
        created_at=open_time,
        updated_at=open_time,
    )
