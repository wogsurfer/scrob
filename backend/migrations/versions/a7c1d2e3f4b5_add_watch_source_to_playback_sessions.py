"""add watch source to playback sessions

Revision ID: a7c1d2e3f4b5
Revises: f3e4a5b6c7d8
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa


revision = "a7c1d2e3f4b5"
down_revision = "f3e4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "playback_sessions",
        sa.Column("watch_source", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("playback_sessions", "watch_source")
