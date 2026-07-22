"""add indexes for API hot paths

Revision ID: 0017_hot_path_indexes
Revises: 0016_signal_forward_observation_epoch
Create Date: 2026-07-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_hot_path_indexes"
down_revision = "0016_signal_forward_observation_epoch"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_market_signal_candidates_readonly_15m_symbol_latest"


def upgrade() -> None:
    if not _has_index(INDEX_NAME):
        op.create_index(
            INDEX_NAME,
            "market_signal_candidates_readonly_15m",
            ["symbol", "window_close_time", "window_open_time", "id"],
        )


def downgrade() -> None:
    if _has_index(INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="market_signal_candidates_readonly_15m")


def _has_index(index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    table_name = "market_signal_candidates_readonly_15m"
    if table_name not in inspector.get_table_names():
        return False
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}
