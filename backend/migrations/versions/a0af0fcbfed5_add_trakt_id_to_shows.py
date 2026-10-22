"""add trakt_id to shows

Revision ID: a0af0fcbfed5
Revises: 22135ef4f816
Create Date: 2026-08-02 15:42:50.262351

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0af0fcbfed5'
down_revision: Union[str, Sequence[str], None] = '22135ef4f816'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shows",
        sa.Column("trakt_id", sa.Integer(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_shows_trakt_id",
        "shows",
        ["trakt_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_shows_trakt_id",
        "shows",
        type_="unique",
    )
    op.drop_column(
        "shows",
        "trakt_id",
    )
