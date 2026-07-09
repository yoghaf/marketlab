from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline15m, FuturesKline1h, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.strategy_optimization_lab import StrategyOptimizationLabService


def test_strategy_optimization_lab_finds_atr_rr_tp_path() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 2, 0, 0)
        _add_atr_history(db, "AAAUSDT", signal_time, close="100")
        db.add(_signal("s1", "AAAUSDT", signal_time, "LONG", "EARLY_LONG", "100"))
        db.add(_kline15("AAAUSDT", signal_time, high="111", low="99", close="110"))
        db.commit()

        payload = StrategyOptimizationLabService(db).summary(stage="EARLY_LONG", timeframe="15m", min_sample=1)

        rows = {
            (str(row["atr_mult"]), str(row["rr"]), row["timeout_minutes"]): row
            for row in payload["rows"]
        }
        row = rows[("1.00", "1.0", 60)]
        assert row["sample_count"] == 1
        assert row["tp_count"] == 1
        assert row["total_r"] == 1.0
        assert row["verdict"] == "PROMISING_TIMEOUT_MODEL"


def test_strategy_optimization_lab_timeout_close_uses_future_15m_close() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        signal_time = datetime(2026, 1, 2, 0, 0)
        _add_atr_history(db, "BBBUSDT", signal_time, close="100")
        db.add(_signal("s1", "BBBUSDT", signal_time, "SHORT", "MID_SHORT", "100"))
        db.add(_kline15("BBBUSDT", signal_time, high="105", low="95", close="98"))
        db.add(_kline15("BBBUSDT", signal_time + timedelta(minutes=15), high="104", low="96", close="97"))
        db.add(_kline15("BBBUSDT", signal_time + timedelta(minutes=30), high="103", low="95", close="96"))
        db.add(_kline15("BBBUSDT", signal_time + timedelta(minutes=45), high="104", low="96", close="95"))
        db.commit()

        payload = StrategyOptimizationLabService(db).summary(stage="MID_SHORT", timeframe="15m", min_sample=1)

        rows = {
            (str(row["atr_mult"]), str(row["rr"]), row["timeout_minutes"]): row
            for row in payload["rows"]
        }
        row = rows[("1.00", "2.0", 60)]
        assert row["timeout_count"] == 1
        assert row["tp_count"] == 0
        assert row["sl_count"] == 0
        assert row["positive_timeout_count"] == 1
        assert row["total_r"] == 0.5


def _add_atr_history(db, symbol: str, signal_time: datetime, *, close: str) -> None:
    start = signal_time - timedelta(hours=15)
    prev_close = Decimal(close)
    for index in range(15):
        open_time = start + timedelta(hours=index)
        high = prev_close + Decimal("5")
        low = prev_close - Decimal("5")
        db.add(
            _kline1h(
                symbol,
                open_time,
                high=str(high),
                low=str(low),
                close=str(prev_close),
            )
        )


def _signal(signal_id: str, symbol: str, signal_time: datetime, direction: str, stage: str, entry: str) -> SignalForwardReturnLog:
    now = datetime(2026, 1, 1, 0, 0)
    return SignalForwardReturnLog(
        signal_id=signal_id,
        symbol=symbol,
        timeframe="15m",
        signal_timestamp=signal_time,
        window_open_time=signal_time - timedelta(minutes=15),
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
