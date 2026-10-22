from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from models.watchlist import MovieWatchlist

from db import get_db
from dependencies import get_current_user
from models.users import User
from models.media import Media
from models.events import WatchEvent
from models.base import MediaType
from models.show import Show
from collections import defaultdict
from datetime import datetime, timedelta, UTC
from core.genres import normalise_genre
from models.emby_library_stats import EmbyLibraryStats

router = APIRouter()


@router.get("/hero")
async def dashboard_hero(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    movie_result = await db.execute(
        select(Media.poster_path)
        .where(
            Media.media_type == MediaType.movie,
            Media.poster_path.is_not(None),
        )
        .order_by(func.random())
        .limit(30)
    )

    show_result = await db.execute(
        select(Show.poster_path)
        .where(
            Show.poster_path.is_not(None),
        )
        .order_by(func.random())
        .limit(30)
    )

    posters = (
        movie_result.scalars().all()
        + show_result.scalars().all()
    )

    return {
        "posters": posters,
    }

@router.get("/stats")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # Average known runtime per show, used when an episode has no runtime
    show_avg = (
        select(
            Media.show_id.label("show_id"),
            func.avg(Media.runtime).label("avg_runtime"),
        )
        .where(
            Media.media_type == MediaType.episode,
            Media.runtime.is_not(None),
        )
        .group_by(Media.show_id)
        .subquery()
    )

    tv = await db.execute(
        select(
            func.count(WatchEvent.id),                          # plays
            func.count(func.distinct(WatchEvent.media_id)),     # unique episodes
            func.count(func.distinct(Media.show_id)),           # shows
            func.coalesce(
                func.sum(func.coalesce(Media.runtime, show_avg.c.avg_runtime, 0)),
                0,
            ),
        )
        .join(Media, Media.id == WatchEvent.media_id)
        .outerjoin(show_avg, show_avg.c.show_id == Media.show_id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.completed.is_(True),
            Media.media_type == MediaType.episode,
        )
    )

    plays, episodes, shows, tv_minutes = tv.one()

    # Movies
    movies = await db.execute(
        select(
            func.count(WatchEvent.id),
            func.count(func.distinct(WatchEvent.media_id)),
            func.coalesce(func.sum(Media.runtime), 0),
        )
        .join(Media, Media.id == WatchEvent.media_id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.completed.is_(True),
            Media.media_type == MediaType.movie,
        )
    )

    movie_plays, movies_watched, movie_minutes = movies.one()

    library = await db.scalar(
    select(EmbyLibraryStats)
)

    return {
        "tv": {
            "minutes": int(tv_minutes),
            "episodes": episodes,
            "plays": plays,
            "shows": shows,
        },
        "movies": {
            "minutes": int(movie_minutes),
            "plays": movie_plays,
            "movies": movies_watched,
        },
        "library": {
            "shows": library.shows if library else 0,
            "movies": library.movies if library else 0,
        },
    }

@router.get("/watchlist")
async def dashboard_watchlist(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(
            MovieWatchlist,
            Media,
        )
        .join(
            Media,
            MovieWatchlist.tmdb_id == Media.tmdb_id,
        )
        .where(
            MovieWatchlist.user_id == current_user.id,
        )
        .order_by(MovieWatchlist.title)
        .limit(6)
    )

    return [
        {
            "title": watch.title,
            "year": watch.year,
            "tmdb_id": watch.tmdb_id,
            "poster_path": media.poster_path,
            "tmdb_rating": media.tmdb_rating,
        }
        for watch, media in result.all()
    ]

@router.get("/runtime-test")
async def runtime_test(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            Media.season_number,
            Media.episode_number,
            Media.title,
            Media.runtime,
        )
        .join(Show, Show.id == Media.show_id)
        .where(
            Show.title == "Underbelly",
        )
        .order_by(
            Media.season_number,
            Media.episode_number,
        )
    )

    return [
        {
            "season": season,
            "episode": episode,
            "title": title,
            "runtime": runtime,
        }
        for season, episode, title, runtime in result.all()
    ]

from core import trakt

@router.get("/trakt-runtime-test")
async def trakt_runtime_test(
    db: AsyncSession = Depends(get_db),
):

    client_id = "igr0vU6QHwj5Jt8gAUpwb3kDXa2u-ZvBukCsggAL-20"

    data = await trakt.get_episode(
        client_id,
        13796,   # Underbelly Trakt ID
        1,
        1,
    )

    return data

@router.get("/last30")
async def dashboard_last30(
    db: AsyncSession = Depends(get_db),
):

    cutoff = datetime.now() - timedelta(days=30)

    result = await db.execute(
        select(
            WatchEvent,
            Media,
            Show,
        )
        .join(
            Media,
            WatchEvent.media_id == Media.id,
        )
        .outerjoin(
            Show,
            Media.show_id == Show.id,
        )
        .where(
            WatchEvent.user_id == 1,
            WatchEvent.watched_at >= cutoff,
            WatchEvent.completed.is_(True),
        )
    )

    rows = result.all()

    daily = defaultdict(lambda: {
        "episodes": 0,
        "movies": 0,
        "total": 0,
        "show_ids": set(),
    })

    genres = defaultdict(lambda: {
        "episodes": 0,
        "movies": 0,
        "shows": set(),
    })

    episode_total = 0
    movie_total = 0
    runtime_total = 0

    for watch, media, show in rows:

        day = watch.watched_at.date().isoformat()

        daily[day]["total"] += 1

        if media.runtime:
            runtime_total += media.runtime

        if media.media_type == MediaType.episode:

            episode_total += 1
            daily[day]["episodes"] += 1
            if media.show_id:
                daily[day]["show_ids"].add(media.show_id)

            if show and show.tmdb_data:
                for genre in show.tmdb_data.get("genres", []):
                    if not isinstance(genre, dict):
                        continue

                    raw_name = genre.get("name")

                    if not isinstance(raw_name, str) or not raw_name.strip():
                        continue

                    name = normalise_genre(raw_name)

                    if name is None:
                        continue

                    g = genres[name]
                    g["episodes"] += 1

                    if media.show_id:
                        g["shows"].add(media.show_id)

        elif media.media_type == MediaType.movie:

            movie_total += 1
            daily[day]["movies"] += 1

            if media.tmdb_data:
                for genre in media.tmdb_data.get("genres", []):
                    if not isinstance(genre, dict):
                        continue

                    raw_name = genre.get("name")

                    if not isinstance(raw_name, str) or not raw_name.strip():
                        continue

                    name = normalise_genre(raw_name)

                    if name is None:
                        continue

                    g = genres[name]
                    g["movies"] += 1

    return {
        "days": {
            day: {
                "episodes": values["episodes"],
                "movies": values["movies"],
                "total": values["total"],
                "shows": len(values["show_ids"]),
            }
            for day, values in daily.items()
        },
        "episodes": episode_total,
        "movies": movie_total,
        "runtime": runtime_total,
        "genres": [
            {
                "name": name,
                "episodes": data["episodes"],
                "movies": data["movies"],
                "shows": len(data["shows"]),
                "total": data["episodes"] + data["movies"],
            }
            for name, data in sorted(
                genres.items(),
                key=lambda x: x[1]["episodes"] + x[1]["movies"],
                reverse=True,
            )
        ],
    }

@router.get("/show-genre-test")
async def show_genre_test(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Show.title, Show.tmdb_data)
        .where(Show.tmdb_data.is_not(None))
        .limit(1)
    )

    row = result.first()

    if row is None:
        return {"error": "No shows"}

    title, tmdb = row

    return {
        "title": title,
        "tmdb_data": tmdb,
    }

@router.get("/genre-test")
async def genre_test(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Media.title, Media.tmdb_data)
        .where(
            Media.media_type == MediaType.movie,
            Media.tmdb_data.is_not(None),
        )
        .limit(1)
    )

    row = result.first()

    if row is None:
        return {"error": "No movies with tmdb_data"}

    title, tmdb = row

    return {
        "title": title,
        "tmdb_data": tmdb,
    }

from services.emby.client import EmbyClient

@router.get("/emby-libraries")
async def emby_libraries(current_user: User = Depends(get_current_user)):
    client = EmbyClient()
    return await client.get("/Library/VirtualFolders")

from services.emby.client import EmbyClient


@router.get("/emby-user")
async def emby_user(current_user: User = Depends(get_current_user)):
    client = EmbyClient()

    return await client.get("/Users")

from services.emby.sync import EmbySync

@router.post("/library-sync")
async def library_sync(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sync = EmbySync(db)

    data = await sync.sync()

    result = await db.execute(select(EmbyLibraryStats))
    stats = result.scalar_one_or_none()

    if stats is None:
        stats = EmbyLibraryStats()
        db.add(stats)

    stats.movies = data["movies"]
    stats.shows = data["shows"]
    stats.episodes = data["episodes"]

    await db.commit()
    await db.refresh(stats)

    return {
        "movies": stats.movies,
        "shows": stats.shows,
        "episodes": stats.episodes,
    }

@router.get("/dup-debug")
async def dup_debug(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import or_

    cutoff = datetime.now() - timedelta(days=2)

    result = await db.execute(
        select(Media, WatchEvent)
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.watched_at >= cutoff,
            or_(
                Media.title.ilike("%The Deep%"),
                Media.title.ilike("%CIA%"),
            ),
        )
        .order_by(WatchEvent.watched_at.desc())
    )

    return [
        {
            "media_id": media.id,
            "title": media.title,
            "show_id": media.show_id,
            "season": media.season_number,
            "episode": media.episode_number,
            "tmdb_id": media.tmdb_id,
            "watch_id": watch.id,
            "watched_at": str(watch.watched_at),
            "source": watch.watch_source,
        }
        for media, watch in result.all()
    ]