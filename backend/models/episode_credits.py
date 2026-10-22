from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EpisodeCredits(Base):
    """Compact per-season guest-star and crew credits, used by the stats Cast & Crew counts."""

    __tablename__ = "episode_credits"

    tmdb_show_id  : Mapped[int]      = mapped_column(Integer, primary_key=True)
    season_number : Mapped[int]      = mapped_column(Integer, primary_key=True)
    data          : Mapped[dict]     = mapped_column(JSONB, nullable=False)
    fetched_at    : Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
