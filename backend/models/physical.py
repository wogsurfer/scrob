"""The user's physical disc collection: one row per release they own or want
(a particular edition of a film or series on Blu-ray, 4K UHD, DVD...), with
box sets grouping several releases and loans tracking who has which disc.

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


class PhysicalBoxSet(Base):
    __tablename__ = "physical_box_sets"

    id            : Mapped[int]                = mapped_column(Integer, primary_key=True)
    user_id       : Mapped[int]                = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name          : Mapped[str]                = mapped_column(String(500), nullable=False)
    upc           : Mapped[Optional[str]]      = mapped_column(String(64))
    cover_front   : Mapped[Optional[str]]      = mapped_column(String(500))
    cover_back    : Mapped[Optional[str]]      = mapped_column(String(500))
    purchase_date : Mapped[Optional[date]]     = mapped_column(Date)
    release_date  : Mapped[Optional[date]]     = mapped_column(Date)
    store         : Mapped[Optional[str]]      = mapped_column(String(255))
    condition     : Mapped[Optional[str]]      = mapped_column(String(100))
    notes         : Mapped[Optional[str]]      = mapped_column(Text)
    created_at    : Mapped[datetime]           = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_physical_box_set_name"),)

    items : Mapped[list["PhysicalItem"]] = relationship(back_populates="box_set")


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
    box_set_id        : Mapped[Optional[int]]      = mapped_column(ForeignKey("physical_box_sets.id", ondelete="SET NULL"), index=True)
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

    box_set : Mapped[Optional["PhysicalBoxSet"]] = relationship(back_populates="items")
    loans   : Mapped[list["PhysicalLoan"]]       = relationship(back_populates="item", cascade="all, delete-orphan")


class PhysicalLoan(Base):
    __tablename__ = "physical_loans"

    id          : Mapped[int]            = mapped_column(Integer, primary_key=True)
    item_id     : Mapped[int]            = mapped_column(ForeignKey("physical_items.id", ondelete="CASCADE"), nullable=False, index=True)
    loaned_to   : Mapped[str]            = mapped_column(String(255), nullable=False)
    loan_date   : Mapped[date]           = mapped_column(Date, nullable=False)
    due_date    : Mapped[Optional[date]] = mapped_column(Date)
    returned_on : Mapped[Optional[date]] = mapped_column(Date)
    notes       : Mapped[Optional[str]]  = mapped_column(Text)

    item : Mapped["PhysicalItem"] = relationship(back_populates="loans")


class PhysicalPickValue(Base):
    """A pick-list value added by hand, offered in the edit form even before
    any disc uses it."""
    __tablename__ = "physical_pick_values"

    id      : Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id : Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    field   : Mapped[str] = mapped_column(String(50), nullable=False)
    value   : Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "field", "value", name="uq_physical_pick_value"),)
