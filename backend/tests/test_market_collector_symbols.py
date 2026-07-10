from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.market import BinanceFuturesSymbol, MarketlabActiveUniverse, SignalForwardReturnLog
from app.services.collectors import MarketCollector


def test_futures_kline_symbols_include_recent_signal_symbols_outside_active_universe() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        db.add(_universe("ACTIVEUSDT", rank=1, now=now))
        db.add(_futures_symbol("ACTIVEUSDT", now=now))
        db.add(_futures_symbol("SIGNALUSDT", now=now))
        db.add(_signal("signal-1", "SIGNALUSDT", now - timedelta(hours=1), now=now))
        db.commit()

        symbols = MarketCollector(db)._futures_kline_symbols()

        assert symbols[:2] == ["ACTIVEUSDT", "SIGNALUSDT"]


def test_futures_kline_symbols_filter_non_trading_signal_symbols_when_exchange_info_exists() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        db.add(_universe("ACTIVEUSDT", rank=1, now=now))
        db.add(_futures_symbol("ACTIVEUSDT", now=now))
        db.add(_futures_symbol("DEADUSDT", now=now, status="BREAK", contract_type="PERPETUAL"))
        db.add(_signal("signal-1", "DEADUSDT", now - timedelta(hours=1), now=now))
        db.commit()

        symbols = MarketCollector(db)._futures_kline_symbols()

        assert symbols == ["ACTIVEUSDT"]


def _futures_symbol(
    symbol: str,
    *,
    now: datetime,
    status: str = "TRADING",
    contract_type: str = "PERPETUAL",
) -> BinanceFuturesSymbol:
    return BinanceFuturesSymbol(
        symbol=symbol,
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        margin_asset="USDT",
        contract_type=contract_type,
        status=status,
        onboard_date=now,
        delivery_date=None,
        raw_json={},
        created_at=now,
        updated_at=now,
    )


def _universe(symbol: str, *, rank: int, now: datetime) -> MarketlabActiveUniverse:
    return MarketlabActiveUniverse(
        symbol=symbol,
        rank=rank,
        quote_volume=Decimal("1000000") / Decimal(rank),
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


def _signal(signal_id: str, symbol: str, signal_time: datetime, *, now: datetime) -> SignalForwardReturnLog:
    return SignalForwardReturnLog(
        signal_id=signal_id,
        symbol=symbol,
        timeframe="15m",
        signal_timestamp=signal_time,
        window_open_time=signal_time - timedelta(minutes=15),
        window_close_time=signal_time,
        direction="LONG",
        stage="MID_LONG",
        candidate_status="SIGNAL_CANDIDATE",
        core_score=Decimal("8"),
        evidence_score=Decimal("1"),
        evidence_data_completeness=4,
        confidence_tier="HIGH_CONF",
        execution_flag="ACTIVE",
        entry_ref="MARKET_REFERENCE_OK",
        sl_ref=Decimal("90"),
        tp_ref=Decimal("115"),
        price_at_signal=Decimal("100"),
        status_15m="READY",
        status_1h="READY",
        status_4h="WAITING_DATA",
        status_24h="WAITING_DATA",
        observation_epoch="post_stage8_v2",
        observation_start_utc=now,
        observation_marker=True,
        evidence={},
        created_at=now,
        updated_at=now,
    )
