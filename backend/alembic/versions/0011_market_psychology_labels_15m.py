"""market psychology labels 15m

Revision ID: 0011_market_psychology_labels_15m
Revises: 0010_market_feature_context_15m_1h
Create Date: 2026-06-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_market_psychology_labels_15m"
down_revision = "0010_market_feature_context_15m_1h"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_psychology_labels_15m",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("window_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context_status", sa.String(length=32), nullable=False),
        sa.Column("primary_label", sa.String(length=64), nullable=False),
        sa.Column("secondary_labels", sa.JSON(), nullable=True),
        sa.Column("confidence_level", sa.String(length=16), nullable=False),
        sa.Column("confidence_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("label_status", sa.String(length=32), nullable=False),
        sa.Column("block_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "window_open_time", name="uq_market_psychology_labels_15m_symbol_open"),
    )
    op.create_index("ix_market_psychology_labels_15m_symbol", "market_psychology_labels_15m", ["symbol"])
    op.create_index(
        "ix_market_psychology_labels_15m_primary_label",
        "market_psychology_labels_15m",
        ["primary_label"],
    )
    op.create_index(
        "ix_market_psychology_labels_15m_label_status",
        "market_psychology_labels_15m",
        ["label_status"],
    )
    op.create_index(
        "ix_market_psychology_labels_15m_close_status",
        "market_psychology_labels_15m",
        ["window_close_time", "label_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_psychology_labels_15m_close_status", table_name="market_psychology_labels_15m")
    op.drop_index("ix_market_psychology_labels_15m_label_status", table_name="market_psychology_labels_15m")
    op.drop_index("ix_market_psychology_labels_15m_primary_label", table_name="market_psychology_labels_15m")
    op.drop_index("ix_market_psychology_labels_15m_symbol", table_name="market_psychology_labels_15m")
    op.drop_table("market_psychology_labels_15m")
