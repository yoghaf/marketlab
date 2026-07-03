"""signal forward observation epoch

Revision ID: 0016_signal_forward_observation_epoch
Revises: 0015_signal_forward_return_logs
Create Date: 2026-07-03 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0016_signal_forward_observation_epoch"
down_revision = "0015_signal_forward_return_logs"
branch_labels = None
depends_on = None

OBSERVATION_START_SQL = "2026-07-03 06:15:20.000000"


def upgrade() -> None:
    if not _has_column("signal_forward_return_logs", "observation_epoch"):
        op.add_column("signal_forward_return_logs", sa.Column("observation_epoch", sa.String(length=32), nullable=True))
    if not _has_column("signal_forward_return_logs", "observation_start_utc"):
        op.add_column(
            "signal_forward_return_logs",
            sa.Column("observation_start_utc", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_column("signal_forward_return_logs", "observation_marker"):
        op.add_column("signal_forward_return_logs", sa.Column("observation_marker", sa.Boolean(), nullable=True))
    op.execute(
        f"""
        UPDATE signal_forward_return_logs
        SET observation_start_utc = '{OBSERVATION_START_SQL}',
            observation_marker = CASE
                WHEN datetime(source_artifact_generated_at) >= datetime('{OBSERVATION_START_SQL}') THEN 1
                ELSE 0
            END,
            observation_epoch = CASE
                WHEN datetime(source_artifact_generated_at) >= datetime('{OBSERVATION_START_SQL}') THEN 'STAGE8_OBSERVATION'
                ELSE 'PRE_STAGE8_FIX'
            END
        WHERE observation_epoch IS NULL
        """
    )
    if not _has_index("ix_signal_forward_return_logs_observation_epoch"):
        op.create_index(
            "ix_signal_forward_return_logs_observation_epoch",
            "signal_forward_return_logs",
            ["observation_epoch"],
        )


def downgrade() -> None:
    if _has_index("ix_signal_forward_return_logs_observation_epoch"):
        op.drop_index("ix_signal_forward_return_logs_observation_epoch", table_name="signal_forward_return_logs")
    if _has_column("signal_forward_return_logs", "observation_marker"):
        op.drop_column("signal_forward_return_logs", "observation_marker")
    if _has_column("signal_forward_return_logs", "observation_start_utc"):
        op.drop_column("signal_forward_return_logs", "observation_start_utc")
    if _has_column("signal_forward_return_logs", "observation_epoch"):
        op.drop_column("signal_forward_return_logs", "observation_epoch")


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index_name in {index["name"] for index in inspector.get_indexes("signal_forward_return_logs")}
