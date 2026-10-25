"""physical collection pick-list values added by hand

The edit form's pick lists are the values already used on discs; this holds
the ones added on the Pick lists page before any disc uses them.

Revision ID: d0f4a5b6c7e8
Revises: c9e3f4a5b6d7
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op


revision = "d0f4a5b6c7e8"
down_revision = "c9e3f4a5b6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "physical_pick_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field", sa.String(50), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.UniqueConstraint("user_id", "field", "value", name="uq_physical_pick_value"),
    )
    op.create_index("idx_physical_pick_values_user", "physical_pick_values", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_physical_pick_values_user", table_name="physical_pick_values")
    op.drop_table("physical_pick_values")
