import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from dependencies import get_current_user

from models.users import User
from models.media import Media
from models.events import WatchEvent
from models.base import MediaType
from models.show import Show

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

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={
                "User-Agent": "Scrob/1.0",
            },
        ) as client:

            response = await client.get(
                "https://api.tvmaze.com/singlesearch/shows",
                params={
                    "q": show_title,
                },
            )

            if response.status_code == 404:
                print(
                    "CALENDAR TVMAZE: no show found:",
                    show_title,
                )
                return []

            response.raise_for_status()

            show_data = response.json()

            tvmaze_title = show_data.get("name")

            # Protect against an obviously bad fuzzy match.
            if (
                normalise_title(tvmaze_title)
                != normalise_title(show_title)
            ):
                print(
                    "CALENDAR TVMAZE: fuzzy match rejected:",
                    show_title,
                    "->",
                    tvmaze_title,
                )
                return []

            tvmaze_id = show_data.get("id")

            if not tvmaze_id:
                return []

            # Get the complete episode list.
            response = await client.get(
                f"https://api.tvmaze.com/shows/{tvmaze_id}/episodes"
            )

            response.raise_for_status()

            episodes = response.json()

    except Exception as e:
        print(
            "CALENDAR TVMAZE ERROR:",
            show_title,
            f"{type(e).__name__}: {e}",
        )
        return []

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

    end_date = (
        today
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
            "start_date": today.isoformat(),
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
            "start_date": today.isoformat(),
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
                today,
                end_date,
            )

            return show, episodes

    schedule_results = await asyncio.gather(
        *(
            fetch_show_schedule(show)
            for show in shows
        )
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
        "start_date": today.isoformat(),
        "end_date": end_date.isoformat(),
        "episodes": unique_episodes,
    }
