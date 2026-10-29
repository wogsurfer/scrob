"""physical collection: half-star ratings

my_rating takes halves (7.5 out of 10), not just whole stars.

Revision ID: d3c7d8e9f0a1
Revises: d2b6c7d8e9f0
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op


revision = "d3c7d8e9f0a1"
down_revision = "d2b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("physical_items", "my_rating", type_=sa.Numeric(3, 1), existing_type=sa.Integer())


def downgrade() -> None:
    op.alter_column(
        "physical_items", "my_rating", type_=sa.Integer(), existing_type=sa.Numeric(3, 1),
        postgresql_using="round(my_rating)::integer",
    )
