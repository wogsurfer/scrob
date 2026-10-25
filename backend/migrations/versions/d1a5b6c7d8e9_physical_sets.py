"""physical collection: box sets and multi-film discs become releases

A box set or double feature is now a release of its own (is_set), holding
the shelf details (barcode, price, location, loans...), with the films on it
as releases inside it (parent_id, in `position` order). Each old box set
becomes such a release, taking what its films had in common, and the
physical_box_sets table goes.

Revision ID: d1a5b6c7d8e9
Revises: d0f4a5b6c7e8
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op


revision = "d1a5b6c7d8e9"
down_revision = "d0f4a5b6c7e8"
branch_labels = None
depends_on = None

# Shelf details a set takes from its films when they all agree.
_COMMON = ("format", "edition", "distributor", "package", "location", "owner", "store", "condition",
           "purchase_date", "disc_release_date")


def upgrade() -> None:
    op.add_column("physical_items", sa.Column("is_set", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("physical_items", sa.Column(
        "parent_id", sa.Integer(), sa.ForeignKey("physical_items.id", ondelete="CASCADE"), nullable=True,
    ))
    op.add_column("physical_items", sa.Column("position", sa.Integer(), nullable=True))
    op.create_index("idx_physical_items_parent", "physical_items", ["parent_id"])

    conn = op.get_bind()
    boxes = conn.execute(sa.text(
        "SELECT id, user_id, name, upc, cover_front, purchase_date, release_date, store, condition, notes"
        " FROM physical_box_sets ORDER BY id"
    )).mappings().all()
    for box in boxes:
        films = conn.execute(sa.text(
            "SELECT * FROM physical_items WHERE box_set_id = :b ORDER BY release_year NULLS LAST, sort_title, title"
        ), {"b": box["id"]}).mappings().all()
        if not films:
            continue

        def common(col):
            values = {f[col] for f in films if f[col] is not None}
            return values.pop() if len(values) == 1 else None

        status = "owned" if any(f["status"] == "owned" for f in films) else films[0]["status"]
        discs = [f["disc_count"] for f in films if f["disc_count"]]
        prices = [f["purchase_price"] for f in films if f["purchase_price"] is not None]
        values = {col: common(col) for col in _COMMON}
        values.update({
            "user_id": box["user_id"],
            "status": status,
            "title": box["name"],
            "is_tv": all(f["is_tv"] for f in films),
            "barcode": box["upc"] or common("barcode"),
            "disc_count": sum(discs) if discs else None,
            "purchase_price": sum(prices) if prices else None,
            "purchase_date": box["purchase_date"] or values["purchase_date"],
            "disc_release_date": box["release_date"] or values["disc_release_date"],
            "store": box["store"] or values["store"],
            "condition": box["condition"] or values["condition"],
            "notes": box["notes"],
            "cover_front": box["cover_front"],
            "date_added": min(f["date_added"] for f in films),
        })
        cols = ", ".join(values)
        params = ", ".join(f":{c}" for c in values)
        set_id = conn.execute(sa.text(
            f"INSERT INTO physical_items ({cols}, is_set, tags, specs) VALUES ({params}, true, '[]', '{{}}') RETURNING id"
        ), values).scalar()
        for position, film in enumerate(films, 1):
            conn.execute(sa.text(
                "UPDATE physical_items SET parent_id = :p, position = :n, status = :s WHERE id = :id"
            ), {"p": set_id, "n": position, "s": status, "id": film["id"]})
        # Loans are of the box, not the films in it.
        conn.execute(sa.text(
            "UPDATE physical_loans SET item_id = :p WHERE item_id IN (SELECT id FROM physical_items WHERE parent_id = :p)"
        ), {"p": set_id})

    op.drop_column("physical_items", "box_set_id")
    op.drop_table("physical_box_sets")


def downgrade() -> None:
    raise NotImplementedError("Box sets can't be split back out; restore a backup from before this migration.")
