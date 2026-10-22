"""add watch source to watch events

Revision ID: f3e4a5b6c7d8
Revises: 98ee86cad0cf
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "f3e4a5b6c7d8"
down_revision = "98ee86cad0cf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watch_events",
        sa.Column("watch_source", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("watch_events", "watch_source")
