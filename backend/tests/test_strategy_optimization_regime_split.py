from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline15m, FuturesKline1h, MarketlabActiveUniverse, SignalForwardReturnLog
from app.services.signal_forward_return_logger import OBSERVATION_EPOCH
from app.services.strategy_optimization_regime_split import StrategyOptimizationRegimeSplitService


def test_strategy_regime_split_identifies_risk_off_short_bucket() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        risk_off_time = datetime(2026, 1, 2, 0, 0)
        risk_on_time = datetime(2026, 1, 2, 1, 0)
        db.add(_active("BTCUSDT", 1))
        db.add(_active("ETHUSDT", 2))
        _add_atr_history(db, "AAAUSDT", risk_off_time)
        _add_atr_history(db, "BBBUSDT", risk_on_time)
        _add_market_regime(db, risk_off_time, btc_close="99", eth_close="99")
        _add_market_regime(db, risk_on_time, btc_close="101", eth_close="101")
        db.add(_signal("sig-risk-off", "AAAUSDT", risk_off_time, "100"))
        db.add(_signal("sig-risk-on", "BBBUSDT", risk_on_time, "100"))
        db.add(_kline15("AAAUSDT", risk_off_time, high="101", low="89", close="90"))
        db.add(_kline15("BBBUSDT", risk_on_time, high="111", low="99", close="110"))
        db.commit()

        payload = StrategyOptimizationRegimeSplitService(db).summary(
            stage="MID_SHORT",
            timeframe="1h",
            atr_mult=Decimal("1.00"),
            rr=Decimal("1.0"),
            timeout_minutes=60,
            min_sample=1,
        )

        combined_rows = {
            row["bucket"]: row
            for row in payload["dimensions"]["combined_regime_1h"]
        }
        assert combined_rows["RISK_OFF"]["tp_count"] == 1
        assert combined_rows["RISK_OFF"]["avg_r"] == 1.0
        assert combined_rows["RISK_OFF"]["verdict"] == "REGIME_HELPFUL"
        assert combined_rows["RISK_ON"]["sl_count"] == 1
        assert payload["summary"]["regime_dependency"].startswith("SHORT_EDGE_APPEARS_BEAR_OR_WEAK_BREADTH_DEPENDENT")


def _active(symbol: str, rank: int) -> MarketlabActiveUniverse:
    now = datetime(2026, 1, 1)
    return MarketlabActiveUniverse(
        symbol=symbol,
        rank=rank,
        quote_volume=Decimal("100"),
        collection_tier="FULL_ACTIVE",
        is_full_active=True,
        is_light_watch=False,
        is_signal_eligible=True,
        is_active=True,
        entered_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )


def _add_atr_history(db, symbol: str, signal_time: datetime) -> None:
    start = signal_time - timedelta(hours=15)
    for index in range(15):
        open_time = start + timedelta(hours=index)
        db.add(_kline1h(symbol, open_time, open_price="100", high="105", low="95", close_price="100"))


def _add_market_regime(db, close_time: datetime, *, btc_close: str, eth_close: str) -> None:
    db.add(_kline1h("BTCUSDT", close_time - timedelta(hours=1), open_price="100", high="102", low="98", close_price=btc_close))
    db.add(_kline1h("ETHUSDT", close_time - timedelta(hours=1), open_price="100", high="102", low="98", close_price=eth_close))


def _signal(signal_id: str, symbol: str, signal_time: datetime, entry: str) -> SignalForwardReturnLog:
    now = datetime(2026, 1, 1)
    return SignalForwardReturnLog(
        signal_id=signal_id,
        symbol=symbol,
        timeframe="1h",
        signal_timestamp=signal_time,
        window_open_time=signal_time - timedelta(hours=1),
        window_close_time=signal_time,
        direction="SHORT",
        stage="MID_SHORT",
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
        volume=Decimal("100"),
        source_interval="1h",
        expected_1m_count=60,
        actual_1m_count=60,
        missing_1m_count=0,
        aggregation_status="AGG_READY",
        created_at=open_time,
        updated_at=open_time,
    )
