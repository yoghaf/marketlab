"""market candidate outcomes 15m

Revision ID: 0014_market_candidate_outcomes_15m
Revises: 0013_signal_candidates_readonly_15m
Create Date: 2026-06-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_market_candidate_outcomes_15m"
down_revision = "0013_signal_candidates_readonly_15m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_candidate_outcomes_15m",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("candidate_window_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_window_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_type", sa.String(length=64), nullable=False),
        sa.Column("candidate_direction", sa.String(length=32), nullable=False),
        sa.Column("classifier_status", sa.String(length=32), nullable=False),
        sa.Column("candidate_close_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("outcome_status", sa.String(length=32), nullable=False),
        sa.Column("outcome_15m_status", sa.String(length=32), nullable=False),
        sa.Column("outcome_30m_status", sa.String(length=32), nullable=False),
        sa.Column("outcome_1h_status", sa.String(length=32), nullable=False),
        sa.Column("outcome_4h_status", sa.String(length=32), nullable=False),
        sa.Column("future_return_15m", sa.Numeric(38, 18), nullable=True),
        sa.Column("future_return_30m", sa.Numeric(38, 18), nullable=True),
        sa.Column("future_return_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("future_return_4h", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_up_move_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_down_move_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_up_move_4h", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_down_move_4h", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_favorable_move_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_adverse_move_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_favorable_move_4h", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_adverse_move_4h", sa.Numeric(38, 18), nullable=True),
        sa.Column("followthrough_status", sa.String(length=32), nullable=False),
        sa.Column("invalidation_status", sa.String(length=32), nullable=False),
        sa.Column("source_candle_count_15m", sa.Integer(), nullable=False),
        sa.Column("source_candle_count_30m", sa.Integer(), nullable=False),
        sa.Column("source_candle_count_1h", sa.Integer(), nullable=False),
        sa.Column("source_candle_count_4h", sa.Integer(), nullable=False),
        sa.Column("missing_window_list", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "candidate_window_open_time", name="uq_market_candidate_outcomes_15m_symbol_open"),
    )
    op.create_index("ix_market_candidate_outcomes_15m_symbol", "market_candidate_outcomes_15m", ["symbol"])
    op.create_index(
        "ix_market_candidate_outcomes_15m_close_status",
        "market_candidate_outcomes_15m",
        ["candidate_window_close_time", "outcome_status"],
    )
    op.create_index(
        "ix_market_candidate_outcomes_15m_type",
        "market_candidate_outcomes_15m",
        ["candidate_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_candidate_outcomes_15m_type", table_name="market_candidate_outcomes_15m")
    op.drop_index("ix_market_candidate_outcomes_15m_close_status", table_name="market_candidate_outcomes_15m")
    op.drop_index("ix_market_candidate_outcomes_15m_symbol", table_name="market_candidate_outcomes_15m")
    op.drop_table("market_candidate_outcomes_15m")
