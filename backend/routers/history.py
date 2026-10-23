import asyncio
import logging
import time
from datetime import datetime, UTC, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, select, desc, func, delete
from sqlalchemy.orm import selectinload
from db import get_db
from models.media import Media
from models.show import Show
from models.events import WatchEvent
from models.playback_session import PlaybackSession
from models.playback_progress import PlaybackProgress
from models.collection import Collection, CollectionFile
from models.base import MediaType, CollectionSource
from models.users import UserSettings
from models.connections import MediaServerConnection
from models.episode_order import EpisodeOrderMapping
from routers.media import enrich_with_state, get_user_tmdb_key, check_tmdb_key
from routers.shows import get_user_tvdb_key
from routers.calendar import get_tvmaze_episodes
from core.translations import get_user_metadata_language, get_media_translations, apply_media_translations
from zoneinfo import ZoneInfo

from dependencies import get_current_user
from models.users import User
import core.plex as plex_client
import core.jellyfin as jellyfin_client
import core.emby as emby_client
import core.trakt as trakt_client
import core.tvdb as tvdb_client
import core.tmdb as tmdb
import core.nuvio as nuvio_client

MALTA_TZ = ZoneInfo("Europe/Malta")

router = APIRouter()
logger = logging.getLogger(__name__)


async def _push_watch_state(
    db: AsyncSession,
    user_id: int,
    media_ids: list[int],
    watched: bool,
    watched_at_by_media: dict[int, datetime | None] | None = None,
) -> None:
    """Fan-out watched/unwatched state to all connections with push_watched enabled."""
    if not media_ids:
        return

    conns_result = await db.execute(
        select(MediaServerConnection).where(
            MediaServerConnection.user_id == user_id,
            MediaServerConnection.push_watched == True,
        )
    )
    connections = conns_result.scalars().all()

    settings_result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    settings = settings_result.scalar_one_or_none()
    push_trakt = settings and settings.trakt_push_watched and settings.trakt_access_token
    push_mdblist = settings and settings.mdblist_push_watched and settings.mdblist_api_key

    resolved_watched_at: dict[int, datetime | None] = {}
    if watched:
        if watched_at_by_media is not None:
            resolved_watched_at = watched_at_by_media
        else:
            from routers.sync import _latest_watched_at
            resolved_watched_at = await _latest_watched_at(db, user_id, media_ids)

    tasks = []

    if connections:
        files_result = await db.execute(
            select(CollectionFile)
            .join(Collection, Collection.id == CollectionFile.collection_id)
            .where(
                Collection.user_id == user_id,
                Collection.media_id.in_(media_ids),
            )
        )
        coll_files = files_result.scalars().all()

        conn_by_type: dict[str, list[MediaServerConnection]] = {}
        for conn in connections:
            conn_by_type.setdefault(conn.type, []).append(conn)

        for coll_file in coll_files:
            if not coll_file.source_id:
                continue
            source_type = coll_file.source.value if hasattr(coll_file.source, "value") else str(coll_file.source)
            for conn in conn_by_type.get(source_type, []):
                if coll_file.source == CollectionSource.plex:
                    if watched:
                        tasks.append(plex_client.mark_watched(conn.url, conn.token, coll_file.source_id))
                    else:
                        tasks.append(plex_client.mark_unwatched(conn.url, conn.token, coll_file.source_id))
                elif coll_file.source == CollectionSource.jellyfin:
                    if watched:
                        tasks.append(jellyfin_client.mark_watched(conn.url, conn.token, conn.server_user_id, coll_file.source_id))
                    else:
                        tasks.append(jellyfin_client.mark_unwatched(conn.url, conn.token, conn.server_user_id, coll_file.source_id))
                elif coll_file.source == CollectionSource.emby:
                    if watched:
                        tasks.append(emby_client.mark_watched(conn.url, conn.token, conn.server_user_id, coll_file.source_id))
                    else:
                        tasks.append(emby_client.mark_unwatched(conn.url, conn.token, conn.server_user_id, coll_file.source_id))

    push_simkl = settings and settings.simkl_push_watched and settings.simkl_access_token
    if push_simkl and settings.simkl_client_id:
        from core import simkl as simkl_client
        simkl_media_res = await db.execute(select(Media).where(Media.id.in_(media_ids)))
        simkl_media_items = simkl_media_res.scalars().all()
        for media in simkl_media_items:
            if not media.tmdb_id:
                continue
            if media.media_type == MediaType.movie:
                if watched:
                    watched_at = resolved_watched_at.get(media.id)
                    if watched_at is not None:
                        tasks.append(simkl_client.add_movie_to_history(settings.simkl_client_id, settings.simkl_access_token, media.tmdb_id, watched_at))
                else:
                    tasks.append(simkl_client.remove_movie_from_history(settings.simkl_client_id, settings.simkl_access_token, media.tmdb_id))
            elif media.media_type == MediaType.episode and media.show_id and media.season_number is not None and media.episode_number is not None:
                show_res = await db.execute(select(Show).where(Show.id == media.show_id))
                show = show_res.scalar_one_or_none()
                if show and show.tmdb_id:
                    if watched:
                        watched_at = resolved_watched_at.get(media.id)
                        if watched_at is not None:
                            tasks.append(simkl_client.add_episode_to_history(settings.simkl_client_id, settings.simkl_access_token, show.tmdb_id, media.season_number, media.episode_number, watched_at))
                    else:
                        tasks.append(simkl_client.remove_episode_from_history(settings.simkl_client_id, settings.simkl_access_token, show.tmdb_id, media.season_number, media.episode_number))

    if push_trakt and settings.trakt_client_id:
        media_res = await db.execute(
            select(Media).where(Media.id.in_(media_ids))
        )
        media_items = media_res.scalars().all()
        for media in media_items:
            if not media.tmdb_id:
                continue
            if media.media_type == MediaType.movie:
                if watched:
                    tasks.append(trakt_client.add_movie_to_history(settings.trakt_client_id, settings.trakt_access_token, media.tmdb_id, resolved_watched_at.get(media.id)))
                else:
                    tasks.append(trakt_client.remove_movie_from_history(settings.trakt_client_id, settings.trakt_access_token, media.tmdb_id))
            elif media.media_type == MediaType.episode and media.show_id and media.season_number is not None and media.episode_number is not None:
                show_res = await db.execute(select(Show).where(Show.id == media.show_id))
                show = show_res.scalar_one_or_none()
                if show and show.tmdb_id:
                    if watched:
                        tasks.append(trakt_client.add_episode_to_history(settings.trakt_client_id, settings.trakt_access_token, show.tmdb_id, media.season_number, media.episode_number, resolved_watched_at.get(media.id)))
                    else:
                        tasks.append(trakt_client.remove_episode_from_history(settings.trakt_client_id, settings.trakt_access_token, show.tmdb_id, media.season_number, media.episode_number))

    if push_mdblist:
        from core import mdblist as mdblist_client
        from routers.mdblist import _empty_payload, _merge_show_entries, _payload_item

        mdblist_payload = _empty_payload()
        media_result = await db.execute(select(Media).where(Media.id.in_(media_ids)))
        media_list = media_result.scalars().all()
        mdblist_show_ids = {m.show_id for m in media_list if m.media_type == MediaType.episode and m.show_id}
        mdblist_shows_by_id: dict[int, Show] = {}
        if mdblist_show_ids:
            shows_result = await db.execute(select(Show).where(Show.id.in_(mdblist_show_ids)))
            mdblist_shows_by_id = {s.id: s for s in shows_result.scalars().all()}
        for media in media_list:
            show = mdblist_shows_by_id.get(media.show_id)
            item = (
                _payload_item(media, show=show, watched_at=resolved_watched_at.get(media.id, datetime.utcnow()))
                if watched
                else _payload_item(media, show=show)
            )
            if item:
                mdblist_payload[item[0]].append(item[1])
        mdblist_payload["shows"] = _merge_show_entries(mdblist_payload["shows"])
        operation = mdblist_client.push_watched if watched else mdblist_client.remove_watched
        tasks.append(operation(settings.mdblist_api_key, mdblist_payload))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    nuvio_connections = [conn for conn in connections if conn.type == "nuvio"]
    if nuvio_connections:
        media_result = await db.execute(select(Media).where(Media.id.in_(media_ids)))
        media_items = media_result.scalars().all()
        show_ids = {media.show_id for media in media_items if media.show_id is not None}
        shows_by_id: dict[int, Show] = {}
        if show_ids:
            show_result = await db.execute(select(Show).where(Show.id.in_(show_ids)))
            shows_by_id = {show.id: show for show in show_result.scalars().all()}
        from routers.sync import _ensure_nuvio_imdb_ids, _nuvio_watched_item

        api_key = await get_user_tmdb_key(db, user_id)
        await _ensure_nuvio_imdb_ids(media_items, shows_by_id, api_key)

        nuvio_items: list[dict] = []
        nuvio_keys: list[dict] = []
        for media in media_items:
            payload = _nuvio_watched_item(
                media,
                resolved_watched_at.get(media.id) if watched else datetime.utcnow(),
                shows_by_id.get(media.show_id),
            )
            if not payload:
                continue
            key = {
                field: payload[field]
                for field in ("content_id", "season", "episode")
                if field in payload
            }
            if watched:
                nuvio_items.append(payload)
            else:
                nuvio_keys.append(key)

        for conn in nuvio_connections:
            try:
                profile_id = nuvio_client.parse_profile_id(conn.server_user_id)
                if watched and nuvio_items:
                    session = await nuvio_client.push_watched_items(
                        conn.url, conn.token, profile_id, nuvio_items
                    )
                elif not watched and nuvio_keys:
                    session = await nuvio_client.delete_watched_items(
                        conn.url, conn.token, profile_id, nuvio_keys
                    )
                else:
                    continue
                conn.token = session.refresh_token
            except Exception:
                logger.exception("Failed to push watch state to Nuvio connection %s", conn.id)
                continue
        await db.commit()


def format_event(event: WatchEvent | PlaybackProgress, media: Media) -> dict:
    # PlaybackProgress has no watched_at; its updated_at remains the display timestamp.
    # A WatchEvent's watched_at may be None (unknown watch date) — preserve that as-is.
    watched_at = event.watched_at if isinstance(event, WatchEvent) else event.updated_at

    data = {
        "id": event.id,
        "media": {
            "id": media.id,
            "tmdb_id": media.tmdb_id,
            "type": media.media_type,
            "title": media.title,
            "overview": media.overview,
            "poster_path": media.poster_path,
            "backdrop_path": media.backdrop_path,
            "release_date": media.release_date,
            "tmdb_rating": media.tmdb_rating,
            "user_rating": (media.tmdb_data or {}).get("user_rating"), # Placeholder, will be enriched
            "season_number": media.season_number,
            "episode_number": media.episode_number,
            "runtime": media.runtime,
            "tagline": media.tagline,
            "genres": (media.tmdb_data or {}).get("genres", []),
            # An edition TMDB doesn't list on its own (e.g. an extended cut)
            # links to its theatrical film's page instead.
            "edition_of": (media.tmdb_data or {}).get("edition_of"),
            "edition": (media.tmdb_data or {}).get("edition"),
        },
        "user_id": event.user_id,
        "watched_at": watched_at.isoformat() if watched_at else None,
        "progress_seconds": event.progress_seconds,
        "progress_percent": event.progress_percent,
        "completed": getattr(event, "completed", False),
        "play_count": getattr(event, "play_count", 1),
        "watch_source": getattr(event, "watch_source", None),
    }

    if media.media_type == MediaType.episode and media.show:
        data["media"]["show_title"] = media.show.title
        data["media"]["show_poster_path"] = media.show.poster_path
        data["media"]["show_tmdb_id"] = media.show.tmdb_id
        data["media"]["show_tvdb_id"] = media.show.tvdb_id

    return data

async def _get_show_history(
    page: int,
    page_size: int,
    db: AsyncSession,
    current_user: User,
) -> dict:
    """One entry per show the user has watched, most recently watched first."""
    offset = (page - 1) * page_size

    per_show = (
        select(
            Media.show_id.label("show_id"),
            func.max(WatchEvent.watched_at).label("last_watched_at"),
            func.count(WatchEvent.id).label("plays"),
            func.count(func.distinct(WatchEvent.media_id)).label("episodes"),
        )
        .select_from(WatchEvent)
        .join(Media, Media.id == WatchEvent.media_id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.completed == True,
            Media.media_type == MediaType.episode,
            Media.show_id.isnot(None),
        )
        .group_by(Media.show_id)
        .subquery()
    )

    total_count = (
        await db.execute(select(func.count()).select_from(per_show))
    ).scalar_one()
    total_pages = max(1, (total_count + page_size - 1) // page_size)

    rows = await db.execute(
        select(Show, per_show.c.last_watched_at, per_show.c.plays, per_show.c.episodes)
        .join(per_show, per_show.c.show_id == Show.id)
        .order_by(per_show.c.last_watched_at.desc().nulls_last(), Show.id.desc())
        .offset(offset)
        .limit(page_size)
    )

    results = [
        {
            "id": show.id,
            "tmdb_id": show.tmdb_id,
            "tvdb_id": show.tvdb_id,
            "title": show.title,
            "poster_path": show.poster_path,
            "status": show.status,
            "last_watched_at": last_watched.isoformat() if last_watched else None,
            "episodes_watched": episodes,
            "plays": plays,
        }
        for show, last_watched, plays, episodes in rows.all()
    ]

    return {
        "page": page,
        "page_size": page_size,
        "total_results": total_count,
        "total_pages": total_pages,
        "results": results,
    }

@router.get("")
async def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if type == "show":
        return await _get_show_history(page, page_size, db, current_user)
    offset = (page - 1) * page_size

    base_query = (
        select(func.count())
        .select_from(WatchEvent)
        .join(Media, Media.id == WatchEvent.media_id)
        .where(WatchEvent.user_id == current_user.id)
        .where(WatchEvent.completed == True)
    )
    if type and type in ("movie", "episode"):
        base_query = base_query.where(Media.media_type == type)

    total_result = await db.execute(base_query)
    total_count = total_result.scalar_one()
    total_pages = max(1, (total_count + page_size - 1) // page_size)

    query = (
        select(WatchEvent, Media)
        .join(Media, Media.id == WatchEvent.media_id)
        .options(selectinload(WatchEvent.media).selectinload(Media.show))
        .where(WatchEvent.user_id == current_user.id)
        .where(WatchEvent.completed == True)
        .order_by(WatchEvent.watched_at.desc().nulls_last(), WatchEvent.id.desc())
    )
    if type and type in ("movie", "episode"):
        query = query.where(Media.media_type == type)

    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    rows = result.all()
    
    events = [format_event(e, m) for e, m in rows]
    if events:
        await enrich_with_state(db, current_user.id, [e["media"] for e in events])
        lang = await get_user_metadata_language(db, current_user.id)
        if lang:
            media_ids = [e["media"]["id"] for e in events if e["media"].get("id")]
            translations = await get_media_translations(db, media_ids, lang)
            for event in events:
                t = translations.get(event["media"].get("id"))
                if t:
                    m = event["media"]
                    if t.get("title"): m["title"] = t["title"]
                    if t.get("overview"): m["overview"] = t["overview"]
                    if t.get("poster_path"): m["poster_path"] = t["poster_path"]

    return {
        "page": page,
        "page_size": page_size,
        "total_results": total_count,
        "total_pages": total_pages,
        "results": events,
    }


@router.get("/continue-watching")
async def get_continue_watching(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Items currently in progress."""
    result = await db.execute(
        select(PlaybackProgress, Media)
        .join(Media, Media.id == PlaybackProgress.media_id)
        .options(selectinload(PlaybackProgress.media).selectinload(Media.show))
        .where(PlaybackProgress.user_id == current_user.id)
        .order_by(desc(PlaybackProgress.updated_at))
        .limit(20)
    )
    rows = result.all()
    items = [format_event(e, m) for e, m in rows]
    if items:
        await enrich_with_state(db, current_user.id, [i["media"] for i in items])
        lang = await get_user_metadata_language(db, current_user.id)
        if lang:
            media_ids = [i["media"]["id"] for i in items if i["media"].get("id")]
            translations = await get_media_translations(db, media_ids, lang)
            for item in items:
                t = translations.get(item["media"].get("id"))
                if t:
                    m = item["media"]
                    if t.get("title"): m["title"] = t["title"]
                    if t.get("overview"): m["overview"] = t["overview"]
                    if t.get("poster_path"): m["poster_path"] = t["poster_path"]
    return {"continue_watching": items}


@router.delete("/continue-watching")
async def dismiss_continue_watching(
    media_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a single item from the continue-watching list."""
    await db.execute(
        delete(PlaybackProgress).where(
            PlaybackProgress.user_id == current_user.id,
            PlaybackProgress.media_id == media_id,
        )
    )
    await db.commit()
    return {"status": "ok"}


def _format_media_item(media: Media) -> dict:
    data = {
        "id": media.id,
        "tmdb_id": media.tmdb_id,
        "type": media.media_type,
        "title": media.title,
        "overview": media.overview,
        "poster_path": media.poster_path,
        "backdrop_path": media.backdrop_path,
        "release_date": media.release_date,
        "tmdb_rating": media.tmdb_rating,
        "season_number": media.season_number,
        "episode_number": media.episode_number,
        "runtime": media.runtime,
        "genres": (media.tmdb_data or {}).get("genres", []),
        "library": None,
        "in_library": False,
        "show_id": media.show_id,
    }
    if media.media_type == MediaType.episode and media.show:
        data["show_title"] = media.show.title
        data["show_poster_path"] = media.show.poster_path
        data["show_backdrop_path"] = media.show.backdrop_path
        data["show_tmdb_id"] = media.show.tmdb_id
        data["show_tvdb_id"] = media.show.tvdb_id
        data["show_imdb_rating"] = (media.show.tmdb_data or {}).get("imdb_rating")
    return data


def _compute_next_episode(seasons: list[dict], season: int, episode: int) -> tuple[int, int] | None:
    """Given a show's TMDB season metadata and the last-watched (season, episode),
    returns the next (season, episode), or None if the show has no more aired/
    known episodes after it. Specials (season 0) are never returned."""
    real_seasons = sorted(
        (s for s in seasons if s.get("season_number", 0) > 0),
        key=lambda s: s["season_number"],
    )
    current_season = next((s for s in real_seasons if s["season_number"] == season), None)
    if current_season and episode < current_season.get("episode_count", 0):
        return season, episode + 1
    upcoming = next(
        (s for s in real_seasons if s["season_number"] > season and s.get("episode_count", 0) > 0),
        None,
    )
    if upcoming:
        return upcoming["season_number"], 1
    return None

async def _show_watch_pct(
    db: AsyncSession,
    user_id: int,
    show_ids: set[int],
    today: date,
) -> dict[int, dict[str, int]]:
    """Percent of each show's aired episodes the user has watched.

    The total comes from the show's full TMDB season list (stored in
    Show.tmdb_data["seasons"]), not just from the episode rows that happen to
    exist in the media table. Episode rows are only created for items that were
    synced or watched, so counting them alone makes the bar look nearly full.
    """
    if not show_ids:
        return {}

    show_rows = await db.execute(
        select(Show.id, Show.tmdb_id, Show.tmdb_data).where(Show.id.in_(show_ids))
    )
    tmdb_season_counts: dict[int, dict[int, int]] = {}
    aired_only: set[tuple[int, int]] = set()  # (show_id, season) counted by air date
    tmdb_ids: dict[int, int] = {}
    for sid, tmdb_id, data in show_rows.all():
        counts: dict[int, int] = {}
        for s in (data or {}).get("seasons", []) or []:
            num = s.get("season_number")
            cnt = s.get("episode_count") or 0
            if isinstance(num, int) and num > 0 and cnt > 0:
                counts[num] = cnt
        tmdb_season_counts[sid] = counts
        if tmdb_id:
            tmdb_ids[sid] = tmdb_id

    # The season list stored on a show can be incomplete (for example when the
    # show was created from a media-server library that only holds some
    # seasons). Ask TMDB for the real season list, and for the newest season of
    # a show that is still airing, which episodes have actually aired.
    try:
        tmdb_key = await get_user_tmdb_key(db, user_id)
    except Exception:
        tmdb_key = None

    if tmdb_key and check_tmdb_key(tmdb_key) and tmdb_ids:
        today_iso = today.isoformat()
        recent_cutoff = (today - timedelta(days=90)).isoformat()
        gate = asyncio.Semaphore(6)

        async def refresh(sid: int, tmdb_id: int) -> None:
            async with gate:
                try:
                    info = await tmdb.get_show_light(tmdb_id, api_key=tmdb_key)
                except Exception:
                    return  # keep the stored counts
                counts = {
                    s["season_number"]: s["episode_count"]
                    for s in info.get("seasons", []) or []
                    if isinstance(s.get("season_number"), int)
                    and s["season_number"] > 0
                    and (s.get("episode_count") or 0) > 0
                }
                if not counts:
                    return
                tmdb_season_counts[sid] = counts

                finished = (info.get("status") or "").lower() in (
                    "ended", "canceled", "cancelled",
                )
                last_air = str(info.get("last_air_date") or "")[:10]
                if finished and not (last_air and last_air >= recent_cutoff):
                    return
                latest = max(counts)
                try:
                    season_data = await tmdb.get_season(
                        tmdb_id, latest, api_key=tmdb_key
                    )
                except Exception:
                    return  # keep the season's full episode_count
                eps = season_data.get("episodes") or []
                if eps:
                    aired_only.add((sid, latest))
                    counts[latest] = sum(
                        1
                        for e in eps
                        if e.get("air_date") and str(e["air_date"])[:10] <= today_iso
                    )

        await asyncio.gather(*(refresh(sid, tid) for sid, tid in tmdb_ids.items()))

    watched_sq = (
        select(WatchEvent.media_id)
        .where(
            WatchEvent.user_id == user_id,
            WatchEvent.completed == True,
        )
        .distinct()
        .subquery()
    )

    rows = await db.execute(
        select(
            Media.show_id,
            Media.season_number,
            Media.episode_number,
            Media.first_aired_at,
            Media.release_date,
            watched_sq.c.media_id,
        )
        .outerjoin(watched_sq, watched_sq.c.media_id == Media.id)
        .where(
            Media.media_type == MediaType.episode,
            Media.show_id.in_(show_ids),
            Media.season_number.isnot(None),
            Media.season_number != 0,
            Media.episode_number.isnot(None),
        )
    )

    now_utc = datetime.now(UTC)
    cutoff = today - timedelta(days=1)

    # One entry per (show, season, episode) so duplicate rows aren't double counted.
    positions: dict[tuple[int, int, int], list[bool]] = {}

    for show_id, season, episode, first_aired_at, release_date, watched_media_id in rows.all():
        seen = watched_media_id is not None

        aired = False
        if first_aired_at:
            stamp = (
                first_aired_at
                if first_aired_at.tzinfo
                else first_aired_at.replace(tzinfo=UTC)
            )
            aired = stamp <= now_utc
        elif release_date:
            try:
                aired = date.fromisoformat(str(release_date)[:10]) <= cutoff
            except ValueError:
                aired = False

        entry = positions.setdefault((show_id, season, episode), [False, False])
        entry[0] = entry[0] or aired
        entry[1] = entry[1] or seen

    # Per show / per season: episodes known to the DB that have aired or been
    # watched, how many are watched, and how many are known but not yet aired.
    known: dict[int, dict[int, int]] = {}
    seen_counts: dict[int, int] = {}
    unaired: dict[int, dict[int, int]] = {}

    for (show_id, season, _episode), (aired, seen) in positions.items():
        if seen:
            seen_counts[show_id] = seen_counts.get(show_id, 0) + 1
        if aired or seen:
            per = known.setdefault(show_id, {})
            per[season] = per.get(season, 0) + 1
        else:
            per = unaired.setdefault(show_id, {})
            per[season] = per.get(season, 0) + 1

    result: dict[int, dict[str, int]] = {}

    for show_id in show_ids:
        db_known = known.get(show_id, {})
        db_unaired = unaired.get(show_id, {})
        tmdb_counts = tmdb_season_counts.get(show_id, {})

        total = 0
        for season in set(db_known) | set(tmdb_counts):
            have = db_known.get(season, 0)
            full = tmdb_counts.get(season, 0)
            if season in db_known:
                # TMDB counts unaired episodes too; drop the ones the DB knows
                # haven't aired yet.
                if (show_id, season) in aired_only:
                    total += max(have, full)
                else:
                    total += max(have, full - db_unaired.get(season, 0))
            else:
                # A season with no rows in the DB at all (not synced or watched
                # yet). It still counts towards the whole show; the newest
                # season was already trimmed to aired episodes above.
                total += full

        watched = seen_counts.get(show_id, 0)
        total = max(total, watched)
        if total:
            result[show_id] = {
                "watched": watched,
                "total": total,
                "pct": (
                    max(1, min(99, watched * 100 // total))
                    if 0 < watched < total
                    else watched * 100 // total
                ),
            }

    return result

# TVDB episode air dates per (show id, season), shared across Next Up requests so
# every page load doesn't repeat the same TVDB/TMDB lookups.
_TVDB_DATES_TTL = 6 * 3600
_TVDB_DATES: dict[tuple[int, int], dict[int, str | None]] = {}
_TVDB_DATES_AT: dict[tuple[int, int], float] = {}

@router.get("/next-up")
async def get_next_up(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int | None = None,
    include_hidden: bool = Query(False),
):
    """Next unwatched episode for each show the user is actively watching."""
    # Step 1: Find the last watched / significantly-viewed episode per show,
    # and the most recent watch timestamp per show for final sorting.
    result = await db.execute(
        select(Media.show_id, Media.season_number, Media.episode_number, WatchEvent.watched_at)
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == current_user.id,
            Media.media_type == MediaType.episode,
            Media.show_id.isnot(None),
            or_(WatchEvent.completed == True, WatchEvent.progress_percent >= 0.5),
        )
        .order_by(Media.show_id, desc(Media.season_number), desc(Media.episode_number))
    )
    rows = result.all()

    # Keep only the furthest episode per show, plus the most recent watch time.
    last_per_show: dict[int, tuple[int, int]] = {}
    last_watched_at: dict[int, object] = {}
    for show_id, season, episode, watched_at in rows:
        if show_id not in last_per_show:
            last_per_show[show_id] = (season, episode)
        if show_id not in last_watched_at or (watched_at and watched_at > last_watched_at[show_id]):
            last_watched_at[show_id] = watched_at

    if not last_per_show:
        return {"next_up": []}

    # Search for episodes after the furthest watched position for each show.
    show_filters = [
        and_(
            Media.show_id == show_id,
            or_(
                Media.season_number > season,
                and_(Media.season_number == season, Media.episode_number > episode),
            ),
        )
        for show_id, (season, episode) in last_per_show.items()
    ]

    now_malta = datetime.now(MALTA_TZ)
    today = now_malta.date()

    candidates_result = await db.execute(
        select(Media)
        .options(selectinload(Media.show))
        .where(
            Media.media_type == MediaType.episode,
            or_(*show_filters),
        )
        .order_by(
            Media.show_id,
            Media.season_number,
            Media.episode_number,
        )
    )

    candidates = candidates_result.scalars().all()

    # Take only the immediately next eligible episode per show.
    # Never show episodes with missing, invalid, placeholder, or future air dates.
    next_per_show: dict[int, Media] = {}

    # TVDB episode air dates, cached per show/season for a few hours.
    now_mono = time.monotonic()
    for expired in [k for k, at in _TVDB_DATES_AT.items() if now_mono - at > _TVDB_DATES_TTL]:
        _TVDB_DATES.pop(expired, None)
        _TVDB_DATES_AT.pop(expired, None)
    tvdb_dates = _TVDB_DATES

    tvmaze_dates: dict[int, dict[tuple[int, int], datetime | None]] = {}

    async def get_tvmaze_air_datetime(
        show: Show,
        season: int,
        episode: int,
    ) -> datetime | None:
        if show.id not in tvmaze_dates:
            try:
                scheduled = await get_tvmaze_episodes(
                    show.title,
                    today,
                    date.max,
                )

                tvmaze_dates[show.id] = {
                    (
                        ep.get("season"),
                        ep.get("episode"),
                    ): (
                        ep.get("air_datetime")
                        if ep.get("air_datetime")
                        else None
                    )
                    for ep in scheduled
                    if ep.get("season") is not None
                    and ep.get("episode") is not None
                }
            except Exception:
                tvmaze_dates[show.id] = {}

        return tvmaze_dates.get(show.id, {}).get(
            (season, episode)
        )

    async def episode_has_aired(media: Media, show: Show) -> bool:
        # Trakt's first_aired timestamp is an exact instant. Convert that
        # instant to Malta time before making the decision; don't make one
        # schedule request per episode when the timestamp already answers it.
        if media.first_aired_at:
            aired_at = media.first_aired_at
            if aired_at.tzinfo is None:
                aired_at = aired_at.replace(tzinfo=UTC)
            return aired_at.astimezone(MALTA_TZ) <= now_malta

        try:
            release_day = (
                datetime.strptime(str(media.release_date)[:10], "%Y-%m-%d").date()
                if media.release_date
                else None
            )
        except (ValueError, TypeError):
            release_day = None

        # Old date-only records cannot still be waiting for their U.S. evening
        # broadcast. The one-day boundary is handled by the exact schedule.
        if release_day and release_day < today - timedelta(days=1):
            return True
        if release_day and release_day > today + timedelta(days=1):
            return False
        tvmaze_air_datetime = await get_tvmaze_air_datetime(
            show,
            media.season_number,
            media.episode_number,
        )
        if tvmaze_air_datetime:
            if tvmaze_air_datetime.tzinfo is None:
                tvmaze_air_datetime = tvmaze_air_datetime.replace(tzinfo=MALTA_TZ)
            return tvmaze_air_datetime.astimezone(MALTA_TZ) <= now_malta

        tvdb_air_date = await get_tvdb_air_date(
            show,
            media.season_number,
            media.episode_number,
        )
        effective_release_date = tvdb_air_date or media.release_date
        if not effective_release_date:
            return False

        try:
            release_date = datetime.strptime(
                effective_release_date,
                "%Y-%m-%d",
            ).date()
        except (ValueError, TypeError):
            return False

        # U.S. date-only metadata may be one day earlier than its Malta-local
        # airtime. Require the exact schedule for today/yesterday; after that,
        # the timestamp cannot affect whether the episode has aired.
        return release_date < today - timedelta(days=1) and release_date.year < 9999

    async def get_tvdb_air_date(show: Show, season: int, episode: int) -> str | None:
        key = (show.id, season)
        if key not in tvdb_dates:
            tvdb_dates[key] = {}
            _TVDB_DATES_AT[key] = time.monotonic()

            tvdb_series_id = show.tvdb_id

            if not tvdb_series_id and show.tmdb_id:
                try:
                    tmdb_api_key = await get_user_tmdb_key(db, current_user.id)
                    if check_tmdb_key(tmdb_api_key):
                        show_tmdb = await tmdb.get_show(
                            show.tmdb_id,
                            api_key=tmdb_api_key,
                        )
                        tvdb_series_id = (
                            show_tmdb.get("external_ids", {}).get("tvdb_id")
                        )
                except Exception:
                    tvdb_series_id = None

            tvdb_api_key = await get_user_tvdb_key(db, current_user.id)

            if tvdb_api_key and tvdb_series_id:
                try:
                    raw = await tvdb_client.get_series_episodes(
                        int(tvdb_series_id),
                        season,
                        tvdb_api_key,
                    )
                    episodes = [
                        tvdb_client.format_episode(e)
                        for e in raw
                    ]
                    tvdb_dates[key] = {
                        e.get("episode_number"): e.get("air_date")
                        for e in episodes
                        if e.get("episode_number") is not None
                    }
                except Exception:
                    tvdb_dates[key] = {}
                    # Retry a failed lookup after ~10 minutes rather than the full TTL.
                    _TVDB_DATES_AT[key] = time.monotonic() - _TVDB_DATES_TTL + 600

        return tvdb_dates.get(key, {}).get(episode)

    for media in candidates:
        if media.show_id in next_per_show:
            continue
        if not media.show or not await episode_has_aired(media, media.show):
            continue

        next_per_show[media.show_id] = media

    # Fallback for shows with no local row for the next episode yet.
    missing_show_ids = set(last_per_show) - set(next_per_show)

    if missing_show_ids:
        api_key = await get_user_tmdb_key(db, current_user.id)

        if check_tmdb_key(api_key):
            shows_result = await db.execute(
                select(Show).where(
                    Show.id.in_(missing_show_ids)
                )
            )

            shows_by_id = {
                s.id: s
                for s in shows_result.scalars().all()
            }

            for show_id in missing_show_ids:
                show = shows_by_id.get(show_id)

                if not show or not show.tmdb_id:
                    continue

                season, episode = last_per_show[show_id]

                # A just-aired episode can be missing from the local catalog
                # while TMDB points at the next future episode. Check only the
                # recent Malta-local window for active shows; fetching an
                # entire series history for every missing show made this route
                # slow and produced no useful schedule data for ended shows.
                show_status = (show.status or "").strip().lower()
                ended_statuses = {"ended", "canceled", "cancelled"}
                try:
                    schedule = (
                        await get_tvmaze_episodes(
                            show.title,
                            today - timedelta(days=2),
                            today,
                        )
                        if show_status not in ended_statuses
                        else []
                    )
                except Exception:
                    schedule = []

                aired_schedule = []
                for scheduled_ep in schedule:
                    scheduled_season = scheduled_ep.get("season")
                    scheduled_episode = scheduled_ep.get("episode")
                    scheduled_at = scheduled_ep.get("air_datetime")
                    if scheduled_season is None or scheduled_episode is None or not scheduled_at:
                        continue
                    if (scheduled_season, scheduled_episode) <= (season, episode):
                        continue
                    if scheduled_at.tzinfo is None:
                        scheduled_at = scheduled_at.replace(tzinfo=MALTA_TZ)
                    if scheduled_at.astimezone(MALTA_TZ) <= now_malta:
                        aired_schedule.append((scheduled_season, scheduled_episode, scheduled_ep, scheduled_at))

                aired_schedule.sort(key=lambda item: (item[0], item[1]))
                if aired_schedule:
                    scheduled_season, scheduled_episode, scheduled_ep, scheduled_at = aired_schedule[0]
                    media = Media(
                        media_type=MediaType.episode,
                        show_id=show.id,
                        season_number=scheduled_season,
                        episode_number=scheduled_episode,
                        title=scheduled_ep.get("title"),
                        release_date=str(scheduled_ep.get("air_date") or "")[:10] or None,
                        first_aired_at=scheduled_at,
                    )
                    await enrich_media(
                        media,
                        api_key=api_key,
                        series_tmdb_id=show.tmdb_id,
                    )
                    if media.tmdb_id:
                        media.show = show
                        db.add(media)
                        await db.flush()
                        next_per_show[show_id] = media
                        continue

                next_ep = _compute_next_episode(
                    (show.tmdb_data or {}).get("seasons", []),
                    season,
                    episode,
                )

                if next_ep is None:
                    continue

                next_season_num, next_episode_num = next_ep

                media = Media(
                    media_type=MediaType.episode,
                    show_id=show.id,
                    season_number=next_season_num,
                    episode_number=next_episode_num,
                )

                await enrich_media(
                    media,
                    api_key=api_key,
                    series_tmdb_id=show.tmdb_id,
                )

                if not media.tmdb_id:
                    continue
                media.show = show
                if not await episode_has_aired(media, show):
                    continue
                db.add(media)

                await db.flush()

                next_per_show[show_id] = media

            await db.commit()

    if not next_per_show:
        return {"next_up": []}

    # Remove episodes the user has already completed
    completed_result = await db.execute(
        select(WatchEvent.media_id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.completed == True,
            WatchEvent.media_id.in_(
                [m.id for m in next_per_show.values()]
            ),
        )
    )

    completed_ids = {
        row[0]
        for row in completed_result.all()
    }

    settings_result = await db.execute(
        select(UserSettings).where(
            UserSettings.user_id == current_user.id
        )
    )

    settings = settings_result.scalar_one_or_none()

    hidden_set = (
        set(settings.next_up_hidden_shows or [])
        if settings
        else set()
    )

    next_up = []

    for m in next_per_show.values():

        if m.id in completed_ids:
            continue

        if not include_hidden and m.show_id in hidden_set:
            continue

        # These episodes have already passed episode_has_aired above. Keep
        # TVMaze's exact timestamp for Malta-local airing checks; the former
        # date-only strptime validation rejected datetime values and silently
        # removed every TVMaze-matched episode from Next Up.
        tvmaze_air_date = await get_tvmaze_air_datetime(
            m.show,
            m.season_number,
            m.episode_number,
        )

        # Guard again at output time in case the source returned an exact
        # timestamp in a timezone other than Malta. Date-only source checks
        # were already handled conservatively by episode_has_aired.
        if tvmaze_air_date:
            if tvmaze_air_date.tzinfo is None:
                tvmaze_air_date = tvmaze_air_date.replace(tzinfo=MALTA_TZ)
            if tvmaze_air_date.astimezone(MALTA_TZ) > now_malta:
                continue

        next_up.append(m)

    next_up.sort(
        key=lambda m: (
            last_watched_at.get(m.show_id)
            or datetime.min
        ),
        reverse=True,
    )

    if limit is not None:
        next_up = next_up[:limit]

    items = [
        _format_media_item(m)
        for m in next_up
    ]

    # Poster of the season the next episode belongs to (falls back to the show
    # poster on the card when TMDB has none for that season).
    for m, item in zip(next_up, items):
        season_poster = next(
            (
                s.get("poster_path")
                for s in ((m.show.tmdb_data or {}).get("seasons") or [])
                if isinstance(s, dict) and s.get("season_number") == m.season_number
            ),
            None,
        ) if m.show else None
        # Stored season posters are either TMDB paths or already full URLs.
        item["season_poster_path"] = (
            season_poster
            if isinstance(season_poster, str) and season_poster.startswith("http")
            else tmdb.poster_url(season_poster)
        )

    # A season newer than the stored show data has no stored poster; ask TMDB for those few.
    missing = [
        (m, item) for m, item in zip(next_up, items)
        if not item["season_poster_path"] and m.show and m.show.tmdb_id
    ]
    if missing:
        poster_key = await get_user_tmdb_key(db, current_user.id)
        if check_tmdb_key(poster_key):
            async def fetch_season_poster(m, item):
                try:
                    data = await tmdb.get_show_light(m.show.tmdb_id, api_key=poster_key)
                except Exception:
                    return
                for s in data.get("seasons") or []:
                    if s.get("season_number") == m.season_number and s.get("poster_path"):
                        item["season_poster_path"] = tmdb.poster_url(s["poster_path"])
                        return

            await asyncio.gather(*(fetch_season_poster(m, item) for m, item in missing))

    progress_by_show = await _show_watch_pct(
        db,
        current_user.id,
        {i["show_id"] for i in items if i.get("show_id")},
        today,
    )

    for item in items:
        item["next_up_hidden"] = (
            item.get("show_id") in hidden_set
        )
        stats = progress_by_show.get(item.get("show_id"))
        item["show_watch_pct"] = stats["pct"] if stats else None
        item["show_episodes_watched"] = stats["watched"] if stats else None
        item["show_episodes_total"] = stats["total"] if stats else None

    if items:
        await enrich_with_state(
            db,
            current_user.id,
            items,
        )

        lang = await get_user_metadata_language(
            db,
            current_user.id,
        )

        if lang:
            media_ids = [
                i["id"]
                for i in items
                if i.get("id")
            ]

            translations = await get_media_translations(
                db,
                media_ids,
                lang,
            )

            apply_media_translations(
                items,
                translations,
            )

    return {"next_up": items}


import schemas
from core import tmdb
from core.enrichment import enrich_media
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm.attributes import flag_modified


class NextUpHideRequest(BaseModel):
    show_id: int


@router.post("/next-up/hide")
async def hide_next_up_show(
    body: NextUpHideRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings_result = await db.execute(select(UserSettings).where(UserSettings.user_id == current_user.id))
    settings = settings_result.scalar_one_or_none()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")
    hidden = list(settings.next_up_hidden_shows or [])
    if body.show_id not in hidden:
        hidden.append(body.show_id)
        settings.next_up_hidden_shows = hidden
        flag_modified(settings, "next_up_hidden_shows")
        await db.commit()
    return {"status": "ok"}


@router.delete("/next-up/hide")
async def unhide_next_up_show(
    show_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings_result = await db.execute(select(UserSettings).where(UserSettings.user_id == current_user.id))
    settings = settings_result.scalar_one_or_none()
    if settings:
        hidden = list(settings.next_up_hidden_shows or [])
        if show_id in hidden:
            hidden.remove(show_id)
            settings.next_up_hidden_shows = hidden
            flag_modified(settings, "next_up_hidden_shows")
            await db.commit()
    return {"status": "ok"}


class SeasonWatchRequest(BaseModel):
    series_tmdb_id: int
    season_number: int
    episode_order: str | None = None


class ShowWatchRequest(BaseModel):
    series_tmdb_id: int


@router.post("", response_model=dict)
async def mark_as_watched(
    event_in: schemas.WatchEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Check if Media exists locally
    media = None
    show = None
    api_key = None
    episode_has_context = (
        event_in.media_type == MediaType.episode
        and event_in.series_tmdb_id is not None
        and event_in.season_number is not None
        and event_in.episode_number is not None
    )

    if episode_has_context:
        from routers.media import get_user_tmdb_key
        from routers.webhooks import _find_or_create_show

        api_key = await get_user_tmdb_key(db, current_user.id)
        try:
            show = await _find_or_create_show(db, event_in.series_tmdb_id, api_key)
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"TMDB Media not found: {e}")

        # Prefer looking up episodes by their show context since tmdb_id may not
        # be set on Media records created via TVDB or webhook paths.
        ep_result = await db.execute(
            select(Media)
            .where(Media.media_type == MediaType.episode)
            .where(Media.show_id == show.id)
            .where(Media.season_number == event_in.season_number)
            .where(Media.episode_number == event_in.episode_number)
        )
        media = ep_result.scalars().first()

    if not media:
        result = await db.execute(
            select(Media).where(Media.tmdb_id == event_in.tmdb_id, Media.media_type == event_in.media_type)
        )
        media = result.scalars().first()

    # A previous manual mark may have created the episode before its parent show
    # existed locally. Adopt and re-enrich that orphan now that the UI supplied
    # the complete episode context.
    if media and show and not media.show_id:
        media.show_id = show.id
        media.season_number = event_in.season_number
        media.episode_number = event_in.episode_number
        if not media.poster_path or media.tmdb_data is None:
            await enrich_media(media, api_key=api_key, series_tmdb_id=event_in.series_tmdb_id)

    # 2. If not, create Media record from TMDB
    if not media:
        if api_key is None:
            from routers.media import get_user_tmdb_key

            api_key = await get_user_tmdb_key(db, current_user.id)

        try:
            if event_in.media_type == MediaType.movie:
                data = await tmdb.get_movie(event_in.tmdb_id, api_key=api_key)
                media = Media(
                    tmdb_id=event_in.tmdb_id, media_type=event_in.media_type, title=data.get("title")
                )
                db.add(media)
                await db.flush()
                await enrich_media(media, api_key=api_key)
            elif episode_has_context:
                ep_data = await tmdb.get_episode(
                    event_in.series_tmdb_id, event_in.season_number, event_in.episode_number, api_key=api_key
                )
                media = Media(
                    tmdb_id=ep_data.get("id"),
                    media_type=MediaType.episode,
                    title=ep_data.get("name"),
                    season_number=event_in.season_number,
                    episode_number=event_in.episode_number,
                    show_id=show.id,
                )
                db.add(media)
                await db.flush()
                await enrich_media(media, api_key=api_key, series_tmdb_id=event_in.series_tmdb_id)
            else:
                raise HTTPException(status_code=404, detail="Episode context required (series_tmdb_id, season_number, episode_number)")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"TMDB Media not found: {e}")

    # 3. Create WatchEvent
    # Omitted watched_at retains the existing API default ("now"); explicit
    # null marks the play watched without a known date.
    watched_at = (
        event_in.watched_at.replace(tzinfo=None) if event_in.watched_at is not None
        else None if "watched_at" in event_in.model_fields_set
        else datetime.utcnow()
    )
    event = WatchEvent(
        user_id=current_user.id,
        media_id=media.id,
        watched_at=watched_at,
        watch_source=event_in.watch_source,
        completed=event_in.completed,
        play_count=1,
        progress_percent=1.0 if event_in.completed else 0.0,
    )
    db.add(event)
    if event_in.completed:
        await db.execute(
            delete(PlaybackProgress).where(
                PlaybackProgress.user_id == current_user.id,
                PlaybackProgress.media_id == media.id,
            )
        )
    await db.commit()

    # 4. Push to media servers if outbound push is enabled
    if event_in.completed:
        await _push_watch_state(
            db, current_user.id, [media.id], watched=True,
            watched_at_by_media={media.id: watched_at},
        )

    return {"status": "ok", "message": f"Marked {media.title} as watched"}


@router.get("/item-events")
async def get_item_events(
    tmdb_id: int = Query(...),
    media_type: MediaType = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all completed watch events for a specific movie or episode."""
    query = (
        select(WatchEvent)
        .join(Media, Media.id == WatchEvent.media_id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.completed == True,
            Media.tmdb_id == tmdb_id,
            Media.media_type == media_type,
        )
        .order_by(WatchEvent.watched_at.desc().nulls_last(), WatchEvent.id.desc())
    )
    result = await db.execute(query)
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "watched_at": e.watched_at.isoformat() if e.watched_at else None,
            "watch_source": e.watch_source,
        }
        for e in events
    ]


@router.delete("/event/{event_id}")
async def delete_single_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a single watch event by its ID."""
    result = await db.execute(
        select(WatchEvent).where(
            WatchEvent.id == event_id,
            WatchEvent.user_id == current_user.id,
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    media_id = event.media_id
    await db.execute(
        delete(WatchEvent).where(
            WatchEvent.id == event_id,
            WatchEvent.user_id == current_user.id,
        )
    )
    await db.commit()

    # Only push "unwatched" to connected services if no events remain for this media
    remaining = await db.execute(
        select(func.count()).where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.media_id == media_id,
        )
    )
    if remaining.scalar() == 0:
        await _push_watch_state(db, current_user.id, [media_id], watched=False)

    return {"status": "ok"}


@router.patch("/event/{event_id}")
async def update_watch_event_source(
    event_id: int,
    update: schemas.WatchEventSourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the source for an existing play without changing its watch date."""
    result = await db.execute(
        select(WatchEvent).where(
            WatchEvent.id == event_id,
            WatchEvent.user_id == current_user.id,
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event.watch_source = update.watch_source
    await db.commit()
    return {"status": "ok", "watch_source": event.watch_source}


@router.delete("")
async def clear_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(delete(WatchEvent).where(WatchEvent.user_id == current_user.id))
    await db.commit()
    return {"status": "ok", "message": "Watch history cleared"}


@router.delete("/item")
async def unwatch_item(
    tmdb_id: int | None = Query(None),
    media_id: int | None = Query(None, alias="id"),
    media_type: MediaType = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove all watch events for a specific item."""
    if not tmdb_id and not media_id:
        raise HTTPException(status_code=400, detail="Either tmdb_id or id is required")

    if tmdb_id:
        media_q = await db.execute(
            select(Media).where(Media.tmdb_id == tmdb_id, Media.media_type == media_type)
        )
    else:
        media_q = await db.execute(
            select(Media).where(Media.id == media_id, Media.media_type == media_type)
        )
    
    media = media_q.scalar_one_or_none()
    if not media:
        return {"status": "ok", "count": 0}
    await db.execute(
        delete(WatchEvent).where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.media_id == media.id,
        )
    )
    await db.commit()
    await _push_watch_state(db, current_user.id, [media.id], watched=False)
    return {"status": "ok"}


@router.post("/season")
async def mark_season_watched(
    body: SeasonWatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all aired episodes of a season as watched, fetching from TMDB if needed."""
    # 1. Ensure show exists
    show_q = await db.execute(select(Show).where(Show.tmdb_id == body.series_tmdb_id))
    show = show_q.scalar_one_or_none()
    
    api_key = await get_user_tmdb_key(db, current_user.id)
    if not show:
        if not check_tmdb_key(api_key):
            raise HTTPException(status_code=404, detail="Show not found and TMDB key not configured")
        data = await tmdb.get_show(body.series_tmdb_id, api_key=api_key)
        show = Show(
            tmdb_id=body.series_tmdb_id,
            title=data.get("name") or "Unknown",
            poster_path=tmdb.poster_url(data.get("poster_path")),
            backdrop_path=tmdb.poster_url(data.get("backdrop_path"), size="w1280"),
            tmdb_rating=data.get("vote_average"),
            status=data.get("status"),
            first_air_date=data.get("first_air_date"),
            tmdb_data={
                "genres": [g["name"] for g in data.get("genres", [])],
                "seasons": [
                    {
                        "season_number": s["season_number"],
                        "episode_count": s["episode_count"],
                        "name": s["name"],
                    } for s in data.get("seasons", [])
                ]
            }
        )
        db.add(show)
        await db.flush()

    target_positions: set[tuple[int, int]] | None = None
    canonical_seasons = [body.season_number]
    if body.episode_order == "tvdb":
        mapping_result = await db.execute(
            select(EpisodeOrderMapping).where(
                EpisodeOrderMapping.series_tmdb_id == body.series_tmdb_id,
                EpisodeOrderMapping.tvdb_season_number == body.season_number,
            )
        )
        mappings = list(mapping_result.scalars().all())
        if not mappings:
            raise HTTPException(status_code=400, detail="TVDB episode mapping is not available")
        target_positions = {
            (mapping.tmdb_season_number, mapping.tmdb_episode_number)
            for mapping in mappings
        }
        canonical_seasons = sorted({season for season, _ in target_positions})

    try:
        season_payloads = await asyncio.gather(
            *(
                tmdb.get_season(
                    body.series_tmdb_id,
                    canonical_season,
                    api_key=api_key,
                )
                for canonical_season in canonical_seasons
            )
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Season not found: {e}")

    now = datetime.utcnow()
    today = now.date()
    existing_q = await db.execute(
        select(Media).where(
            Media.show_id == show.id,
            Media.media_type == MediaType.episode,
            Media.season_number.in_(canonical_seasons),
        )
    )
    existing_map = {
        (media.season_number, media.episode_number): media
        for media in existing_q.scalars().all()
    }

    all_season_episodes = []
    for canonical_season, season_data in zip(canonical_seasons, season_payloads):
        for ep in season_data.get("episodes", []):
            position = (canonical_season, ep["episode_number"])
            if target_positions is not None and position not in target_positions:
                continue
            air_date_str = ep.get("air_date")
            if not air_date_str:
                continue
            try:
                air_date = datetime.strptime(air_date_str, "%Y-%m-%d").date()
                if air_date > today:
                    continue
            except Exception:
                continue

            existing = existing_map.get(position)
            if existing:
                all_season_episodes.append(existing)
                continue
            new_ep = Media(
                show_id=show.id,
                tmdb_id=ep["id"],
                media_type=MediaType.episode,
                title=ep.get("name") or f"Episode {ep['episode_number']}",
                season_number=canonical_season,
                episode_number=ep["episode_number"],
                poster_path=tmdb.poster_url(ep.get("still_path"), size="w500"),
                release_date=air_date_str,
                tmdb_rating=ep.get("vote_average"),
            )
            db.add(new_ep)
            all_season_episodes.append(new_ep)
    
    await db.flush() # Get IDs for new episodes
    
    # 4. Mark all as watched
    if not all_season_episodes:
        return {"status": "ok", "count": 0}

    already_q = await db.execute(
        select(WatchEvent.media_id).where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.media_id.in_([ep.id for ep in all_season_episodes]),
            WatchEvent.completed == True
        )
    )
    already_watched = {r[0] for r in already_q.all()}
    
    newly_watched = []
    for ep in all_season_episodes:
        if ep.id not in already_watched:
            db.add(WatchEvent(
                user_id=current_user.id,
                media_id=ep.id,
                watched_at=now,
                completed=True,
                play_count=1,
                progress_percent=1.0,
            ))
            newly_watched.append(ep.id)
            
    if newly_watched:
        await db.execute(
            delete(PlaybackProgress).where(
                PlaybackProgress.user_id == current_user.id,
                PlaybackProgress.media_id.in_(newly_watched),
            )
        )
    await db.commit()
    await _push_watch_state(db, current_user.id, newly_watched, watched=True)
    return {"status": "ok", "count": len(newly_watched)}


@router.delete("/season")
async def unwatch_season(
    series_tmdb_id: int = Query(...),
    season_number: int = Query(...),
    episode_order: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove all watch events for a season."""
    show_q = await db.execute(select(Show).where(Show.tmdb_id == series_tmdb_id))
    show = show_q.scalar_one_or_none()
    if not show:
        return {"status": "ok", "count": 0}

    media_filters = [
        Media.show_id == show.id,
        Media.media_type == MediaType.episode,
    ]
    if episode_order == "tvdb":
        mapping_result = await db.execute(
            select(EpisodeOrderMapping).where(
                EpisodeOrderMapping.series_tmdb_id == series_tmdb_id,
                EpisodeOrderMapping.tvdb_season_number == season_number,
            )
        )
        positions = [
            and_(
                Media.season_number == mapping.tmdb_season_number,
                Media.episode_number == mapping.tmdb_episode_number,
            )
            for mapping in mapping_result.scalars().all()
        ]
        if not positions:
            return {"status": "ok", "count": 0}
        media_filters.append(or_(*positions))
    else:
        media_filters.append(Media.season_number == season_number)

    episodes_q = await db.execute(select(Media.id).where(*media_filters))
    episode_ids = [row[0] for row in episodes_q.all()]
    if not episode_ids:
        return {"status": "ok", "count": 0}

    result = await db.execute(
        delete(WatchEvent).where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.media_id.in_(episode_ids),
        )
    )
    await db.commit()
    await _push_watch_state(db, current_user.id, episode_ids, watched=False)
    return {"status": "ok", "count": result.rowcount}


@router.post("/show-all")
async def mark_show_watched(
    body: ShowWatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all aired episodes of all seasons as watched."""
    # 1. Ensure show exists and get its metadata
    show_q = await db.execute(select(Show).where(Show.tmdb_id == body.series_tmdb_id))
    show = show_q.scalar_one_or_none()
    
    api_key = await get_user_tmdb_key(db, current_user.id)
    if not show:
        if not check_tmdb_key(api_key):
            raise HTTPException(status_code=404, detail="Show not found and TMDB key not configured")
        data = await tmdb.get_show(body.series_tmdb_id, api_key=api_key)
        show = Show(
            tmdb_id=body.series_tmdb_id,
            title=data.get("name") or "Unknown",
            poster_path=tmdb.poster_url(data.get("poster_path")),
            backdrop_path=tmdb.poster_url(data.get("backdrop_path"), size="w1280"),
            tmdb_rating=data.get("vote_average"),
            status=data.get("status"),
            first_air_date=data.get("first_air_date"),
            tmdb_data={
                "genres": [g["name"] for g in data.get("genres", [])],
                "seasons": [
                    {
                        "season_number": s["season_number"],
                        "episode_count": s["episode_count"],
                        "name": s["name"],
                    } for s in data.get("seasons", [])
                ]
            }
        )
        db.add(show)
        await db.flush()
    else:
        # We need TMDB data for season/episode counts
        if not show.tmdb_data or "seasons" not in show.tmdb_data:
            data = await tmdb.get_show(body.series_tmdb_id, api_key=api_key)
            show.tmdb_data = {
                "genres": [g["name"] for g in data.get("genres", [])],
                "seasons": [
                    {
                        "season_number": s["season_number"],
                        "episode_count": s["episode_count"],
                        "name": s["name"],
                    } for s in data.get("seasons", [])
                ]
            }
            await db.flush()

    # 2. For each season, fetch episodes and ensure they exist + mark watched
    seasons = [s["season_number"] for s in show.tmdb_data["seasons"] if s["season_number"] > 0]
    all_newly_watched_ids = []
    
    now = datetime.utcnow()
    today = now.date()

    for sn in seasons:
        try:
            season_data = await tmdb.get_season(body.series_tmdb_id, sn, api_key=api_key)
        except Exception: continue # Skip failed seasons

        existing_q = await db.execute(
            select(Media).where(
                Media.show_id == show.id,
                Media.media_type == MediaType.episode,
                Media.season_number == sn
            )
        )
        existing_map = {m.episode_number: m for m in existing_q.scalars().all()}
        
        season_eps_to_watch = []
        for ep in season_data.get("episodes", []):
            air_date_str = ep.get("air_date")
            if not air_date_str: continue
            try:
                air_date = datetime.strptime(air_date_str, "%Y-%m-%d").date()
                if air_date > today: continue
            except Exception: continue
            
            ep_num = ep["episode_number"]
            if ep_num in existing_map:
                season_eps_to_watch.append(existing_map[ep_num])
            else:
                new_ep = Media(
                    show_id=show.id,
                    tmdb_id=ep["id"],
                    media_type=MediaType.episode,
                    title=ep.get("name") or f"Episode {ep_num}",
                    season_number=sn,
                    episode_number=ep_num,
                    poster_path=tmdb.poster_url(ep.get("still_path"), size="w500"),
                    release_date=air_date_str,
                    tmdb_rating=ep.get("vote_average"),
                )
                db.add(new_ep)
                season_eps_to_watch.append(new_ep)
        
        await db.flush()
        
        if not season_eps_to_watch: continue

        already_q = await db.execute(
            select(WatchEvent.media_id).where(
                WatchEvent.user_id == current_user.id,
                WatchEvent.media_id.in_([ep.id for ep in season_eps_to_watch]),
                WatchEvent.completed == True
            )
        )
        already_watched = {r[0] for r in already_q.all()}
        
        for ep in season_eps_to_watch:
            if ep.id not in already_watched:
                db.add(WatchEvent(
                    user_id=current_user.id,
                    media_id=ep.id,
                    watched_at=now,
                    completed=True,
                    play_count=1,
                    progress_percent=1.0,
                ))
                all_newly_watched_ids.append(ep.id)

    if all_newly_watched_ids:
        await db.execute(
            delete(PlaybackProgress).where(
                PlaybackProgress.user_id == current_user.id,
                PlaybackProgress.media_id.in_(all_newly_watched_ids),
            )
        )
    await db.commit()
    await _push_watch_state(db, current_user.id, all_newly_watched_ids, watched=True)
    return {"status": "ok", "count": len(all_newly_watched_ids)}


@router.delete("/show-all")
async def unwatch_show(
    series_tmdb_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove all watch events for all episodes of a show."""
    show_q = await db.execute(select(Show).where(Show.tmdb_id == series_tmdb_id))
    show = show_q.scalar_one_or_none()
    if not show:
        return {"status": "ok", "count": 0}

    episodes_q = await db.execute(
        select(Media.id).where(
            Media.show_id == show.id,
            Media.media_type == MediaType.episode,
        )
    )
    episode_ids = [r[0] for r in episodes_q.all()]
    if not episode_ids:
        return {"status": "ok", "count": 0}

    result = await db.execute(
        delete(WatchEvent).where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.media_id.in_(episode_ids),
        )
    )
    await db.commit()
    await _push_watch_state(db, current_user.id, episode_ids, watched=False)
    return {"status": "ok", "count": result.rowcount}


# ---------------------------------------------------------------------------
# Manual scrobble session endpoints
# ---------------------------------------------------------------------------

async def _get_or_create_media_for_session(
    db: AsyncSession,
    body: schemas.ManualSessionStart,
    user_id: int,
) -> Media:
    # Prefer direct media_id lookup (used for TVDB-only episodes with no tmdb_id)
    if body.media_id:
        result = await db.execute(select(Media).where(Media.id == body.media_id))
        media = result.scalar_one_or_none()
        if media:
            return media

    if body.tmdb_id:
        result = await db.execute(
            select(Media)
            .where(Media.tmdb_id == body.tmdb_id, Media.media_type == body.media_type)
            .order_by(Media.id)
        )
        # A film can have more than one row (e.g. a media-server stub and a
        # Trakt row); use the oldest rather than failing.
        media = result.scalars().first()
        if media:
            return media

    api_key = await get_user_tmdb_key(db, user_id)

    if body.media_type == MediaType.movie:
        if not body.tmdb_id:
            raise HTTPException(status_code=400, detail="tmdb_id required for movies")
        if not check_tmdb_key(api_key):
            raise HTTPException(status_code=404, detail="Movie not in library and TMDB key not configured")
        try:
            data = await tmdb.get_movie(body.tmdb_id, api_key=api_key)
            title = data.get("title") or body.title or "Unknown"
        except Exception:
            title = body.title or "Unknown"
        media = Media(tmdb_id=body.tmdb_id, media_type=body.media_type, title=title)
        db.add(media)
        await db.flush()
        try:
            await enrich_media(media, api_key=api_key)
        except Exception:
            pass
    else:
        # Episode: create a minimal row from request data
        media = Media(
            tmdb_id=body.tmdb_id,
            media_type=body.media_type,
            title=body.title or "Unknown",
            runtime=body.runtime,
            season_number=body.season_number,
            episode_number=body.episode_number,
        )
        if body.show_tmdb_id:
            show_q = await db.execute(select(Show).where(Show.tmdb_id == body.show_tmdb_id))
            show = show_q.scalar_one_or_none()
            if show:
                media.show_id = show.id
        db.add(media)
        await db.flush()

    return media


@router.post("/session/start")
async def start_manual_session(
    body: schemas.ManualSessionStart,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a manual scrobble session for any movie or episode."""
    media = await _get_or_create_media_for_session(db, body, current_user.id)

    if media.runtime is None and body.runtime:
        media.runtime = body.runtime

    session_key = f"manual-{current_user.id}-{media.id}"

    await db.execute(delete(PlaybackSession).where(PlaybackSession.session_key == session_key))
    session = PlaybackSession(
        user_id=current_user.id,
        media_id=media.id,
        session_key=session_key,
        source="manual",
        state="playing",
        progress_seconds=0,
        progress_percent=0.0,
        watch_source=body.watch_source,
    )
    db.add(session)
    await db.commit()

    return {"session_key": session_key, "media_id": media.id, "runtime": media.runtime}


@router.get("/session/active")
async def list_manual_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The user's running "Watch now" sessions, for the Now watching bar."""
    result = await db.execute(
        select(PlaybackSession, Media)
        .options(selectinload(Media.show))
        .join(Media, Media.id == PlaybackSession.media_id)
        .where(
            PlaybackSession.user_id == current_user.id,
            PlaybackSession.source == "manual",
        )
        .order_by(PlaybackSession.started_at.desc())
    )
    sessions = []
    for session, media in result.all():
        show = media.show if media.media_type == MediaType.episode else None
        sessions.append({
            "session_key": session.session_key,
            "state": session.state,
            "progress_seconds": session.progress_seconds,
            # Naive UTC timestamps, like the rest of the API
            "started_at": session.started_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "watch_source": session.watch_source,
            "runtime": media.runtime,
            "media": {
                "id": media.id,
                "tmdb_id": media.tmdb_id,
                "type": media.media_type,
                "title": media.title,
                "poster_path": (show.poster_path if show else None) or media.poster_path,
                "show_title": show.title if show else None,
                "show_tmdb_id": show.tmdb_id if show else None,
                "season_number": media.season_number,
                "episode_number": media.episode_number,
            },
        })
    return sessions


@router.patch("/session/{session_key}")
async def update_manual_session(
    session_key: str,
    body: schemas.ManualSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Heartbeat / pause / resume for a manual session."""
    result = await db.execute(
        select(PlaybackSession).where(
            PlaybackSession.session_key == session_key,
            PlaybackSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    media_q = await db.execute(select(Media).where(Media.id == session.media_id))
    media = media_q.scalar_one_or_none()

    runtime_seconds = (media.runtime * 60) if (media and media.runtime) else 0
    progress_pct = (body.progress_seconds / runtime_seconds) if runtime_seconds > 0 else 0.0
    progress_pct = min(1.0, max(0.0, progress_pct))

    session.progress_seconds = body.progress_seconds
    session.progress_percent = progress_pct
    if body.state in ("playing", "paused"):
        session.state = body.state
    session.updated_at = datetime.utcnow()

    if 0.05 <= progress_pct < 0.90:
        prog_q = await db.execute(
            select(PlaybackProgress).where(
                PlaybackProgress.user_id == current_user.id,
                PlaybackProgress.media_id == session.media_id,
            )
        )
        prog = prog_q.scalar_one_or_none()
        if prog:
            prog.progress_seconds = body.progress_seconds
            prog.progress_percent = progress_pct
        else:
            db.add(PlaybackProgress(
                user_id=current_user.id,
                media_id=session.media_id,
                progress_seconds=body.progress_seconds,
                progress_percent=progress_pct,
            ))

    await db.commit()
    return {"status": "ok"}


@router.delete("/session/{session_key}")
async def stop_manual_session(
    session_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop and discard a manual session without marking as watched."""
    result = await db.execute(
        select(PlaybackSession).where(
            PlaybackSession.session_key == session_key,
            PlaybackSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    media_id = session.media_id
    await db.execute(delete(PlaybackSession).where(PlaybackSession.session_key == session_key))
    await db.execute(
        delete(PlaybackProgress).where(
            PlaybackProgress.user_id == current_user.id,
            PlaybackProgress.media_id == media_id,
        )
    )
    await db.commit()
    return {"status": "ok"}


async def auto_complete_manual_sessions(db: AsyncSession) -> None:
    """Complete any manual sessions where enough time has elapsed since the last heartbeat."""
    now = datetime.utcnow()
    result = await db.execute(
        select(PlaybackSession, Media)
        .join(Media, Media.id == PlaybackSession.media_id)
        .where(PlaybackSession.source == "manual", PlaybackSession.state == "playing")
    )
    completed: list[tuple[int, int]] = []  # (user_id, media_id)
    for session, media in result.all():
        runtime_seconds = (media.runtime or 0) * 60
        if runtime_seconds <= 0:
            continue
        elapsed = session.progress_seconds + (now - session.updated_at).total_seconds()
        if elapsed < runtime_seconds:
            continue
        await db.execute(delete(PlaybackSession).where(PlaybackSession.id == session.id))
        await db.execute(
            delete(PlaybackProgress).where(
                PlaybackProgress.user_id == session.user_id,
                PlaybackProgress.media_id == session.media_id,
            )
        )
        db.add(WatchEvent(
            user_id=session.user_id,
            media_id=session.media_id,
            watched_at=now,
            completed=True,
            play_count=1,
            progress_percent=1.0,
            watch_source=session.watch_source,
        ))
        completed.append((session.user_id, session.media_id))
    if completed:
        await db.commit()
        for user_id, media_id in completed:
            await _push_watch_state(db, user_id, [media_id], watched=True)


@router.post("/session/{session_key}/complete")
async def complete_manual_session(
    session_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark as fully watched and end the session."""
    result = await db.execute(
        select(PlaybackSession).where(
            PlaybackSession.session_key == session_key,
            PlaybackSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    media_id = session.media_id
    watch_source = session.watch_source
    await db.execute(delete(PlaybackSession).where(PlaybackSession.session_key == session_key))
    await db.execute(
        delete(PlaybackProgress).where(
            PlaybackProgress.user_id == current_user.id,
            PlaybackProgress.media_id == media_id,
        )
    )

    db.add(WatchEvent(
        user_id=current_user.id,
        media_id=media_id,
        watched_at=datetime.utcnow(),
        completed=True,
        play_count=1,
        progress_percent=1.0,
        watch_source=watch_source,
    ))
    await db.commit()

    await _push_watch_state(db, current_user.id, [media_id], watched=True)
    return {"status": "ok"}
