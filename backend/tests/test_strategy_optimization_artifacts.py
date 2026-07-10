from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline15m, FuturesKline1h, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.strategy_optimization_artifacts import (
    StrategyOptimizationArtifactRunner,
    StrategyOptimizationArtifactService,
)


def test_strategy_optimization_artifact_runner_writes_and_serves_lane(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    artifact_dir = tmp_path / "strategy_optimization"
    with Session() as db:
        signal_time = datetime(2026, 1, 2, 0, 0)
        _add_atr_history(db, "AAAUSDT", signal_time)
        db.add(_signal("sig-1", "AAAUSDT", signal_time, "SHORT", "MID_SHORT", "100"))
        db.add(_kline15("AAAUSDT", signal_time, high="101", low="89", close="90"))
        db.commit()

        payload = StrategyOptimizationArtifactRunner(db, artifact_dir=artifact_dir).run(
            min_sample=1,
            limit=20,
            lane_pairs=(("MID_SHORT", "1h"),),
        )

    assert (artifact_dir / "summary.json").exists()
    assert payload["optimization_by_lane"]["MID_SHORT:1h"]["summary"]["signals_loaded"] == 1

    service = StrategyOptimizationArtifactService(artifact_dir=artifact_dir)
    row = service.optimization_for(
        stage="MID_SHORT",
        timeframe="1h",
        include_watch_only=False,
        position_lock=True,
        min_sample=1,
        limit=10,
    )
    assert row is not None
    assert row["artifact"]["read_from_artifact"] is True
    assert row["summary"]["best_row"]["tp_count"] == 1


def _add_atr_history(db, symbol: str, signal_time: datetime) -> None:
    start = signal_time - timedelta(hours=15)
    for index in range(15):
        open_time = start + timedelta(hours=index)
        db.add(_kline1h(symbol, open_time, open_price="100", high="105", low="95", close_price="100"))


def _signal(signal_id: str, symbol: str, signal_time: datetime, direction: str, stage: str, entry: str) -> SignalForwardReturnLog:
    now = datetime(2026, 1, 1)
    return SignalForwardReturnLog(
        signal_id=signal_id,
        symbol=symbol,
        timeframe="1h",
        signal_timestamp=signal_time,
        window_open_time=signal_time - timedelta(hours=1),
        window_close_time=signal_time,
        direction=direction,
        stage=stage,
        candidate_status="SIGNAL_CANDIDATE",
        core_score=Decimal("7"),
        evidence_score=Decimal("1"),
        evidence_data_completeness=4,
        confidence_tier="MEDIUM_CONF",
        execution_flag="ACTIVE",
        entry_ref="FUTURES_CLOSE",
        sl_ref=Decimal("0"),
        tp_ref=Decimal("0"),
        price_at_signal=Decimal(entry),
        status_15m="READY",
        status_1h="READY",
        status_4h="WAITING_DATA",
        status_24h="WAITING_DATA",
        observation_epoch=OBSERVATION_EPOCH,
        observation_start_utc=now,
        observation_marker=True,
        evidence={},
        created_at=now,
        updated_at=now,
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


def _kline1h(symbol: str, open_time: datetime, *, open_price: str, high: str, low: str, close_price: str) -> FuturesKline1h:
    return FuturesKline1h(
        symbol=symbol,
        open_time=open_time,
        close_time=open_time + timedelta(hours=1),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close_price),
        source_interval="1m",
        expected_1m_count=60,
        actual_1m_count=60,
        missing_1m_count=0,
        aggregation_status="AGG_READY",
        created_at=open_time,
        updated_at=open_time,
    )
