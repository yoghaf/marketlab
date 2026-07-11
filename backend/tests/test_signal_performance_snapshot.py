from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline1m, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.signal_performance_snapshot import (
    FORWARD_INTEGRITY_FILE,
    FORWARD_INTEGRITY_1H_FILE,
    PERFORMANCE_FILE,
    PERFORMANCE_1H_FILE,
    SignalPerformanceSnapshotRunner,
    SignalPerformanceSnapshotService,
)


def test_signal_performance_snapshot_writes_and_reads_default_payloads(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 1, 0, 15)
        db.add(_signal("s1", "AAAUSDT", signal_time, "LONG", "EARLY_LONG", "100", "90", "115"))
        db.add(_signal("s2", "BBBUSDT", signal_time, "SHORT", "MID_SHORT", "100", "110", "85", timeframe="1h"))
        db.add(_candle("AAAUSDT", signal_time, signal_time + timedelta(minutes=15), high="116", low="99", close="115"))
        db.add(_candle("BBBUSDT", signal_time, signal_time + timedelta(minutes=15), high="101", low="84", close="85"))
        db.commit()

        result = SignalPerformanceSnapshotRunner(db, artifact_dir=tmp_path).run(
            performance_limit=25,
            forward_integrity_limit=25,
        )

    assert result["performance_items"] == 2
    assert result["performance_1h_items"] == 1
    assert (tmp_path / PERFORMANCE_FILE).exists()
    assert (tmp_path / FORWARD_INTEGRITY_FILE).exists()
    assert (tmp_path / PERFORMANCE_1H_FILE).exists()
    assert (tmp_path / FORWARD_INTEGRITY_1H_FILE).exists()
    assert not (tmp_path / f"{PERFORMANCE_FILE}.tmp").exists()

    service = SignalPerformanceSnapshotService(artifact_dir=tmp_path)
    performance = service.performance(limit=1)
    performance_1h = service.performance_1h(limit=1)
    integrity = service.forward_integrity(limit=1)
    integrity_1h = service.forward_integrity_1h(limit=1)
    one_hour_filter = service.one_hour_filter_candidate_study(min_sample=1, limit=5)
    one_hour_walk_forward = service.one_hour_walk_forward_study(min_sample=1, limit=5)
    one_hour_v4_shadow = service.one_hour_v4_shadow_monitor(min_sample=1, limit=5)

    assert performance["cache"]["source"] == "artifact_snapshot"
    assert performance["snapshot"]["read_model"] == "artifact_snapshot"
    assert performance["filters"]["limit"] == 1
    assert performance["aggregate"]["tp_count"] == 2
    assert len(performance["items"]) == 1
    assert performance_1h["snapshot"]["filename"] == PERFORMANCE_1H_FILE
    assert performance_1h["filters"]["timeframe"] == "1h"
    assert performance_1h["aggregate"]["tp_count"] == 1
    assert len(performance_1h["items"]) == 1
    assert integrity["cache"]["source"] == "artifact_snapshot"
    assert integrity["snapshot"]["filename"] == FORWARD_INTEGRITY_FILE
    assert integrity_1h["snapshot"]["filename"] == FORWARD_INTEGRITY_1H_FILE
    assert one_hour_filter["source"] == "signal_performance_snapshot_1h"
    assert one_hour_filter["snapshot"]["filename"] == PERFORMANCE_1H_FILE
    assert one_hour_filter["filters"]["timeframe"] == "1h"
    assert len(one_hour_filter["lanes"]) == 2
    assert one_hour_walk_forward["source"] == "signal_performance_snapshot_1h"
    assert one_hour_walk_forward["snapshot"]["filename"] == PERFORMANCE_1H_FILE
    assert one_hour_walk_forward["split_method"] == "chronological_70_30"
    assert len(one_hour_walk_forward["lanes"]) == 2
    assert one_hour_v4_shadow["source"] == "signal_performance_snapshot_1h"
    assert one_hour_v4_shadow["snapshot"]["filename"] == PERFORMANCE_1H_FILE
    assert one_hour_v4_shadow["study_scope"] == "one_hour_v4_shadow_forward_monitor_read_only"
    assert one_hour_v4_shadow["summary"]["read"] == "V4_NO_FILTER_SELECTED"


def _signal(
    signal_id: str,
    symbol: str,
    signal_time: datetime,
    direction: str,
    stage: str,
    entry: str,
    stop: str,
    target: str,
    timeframe: str = "15m",
) -> SignalForwardReturnLog:
    now = datetime(2026, 1, 1, 0, 0)
    return SignalForwardReturnLog(
        signal_id=signal_id,
        symbol=symbol,
        timeframe=timeframe,
        signal_timestamp=signal_time,
        window_open_time=signal_time - timedelta(minutes=15),
        window_close_time=signal_time,
        direction=direction,
        stage=stage,
        candidate_status="SIGNAL_CANDIDATE",
        core_score=Decimal("8"),
        evidence_score=Decimal("1"),
        evidence_data_completeness=4,
        confidence_tier="HIGH_CONF",
        execution_flag="ACTIVE",
        entry_ref="MARKET_REFERENCE_OK",
        sl_ref=Decimal(stop),
        tp_ref=Decimal(target),
        price_at_signal=Decimal(entry),
        status_15m="READY",
        status_1h="WAITING_DATA",
        status_4h="WAITING_DATA",
        status_24h="WAITING_DATA",
        observation_epoch=OBSERVATION_EPOCH,
        observation_start_utc=now,
        observation_marker=True,
        evidence={},
        created_at=now,
        updated_at=now,
    )


def _candle(
    symbol: str,
    open_time: datetime,
    close_time: datetime,
    *,
    high: str,
    low: str,
    close: str,
) -> FuturesKline1m:
    return FuturesKline1m(
        symbol=symbol,
        open_time=open_time,
        close_time=close_time,
        open_price=Decimal("100"),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
        volume=Decimal("100"),
        trade_count=1,
        created_at=open_time,
        updated_at=open_time,
    )
