"""market feature context 15m 1h

Revision ID: 0010_market_feature_context_15m_1h
Revises: 0009_market_features_1h
Create Date: 2026-06-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_market_feature_context_15m_1h"
down_revision = "0009_market_features_1h"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _has_table("market_feature_context_15m_1h"):
        return
    op.create_table(
        "market_feature_context_15m_1h",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("feature_15m_window_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_15m_window_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context_1h_window_open_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context_1h_window_close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feature_15m_status", sa.String(length=32), nullable=False),
        sa.Column("feature_1h_status", sa.String(length=32), nullable=True),
        sa.Column("context_status", sa.String(length=32), nullable=False),
        sa.Column("context_block_reason", sa.Text(), nullable=True),
        sa.Column("price_return_pct_15m", sa.Numeric(38, 18), nullable=True),
        sa.Column("range_pct_15m", sa.Numeric(38, 18), nullable=True),
        sa.Column("close_position_15m", sa.Numeric(38, 18), nullable=True),
        sa.Column("kline_taker_buy_ratio_15m", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_change_pct_15m", sa.Numeric(38, 18), nullable=True),
        sa.Column("global_long_short_ratio_15m", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_position_ratio_15m", sa.Numeric(38, 18), nullable=True),
        sa.Column("funding_status_15m", sa.String(length=32), nullable=True),
        sa.Column("price_return_pct_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("range_pct_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("close_position_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("kline_taker_buy_ratio_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_change_pct_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("global_long_short_ratio_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_position_ratio_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("funding_status_1h", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "feature_15m_window_open_time",
            name="uq_market_feature_context_15m_1h_symbol_open",
        ),
    )
    op.create_index("ix_market_feature_context_15m_1h_symbol", "market_feature_context_15m_1h", ["symbol"])
    op.create_index(
        "ix_market_feature_context_15m_1h_context_status",
        "market_feature_context_15m_1h",
        ["context_status"],
    )
    op.create_index(
        "ix_market_feature_context_15m_1h_close_status",
        "market_feature_context_15m_1h",
        ["feature_15m_window_close_time", "context_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_feature_context_15m_1h_close_status", table_name="market_feature_context_15m_1h")
    op.drop_index("ix_market_feature_context_15m_1h_context_status", table_name="market_feature_context_15m_1h")
    op.drop_index("ix_market_feature_context_15m_1h_symbol", table_name="market_feature_context_15m_1h")
    op.drop_table("market_feature_context_15m_1h")


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()
