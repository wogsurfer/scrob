"""The user's physical disc collection: one row per release they own or want
(a particular edition of a film or series on Blu-ray, 4K UHD, DVD...).

A box set or a disc with several films (a double feature) is a release of
its own, marked is_set: it holds the shelf details (barcode, price,
location). The films on it are releases inside it (parent_id),
holding each film's own details.

Fields that are sorted, filtered or grouped by are columns; the long tail of
edition details (audio tracks, subtitles, discs, extras, cast...) lives in
`specs`.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class PhysicalItem(Base):
    __tablename__ = "physical_items"

    id                : Mapped[int]                = mapped_column(Integer, primary_key=True)
    user_id           : Mapped[int]                = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # "owned" or "wishlist".
    status            : Mapped[str]                = mapped_column(String(20), nullable=False, default="owned", server_default="owned")
    # The record's id in Collectorz, so a fresh export updates instead of duplicating.
    clz_id            : Mapped[Optional[int]]      = mapped_column(Integer)

    title             : Mapped[str]                = mapped_column(String(500), nullable=False)
    sort_title        : Mapped[Optional[str]]      = mapped_column(String(500))
    is_tv             : Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    series            : Mapped[Optional[str]]      = mapped_column(String(255))
    tmdb_id           : Mapped[Optional[int]]      = mapped_column(Integer, index=True)
    media_id          : Mapped[Optional[int]]      = mapped_column(ForeignKey("media.id", ondelete="SET NULL"), index=True)
    # A box set or multi-film disc, and the films in it in order.
    is_set            : Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    parent_id         : Mapped[Optional[int]]      = mapped_column(ForeignKey("physical_items.id", ondelete="CASCADE"), index=True)
    position          : Mapped[Optional[int]]      = mapped_column(Integer)
    release_year      : Mapped[Optional[int]]      = mapped_column(Integer)

    # Edition
    format            : Mapped[Optional[str]]      = mapped_column(String(50))
    edition           : Mapped[Optional[str]]      = mapped_column(String(500))
    distributor       : Mapped[Optional[str]]      = mapped_column(String(255))
    barcode           : Mapped[Optional[str]]      = mapped_column(String(64), index=True)
    package           : Mapped[Optional[str]]      = mapped_column(String(100))
    disc_count        : Mapped[Optional[int]]      = mapped_column(Integer)
    disc_release_date : Mapped[Optional[date]]     = mapped_column(Date)
    runtime           : Mapped[Optional[int]]      = mapped_column(Integer)

    # Personal
    purchase_date     : Mapped[Optional[date]]     = mapped_column(Date)
    purchase_price    : Mapped[Optional[Decimal]]  = mapped_column(Numeric(10, 2))
    current_value     : Mapped[Optional[Decimal]]  = mapped_column(Numeric(10, 2))
    store             : Mapped[Optional[str]]      = mapped_column(String(255))
    condition         : Mapped[Optional[str]]      = mapped_column(String(100))
    location          : Mapped[Optional[str]]      = mapped_column(String(255))
    owner             : Mapped[Optional[str]]      = mapped_column(String(255))
    index_no          : Mapped[Optional[int]]      = mapped_column(Integer)
    my_rating         : Mapped[Optional[int]]      = mapped_column(Integer)
    seen_it           : Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    viewing_date      : Mapped[Optional[date]]     = mapped_column(Date)
    notes             : Mapped[Optional[str]]      = mapped_column(Text)
    tags              : Mapped[list]               = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # Covers, stored under data/physical/covers.
    cover_front       : Mapped[Optional[str]]      = mapped_column(String(500))
    cover_back        : Mapped[Optional[str]]      = mapped_column(String(500))

    specs             : Mapped[dict]               = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    date_added        : Mapped[datetime]           = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at        : Mapped[datetime]           = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    # Set when edited in Watchd, so a later Collectorz import leaves it alone.
    edited_locally    : Mapped[bool]               = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("user_id", "clz_id", name="uq_physical_item_clz"),
        Index("idx_physical_items_user_status", "user_id", "status"),
    )

    parent   : Mapped[Optional["PhysicalItem"]] = relationship(remote_side="PhysicalItem.id", back_populates="contents")
    contents : Mapped[list["PhysicalItem"]]     = relationship(back_populates="parent", order_by="PhysicalItem.position")



class PhysicalPickValue(Base):
    """A pick-list value added by hand, offered in the edit form even before
    any disc uses it."""
    __tablename__ = "physical_pick_values"

    id      : Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id : Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    field   : Mapped[str] = mapped_column(String(50), nullable=False)
    value   : Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "field", "value", name="uq_physical_pick_value"),)
