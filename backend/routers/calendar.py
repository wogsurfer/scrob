import asyncio
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db, engine, AsyncSessionLocal
from dependencies import get_current_user

from models.tvmaze_cache import TvmazeCache
from models.users import User
from models.media import Media
from models.events import WatchEvent
from models.base import MediaType
from models.show import Show
from models.lists import List, ListItem
from models.watchlist import MovieWatchlist
from models.profile import UserProfileData
from core import tmdb
from core.episode_badges import episode_badge, last_season
from core.movie_releases import COUNTRY_NAMES, release_countries, upcoming_releases
from routers.media import check_tmdb_key, get_user_tmdb_key

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


# TVMaze has no time for most streaming episodes and stamps them midday UTC,
# which puts a Disney+ drop at 1pm in Malta when it really lands at 2am the
# next morning. Each service's usual release, as (zone, hours after the
# listed day's midnight there): Apple's evening-before drop is -3h Eastern.
STREAMING_RELEASES = {
    "disney+": ("America/Los_Angeles", 18),
    "netflix": ("America/Los_Angeles", 0),
    "apple tv": ("America/New_York", -3),
    "apple tv+": ("America/New_York", -3),
    "paramount+": ("America/New_York", 3),
    "paramount+ with showtime": ("America/New_York", 3),
}


def tvmaze_release(ep: dict, web_channel: str | None = None):
    """When an episode lands in Malta: TVMaze's airstamp, or the streaming
    service's usual release time when TVMaze only knows the day."""
    release = STREAMING_RELEASES.get((web_channel or "").strip().lower())
    if release and ep.get("airdate") and not ep.get("airtime"):
        try:
            day = date.fromisoformat(ep["airdate"])
        except ValueError:
            return parse_tvmaze_airstamp(ep.get("airstamp"))
        zone, hours = release
        local = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(zone))
        return (local + timedelta(hours=hours)).astimezone(MALTA_TZ)
    return parse_tvmaze_airstamp(ep.get("airstamp"))


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
_tvmaze_pace_lock = asyncio.Lock()
_tvmaze_next_slot = 0.0
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


async def _tvmaze_pace():
    """Start requests at most every half second (TVMaze's 20 per 10 seconds).
    Past that, TVMaze drops connections rather than answering 429."""
    global _tvmaze_next_slot
    async with _tvmaze_pace_lock:
        wait = _tvmaze_next_slot - time.monotonic()
        _tvmaze_next_slot = max(_tvmaze_next_slot, time.monotonic()) + 0.5
    if wait > 0:
        await asyncio.sleep(wait)


async def _tvmaze_get(client: httpx.AsyncClient, url: str, params: dict | None = None):
    response = None
    for attempt in range(4):
        await _tvmaze_pace()
        try:
            async with _tvmaze_limit:
                response = await client.get(url, params=params)
        except httpx.TransportError:
            if attempt == 3:
                raise
            await asyncio.sleep(2 * (attempt + 1))
            continue
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

            return {
                "tvmaze_id": tvmaze_id,
                "web_channel": (show_data.get("webChannel") or {}).get("name"),
                "episodes": response.json(),
            }

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


async def _cached_tvmaze_show(show_title: str) -> dict:
    await _load_tvmaze_cache()
    key = normalise_title(show_title)
    hit = _tvmaze_memory.get(key)
    if hit:
        # Entries saved before the web channel was kept are refreshed too.
        stale = "web_channel" not in hit[1] and hit[1].get("episodes")
        if stale or datetime.utcnow() - hit[0] > _TVMAZE_FRESH:
            _refresh_tvmaze_once(key, show_title)
        return hit[1]
    # Shielded so a cancelled page request doesn't abort a fetch others may share.
    data = await asyncio.shield(_refresh_tvmaze_once(key, show_title))
    return data or {}


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

    show = await _cached_tvmaze_show(show_title)
    web_channel = show.get("web_channel")

    results = []

    for ep in show.get("episodes") or []:

        airstamp = tvmaze_release(ep, web_channel)

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
# Film releases
# =========================================================

# TMDB release dates per film, kept for half a day: they change rarely and
# the calendar asks for a hundred or so films at a time.
_MOVIE_RELEASES_TTL = 12 * 3600
_movie_releases: dict[int, tuple[float, dict]] = {}


async def _calendar_movie_candidates(db: AsyncSession, user_id: int, today: date) -> dict[int, dict]:
    """Films whose releases belong on the user's calendar, by TMDB id: recent
    films on their watchlist or lists, and recent films they've watched (for
    their disc and streaming dates)."""
    recent_year = today.year - 2
    candidates: dict[int, dict] = {}

    watchlist = await db.execute(
        select(MovieWatchlist.tmdb_id, MovieWatchlist.title).where(
            MovieWatchlist.user_id == user_id,
            or_(MovieWatchlist.year.is_(None), MovieWatchlist.year == 0, MovieWatchlist.year >= recent_year),
        )
    )
    for tmdb_id, title in watchlist.all():
        candidates[tmdb_id] = {"title": title, "poster_path": None}

    recent = or_(Media.release_date.is_(None), Media.release_date >= str(recent_year))
    listed = await db.execute(
        select(Media.tmdb_id, Media.title, Media.poster_path)
        .join(ListItem, ListItem.media_id == Media.id)
        .join(List, List.id == ListItem.list_id)
        .where(List.user_id == user_id, Media.media_type == MediaType.movie, Media.tmdb_id.is_not(None), recent)
    )
    watched = await db.execute(
        select(Media.tmdb_id, Media.title, Media.poster_path)
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == user_id,
            Media.media_type == MediaType.movie,
            Media.tmdb_id.is_not(None),
            Media.release_date >= f"{today.year - 1}-01-01",
        )
    )
    for tmdb_id, title, poster in [*listed.all(), *watched.all()]:
        entry = candidates.setdefault(tmdb_id, {"title": title, "poster_path": None})
        entry["poster_path"] = entry["poster_path"] or poster

    if candidates:
        seen = await db.execute(
            select(Media.tmdb_id)
            .join(WatchEvent, WatchEvent.media_id == Media.id)
            .where(
                WatchEvent.user_id == user_id,
                WatchEvent.completed.is_(True),
                Media.media_type == MediaType.movie,
                Media.tmdb_id.in_(list(candidates)),
            )
            .distinct()
        )
        for (tmdb_id,) in seen.all():
            candidates[tmdb_id]["watched"] = True
    return candidates


async def _calendar_movies(
    candidates: dict[int, dict],
    start: date,
    end: date,
    countries: list[str],
    api_key: str | None,
) -> list[dict]:
    """Cinema, digital, streaming and disc releases of the candidate films
    between start and end."""
    if not candidates or not check_tmdb_key(api_key):
        return []
    gate = asyncio.Semaphore(8)

    async def releases(tmdb_id: int) -> dict:
        hit = _movie_releases.get(tmdb_id)
        if hit and time.monotonic() - hit[0] < _MOVIE_RELEASES_TTL:
            return hit[1]
        async with gate:
            try:
                data = await tmdb.get_movie_releases(tmdb_id, api_key=api_key)
            except Exception:
                return {}
        kept = {
            "title": data.get("title"),
            "poster_path": data.get("poster_path"),
            "results": (data.get("release_dates") or {}).get("results") or [],
        }
        _movie_releases[tmdb_id] = (time.monotonic(), kept)
        return kept

    ids = list(candidates)
    movies = []
    for tmdb_id, data in zip(ids, await asyncio.gather(*(releases(i) for i in ids))):
        if not data:
            continue
        film = candidates[tmdb_id]
        poster = film.get("poster_path") or tmdb.poster_url(data.get("poster_path"))
        for release in upcoming_releases(data["results"], start, end, countries):
            movies.append({
                "tmdb_id": tmdb_id,
                "title": data.get("title") or film["title"],
                "poster_path": poster,
                "date": release["date"].isoformat(),
                "kind": release["kind"],
                "label": release["label"],
                # Only named when it isn't the user's own country.
                "country": (
                    COUNTRY_NAMES.get(release["country"], release["country"])
                    if release["country"] != countries[0] else None
                ),
                "watched": bool(film.get("watched")),
            })
    movies.sort(key=lambda m: (m["date"], m["title"] or ""))
    return movies


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
    Return upcoming TV episodes for shows the user watches, and release
    dates (cinema, digital, streaming, disc) of films they follow.

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

    # Film releases are fetched alongside the TV schedule below.
    tmdb_api_key = await get_user_tmdb_key(db, current_user.id)
    profile = (await db.execute(
        select(UserProfileData).where(UserProfileData.user_id == current_user.id)
    )).scalar_one_or_none()
    movies_task = asyncio.create_task(_calendar_movies(
        await _calendar_movie_candidates(db, current_user.id, today),
        start_date,
        end_date,
        release_countries(profile.country if profile else None),
        tmdb_api_key,
    ))

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
            "movies": await movies_task,
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
            "movies": await movies_task,
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

    # An episode can have more than one local row (they're created from
    # several places), so keep them all: any of them may hold the play.
    local_media_by_episode: dict[tuple, list[Media]] = {}

    for media in local_result.scalars().all():

        key = (
            media.show_id,
            media.season_number,
            media.episode_number,
        )

        local_media_by_episode.setdefault(key, []).append(media)

    watched_media_ids = set()
    if local_media_by_episode:
        watched_q = await db.execute(
            select(WatchEvent.media_id).where(
                WatchEvent.user_id == current_user.id,
                WatchEvent.completed.is_(True),
                WatchEvent.media_id.in_([m.id for rows in local_media_by_episode.values() for m in rows]),
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
        tmdb_api_key,
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

            local_rows = local_media_by_episode.get(
                (
                    show.id,
                    season_number,
                    episode_number,
                ),
                [],
            )
            watched = any(m.id in watched_media_ids for m in local_rows)
            # Prefer the row that holds the play.
            local_media = next(
                (m for m in local_rows if m.id in watched_media_ids),
                local_rows[0] if local_rows else None,
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

            badge = episode_badge(
                season_number, episode_number,
                episode_types.get((show.tmdb_id, season_number, episode_number)),
                episode_types.get((show.tmdb_id, season_number, episode_number - 1)),
                show.status,
                last_season(show.tmdb_data),
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

                "watched": watched,

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
        "movies": await movies_task,
    }
