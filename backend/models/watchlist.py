from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

class MovieWatchlist(Base):
    __tablename__ = "movie_watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(index=True)

    trakt_id: Mapped[int | None] = mapped_column(index=True, nullable=True)

    tmdb_id: Mapped[int] = mapped_column(index=True)
    imdb_id: Mapped[str | None] = mapped_column(String, nullable=True)

    title: Mapped[str] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(nullable=True)

    from sqlalchemy import DateTime

    listed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    rank: Mapped[int | None] = mapped_column(nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    my_rating: Mapped[int | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )