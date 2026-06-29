"""signal candidates readonly 15m

Revision ID: 0013_signal_candidates_readonly_15m
Revises: 0012_spot_futures_context_evidence
Create Date: 2026-06-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_signal_candidates_readonly_15m"
down_revision = "0012_spot_futures_context_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_signal_candidates_readonly_15m",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("window_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("classifier_status", sa.String(length=32), nullable=False),
        sa.Column("candidate_type", sa.String(length=64), nullable=False),
        sa.Column("candidate_direction", sa.String(length=32), nullable=False),
        sa.Column("confidence_level", sa.String(length=16), nullable=False),
        sa.Column("confidence_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("block_reason", sa.Text(), nullable=True),
        sa.Column("not_entry_signal", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "window_open_time", name="uq_market_signal_candidates_readonly_15m_symbol_open"),
    )
    op.create_index("ix_market_signal_candidates_readonly_15m_symbol", "market_signal_candidates_readonly_15m", ["symbol"])
    op.create_index(
        "ix_market_signal_candidates_readonly_15m_close_status",
        "market_signal_candidates_readonly_15m",
        ["window_close_time", "classifier_status"],
    )
    op.create_index(
        "ix_market_signal_candidates_readonly_15m_type",
        "market_signal_candidates_readonly_15m",
        ["candidate_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_signal_candidates_readonly_15m_type", table_name="market_signal_candidates_readonly_15m")
    op.drop_index(
        "ix_market_signal_candidates_readonly_15m_close_status",
        table_name="market_signal_candidates_readonly_15m",
    )
    op.drop_index("ix_market_signal_candidates_readonly_15m_symbol", table_name="market_signal_candidates_readonly_15m")
    op.drop_table("market_signal_candidates_readonly_15m")
