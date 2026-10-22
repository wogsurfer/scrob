from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from dependencies import get_current_user
from models.watchlist import MovieWatchlist
from models.media import Media
from models.base import MediaType
from models.users import User
from services.media_service import get_or_create_movie
from models.users import UserSettings
from models.global_settings import GlobalSettings
from routers.media import _effective_radarr
from core import radarr as radarr_client

router = APIRouter()


@router.get("")
async def get_watchlist(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MovieWatchlist, Media)
        .outerjoin(
            Media,
            (Media.tmdb_id == MovieWatchlist.tmdb_id)
            & (Media.media_type == MediaType.movie),
        )
        .order_by(MovieWatchlist.title)
    )

    rows = result.all()

    return [
        {
            "id": watch.id,
            "title": watch.title,
            "year": watch.year,
            "tmdb_id": watch.tmdb_id,
            "imdb_id": watch.imdb_id,
            "poster_path": media.poster_path if media else None,
            "backdrop_path": media.backdrop_path if media else None,
            "overview": media.overview if media else None,
            "tmdb_rating": media.tmdb_rating if media else None,
            "runtime": media.runtime if media else None,
            "release_date": media.release_date if media else None,
        }
        for watch, media in rows
    ]

@router.post("")
async def add_to_watchlist(
    tmdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    media = await get_or_create_movie(db, tmdb_id)

    exists = (
        await db.execute(
            select(MovieWatchlist).where(
                MovieWatchlist.user_id == current_user.id,
                MovieWatchlist.tmdb_id == tmdb_id,
            )
        )
    ).scalar_one_or_none()

    if exists:
        return {
            "id": exists.id,
            "tmdb_id": exists.tmdb_id,
            "title": exists.title,
            "already_exists": True,
        }

    watch = MovieWatchlist(
        user_id=current_user.id,
        trakt_id=None,
        tmdb_id=tmdb_id,
        imdb_id=None,
        title=media.title,
        year=int(media.release_date[:4]) if media.release_date else None,
        listed_at=datetime.utcnow(),
    )

    db.add(watch)
    await db.commit()
    await db.refresh(watch)

    # Automatically add movies from the Watchd Watchlist to Radarr.
    try:
        settings_q = await db.execute(
            select(UserSettings).where(
                UserSettings.user_id == current_user.id
            )
        )
        user_settings = settings_q.scalar_one_or_none()

        global_q = await db.execute(
            select(GlobalSettings).where(
                GlobalSettings.id == 1
            )
        )
        global_settings = global_q.scalar_one_or_none()

        radarr_cfg = _effective_radarr(
            user_settings,
            global_settings
        )

        import logging
        logging.getLogger("uvicorn.error").info(
            f"Watchlist: Radarr settings — "
            f"url={bool(getattr(user_settings, 'radarr_url', None))}, "
            f"token={bool(getattr(user_settings, 'radarr_token', None))}, "
            f"root={bool(getattr(user_settings, 'radarr_root_folder', None))}, "
            f"profile={bool(getattr(user_settings, 'radarr_quality_profile', None))}"
        )

        if radarr_cfg:
            await radarr_client.add_movie(
                url=radarr_cfg.radarr_url,
                token=radarr_cfg.radarr_token,
                tmdb_id=tmdb_id,
                title=watch.title,
                root_folder=radarr_cfg.radarr_root_folder,
                quality_profile_id=radarr_cfg.radarr_quality_profile,
                tags=radarr_cfg.radarr_tags,
            )

    except Exception as e:
        import logging
        logging.getLogger("uvicorn.error").error(
            f"Watchlist: Radarr error for tmdb:{tmdb_id}: {e}"
        )

    return {
        "id": watch.id,
        "tmdb_id": watch.tmdb_id,
        "title": watch.title,
        "already_exists": False,
    }

@router.delete("/{tmdb_id}")
async def remove_from_watchlist(
    tmdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MovieWatchlist).where(
            MovieWatchlist.user_id == current_user.id,
            MovieWatchlist.tmdb_id == tmdb_id,
        )
    )
    watch = result.scalar_one_or_none()

    if not watch:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    await db.delete(watch)
    await db.commit()

    return {"message": "Item removed"}
