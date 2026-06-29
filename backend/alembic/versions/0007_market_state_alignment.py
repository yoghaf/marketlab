"""market state alignment

Revision ID: 0007_market_state_alignment
Revises: 0006_rich_5m_alignment
Create Date: 2026-06-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_market_state_alignment"
down_revision = "0006_rich_5m_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_state_alignment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("window_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_alignment_status", sa.String(length=32), nullable=False),
        sa.Column("funding_alignment_status", sa.String(length=32), nullable=False),
        sa.Column("current_oi_status", sa.String(length=32), nullable=False),
        sa.Column("mark_status", sa.String(length=32), nullable=False),
        sa.Column("futures_book_status", sa.String(length=32), nullable=False),
        sa.Column("spot_book_status", sa.String(length=32), nullable=False),
        sa.Column("current_oi", sa.Numeric(38, 18), nullable=True),
        sa.Column("current_oi_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_oi_age_seconds", sa.Integer(), nullable=True),
        sa.Column("mark_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("index_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("last_funding_rate", sa.Numeric(38, 18), nullable=True),
        sa.Column("next_funding_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mark_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mark_age_seconds", sa.Integer(), nullable=True),
        sa.Column("futures_bid_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_ask_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_spread_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("futures_book_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("futures_book_age_seconds", sa.Integer(), nullable=True),
        sa.Column("spot_bid_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("spot_ask_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("spot_spread_pct", sa.Numeric(38, 18), nullable=True),
        sa.Column("spot_book_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spot_book_age_seconds", sa.Integer(), nullable=True),
        sa.Column("latest_funding_rate", sa.Numeric(38, 18), nullable=True),
        sa.Column("latest_funding_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_funding_mark_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("funding_age_seconds", sa.Integer(), nullable=True),
        sa.Column("funding_carry_forward_status", sa.String(length=32), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "timeframe",
            "window_open_time",
            name="uq_market_state_alignment_symbol_timeframe_open",
        ),
    )
    op.create_index(
        "ix_market_state_alignment_funding_alignment_status",
        "market_state_alignment",
        ["funding_alignment_status"],
    )
    op.create_index(
        "ix_market_state_alignment_snapshot_alignment_status",
        "market_state_alignment",
        ["snapshot_alignment_status"],
    )
    op.create_index("ix_market_state_alignment_symbol", "market_state_alignment", ["symbol"])
    op.create_index("ix_market_state_alignment_timeframe", "market_state_alignment", ["timeframe"])
    op.create_index(
        "ix_market_state_alignment_timeframe_close",
        "market_state_alignment",
        ["timeframe", "window_close_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_state_alignment_timeframe_close", table_name="market_state_alignment")
    op.drop_index("ix_market_state_alignment_timeframe", table_name="market_state_alignment")
    op.drop_index("ix_market_state_alignment_symbol", table_name="market_state_alignment")
    op.drop_index("ix_market_state_alignment_snapshot_alignment_status", table_name="market_state_alignment")
    op.drop_index("ix_market_state_alignment_funding_alignment_status", table_name="market_state_alignment")
    op.drop_table("market_state_alignment")
