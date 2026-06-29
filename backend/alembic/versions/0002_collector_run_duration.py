"""collector run duration

Revision ID: 0002_collector_run_duration
Revises: 0001_initial_marketlab_schema
Create Date: 2026-06-28 00:00:01.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_collector_run_duration"
down_revision = "0001_initial_marketlab_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _has_column("collector_runs", "duration_seconds"):
        return
    op.add_column("collector_runs", sa.Column("duration_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("collector_runs", "duration_seconds")


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}
