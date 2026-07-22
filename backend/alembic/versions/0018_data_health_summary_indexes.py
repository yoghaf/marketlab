"""add covering indexes for data health summaries

Revision ID: 0018_data_health_summary_indexes
Revises: 0017_hot_path_indexes
Create Date: 2026-07-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_data_health_summary_indexes"
down_revision = "0017_hot_path_indexes"
branch_labels = None
depends_on = None


INDEXES = {
    "ix_rich_futures_5m_alignment_summary": (
        "rich_futures_5m_alignment",
        ["timeframe", "alignment_status", "window_close_time"],
    ),
    "ix_market_state_alignment_summary": (
        "market_state_alignment",
        ["timeframe", "snapshot_alignment_status", "funding_alignment_status", "window_close_time"],
    ),
    "ix_market_feature_context_15m_1h_summary": (
        "market_feature_context_15m_1h",
        ["context_status", "spot_support_status_15m", "feature_15m_window_close_time"],
    ),
    "ix_market_signal_candidates_readonly_15m_summary": (
        "market_signal_candidates_readonly_15m",
        ["classifier_status", "candidate_type", "candidate_direction", "window_close_time"],
    ),
}


def upgrade() -> None:
    for index_name, (table_name, columns) in INDEXES.items():
        if not _has_index(table_name, index_name):
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    for index_name, (table_name, _columns) in reversed(INDEXES.items()):
        if _has_index(table_name, index_name):
            op.drop_index(index_name, table_name=table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}
