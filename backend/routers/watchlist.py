import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db, AsyncSessionLocal
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
from core import tmdb
from routers.media import enrich_with_state

router = APIRouter()

# Keeps unfinished background lookups referenced until they complete.
_background_tasks: set[asyncio.Task] = set()
# IMDb ids being looked up right now, so repeat page loads don't queue them again.
_imdb_in_flight: set[str] = set()

# Only the fields the watchlist needs: Media.tmdb_data can hold full cast lists
# and loading it for a whole watchlist is slow.
WATCHLIST_MEDIA_COLUMNS = (
    Media.id.label("media_id"),
    Media.poster_path,
    Media.backdrop_path,
    Media.overview,
    Media.tmdb_rating,
    Media.runtime,
    Media.release_date,
    Media.tmdb_data["imdb_rating"].astext.label("stored_imdb_rating"),
    func.coalesce(
        Media.tmdb_data["imdb_id"].astext,
        Media.tmdb_data["external_ids"]["imdb_id"].astext,
    ).label("media_imdb_id"),
)


async def _save_imdb_ratings(found: dict[int, float]) -> None:
    """Store looked-up IMDb ratings on the movies so they are only fetched once."""
    if not found:
        return
    async with AsyncSessionLocal() as db:
        for media_id, rating in found.items():
            media = await db.get(Media, media_id)
            if media is not None:
                media.tmdb_data = {**(media.tmdb_data or {}), "imdb_rating": rating}
        await db.commit()


async def watchlist_imdb_ratings(rows, wait: float = 1.5) -> list[float | None]:
    """IMDb rating for each row selected with WATCHLIST_MEDIA_COLUMNS.

    Uses the rating stored on the movie when there is one. Missing ones are
    looked up, waiting at most `wait` seconds so a cold lookup doesn't hold the
    page; the rest finish in the background. Every rating found is stored.
    """
    ratings: list[float | None] = []
    lookups: dict[int, tuple[int, str]] = {}
    for i, row in enumerate(rows):
        stored = row.stored_imdb_rating
        ratings.append(float(stored) if stored not in (None, "null") else None)
        imdb_id = row.MovieWatchlist.imdb_id or row.media_imdb_id
        if ratings[-1] is None and row.media_id is not None and imdb_id:
            lookups[i] = (row.media_id, imdb_id)
    if not lookups:
        return ratings

    async def lookup(imdb_id: str):
        try:
            return await tmdb.get_imdb_rating(imdb_id)
        except Exception:
            return None
        finally:
            _imdb_in_flight.discard(imdb_id)

    tasks = {}
    for i, (_, imdb_id) in lookups.items():
        if imdb_id in _imdb_in_flight:
            continue
        _imdb_in_flight.add(imdb_id)
        tasks[i] = asyncio.create_task(lookup(imdb_id))
    if not tasks:
        return ratings
    await asyncio.wait(tasks.values(), timeout=wait)
    for i, task in tasks.items():
        if task.done():
            ratings[i] = task.result()

    media_by_task = {task: lookups[i][0] for i, task in tasks.items()}

    async def save_all():
        # Save in batches as lookups finish, so a long backfill keeps its
        # progress even if the server restarts part way through.
        pending = set(media_by_task)
        found: dict[int, float] = {}
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.result() is not None:
                    found[media_by_task[task]] = task.result()
            if len(found) >= 50 or not pending:
                await _save_imdb_ratings(found)
                found = {}

    saver = asyncio.create_task(save_all())
    _background_tasks.add(saver)
    saver.add_done_callback(_background_tasks.discard)
    return ratings


@router.get("")
async def get_watchlist(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MovieWatchlist, *WATCHLIST_MEDIA_COLUMNS)
        .outerjoin(
            Media,
            (Media.tmdb_id == MovieWatchlist.tmdb_id)
            & (Media.media_type == MediaType.movie),
        )
        .where(MovieWatchlist.user_id == current_user.id)
        .order_by(MovieWatchlist.title)
    )

    rows = result.all()
    ratings = await watchlist_imdb_ratings(rows)

    items = [
        {
            "id": row.media_id or row.MovieWatchlist.id,
            "type": "movie",
            "title": row.MovieWatchlist.title,
            "year": row.MovieWatchlist.year,
            "tmdb_id": row.MovieWatchlist.tmdb_id,
            "imdb_id": row.MovieWatchlist.imdb_id,
            "poster_path": row.poster_path,
            "backdrop_path": row.backdrop_path,
            "overview": row.overview,
            "tmdb_rating": row.tmdb_rating,
            "imdb_rating": rating,
            "runtime": row.runtime,
            "release_date": row.release_date,
        }
        for row, rating in zip(rows, ratings)
    ]
    # Watched / list / collection state for the card's action buttons.
    if items:
        await enrich_with_state(db, current_user.id, items)
    return items

@router.get("/count")
async def watchlist_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # How many films, without sending the whole list (it runs past 1,500).
    count = await db.scalar(select(func.count()).select_from(MovieWatchlist).where(MovieWatchlist.user_id == current_user.id))
    return {"count": count or 0}


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
