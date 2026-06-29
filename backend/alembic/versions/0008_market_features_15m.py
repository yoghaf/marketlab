"""market features 15m

Revision ID: 0008_market_features_15m
Revises: 0007_market_state_alignment
Create Date: 2026-06-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_market_features_15m"
down_revision = "0007_market_state_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_features_15m",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("window_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_open", sa.Numeric(38, 18), nullable=True),
        sa.Column("price_high", sa.Numeric(38, 18), nullable=True),
        sa.Column("price_low", sa.Numeric(38, 18), nullable=True),
        sa.Column("price_close", sa.Numeric(38, 18), nullable=True),
        sa.Column("price_return_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("range_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("close_position", sa.Numeric(38, 18), nullable=True),
        sa.Column("body_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("upper_wick_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("lower_wick_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_volume", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_quote_volume", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_trade_count", sa.Integer(), nullable=True),
        sa.Column("kline_taker_buy_base", sa.Numeric(38, 18), nullable=True),
        sa.Column("kline_taker_sell_base", sa.Numeric(38, 18), nullable=True),
        sa.Column("kline_taker_buy_quote", sa.Numeric(38, 18), nullable=True),
        sa.Column("kline_taker_sell_quote", sa.Numeric(38, 18), nullable=True),
        sa.Column("kline_taker_buy_ratio", sa.Numeric(38, 18), nullable=True),
        sa.Column("kline_taker_sell_ratio", sa.Numeric(38, 18), nullable=True),
        sa.Column("spot_volume", sa.Numeric(38, 18), nullable=True),
        sa.Column("spot_quote_volume", sa.Numeric(38, 18), nullable=True),
        sa.Column("spot_taker_buy_ratio", sa.Numeric(38, 18), nullable=True),
        sa.Column("spot_futures_volume_ratio", sa.Numeric(38, 18), nullable=True),
        sa.Column("spot_missing_flag", sa.Boolean(), nullable=False),
        sa.Column("oi_open", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_close", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_change", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_change_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_value_open", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_value_close", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_value_change_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("global_long_short_ratio", sa.Numeric(38, 18), nullable=True),
        sa.Column("global_long_account", sa.Numeric(38, 18), nullable=True),
        sa.Column("global_short_account", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_position_ratio", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_long_position", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_short_position", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_account_ratio", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_long_account", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_short_account", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_taker_buy_volume", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_taker_sell_volume", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_taker_buy_sell_ratio", sa.Numeric(38, 18), nullable=True),
        sa.Column("funding_rate", sa.Numeric(38, 18), nullable=True),
        sa.Column("funding_status", sa.String(length=32), nullable=True),
        sa.Column("funding_age_seconds", sa.Integer(), nullable=True),
        sa.Column("current_oi_age_seconds", sa.Integer(), nullable=True),
        sa.Column("mark_age_seconds", sa.Integer(), nullable=True),
        sa.Column("futures_spread_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_book_age_seconds", sa.Integer(), nullable=True),
        sa.Column("spot_spread_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("spot_book_age_seconds", sa.Integer(), nullable=True),
        sa.Column("ohlcv_status", sa.String(length=32), nullable=False),
        sa.Column("rich_alignment_status", sa.String(length=32), nullable=True),
        sa.Column("snapshot_alignment_status", sa.String(length=32), nullable=True),
        sa.Column("funding_alignment_status", sa.String(length=32), nullable=True),
        sa.Column("feature_status", sa.String(length=32), nullable=False),
        sa.Column("feature_block_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "window_open_time", name="uq_market_features_15m_symbol_open"),
    )
    op.create_index("ix_market_features_15m_symbol", "market_features_15m", ["symbol"])
    op.create_index("ix_market_features_15m_feature_status", "market_features_15m", ["feature_status"])
    op.create_index(
        "ix_market_features_15m_close_status",
        "market_features_15m",
        ["window_close_time", "feature_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_features_15m_close_status", table_name="market_features_15m")
    op.drop_index("ix_market_features_15m_feature_status", table_name="market_features_15m")
    op.drop_index("ix_market_features_15m_symbol", table_name="market_features_15m")
    op.drop_table("market_features_15m")
