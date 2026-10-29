from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import aliased
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
from models.physical import PhysicalItem
from routers.media import enrich_with_state
from routers.watchlist import WATCHLIST_MEDIA_COLUMNS, watchlist_imdb_ratings

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

    # The physical disc collection: films and TV series owned on disc.
    owned = await db.execute(
        select(PhysicalItem.is_tv, func.count(PhysicalItem.id))
        # Films and series, a box set's counted by what's in it.
        .where(PhysicalItem.user_id == current_user.id, PhysicalItem.status == "owned", PhysicalItem.is_set.is_(False))
        .group_by(PhysicalItem.is_tv)
    )
    owned_counts = dict(owned.all())

    # TV is counted by show, not by season box: each disc's series, else the
    # set it's in (the Peanuts specials), else its own title.
    Parent = aliased(PhysicalItem)
    tv_discs = await db.execute(
        select(PhysicalItem.series, Parent.title, PhysicalItem.title)
        .outerjoin(Parent, Parent.id == PhysicalItem.parent_id)
        .where(
            PhysicalItem.user_id == current_user.id, PhysicalItem.status == "owned",
            PhysicalItem.is_set.is_(False), PhysicalItem.is_tv.is_(True),
        )
    )
    owned_counts[True] = len({(series or in_set or title).strip().lower() for series, in_set, title in tv_discs.all()})

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
            "shows": owned_counts.get(True, 0),
            "movies": owned_counts.get(False, 0),
        },
    }

@router.get("/watchlist")
async def dashboard_watchlist(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(MovieWatchlist, *WATCHLIST_MEDIA_COLUMNS)
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

    rows = result.all()
    ratings = await watchlist_imdb_ratings(rows)

    items = [
        {
            "id": row.media_id,
            "type": "movie",
            "title": row.MovieWatchlist.title,
            "year": row.MovieWatchlist.year,
            "tmdb_id": row.MovieWatchlist.tmdb_id,
            "poster_path": row.poster_path,
            "tmdb_rating": row.tmdb_rating,
            "imdb_rating": rating,
        }
        for row, rating in zip(rows, ratings)
    ]
    # Watched / list / collection state for the card's action buttons.
    if items:
        await enrich_with_state(db, current_user.id, items)
    return items

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


@router.get("/glance")
async def dashboard_glance(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The app's home screen widget: what you watched in the last 7 and 30
    days (with the 7 and 30 before, to compare), your run of days in a row
    with something watched, and the show you watched most this week."""
    from collections import Counter
    from zoneinfo import ZoneInfo

    now = datetime.now(UTC).replace(tzinfo=None)  # watched_at is stored in UTC
    rows = (await db.execute(
        select(WatchEvent.watched_at, Media.media_type, Media.runtime, Show.title)
        .join(Media, WatchEvent.media_id == Media.id)
        .outerjoin(Show, Media.show_id == Show.id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.completed.is_(True),
            WatchEvent.watched_at >= now - timedelta(days=60),
        )
    )).all()

    def period(start_days_ago: int, end_days_ago: int) -> dict:
        lo, hi = now - timedelta(days=start_days_ago), now - timedelta(days=end_days_ago)
        picked = [r for r in rows if lo <= r.watched_at < hi]
        return {
            "episodes": sum(r.media_type == MediaType.episode for r in picked),
            "movies": sum(r.media_type == MediaType.movie for r in picked),
            "minutes": sum(r.runtime or 0 for r in picked),
        }

    # Days in a row (Malta's days) with something watched, up to today; a
    # run that ended yesterday still counts until today is over. Only the
    # dates are fetched, so the whole history is cheap.
    malta = ZoneInfo("Europe/Malta")
    local_day = func.date(func.timezone("Europe/Malta", func.timezone("UTC", WatchEvent.watched_at)))
    days = set((await db.execute(
        select(local_day).distinct()
        .where(WatchEvent.user_id == current_user.id, WatchEvent.completed.is_(True), WatchEvent.watched_at.is_not(None))
    )).scalars())
    day = datetime.now(malta).date()
    if day not in days:
        day -= timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)

    week_shows = Counter(r.title for r in rows if r.title and r.watched_at >= now - timedelta(days=7))
    top = week_shows.most_common(1)
    return {
        "week": period(7, 0),
        "previous_week": period(14, 7),
        "month": period(30, 0),
        "previous_month": period(60, 30),
        "streak_days": streak,
        "top_show": {"title": top[0][0], "episodes": top[0][1]} if top else None,
    }


@router.get("/theme")
async def holiday_theme(day: str | None = None):
    """Today's holiday theme (Malta time), or null on an ordinary day.
    ?day=YYYY-MM-DD shows another day's, to preview it."""
    from datetime import date as _date
    from core.holidays import theme_for, today
    try:
        when = _date.fromisoformat(day) if day else today()
    except ValueError:
        when = today()
    return {"theme": theme_for(when)}
