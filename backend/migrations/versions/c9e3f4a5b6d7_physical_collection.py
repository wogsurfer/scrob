"""physical disc collection: releases, box sets and loans

The collection becomes the user's physical discs. Adds the tables for them
and a "physical" collection source, used for the collection entries mirrored
from the discs they own.

Revision ID: c9e3f4a5b6d7
Revises: b8d2e3f4a5c6
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "c9e3f4a5b6d7"
down_revision = "b8d2e3f4a5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE collectionsource ADD VALUE IF NOT EXISTS 'physical'")

    op.create_table(
        "physical_box_sets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("upc", sa.String(64)),
        sa.Column("cover_front", sa.String(500)),
        sa.Column("cover_back", sa.String(500)),
        sa.Column("purchase_date", sa.Date),
        sa.Column("release_date", sa.Date),
        sa.Column("store", sa.String(255)),
        sa.Column("condition", sa.String(100)),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_physical_box_set_name"),
    )

    op.create_table(
        "physical_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="owned"),
        sa.Column("clz_id", sa.Integer),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("sort_title", sa.String(500)),
        sa.Column("is_tv", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("series", sa.String(255)),
        sa.Column("tmdb_id", sa.Integer, index=True),
        sa.Column("media_id", sa.Integer, sa.ForeignKey("media.id", ondelete="SET NULL"), index=True),
        sa.Column("box_set_id", sa.Integer, sa.ForeignKey("physical_box_sets.id", ondelete="SET NULL"), index=True),
        sa.Column("release_year", sa.Integer),
        sa.Column("format", sa.String(50)),
        sa.Column("edition", sa.String(500)),
        sa.Column("distributor", sa.String(255)),
        sa.Column("barcode", sa.String(64), index=True),
        sa.Column("package", sa.String(100)),
        sa.Column("disc_count", sa.Integer),
        sa.Column("disc_release_date", sa.Date),
        sa.Column("runtime", sa.Integer),
        sa.Column("purchase_date", sa.Date),
        sa.Column("purchase_price", sa.Numeric(10, 2)),
        sa.Column("current_value", sa.Numeric(10, 2)),
        sa.Column("store", sa.String(255)),
        sa.Column("condition", sa.String(100)),
        sa.Column("location", sa.String(255)),
        sa.Column("owner", sa.String(255)),
        sa.Column("index_no", sa.Integer),
        sa.Column("my_rating", sa.Integer),
        sa.Column("seen_it", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("viewing_date", sa.Date),
        sa.Column("notes", sa.Text),
        sa.Column("tags", JSONB, nullable=False, server_default="[]"),
        sa.Column("cover_front", sa.String(500)),
        sa.Column("cover_back", sa.String(500)),
        sa.Column("specs", JSONB, nullable=False, server_default="{}"),
        sa.Column("date_added", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("edited_locally", sa.Boolean, nullable=False, server_default="false"),
        sa.UniqueConstraint("user_id", "clz_id", name="uq_physical_item_clz"),
    )
    op.create_index("idx_physical_items_user_status", "physical_items", ["user_id", "status"])

    op.create_table(
        "physical_loans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("physical_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("loaned_to", sa.String(255), nullable=False),
        sa.Column("loan_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date),
        sa.Column("returned_on", sa.Date),
        sa.Column("notes", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("physical_loans")
    op.drop_index("idx_physical_items_user_status", table_name="physical_items")
    op.drop_table("physical_items")
    op.drop_table("physical_box_sets")
    # Enum values can't be dropped in Postgres; "physical" stays unused.
