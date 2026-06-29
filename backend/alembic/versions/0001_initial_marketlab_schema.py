"""initial marketlab schema

Revision ID: 0001_initial_marketlab_schema
Revises:
Create Date: 2026-06-28 00:00:00.000000
"""
from alembic import op

from app.db.base import Base
from app.models import market  # noqa: F401

revision = "0001_initial_marketlab_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
