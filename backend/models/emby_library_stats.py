from sqlalchemy import Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class EmbyLibraryStats(Base):
    __tablename__ = "emby_library_stats"

    id: Mapped[int] = mapped_column(primary_key=True)

    movies: Mapped[int] = mapped_column(Integer, default=0)
    shows: Mapped[int] = mapped_column(Integer, default=0)
    episodes: Mapped[int] = mapped_column(Integer, default=0)
    runtime_minutes: Mapped[int] = mapped_column(Integer, default=0)

    last_synced: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )