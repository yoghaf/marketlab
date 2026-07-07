from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import FuturesKline1h, MarketlabActiveUniverse
from app.services.market_regime_study import (
    MarketRegimeStudyRunner,
    candle_return_pct,
    classify_breadth,
    classify_return,
    classify_volatility,
    combined_regime,
)


def test_regime_classifiers_are_directional_and_conservative() -> None:
    assert classify_return(0.30, bullish_threshold=0.25, bearish_threshold=-0.25) == "BULLISH"
    assert classify_return(-0.30, bullish_threshold=0.25, bearish_threshold=-0.25) == "BEARISH"
    assert classify_return(0.10, bullish_threshold=0.25, bearish_threshold=-0.25) == "FLAT"
    assert classify_breadth(70) == "BREADTH_STRONG"
    assert classify_breadth(30) == "BREADTH_WEAK"
    assert classify_breadth(50) == "BREADTH_MIXED"
    assert classify_volatility(1.50, high=1.25, low=0.45) == "VOL_HIGH"
    assert classify_volatility(0.25, high=1.25, low=0.45) == "VOL_LOW"
    assert combined_regime("BULLISH", "BREADTH_STRONG") == "RISK_ON"
    assert combined_regime("BEARISH", "BREADTH_WEAK") == "RISK_OFF"


def test_market_snapshot_uses_active_symbols_and_latest_closed_window() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        close_time = datetime(2026, 1, 1, 1, 0)
        future_time = datetime(2026, 1, 1, 2, 0)
        for rank, symbol in enumerate(["AAAUSDT", "BBBUSDT", "CCCUSDT"], start=1):
            db.add(_active(symbol, rank))
        db.add(_active("INACTIVEUSDT", 99, active=False))
        db.add(_kline("AAAUSDT", close_time, "100", "110"))
        db.add(_kline("BBBUSDT", close_time, "100", "90"))
        db.add(_kline("CCCUSDT", close_time, "100", "100"))
        db.add(_kline("INACTIVEUSDT", close_time, "100", "150"))
        db.add(_kline("AAAUSDT", future_time, "100", "200"))
        db.commit()

        snapshot = MarketRegimeStudyRunner(db)._market_snapshot("1h", close_time + timedelta(minutes=5))  # noqa: SLF001

        assert snapshot.close_time == close_time
        assert snapshot.symbol_count == 3
        assert snapshot.up_count == 1
        assert snapshot.down_count == 1
        assert snapshot.flat_count == 1
        assert round(snapshot.up_pct or 0, 4) == round(100 / 3, 4)
        assert round(snapshot.avg_return_pct or 0, 4) == 0


def test_candle_return_pct_handles_decimal_inputs() -> None:
    assert candle_return_pct(Decimal("100"), Decimal("102")) == 2.0
    assert candle_return_pct(Decimal("0"), Decimal("102")) is None


def _active(symbol: str, rank: int, *, active: bool = True) -> MarketlabActiveUniverse:
    now = datetime(2026, 1, 1)
    return MarketlabActiveUniverse(
        symbol=symbol,
        rank=rank,
        quote_volume=Decimal("100"),
        collection_tier="FULL_ACTIVE" if active else "NOT_ACTIVE",
        is_full_active=active,
        is_light_watch=False,
        is_signal_eligible=active,
        is_active=active,
        entered_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )


def _kline(symbol: str, close_time: datetime, open_price: str, close_price: str) -> FuturesKline1h:
    return FuturesKline1h(
        symbol=symbol,
        open_time=close_time - timedelta(hours=1),
        close_time=close_time,
        open=Decimal(open_price),
        high=max(Decimal(open_price), Decimal(close_price)),
        low=min(Decimal(open_price), Decimal(close_price)),
        close=Decimal(close_price),
        volume=Decimal("100"),
        source_interval="1h",
        expected_1m_count=60,
        actual_1m_count=60,
        missing_1m_count=0,
        aggregation_status="AGG_READY",
        created_at=close_time,
        updated_at=close_time,
    )
