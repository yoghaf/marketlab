"""rich futures data layer

Revision ID: 0003_rich_futures_data_layer
Revises: 0002_collector_run_duration
Create Date: 2026-06-28 00:00:02.000000
"""
from alembic import op

from app.db.base import Base
from app.models import market  # noqa: F401

revision = "0003_rich_futures_data_layer"
down_revision = "0002_collector_run_duration"
branch_labels = None
depends_on = None

TABLES = [
    "futures_liquidation_events",
    "futures_funding_history",
    "futures_open_interest_history",
    "futures_top_trader_account_ratio",
    "futures_top_trader_position_ratio",
    "futures_global_long_short_account_ratio",
    "futures_taker_buy_sell_volume",
]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    for table_name in TABLES:
        op.drop_table(table_name)
