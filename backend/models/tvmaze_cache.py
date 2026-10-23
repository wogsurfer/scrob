from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TvmazeCache(Base):
    """TVMaze show lookup + full episode list, keyed by normalised show title.

    Lets the calendar, Next Up and progress pages skip TVMaze's rate-limited API
    (20 requests / 10 s) on every page load.
    """

    __tablename__ = "tvmaze_cache"

    title_key  : Mapped[str]      = mapped_column(String, primary_key=True)
    data       : Mapped[dict]     = mapped_column(JSONB, nullable=False)
    fetched_at : Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
