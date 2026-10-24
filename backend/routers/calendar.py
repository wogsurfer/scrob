import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db, engine, AsyncSessionLocal
from dependencies import get_current_user

from models.tvmaze_cache import TvmazeCache
from models.users import User
from models.media import Media
from models.events import WatchEvent
from models.base import MediaType
from models.show import Show
from core import tmdb
from routers.media import get_user_tmdb_key

router = APIRouter()

MALTA_TZ = ZoneInfo("Europe/Malta")


# =========================================================
# Helpers
# =========================================================

def parse_tvmaze_airstamp(value: str | None):
    """
    Convert a TVMaze ISO-8601 airstamp into Malta local time.

    TVMaze airstamp is timezone-aware and therefore preferable
    to guessing an airing time from a date-only value.
    """
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            return None

        return dt.astimezone(MALTA_TZ)

    except (ValueError, TypeError):
        return None


def normalise_title(value: str | None) -> str:
    if not value:
        return ""

    return (
        value.lower()
        .replace("&", "and")
        .replace(":", "")
        .replace("-", " ")
        .replace("'", "")
        .strip()
    )

def get_network_name(show) -> str | None:
    """First network listed in the show's stored TMDB data."""
    networks = (show.tmdb_data or {}).get("networks") or []

    for network in networks:
        if isinstance(network, dict) and network.get("name"):
            return network["name"]

    return None

# =========================================================
# TVMaze
# =========================================================

# TVMaze allows 20 requests per 10 seconds, and every page that shows schedules
# (calendar, Next Up, progress) needs two requests per show. Episode lists are
# cached in the tvmaze_cache table: a fresh entry is used as is, a stale one is
# served immediately while it refreshes in the background, and TVMaze is only
# waited on for a show that has never been fetched.
_TVMAZE_FRESH = timedelta(hours=6)
_tvmaze_memory: dict[str, tuple[datetime, dict]] = {}
_tvmaze_inflight: dict[str, asyncio.Task] = {}
_tvmaze_limit = asyncio.Semaphore(4)
_tvmaze_loaded = False
_tvmaze_load_lock = asyncio.Lock()


async def _load_tvmaze_cache():
    """Create the cache table if needed and load every row into memory, once per process."""
    global _tvmaze_loaded
    if _tvmaze_loaded:
        return
    async with _tvmaze_load_lock:
        if _tvmaze_loaded:
            return
        try:
            async with engine.begin() as conn:
                await conn.run_sync(TvmazeCache.__table__.create, checkfirst=True)
            async with AsyncSessionLocal() as db:
                rows = await db.execute(
                    select(TvmazeCache.title_key, TvmazeCache.fetched_at, TvmazeCache.data)
                )
                for key, fetched_at, data in rows.all():
                    _tvmaze_memory.setdefault(key, (fetched_at, data or {}))
        except Exception as e:
            print("TVMAZE CACHE LOAD ERROR:", f"{type(e).__name__}: {e}")
        _tvmaze_loaded = True


async def _tvmaze_get(client: httpx.AsyncClient, url: str, params: dict | None = None):
    response = None
    for attempt in range(4):
        async with _tvmaze_limit:
            response = await client.get(url, params=params)
        if response.status_code != 429:
            return response
        await asyncio.sleep(float(response.headers.get("Retry-After") or 2 * (attempt + 1)))
    return response


async def _fetch_tvmaze(show_title: str) -> dict | None:
    """{"episodes": [...]} (empty when TVMaze has no matching show), or None on an error."""
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={
                "User-Agent": "Scrob/1.0",
            },
        ) as client:

            response = await _tvmaze_get(
                client,
                "https://api.tvmaze.com/singlesearch/shows",
                {"q": show_title},
            )

            if response.status_code == 404:
                return {"episodes": []}

            response.raise_for_status()

            show_data = response.json()

            tvmaze_title = show_data.get("name")

            # Protect against an obviously bad fuzzy match.
            if (
                normalise_title(tvmaze_title)
                != normalise_title(show_title)
            ):
                return {"episodes": []}

            tvmaze_id = show_data.get("id")

            if not tvmaze_id:
                return {"episodes": []}

            # Get the complete episode list.
            response = await _tvmaze_get(
                client,
                f"https://api.tvmaze.com/shows/{tvmaze_id}/episodes",
            )

            response.raise_for_status()

            return {"tvmaze_id": tvmaze_id, "episodes": response.json()}

    except Exception as e:
        print(
            "CALENDAR TVMAZE ERROR:",
            show_title,
            f"{type(e).__name__}: {e}",
        )
        return None


async def _refresh_tvmaze(key: str, show_title: str) -> dict | None:
    data = await _fetch_tvmaze(show_title)
    if data is None:
        return None  # keep whatever is cached
    now = datetime.utcnow()
    _tvmaze_memory[key] = (now, data)
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(TvmazeCache, key)
            if row:
                row.data = data
                row.fetched_at = now
            else:
                db.add(TvmazeCache(title_key=key, data=data, fetched_at=now))
            await db.commit()
    except Exception as e:
        print("TVMAZE CACHE SAVE ERROR:", show_title, f"{type(e).__name__}: {e}")
    return data


def _refresh_tvmaze_once(key: str, show_title: str) -> asyncio.Task:
    """One refresh per show at a time, however many requests ask for it."""
    task = _tvmaze_inflight.get(key)
    if task is None or task.done():
        task = asyncio.create_task(_refresh_tvmaze(key, show_title))
        _tvmaze_inflight[key] = task
        task.add_done_callback(
            lambda t, k=key: _tvmaze_inflight.pop(k, None) if _tvmaze_inflight.get(k) is t else None
        )
    return task


async def _cached_tvmaze_episodes(show_title: str) -> list:
    await _load_tvmaze_cache()
    key = normalise_title(show_title)
    hit = _tvmaze_memory.get(key)
    if hit:
        if datetime.utcnow() - hit[0] > _TVMAZE_FRESH:
            _refresh_tvmaze_once(key, show_title)
        return hit[1].get("episodes") or []
    # Shielded so a cancelled page request doesn't abort a fetch others may share.
    data = await asyncio.shield(_refresh_tvmaze_once(key, show_title))
    return (data or {}).get("episodes") or []


async def get_tvmaze_episodes(
    show_title: str,
    today: date,
    end_date: date,
):
    """
    Get the complete episode list for a show from TVMaze and
    return only episodes whose Malta-local airing date falls
    inside the requested calendar window.

    TVMaze is the schedule authority here.

    We deliberately do NOT care whether the episode exists
    in the local database.
    """

    if not show_title:
        return []

    episodes = await _cached_tvmaze_episodes(show_title)

    results = []

    for ep in episodes:

        airstamp = parse_tvmaze_airstamp(
            ep.get("airstamp")
        )

        if not airstamp:
            continue

        air_date = airstamp.date()

        if air_date < today:
            continue

        if air_date > end_date:
            continue

        results.append({
            "tvmaze_id": ep.get("id"),
            "tmdb_id": None,

            "title": ep.get("name"),

            "season": ep.get(
                "season"
            ),

            "episode": ep.get(
                "number"
            ),

            "air_date": air_date,

            "air_time": airstamp.strftime(
                "%H:%M"
            ),

            "air_datetime": airstamp,

            "runtime": ep.get(
                "runtime"
            ),

            "rating": (
                ep.get("rating", {})
                or {}
            ).get("average"),

            "image": (
                ep.get("image", {})
                or {}
            ).get("original"),

            "summary": ep.get(
                "summary"
            ),
        })

    return results


def _tmdb_season(show, season_number: int) -> dict:
    for season in (show.tmdb_data or {}).get("seasons") or []:
        if season.get("season_number") == season_number:
            return season
    return {}


def _season_poster(show, season_number: int) -> str | None:
    """The season's own poster, else the show's."""
    return _tmdb_season(show, season_number).get("poster_path") or show.poster_path


def _episode_badge(
    show, season_number: int, episode_number: int, episode_type: str | None, previous_type: str | None = None,
) -> str | None:
    """ "Series premiere", "Season premiere", "Mid-season premiere",
    "Mid-season finale", "Season finale" or "Series finale" for an episode,
    or None. Finales come from TMDB's episode type, which it sets once a
    finale is announced; the episode after a mid-season finale is the
    mid-season premiere."""
    if episode_number == 1:
        return "Series premiere" if season_number == 1 else "Season premiere"
    if previous_type == "mid_season":
        return "Mid-season premiere"
    if episode_type == "mid_season":
        return "Mid-season finale"
    if episode_type == "finale":
        ended = (show.status or "").lower() in {"ended", "canceled", "cancelled"}
        return "Series finale" if ended else "Season finale"
    return None


async def _episode_types(pairs: set[tuple[int, int]], api_key: str | None) -> dict[tuple[int, int, int], str]:
    """TMDB episode types ("standard", "mid_season", "finale") keyed by
    (show tmdb id, season, episode), for the given (show tmdb id, season) pairs."""
    if not api_key:
        return {}
    gate = asyncio.Semaphore(6)

    async def one(tmdb_id: int, season: int):
        async with gate:
            try:
                data = await tmdb.get_season(tmdb_id, season, api_key=api_key)
            except Exception:
                return []
            return [((tmdb_id, season, e.get("episode_number")), e.get("episode_type")) for e in data.get("episodes") or []]

    types: dict[tuple[int, int, int], str] = {}
    for rows in await asyncio.gather(*(one(t, s) for t, s in pairs)):
        types.update(rows)
    return types


# =========================================================
# Calendar endpoint
# =========================================================

@router.get("/upcoming")
async def calendar_upcoming(
    days: int = Query(
        7,
        ge=1,
        le=90,
    ),
    from_week_start: bool = Query(
        False,
        description="Start on Monday of the current week, so episodes already out this week are included",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return upcoming TV episodes for shows the user watches.

    IMPORTANT:

    The calendar is schedule-driven, not library-driven.

    TVMaze supplies the future episode schedule.

    Local Media rows are used only to enrich episodes that
    already exist locally.
    """

    # -----------------------------------------------------
    # Calendar date range
    # -----------------------------------------------------

    today = datetime.now(
        MALTA_TZ
    ).date()

    start_date = (
        today - timedelta(days=today.weekday())
        if from_week_start
        else today
    )

    end_date = (
        start_date
        + timedelta(days=days - 1)
    )

    # -----------------------------------------------------
    # 1. Find every TV show the user has watched.
    #
    # We don't need the latest episode here for scheduling.
    # The fact that the user has watched the show is enough.
    # -----------------------------------------------------

    watched_result = await db.execute(
        select(
            Media.show_id,
        )
        .join(
            WatchEvent,
            WatchEvent.media_id == Media.id,
        )
        .where(
            WatchEvent.user_id
            == current_user.id,

            WatchEvent.completed.is_(True),

            Media.media_type
            == MediaType.episode,

            Media.show_id.is_not(None),
        )
        .distinct()
    )

    watched_show_ids = [
        row[0]
        for row in watched_result.all()
        if row[0] is not None
    ]

    if not watched_show_ids:
        return {
            "days": days,
            "start_date": start_date.isoformat(),
            "today": today.isoformat(),
            "end_date": end_date.isoformat(),
            "episodes": [],
        }

    # -----------------------------------------------------
    # 2. Load those shows.
    # -----------------------------------------------------

    shows_result = await db.execute(
        select(Show).where(
            Show.id.in_(
                watched_show_ids
            )
        )
    )

    shows = shows_result.scalars().all()

    # Upcoming schedules are only useful for shows that can still release
    # episodes. Avoid querying TVMaze for every historical show in a user's
    # watch history (most of which are ended and produce no calendar items).
    schedulable_statuses = {
        "returning series",
        "in production",
        "planned",
        "pilot",
    }
    schedulable_shows = []
    for show in shows:
        next_episode = (show.tmdb_data or {}).get("next_episode_to_air") or {}
        try:
            next_air_day = date.fromisoformat(str(next_episode.get("air_date"))[:10])
        except (TypeError, ValueError):
            next_air_day = None
        status = (show.status or "").strip().lower()
        if status in schedulable_statuses or (
            next_air_day is not None
            and next_air_day >= today - timedelta(days=1)
        ):
            schedulable_shows.append(show)

    shows = schedulable_shows

    if not shows:
        return {
            "days": days,
            "start_date": start_date.isoformat(),
            "today": today.isoformat(),
            "end_date": end_date.isoformat(),
            "episodes": [],
        }

    # -----------------------------------------------------
    # 3. Load local episode rows.
    #
    # These are ONLY enrichment data.
    #
    # Their existence does NOT control whether an episode
    # appears on the calendar.
    # -----------------------------------------------------

    local_result = await db.execute(
        select(Media).where(
            Media.show_id.in_(
                [show.id for show in shows]
            ),
            Media.media_type
            == MediaType.episode,
        )
    )

    local_media_by_episode = {}

    for media in local_result.scalars().all():

        key = (
            media.show_id,
            media.season_number,
            media.episode_number,
        )

        local_media_by_episode[key] = media

    watched_media_ids = set()
    if local_media_by_episode:
        watched_q = await db.execute(
            select(WatchEvent.media_id).where(
                WatchEvent.user_id == current_user.id,
                WatchEvent.completed.is_(True),
                WatchEvent.media_id.in_([m.id for m in local_media_by_episode.values()]),
            ).distinct()
        )
        watched_media_ids = {row[0] for row in watched_q.all()}

    # -----------------------------------------------------
    # 4. Ask TVMaze for the schedule of every watched show.
    #
    # This is the important bit.
    #
    # We are NOT asking:
    #
    #   "does this episode exist locally?"
    #
    # We are asking:
    #
    #   "what episodes are scheduled to air?"
    # -----------------------------------------------------

    semaphore = asyncio.Semaphore(8)

    async def fetch_show_schedule(show: Show):

        async with semaphore:

            episodes = await get_tvmaze_episodes(
                show.title,
                start_date,
                end_date,
            )

            return show, episodes

    schedule_results = await asyncio.gather(
        *(
            fetch_show_schedule(show)
            for show in shows
        )
    )

    episode_types = await _episode_types(
        {
            (show.tmdb_id, ep["season"])
            for show, scheduled in schedule_results if show.tmdb_id
            for ep in scheduled if ep.get("season") is not None
        },
        await get_user_tmdb_key(db, current_user.id),
    )

    # -----------------------------------------------------
    # 5. Build calendar episodes.
    # -----------------------------------------------------

    episodes = []

    for show, scheduled_episodes in schedule_results:

        for ep in scheduled_episodes:

            season_number = ep.get(
                "season"
            )

            episode_number = ep.get(
                "episode"
            )

            if season_number is None:
                continue

            if episode_number is None:
                continue

            # ---------------------------------------------
            # Look for an existing local Media row.
            #
            # Again: this is enrichment only.
            # ---------------------------------------------

            local_media = (
                local_media_by_episode.get(
                    (
                        show.id,
                        season_number,
                        episode_number,
                    )
                )
            )

            # ---------------------------------------------
            # TVMaze is authoritative for the schedule.
            #
            # Local first_aired_at is NOT allowed to move
            # the episode to another date.
            # ---------------------------------------------

            air_date = ep["air_date"]
            air_time = ep["air_time"]

            # ---------------------------------------------
            # Poster/artwork
            # ---------------------------------------------

            poster_path = None

            if local_media:

                poster_path = (
                    local_media.poster_path
                )

            if not poster_path:

                poster_path = ep.get(
                    "image"
                )

            # ---------------------------------------------
            # Runtime
            # ---------------------------------------------

            runtime = None

            if local_media:

                runtime = (
                    local_media.runtime
                )

            if runtime is None:

                runtime = ep.get(
                    "runtime"
                )

            # ---------------------------------------------
            # Rating
            # ---------------------------------------------

            rating = None

            if local_media:

                rating = (
                    local_media.tmdb_rating
                )

            if rating is None:

                rating = ep.get(
                    "rating"
                )

            badge = _episode_badge(
                show, season_number, episode_number,
                episode_types.get((show.tmdb_id, season_number, episode_number)),
                episode_types.get((show.tmdb_id, season_number, episode_number - 1)),
            )

            # ---------------------------------------------
            # Build calendar item.
            # ---------------------------------------------

            episodes.append({
                "id": (
                    local_media.id
                    if local_media
                    else ep.get(
                        "tvmaze_id"
                    )
                ),

                "show_id": show.id,

                "show_title": show.title,

                "title": ep.get(
                    "title"
                ),

                "season": season_number,

                "episode": episode_number,

                "air_date": (
                    air_date.isoformat()
                ),

                "air_time": air_time,
                "network": get_network_name(show),
                
                "poster_path": poster_path,

                "backdrop_path": (
                    show.backdrop_path
                ),

                "show_poster_path": (
                    show.poster_path
                ),

                "season_poster_path": _season_poster(show, season_number),

                "show_tmdb_id": show.tmdb_id,

                "badge": badge,

                "watched": bool(local_media and local_media.id in watched_media_ids),

                "runtime": runtime,
                
                "rating": rating,

                "tmdb_id": (
                    local_media.tmdb_id
                    if local_media
                    else None
                ),

                "tvmaze_id": (
                    ep.get(
                        "tvmaze_id"
                    )
                ),
            })

    # -----------------------------------------------------
    # 6. Remove duplicates.
    # -----------------------------------------------------

    seen = set()

    unique_episodes = []

    for ep in sorted(
        episodes,
        key=lambda x: (
            x["air_date"],
            x["air_time"] or "99:99",
            x["show_title"] or "",
            x["season"] or 0,
            x["episode"] or 0,
        ),
    ):

        key = (
            ep["show_id"],
            ep["season"],
            ep["episode"],
        )

        if key in seen:
            continue

        seen.add(key)

        unique_episodes.append(
            ep
        )

    # -----------------------------------------------------
    # 7. Return.
    # -----------------------------------------------------

    return {
        "days": days,
        "start_date": start_date.isoformat(),
        "today": today.isoformat(),
        "end_date": end_date.isoformat(),
        "episodes": unique_episodes,
    }
