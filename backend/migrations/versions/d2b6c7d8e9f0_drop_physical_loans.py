"""physical collection: drop loans

Lending discs out isn't tracked any more.

Revision ID: d2b6c7d8e9f0
Revises: d1a5b6c7d8e9
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op


revision = "d2b6c7d8e9f0"
down_revision = "d1a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("physical_loans")


def downgrade() -> None:
    op.create_table(
        "physical_loans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("physical_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("loaned_to", sa.String(255), nullable=False),
        sa.Column("loan_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("returned_on", sa.Date()),
        sa.Column("notes", sa.Text()),
    )
