import asyncio
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, update, func, case, cast as sa_cast, Text, or_, and_
from sqlalchemy.orm import aliased
import os
import re
import time

from models.events import WatchEvent
from models.collection import Collection, CollectionFile
from models.ratings import Rating
from models.lists import List as UserList, ListItem

from db import get_db, engine
from models.media import Media
from models.collection import Collection, CollectionFile
from models.base import CollectionSource, MediaType
from models.show import Show as ShowModel
from models.sync import SyncJob, SyncStatus
from models.users import User, UserSettings
from models.episode_order import EpisodeOrderMapping, UserShowEpisodeOrder
from routers.media import format_media, get_user_tmdb_key, check_tmdb_key, enrich_with_state, refresh_technical_data, _extract_show_content_rating, get_where_to_watch, _effective_sonarr, _get_global_settings

from dependencies import get_current_user
from core.episode_badges import last_season, season_badges
from core import cast_split
from core import award_data
from core.awards import TV_FAMILIES, credited, family as award_family, join_names, match_group, name_tv_awards, topic, topic_jobs, tv_record_rows
from core import source_work, wikidata
from core import tmdb
from core.config import settings
from core import tvdb as tvdb_client
from core.episode_order import ensure_episode_order_mapping, get_episode_order, validate_episode_order
from core.translations import (
    get_user_metadata_language,
    get_media_translations,
    get_show_translations,
    upsert_media_translation,
    upsert_show_translation,
    apply_media_translations,
    apply_show_translations,
)
from routers.calendar import get_tvmaze_episodes

MALTA_TZ = ZoneInfo("Europe/Malta")

router = APIRouter()


def _format_show_crew(data: dict) -> list[dict]:
    """Flatten TMDB aggregate episode crew into person/job credits."""
    crew = []
    seen = set()
    for person in (data.get("aggregate_credits") or {}).get("crew", []):
        person_id = person.get("id")
        if not person_id or not person.get("name"):
            continue
        for credit in person.get("jobs", []):
            job = credit.get("job")
            if not job or (person_id, job) in seen:
                continue
            seen.add((person_id, job))
            crew.append({
                "tmdb_id": person_id,
                "name": person["name"],
                "job": job,
                "department": person.get("department"),
                "profile_path": tmdb.poster_url(person.get("profile_path"), size="w185"),
                # This job's own episodes, never their total across every job.
                "episode_count": credit.get("episode_count") or None,
            })

    # TMDB lists show creators separately from aggregate episode crew.
    for creator in data.get("created_by", []):
        person_id = creator.get("id")
        if not person_id or not creator.get("name") or (person_id, "Creator") in seen:
            continue
        seen.add((person_id, "Creator"))
        crew.append({
            "tmdb_id": person_id,
            "name": creator["name"],
            "job": "Creator",
            "department": "Creator",
            "profile_path": tmdb.poster_url(creator.get("profile_path"), size="w185"),
            "episode_count": None,
        })
    return crew


async def _show_cast(show, data: dict, api_key: str | None, db: AsyncSession) -> tuple[list[dict], list[dict]]:
    """Cast and guest stars by who was a regular in any season (core.cast_split),
    kept on a local show; TMDB's latest-season split if the seasons can't be read."""
    if show is not None and cast_split.is_fresh(show.tmdb_data, show.status):
        split = show.tmdb_data["cast_split"]
        return split["cast"], split["guest_stars"]
    split = await cast_split.build(data.get("id") or (show.tmdb_id if show else None), data, api_key)
    if not split:
        return _format_aggregate_show_cast(data)
    if show is not None:
        show.tmdb_data = {**(show.tmdb_data or {}), "cast_split": split}
        await db.commit()
    return split["cast"], split["guest_stars"]


def _format_aggregate_show_cast(data: dict) -> tuple[list[dict], list[dict]]:
    """Build cast and guest-star lists from one aggregate TMDB response."""
    credits = data.get("credits") or {}
    main_cast_ids = {
        person.get("id") for person in credits.get("cast", []) if person.get("id")
    }
    aggregate_cast = (data.get("aggregate_credits") or {}).get("cast", [])

    if not aggregate_cast:
        cast = [
            {
                "tmdb_id": person.get("id"),
                "name": person.get("name"),
                "character": person.get("character"),
                "profile_path": tmdb.poster_url(person.get("profile_path")),
                "episode_count": None,
            }
            for person in credits.get("cast", [])[:12]
            if person.get("id") and person.get("name")
        ]
        return cast, []

    cast, guest_stars = [], []
    for person in aggregate_cast:
        person_id = person.get("id")
        if not person_id or not person.get("name"):
            continue
        roles = person.get("roles") or []
        characters = list(dict.fromkeys(
            role["character"] for role in roles
            if role.get("character")
        ))
        entry = {
            "tmdb_id": person_id,
            "name": person["name"],
            "character": " / ".join(characters),
            "profile_path": tmdb.poster_url(person.get("profile_path")),
            "episode_count": person.get("total_episode_count") or sum(
                role.get("episode_count", 0) for role in roles
            ),
        }
        (cast if person_id in main_cast_ids else guest_stars).append(entry)

    if not main_cast_ids:
        all_cast = sorted(
            cast + guest_stars,
            key=lambda person: person["episode_count"],
            reverse=True,
        )
        cast, guest_stars = all_cast[:12], all_cast[12:]

    cast.sort(key=lambda person: person["episode_count"], reverse=True)
    guest_stars.sort(key=lambda person: person["episode_count"], reverse=True)
    return cast[:12], guest_stars


async def get_user_tvdb_key(db: AsyncSession, user_id: int) -> str | None:
    from models.global_settings import GlobalSettings
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalar_one_or_none()
    if s and s.tvdb_api_key:
        return s.tvdb_api_key
    gs_result = await db.execute(select(GlobalSettings).where(GlobalSettings.id == 1))
    gs = gs_result.scalar_one_or_none()

    if gs and gs.tvdb_api_key:
        return gs.tvdb_api_key

    return os.getenv("TVDB_API_KEY")


async def _enrich_tvdb_seasons(
    seasons: list[dict],
    mappings: list[EpisodeOrderMapping],
    *,
    tvdb_api_key: str,
    tvdb_language: str | None,
    series_tmdb_id: int | None,
    tmdb_api_key: str | None,
    metadata_language: str | None,
) -> tuple[list[dict], dict]:
    """Add translated TVDB metadata and TMDB ratings to TVDB seasons."""
    semaphore = asyncio.Semaphore(5)
    tvdb_metadata: dict[int, dict] = {}
    tmdb_show: dict = {}

    async def fetch_tvdb_season(season: dict) -> None:
        season_id = season.get("id")
        season_number = season.get("season_number")
        if season_id is None or season_number is None:
            return
        try:
            async with semaphore:
                raw = await tvdb_client.get_season(season_id, tvdb_api_key)
            tvdb_metadata[season_number] = tvdb_client.format_season(
                raw,
                language=tvdb_language,
            )
        except Exception:
            pass

    async def fetch_tmdb_show() -> None:
        nonlocal tmdb_show
        if series_tmdb_id is None or not tmdb_api_key:
            return
        try:
            tmdb_show = await tmdb.get_show(
                series_tmdb_id,
                tmdb_api_key,
                language=metadata_language,
            )
        except Exception:
            pass

    await asyncio.gather(
        *(fetch_tvdb_season(season) for season in seasons),
        fetch_tmdb_show(),
    )

    tmdb_seasons = {
        season.get("season_number"): season
        for season in (tmdb_show.get("seasons") or [])
        if season.get("season_number") is not None
    }
    mapping_counts: dict[int, dict[int, int]] = {}
    for mapping in mappings:
        if (
            mapping.tvdb_season_number is None
            or mapping.tmdb_season_number is None
        ):
            continue
        counts = mapping_counts.setdefault(mapping.tvdb_season_number, {})
        counts[mapping.tmdb_season_number] = (
            counts.get(mapping.tmdb_season_number, 0) + 1
        )

    enriched = []
    for season in seasons:
        season_number = season.get("season_number")
        tvdb_season = tvdb_metadata.get(season_number, {})
        candidates = mapping_counts.get(season_number, {})
        tmdb_season_number = (
            max(
                candidates,
                key=lambda candidate: (
                    candidates[candidate],
                    candidate == season_number,
                    -abs(candidate - season_number),
                ),
            )
            if candidates
            else season_number
        )
        tmdb_season = tmdb_seasons.get(tmdb_season_number, {})
        enriched.append({
            **season,
            "name": tvdb_season.get("name") or season.get("name"),
            "overview": (
                tvdb_season.get("overview")
                or tmdb_season.get("overview")
                or season.get("overview")
            ),
            "poster_path": (
                tvdb_season.get("poster_path")
                or season.get("poster_path")
            ),
            "air_date": (
                tvdb_season.get("air_date")
                or season.get("air_date")
                or tmdb_season.get("air_date")
            ),
            "tmdb_rating": tmdb_season.get("vote_average"),
        })
    return enriched, tmdb_show


def format_show(show: ShowModel) -> dict:
    return {
        "id": show.id,
        "tmdb_id": show.tmdb_id,
        "tvdb_id": show.tvdb_id,
        "type": "series",
        "title": show.title,
        "original_title": show.original_title,
        "overview": show.overview,
        "poster_path": show.poster_path,
        "backdrop_path": show.backdrop_path,
        "tmdb_rating": show.tmdb_rating,
        "imdb_rating": (show.tmdb_data or {}).get("imdb_rating"),
        "status": show.status,
        "tagline": show.tagline,
        "first_air_date": show.first_air_date,
        "last_air_date": show.last_air_date,
        "genres": [g["name"] if isinstance(g, dict) else g for g in (show.tmdb_data or {}).get("genres", [])],
        "seasons_meta": (show.tmdb_data or {}).get("seasons", []),
        "networks": [
            {
                **n,
                "logo_path": tmdb.poster_url(n.get("logo_path")),
            }
            for n in (show.tmdb_data or {}).get("networks", [])
        ],
        "original_language": (show.tmdb_data or {}).get("original_language"),
        "adult": (show.tmdb_data or {}).get("adult", False),
    }

async def build_show_info(
    show: ShowModel,
    db: AsyncSession,
    user_id: int,
    *,
    tmdb_data: dict | None = None,
) -> dict:
    """Build consistent show metadata using Watchd + TMDB + TVDB."""
    show_info = format_show(show)

    show_info["genres"] = [
        g
        for g in show_info.get("genres", [])
        if g.lower() not in {"family", "kids", "children"}
    ]

    # TVDB is the source of truth for show genres.
    tvdb_api_key = await get_user_tvdb_key(db, user_id)
    metadata_lang = await get_user_metadata_language(db, user_id)

    if tvdb_api_key and show.tvdb_id:
        try:
            tvdb_raw = await tvdb_client.get_series(
                show.tvdb_id,
                tvdb_api_key,
            )
            tvdb_formatted = tvdb_client.format_series(
                tvdb_raw,
                language=tvdb_client.tvdb_language(metadata_lang),
            )

            show_info["genres"] = [
                g
                for g in tvdb_formatted.get("genres", [])
                if g.lower() not in {"family", "kids", "children"}
            ]
        except Exception as e:
            print(f"TVDB genre fetch failed for {show.tvdb_id}: {e}")

    # Use live TMDB data for fields that should reflect the selected
    # metadata language.
    if tmdb_data:
        for field, tmdb_key in [
            ("title", "name"),
            ("overview", "overview"),
            ("tagline", "tagline"),
        ]:
            value = tmdb_data.get(tmdb_key)
            if value:
                show_info[field] = value

        if tmdb_data.get("networks"):
            show_info["networks"] = [
                {
                    "id": n["id"],
                    "name": n["name"],
                    "logo_path": tmdb.poster_url(n.get("logo_path"), size="w500")
                    if n.get("logo_path")
                    else None,
                    "origin_country": n.get("origin_country"),
                }
                for n in tmdb_data.get("networks", [])
            ]

        show_info["age_rating"] = _extract_show_content_rating(tmdb_data)

        if tmdb_data.get("external_ids"):
            show_info["imdb_id"] = tmdb_data["external_ids"].get("imdb_id")

        show_info["original_language"] = (
            show_info.get("original_language")
            or tmdb_data.get("original_language")
        )

        show_info["adult"] = tmdb_data.get(
            "adult",
            show_info.get("adult", False),
        )

    return show_info

@router.get("")
async def list_shows(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    sort: str = Query(default="title"),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    genre: list[str] = Query(default=[]),
    year: list[int] = Query(default=[]),
    status: list[str] = Query(default=[]),
    watched: list[str] = Query(default=[]),
):
    offset = (page - 1) * page_size

    # A show is in the user's collection when either the series itself is
    # collected (cloud/watchlist providers) or at least one countable episode
    # is collected (media-server libraries).
    episode_show_ids = (
        select(Media.show_id)
        .join(Collection, Collection.media_id == Media.id)
        .where(
            Collection.user_id == current_user.id,
            Media.show_id.isnot(None),
            Media.media_type == MediaType.episode,
            Media.season_number.isnot(None),
            Media.season_number != 0,
            Media.episode_number.isnot(None),
        )
        .distinct()
        .subquery()
    )
    direct_series_tmdb_ids = (
        select(Media.tmdb_id)
        .join(Collection, Collection.media_id == Media.id)
        .where(
            Collection.user_id == current_user.id,
            Media.media_type == MediaType.series,
            Media.tmdb_id.isnot(None),
        )
        .distinct()
        .subquery()
    )

    base_query = select(ShowModel).where(
        or_(
            ShowModel.id.in_(select(episode_show_ids)),
            ShowModel.tmdb_id.in_(select(direct_series_tmdb_ids)),
        )
    )
    if genre:
        base_query = base_query.where(or_(*[
            sa_cast(ShowModel.tmdb_data["genres"], Text).contains(f'"{g}"') for g in genre
        ]))
    if year:
        base_query = base_query.where(or_(*[ShowModel.first_air_date.like(f'{y}%') for y in year]))
    if status:
        base_query = base_query.where(ShowModel.status.in_(status))

    watched_states = set(watched)

    if watched_states and watched_states != {"watched", "unwatched"}:

        watched_show_ids = (
            select(Media.show_id)
            .join(WatchEvent, WatchEvent.media_id == Media.id)
            .where(
                WatchEvent.user_id == current_user.id,
                WatchEvent.completed.is_(True),
                Media.media_type == MediaType.episode,
                Media.show_id.isnot(None),
                Media.season_number.isnot(None),
                Media.season_number != 0,
                Media.episode_number.isnot(None),
            )
            .distinct()
            .subquery()
        )

        if "unwatched" in watched_states:
            # No completed episodes.
            base_query = base_query.where(
                ShowModel.id.notin_(select(watched_show_ids))
            )

        elif "watched" in watched_states:
            # We'll handle fully-watched vs in-progress after
            # enrich_with_state(), because watch_pct is calculated there.
            base_query = base_query.where(
                ShowModel.id.in_(select(watched_show_ids))
            )

        elif "in_progress" in watched_states:
            # Started shows are narrowed here.
            # The final 100% check happens after enrichment.
            base_query = base_query.where(
                ShowModel.id.in_(select(watched_show_ids))
            )

    # Sort and Paginate
    if sort == "rating":
        q = base_query.order_by(ShowModel.tmdb_rating.desc().nulls_last())
    elif sort == "release_date":
        q = base_query.order_by(ShowModel.first_air_date.desc().nulls_last())
    elif sort == "created_at":
        q = base_query.order_by(ShowModel.created_at.desc().nulls_last())
    elif sort == "last_watched":
        last_watched_sq = (
            select(Media.show_id, func.max(WatchEvent.watched_at).label("last_watched_at"))
            .join(WatchEvent, WatchEvent.media_id == Media.id)
            .where(WatchEvent.user_id == current_user.id, Media.show_id.isnot(None))
            .group_by(Media.show_id)
            .subquery()
        )
        q = (
            base_query
            .outerjoin(last_watched_sq, last_watched_sq.c.show_id == ShowModel.id)
            .order_by(last_watched_sq.c.last_watched_at.desc().nulls_last())
        )
    else:
        q = base_query.order_by(func.lower(ShowModel.title).asc())

    filter_by_progress = bool(watched_states) and watched_states != {"watched", "unwatched"}
    if not filter_by_progress:
        # No Watch Status filter: count and page in the database.
        total = (await db.execute(select(func.count()).select_from(base_query.subquery()))).scalar_one()
        result = await db.execute(q.limit(page_size).offset(offset))
        results = [format_show(s) for s in result.scalars().all()]
        await enrich_with_state(db, current_user.id, results)
    else:
        # Fetch all matching shows first so watch_pct can be calculated
        # before applying Watch Status filtering.
        result = await db.execute(q)
        results = [format_show(s) for s in result.scalars().all()]
        await enrich_with_state(db, current_user.id, results)

    # Apply Watch Status using the existing watch_pct value.
    if filter_by_progress:
        if "unwatched" in watched_states:
            results = [
                show for show in results
                if show.get("watch_pct", 0) == 0
            ]

        elif "in_progress" in watched_states:
            results = [
                show for show in results
                if 0 < show.get("watch_pct", 0) < 100
            ]

        elif "watched" in watched_states:
            results = [
                show for show in results
                if show.get("watch_pct", 0) >= 100
            ]

        # Correct pagination after filtering.
        total = len(results)
        results = results[offset:offset + page_size]
    total_pages = (total + page_size - 1) // page_size

    lang = await get_user_metadata_language(db, current_user.id)
    if lang:
        show_ids = [r["id"] for r in results if r.get("id")]
        translations = await get_show_translations(db, show_ids, lang)
        apply_show_translations(results, translations)
    return {
        "page": page,
        "page_size": page_size,
        "total_results": total,
        "total_pages": total_pages,
        "results": results,
    }


@router.get("/years")
async def list_show_years(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct first-air-date years present in the user's show collection, for the year filter."""
    episode_show_ids = (
        select(Media.show_id)
        .join(Collection, Collection.media_id == Media.id)
        .where(
            Collection.user_id == current_user.id,
            Media.show_id.isnot(None),
            Media.media_type == MediaType.episode,
            Media.season_number.isnot(None),
            Media.season_number != 0,
            Media.episode_number.isnot(None),
        )
        .distinct()
        .subquery()
    )
    direct_series_tmdb_ids = (
        select(Media.tmdb_id)
        .join(Collection, Collection.media_id == Media.id)
        .where(
            Collection.user_id == current_user.id,
            Media.media_type == MediaType.series,
            Media.tmdb_id.isnot(None),
        )
        .distinct()
        .subquery()
    )
    result = await db.execute(
        select(func.substr(ShowModel.first_air_date, 1, 4))
        .where(
            or_(
                ShowModel.id.in_(select(episode_show_ids)),
                ShowModel.tmdb_id.in_(select(direct_series_tmdb_ids)),
            ),
            ShowModel.first_air_date.isnot(None),
            ShowModel.first_air_date != "",
        )
        .distinct()
    )
    years = sorted(
        {int(row[0]) for row in result.all() if row[0] and row[0].isdigit()},
        reverse=True,
    )
    return {"years": years}


class EpisodeOrderRequest(BaseModel):
    episode_order: str
    force_refresh: bool = False


async def _run_episode_order_mapping(
    user_id: int,
    job_id: int,
    series_tmdb_id: int,
    tmdb_api_key: str,
    tvdb_api_key: str,
    force_refresh: bool,
) -> None:
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Called concurrently (up to 5 in flight) from ensure_episode_order_mapping's
    # per-episode fetch loop — each call gets its own short-lived session/connection
    # so concurrent progress writes never share a single AsyncSession.
    async def report_progress(done: int, total: int) -> None:
        async with async_session() as pdb:
            await pdb.execute(update(SyncJob).where(SyncJob.id == job_id).values(
                processed_items=done, total_items=total, updated_at=func.now(),
            ))
            await pdb.commit()

    async with async_session() as db:
        try:
            await db.execute(update(SyncJob).where(SyncJob.id == job_id).values(status=SyncStatus.running))
            await db.commit()

            mapping_summary = await ensure_episode_order_mapping(
                db,
                series_tmdb_id,
                tmdb_api_key,
                tvdb_api_key,
                force=force_refresh,
                on_progress=report_progress,
            )
            tvdb_id = mapping_summary["tvdb_id"]

            preference = await get_episode_order(db, user_id, series_tmdb_id)
            if preference:
                preference.episode_order = "tvdb"
                preference.tvdb_id = tvdb_id
            else:
                db.add(UserShowEpisodeOrder(
                    user_id=user_id,
                    series_tmdb_id=series_tmdb_id,
                    episode_order="tvdb",
                    tvdb_id=tvdb_id,
                ))

            show_result = await db.execute(
                select(ShowModel).where(ShowModel.tmdb_id == series_tmdb_id)
            )
            local_show = show_result.scalar_one_or_none()
            if local_show:
                local_show.tvdb_id = tvdb_id

            await db.execute(update(SyncJob).where(SyncJob.id == job_id).values(
                status=SyncStatus.completed,
                stats={
                    "episode_order": "tvdb",
                    "series_tmdb_id": series_tmdb_id,
                    "tvdb_id": tvdb_id,
                    "mapping": mapping_summary,
                    "redirect": f"/show/tvdb/{tvdb_id}",
                },
            ))
            await db.commit()
        except Exception as exc:
            await db.rollback()
            await db.execute(update(SyncJob).where(SyncJob.id == job_id).values(
                status=SyncStatus.failed, error_message=str(exc)[:900],
            ))
            await db.commit()


@router.get("/episode-order/jobs/{job_id}")
async def get_episode_order_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SyncJob).where(SyncJob.id == job_id, SyncJob.user_id == current_user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{series_tmdb_id}/episode-order")
async def set_show_episode_order(
    series_tmdb_id: int,
    body: EpisodeOrderRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        selected_order = validate_episode_order(body.episode_order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if selected_order == "tvdb":
        # Building the TVDB mapping fans out one TMDB request per episode and can
        # take minutes for long-running shows — always run it in the background so
        # the request never risks hitting the reverse proxy's read timeout.
        tmdb_api_key, tvdb_api_key = await asyncio.gather(
            get_user_tmdb_key(db, current_user.id),
            get_user_tvdb_key(db, current_user.id),
        )
        if not check_tmdb_key(tmdb_api_key):
            raise HTTPException(status_code=400, detail="TMDB API key not configured")
        if not tvdb_api_key:
            raise HTTPException(status_code=400, detail="TVDB API key not configured")

        job = SyncJob(
            user_id=current_user.id,
            source=CollectionSource.tmdb,
            job_type="episode_order",
            status=SyncStatus.pending,
            stats={"series_tmdb_id": series_tmdb_id},
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        background_tasks.add_task(
            _run_episode_order_mapping,
            current_user.id, job.id, series_tmdb_id, tmdb_api_key, tvdb_api_key, body.force_refresh,
        )
        return {"status": "started", "job_id": job.id}

    preference = await get_episode_order(db, current_user.id, series_tmdb_id)
    if preference:
        preference.episode_order = selected_order
    else:
        db.add(UserShowEpisodeOrder(
            user_id=current_user.id,
            series_tmdb_id=series_tmdb_id,
            episode_order=selected_order,
            tvdb_id=None,
        ))

    await db.commit()
    return {
        "episode_order": selected_order,
        "series_tmdb_id": series_tmdb_id,
        "tvdb_id": None,
        "mapping": None,
        "redirect": f"/show/{series_tmdb_id}",
    }


@router.get("/{series_tmdb_id}/episode-order/job")
async def get_active_episode_order_job(
    series_tmdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Look up an in-flight TVDB mapping job for this show, if any — lets the
    page recover its progress after a refresh instead of losing track of it."""
    result = await db.execute(
        select(SyncJob)
        .where(
            SyncJob.user_id == current_user.id,
            SyncJob.job_type == "episode_order",
            SyncJob.status.in_([SyncStatus.pending, SyncStatus.running]),
            SyncJob.stats["series_tmdb_id"].astext == str(series_tmdb_id),
        )
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()

# Show id -> monotonic time its TMDB season list was last refreshed for Progress.
_PROGRESS_META_REFRESHED: dict[int, float] = {}
_PROGRESS_META_TTL = 6 * 60 * 60


async def _refresh_airing_show_meta(db: AsyncSession, user_id: int, shows) -> None:
    """Bring the stored TMDB season list up to date for shows still airing.

    Progress counts come from Show.tmdb_data, which is only written when a show
    is synced or opened. For a show that is still airing that copy goes stale:
    a new season is missing and the latest season's last aired episode is old,
    so the totals come out short. Refresh those shows (at most every 6 hours).
    """
    now = time.monotonic()
    recent_cutoff = (date.today() - timedelta(days=90)).isoformat()
    stale = [
        show for show in shows
        if show.tmdb_id
        and now - _PROGRESS_META_REFRESHED.get(show.id, float("-inf")) > _PROGRESS_META_TTL
        and (
            (show.status or "").strip().lower() not in {"ended", "canceled", "cancelled"}
            or str(show.last_air_date or "")[:10] >= recent_cutoff
        )
    ]
    if not stale:
        return
    try:
        api_key = await get_user_tmdb_key(db, user_id)
    except Exception:
        return
    if not check_tmdb_key(api_key):
        return

    gate = asyncio.Semaphore(8)

    async def fetch(show):
        async with gate:
            try:
                return show, await tmdb.get_show_light(show.tmdb_id, api_key=api_key)
            except Exception:
                return show, None

    changed = False
    for show, data in await asyncio.gather(*(fetch(show) for show in stale)):
        if not data or not data.get("seasons"):
            continue
        _PROGRESS_META_REFRESHED[show.id] = now
        old_seasons = {
            s.get("season_number"): s
            for s in (show.tmdb_data or {}).get("seasons", []) or []
            if isinstance(s, dict)
        }
        seasons = [
            {
                **old_seasons.get(s["season_number"], {}),
                "season_number": s["season_number"],
                "poster_path": tmdb.poster_url(s.get("poster_path"))
                or old_seasons.get(s["season_number"], {}).get("poster_path"),
                "episode_count": s.get("episode_count"),
                "name": s.get("name"),
                "air_date": s.get("air_date"),
                "overview": s.get("overview"),
            }
            for s in data["seasons"]
        ]
        show.status = data.get("status") or show.status
        show.last_air_date = data.get("last_air_date") or show.last_air_date
        show.tmdb_data = {
            **(show.tmdb_data or {}),
            "last_episode_to_air": data.get("last_episode_to_air"),
            "next_episode_to_air": data.get("next_episode_to_air"),
            "seasons": seasons,
        }
        changed = True
    if changed:
        await db.commit()


@router.get("/progress")
async def list_progress_shows(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List shows the user has started watching, with progress data."""

    # Find shows where the user has completed at least one episode.
    watched_show_ids = (
        select(Media.show_id)
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.completed.is_(True),
            Media.media_type == MediaType.episode,
            Media.show_id.isnot(None),
            Media.season_number.isnot(None),
            Media.season_number != 0,
            Media.episode_number.isnot(None),
        )
        .distinct()
        .subquery()
    )

    result = await db.execute(
        select(ShowModel)
        .where(ShowModel.id.in_(select(watched_show_ids)))
        .order_by(func.lower(ShowModel.title).asc())
    )

    shows = result.scalars().all()

    if not shows:
        return {
            "results": [],
            "total_results": 0,
        }

    await _refresh_airing_show_meta(db, current_user.id, shows)

    show_ids = [show.id for show in shows]

    # Get every episode belonging to these shows.
    episode_result = await db.execute(
        select(Media)
        .where(
            Media.show_id.in_(show_ids),
            Media.media_type == MediaType.episode,
            Media.season_number.isnot(None),
            Media.season_number != 0,
            Media.episode_number.isnot(None),
        )
        .order_by(
            Media.show_id,
            Media.season_number,
            Media.episode_number,
        )
    )

    episodes = episode_result.scalars().all()

    # Get the local Media IDs for episodes completed by this user.
    # WatchEvent.media_id is the direct, reliable relationship.
    watched_result = await db.execute(
        select(Media.id)
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.completed.is_(True),
            Media.media_type == MediaType.episode,
        )
        .distinct()
    )

    watched_ids = set(watched_result.scalars().all())

    # Get the most recent completed watch time for each show.
    last_watched_result = await db.execute(
        select(
            Media.show_id,
            func.max(WatchEvent.watched_at),
        )
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == current_user.id,
            WatchEvent.completed.is_(True),
            Media.media_type == MediaType.episode,
            Media.show_id.in_(show_ids),
        )
        .group_by(Media.show_id)
    )

    last_watched_by_show = {
        show_id: watched_at
        for show_id, watched_at in last_watched_result.all()
    }

    # Watching date range and sources per show, in one query each rather than per show.
    show_watch_filters = (
        WatchEvent.user_id == current_user.id,
        WatchEvent.completed == True,
        Media.show_id.in_(show_ids),
        Media.media_type == MediaType.episode,
        WatchEvent.watched_at.isnot(None),
    )
    watch_dates_result = await db.execute(
        select(Media.show_id, func.min(WatchEvent.watched_at), func.max(WatchEvent.watched_at))
        .join(Media, Media.id == WatchEvent.media_id)
        .where(*show_watch_filters)
        .group_by(Media.show_id)
    )
    watch_dates_by_show = {
        show_id: (first, last) for show_id, first, last in watch_dates_result.all()
    }
    watch_sources_result = await db.execute(
        select(Media.show_id, WatchEvent.watch_source)
        .join(Media, Media.id == WatchEvent.media_id)
        .where(*show_watch_filters, WatchEvent.watch_source.isnot(None))
        .distinct()
    )
    watch_sources_by_show = defaultdict(set)
    for show_id, source in watch_sources_result.all():
        if source:
            watch_sources_by_show[show_id].add(source)

    # Only consult TVMaze for episodes scheduled today whose local catalog
    # entry has a date but no precise airing timestamp. TVMaze timestamps are
    # converted to Malta time by the shared calendar helper.
    now_malta = datetime.now(MALTA_TZ)
    today_malta = now_malta.date()
    today_iso = today_malta.isoformat()
    adjacent_malta_days = {
        today_malta,
        today_malta - timedelta(days=1),
    }
    schedule_show_ids = set()
    schedulable_statuses = {
        "returning series",
        "in production",
        "planned",
        "pilot",
    }
    for ep in episodes:
        if ep.release_date and str(ep.release_date)[:10] in {
            today_iso,
            (today_malta - timedelta(days=1)).isoformat(),
        }:
            schedule_show_ids.add(ep.show_id)
        if ep.first_aired_at:
            stored_airtime = ep.first_aired_at
            if stored_airtime.tzinfo is None:
                stored_airtime = stored_airtime.replace(tzinfo=timezone.utc)
            if stored_airtime.astimezone(MALTA_TZ).date() in adjacent_malta_days:
                schedule_show_ids.add(ep.show_id)
    for show in shows:
        next_episode = (show.tmdb_data or {}).get("next_episode_to_air") or {}
        try:
            next_air_day = date.fromisoformat(str(next_episode.get("air_date"))[:10])
        except (TypeError, ValueError):
            next_air_day = None
        # TMDB date-only values may reflect the broadcaster's US calendar
        # date while the actual airtime falls on the next day in Malta.
        # Include yesterday when looking up today's Malta-local schedule.
        if (
            (show.status or "").strip().lower() in schedulable_statuses
            or (
                next_air_day is not None
                and next_air_day >= today_malta - timedelta(days=1)
            )
        ):
            schedule_show_ids.add(show.id)
    schedule_semaphore = asyncio.Semaphore(8)

    async def fetch_progress_schedule(show):
        async with schedule_semaphore:
            return show.id, await get_tvmaze_episodes(
                show.title,
                today_malta,
                date.max,
            )

    schedules = await asyncio.gather(*(
        fetch_progress_schedule(show)
        for show in shows
        if show.id in schedule_show_ids
    ))
    schedules_by_show = {
        show_id: {
            (int(ep["season"]), int(ep["episode"])): ep.get("air_datetime")
            for ep in scheduled
            if ep.get("season") is not None and ep.get("episode") is not None
        }
        for show_id, scheduled in schedules
    }
    scheduled_seasons_by_show = {
        show_id: {season_number for season_number, _episode_number in schedule}
        for show_id, schedule in schedules_by_show.items()
    }
    # TMDB's next_episode_to_air is also a useful signal when TVMaze has no
    # matching listing. Preserve the upcoming season's local aired episodes
    # instead of letting stale season-size metadata truncate them.
    for show in shows:
        next_episode = (show.tmdb_data or {}).get("next_episode_to_air") or {}
        try:
            next_air_day = date.fromisoformat(
                str(next_episode.get("air_date"))[:10]
            )
            next_season_number = int(next_episode["season_number"])
        except (KeyError, TypeError, ValueError):
            continue
        if next_air_day >= today_malta and next_season_number > 0:
            scheduled_seasons_by_show.setdefault(show.id, set()).add(
                next_season_number
            )

    # Build the response.
    show_data = []

    def episode_runtime(ep):
        if ep.runtime:
            return int(ep.runtime)

        tmdb_runtime = (ep.tmdb_data or {}).get("runtime")
        if tmdb_runtime:
            return int(tmdb_runtime)

        return 0

    episodes_by_show_id = defaultdict(list)
    for ep in episodes:
        episodes_by_show_id[ep.show_id].append(ep)

    for show in shows:
        # The local episode table can contain extras or stale records. Use
        # stored season sizes to constrain those rows, unless a precise
        # schedule shows that the cached size for a season may be stale.
        schedulable_statuses = {
            "returning series",
            "in production",
            "planned",
            "pilot",
        }
        is_schedulable_show = (
            (show.status or "").strip().lower() in schedulable_statuses
        )
        season_ep_counts = {
            int(s["season_number"]): int(s.get("episode_count", 0))
            for s in (show.tmdb_data or {}).get("seasons", [])
            if s.get("season_number") is not None
            and int(s["season_number"]) > 0
            and int(s.get("episode_count", 0) or 0) > 0
        }

        def has_aired(ep) -> bool:
            # Use the same precise U.S. broadcast schedule as Next Up first,
            # converted to Malta time. It must override stale dates or stored
            # timestamps that would otherwise make a future episode look aired.
            scheduled_at = schedules_by_show.get(show.id, {}).get(
                (int(ep.season_number), int(ep.episode_number))
            )
            if scheduled_at is not None:
                if scheduled_at.tzinfo is None:
                    scheduled_at = scheduled_at.replace(tzinfo=MALTA_TZ)
                return scheduled_at.astimezone(MALTA_TZ) <= now_malta

            try:
                release_day = (
                    date.fromisoformat(str(ep.release_date)[:10])
                    if ep.release_date
                    else None
                )
            except (TypeError, ValueError):
                release_day = None

            # Fall back to the stored Trakt timestamp when the schedule has no
            # entry for this episode. Historical naive values are UTC. If that
            # timestamp conflicts with a release date several Malta days in
            # the past, prefer the unambiguous past date instead of letting a
            # stale future timestamp drop an episode that has already aired.
            if ep.first_aired_at:
                aired_at = ep.first_aired_at
                if aired_at.tzinfo is None:
                    aired_at = aired_at.replace(tzinfo=timezone.utc)
                aired_at = aired_at.astimezone(MALTA_TZ)
                if aired_at <= now_malta:
                    return True
                if release_day and release_day < today_malta - timedelta(days=1):
                    return True
                return False

            # U.S. date-only releases can be a day behind Malta. Only use an
            # exact converted schedule for the adjacent-day boundary.
            if release_day and release_day < today_malta - timedelta(days=1):
                return True
            if release_day and release_day > today_malta + timedelta(days=1):
                return False

            if not ep.release_date:
                ended_statuses = {"ended", "canceled", "cancelled"}
                if (show.status or "").strip().lower() not in ended_statuses:
                    return False
                try:
                    last_air_day = date.fromisoformat(
                        str(show.last_air_date)[:10]
                    )
                except (TypeError, ValueError):
                    return False
                return last_air_day < today_malta - timedelta(days=1)
            return False

        # Collapse duplicate local records by episode position. If one copy is
        # watched, prefer it so imported watch history is never lost.
        episodes_by_position = {}
        for ep in episodes_by_show_id.get(show.id, ()):
            season_number = int(ep.season_number)
            episode_number = int(ep.episode_number)
            canonical_season_count = season_ep_counts.get(season_number)
            # A watched episode is never an extra: TMDB sometimes numbers a
            # season shorter than the broadcast order the user watched in.
            if (
                canonical_season_count
                and episode_number > canonical_season_count
                and ep.id not in watched_ids
                and not is_schedulable_show
                and season_number not in scheduled_seasons_by_show.get(show.id, set())
            ):
                continue
            position = (season_number, episode_number)
            current = episodes_by_position.get(position)
            if current is None or (
                has_aired(ep) and not has_aired(current)
            ) or (
                has_aired(ep) == has_aired(current)
                and ep.id in watched_ids and current.id not in watched_ids
            ) or (
                has_aired(ep) == has_aired(current)
                and (ep.id in watched_ids) == (current.id in watched_ids)
                and not episode_runtime(current)
                and episode_runtime(ep)
            ):
                episodes_by_position[position] = ep

        all_show_episodes = list(episodes_by_position.values())
        # A completed watch event is definitive proof that the user had access
        # to the episode. Keep it in Progress even if stale airing metadata or
        # a mismatched schedule incorrectly labels that watched episode as
        # future; otherwise the episode page and Progress disagree.
        show_episodes = [
            ep for ep in all_show_episodes
            if has_aired(ep) or ep.id in watched_ids
        ]
        local_season_counts = {}
        for ep in show_episodes:
            season_number = int(ep.season_number)
            local_season_counts[season_number] = (
                local_season_counts.get(season_number, 0) + 1
            )
        season_air_dates = {
            int(season["season_number"]): season.get("air_date")
            for season in (show.tmdb_data or {}).get("seasons", [])
            if season.get("season_number") is not None
            and int(season["season_number"]) > 0
        }
        tmdb_data = show.tmdb_data or {}
        last_episode = tmdb_data.get("last_episode_to_air") or {}
        next_episode = tmdb_data.get("next_episode_to_air") or {}

        # TMDB's last_episode_to_air can lag behind an overnight release.
        # Use a precise TVMaze airtime for next_episode_to_air when available
        # so Progress counts the episode as soon as it has aired in Malta.
        aired_through: dict[int, int] = {}

        def record_aired_position(episode_data: dict) -> None:
            try:
                season_number = int(episode_data["season_number"])
                episode_number = int(episode_data["episode_number"])
            except (KeyError, TypeError, ValueError):
                return
            if season_number > 0 and episode_number > 0:
                aired_through[season_number] = max(
                    aired_through.get(season_number, 0), episode_number
                )

        # TVMaze schedule timestamps represent the U.S. broadcast moment in
        # an explicit timezone and are converted to Malta time by the shared
        # helper. Count any returned episode whose U.S. airtime has passed,
        # even when TMDB's cached next/last episode fields are stale.
        for position, scheduled_at in schedules_by_show.get(show.id, {}).items():
            if scheduled_at is None:
                continue
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=MALTA_TZ)
            if scheduled_at.astimezone(MALTA_TZ) <= now_malta:
                record_aired_position({
                    "season_number": position[0],
                    "episode_number": position[1],
                })

        # TMDB's last_episode_to_air can itself be stale or point at an
        # episode whose U.S. release date is today/tomorrow. Trust it only
        # when no exact TVMaze schedule exists and its date is safely in the
        # past relative to Malta. Exact schedule timestamps were handled above.
        try:
            last_episode_position = (
                int(last_episode["season_number"]),
                int(last_episode["episode_number"]),
            )
            last_air_day = date.fromisoformat(
                str(last_episode.get("air_date"))[:10]
            )
        except (KeyError, TypeError, ValueError):
            last_episode_position = None
            last_air_day = None
        if (
            last_episode_position
            and last_episode_position not in schedules_by_show.get(show.id, {})
            and last_air_day
            and last_air_day < today_malta - timedelta(days=1)
        ):
            record_aired_position(last_episode)

        future_scheduled_seasons = {
            season_number
            for (season_number, _episode_number), scheduled_at
            in schedules_by_show.get(show.id, {}).items()
            if scheduled_at is not None
            and (
                scheduled_at.replace(tzinfo=MALTA_TZ)
                if scheduled_at.tzinfo is None
                else scheduled_at.astimezone(MALTA_TZ)
            ) > now_malta
        }
        try:
            next_air_day = date.fromisoformat(str(next_episode.get("air_date"))[:10])
        except (TypeError, ValueError):
            next_air_day = None

        next_position = None
        try:
            next_position = (
                int(next_episode["season_number"]),
                int(next_episode["episode_number"]),
            )
        except (KeyError, TypeError, ValueError):
            pass

        if next_air_day and next_air_day >= today_malta and next_position:
            future_scheduled_seasons.add(next_position[0])

        next_episode_has_aired = bool(
            next_air_day and next_air_day < today_malta - timedelta(days=1)
        )
        if next_position and next_air_day in {
            today_malta,
            today_malta - timedelta(days=1),
        }:
            scheduled_at = schedules_by_show.get(show.id, {}).get(next_position)
            if scheduled_at is not None:
                if scheduled_at.tzinfo is None:
                    scheduled_at = scheduled_at.replace(tzinfo=MALTA_TZ)
                next_episode_has_aired = scheduled_at.astimezone(MALTA_TZ) <= now_malta
        if next_position and next_episode_has_aired:
            record_aired_position(next_episode)

        # Use metadata counts for aired seasons as well as local episode rows.
        # The local catalog can be incomplete (especially for older seasons),
        # but absent rows are still unwatched episodes and must count toward
        # the user's progress.
        effective_season_counts: dict[int, int] = {}
        ended_statuses = {"ended", "canceled", "cancelled"}
        show_ended = (show.status or "").strip().lower() in ended_statuses
        latest_aired_season = max(aired_through, default=0)
        for season_number in set(season_ep_counts) | set(local_season_counts):
            metadata_count = season_ep_counts.get(season_number, 0)
            local_count = local_season_counts.get(season_number, 0)
            expected_count = 0

            if season_number in aired_through:
                # The schedule is the freshest source for an actively airing
                # season. A stale season episode_count must not cap it.
                expected_count = max(
                    local_count,
                    aired_through[season_number],
                )
            elif season_number in future_scheduled_seasons:
                # A season with a precise future U.S. broadcast must not be
                # treated as fully released just because stale season metadata
                # has an old air date. Count only episodes known to have aired.
                expected_count = local_count
            elif latest_aired_season and season_number < latest_aired_season:
                expected_count = metadata_count
            else:
                try:
                    season_first_air = date.fromisoformat(
                        str(season_air_dates.get(season_number))[:10]
                    )
                except (TypeError, ValueError):
                    season_first_air = None

                # A fully historic season has completed; its metadata gives
                # the correct total even when some episode rows are absent.
                if season_first_air and season_first_air < today_malta - timedelta(days=1):
                    expected_count = metadata_count
                elif show_ended and (
                    season_first_air is None or season_first_air <= today_malta
                ):
                    expected_count = metadata_count

            effective_count = max(local_count, expected_count)
            if effective_count > 0:
                effective_season_counts[season_number] = effective_count

        season_numbers = set(effective_season_counts)

        has_upcoming_episodes = any(
            not has_aired(ep) for ep in all_show_episodes
        )
        if next_air_day and next_air_day > today_malta:
            has_upcoming_episodes = True
        elif next_air_day in {today_malta, today_malta - timedelta(days=1)}:
            scheduled_at = schedules_by_show.get(show.id, {}).get(next_position)
            if scheduled_at is not None and scheduled_at > now_malta:
                has_upcoming_episodes = True

        # Returning shows stay in Progress when the user has watched every
        # aired episode. Future episodes remain excluded from counts; this
        # flag keeps the caught-up show discoverable until its run ends.
        if (show.status or "").strip().lower() in {
            "returning series",
            "in production",
        }:
            has_upcoming_episodes = True

        total_count = sum(effective_season_counts.values())

        watched_episodes = [
            ep for ep in show_episodes
            if ep.id in watched_ids
        ]

        watched_positions_by_season: dict[int, set[int]] = {}
        for ep in watched_episodes:
            season_number = int(ep.season_number)
            episode_number = int(ep.episode_number)
            if episode_number <= effective_season_counts.get(season_number, 0):
                watched_positions_by_season.setdefault(season_number, set()).add(
                    episode_number
                )
        watched_count = sum(
            len(positions) for positions in watched_positions_by_season.values()
        )
        remaining_count = max(total_count - watched_count, 0)

        watched_runtime = sum(
            episode_runtime(ep)
            for ep in watched_episodes
        )

        # Unwatched episodes may not have individual runtime metadata yet.
        # Estimate those from known episode runtimes (or the show's published
        # episode_run_time) so missing data never turns real remaining time
        # into a misleading zero.
        known_runtimes = [
            episode_runtime(ep)
            for ep in all_show_episodes
            if episode_runtime(ep) > 0
        ]
        if not known_runtimes:
            show_runtimes = (show.tmdb_data or {}).get("episode_run_time") or []
            known_runtimes = [
                int(runtime)
                for runtime in show_runtimes
                if isinstance(runtime, (int, float)) and runtime > 0
            ]
        estimated_episode_runtime = (
            sorted(known_runtimes)[len(known_runtimes) // 2]
            if known_runtimes
            else None
        )
        unwatched_episodes = [
            ep for ep in show_episodes if ep.id not in watched_ids
        ]
        missing_episode_count = sum(
            max(
                0,
                effective_season_counts.get(season_number, 0)
                - local_season_counts.get(season_number, 0),
            )
            for season_number in effective_season_counts
        )
        missing_unwatched_runtime = any(
            episode_runtime(ep) <= 0 for ep in unwatched_episodes
        ) or missing_episode_count > 0
        cannot_estimate_runtime = (
            estimated_episode_runtime is None
            and (
                missing_episode_count > 0
                or any(episode_runtime(ep) <= 0 for ep in unwatched_episodes)
            )
        )
        remaining_runtime = (
            None
            if cannot_estimate_runtime
            else sum(
                episode_runtime(ep) or estimated_episode_runtime or 0
                for ep in unwatched_episodes
            ) + missing_episode_count * (estimated_episode_runtime or 0)
        )
        total_runtime = watched_runtime + (remaining_runtime or 0)
        remaining_runtime_estimated = bool(
            missing_unwatched_runtime and estimated_episode_runtime
        )
        watch_pct = (
            # Rounded down, and never 0% or 100% while partly watched, so a
            # long show one episode short does not read as finished.
            max(1, min(99, watched_count * 100 // total_count))
            if 0 < watched_count < total_count
            else watched_count * 100 // total_count if total_count
            else 0
        )

        # Group episodes into seasons.
        seasons = {}
        season_states = {}

        for ep in show_episodes:
            season_number = int(ep.season_number)
            is_watched = ep.id in watched_ids

            if season_number not in seasons:
                seasons[season_number] = []

            seasons[season_number].append({
                "id": ep.id,
                "tmdb_id": ep.tmdb_id,
                "title": ep.title,
                "season": season_number,
                "episode": int(ep.episode_number),
                "runtime": ep.runtime,
                "watched": is_watched,
                "poster_path": ep.poster_path,
                "backdrop_path": ep.backdrop_path,
            })

        for season_number in season_numbers:
            season_total = effective_season_counts.get(season_number, 0)
            season_watched = len(watched_positions_by_season.get(season_number, set()))

            season_states[season_number] = {
                "watched_count": season_watched,
                "episode_count": season_total,
                "has_aired": True,
                "watch_pct": (
                    max(1, min(99, season_watched * 100 // season_total))
                    if 0 < season_watched < season_total
                    else season_watched * 100 // season_total if season_total
                    else 0
                ),
            }

        show_info = format_show(show)

        # Poster of the season the user is up to, like the Up Next cards: the
        # season of the furthest watched episode, or the next season once that
        # one is finished.
        current_season = None
        if watched_positions_by_season:
            current_season = max(watched_positions_by_season)
            if (
                max(watched_positions_by_season[current_season])
                >= effective_season_counts.get(current_season, 0)
            ):
                current_season = min(
                    (n for n in effective_season_counts if n > current_season),
                    default=current_season,
                )
        season_poster = next(
            (
                s.get("poster_path")
                for s in tmdb_data.get("seasons", []) or []
                if isinstance(s, dict) and s.get("season_number") == current_season
            ),
            None,
        )
        show_info["season_poster_path"] = (
            season_poster
            if isinstance(season_poster, str) and season_poster.startswith("http")
            else tmdb.poster_url(season_poster)
        )

        # Watching dates + source
        first_watched, last_watched = watch_dates_by_show.get(show.id, (None, None))

        show_info["watch_start_date"] = (
            first_watched.date().isoformat() if first_watched else None
        )
        show_info["watch_end_date"] = (
            last_watched.date().isoformat() if last_watched else None
        )

        watch_sources = sorted(watch_sources_by_show.get(show.id, ()), key=str)

        show_info["watch_sources"] = watch_sources

        show_info.update({
            "episode_count": total_count,
            "watched_count": watched_count,
            "remaining_count": remaining_count,
            "last_watched_at": (
                last_watched_by_show.get(show.id).isoformat()
                if last_watched_by_show.get(show.id)
                else None
            ),
            "total_runtime": total_runtime,
            "watched_runtime": watched_runtime,
            "remaining_runtime": remaining_runtime,
            "remaining_runtime_estimated": remaining_runtime_estimated,
            "has_upcoming_episodes": has_upcoming_episodes,
            "watch_pct": watch_pct,
            "seasons": seasons,
            "season_states": season_states,
        })

        show_data.append(show_info)

    return {
        "results": show_data,
        "total_results": len(show_data),
    }

@router.get("/{series_tmdb_id}")
async def get_show(
    series_tmdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Try to find locally
    show_result = await db.execute(
        select(ShowModel).where(ShowModel.tmdb_id == series_tmdb_id)
    )
    show = show_result.scalar_one_or_none()
    order_preference = await get_episode_order(db, current_user.id, series_tmdb_id)
    # Your discs of the series (its season sets), for "On disc".
    from core.physical import title_discs
    discs = await title_discs(db, current_user.id, series_tmdb_id, "tv")
    selected_episode_order = order_preference.episode_order if order_preference else "tmdb"

    if show:
        # Fetch local episodes
        episodes_result = await db.execute(
            select(Media)
            .where(Media.media_type == MediaType.episode)
            .where(Media.show_id == show.id)
            .order_by(Media.season_number.asc(), Media.episode_number.asc())
        )
        episodes = episodes_result.scalars().all()

        seasons_meta = {
            s["season_number"]: s for s in (show.tmdb_data or {}).get("seasons", [])
        }

        seasons: dict = {}
        for ep in episodes:
            s_num = ep.season_number or 0
            season_poster = (
                seasons_meta.get(s_num, {}).get("poster_path") or show.poster_path
            )
            ep_formatted = format_media(ep)
            ep_formatted["poster_path"] = ep.poster_path or season_poster
            seasons.setdefault(s_num, []).append(ep_formatted)

        # Fetch networks + recommendations from TMDB if key is available
        networks = []
        recommendations = []
        cast = []
        awards = []
        tmdb_extra: dict | None = None
        api_key = await get_user_tmdb_key(db, current_user.id)
        tvdb_api_key = await get_user_tvdb_key(db, current_user.id)
        metadata_lang = await get_user_metadata_language(db, current_user.id)
        tmdb_show_task = (
            asyncio.create_task(
                tmdb.get_show(
                    series_tmdb_id,
                    api_key=api_key,
                    language=metadata_lang,
                )
            )
            if check_tmdb_key(api_key)
            else None
        )

        tvdb_genres = []
        if tvdb_api_key and show.tvdb_id:
            try:
                tvdb_raw = await tvdb_client.get_series(
                    show.tvdb_id,
                    tvdb_api_key,
                )
                tvdb_formatted = tvdb_client.format_series(
                    tvdb_raw,
                    language=tvdb_client.tvdb_language(metadata_lang),
                )
                tvdb_genres = [
                    g
                    for g in tvdb_formatted.get("genres", [])
                    if g.lower() not in {"family", "kids", "children"}
                ]
            except Exception as e:
                print(f"TVDB genre fetch failed for {show.tvdb_id}: {e}")

        if check_tmdb_key(api_key):
            try:
                tmdb_extra = await tmdb_show_task

                production_countries = [
                    {
                        "iso_3166_1": c.get("iso_3166_1"),
                        "name": c.get("name"),
                    }
                    for c in tmdb_extra.get("production_countries", [])
                ]

                
                networks = [
                    {
                        "id": n["id"],
                        "name": n["name"],
                        "logo_path": tmdb.poster_url(n.get("logo_path"), size="w500")
                        if n.get("logo_path")
                        else None,
                        "origin_country": n.get("origin_country"),
                    }
                    for n in tmdb_extra.get("networks", [])
                ]
                recommendations = [
                    {
                        "id": None,
                        "tmdb_id": r["id"],
                        "type": "series",
                        "title": r.get("name") or r.get("title"),
                        "original_title": r.get("original_name")
                        or r.get("original_title"),
                        "overview": r.get("overview"),
                        "poster_path": tmdb.poster_url(r.get("poster_path")),
                        "backdrop_path": tmdb.poster_url(
                            r.get("backdrop_path"), size="w1280"
                        ),
                        "release_date": r.get("first_air_date")
                        or r.get("release_date"),
                        "tmdb_rating": r.get("vote_average"),
                        "adult": r.get("adult", False),
                    }
                    for r in tmdb_extra.get("recommendations", {}).get("results", [])[
                        :12
                    ]
                ]
                await enrich_with_state(db, current_user.id, recommendations)

                cast, guest_stars = await _show_cast(show, tmdb_extra, api_key, db)

                if metadata_lang:
                    try:
                        await upsert_show_translation(
                            db, show.id, metadata_lang,
                            tmdb_extra.get("name"),
                            tmdb_extra.get("overview"),
                            tmdb_extra.get("tagline"),
                            tmdb_extra.get("poster_path"),
                        )
                        await db.commit()
                    except Exception:
                        pass
            except Exception:
                pass

        state_item: dict = {"tmdb_id": series_tmdb_id, "type": "series"}
        # Pass last_episode_to_air from the already-fetched tmdb_extra so enrich_with_state
        # doesn't make a redundant second TMDB call for the same data.
        if tmdb_extra and tmdb_extra.get("last_episode_to_air"):
            state_item["_last_episode_to_air"] = tmdb_extra["last_episode_to_air"]
        await enrich_with_state(db, current_user.id, [state_item])

        # --- Per-season states ---
        season_states: dict = {}

        # Collected and watched episode counts per season in one query
        coll_a  = aliased(Collection)
        watch_a = aliased(WatchEvent)
        season_stats_q = await db.execute(
            select(
                Media.season_number,
                func.count(func.distinct(
                    case((coll_a.id.isnot(None), Media.episode_number), else_=None)
                )).label("collected"),
                func.count(func.distinct(
                    case((watch_a.id.isnot(None), Media.episode_number), else_=None)
                )).label("watched"),
            )
            .outerjoin(coll_a, and_(coll_a.media_id == Media.id, coll_a.user_id == current_user.id))
            .outerjoin(watch_a, and_(watch_a.media_id == Media.id, watch_a.user_id == current_user.id))
            .where(
                Media.show_id == show.id,
                Media.media_type == MediaType.episode,
                Media.season_number.isnot(None),
                Media.episode_number.isnot(None),
            )
            .group_by(Media.season_number)
        )
        coll_per_season: dict = {}
        watched_per_season: dict = {}
        for sn, collected, watched in season_stats_q.all():
            coll_per_season[sn] = collected
            watched_per_season[sn] = watched

        # Season user ratings (stored against the show's Media row with season_number)
        show_media_q = await db.execute(
            select(Media).where(Media.tmdb_id == series_tmdb_id, Media.media_type == MediaType.series)
        )
        show_media = show_media_q.scalar_one_or_none()

        # Show-level user rating
        show_user_rating = None
        if show_media:
            rating_q = await db.execute(
                select(Rating.rating)
                .where(
                    Rating.media_id == show_media.id,
                    Rating.user_id == current_user.id,
                    Rating.season_number.is_(None),
                    Rating.episode_order.is_(None),
                )
            )
            show_user_rating = rating_q.scalar_one_or_none()

        if show_media and not show_media.adult and (tmdb_extra or {}).get("adult", False):
            show_media.adult = True
            await db.commit()
        season_ratings: dict = {}
        if show_media:
            ratings_q = await db.execute(
                select(Rating.season_number, func.max(Rating.rating))
                .where(
                    Rating.media_id == show_media.id,
                    Rating.user_id == current_user.id,
                    Rating.season_number.isnot(None),
                    Rating.episode_order.is_(None),
                )
                .group_by(Rating.season_number)
            )
            season_ratings = dict(ratings_q.all())

        # Episode counts per season from stored TMDB metadata
        season_ep_counts: dict = {
            s["season_number"]: s.get("episode_count", 0)
            for s in (show.tmdb_data or {}).get("seasons", [])
        }

        # For shows that are still airing, adjust the counts to only include aired episodes
        last_ep = (tmdb_extra or show.tmdb_data or {}).get("last_episode_to_air")
        if last_ep:
            last_sn = last_ep.get("season_number")
            last_en = last_ep.get("episode_number")
            if last_sn in season_ep_counts:
                # Capped at the last aired episode number for the current season
                season_ep_counts[last_sn] = last_en
            # Future seasons have 0 aired episodes
            for sn in season_ep_counts:
                if sn > last_sn:
                    season_ep_counts[sn] = 0

        # Seasons you own on disc are fully collected.
        from core.physical import season_discs
        owned_on_disc = await season_discs(db, current_user.id, series_tmdb_id)

        # Build season states for all known seasons
        for sn in set(list(coll_per_season.keys()) + list(season_ep_counts.keys())):
            collected = coll_per_season.get(sn, 0)
            watched = watched_per_season.get(sn, 0)
            total = season_ep_counts.get(sn, 0)
            if sn in owned_on_disc:
                collected = max(collected, total)
            
            # Use distinct (season, episode) from user's collection for calculation
            # to be consistent with how total is calculated (unique episodes in season).
            season_states[sn] = {
                # The disc holding this season, when you own it.
                "disc_id": owned_on_disc.get(sn),
                "in_library": collected > 0,
                "collection_pct": min(100, int((collected / total) * 100)) if total > 0 else 0,
                "watched": watched >= total if total > 0 else False,
                # Rounded down, and never 0% or 100% while partly watched.
                "watch_pct": (
                    max(1, min(99, watched * 100 // total)) if 0 < watched < total
                    else min(100, watched * 100 // total) if total > 0
                    else 0
                ),
                "watched_count": min(watched, total) if total > 0 else watched,
                "episode_count": total,  # aired so far
                "user_rating": season_ratings.get(sn),
            }

        # Enhance seasons_meta with live TMDB data (id, rating, overview, air_date)
        tmdb_season_map: dict = {}
        if tmdb_extra:
            tmdb_season_map = {s["season_number"]: s for s in tmdb_extra.get("seasons", [])}
        base_seasons_meta = (show.tmdb_data or {}).get("seasons", [])
        enhanced_seasons_meta = [
            {
                **s,
                "tmdb_season_id": tmdb_season_map.get(s["season_number"], {}).get("id"),
                "tmdb_rating": tmdb_season_map.get(s["season_number"], {}).get("vote_average"),
                # Prefer live TMDB (translated) overview; fall back to DB value
                "overview": tmdb_season_map.get(s["season_number"], {}).get("overview") or s.get("overview"),
                "air_date": s.get("air_date") or tmdb_season_map.get(s["season_number"], {}).get("air_date"),
            }
            for s in base_seasons_meta
        ]

        where_to_watch = await get_where_to_watch(
            db, current_user.id, series_tmdb_id, MediaType.series, show=show, tmdb_key=api_key
        )

        # Overlay episode translations for the seasons dict
        if metadata_lang:
            all_ep_ids = [ep["id"] for ep_list in seasons.values() for ep in ep_list if ep.get("id")]
            if all_ep_ids:
                ep_trans = await get_media_translations(db, all_ep_ids, metadata_lang)
                for ep_list in seasons.values():
                    apply_media_translations(ep_list, ep_trans)

                # First and last time the user watched this show
                watch_dates_q = await db.execute(
                    select(
                        func.min(WatchEvent.watched_at),
                        func.max(WatchEvent.watched_at),
                    )
                    .join(Media, Media.id == WatchEvent.media_id)
                    .join(ShowModel, ShowModel.id == Media.show_id)
                    .where(
                        WatchEvent.user_id == current_user.id,
                        WatchEvent.completed.is_(True),
                        ShowModel.tmdb_id == series_tmdb_id,
                        Media.media_type == MediaType.episode,
                        Media.season_number.isnot(None),
                        Media.episode_number.isnot(None),
                    )
                )
                watch_start_date, watch_end_date = watch_dates_q.one()
                # First and last time the user watched this show
                watch_dates_q = await db.execute(
                    select(
                        func.min(WatchEvent.watched_at),
                        func.max(WatchEvent.watched_at),
                    )
                    .join(Media, Media.id == WatchEvent.media_id)
                    .join(ShowModel, ShowModel.id == Media.show_id)
                    .where(
                        WatchEvent.user_id == current_user.id,
                        WatchEvent.completed.is_(True),
                        ShowModel.tmdb_id == series_tmdb_id,
                        Media.media_type == MediaType.episode,
                        Media.season_number.isnot(None),
                        Media.episode_number.isnot(None),
                    )
                )
                watch_start_date, watch_end_date = watch_dates_q.one()

                watch_sources_q = await db.execute(
                    select(WatchEvent.watch_source)
                    .join(Media, Media.id == WatchEvent.media_id)
                    .join(ShowModel, ShowModel.id == Media.show_id)
                    .where(
                        WatchEvent.user_id == current_user.id,
                        WatchEvent.completed.is_(True),
                        ShowModel.tmdb_id == series_tmdb_id,
                        Media.media_type == MediaType.episode,
                        WatchEvent.watched_at.isnot(None),
                        WatchEvent.watch_source.isnot(None),
                    )
                    .distinct()
                    .order_by(WatchEvent.watch_source.asc())
                )

                watch_sources = [
                    source for source in watch_sources_q.scalars().all()
                    if source
                ]


        show_dict = format_show(show)

        # Most shows have no IMDb rating stored yet: look it up once and keep it.
        imdb_id = (show.tmdb_data or {}).get("external_ids", {}).get("imdb_id")
        if show_dict.get("imdb_rating") is None and imdb_id:
            rating = await tmdb.get_imdb_rating(imdb_id)
            if rating:
                show.tmdb_data = {**(show.tmdb_data or {}), "imdb_rating": rating}
                await db.commit()
                show_dict["imdb_rating"] = rating

        if tvdb_genres:
            show_dict["genres"] = tvdb_genres
        if metadata_lang and tmdb_extra:
            for field, tmdb_key in [("title", "name"), ("overview", "overview"), ("tagline", "tagline")]:
                val = tmdb_extra.get(tmdb_key)
                if val:
                    show_dict[field] = val

        return {
            "discs": discs,
            **show_dict,
            "episode_order": selected_episode_order,
            "tvdb_id": (
                (order_preference.tvdb_id if order_preference else None)
                or show.tvdb_id
                or (tmdb_extra or show.tmdb_data or {}).get("external_ids", {}).get("tvdb_id")
            ),
            "seasons_meta": enhanced_seasons_meta,
            "original_language": (show.tmdb_data or {}).get("original_language") or (tmdb_extra or {}).get("original_language"),
            "first_air_date": (tmdb_extra or show.tmdb_data or {}).get("first_air_date"),
            "last_air_date": (tmdb_extra or show.tmdb_data or {}).get("last_air_date"),
            "production_countries": (tmdb_extra or show.tmdb_data or {}).get("production_countries", []),
            "production_companies": [
    {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "logo_path": tmdb.poster_url(c.get("logo_path"), size="w500")
                    if c.get("logo_path")
                    else None,
                }
                for c in (tmdb_extra or show.tmdb_data or {}).get("production_companies", [])
            ],
            "age_rating": _extract_show_content_rating(tmdb_extra) if tmdb_extra else None,
            "imdb_id": (tmdb_extra or show.tmdb_data or {}).get("external_ids", {}).get("imdb_id"),
            "adult": (tmdb_extra or show.tmdb_data or {}).get("adult", False),
            "in_library": state_item.get("collection_pct", 0) > 0 if state_item else False,
            "watched": state_item.get("watched", False) if state_item else False,
            "watch_start_date": watch_start_date.isoformat() if watch_start_date else None,
            "watch_end_date": watch_end_date.isoformat() if watch_end_date else None,
            "watch_sources": watch_sources,
            "in_lists": state_item.get("in_lists", []),
            "collection_pct": state_item.get("collection_pct", 0),
            "watch_pct": state_item.get("watch_pct", 0),
            "is_monitored": state_item.get("is_monitored", False),
            "request_enabled": state_item.get("request_enabled", False),
            "request_status": state_item.get("request_status"),
            "user_rating": state_item.get("user_rating"),
            "season_states": season_states,
            "seasons": {f"season_{k}": v for k, v in sorted(seasons.items())},
            "created_by": [
                {"tmdb_id": c["id"], "name": c["name"], "profile_path": tmdb.poster_url(c.get("profile_path"), size="w185")}
                for c in (tmdb_extra or show.tmdb_data or {}).get("created_by", [])
            ],
            "crew": await source_work.with_source_credits(
                _format_show_crew(tmdb_extra or show.tmdb_data or {}), "tv", series_tmdb_id,
                await get_user_tmdb_key(db, current_user.id), cast,
            ),
            "cast": cast,
            "guest_stars": guest_stars,
            "awards": awards,
            "networks": networks,
            "where_to_watch": where_to_watch,
        }

    # 2. If not local, fetch from TMDB
    api_key = await get_user_tmdb_key(db, current_user.id)
    if not check_tmdb_key(api_key):
        raise HTTPException(
            status_code=404, detail="Show not found and TMDB key not configured"
        )

    try:
        data = await tmdb.get_show(series_tmdb_id, api_key=api_key)

        cast, guest_stars = await _show_cast(None, data, api_key, db)

        networks = [
            {
                "id": n["id"],
                "name": n["name"],
                "logo_path": tmdb.poster_url(n.get("logo_path"), size="w500")
                if n.get("logo_path")
                else None,
                "origin_country": n.get("origin_country"),
            }
            for n in data.get("networks", [])
        ]

        state_item_tmdb: dict = {"tmdb_id": series_tmdb_id, "type": "series"}
        await enrich_with_state(db, current_user.id, [state_item_tmdb])

        where_to_watch = await get_where_to_watch(
            db, current_user.id, series_tmdb_id, MediaType.series, tmdb_key=api_key
        )

        return {
            "discs": discs,
            "id": None,
            "tmdb_id": series_tmdb_id,
            "episode_order": selected_episode_order,
            "tvdb_id": (
                (order_preference.tvdb_id if order_preference else None)
                or data.get("external_ids", {}).get("tvdb_id")
            ),
            "title": data.get("name"),
            "original_title": data.get("original_name"),
            "overview": data.get("overview"),
            "poster_path": tmdb.poster_url(data.get("poster_path")),
            "backdrop_path": tmdb.poster_url(data.get("backdrop_path"), size="w1280"),
            "tmdb_rating": data.get("vote_average"),
            "status": data.get("status"),
            "tagline": data.get("tagline"),
            "first_air_date": data.get("first_air_date"),
            "last_air_date": data.get("last_air_date"),
            "production_countries": data.get("production_countries", []),
            "genres": [g["name"] for g in data.get("genres", [])],
            "original_language": data.get("original_language"),
            "age_rating": _extract_show_content_rating(data),
            "imdb_id": data.get("external_ids", {}).get("imdb_id"),
            "adult": data.get("adult", False),
            "in_library": state_item_tmdb.get("collection_pct", 0) > 0,
            "watched": state_item_tmdb.get("watched", False),
            "in_lists": state_item_tmdb.get("in_lists", []),
            "collection_pct": state_item_tmdb.get("collection_pct", 0),
            "is_monitored": state_item_tmdb.get("is_monitored", False),
            "request_enabled": state_item_tmdb.get("request_enabled", False),
            "request_status": state_item_tmdb.get("request_status"),
            "user_rating": state_item_tmdb.get("user_rating"),
            "created_by": [
                {"tmdb_id": c["id"], "name": c["name"], "profile_path": tmdb.poster_url(c.get("profile_path"), size="w185")}
                for c in data.get("created_by", [])
            ],
            "crew": await source_work.with_source_credits(_format_show_crew(data), "tv", series_tmdb_id, api_key, cast),
            "cast": cast,
            "guest_stars": guest_stars,
            "networks": networks,
            "seasons_meta": [
                {
                    "season_number": s["season_number"],
                    "poster_path": tmdb.poster_url(s.get("poster_path")),
                    "episode_count": s["episode_count"],
                    "name": s["name"],
                    "air_date": s.get("air_date"),
                    "overview": s.get("overview"),
                    "tmdb_rating": s.get("vote_average"),
                }
                for s in data.get("seasons", [])
            ],
            "seasons": {},
            "season_states": {},
            "where_to_watch": where_to_watch,
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"TMDB Show not found: {e}")


@router.get("/{series_tmdb_id}/recommendations")
async def get_show_recommendations(
    series_tmdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch series recommendations from TMDB and enrich with state."""
    tmdb_key = await get_user_tmdb_key(db, current_user.id)
    if not check_tmdb_key(tmdb_key):
        return {"results": []}

    try:
        data = await tmdb.get_show(series_tmdb_id, api_key=tmdb_key)
        recs_raw = data.get("recommendations", {}).get("results", [])[:12]
        recommendations = [
            {
                "id": None,
                "tmdb_id": r["id"],
                "type": "series",
                "title": r.get("name") or r.get("title"),
                "original_title": r.get("original_name") or r.get("original_title"),
                "overview": r.get("overview"),
                "poster_path": tmdb.poster_url(r.get("poster_path")),
                "backdrop_path": tmdb.poster_url(r.get("backdrop_path"), size="w1280"),
                "release_date": r.get("first_air_date") or r.get("release_date"),
                "tmdb_rating": r.get("vote_average"),
            }
            for r in recs_raw
        ]
        await enrich_with_state(db, current_user.id, recommendations)
        return {"results": recommendations}
    except Exception:
        return {"results": []}


@router.get("/{series_tmdb_id}/season/{season_number}")
async def get_show_season(
    series_tmdb_id: int,
    season_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Try to find show and local episodes for this season
    show_result = await db.execute(
        select(ShowModel).where(ShowModel.tmdb_id == series_tmdb_id)
    )
    show = show_result.scalar_one_or_none()

    local_episodes = []
    if show:
        ep_result = await db.execute(
            select(Media)
            .where(Media.media_type == MediaType.episode)
            .where(Media.show_id == show.id)
            .where(Media.season_number == season_number)
            .order_by(Media.episode_number.asc())
        )
        local_episodes = ep_result.scalars().all()

    # 2. Always fetch full season data from TMDB for consistent metadata
    api_key = await get_user_tmdb_key(db, current_user.id)
    metadata_lang = await get_user_metadata_language(db, current_user.id)

    season_owned_on_disc = False
    season_disc_id = None
    try:
        if check_tmdb_key(api_key):
            import asyncio

            # Fetch season and show info (if not local) in parallel
            if not show:
                tmdb_data, tmdb_show_data = await asyncio.gather(
                    tmdb.get_season(series_tmdb_id, season_number, api_key=api_key, language=metadata_lang),
                    tmdb.get_show(series_tmdb_id, api_key=api_key, language=metadata_lang),
                )
                show_info = {
                    "id": None,
                    "tmdb_id": series_tmdb_id,
                    "title": tmdb_show_data.get("name"),
                    "poster_path": tmdb.poster_url(tmdb_show_data.get("poster_path")),
                    "backdrop_path": tmdb.poster_url(
                        tmdb_show_data.get("backdrop_path"), size="w1280"
                    ),
                    "networks": tmdb_show_data.get("networks", []),
                    "imdb_id": tmdb_show_data.get("external_ids", {}).get("imdb_id"),
                }
            else:
                tmdb_data = await tmdb.get_season(
                    series_tmdb_id, season_number, api_key=api_key, language=metadata_lang
                )
                show_info = format_show(show)
                show_info["imdb_id"] = (show.tmdb_data or {}).get("external_ids", {}).get("imdb_id")

            imdb_id = (show_info or {}).get("imdb_id")
            imdb_rating = await tmdb.get_imdb_rating(imdb_id) if imdb_id else None

            # Bulk fetch watched state and ratings for episodes in this season
            tmdb_episodes = tmdb_data.get("episodes", [])
            total_in_season = len(tmdb_episodes)
            today_str = date.today().isoformat()
            total_aired_in_season = sum(
                1 for ep in tmdb_episodes
                if ep.get("air_date") and ep["air_date"] <= today_str
            )
            season_ep_tmdb_ids = [
                ep.get("id") for ep in tmdb_episodes if ep.get("id")
            ]

            watched_ep_tmdb_ids: set[int] = set()
            episode_ratings: dict = {}

            if season_ep_tmdb_ids:
                watched_q = await db.execute(
                    select(Media.tmdb_id)
                    .join(WatchEvent, WatchEvent.media_id == Media.id)
                    .where(
                        WatchEvent.user_id == current_user.id,
                        WatchEvent.completed == True,
                        Media.media_type == MediaType.episode,
                        Media.tmdb_id.in_(season_ep_tmdb_ids),
                    )
                    .distinct()
                )
                watched_ep_tmdb_ids = {r[0] for r in watched_q.all()}

            # Fetch list membership per episode
            episode_in_lists: dict[int, list[int]] = {}
            local_media_ids = [ep.id for ep in local_episodes] if local_episodes else []
            if local_media_ids:
                user_lists_q = await db.execute(
                    select(UserList.id).where(UserList.user_id == current_user.id)
                )
                user_list_ids = [r[0] for r in user_lists_q.all()]
                if user_list_ids:
                    ep_lists_q = await db.execute(
                        select(Media.tmdb_id, ListItem.list_id)
                        .join(ListItem, ListItem.media_id == Media.id)
                        .where(
                            Media.id.in_(local_media_ids),
                            ListItem.list_id.in_(user_list_ids),
                        )
                        .distinct()
                    )
                    for ep_tmdb_id, list_id in ep_lists_q.all():
                        episode_in_lists.setdefault(ep_tmdb_id, []).append(list_id)

            # Merge local library status
            local_map = {ep.episode_number: ep for ep in local_episodes}

            # Subquery to check which (season, episode) pairs are in the user collection.
            # Primary path: match by show_id. The outerjoin also catches rows where show_id
            # points to a different DB row for the same TMDB show (duplicate show rows).
            coll_show_conditions = [ShowModel.tmdb_id == series_tmdb_id]
            if show:
                coll_show_conditions.insert(0, Media.show_id == show.id)
            user_coll_eps_q = await db.execute(
                select(Media.season_number, Media.episode_number)
                .join(Collection, Collection.media_id == Media.id)
                .outerjoin(ShowModel, ShowModel.id == Media.show_id)
                .where(
                    Collection.user_id == current_user.id,
                    Media.media_type == MediaType.episode,
                    Media.season_number == season_number,
                    or_(*coll_show_conditions)
                )
                .distinct()
            )
            user_collected_eps = {(r[0], r[1]) for r in user_coll_eps_q.all()}

            # Fallback: also match by TMDB episode ID for rows where show_id is null.
            if season_ep_tmdb_ids:
                tmdb_id_coll_q = await db.execute(
                    select(Media.season_number, Media.episode_number)
                    .join(Collection, Collection.media_id == Media.id)
                    .where(
                        Collection.user_id == current_user.id,
                        Media.media_type == MediaType.episode,
                        Media.tmdb_id.in_(season_ep_tmdb_ids),
                        Media.show_id.is_(None),
                    )
                    .distinct()
                )
                user_collected_eps |= {(r[0], r[1]) for r in tmdb_id_coll_q.all()}

            # A season you own on disc: all its episodes are in your collection.
            from core.physical import season_discs
            season_disc_id = (await season_discs(db, current_user.id, series_tmdb_id)).get(season_number)
            season_owned_on_disc = season_disc_id is not None
            if season_owned_on_disc:
                user_collected_eps |= {(season_number, ep.get("episode_number")) for ep in tmdb_episodes if ep.get("episode_number")}

            async def fetch_episode_imdb_rating(ep):
                ep_num = ep.get("episode_number")
                if ep_num is None:
                    return None, None

                try:
                    external_ids = await tmdb.get_episode_external_ids(
                        series_tmdb_id,
                        season_number,
                        ep_num,
                        api_key=api_key,
                    )

                    imdb_id = external_ids.get("imdb_id")
                    rating = await tmdb.get_imdb_rating(imdb_id) if imdb_id else None
                    return ep_num, rating
                except Exception:
                    return ep_num, None

            imdb_ratings = dict(
                await asyncio.gather(
                    *(fetch_episode_imdb_rating(ep) for ep in tmdb_episodes)
                )
            )

            badges = season_badges(
                tmdb_data,
                show.status if show else tmdb_show_data.get("status"),
                last_season(show.tmdb_data if show else tmdb_show_data),
            )

            episodes = []
            for ep in tmdb_episodes:
                ep_num = ep.get("episode_number")
                local_ep = local_map.get(ep_num)
                local_media_id = local_ep.id if local_ep else None
                
                is_in_library = (season_number, ep_num) in user_collected_eps

                episodes.append(
                    {
                        "id": local_media_id,
                        "tmdb_id": ep.get("id"),
                        "type": "episode",
                        "title": ep.get("name"),
                        "overview": ep.get("overview"),
                        "poster_path": tmdb.poster_url(
                            ep.get("still_path"), size="w500"
                        ),
                        "air_date": ep.get("air_date"),
                        "episode_number": ep_num,
                        "season_number": season_number,
                        "tmdb_rating": ep.get("vote_average"),
                        "imdb_rating": imdb_ratings.get(ep_num),
                        "badge": badges.get(ep_num),
                        "in_library": is_in_library,
                        "runtime": ep.get("runtime"),
                        "watched": ep.get("id") in watched_ep_tmdb_ids,
                        "user_rating": episode_ratings.get(local_media_id) if local_media_id else None,
                        "in_lists": episode_in_lists.get(ep.get("id"), []),
                    }
                )

            # Store episode translations for library browsing
            if metadata_lang:
                try:
                    for ep_item in episodes:
                        if ep_item.get("id"):
                            await upsert_media_translation(
                                db, ep_item["id"], metadata_lang,
                                ep_item.get("title"),
                                ep_item.get("overview"),
                                None,
                                None,
                            )
                    await db.commit()
                except Exception:
                    pass

            show_state: dict = {"tmdb_id": series_tmdb_id, "type": "series"}
            await enrich_with_state(db, current_user.id, [show_state])

            # Season-level stats: watched, in_library, collection_pct, user_rating
            collected_in_season = 0
            if show:
                # Count collected episodes in this season.
                # Primary path: match by show_id.
                coll_q = await db.execute(
                    select(func.count(func.distinct(Media.episode_number)))
                    .join(Collection, Collection.media_id == Media.id)
                    .where(
                        Media.show_id == show.id,
                        Media.season_number == season_number,
                        Collection.user_id == current_user.id,
                        Media.media_type == MediaType.episode,
                        Media.episode_number.isnot(None),
                    )
                )
                collected_in_season = coll_q.scalar_one()

                # Fallback: count any collected episodes matched only by TMDB ID (show_id null).
                # This covers rows created before show_id was reliably set on manual collects.
                if season_ep_tmdb_ids:
                    null_show_coll_q = await db.execute(
                        select(Media.episode_number)
                        .join(Collection, Collection.media_id == Media.id)
                        .where(
                            Collection.user_id == current_user.id,
                            Media.media_type == MediaType.episode,
                            Media.tmdb_id.in_(season_ep_tmdb_ids),
                            Media.show_id.is_(None),
                            Media.episode_number.isnot(None),
                        )
                        .distinct()
                    )
                    null_show_ep_nums = {r[0] for r in null_show_coll_q.all()}
                    
                    # Merge: avoid double-counting episodes already found via show_id.
                    already_by_show_q = await db.execute(
                        select(Media.episode_number)
                        .join(Collection, Collection.media_id == Media.id)
                        .where(
                            Media.show_id == show.id,
                            Media.season_number == season_number,
                            Collection.user_id == current_user.id,
                            Media.media_type == MediaType.episode,
                            Media.episode_number.isnot(None),
                        )
                        .distinct()
                    )
                    already_ep_nums = {r[0] for r in already_by_show_q.all()}
                    extra = null_show_ep_nums - already_ep_nums
                    collected_in_season += len(extra)
            elif season_ep_tmdb_ids:
                # If no local show, just count by TMDB IDs
                coll_q = await db.execute(
                    select(func.count(func.distinct(Media.episode_number)))
                    .join(Collection, Collection.media_id == Media.id)
                    .where(
                        Collection.user_id == current_user.id,
                        Media.media_type == MediaType.episode,
                        Media.tmdb_id.in_(season_ep_tmdb_ids),
                        Media.episode_number.isnot(None),
                    )
                )
                collected_in_season = coll_q.scalar_one()

            aired_denom = total_aired_in_season if total_aired_in_season > 0 else total_in_season
            if season_owned_on_disc:
                collected_in_season = max(collected_in_season, aired_denom)
            season_in_library = collected_in_season > 0
            season_collection_pct = min(100, int((collected_in_season / aired_denom) * 100)) if aired_denom > 0 else 0

            # Count unique episodes in this season that have been watched
            # episodes list contains "watched": True/False for each episode.
            watched_count = sum(1 for ep in episodes if ep.get("watched"))
            season_watched = watched_count >= aired_denom if aired_denom > 0 else False
            season_watch_pct = min(100, int((watched_count / aired_denom) * 100)) if aired_denom > 0 else 0

            # Season user rating (stored against show's Media row with season_number)
            season_user_rating = None
            show_media_q = await db.execute(
                select(Media).where(Media.tmdb_id == series_tmdb_id, Media.media_type == MediaType.series)
            )
            show_media = show_media_q.scalar_one_or_none()
            if show_media:
                rating_q = await db.execute(
                    select(Rating.rating).where(
                        Rating.media_id == show_media.id,
                        Rating.user_id == current_user.id,
                        Rating.season_number == season_number,
                        Rating.episode_order.is_(None),
                    )
                )
                season_user_rating = rating_q.scalar_one_or_none()

            return {
                "id": tmdb_data.get("id"),
                "tmdb_id": series_tmdb_id,
                "season_number": season_number,
                "name": tmdb_data.get("name"),
                "overview": tmdb_data.get("overview"),
                "poster_path": tmdb.poster_url(tmdb_data.get("poster_path")),
                "backdrop_path": tmdb.poster_url(
                    tmdb_data.get("backdrop_path"), size="w1280"
                ),
                "imdb_id": (show_info or {}).get("imdb_id"),
                "air_date": tmdb_data.get("air_date"),
                "tmdb_rating": tmdb_data.get("vote_average"),
                "imdb_rating": imdb_rating,
                "episodes": episodes,
                "show": show_info,
                "show_watched": show_state.get("watched", False),
                "season_watched": season_watched,
                "season_watch_pct": season_watch_pct,
                "season_in_library": season_in_library,
                "season_disc_id": season_disc_id,
                "season_collection_pct": season_collection_pct,
                "season_user_rating": season_user_rating,
                "show_in_lists": show_state.get("in_lists", []),
                "show_in_library": show_state.get("collection_pct", 0) > 0,
                "show_collection_pct": show_state.get("collection_pct", 0),
                "show_request_enabled": show_state.get("request_enabled", False),
                "show_is_monitored": show_state.get("is_monitored", False),
            }
        elif show:
            # Fallback to local only if no TMDB key
            return {
                "season_number": season_number,
                "name": f"Season {season_number}",
                "episodes": [format_media(ep) for ep in local_episodes],
                "show": format_show(show),
            }
        else:
            raise HTTPException(status_code=404, detail="Show not found")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=404, detail=f"Season not found: {e}")


@router.get("/{series_tmdb_id}/season/{season_number}/{episode_number}")
async def get_episode_detail(
    series_tmdb_id: int,
    season_number: int,
    episode_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key = await get_user_tmdb_key(db, current_user.id)
    if not check_tmdb_key(api_key):
        raise HTTPException(status_code=404, detail="TMDB API Key not configured")
    metadata_lang = await get_user_metadata_language(db, current_user.id)

    try:
        import asyncio

        show_result = await db.execute(
            select(ShowModel).where(ShowModel.tmdb_id == series_tmdb_id)
        )
        show = show_result.scalar_one_or_none()

        if show:
            ep_data, show_tmdb = await asyncio.gather(
                tmdb.get_episode(
                    series_tmdb_id, season_number, episode_number, api_key=api_key, language=metadata_lang
                ),
                tmdb.get_show(
                    series_tmdb_id, api_key=api_key, language=metadata_lang
                ),
            )
            show_info = await build_show_info(
                show,
                db,
                current_user.id,
                tmdb_data=show_tmdb,
            )

            external_ids = await tmdb.get_episode_external_ids(
                series_tmdb_id,
                season_number,
                episode_number,
                api_key=api_key,
            )

        # TVDB is used as the authoritative episode air-date source.
        tvdb_air_date = None
        tvdb_series_id = show.tvdb_id if show and show.tvdb_id else None

        if not tvdb_series_id and show_tmdb:
            tvdb_series_id = show_tmdb.get("external_ids", {}).get("tvdb_id")

        tvdb_api_key = await get_user_tvdb_key(db, current_user.id)
        if tvdb_api_key and tvdb_series_id:
            try:
                tvdb_raw = await tvdb_client.get_series_episodes(
                    int(tvdb_series_id),
                    season_number,
                    tvdb_api_key,
                    language=tvdb_client.tvdb_language(metadata_lang),
                )
                tvdb_eps = [
                    tvdb_client.format_episode(e)
                    for e in tvdb_raw
                ]
                tvdb_ep = next(
                    (
                        e for e in tvdb_eps
                        if e.get("episode_number") == episode_number
                    ),
                    None,
                )
                if tvdb_ep:
                    tvdb_air_date = tvdb_ep.get("air_date")
            except Exception:
                pass


        imdb_id = external_ids.get("imdb_id")

        imdb_rating = await tmdb.get_imdb_rating(imdb_id)

        # Check local library for this episode
        local_ep = None
        library_info = None
        if show:
            local_result = await db.execute(
                select(Media)
                .where(Media.media_type == MediaType.episode)
                .where(Media.show_id == show.id)
                .where(Media.season_number == season_number)
                .where(Media.episode_number == episode_number)
            )
            local_ep = local_result.scalars().first()
            
            if local_ep:
                coll_q = (
                    select(CollectionFile)
                    .join(Collection, Collection.id == CollectionFile.collection_id)
                    .where(Collection.media_id == local_ep.id, Collection.user_id == current_user.id)
                    .order_by(CollectionFile.added_at.desc())
                )
                coll_res = await db.execute(coll_q)
                coll_file = coll_res.scalars().first()
                if coll_file:
                    library_info = {
                        "resolution": coll_file.resolution,
                        "video_codec": coll_file.video_codec,
                        "audio_codec": coll_file.audio_codec,
                        "audio_channels": coll_file.audio_channels,
                        "audio_languages": coll_file.audio_languages,
                        "subtitle_languages": coll_file.subtitle_languages,
                    }

        credits = ep_data.get("credits", {})
        cast = [
            {
                "tmdb_id": c.get("id"),
                "name": c.get("name"),
                "character": c.get("character"),
                "profile_path": tmdb.poster_url(c.get("profile_path")),
            }
            for c in credits.get("cast", [])[:12]
        ]
        guest_stars = [
            {
                "tmdb_id": c.get("id"),
                "name": c.get("name"),
                "character": c.get("character"),
                "profile_path": tmdb.poster_url(c.get("profile_path")),
            }
            for c in ep_data.get("guest_stars", [])
        ]

        crew = [
            {
                "tmdb_id": c.get("id"),
                "name": c.get("name"),
                "department": c.get("department"),
                "job": c.get("job"),
                "profile_path": tmdb.poster_url(c.get("profile_path")),
            }
            for c in credits.get("crew", [])
        ]

        external_ids = await tmdb.get_episode_external_ids(
            series_tmdb_id,
            season_number,
            episode_number,
            api_key=api_key,
        )
        imdb_id = external_ids.get("imdb_id")

        # Store episode translation for library browsing
        if metadata_lang and local_ep:
            try:
                await upsert_media_translation(
                    db, local_ep.id, metadata_lang,
                    ep_data.get("name"),
                    ep_data.get("overview"),
                    None,
                    ep_data.get("still_path"),
                )
                await db.commit()
            except Exception:
                pass

        # Get all episodes in this season for navigation
        season_tmdb = await tmdb.get_season(
            series_tmdb_id, season_number, api_key=api_key, language=metadata_lang
        )
        episodes_nav = [
            {
                "episode_number": ep.get("episode_number"),
                "title": ep.get("name"),
            }
            for ep in season_tmdb.get("episodes", [])
        ]
        badge = season_badges(season_tmdb, (show_info or {}).get("status"), last_season(show_tmdb)).get(episode_number)

        ep_tmdb_id = ep_data.get("id")
        ep_state: dict = {"tmdb_id": ep_tmdb_id, "type": "episode"}
        await enrich_with_state(db, current_user.id, [ep_state])

        watch_history = []

        if local_ep:
            watch_history_q = await db.execute(
                select(
                    WatchEvent.id,
                    WatchEvent.watched_at,
                    WatchEvent.watch_source,
                )
                .where(
                    WatchEvent.media_id == local_ep.id,
                    WatchEvent.user_id == current_user.id,
                    WatchEvent.completed.is_(True),
                )
                .order_by(WatchEvent.watched_at.desc())
            )

            watch_history = [
                {
                    "id": row.id,
                    "watched_at": row.watched_at.isoformat() if row.watched_at else None,
                    "watch_source": row.watch_source,
                }
                for row in watch_history_q.all()
            ]

        return {
            "id": local_ep.id if local_ep else None,
            "tmdb_id": ep_tmdb_id,
            "in_library": ep_state.get("in_library", local_ep is not None),
            "watched": ep_state.get("watched", False),
            "in_lists": ep_state.get("in_lists", []),
            "collection_pct": ep_state.get("collection_pct", 100 if local_ep else 0),
            "user_rating": ep_state.get("user_rating"),
            "play_count": ep_state.get("play_count", 0),
            "watch_history": watch_history,
            "episode_number": episode_number,
            "season_number": season_number,
            "title": ep_data.get("name"),
            "overview": ep_data.get("overview"),
            "still_path": tmdb.poster_url(ep_data.get("still_path"), size="w780"),
            "air_date": tvdb_air_date or ep_data.get("air_date"),
            "runtime": ep_data.get("runtime"),
            "tmdb_rating": ep_data.get("vote_average"),
            "imdb_id": imdb_id,
            "imdb_rating": imdb_rating,
            "cast": cast,
            "guest_stars": guest_stars,
            "crew": crew,
            "show": show_info,
            "episodes": episodes_nav,
            "library": library_info,
            "badge": badge,
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=404, detail=f"Episode not found: {e}")


@router.post("/{series_tmdb_id}/refresh")
async def refresh_show_metadata(
    series_tmdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key = await get_user_tmdb_key(db, current_user.id)
    if not check_tmdb_key(api_key):
        raise HTTPException(status_code=400, detail="TMDB API key not configured")

    show_result = await db.execute(
        select(ShowModel).where(ShowModel.tmdb_id == series_tmdb_id)
    )
    show = show_result.scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found in local library")

    try:
        data = await tmdb.get_show(series_tmdb_id, api_key=api_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TMDB fetch failed: {e}")

    # Update show-level fields
    show.title = data.get("name") or show.title
    show.original_title = data.get("original_name")
    show.overview = data.get("overview")
    show.poster_path = tmdb.poster_url(data.get("poster_path"))
    show.backdrop_path = tmdb.poster_url(data.get("backdrop_path"), size="w1280")
    show.tmdb_rating = data.get("vote_average")
    show.status = data.get("status")
    show.tagline = data.get("tagline")
    show.tvdb_id = data.get("external_ids", {}).get("tvdb_id") or show.tvdb_id
    show.first_air_date = data.get("first_air_date")
    show.last_air_date = data.get("last_air_date")
    show.tmdb_data = {
        **(show.tmdb_data or {}),
        "genres": [g["name"] for g in data.get("genres", [])],
        "external_ids": data.get("external_ids", {}),
        "imdb_rating": await tmdb.get_imdb_rating(
            data.get("external_ids", {}).get("imdb_id")
        ),
        "original_language": data.get("original_language"),
        "networks": data.get("networks", []),
        "last_episode_to_air": data.get("last_episode_to_air"),
        "next_episode_to_air": data.get("next_episode_to_air"),
        "seasons": [
            {
                "season_number": s["season_number"],
                "poster_path": tmdb.poster_url(s.get("poster_path")),
                "episode_count": s["episode_count"],
                "name": s["name"],
                "air_date": s.get("air_date"),
                "overview": s.get("overview"),
            }
            for s in data.get("seasons", [])
        ],
    }

    # Re-enrich all local episodes linked to this show
    ep_result = await db.execute(
        select(Media)
        .where(Media.media_type == MediaType.episode)
        .where(Media.show_id == show.id)
    )
    episodes = ep_result.scalars().all()

    # Also find orphaned episodes (show_id = null) in this user's collection
    # whose (season_number, episode_number) match TMDB data for this show.
    # This happens when the show's TMDB lookup failed during the original sync,
    # leaving episodes with no show_id even though they belong to this show.
    user_media_ids_sq = select(Collection.media_id).where(Collection.user_id == current_user.id)
    orphan_result = await db.execute(
        select(Media)
        .where(
            Media.media_type == MediaType.episode,
            Media.show_id.is_(None),
            Media.id.in_(user_media_ids_sq),
        )
    )
    orphans = orphan_result.scalars().all()

    semaphore = asyncio.Semaphore(10)
    season_data: dict[int, dict[int, dict]] = {}

    # Collect seasons needed: linked episodes + all show seasons (for orphan matching)
    linked_seasons = {ep.season_number for ep in episodes if ep.season_number is not None}
    tmdb_seasons = {s["season_number"] for s in data.get("seasons", [])}
    orphan_seasons = {ep.season_number for ep in orphans if ep.season_number is not None}
    # Only fetch seasons that could contain orphans belonging to this show
    needed_seasons = linked_seasons | (tmdb_seasons & orphan_seasons)

    async def fetch_season(sn: int) -> None:
        async with semaphore:
            try:
                d = await tmdb.get_season(series_tmdb_id, sn, api_key=api_key)
                season_data[sn] = {ep["episode_number"]: ep for ep in d.get("episodes", [])}
            except Exception:
                season_data[sn] = {}

    if needed_seasons:
        await asyncio.gather(*[fetch_season(sn) for sn in needed_seasons])

    def apply_episode_data(media: Media, ep: dict) -> None:
        media.show_id = show.id
        media.tmdb_id = ep.get("id") or media.tmdb_id
        media.title = ep.get("name") or media.title
        media.overview = ep.get("overview")
        media.poster_path = tmdb.poster_url(ep.get("still_path"), size="w500")
        media.release_date = ep.get("air_date")
        media.tmdb_rating = ep.get("vote_average")
        media.tmdb_data = {"runtime": ep.get("runtime"), "cast": []}

    for media in episodes:
        if media.season_number is None:
            continue
        ep = season_data.get(media.season_number, {}).get(media.episode_number)
        if ep:
            apply_episode_data(media, ep)

    # Adopt orphans whose (season, episode) has exactly one candidate in this show's TMDB data
    for media in orphans:
        if media.season_number is None or media.episode_number is None:
            continue
        ep = season_data.get(media.season_number, {}).get(media.episode_number)
        if ep:
            apply_episode_data(media, ep)

    all_media_ids = [ep.id for ep in episodes] + [ep.id for ep in orphans]
    await refresh_technical_data(db, all_media_ids, current_user.id)

    await db.commit()
    return {"message": "Metadata refreshed successfully"}


# ── TVDB Show Endpoints ─────────────────────────────────────────────────────

_PLAYING_RE = re.compile(r'For playing:?\s*"([^"]+)"', re.I)


def _norm_character(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


# (character, actor, episodes) per show for naming award nominees. Long-running
# shows have thousands of credits, so build the list once a day, not per visit.
_ROLES_TTL = 24 * 3600
_roles_cache: dict[int, tuple[float, list[tuple[str, str, int]]]] = {}


async def _show_roles(tmdb_id: int, tmdb_key: str | None) -> list[tuple[str, str, int]] | None:
    hit = _roles_cache.get(tmdb_id)
    if hit and time.time() - hit[0] < _ROLES_TTL:
        return hit[1]
    try:
        data = await tmdb.get_show(tmdb_id, api_key=tmdb_key)
    except Exception:
        return None
    roles: list[tuple[str, str, int]] = []
    for person in (data.get("aggregate_credits") or {}).get("cast") or []:
        for role in person.get("roles") or []:
            character = _norm_character(role.get("character") or "")
            if character:
                roles.append((character, person.get("name"), role.get("episode_count") or 0))
    _roles_cache[tmdb_id] = (time.time(), roles)
    return roles


_EPISODES_TTL = 24 * 3600
_episodes_cache: dict[int, tuple[float, dict[str, dict]]] = {}
_EPISODE_RE = re.compile(r'For episodes?:?\s*(.+)', re.I)


def _norm_episode(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


async def _show_episodes(tmdb_id: int, tmdb_key: str | None) -> dict[str, dict]:
    """Every episode of a show (with its crew) by normalised title, cached for a day."""
    cached = _episodes_cache.get(tmdb_id)
    if cached and time.time() - cached[0] < _EPISODES_TTL:
        return cached[1]
    show = await tmdb.get_show(tmdb_id, api_key=tmdb_key)
    semaphore = asyncio.Semaphore(5)

    async def season(number: int) -> list[dict]:
        async with semaphore:
            try:
                return (await tmdb.get_season(tmdb_id, number, api_key=tmdb_key)).get("episodes") or []
            except Exception:
                return []

    seasons = await asyncio.gather(*(season(s["season_number"]) for s in show.get("seasons") or [] if s.get("season_number") is not None))
    episodes = {_norm_episode(e.get("name")): e for eps in seasons for e in eps if e.get("name")}
    _episodes_cache[tmdb_id] = (time.time(), episodes)
    return episodes


async def _name_award_nominees(awards: list[dict], tmdb_id: int, tmdb_key: str | None) -> list[dict]:
    """Name TVDB's nominees: actors from the character they played, then
    whoever Wikidata names (which also adds Golden Globe and Emmy nominations
    TVDB lacks), then directors, writers and other crew from the credits of
    the episode named in the details ("For episode "Swing"")."""
    named = await _name_actors(awards, tmdb_id, tmdb_key)
    on_record = tv_record_rows(await _emmy_records(tmdb_id, tmdb_key))
    # Wikidata's copies of nominations on record would only be added twice.
    wd_rows = [w for w in await wikidata.tv_award_people(tmdb_id) if match_group(w, on_record, set()) is None]
    named = name_tv_awards(named, on_record + wd_rows)
    return await _name_crew(named, tmdb_id, tmdb_key)


async def _emmy_records(tmdb_id: int, tmdb_key: str | None) -> list[dict]:
    """The show's Primetime Emmy nominations on record (core.award_data)."""
    if not await award_data.ensure_loaded():
        return []
    try:
        show = await tmdb.get_show(tmdb_id, api_key=tmdb_key)
    except Exception:
        return []
    year = lambda d: int(d[:4]) if d and d[:4].isdigit() else None
    ended = (show.get("status") or "").lower() in {"ended", "canceled"}
    return award_data.show_records(
        {show.get("name"), show.get("original_name")} - {None},
        year(show.get("first_air_date")),
        year(show.get("last_air_date")) if ended else None,
    )


async def _name_crew(named: list[dict], tmdb_id: int, tmdb_key: str | None) -> list[dict]:
    # Casting isn't per episode: one team usually casts the whole show, so it
    # comes from the show's crew (those credited on most episodes).
    if any(not a.get("person_name") and topic(a.get("category_name")) == "casting" for a in named):
        try:
            show = await tmdb.get_show(tmdb_id, api_key=tmdb_key)
            casting = [
                (c["name"], j.get("episode_count") or 0)
                for c in (show.get("aggregate_credits") or {}).get("crew") or []
                for j in c.get("jobs") or [] if j.get("job") == "Casting"
            ]
            most = max((n for _, n in casting), default=0)
            team = list(dict.fromkeys(name for name, n in casting if most and n >= most * 0.8))
            if 0 < len(team) <= 3:
                named = [
                    {**a, "person_name": join_names(team), "name_inferred": True}
                    if not a.get("person_name") and topic(a.get("category_name")) == "casting" else a
                    for a in named
                ]
        except Exception:
            pass
    wanted = [
        i for i, a in enumerate(named)
        if not a.get("person_name") and topic_jobs(a.get("category_name"))
        and _EPISODE_RE.search(a.get("details") or "")
    ]
    if not wanted:
        return named
    try:
        episodes = await _show_episodes(tmdb_id, tmdb_key)
    except Exception:
        return named
    for i in wanted:
        award = named[i]
        titles = re.findall(r'"([^"]+)"', _EPISODE_RE.search(award["details"]).group(1))
        crew = [c for t in titles for c in (episodes.get(_norm_episode(t)) or {}).get("crew") or []]
        people = credited(crew, award["category_name"])
        if people:
            named[i] = {**award, "person_name": join_names([p["name"] for p in people]), "name_inferred": True}
    return named


async def _name_actors(awards: list[dict], tmdb_id: int, tmdb_key: str | None) -> list[dict]:
    """TVDB nominees carry no person, only "For playing "X"" in the details,
    so match that character against the show's full TMDB cast (guest stars
    included) to name the actor."""
    wanted = [a for a in awards if not a.get("person_name") and _PLAYING_RE.search(a.get("details") or "")]
    if not wanted:
        return awards
    roles = await _show_roles(tmdb_id, tmdb_key)
    if roles is None:
        return awards

    def actor_for(character: str) -> str | None:
        target = _norm_character(character)
        if not target:
            return None
        # Exact match first, then one name containing the other: "Det. Olivia
        # Benson" for "Olivia Benson", or "Dana Lewis" for "Agent Dana Lewis".
        # A shorter credit must still be a full name: a lone "Bernadette" is
        # someone else, not "Bernadette Stabler".
        # When several actors played the part (a younger self in a flashback),
        # take the one with the most episodes in it.
        for matches in (
            [r for r in roles if r[0] == target],
            [r for r in roles if target in r[0] or (r[0] in target and " " in r[0])],
        ):
            if matches:
                return max(matches, key=lambda r: r[2])[1]
        # Nicknames: same surname and the first names share their first three
        # letters ("Bernie Stabler" for "Bernadette Stabler").
        words = target.split()
        if len(words) >= 2 and len(words[0]) >= 3:
            nick = [
                r for r in roles
                if len(r[0].split()) >= 2
                and r[0].split()[-1] == words[-1]
                and r[0].split()[0][:3] == words[0][:3]
            ]
            if nick:
                return max(nick, key=lambda r: r[2])[1]
        # A regular credited by first name only ("Hal" for "Hal Wilkerson").
        # Ten-plus episodes keeps out one-off parts like a younger self.
        if len(words) >= 2:
            first = [r for r in roles if r[0] == words[0] and r[2] >= 10]
            if first:
                return max(first, key=lambda r: r[2])[1]
        return None

    named = []
    for award in awards:
        match = _PLAYING_RE.search(award.get("details") or "") if not award.get("person_name") else None
        if match:
            actors = [actor_for(c) for c in match.group(1).split("/")]
            actors = list(dict.fromkeys(a for a in actors if a))
            if actors:
                award = {**award, "person_name": join_names(actors)}
        named.append(award)

    # Acting nominations with no details at all (e.g. a Golden Globe for Best
    # Actress): credit whoever holds most of the show's other named
    # nominations of that kind (lead actress, lead actor), if anyone clearly does.
    def acting_kind(category: str) -> str | None:
        c = category.lower()
        if "guest" in c:
            return None
        if "actress" in c:
            return "actress"
        if "actor" in c:
            return "actor"
        return None

    tally: dict[str, dict[str, int]] = {}
    for award in named:
        kind = acting_kind(award.get("category_name") or "")
        if kind and award.get("person_name"):
            people = tally.setdefault(kind, {})
            people[award["person_name"]] = people.get(award["person_name"], 0) + 1
    for i, award in enumerate(named):
        kind = acting_kind(award.get("category_name") or "")
        if award.get("person_name") or award.get("details") or not kind or not tally.get(kind):
            continue
        ranked = sorted(tally[kind].items(), key=lambda kv: -kv[1])
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            named[i] = {**award, "person_name": ranked[0][0], "name_inferred": True}
    return named


@router.get("/tvdb/{tvdb_id}/awards")
async def get_tvdb_awards(
    tvdb_id: int,
    tmdb_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key = await get_user_tvdb_key(db, current_user.id)

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="TVDB API key not configured",
        )

    try:
        awards = await tvdb_client.get_series_awards(
            tvdb_id,
            api_key,
        )
        # TV awards are only the Golden Globes and Emmys.
        awards = [a for a in awards if award_family(a.get("award_name")) in TV_FAMILIES]
        if tmdb_id:
            awards = await _name_award_nominees(
                awards, tmdb_id, await get_user_tmdb_key(db, current_user.id)
            )

        return {
            "tvdb_id": tvdb_id,
            "count": len(awards),
            "awards": awards,
        }

    except tvdb_client.AwardIndexBuilding:
        return {"tvdb_id": tvdb_id, "count": 0, "awards": [], "pending": True}
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"TVDB awards fetch failed: {e}",
        )

@router.get("/tvdb/{tvdb_id}")
async def get_tvdb_show(
    tvdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key = await get_user_tvdb_key(db, current_user.id)
    if not api_key:
        raise HTTPException(status_code=400, detail="TVDB API key not configured")

    metadata_lang = await get_user_metadata_language(db, current_user.id)
    tvdb_lang = tvdb_client.tvdb_language(metadata_lang)

    try:
        raw = await tvdb_client.get_series(tvdb_id, api_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TVDB fetch failed: {e}")

    show_data = tvdb_client.format_series(raw, language=tvdb_lang)
    cast = tvdb_client.format_cast(raw)

    series_tmdb_id = show_data.get("tmdb_id_cross")
    series_tmdb_id = int(series_tmdb_id) if series_tmdb_id else None
    show_result = await db.execute(
        select(ShowModel).where(
            or_(
                ShowModel.tvdb_id == tvdb_id,
                ShowModel.tmdb_id == series_tmdb_id,
            )
        )
    )
    show = show_result.scalar_one_or_none()

    mapping_result = await db.execute(
        select(EpisodeOrderMapping).where(
            EpisodeOrderMapping.series_tmdb_id == series_tmdb_id
        )
    ) if series_tmdb_id else None
    mappings = list(mapping_result.scalars().all()) if mapping_result else []
    tmdb_api_key = await get_user_tmdb_key(db, current_user.id)
    show_data["seasons"], tmdb_show = await _enrich_tvdb_seasons(
        show_data["seasons"],
        mappings,
        tvdb_api_key=api_key,
        tvdb_language=tvdb_lang,
        series_tmdb_id=series_tmdb_id,
        tmdb_api_key=tmdb_api_key,
        metadata_language=metadata_lang,
    )
    mapping_by_tmdb = {
        (mapping.tmdb_season_number, mapping.tmdb_episode_number): mapping
        for mapping in mappings
    }

    collected_positions: dict[int, set[int]] = {}
    watched_positions: dict[int, set[int]] = {}
    season_ratings: dict[int, float] = {}
    if show:
        local_eps_result = await db.execute(
            select(Media).where(
                Media.show_id == show.id,
                Media.media_type == MediaType.episode,
            )
        )
        local_eps = list(local_eps_result.scalars().all())
        local_media_ids = [episode.id for episode in local_eps]
        collected_ids: set[int] = set()
        watched_ids: set[int] = set()
        if local_media_ids:
            collected_result = await db.execute(
                select(Collection.media_id).where(
                    Collection.user_id == current_user.id,
                    Collection.media_id.in_(local_media_ids),
                )
            )
            watched_result = await db.execute(
                select(WatchEvent.media_id).where(
                    WatchEvent.user_id == current_user.id,
                    WatchEvent.media_id.in_(local_media_ids),
                )
            )
            collected_ids = {row[0] for row in collected_result.all()}
            watched_ids = {row[0] for row in watched_result.all()}

        for episode in local_eps:
            mapping = mapping_by_tmdb.get(
                (episode.season_number, episode.episode_number)
            )
            if mapping:
                target_season = mapping.tvdb_season_number
                target_episode = mapping.tvdb_episode_number
            else:
                # No mapping for this specific episode — fall back to its own
                # TMDB position rather than dropping it from the counts entirely.
                target_season = episode.season_number
                target_episode = episode.episode_number
            if target_season is None or target_episode is None:
                continue
            if episode.id in collected_ids:
                collected_positions.setdefault(target_season, set()).add(target_episode)
            if episode.id in watched_ids:
                watched_positions.setdefault(target_season, set()).add(target_episode)

        if series_tmdb_id:
            show_media_result = await db.execute(
                select(Media).where(
                    Media.tmdb_id == series_tmdb_id,
                    Media.media_type == MediaType.series,
                )
            )
            show_media = show_media_result.scalar_one_or_none()
            if show_media:
                rating_result = await db.execute(
                    select(Rating.season_number, Rating.rating).where(
                        Rating.user_id == current_user.id,
                        Rating.media_id == show_media.id,
                        Rating.episode_order == "tvdb",
                        Rating.season_number.isnot(None),
                    )
                )
                season_ratings = dict(rating_result.all())

    season_states: dict = {}
    season_ep_counts = {
        season["season_number"]: season.get("episode_count", 0)
        for season in show_data["seasons"]
    }
    for season_number_value in set(
        list(season_ep_counts)
        + list(collected_positions)
        + list(watched_positions)
    ):
        collected = len(collected_positions.get(season_number_value, set()))
        watched = len(watched_positions.get(season_number_value, set()))
        total = season_ep_counts.get(season_number_value, 0)
        effective_total = total if total > 0 else collected
        season_states[season_number_value] = {
            "in_library": collected > 0,
            "collection_pct": min(100, int((collected / effective_total) * 100)) if effective_total > 0 else 0,
            "watched": watched >= effective_total if effective_total > 0 else False,
            "watch_pct": min(100, int((watched / effective_total) * 100)) if effective_total > 0 else 0,
            "user_rating": season_ratings.get(season_number_value),
        }

    in_library = bool(season_states and any(v["in_library"] for v in season_states.values()))

    # Derive overall watched / collection_pct from season states (skip season 0 specials)
    lib_seasons = [v for sn, v in season_states.items() if sn != 0 and v["in_library"]]
    watched_overall = bool(lib_seasons) and all(v["watched"] for v in lib_seasons)
    total_pct = sum(v["collection_pct"] for sn, v in season_states.items() if sn != 0)
    non_special_seasons = len([sn for sn in season_states if sn != 0])
    collection_pct = int(total_pct / non_special_seasons) if non_special_seasons else 0
    total_watch_pct = sum(v["watch_pct"] for sn, v in season_states.items() if sn != 0)
    watch_pct = int(total_watch_pct / non_special_seasons) if non_special_seasons else 0

    # Sonarr state
    gs = await _get_global_settings(db)
    settings_q = await db.execute(select(UserSettings).where(UserSettings.user_id == current_user.id))
    settings = settings_q.scalar_one_or_none()
    sonarr_cfg = _effective_sonarr(settings, gs)
    is_monitored = False
    request_enabled = sonarr_cfg is not None
    if sonarr_cfg:
        try:
            import httpx as _httpx
            url = sonarr_cfg.sonarr_url.rstrip("/")
            async with _httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(
                    f"{url}/api/v3/series/lookup",
                    params={"apiKey": sonarr_cfg.sonarr_token, "term": f"tvdb:{tvdb_id}"},
                )
                if res.status_code == 200:
                    for entry in res.json():
                        if entry.get("id"):
                            is_monitored = True
                            break
        except Exception:
            pass

    where_to_watch = (
        await get_where_to_watch(
            db,
            current_user.id,
            series_tmdb_id,
            MediaType.series,
            show=show,
        )
        if show and series_tmdb_id
        else []
    )

    # Networks (name only; TVDB doesn't provide logos)
    networks = [{"id": None, "name": n.get("name"), "logo_path": None, "origin_country": None}
                for n in (raw.get("networks") or []) if n.get("name")]

    return {
        **show_data,
        "id": show.id if show else None,
        "tmdb_id": series_tmdb_id,
        "type": "series",
        "tagline": None,
        "tmdb_rating": tmdb_show.get("vote_average"),
        "imdb_id": show_data.get("imdb_id"),
        "tmdb_id_cross": show_data.get("tmdb_id_cross"),
        "episode_order": "tvdb",
        "adult": False,
        "in_library": in_library,
        "watched": watched_overall,
        "in_lists": [],
        "collection_pct": collection_pct,
        "watch_pct": watch_pct,
        "is_monitored": is_monitored,
        "request_enabled": request_enabled,
        "request_status": None,
        "user_rating": None,
        "season_states": season_states,
        "seasons": {},
        "seasons_meta": show_data["seasons"],
        "cast": cast,
        "networks": networks,
        "where_to_watch": where_to_watch,
    }


@router.get("/tvdb/{tvdb_id}/season/{season_number}")
async def get_tvdb_season(
    tvdb_id: int,
    season_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key = await get_user_tvdb_key(db, current_user.id)
    if not api_key:
        raise HTTPException(status_code=400, detail="TVDB API key not configured")

    metadata_lang = await get_user_metadata_language(db, current_user.id)
    tvdb_lang = tvdb_client.tvdb_language(metadata_lang)

    try:
        raw_series, raw_episodes = await asyncio.gather(
            tvdb_client.get_series(tvdb_id, api_key),
            tvdb_client.get_series_episodes(tvdb_id, season_number, api_key, language=tvdb_lang),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TVDB fetch failed: {e}")

    show_data = tvdb_client.format_series(raw_series, language=tvdb_lang)
    eps = [tvdb_client.format_episode(e) for e in raw_episodes]

    series_tmdb_id = show_data.get("tmdb_id_cross")
    series_tmdb_id = int(series_tmdb_id) if series_tmdb_id else None
    show_result = await db.execute(
        select(ShowModel).where(
            or_(
                ShowModel.tvdb_id == tvdb_id,
                ShowModel.tmdb_id == series_tmdb_id,
            )
        )
    )
    show = show_result.scalar_one_or_none()

    mapping_result = await db.execute(
        select(EpisodeOrderMapping).where(
            EpisodeOrderMapping.series_tmdb_id == series_tmdb_id,
            EpisodeOrderMapping.tvdb_season_number == season_number,
        )
    ) if series_tmdb_id else None
    mappings = list(mapping_result.scalars().all()) if mapping_result else []
    base_season_meta = next(
        (
            season
            for season in show_data["seasons"]
            if season["season_number"] == season_number
        ),
        {},
    )
    tmdb_api_key = await get_user_tmdb_key(db, current_user.id)
    enriched_seasons, _ = await _enrich_tvdb_seasons(
        [base_season_meta] if base_season_meta else [],
        mappings,
        tvdb_api_key=api_key,
        tvdb_language=tvdb_lang,
        series_tmdb_id=series_tmdb_id,
        tmdb_api_key=tmdb_api_key,
        metadata_language=metadata_lang,
    )
    season_meta = enriched_seasons[0] if enriched_seasons else base_season_meta
    show_data["seasons"] = [
        season_meta if season["season_number"] == season_number else season
        for season in show_data["seasons"]
    ]
    mapping_by_tvdb_id = {mapping.tvdb_id: mapping for mapping in mappings}
    mapping_by_position = {
        (mapping.tvdb_season_number, mapping.tvdb_episode_number): mapping
        for mapping in mappings
    }

    local_ep_map: dict[tuple[int, int], Media] = {}
    if show:
        ep_result = await db.execute(
            select(Media).where(
                Media.show_id == show.id,
                Media.media_type == MediaType.episode,
            )
        )
        local_eps = list(ep_result.scalars().all())
        local_ep_map = {
            (episode.season_number, episode.episode_number): episode
            for episode in local_eps
            if episode.season_number is not None and episode.episode_number is not None
        }

    mapped_rows: list[tuple[dict, EpisodeOrderMapping | None, Media | None]] = []
    for episode in eps:
        mapping = mapping_by_tvdb_id.get(episode.get("tvdb_id"))
        if not mapping:
            mapping = mapping_by_position.get(
                (season_number, episode.get("episode_number"))
            )
        if mapping:
            local_episode = local_ep_map.get(
                (mapping.tmdb_season_number, mapping.tmdb_episode_number)
            )
        else:
            # No mapping for this specific TVDB episode — fall back to matching
            # by raw position rather than reporting it as missing from the library.
            local_episode = local_ep_map.get(
                (season_number, episode.get("episode_number"))
            )
        mapped_rows.append((episode, mapping, local_episode))

    local_media_ids = list({
        local_episode.id
        for _, _, local_episode in mapped_rows
        if local_episode
    })
    watched_ep_ids: set[int] = set()
    collected_ep_ids: set[int] = set()
    episode_ratings: dict[int, float] = {}
    if local_media_ids:
        watched_q = await db.execute(
            select(WatchEvent.media_id)
            .where(
                WatchEvent.user_id == current_user.id,
                WatchEvent.media_id.in_(local_media_ids),
            )
            .distinct()
        )
        watched_ep_ids = {row[0] for row in watched_q.all()}
        collected_q = await db.execute(
            select(Collection.media_id)
            .where(
                Collection.user_id == current_user.id,
                Collection.media_id.in_(local_media_ids),
            )
            .distinct()
        )
        collected_ep_ids = {row[0] for row in collected_q.all()}
        episode_ratings_q = await db.execute(
            select(Rating.media_id, Rating.rating).where(
                Rating.user_id == current_user.id,
                Rating.media_id.in_(local_media_ids),
                Rating.season_number.is_(None),
            )
        )
        episode_ratings = dict(episode_ratings_q.all())

    season_user_rating = None
    if series_tmdb_id:
        show_media_result = await db.execute(
            select(Media).where(
                Media.tmdb_id == series_tmdb_id,
                Media.media_type == MediaType.series,
            )
        )
        show_media = show_media_result.scalar_one_or_none()
        if show_media:
            season_rating_result = await db.execute(
                select(Rating.rating).where(
                    Rating.user_id == current_user.id,
                    Rating.media_id == show_media.id,
                    Rating.season_number == season_number,
                    Rating.episode_order == "tvdb",
                )
            )
            season_user_rating = season_rating_result.scalar_one_or_none()

    enriched_eps = []
    for episode, mapping, local_episode in mapped_rows:
        enriched_eps.append({
            **episode,
            "id": local_episode.id if local_episode else None,
            "tmdb_id": mapping.tmdb_episode_id if mapping else (
                local_episode.tmdb_id if local_episode else None
            ),
            "show_tmdb_id": series_tmdb_id,
            "tmdb_season_number": mapping.tmdb_season_number if mapping else season_number,
            "tmdb_episode_number": mapping.tmdb_episode_number if mapping else episode.get("episode_number"),
            "in_library": local_episode.id in collected_ep_ids if local_episode else False,
            "watched": local_episode.id in watched_ep_ids if local_episode else False,
            "user_rating": episode_ratings.get(local_episode.id) if local_episode else None,
            "in_lists": [],
        })

    total_eps = len(eps)
    season_in_library = bool(collected_ep_ids)
    season_collection_pct = min(100, int((len(collected_ep_ids) / total_eps) * 100)) if total_eps else 0
    season_watched = total_eps > 0 and len(watched_ep_ids) >= total_eps
    season_watch_pct = min(100, int((len(watched_ep_ids) / total_eps) * 100)) if total_eps else 0

    return {
        "tvdb_id": tvdb_id,
        "season_number": season_number,
        "name": season_meta.get("name") or f"Season {season_number}",
        "overview": season_meta.get("overview"),
        "tmdb_rating": season_meta.get("tmdb_rating"),
        "poster_path": season_meta.get("poster_path"),
        "backdrop_path": show_data["backdrop_path"],
        "air_date": season_meta.get("air_date"),
        "episodes": enriched_eps,
        "season_in_library": season_in_library,
        "season_watched": season_watched,
        "season_watch_pct": season_watch_pct,
        "season_collection_pct": season_collection_pct,
        "season_user_rating": season_user_rating,
        "show_in_library": show is not None,
        "show": {
            "id": show.id if show else None,
            "tvdb_id": tvdb_id,
            "tmdb_id": series_tmdb_id,
            "episode_order": "tvdb",
            "title": show_data["title"],
            "poster_path": show_data["poster_path"],
            "backdrop_path": show_data["backdrop_path"],
            "seasons_meta": show_data["seasons"],
        },
    }


@router.get("/tvdb/{tvdb_id}/season/{season_number}/episode/{episode_number}")
async def get_tvdb_episode(
    tvdb_id: int,
    season_number: int,
    episode_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key = await get_user_tvdb_key(db, current_user.id)
    if not api_key:
        raise HTTPException(status_code=400, detail="TVDB API key not configured")

    metadata_lang = await get_user_metadata_language(db, current_user.id)
    tvdb_lang = tvdb_client.tvdb_language(metadata_lang)

    try:
        raw_series, raw_episodes = await asyncio.gather(
            tvdb_client.get_series(tvdb_id, api_key),
            tvdb_client.get_series_episodes(tvdb_id, season_number, api_key, language=tvdb_lang),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TVDB fetch failed: {e}")

    show_data = tvdb_client.format_series(raw_series, language=tvdb_lang)
    eps = [tvdb_client.format_episode(e) for e in raw_episodes]
    ep_data = next((e for e in eps if e.get("episode_number") == episode_number), None)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Episode not found")

    series_tmdb_id = show_data.get("tmdb_id_cross")
    series_tmdb_id = int(series_tmdb_id) if series_tmdb_id else None
    show_result = await db.execute(
        select(ShowModel).where(
            or_(
                ShowModel.tvdb_id == tvdb_id,
                ShowModel.tmdb_id == series_tmdb_id,
            )
        )
    )
    show = show_result.scalar_one_or_none()
    mapping_result = await db.execute(
        select(EpisodeOrderMapping).where(
            EpisodeOrderMapping.series_tmdb_id == series_tmdb_id,
            or_(
                EpisodeOrderMapping.tvdb_id == ep_data.get("tvdb_id"),
                and_(
                    EpisodeOrderMapping.tvdb_season_number == season_number,
                    EpisodeOrderMapping.tvdb_episode_number == episode_number,
                ),
            ),
        )
    ) if series_tmdb_id else None
    mapping = mapping_result.scalars().first() if mapping_result else None
    canonical_season = mapping.tmdb_season_number if mapping else season_number
    canonical_episode = mapping.tmdb_episode_number if mapping else episode_number

    in_library = False
    watched = False
    user_rating = None
    local_ep_id = None
    local_ep = None
    library_info = None
    play_count = 0

    if show:
        local_ep_q = await db.execute(
            select(Media).where(
                Media.show_id == show.id,
                Media.media_type == MediaType.episode,
                Media.season_number == canonical_season,
                Media.episode_number == canonical_episode,
            )
        )
        local_ep = local_ep_q.scalars().first()
        if local_ep:
            local_ep_id = local_ep.id
            coll_q = await db.execute(
                select(func.count()).select_from(Collection).where(
                    Collection.media_id == local_ep.id,
                    Collection.user_id == current_user.id,
                )
            )
            in_library = coll_q.scalar_one() > 0
            watched_q = await db.execute(
                select(func.count()).select_from(WatchEvent).where(
                    WatchEvent.media_id == local_ep.id,
                    WatchEvent.user_id == current_user.id,
                )
            )
            play_count = watched_q.scalar_one()
            watched = play_count > 0
            rating_q = await db.execute(
                select(Rating.rating).where(
                    Rating.media_id == local_ep.id,
                    Rating.user_id == current_user.id,
                    Rating.season_number.is_(None),
                )
            )
            user_rating = rating_q.scalar_one_or_none()

            if in_library:
                coll_file_q = await db.execute(
                    select(CollectionFile)
                    .join(Collection, Collection.id == CollectionFile.collection_id)
                    .where(
                        Collection.media_id == local_ep.id,
                        Collection.user_id == current_user.id,
                    )
                    .order_by(CollectionFile.added_at.desc())
                )
                coll_file = coll_file_q.scalars().first()
                if coll_file:
                    library_info = {
                        "resolution": coll_file.resolution,
                        "video_codec": coll_file.video_codec,
                        "audio_codec": coll_file.audio_codec,
                        "audio_channels": coll_file.audio_channels,
                        "audio_languages": coll_file.audio_languages,
                        "subtitle_languages": coll_file.subtitle_languages,
                    }

    cast = tvdb_client.format_cast(raw_series)
    season_meta = next((s for s in show_data["seasons"] if s["season_number"] == season_number), {})

    return {
        **ep_data,
        "id": local_ep_id,
        "tmdb_id": mapping.tmdb_episode_id if mapping else (
            local_ep.tmdb_id if local_ep else None
        ),
        "show_tmdb_id": series_tmdb_id,
        "tmdb_season_number": canonical_season,
        "tmdb_episode_number": canonical_episode,
        "in_library": in_library,
        "watched": watched,
        "user_rating": user_rating,
        "play_count": play_count,
        "in_lists": [],
        "library": library_info,
        "cast": cast,
        "episodes": [{"episode_number": e["episode_number"], "name": e["name"]} for e in eps],
        "show": {
            "id": show.id if show else None,
            "tvdb_id": tvdb_id,
            "tmdb_id": series_tmdb_id,
            "episode_order": "tvdb",
            "title": show_data["title"],
            "poster_path": show_data["poster_path"],
            "backdrop_path": show_data["backdrop_path"],
        },
        "season": {
            "name": season_meta.get("name") or f"Season {season_number}",
            "season_number": season_number,
            "poster_path": season_meta.get("poster_path"),
        },
    }


@router.post("/tvdb/{tvdb_id}/refresh")
async def refresh_tvdb_show_metadata(
    tvdb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    api_key = await get_user_tvdb_key(db, current_user.id)
    if not api_key:
        raise HTTPException(status_code=400, detail="TVDB API key not configured")

    show_result = await db.execute(select(ShowModel).where(ShowModel.tvdb_id == tvdb_id))
    show = show_result.scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found in local library")

    try:
        raw = await tvdb_client.get_series(tvdb_id, api_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TVDB fetch failed: {e}")

    if show.tmdb_id:
        tmdb_api_key = await get_user_tmdb_key(db, current_user.id)
        if not check_tmdb_key(tmdb_api_key):
            raise HTTPException(status_code=400, detail="TMDB API key not configured")
        try:
            mapping = await ensure_episode_order_mapping(
                db,
                show.tmdb_id,
                tmdb_api_key,
                api_key,
                force=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Episode mapping failed: {exc}")
        await db.commit()
        return {
            "message": "Episode mapping refreshed successfully",
            "mapping": mapping,
        }

    show_fmt = tvdb_client.format_series(raw)
    show.title = show_fmt["title"] or show.title
    show.original_title = show_fmt.get("original_title")
    show.overview = show_fmt.get("overview")
    show.poster_path = show_fmt.get("poster_path")
    show.backdrop_path = show_fmt.get("backdrop_path")
    show.status = show_fmt.get("status")
    show.first_air_date = show_fmt.get("first_air_date")
    show.last_air_date = show_fmt.get("last_air_date")
    show.tmdb_data = {
        **(show.tmdb_data or {}),
        "seasons": show_fmt.get("seasons", []),
        "genres": show_fmt.get("genres", []),
        "source": "tvdb",
    }
    await db.commit()
    return {"message": "Metadata refreshed successfully"}
