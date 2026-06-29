"""ohlcv aggregate kline tables

Revision ID: 0005_ohlcv_aggregate_klines
Revises: 0004_universe_tiers
Create Date: 2026-06-28 00:00:04.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_ohlcv_aggregate_klines"
down_revision = "0004_universe_tiers"
branch_labels = None
depends_on = None


TABLES = (
    ("futures_klines_15m", "uq_futures_klines_15m_symbol_open_time", "ix_futures_klines_15m_symbol_close_time"),
    ("futures_klines_1h", "uq_futures_klines_1h_symbol_open_time", "ix_futures_klines_1h_symbol_close_time"),
    ("futures_klines_4h", "uq_futures_klines_4h_symbol_open_time", "ix_futures_klines_4h_symbol_close_time"),
    ("futures_klines_24h", "uq_futures_klines_24h_symbol_open_time", "ix_futures_klines_24h_symbol_close_time"),
    ("spot_klines_15m", "uq_spot_klines_15m_symbol_open_time", "ix_spot_klines_15m_symbol_close_time"),
    ("spot_klines_1h", "uq_spot_klines_1h_symbol_open_time", "ix_spot_klines_1h_symbol_close_time"),
    ("spot_klines_4h", "uq_spot_klines_4h_symbol_open_time", "ix_spot_klines_4h_symbol_close_time"),
    ("spot_klines_24h", "uq_spot_klines_24h_symbol_open_time", "ix_spot_klines_24h_symbol_close_time"),
)


def upgrade() -> None:
    for table_name, unique_name, index_name in TABLES:
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(length=32), nullable=False),
            sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("open", sa.Numeric(38, 18), nullable=True),
            sa.Column("high", sa.Numeric(38, 18), nullable=True),
            sa.Column("low", sa.Numeric(38, 18), nullable=True),
            sa.Column("close", sa.Numeric(38, 18), nullable=True),
            sa.Column("volume", sa.Numeric(38, 18), nullable=True),
            sa.Column("quote_volume", sa.Numeric(38, 18), nullable=True),
            sa.Column("number_of_trades", sa.Integer(), nullable=True),
            sa.Column("taker_buy_base_volume", sa.Numeric(38, 18), nullable=True),
            sa.Column("taker_buy_quote_volume", sa.Numeric(38, 18), nullable=True),
            sa.Column("taker_sell_base_volume", sa.Numeric(38, 18), nullable=True),
            sa.Column("taker_sell_quote_volume", sa.Numeric(38, 18), nullable=True),
            sa.Column("source_interval", sa.String(length=8), nullable=False),
            sa.Column("expected_1m_count", sa.Integer(), nullable=False),
            sa.Column("actual_1m_count", sa.Integer(), nullable=False),
            sa.Column("missing_1m_count", sa.Integer(), nullable=False),
            sa.Column("aggregation_status", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("symbol", "open_time", name=unique_name),
        )
        op.create_index(op.f(f"ix_{table_name}_symbol"), table_name, ["symbol"], unique=False)
        op.create_index(op.f(f"ix_{table_name}_aggregation_status"), table_name, ["aggregation_status"], unique=False)
        op.create_index(index_name, table_name, ["symbol", "close_time"], unique=False)


def downgrade() -> None:
    for table_name, _unique_name, index_name in reversed(TABLES):
        op.drop_index(index_name, table_name=table_name)
        op.drop_index(op.f(f"ix_{table_name}_aggregation_status"), table_name=table_name)
        op.drop_index(op.f(f"ix_{table_name}_symbol"), table_name=table_name)
        op.drop_table(table_name)
