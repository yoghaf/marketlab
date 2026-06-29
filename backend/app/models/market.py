from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BinanceFuturesSymbol(Base, TimestampMixin):
    __tablename__ = "binance_futures_symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    base_asset: Mapped[str | None] = mapped_column(String(32))
    quote_asset: Mapped[str | None] = mapped_column(String(32))
    margin_asset: Mapped[str | None] = mapped_column(String(32))
    contract_type: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32))
    onboard_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("symbol", name="uq_binance_futures_symbols_symbol"),)


class BinanceSpotSymbol(Base, TimestampMixin):
    __tablename__ = "binance_spot_symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    base_asset: Mapped[str | None] = mapped_column(String(32))
    quote_asset: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32))
    is_spot_trading_allowed: Mapped[bool | None] = mapped_column(Boolean)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("symbol", name="uq_binance_spot_symbols_symbol"),)


class Futures24hTicker(Base, TimestampMixin):
    __tablename__ = "futures_24h_tickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_change_percent: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    weighted_avg_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("symbol", "event_time", name="uq_futures_24h_tickers_symbol_event_time"),)


class Spot24hTicker(Base, TimestampMixin):
    __tablename__ = "spot_24h_tickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_change_percent: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    weighted_avg_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("symbol", "event_time", name="uq_spot_24h_tickers_symbol_event_time"),)


class MarketlabUniverseSnapshot(Base, TimestampMixin):
    __tablename__ = "marketlab_universe_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collector_runs.id"))
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("snapshot_time", "symbol", name="uq_marketlab_universe_snapshots_time_symbol"),)


class MarketlabActiveUniverse(Base, TimestampMixin):
    __tablename__ = "marketlab_active_universe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_change_percent: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    high_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    low_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    trade_count_24h: Mapped[int | None] = mapped_column(Integer)
    collection_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_ACTIVE")
    is_full_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_light_watch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_signal_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("symbol", name="uq_marketlab_active_universe_symbol"),)


class FuturesKline1m(Base, TimestampMixin):
    __tablename__ = "futures_klines_1m"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    trade_count: Mapped[int | None] = mapped_column(Integer)
    taker_buy_base_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    taker_buy_quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    raw_json: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_futures_klines_1m_symbol_open_time"),
        Index("ix_futures_klines_1m_symbol_close_time", "symbol", "close_time"),
    )


class SpotKline1m(Base, TimestampMixin):
    __tablename__ = "spot_klines_1m"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    trade_count: Mapped[int | None] = mapped_column(Integer)
    taker_buy_base_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    taker_buy_quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    raw_json: Mapped[list | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_spot_klines_1m_symbol_open_time"),
        Index("ix_spot_klines_1m_symbol_close_time", "symbol", "close_time"),
    )


class AggregateKlineMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    high: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    low: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    close: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    number_of_trades: Mapped[int | None] = mapped_column(Integer)
    taker_buy_base_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    taker_buy_quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    taker_sell_base_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    taker_sell_quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    source_interval: Mapped[str] = mapped_column(String(8), nullable=False)
    expected_1m_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_1m_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_1m_count: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregation_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FuturesKline15m(Base, AggregateKlineMixin):
    __tablename__ = "futures_klines_15m"
    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_futures_klines_15m_symbol_open_time"),
        Index("ix_futures_klines_15m_symbol_close_time", "symbol", "close_time"),
    )


class FuturesKline1h(Base, AggregateKlineMixin):
    __tablename__ = "futures_klines_1h"
    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_futures_klines_1h_symbol_open_time"),
        Index("ix_futures_klines_1h_symbol_close_time", "symbol", "close_time"),
    )


class FuturesKline4h(Base, AggregateKlineMixin):
    __tablename__ = "futures_klines_4h"
    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_futures_klines_4h_symbol_open_time"),
        Index("ix_futures_klines_4h_symbol_close_time", "symbol", "close_time"),
    )


class FuturesKline24h(Base, AggregateKlineMixin):
    __tablename__ = "futures_klines_24h"
    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_futures_klines_24h_symbol_open_time"),
        Index("ix_futures_klines_24h_symbol_close_time", "symbol", "close_time"),
    )


class SpotKline15m(Base, AggregateKlineMixin):
    __tablename__ = "spot_klines_15m"
    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_spot_klines_15m_symbol_open_time"),
        Index("ix_spot_klines_15m_symbol_close_time", "symbol", "close_time"),
    )


class SpotKline1h(Base, AggregateKlineMixin):
    __tablename__ = "spot_klines_1h"
    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_spot_klines_1h_symbol_open_time"),
        Index("ix_spot_klines_1h_symbol_close_time", "symbol", "close_time"),
    )


class SpotKline4h(Base, AggregateKlineMixin):
    __tablename__ = "spot_klines_4h"
    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_spot_klines_4h_symbol_open_time"),
        Index("ix_spot_klines_4h_symbol_close_time", "symbol", "close_time"),
    )


class SpotKline24h(Base, AggregateKlineMixin):
    __tablename__ = "spot_klines_24h"
    __table_args__ = (
        UniqueConstraint("symbol", "open_time", name="uq_spot_klines_24h_symbol_open_time"),
        Index("ix_spot_klines_24h_symbol_close_time", "symbol", "close_time"),
    )


class FuturesOpenInterest(Base, TimestampMixin):
    __tablename__ = "futures_open_interest"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_interest: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("symbol", "event_time", name="uq_futures_open_interest_symbol_event_time"),)


class FuturesMarkFunding(Base, TimestampMixin):
    __tablename__ = "futures_mark_funding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    index_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    estimated_settle_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    last_funding_rate: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    next_funding_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("symbol", "event_time", name="uq_futures_mark_funding_symbol_event_time"),)


class FuturesBookTicker(Base, TimestampMixin):
    __tablename__ = "futures_book_tickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bid_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    bid_qty: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    ask_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    ask_qty: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("symbol", "event_time", name="uq_futures_book_tickers_symbol_event_time"),)


class SpotBookTicker(Base, TimestampMixin):
    __tablename__ = "spot_book_tickers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bid_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    bid_qty: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    ask_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    ask_qty: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("symbol", "event_time", name="uq_spot_book_tickers_symbol_event_time"),)


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collector_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target: Mapped[str | None] = mapped_column(String(128))
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    details_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (Index("ix_collector_runs_name_started", "collector_name", "started_at"),)


class CollectorError(Base):
    __tablename__ = "collector_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collector_run_id: Mapped[int | None] = mapped_column(ForeignKey("collector_runs.id"))
    collector_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    endpoint: Mapped[str | None] = mapped_column(String(256))
    status_code: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RateLimitUsage(Base):
    __tablename__ = "rate_limit_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collector_run_id: Mapped[int | None] = mapped_column(ForeignKey("collector_runs.id"))
    collector_name: Mapped[str | None] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    used_weight_1m: Mapped[int | None] = mapped_column(Integer)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_headers: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (Index("ix_rate_limit_usage_created_endpoint", "created_at", "endpoint"),)


class DataHealthSnapshot(Base, TimestampMixin):
    __tablename__ = "data_health_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    latest_futures_candle_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_spot_candle_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_open_interest_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_funding_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_futures_book_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_spot_book_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("symbol", "snapshot_time", name="uq_data_health_snapshots_symbol_time"),)


class FuturesTakerBuySellVolume(Base):
    __tablename__ = "futures_taker_buy_sell_volume"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    buy_sell_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    buy_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    sell_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("symbol", "period", "timestamp", name="uq_futures_taker_buy_sell_volume_symbol_period_time"),
    )


class FuturesGlobalLongShortAccountRatio(Base):
    __tablename__ = "futures_global_long_short_account_ratio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    long_short_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    long_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    short_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("symbol", "period", "timestamp", name="uq_futures_global_ls_account_symbol_period_time"),
    )


class FuturesTopTraderPositionRatio(Base):
    __tablename__ = "futures_top_trader_position_ratio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    long_short_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    long_position: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    short_position: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("symbol", "period", "timestamp", name="uq_futures_top_position_symbol_period_time"),
    )


class FuturesTopTraderAccountRatio(Base):
    __tablename__ = "futures_top_trader_account_ratio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    long_short_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    long_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    short_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("symbol", "period", "timestamp", name="uq_futures_top_account_symbol_period_time"),
    )


class FuturesOpenInterestHistory(Base):
    __tablename__ = "futures_open_interest_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sum_open_interest: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    sum_open_interest_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("symbol", "period", "timestamp", name="uq_futures_open_interest_history_symbol_period_time"),
    )


class FuturesFundingHistory(Base):
    __tablename__ = "futures_funding_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    funding_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    funding_rate: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("symbol", "funding_time", name="uq_futures_funding_history_symbol_funding_time"),
    )


class RichFutures5mAlignment(Base):
    __tablename__ = "rich_futures_5m_alignment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    window_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_5m_count: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_5m_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_5m_count: Mapped[int] = mapped_column(Integer, nullable=False)
    alignment_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    oi_open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_close: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_value_open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_value_close: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_long_short_ratio_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_long_account_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_short_account_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_position_ratio_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_long_position_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_short_position_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_account_ratio_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_long_account_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_short_account_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    taker_buy_volume_sum: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    taker_sell_volume_sum: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    taker_buy_sell_ratio_avg: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    source_timestamps_json: Mapped[list | None] = mapped_column(JSON)
    missing_timestamps_json: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "window_open_time",
            name="uq_rich_futures_5m_alignment_symbol_timeframe_open",
        ),
        Index("ix_rich_futures_5m_alignment_timeframe_close", "timeframe", "window_close_time"),
    )


class MarketStateAlignment(Base):
    __tablename__ = "market_state_alignment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    window_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_alignment_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    funding_alignment_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    current_oi_status: Mapped[str] = mapped_column(String(32), nullable=False)
    mark_status: Mapped[str] = mapped_column(String(32), nullable=False)
    futures_book_status: Mapped[str] = mapped_column(String(32), nullable=False)
    spot_book_status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_oi: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    current_oi_event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_oi_age_seconds: Mapped[int | None] = mapped_column(Integer)
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    index_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    last_funding_rate: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    next_funding_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mark_event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mark_age_seconds: Mapped[int | None] = mapped_column(Integer)
    futures_bid_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_ask_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_spread_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_book_event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    futures_book_age_seconds: Mapped[int | None] = mapped_column(Integer)
    spot_bid_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_ask_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_spread_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_book_event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    spot_book_age_seconds: Mapped[int | None] = mapped_column(Integer)
    latest_funding_rate: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    latest_funding_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_funding_mark_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    funding_age_seconds: Mapped[int | None] = mapped_column(Integer)
    funding_carry_forward_status: Mapped[str] = mapped_column(String(32), nullable=False)
    details_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "window_open_time",
            name="uq_market_state_alignment_symbol_timeframe_open",
        ),
        Index("ix_market_state_alignment_timeframe_close", "timeframe", "window_close_time"),
    )


class MarketFeature15m(Base):
    __tablename__ = "market_features_15m"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    window_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_high: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_low: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_close: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    range_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    close_position: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    body_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    upper_wick_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    lower_wick_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_trade_count: Mapped[int | None] = mapped_column(Integer)
    kline_taker_buy_base: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_sell_base: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_buy_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_sell_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_buy_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_sell_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_taker_buy_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_futures_volume_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_missing_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    oi_open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_close: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_value_open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_value_close: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_value_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_long_short_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_long_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_short_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_position_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_long_position: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_short_position: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_account_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_long_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_short_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_taker_buy_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_taker_sell_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_taker_buy_sell_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    funding_rate: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    funding_status: Mapped[str | None] = mapped_column(String(32))
    funding_age_seconds: Mapped[int | None] = mapped_column(Integer)
    current_oi_age_seconds: Mapped[int | None] = mapped_column(Integer)
    mark_age_seconds: Mapped[int | None] = mapped_column(Integer)
    futures_spread_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_book_age_seconds: Mapped[int | None] = mapped_column(Integer)
    spot_spread_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_book_age_seconds: Mapped[int | None] = mapped_column(Integer)
    ohlcv_status: Mapped[str] = mapped_column(String(32), nullable=False)
    rich_alignment_status: Mapped[str | None] = mapped_column(String(32))
    snapshot_alignment_status: Mapped[str | None] = mapped_column(String(32))
    funding_alignment_status: Mapped[str | None] = mapped_column(String(32))
    feature_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    feature_block_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "window_open_time", name="uq_market_features_15m_symbol_open"),
        Index("ix_market_features_15m_close_status", "window_close_time", "feature_status"),
    )


class MarketFeature1h(Base):
    __tablename__ = "market_features_1h"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    window_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_high: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_low: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_close: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    range_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    close_position: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    body_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    upper_wick_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    lower_wick_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_trade_count: Mapped[int | None] = mapped_column(Integer)
    kline_taker_buy_base: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_sell_base: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_buy_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_sell_quote: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_buy_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_sell_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_taker_buy_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_futures_volume_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_missing_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    oi_open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_close: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_value_open: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_value_close: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_value_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_long_short_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_long_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_short_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_position_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_long_position: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_short_position: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_account_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_long_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_short_account: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_taker_buy_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_taker_sell_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_taker_buy_sell_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    funding_rate: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    funding_status: Mapped[str | None] = mapped_column(String(32))
    funding_age_seconds: Mapped[int | None] = mapped_column(Integer)
    current_oi_age_seconds: Mapped[int | None] = mapped_column(Integer)
    mark_age_seconds: Mapped[int | None] = mapped_column(Integer)
    futures_spread_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    futures_book_age_seconds: Mapped[int | None] = mapped_column(Integer)
    spot_spread_pct: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    spot_book_age_seconds: Mapped[int | None] = mapped_column(Integer)
    ohlcv_status: Mapped[str] = mapped_column(String(32), nullable=False)
    rich_alignment_status: Mapped[str | None] = mapped_column(String(32))
    snapshot_alignment_status: Mapped[str | None] = mapped_column(String(32))
    funding_alignment_status: Mapped[str | None] = mapped_column(String(32))
    feature_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    feature_block_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "window_open_time", name="uq_market_features_1h_symbol_open"),
        Index("ix_market_features_1h_close_status", "window_close_time", "feature_status"),
    )


class MarketFeatureContext15m1h(Base):
    __tablename__ = "market_feature_context_15m_1h"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    feature_15m_window_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feature_15m_window_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context_1h_window_open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context_1h_window_close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feature_15m_status: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_1h_status: Mapped[str | None] = mapped_column(String(32))
    context_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    context_block_reason: Mapped[str | None] = mapped_column(Text)
    price_return_pct_15m: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    range_pct_15m: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    close_position_15m: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_buy_ratio_15m: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_change_pct_15m: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_long_short_ratio_15m: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_position_ratio_15m: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    funding_status_15m: Mapped[str | None] = mapped_column(String(32))
    price_return_pct_1h: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    range_pct_1h: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    close_position_1h: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    kline_taker_buy_ratio_1h: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    oi_change_pct_1h: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    global_long_short_ratio_1h: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    top_trader_position_ratio_1h: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    funding_status_1h: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "feature_15m_window_open_time",
            name="uq_market_feature_context_15m_1h_symbol_open",
        ),
        Index("ix_market_feature_context_15m_1h_close_status", "feature_15m_window_close_time", "context_status"),
    )


class MarketPsychologyLabel15m(Base):
    __tablename__ = "market_psychology_labels_15m"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    window_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context_status: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_label: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    secondary_labels: Mapped[list | None] = mapped_column(JSON)
    confidence_level: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    evidence: Mapped[dict | None] = mapped_column(JSON)
    label_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    block_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "window_open_time", name="uq_market_psychology_labels_15m_symbol_open"),
        Index("ix_market_psychology_labels_15m_close_status", "window_close_time", "label_status"),
    )


class FuturesLiquidationEvent(Base):
    __tablename__ = "futures_liquidation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    order_type: Mapped[str | None] = mapped_column(String(32))
    time_in_force: Mapped[str | None] = mapped_column(String(32))
    original_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    average_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    order_status: Mapped[str | None] = mapped_column(String(32))
    last_filled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    filled_accumulated_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    trade_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint(
            "event_time",
            "symbol",
            "side",
            "price",
            "original_quantity",
            name="uq_futures_liquidation_events_identity",
        ),
    )
