"""spot futures context evidence

Revision ID: 0012_spot_futures_context_evidence
Revises: 0011_market_psychology_labels_15m
Create Date: 2026-06-29 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_spot_futures_context_evidence"
down_revision = "0011_market_psychology_labels_15m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_feature_context_15m_1h", sa.Column("futures_volume_15m", sa.Numeric(38, 18), nullable=True))
    op.add_column("market_feature_context_15m_1h", sa.Column("spot_volume_15m", sa.Numeric(38, 18), nullable=True))
    op.add_column(
        "market_feature_context_15m_1h", sa.Column("futures_quote_volume_15m", sa.Numeric(38, 18), nullable=True)
    )
    op.add_column(
        "market_feature_context_15m_1h", sa.Column("spot_quote_volume_15m", sa.Numeric(38, 18), nullable=True)
    )
    op.add_column(
        "market_feature_context_15m_1h",
        sa.Column("spot_futures_volume_ratio_15m", sa.Numeric(38, 18), nullable=True),
    )
    op.add_column(
        "market_feature_context_15m_1h", sa.Column("futures_taker_buy_ratio_15m", sa.Numeric(38, 18), nullable=True)
    )
    op.add_column(
        "market_feature_context_15m_1h", sa.Column("spot_taker_buy_ratio_15m", sa.Numeric(38, 18), nullable=True)
    )
    op.add_column(
        "market_feature_context_15m_1h",
        sa.Column("spot_missing_flag_15m", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "market_feature_context_15m_1h", sa.Column("spot_support_status_15m", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "market_feature_context_15m_1h", sa.Column("futures_led_score_15m", sa.Numeric(10, 4), nullable=True)
    )
    op.add_column(
        "market_feature_context_15m_1h", sa.Column("spot_support_score_15m", sa.Numeric(10, 4), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("market_feature_context_15m_1h", "spot_support_score_15m")
    op.drop_column("market_feature_context_15m_1h", "futures_led_score_15m")
    op.drop_column("market_feature_context_15m_1h", "spot_support_status_15m")
    op.drop_column("market_feature_context_15m_1h", "spot_missing_flag_15m")
    op.drop_column("market_feature_context_15m_1h", "spot_taker_buy_ratio_15m")
    op.drop_column("market_feature_context_15m_1h", "futures_taker_buy_ratio_15m")
    op.drop_column("market_feature_context_15m_1h", "spot_futures_volume_ratio_15m")
    op.drop_column("market_feature_context_15m_1h", "spot_quote_volume_15m")
    op.drop_column("market_feature_context_15m_1h", "futures_quote_volume_15m")
    op.drop_column("market_feature_context_15m_1h", "spot_volume_15m")
    op.drop_column("market_feature_context_15m_1h", "futures_volume_15m")
