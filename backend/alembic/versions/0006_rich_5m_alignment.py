"""rich 5m alignment

Revision ID: 0006_rich_5m_alignment
Revises: 0005_ohlcv_aggregate_klines
Create Date: 2026-06-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_rich_5m_alignment"
down_revision = "0005_ohlcv_aggregate_klines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _has_table("rich_futures_5m_alignment"):
        return
    op.create_table(
        "rich_futures_5m_alignment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("window_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_5m_count", sa.Integer(), nullable=False),
        sa.Column("actual_5m_count", sa.Integer(), nullable=False),
        sa.Column("missing_5m_count", sa.Integer(), nullable=False),
        sa.Column("alignment_status", sa.String(length=32), nullable=False),
        sa.Column("oi_open", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_close", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_change", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_change_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_value_open", sa.Numeric(38, 18), nullable=True),
        sa.Column("oi_value_close", sa.Numeric(38, 18), nullable=True),
        sa.Column("global_long_short_ratio_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("global_long_account_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("global_short_account_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_position_ratio_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_long_position_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_short_position_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_account_ratio_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_long_account_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("top_trader_short_account_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("taker_buy_volume_sum", sa.Numeric(38, 18), nullable=True),
        sa.Column("taker_sell_volume_sum", sa.Numeric(38, 18), nullable=True),
        sa.Column("taker_buy_sell_ratio_avg", sa.Numeric(38, 18), nullable=True),
        sa.Column("source_timestamps_json", sa.JSON(), nullable=True),
        sa.Column("missing_timestamps_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "timeframe",
            "window_open_time",
            name="uq_rich_futures_5m_alignment_symbol_timeframe_open",
        ),
    )
    op.create_index(
        "ix_rich_futures_5m_alignment_alignment_status",
        "rich_futures_5m_alignment",
        ["alignment_status"],
    )
    op.create_index("ix_rich_futures_5m_alignment_symbol", "rich_futures_5m_alignment", ["symbol"])
    op.create_index("ix_rich_futures_5m_alignment_timeframe", "rich_futures_5m_alignment", ["timeframe"])
    op.create_index(
        "ix_rich_futures_5m_alignment_timeframe_close",
        "rich_futures_5m_alignment",
        ["timeframe", "window_close_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_rich_futures_5m_alignment_timeframe_close", table_name="rich_futures_5m_alignment")
    op.drop_index("ix_rich_futures_5m_alignment_timeframe", table_name="rich_futures_5m_alignment")
    op.drop_index("ix_rich_futures_5m_alignment_symbol", table_name="rich_futures_5m_alignment")
    op.drop_index("ix_rich_futures_5m_alignment_alignment_status", table_name="rich_futures_5m_alignment")
    op.drop_table("rich_futures_5m_alignment")


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()
