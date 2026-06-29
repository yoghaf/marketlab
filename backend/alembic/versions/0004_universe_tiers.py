"""universe tiers

Revision ID: 0004_universe_tiers
Revises: 0003_rich_futures_data_layer
Create Date: 2026-06-28 00:00:03.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_universe_tiers"
down_revision = "0003_rich_futures_data_layer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _add_column("marketlab_active_universe", sa.Column("price_change_percent", sa.Numeric(38, 18), nullable=True))
    _add_column("marketlab_active_universe", sa.Column("last_price", sa.Numeric(38, 18), nullable=True))
    _add_column("marketlab_active_universe", sa.Column("high_price", sa.Numeric(38, 18), nullable=True))
    _add_column("marketlab_active_universe", sa.Column("low_price", sa.Numeric(38, 18), nullable=True))
    _add_column("marketlab_active_universe", sa.Column("volume", sa.Numeric(38, 18), nullable=True))
    _add_column("marketlab_active_universe", sa.Column("trade_count_24h", sa.Integer(), nullable=True))
    _add_column("marketlab_active_universe", sa.Column("collection_tier", sa.String(32), nullable=False, server_default="NOT_ACTIVE"))
    _add_column("marketlab_active_universe", sa.Column("is_full_active", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column("marketlab_active_universe", sa.Column("is_light_watch", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column("marketlab_active_universe", sa.Column("is_signal_eligible", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("marketlab_active_universe", "is_signal_eligible")
    op.drop_column("marketlab_active_universe", "is_light_watch")
    op.drop_column("marketlab_active_universe", "is_full_active")
    op.drop_column("marketlab_active_universe", "collection_tier")
    op.drop_column("marketlab_active_universe", "trade_count_24h")
    op.drop_column("marketlab_active_universe", "volume")
    op.drop_column("marketlab_active_universe", "low_price")
    op.drop_column("marketlab_active_universe", "high_price")
    op.drop_column("marketlab_active_universe", "last_price")
    op.drop_column("marketlab_active_universe", "price_change_percent")


def _add_column(table_name: str, column: sa.Column) -> None:
    if column.name not in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}:
        op.add_column(table_name, column)
