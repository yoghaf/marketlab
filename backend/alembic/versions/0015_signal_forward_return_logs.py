"""signal forward return logs

Revision ID: 0015_signal_forward_return_logs
Revises: 0014_market_candidate_outcomes_15m
Create Date: 2026-07-03 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0015_signal_forward_return_logs"
down_revision = "0014_market_candidate_outcomes_15m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _has_table("signal_forward_return_logs"):
        return
    op.create_table(
        "signal_forward_return_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.String(length=96), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("signal_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_open_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("candidate_status", sa.String(length=32), nullable=False),
        sa.Column("core_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("evidence_score", sa.Numeric(10, 4), nullable=True),
        sa.Column("evidence_data_completeness", sa.Integer(), nullable=True),
        sa.Column("confidence_tier", sa.String(length=32), nullable=True),
        sa.Column("execution_flag", sa.String(length=32), nullable=True),
        sa.Column("entry_ref", sa.String(length=64), nullable=True),
        sa.Column("sl_ref", sa.Numeric(38, 18), nullable=True),
        sa.Column("tp_ref", sa.Numeric(38, 18), nullable=True),
        sa.Column("price_at_signal", sa.Numeric(38, 18), nullable=True),
        sa.Column("price_at_15m", sa.Numeric(38, 18), nullable=True),
        sa.Column("price_at_1h", sa.Numeric(38, 18), nullable=True),
        sa.Column("price_at_4h", sa.Numeric(38, 18), nullable=True),
        sa.Column("price_at_24h", sa.Numeric(38, 18), nullable=True),
        sa.Column("status_15m", sa.String(length=32), nullable=False),
        sa.Column("status_1h", sa.String(length=32), nullable=False),
        sa.Column("status_4h", sa.String(length=32), nullable=False),
        sa.Column("status_24h", sa.String(length=32), nullable=False),
        sa.Column("source_artifact_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", name="uq_signal_forward_return_logs_signal_id"),
    )
    op.create_index("ix_signal_forward_return_logs_signal_id", "signal_forward_return_logs", ["signal_id"])
    op.create_index("ix_signal_forward_return_logs_signal_timestamp", "signal_forward_return_logs", ["signal_timestamp"])
    op.create_index("ix_signal_forward_return_logs_symbol", "signal_forward_return_logs", ["symbol"])
    op.create_index("ix_signal_forward_return_logs_symbol_time", "signal_forward_return_logs", ["symbol", "signal_timestamp"])
    op.create_index("ix_signal_forward_return_logs_stage_status", "signal_forward_return_logs", ["stage", "candidate_status"])


def downgrade() -> None:
    op.drop_index("ix_signal_forward_return_logs_stage_status", table_name="signal_forward_return_logs")
    op.drop_index("ix_signal_forward_return_logs_symbol_time", table_name="signal_forward_return_logs")
    op.drop_index("ix_signal_forward_return_logs_symbol", table_name="signal_forward_return_logs")
    op.drop_index("ix_signal_forward_return_logs_signal_timestamp", table_name="signal_forward_return_logs")
    op.drop_index("ix_signal_forward_return_logs_signal_id", table_name="signal_forward_return_logs")
    op.drop_table("signal_forward_return_logs")


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()
