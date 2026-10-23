import asyncio
import functools
import time
from collections import defaultdict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, case, or_
from sqlalchemy.orm import aliased
from datetime import date as DateType, timedelta as TimeDelta
from typing import Optional

from db import get_db, AsyncSessionLocal
from core import tmdb as tmdb_client
from core.translations import upsert_media_translation, upsert_show_translation

from dependencies import get_current_user, get_optional_user
from models.users import User
from models.profile import UserProfileData, PrivacyLevel
from models.events import WatchEvent
from models.collection import Collection
from models.media import Media
from models.ratings import Rating
from models.show import Show as ShowModel
from models.comments import Comment as CommentModel
from models.lists import List as ListModel, ListItem
from models.follows import Follow
from core.config import settings
import schemas

router = APIRouter()


async def _check_profile_access(user_id: int, current_user, db: AsyncSession):
    """Returns (user, profile) or raises 404/403."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile_result = await db.execute(select(UserProfileData).where(UserProfileData.user_id == user_id))
    profile = profile_result.scalar_one_or_none()

    is_owner = current_user and current_user.id == user_id
    is_admin = current_user and current_user.role == "admin"
    privacy = profile.privacy_level if profile else PrivacyLevel.private

    is_mutual_follow = False
    if current_user and not is_owner and privacy == PrivacyLevel.friends_only:
        mutual_q = await db.execute(
            select(func.count())
            .select_from(Follow)
            .where(Follow.follower_id == current_user.id, Follow.following_id == user_id)
            .where(
                select(Follow.id)
                .where(Follow.follower_id == user_id, Follow.following_id == current_user.id)
                .exists()
            )
        )
        is_mutual_follow = mutual_q.scalar_one() > 0

    if not (is_owner or is_admin or privacy == PrivacyLevel.public or is_mutual_follow):
        raise HTTPException(status_code=403, detail="This profile is private")

    return user, profile


@router.get("/me", response_model=schemas.UserProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProfileData).where(UserProfileData.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        return schemas.UserProfileResponse()
    resp = schemas.UserProfileResponse.model_validate(profile)
    if profile.avatar_path:
        resp.avatar_url = f"/profile/avatar/{current_user.id}"
    return resp


@router.patch("/me", response_model=schemas.UserProfileResponse)
async def update_profile(
    body: schemas.UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserProfileData).where(UserProfileData.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = UserProfileData(user_id=current_user.id)
        db.add(profile)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)
    return profile


_ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}
_AVATAR_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post("/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in _ALLOWED_AVATAR_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type. Use JPEG, PNG or WebP.")

    content = await file.read()
    if len(content) > _MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 5 MB.")

    ext = _AVATAR_EXT[file.content_type]
    avatars_dir = settings.data_dir / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)

    # Remove any existing avatar for this user (may have different extension)
    for old in avatars_dir.glob(f"{current_user.id}.*"):
        old.unlink(missing_ok=True)

    fname = f"{current_user.id}.{ext}"
    (avatars_dir / fname).write_bytes(content)

    result = await db.execute(select(UserProfileData).where(UserProfileData.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = UserProfileData(user_id=current_user.id)
        db.add(profile)
    profile.avatar_path = fname
    await db.commit()

    return {"avatar_url": f"/profile/avatar/{current_user.id}"}


@router.delete("/me/avatar")
async def delete_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserProfileData).where(UserProfileData.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if profile and profile.avatar_path:
        avatars_dir = settings.data_dir / "avatars"
        for old in avatars_dir.glob(f"{current_user.id}.*"):
            old.unlink(missing_ok=True)
        profile.avatar_path = None
        await db.commit()
    return {"status": "ok"}


# ── Translation backfill ──────────────────────────────────────────────────────

_TRANSLATION_BACKFILL: dict[int, dict] = {}


@router.post("/me/translations/backfill")
async def start_translation_backfill(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user.id
    if _TRANSLATION_BACKFILL.get(user_id, {}).get("running"):
        raise HTTPException(status_code=409, detail="Backfill already running")

    profile_result = await db.execute(select(UserProfileData).where(UserProfileData.user_id == user_id))
    profile = profile_result.scalar_one_or_none()
    if not profile or not profile.metadata_language:
        raise HTTPException(status_code=400, detail="No metadata language set")

    language = profile.metadata_language

    from routers.media import get_user_tmdb_key
    tmdb_key = await get_user_tmdb_key(db, user_id)
    if not tmdb_key:
        raise HTTPException(status_code=400, detail="TMDB API key not configured")

    _TRANSLATION_BACKFILL[user_id] = {
        "running": True, "progress": 0, "total": 0, "done": False, "error": None,
    }
    background_tasks.add_task(_run_translation_backfill, user_id, language, tmdb_key)
    return {"status": "started"}


@router.get("/me/translations/backfill/status")
async def get_backfill_status(current_user: User = Depends(get_current_user)):
    state = _TRANSLATION_BACKFILL.get(current_user.id)
    if not state:
        return {"running": False, "progress": 0, "total": 0, "done": False, "error": None}
    return state


@router.delete("/me/translations/backfill")
async def abort_backfill(current_user: User = Depends(get_current_user)):
    state = _TRANSLATION_BACKFILL.get(current_user.id)
    if state and state.get("running"):
        state["abort"] = True
    return {"status": "ok"}


async def _run_translation_backfill(user_id: int, language: str, tmdb_key: str) -> None:
    state = _TRANSLATION_BACKFILL[user_id]
    try:
        # ── 1. Read all user-linked items from DB ─────────────────────────────
        async with AsyncSessionLocal() as db:
            has_items_filter = or_(
                Media.id.in_(select(Collection.media_id).where(Collection.user_id == user_id)),
                Media.id.in_(
                    select(WatchEvent.media_id).where(
                        WatchEvent.user_id == user_id, WatchEvent.completed == True
                    )
                ),
            )

            movie_q = await db.execute(
                select(Media.id, Media.tmdb_id)
                .where(Media.media_type == "movie", Media.tmdb_id.isnot(None), has_items_filter)
                .distinct()
            )
            movies = movie_q.all()

            show_q = await db.execute(
                select(ShowModel.id, ShowModel.tmdb_id)
                .join(Media, Media.show_id == ShowModel.id)
                .where(Media.media_type == "episode", ShowModel.tmdb_id.isnot(None), has_items_filter)
                .distinct()
            )
            shows = show_q.all()

            ep_q = await db.execute(
                select(Media.id, Media.episode_number, Media.season_number, ShowModel.tmdb_id.label("show_tmdb_id"))
                .join(ShowModel, Media.show_id == ShowModel.id)
                .where(
                    Media.media_type == "episode",
                    Media.season_number.isnot(None),
                    Media.episode_number.isnot(None),
                    ShowModel.tmdb_id.isnot(None),
                    has_items_filter,
                )
                .distinct()
            )
            eps = ep_q.all()

        season_map: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for media_id, ep_num, season_num, show_tmdb_id in eps:
            season_map[(show_tmdb_id, season_num)].append((media_id, ep_num))

        total = len(movies) + len(shows) + len(season_map)
        state["total"] = total
        if total == 0:
            return

        # ── 2. Fetch all translations from TMDB in parallel ───────────────────
        sem = asyncio.Semaphore(5)

        # Collected results written to DB after all fetches complete
        movie_results: list[tuple[int, dict]] = []   # (media_id, data)
        show_results: list[tuple[int, dict]] = []    # (show_id, data)
        season_results: list[tuple[list[tuple[int, int]], dict]] = []  # (ep_list, season_data)

        async def fetch_movie(media_id: int, tmdb_id: int) -> None:
            async with sem:
                if not state.get("abort"):
                    try:
                        data = await tmdb_client.get_movie_light(tmdb_id, api_key=tmdb_key, language=language)
                        movie_results.append((media_id, data))
                    except Exception:
                        pass
            state["progress"] += 1

        async def fetch_show(show_id: int, show_tmdb_id: int) -> None:
            async with sem:
                if not state.get("abort"):
                    try:
                        data = await tmdb_client.get_show_light(show_tmdb_id, api_key=tmdb_key, language=language)
                        show_results.append((show_id, data))
                    except Exception:
                        pass
            state["progress"] += 1

        async def fetch_season(show_tmdb_id: int, season_num: int, ep_list: list[tuple[int, int]]) -> None:
            async with sem:
                if not state.get("abort"):
                    try:
                        data = await tmdb_client.get_season(show_tmdb_id, season_num, api_key=tmdb_key, language=language)
                        season_results.append((ep_list, data))
                    except Exception:
                        pass
            state["progress"] += 1

        await asyncio.gather(
            *[fetch_movie(mid, tid) for mid, tid in movies],
            *[fetch_show(sid, stid) for sid, stid in shows],
            *[fetch_season(stid, snum, ep_list) for (stid, snum), ep_list in season_map.items()],
        )

        # ── 3. Write collected results to DB in one batch ─────────────────────
        async with AsyncSessionLocal() as db:
            for media_id, data in movie_results:
                await upsert_media_translation(
                    db, media_id, language,
                    data.get("title"), data.get("overview"),
                    data.get("tagline"), data.get("poster_path"),
                )
            for show_id, data in show_results:
                await upsert_show_translation(
                    db, show_id, language,
                    data.get("name"), data.get("overview"),
                    data.get("tagline"), data.get("poster_path"),
                )
            for ep_list, season_data in season_results:
                ep_by_num = {ep["episode_number"]: ep for ep in (season_data.get("episodes") or [])}
                for media_id, ep_num in ep_list:
                    ep_data = ep_by_num.get(ep_num)
                    if ep_data:
                        await upsert_media_translation(
                            db, media_id, language,
                            ep_data.get("name"), ep_data.get("overview"),
                            None, ep_data.get("still_path"),
                        )
            await db.commit()

    except Exception as e:
        state["error"] = str(e)
    finally:
        state["running"] = False
        state["done"] = True


# ─────────────────────────────────────────────────────────────────────────────

@router.get("/avatar/{user_id}")
async def get_avatar(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserProfileData).where(UserProfileData.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile or not profile.avatar_path:
        raise HTTPException(status_code=404, detail="No avatar")

    path = settings.data_dir / "avatars" / profile.avatar_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Avatar file not found")

    ext = path.suffix.lstrip(".")
    media_type = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return FileResponse(str(path), media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})


@router.get("/search")
async def search_users(
    q: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_user),
):
    if len(q.strip()) < 1:
        return {"results": []}

    pattern = f"%{q.strip()}%"

    # Match on username or display_name, only public profiles (+ own profile)
    users_q = await db.execute(
        select(User, UserProfileData)
        .outerjoin(UserProfileData, UserProfileData.user_id == User.id)
        .where(
            (User.username.ilike(pattern)) | (UserProfileData.display_name.ilike(pattern)),
            (UserProfileData.privacy_level.in_([PrivacyLevel.public, PrivacyLevel.friends_only]))
            | (User.id == (current_user.id if current_user else -1)),
        )
        .order_by(User.username)
        .limit(24)
    )
    rows = users_q.all()
    if not rows:
        return {"results": []}

    user_ids = [u.id for u, _ in rows]

    # Batch stats
    movies_q = await db.execute(
        select(WatchEvent.user_id, func.count(func.distinct(WatchEvent.media_id)))
        .join(Media, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id.in_(user_ids), WatchEvent.completed == True, Media.media_type == "movie")
        .group_by(WatchEvent.user_id)
    )
    movies_map = dict(movies_q.all())

    shows_q = await db.execute(
        select(WatchEvent.user_id, func.count(func.distinct(ShowModel.id)))
        .join(Media, WatchEvent.media_id == Media.id)
        .join(ShowModel, Media.show_id == ShowModel.id)
        .where(WatchEvent.user_id.in_(user_ids), WatchEvent.completed == True)
        .group_by(WatchEvent.user_id)
    )
    shows_map = dict(shows_q.all())

    collected_q = await db.execute(
        select(Collection.user_id, func.count(func.distinct(Collection.media_id)))
        .where(Collection.user_id.in_(user_ids))
        .group_by(Collection.user_id)
    )
    collected_map = dict(collected_q.all())

    rated_q = await db.execute(
        select(Rating.user_id, func.count(Rating.id))
        .where(Rating.user_id.in_(user_ids), Rating.rating.isnot(None))
        .group_by(Rating.user_id)
    )
    rated_map = dict(rated_q.all())

    followers_q = await db.execute(
        select(Follow.following_id, func.count(Follow.id))
        .where(Follow.following_id.in_(user_ids))
        .group_by(Follow.following_id)
    )
    followers_map = dict(followers_q.all())

    # Which of these users is the current viewer already following?
    following_set: set[int] = set()
    if current_user:
        fol_q = await db.execute(
            select(Follow.following_id)
            .where(Follow.follower_id == current_user.id, Follow.following_id.in_(user_ids))
        )
        following_set = {row[0] for row in fol_q.all()}

    results = []
    for u, p in rows:
        display_name = p.display_name if p and p.display_name else u.username
        results.append({
            "id": u.id,
            "username": u.username,
            "display_name": display_name,
            "avatar_url": f"/profile/avatar/{u.id}" if (p and p.avatar_path) else None,
            "country": p.country if p else None,
            "movies_watched": movies_map.get(u.id, 0),
            "shows_watched": shows_map.get(u.id, 0),
            "total_collected": collected_map.get(u.id, 0),
            "total_rated": rated_map.get(u.id, 0),
            "follower_count": followers_map.get(u.id, 0),
            "is_following": u.id in following_set,
            "is_self": current_user is not None and current_user.id == u.id,
        })

    return {"results": results}


@router.post("/{user_id}/follow")
async def follow_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="You cannot follow yourself.")
    target = await db.execute(select(User).where(User.id == user_id))
    if not target.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found.")
    existing = await db.execute(
        select(Follow).where(Follow.follower_id == current_user.id, Follow.following_id == user_id)
    )
    if not existing.scalar_one_or_none():
        db.add(Follow(follower_id=current_user.id, following_id=user_id))
        await db.commit()
    return {"status": "following"}


@router.delete("/{user_id}/follow")
async def unfollow_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import delete as sa_delete
    await db.execute(
        sa_delete(Follow).where(Follow.follower_id == current_user.id, Follow.following_id == user_id)
    )
    await db.commit()
    return {"status": "unfollowed"}


@router.get("/{user_id}", response_model=schemas.PublicProfileResponse)
async def get_public_profile(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_user),
):
    user, profile = await _check_profile_access(user_id, current_user, db)
    is_owner = current_user and current_user.id == user_id
    is_admin = current_user and current_user.role == "admin"

    # --- Stats ---
    watched_q = await db.execute(
        select(func.count(func.distinct(WatchEvent.media_id)))
        .where(WatchEvent.user_id == user_id, WatchEvent.completed == True)
    )
    total_watched = watched_q.scalar_one()

    collected_q = await db.execute(
        select(func.count(func.distinct(Collection.media_id)))
        .where(Collection.user_id == user_id)
    )
    total_collected = collected_q.scalar_one()

    movies_q = await db.execute(
        select(func.count(func.distinct(WatchEvent.media_id)))
        .join(Media, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, WatchEvent.completed == True, Media.media_type == "movie")
    )
    movies_watched = movies_q.scalar_one()

    shows_q = await db.execute(
        select(func.count(func.distinct(ShowModel.id)))
        .join(Media, Media.show_id == ShowModel.id)
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, WatchEvent.completed == True)
    )
    shows_watched = shows_q.scalar_one()

    rated_q = await db.execute(
        select(func.count(Rating.id))
        .where(Rating.user_id == user_id, Rating.rating.isnot(None))
    )
    total_rated = rated_q.scalar_one()

    # --- Recently Watched Movies ---
    rw_movies_q = await db.execute(
        select(WatchEvent, Media)
        .join(Media, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == user_id,
            WatchEvent.completed == True,
            Media.media_type == "movie",
            WatchEvent.watched_at.isnot(None),
        )
        .order_by(WatchEvent.watched_at.desc())
        .limit(12)
    )
    recently_watched_movies = [
        {
            "tmdb_id": media.tmdb_id,
            "media_type": "movie",
            "title": media.title,
            "poster_path": media.poster_path,
            "watched_at": we.watched_at.isoformat(),
        }
        for we, media in rw_movies_q.all()
    ]

    # --- Recently Watched Shows (episodes) ---
    rw_shows_q = await db.execute(
        select(WatchEvent, Media, ShowModel)
        .join(Media, WatchEvent.media_id == Media.id)
        .outerjoin(ShowModel, Media.show_id == ShowModel.id)
        .where(
            WatchEvent.user_id == user_id,
            WatchEvent.completed == True,
            Media.media_type == "episode",
            WatchEvent.watched_at.isnot(None),
        )
        .order_by(WatchEvent.watched_at.desc())
        .limit(12)
    )
    recently_watched_shows = [
        {
            "tmdb_id": media.tmdb_id,
            "media_type": "episode",
            "title": media.title,
            "backdrop_path": show.backdrop_path if show else media.backdrop_path,
            "poster_path": show.poster_path if show else media.poster_path,
            "watched_at": we.watched_at.isoformat(),
            "show_title": show.title if show else None,
            "show_tmdb_id": show.tmdb_id if show else None,
            "season_number": media.season_number,
            "episode_number": media.episode_number,
        }
        for we, media, show in rw_shows_q.all()
    ]

    # --- Top Rated Movies ---
    tr_movies_q = await db.execute(
        select(Rating, Media)
        .join(Media, Rating.media_id == Media.id)
        .where(
            Rating.user_id == user_id,
            Rating.season_number.is_(None),
            Media.media_type == "movie",
            Rating.rating.isnot(None),
        )
        .order_by(Rating.rating.desc())
        .limit(16)
    )
    top_rated_movies = [
        {
            "tmdb_id": media.tmdb_id,
            "media_type": "movie",
            "title": media.title,
            "poster_path": media.poster_path,
            "user_rating": rating.rating,
        }
        for rating, media in tr_movies_q.all()
    ]

    # --- Top Rated Shows ---
    tr_shows_q = await db.execute(
        select(Rating, Media, ShowModel)
        .join(Media, Rating.media_id == Media.id)
        .outerjoin(ShowModel, (Media.media_type == "series") & (Media.tmdb_id == ShowModel.tmdb_id))
        .where(
            Rating.user_id == user_id,
            Rating.season_number.is_(None),
            Media.media_type == "series",
            Rating.rating.isnot(None),
        )
        .order_by(Rating.rating.desc())
        .limit(16)
    )
    top_rated_shows = [
        {
            "tmdb_id": media.tmdb_id,
            "media_type": "series",
            "title": media.title,
            "poster_path": show.poster_path if show else media.poster_path,
            "user_rating": rating.rating,
        }
        for rating, media, show in tr_shows_q.all()
    ]

    # --- Recent Comments ---
    recent_comments_q = await db.execute(
        select(CommentModel)
        .where(CommentModel.user_id == user_id)
        .order_by(CommentModel.created_at.desc())
        .limit(5)
    )
    comments_list = recent_comments_q.scalars().all()

    # Batch resolve titles for comments
    show_tmdb_ids = list({c.tmdb_id for c in comments_list if c.media_type in ("series", "season", "episode")})
    movie_tmdb_ids = list({c.tmdb_id for c in comments_list if c.media_type == "movie"})

    show_titles: dict[int, tuple[str, str | None]] = {}
    movie_titles: dict[int, tuple[str, str | None]] = {}

    if show_tmdb_ids:
        sq = await db.execute(
            select(ShowModel.tmdb_id, ShowModel.title, ShowModel.poster_path)
            .where(ShowModel.tmdb_id.in_(show_tmdb_ids))
        )
        for tmdb_id, title, poster_path in sq.all():
            show_titles[tmdb_id] = (title, poster_path)

    if movie_tmdb_ids:
        mq = await db.execute(
            select(Media.tmdb_id, Media.title, Media.poster_path)
            .where(Media.tmdb_id.in_(movie_tmdb_ids), Media.media_type == "movie")
            .group_by(Media.tmdb_id, Media.title, Media.poster_path)
        )
        for tmdb_id, title, poster_path in mq.all():
            movie_titles[tmdb_id] = (title, poster_path)

    recent_comments = []
    for c in comments_list:
        if c.media_type in ("series", "season", "episode"):
            info = show_titles.get(c.tmdb_id)
        else:
            info = movie_titles.get(c.tmdb_id)
        recent_comments.append({
            "id": c.id,
            "content": c.content,
            "media_type": c.media_type,
            "tmdb_id": c.tmdb_id,
            "season_number": c.season_number,
            "episode_number": c.episode_number,
            "title": info[0] if info else None,
            "poster_path": info[1] if info else None,
            "created_at": c.created_at.isoformat(),
        })

    # --- Followers / Following ---
    follower_count_q = await db.execute(
        select(func.count(Follow.id)).where(Follow.following_id == user_id)
    )
    follower_count = follower_count_q.scalar_one()

    following_count_q = await db.execute(
        select(func.count(Follow.id)).where(Follow.follower_id == user_id)
    )
    following_count = following_count_q.scalar_one()

    # Preview: up to 8 of each, with display_name and avatar
    followers_q = await db.execute(
        select(User, UserProfileData)
        .join(Follow, Follow.follower_id == User.id)
        .outerjoin(UserProfileData, UserProfileData.user_id == User.id)
        .where(Follow.following_id == user_id)
        .order_by(Follow.created_at.desc())
        .limit(8)
    )
    followers_preview = [
        {
            "id": u.id,
            "display_name": p.display_name if p and p.display_name else u.username,
            "avatar_url": f"/profile/avatar/{u.id}" if (p and p.avatar_path) else None,
        }
        for u, p in followers_q.all()
    ]

    following_q = await db.execute(
        select(User, UserProfileData)
        .join(Follow, Follow.following_id == User.id)
        .outerjoin(UserProfileData, UserProfileData.user_id == User.id)
        .where(Follow.follower_id == user_id)
        .order_by(Follow.created_at.desc())
        .limit(8)
    )
    following_preview = [
        {
            "id": u.id,
            "display_name": p.display_name if p and p.display_name else u.username,
            "avatar_url": f"/profile/avatar/{u.id}" if (p and p.avatar_path) else None,
        }
        for u, p in following_q.all()
    ]

    is_following = False
    if current_user and current_user.id != user_id:
        follow_check = await db.execute(
            select(Follow).where(Follow.follower_id == current_user.id, Follow.following_id == user_id)
        )
        is_following = follow_check.scalar_one_or_none() is not None

    # --- Lists ---
    lists_query = (
        select(
            ListModel.id,
            ListModel.name,
            ListModel.description,
            ListModel.privacy_level,
            ListModel.updated_at,
            func.count(ListModel.items).label("item_count"),
        )
        .outerjoin(ListModel.items)
        .where(ListModel.user_id == user_id)
        .group_by(ListModel.id)
        .order_by(ListModel.updated_at.desc())
    )
    if not (is_owner or is_admin):
        lists_query = lists_query.where(ListModel.privacy_level == PrivacyLevel.public)

    lists_result = await db.execute(lists_query)
    lists_rows = lists_result.all()
    list_ids = [row.id for row in lists_rows]

    # Fetch up to 3 preview posters per list using ROW_NUMBER
    posters_by_list: dict[int, list[dict]] = {}
    if list_ids:
        ShowAlias = aliased(ShowModel)
        rn = func.row_number().over(
            partition_by=ListItem.list_id,
            order_by=ListItem.added_at,
        ).label("rn")
        poster_col = case(
            (Media.poster_path.isnot(None), Media.poster_path),
            else_=ShowAlias.poster_path,
        ).label("poster")
        inner = (
            select(ListItem.list_id, poster_col, Media.adult, rn)
            .join(Media, ListItem.media_id == Media.id)
            .outerjoin(ShowAlias, ShowAlias.tmdb_id == Media.tmdb_id)
            .where(ListItem.list_id.in_(list_ids))
        ).subquery()
        posters_q = await db.execute(
            select(inner.c.list_id, inner.c.poster, inner.c.adult)
            .where(inner.c.rn <= 3)
            .where(inner.c.poster.isnot(None))
        )
        for row in posters_q.all():
            posters_by_list.setdefault(row.list_id, []).append({"url": row.poster, "adult": row.adult})

    user_lists = [
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "privacy_level": row.privacy_level.value,
            "item_count": row.item_count,
            "updated_at": row.updated_at.isoformat(),
            "preview_posters": posters_by_list.get(row.id, []),
        }
        for row in lists_rows
    ]

    # Compute display_name from the already-loaded profile to avoid lazy-load in async context
    display_name = (profile.display_name if profile and profile.display_name else user.username)

    return {
        "id": user.id,
        "username": user.username,
        "display_name": display_name,
        "avatar_url": f"/profile/avatar/{user.id}" if (profile and profile.avatar_path) else None,
        "bio": profile.bio if profile else None,
        "country": profile.country if profile else None,
        "movie_genres": profile.movie_genres if profile else [],
        "show_genres": profile.show_genres if profile else [],
        "created_at": user.created_at,
        "total_watched": total_watched,
        "total_collected": total_collected,
        "movies_watched": movies_watched,
        "shows_watched": shows_watched,
        "total_rated": total_rated,
        "recently_watched_movies": recently_watched_movies,
        "recently_watched_shows": recently_watched_shows,
        "top_rated_movies": top_rated_movies,
        "top_rated_shows": top_rated_shows,
        "recent_comments": recent_comments,
        "lists": user_lists,
        "follower_count": follower_count,
        "following_count": following_count,
        "followers": followers_preview,
        "following": following_preview,
        "is_following": is_following,
    }


@router.get("/{user_id}/stats")
async def get_user_stats(
    user_id: int,
    since: Optional[DateType] = None,
    until: Optional[DateType] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_user),
):
    await _check_profile_access(user_id, current_user, db)

    # Date range filters applied to all WatchEvent queries
    date_filters = [WatchEvent.completed == True]
    if since:
        date_filters.append(WatchEvent.watched_at >= since)
    if until:
        date_filters.append(WatchEvent.watched_at < until + TimeDelta(days=1))
    # Additional filter for anything bucketed/grouped by watched_at (activity charts,
    # weekday distribution, weeks-active count) — an unknown-dated event can't be
    # placed on a timeline, so it's excluded there while still counting in plain totals.
    dated_event_filters = [*date_filters, WatchEvent.watched_at.isnot(None)]

    # Activity granularity: daily for ranges ≤ 62 days, monthly otherwise
    if since and until:
        use_daily = (until - since).days <= 62
    else:
        use_daily = False
    activity_fmt = "YYYY-MM-DD" if use_daily else "YYYY-MM"

    # ── Watching ────────────────────────────────────────────────────────────
    movies_q = await db.execute(
        select(func.count(func.distinct(WatchEvent.media_id)))
        .join(Media, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, Media.media_type == "movie", *date_filters)
    )
    movies_watched = movies_q.scalar_one()
    episodes_q = await db.execute(
        select(func.count(func.distinct(WatchEvent.media_id)))
        .join(Media, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, Media.media_type == "episode", *date_filters)
    )
    episodes_watched = episodes_q.scalar_one()

    shows_q = await db.execute(
        select(func.count(func.distinct(ShowModel.id)))
        .join(Media, Media.show_id == ShowModel.id)
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, *date_filters)
    )
    shows_watched = shows_q.scalar_one()

    from sqlalchemy import Integer as SAInteger
    from sqlalchemy.types import Text as SAText
    # Episodes store runtime in tmdb_data['runtime']; movies use Media.runtime.
    # JSON (non-JSONB) has no .astext; cast to Text first, guard against JSON "null".
    json_runtime = func.cast(
        func.nullif(func.cast(Media.tmdb_data["runtime"], SAText), "null"),
        SAInteger,
    )
    effective_runtime = func.coalesce(Media.runtime, json_runtime)
    watch_time_q = await db.execute(
        select(func.coalesce(func.sum(effective_runtime), 0))
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, Media.media_type.in_(["movie", "episode"]), *date_filters)
    )
    total_watch_minutes = watch_time_q.scalar_one() or 0

    movie_watch_time_q = await db.execute(
        select(func.coalesce(func.sum(effective_runtime), 0))
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, Media.media_type == "movie", *date_filters)
    )
    movie_watch_minutes = movie_watch_time_q.scalar_one() or 0

    show_watch_time_q = await db.execute(
        select(func.coalesce(func.sum(effective_runtime), 0))
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, Media.media_type == "episode", *date_filters)
    )
    show_watch_minutes = show_watch_time_q.scalar_one() or 0

    # Activity — GROUP BY must use the expression, not the label alias (PostgreSQL requirement)
    activity_expr = func.to_char(WatchEvent.watched_at, activity_fmt)
    activity_q = await db.execute(
        select(
            activity_expr.label("period"),
            Media.media_type,
            func.count(func.distinct(WatchEvent.media_id)).label("cnt"),
        )
        .join(Media, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, Media.media_type.in_(["movie", "episode"]), *dated_event_filters)
        .group_by(activity_expr, Media.media_type)
        .order_by(activity_expr)
    )
    activity_rows = activity_q.all()
    activity_map: dict[str, dict] = {}
    for period_key, mtype, cnt in activity_rows:
        if period_key not in activity_map:
            activity_map[period_key] = {"month": period_key, "movies": 0, "episodes": 0}
        if mtype == "movie":
            activity_map[period_key]["movies"] = cnt
        else:
            activity_map[period_key]["episodes"] = cnt
    watch_activity = sorted(activity_map.values(), key=lambda x: x["month"])

    # Watch time per period (same granularity as activity)
    watch_time_activity_q = await db.execute(
        select(
            activity_expr.label("period"),
            Media.media_type,
            func.coalesce(func.sum(effective_runtime), 0).label("minutes"),
        )
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, Media.media_type.in_(["movie", "episode"]), *dated_event_filters)
        .group_by(activity_expr, Media.media_type)
        .order_by(activity_expr)
    )
    watch_time_map: dict[str, dict] = {}
    for period_key, mtype, minutes in watch_time_activity_q.all():
        if period_key not in watch_time_map:
            watch_time_map[period_key] = {"month": period_key, "movie_minutes": 0, "show_minutes": 0}
        if mtype == "movie":
            watch_time_map[period_key]["movie_minutes"] = int(minutes)
        else:
            watch_time_map[period_key]["show_minutes"] = int(minutes)
    watch_time_activity = sorted(watch_time_map.values(), key=lambda x: x["month"])

    # Average watches per weekday (0=Sun … 6=Sat)
    from sqlalchemy import extract
    dow_expr = func.extract("dow", WatchEvent.watched_at)
    dow_q = await db.execute(
        select(
            dow_expr.label("dow"),
            func.count(func.distinct(WatchEvent.media_id)).label("cnt"),
        )
        .join(Media, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, Media.media_type.in_(["movie", "episode"]), *dated_event_filters)
        .group_by(dow_expr)
        .order_by(dow_expr)
    )
    dow_raw = {int(row.dow): row.cnt for row in dow_q.all()}

    # Count distinct weeks to normalise
    weeks_q = await db.execute(
        select(func.count(func.distinct(func.to_char(WatchEvent.watched_at, "IYYY-IW"))))
        .join(Media, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, Media.media_type.in_(["movie", "episode"]), *dated_event_filters)
    )
    total_weeks = max(weeks_q.scalar_one() or 1, 1)
    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    weekday_activity = [
        {"day": day_names[i], "avg": round(dow_raw.get(i, 0) / total_weeks, 2)}
        for i in range(7)
    ]

    # ── Genre Activity ───────────────────────────────────────────────────────
    # Movies Genres
    movie_genres_q = await db.execute(
        select(Media.tmdb_data["genres"])
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == user_id,
            Media.media_type == "movie",
            Media.tmdb_data["genres"].isnot(None),
            *date_filters
        )
    )
    movie_genre_counts = {}
    for (genres_list,) in movie_genres_q.all():
        if genres_list:
            for g in genres_list:
                name = g["name"] if isinstance(g, dict) else g
                movie_genre_counts[name] = movie_genre_counts.get(name, 0) + 1

    # Shows Genres
    show_genres_q = await db.execute(
        select(ShowModel.tmdb_data["genres"])
        .join(Media, Media.show_id == ShowModel.id)
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == user_id,
            Media.media_type == "episode",
            ShowModel.tmdb_data["genres"].isnot(None),
            *date_filters
        )
    )
    show_genre_counts = {}
    for (genres_list,) in show_genres_q.all():
        if genres_list:
            for g in genres_list:
                name = g["name"] if isinstance(g, dict) else g
                show_genre_counts[name] = show_genre_counts.get(name, 0) + 1

    top_movie_genres = sorted(
        [{"name": k, "count": v} for k, v in movie_genre_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    top_show_genres = sorted(
        [{"name": k, "count": v} for k, v in show_genre_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    # ── Rating date filters mirror the watch event date filters but on rated_at
    rating_date_filters = []
    if since:
        rating_date_filters.append(Rating.rated_at >= since)
    if until:
        rating_date_filters.append(Rating.rated_at < until + TimeDelta(days=1))

    rating_dist_q = await db.execute(
        select(Rating.rating, func.count(Rating.id).label("cnt"))
        .where(Rating.user_id == user_id, Rating.rating.isnot(None), *rating_date_filters)
        .group_by(Rating.rating)
        .order_by(Rating.rating)
    )
    rating_distribution = [
        {"rating": float(r), "count": c} for r, c in rating_dist_q.all()
    ]

    avg_movie_rating_q = await db.execute(
        select(func.avg(Rating.rating))
        .join(Media, Rating.media_id == Media.id)
        .where(Rating.user_id == user_id, Rating.rating.isnot(None), Media.media_type == "movie", *rating_date_filters)
    )
    avg_movie_rating = avg_movie_rating_q.scalar_one()
    avg_movie_rating = round(float(avg_movie_rating), 2) if avg_movie_rating else None

    avg_show_rating_q = await db.execute(
        select(func.avg(Rating.rating))
        .join(Media, Rating.media_id == Media.id)
        .where(Rating.user_id == user_id, Rating.rating.isnot(None), Media.media_type == "series", *rating_date_filters)
    )
    avg_show_rating = avg_show_rating_q.scalar_one()
    avg_show_rating = round(float(avg_show_rating), 2) if avg_show_rating else None

    # ── Collection ───────────────────────────────────────────────────────────
    movies_collected_q = await db.execute(
        select(func.count(func.distinct(Collection.media_id)))
        .join(Media, Collection.media_id == Media.id)
        .where(Collection.user_id == user_id, Media.media_type == "movie")
    )
    movies_collected = movies_collected_q.scalar_one()

    episodes_collected_q = await db.execute(
        select(func.count(func.distinct(Collection.media_id)))
        .join(Media, Collection.media_id == Media.id)
        .where(Collection.user_id == user_id, Media.media_type == "episode")
    )
    episodes_collected = episodes_collected_q.scalar_one()

    shows_collected_q = await db.execute(
        select(func.count(func.distinct(ShowModel.id)))
        .join(Media, Media.show_id == ShowModel.id)
        .join(Collection, Collection.media_id == Media.id)
        .where(Collection.user_id == user_id)
    )
    shows_collected = shows_collected_q.scalar_one()

    # Unwatched movies in collection
    watched_movie_ids_sub = (
        select(WatchEvent.media_id)
        .join(Media, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, WatchEvent.completed == True, Media.media_type == "movie")
        .scalar_subquery()
    )
    unwatched_movies_q = await db.execute(
        select(func.count(func.distinct(Collection.media_id)))
        .join(Media, Collection.media_id == Media.id)
        .where(
            Collection.user_id == user_id,
            Media.media_type == "movie",
            Collection.media_id.notin_(watched_movie_ids_sub),
        )
    )
    unwatched_movies = unwatched_movies_q.scalar_one()

    # Shows watched from collection (has at least one watched episode in collection)
    watched_shows_collected_q = await db.execute(
        select(func.count(func.distinct(ShowModel.id)))
        .join(Media, Media.show_id == ShowModel.id)
        .join(Collection, Collection.media_id == Media.id)
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(Collection.user_id == user_id, WatchEvent.user_id == user_id, WatchEvent.completed == True)
    )
    shows_watched_collected = watched_shows_collected_q.scalar_one()

    return {
        # Watching
        "granularity": "day" if use_daily else "month",
        "weekday_activity": weekday_activity,
        "movies_watched": movies_watched,
        "shows_watched": shows_watched,
        "episodes_watched": episodes_watched,
        "total_watch_minutes": total_watch_minutes,
        "movie_watch_minutes": movie_watch_minutes,
        "show_watch_minutes": show_watch_minutes,
        "watch_activity": watch_activity,
        "watch_time_activity": watch_time_activity,
        "rating_distribution": rating_distribution,
        "avg_movie_rating": avg_movie_rating,
        "avg_show_rating": avg_show_rating,
        "top_movie_genres": top_movie_genres,
        "top_show_genres": top_show_genres,
        # Collection
        "movies_collected": movies_collected,
        "shows_collected": shows_collected,
        "episodes_collected": episodes_collected,
        "movies_watched_collected": movies_collected - unwatched_movies,
        "movies_unwatched_collected": unwatched_movies,
        "shows_watched_collected": shows_watched_collected,
        "shows_unwatched_collected": max(shows_collected - shows_watched_collected, 0),
    }


# ── All-time dashboard data for the Watchd statistics page ───────────────────
@router.get("/{user_id}/stats/all-time-dashboard")
async def get_all_time_dashboard(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_user),
):
    """Return the richer, lifetime-only datasets used by the All Time dashboard."""
    await _check_profile_access(user_id, current_user, db)

    # Pull dated completed plays with their media and (for episodes) parent show.
    plays_q = await db.execute(
        select(WatchEvent, Media, ShowModel)
        .join(Media, WatchEvent.media_id == Media.id)
        .outerjoin(ShowModel, Media.show_id == ShowModel.id)
        .where(WatchEvent.user_id == user_id, WatchEvent.completed == True)
        .order_by(WatchEvent.watched_at.asc().nullsfirst())
    )
    plays = plays_q.all()

    movies_by_id = {}
    shows_by_id = {}
    movie_years = defaultdict(int)
    episode_years = defaultdict(int)
    movie_genres = defaultdict(int)
    show_genres = defaultdict(int)
    movie_studios = defaultdict(int)
    show_networks = defaultdict(int)
    crew_counts = {
        "actors": defaultdict(int), "actresses": defaultdict(int),
        "directors": defaultdict(int), "writers": defaultdict(int),
        "producers": defaultdict(int), "composers": defaultdict(int),
        "cinematographers": defaultdict(int), "original_material": defaultdict(int),
    }
    total_minutes = 0
    first_play = None
    last_play = None

    def json_list(data, key):
        value = (data or {}).get(key, [])
        return value if isinstance(value, list) else []

    def label_of(item):
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            return str(item.get("name") or item.get("title") or "").strip()
        return ""

    def increment_people(data, keys, bucket):
        for key in keys:
            for item in json_list(data, key):
                name = label_of(item)
                if name:
                    bucket[name] += 1

    for event, media, show in plays:
        when = event.watched_at
        if when is not None:
            stamp = when.isoformat()
            play_item = {
                "watched_at": stamp,
                "media_type": media.media_type,
                "title": media.title,
                "poster_path": media.poster_path,
                "backdrop_path": media.backdrop_path,
                "runtime": media.runtime,
                "season_number": media.season_number,
                "episode_number": media.episode_number,
                "show_title": show.title if show else None,
                "show_poster_path": show.poster_path if show else None,
                "show_backdrop_path": show.backdrop_path if show else None,
            }
            if first_play is None:
                first_play = play_item
            last_play = play_item

        runtime = media.runtime
        if runtime is None:
            try:
                runtime = int((media.tmdb_data or {}).get("runtime") or 0)
            except (TypeError, ValueError):
                runtime = 0
        total_minutes += max(int(runtime or 0), 0)

        if media.media_type == "movie":
            key = media.tmdb_id or media.id
            if key not in movies_by_id:
                movies_by_id[key] = {
                    "title": media.title, "poster_path": media.poster_path,
                    "tmdb_id": media.tmdb_id, "year": (media.release_date.year if media.release_date else None),
                    "plays": 0, "tmdb_data": media.tmdb_data or {},
                }
            movies_by_id[key]["plays"] += 1
            year = movies_by_id[key]["year"]
            if year:
                movie_years[str(year)] += 1
            data = media.tmdb_data or {}
            for item in json_list(data, "genres"):
                name = label_of(item)
                if name:
                    movie_genres[name] += 1
            for item in json_list(data, "production_companies"):
                name = label_of(item)
                if name:
                    movie_studios[name] += 1
            credits = data.get("credits") if isinstance(data.get("credits"), dict) else data
            cast = json_list(credits, "cast")
            for person in cast:
                name = label_of(person)
                if name:
                    gender = person.get("gender") if isinstance(person, dict) else None
                    crew_counts["actresses" if gender == 1 else "actors"][name] += 1
            crew = json_list(credits, "crew")
            for person in crew:
                if not isinstance(person, dict):
                    continue
                name = label_of(person)
                job = str(person.get("job") or "").lower()
                dept = str(person.get("department") or "").lower()
                if not name:
                    continue
                if job == "director":
                    crew_counts["directors"][name] += 1
                if job in ("writer", "screenplay", "story", "author"):
                    crew_counts["writers"][name] += 1
                if job == "producer":
                    crew_counts["producers"][name] += 1
                if job in ("original music composer", "composer") or dept == "sound":
                    if "compos" in job:
                        crew_counts["composers"][name] += 1
                if job == "director of photography" or job == "cinematographer":
                    crew_counts["cinematographers"][name] += 1
                if job in ("based on", "original story", "characters"):
                    crew_counts["original_material"][name] += 1

        elif media.media_type == "episode" and show:
            key = show.tmdb_id or show.id
            if key not in shows_by_id:
                shows_by_id[key] = {
                    "title": show.title, "poster_path": show.poster_path,
                    "tmdb_id": show.tmdb_id, "year": (show.first_air_date.year if show.first_air_date else None),
                    "plays": 0, "tmdb_data": show.tmdb_data or {},
                }
            shows_by_id[key]["plays"] += 1
            year = shows_by_id[key]["year"]
            if year:
                episode_years[str(year)] += 1
            data = show.tmdb_data or {}
            for item in json_list(data, "genres"):
                name = label_of(item)
                if name:
                    show_genres[name] += 1
            for item in json_list(data, "networks"):
                name = label_of(item)
                if name:
                    show_networks[name] += 1
            credits = data.get("credits") if isinstance(data.get("credits"), dict) else data
            for person in json_list(credits, "cast"):
                name = label_of(person)
                if name:
                    gender = person.get("gender") if isinstance(person, dict) else None
                    crew_counts["actresses" if gender == 1 else "actors"][name] += 1
            for person in json_list(credits, "crew"):
                if not isinstance(person, dict):
                    continue
                name = label_of(person)
                job = str(person.get("job") or "").lower()
                if not name:
                    continue
                if job == "director":
                    crew_counts["directors"][name] += 1
                if job in ("writer", "screenplay", "story", "creator"):
                    crew_counts["writers"][name] += 1
                if job == "producer":
                    crew_counts["producers"][name] += 1
                if "compos" in job:
                    crew_counts["composers"][name] += 1
                if job in ("director of photography", "cinematographer"):
                    crew_counts["cinematographers"][name] += 1

    def top_counts(counter, limit=25):
        return [{"name": name, "count": count} for name, count in sorted(counter.items(), key=lambda pair: (-pair[1], pair[0].casefold()))[:limit]]

    def top_media(items, limit=10):
        return [
            {k: v for k, v in item.items() if k != "tmdb_data"}
            for item in sorted(items.values(), key=lambda item: (-item["plays"], (item["title"] or "").casefold()))[:limit]
        ]

    # Existing stats endpoint supplies the canonical collection and rating totals.
    rating_q = await db.execute(
        select(Rating.rating, func.count(Rating.id))
        .where(Rating.user_id == user_id, Rating.rating.isnot(None))
        .group_by(Rating.rating).order_by(Rating.rating)
    )
    rating_distribution = [{"rating": float(rating), "count": count} for rating, count in rating_q.all()]

    movies_count = len(movies_by_id)
    episodes_count_q = await db.execute(
        select(func.count(func.distinct(WatchEvent.media_id)))
        .join(Media, WatchEvent.media_id == Media.id)
        .where(WatchEvent.user_id == user_id, WatchEvent.completed == True, Media.media_type == "episode")
    )
    episodes_count = episodes_count_q.scalar_one()

    return {
        "movies_watched": movies_count,
        "episodes_watched": episodes_count,
        "shows_watched": len(shows_by_id),
        "total_watch_minutes": total_minutes,
        "first_play": first_play,
        "last_play": last_play,
        "top_movies": top_media(movies_by_id),
        "top_shows": top_media(shows_by_id),
        "movie_years": [{"year": k, "count": v} for k, v in sorted(movie_years.items())],
        "episode_years": [{"year": k, "count": v} for k, v in sorted(episode_years.items())],
        "movie_genres": top_counts(movie_genres, 20),
        "show_genres": top_counts(show_genres, 20),
        "movie_studios": top_counts(movie_studios, 25),
        "show_networks": top_counts(show_networks, 25),
        "crew": {key: top_counts(value, 100) for key, value in crew_counts.items()},
        "rating_distribution": rating_distribution,
    }



# ── Stats overview ───────────────────────────────────────────────────────────
# One endpoint behind the All Time, Year to Date and per-year statistics pages.
# Append this to the end of routers/profile.py.

from zoneinfo import ZoneInfo as _ZoneInfo
from datetime import timezone as _Timezone


def _so_year(value):
    if not value:
        return None
    if hasattr(value, "year"):
        return value.year
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _so_label(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("name") or item.get("title") or "").strip()
    return ""


def _so_utc_iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.astimezone(_Timezone.utc).isoformat().replace("+00:00", "Z")


_SO_CREW_CATEGORIES = {
    "directors": lambda job: job == "director",
    "writers": lambda job: job in {"writer", "screenplay", "story", "teleplay", "creator"},
    "producers": lambda job: job == "producer",
    "composers": lambda job: "compos" in job,
    "cinematographers": lambda job: job in {"director of photography", "cinematographer"},
    "original_material": lambda job: job in {
        "novel", "characters", "original story", "author", "comic book", "based on", "book",
    },
}


@functools.lru_cache(maxsize=4096)
def _so_job_cats(job):
    return tuple(cat for cat, matches in _SO_CREW_CATEGORIES.items() if matches(job))


def _so_crew_cats(jobs):
    # Called for every crew credit (hundreds of thousands per All Time page), so
    # each distinct job string is categorised once.
    cats = []
    for job in jobs:
        if job:
            for cat in _so_job_cats(job):
                if cat not in cats:
                    cats.append(cat)
    return cats


_CREDITS_TABLE_READY = False


async def _ensure_credits_table():
    """Create episode_credits on demand so no restart/migration is needed."""
    global _CREDITS_TABLE_READY
    if _CREDITS_TABLE_READY:
        return
    from db import engine
    from models.episode_credits import EpisodeCredits
    async with engine.begin() as conn:
        await conn.run_sync(EpisodeCredits.__table__.create, checkfirst=True)
    _CREDITS_TABLE_READY = True


# Bump when the cached episode_credits payload shape changes; older rows are re-fetched.
# v2 adds "r": the season's regular cast, so series regulars are credited per watched episode.
_CREDITS_CACHE_VERSION = 2


async def _so_episode_credit_rows(db, episodes_by_show, show_tmdb):
    """Return ({(tmdb_show, season): season data}, watched map, pending season count).

    season data: {"r": [regulars], "eps": {ep_number: {"g": [guests], "c": [crew]}}}
    watched map: {show_id: {(season, ep_number): media_id}}
    """
    from models.episode_credits import EpisodeCredits

    await _ensure_credits_table()
    all_ids = [m for ids in episodes_by_show.values() for m in ids]
    watched = defaultdict(dict)
    for start in range(0, len(all_ids), 1000):
        res = await db.execute(
            select(Media.id, Media.show_id, Media.season_number, Media.episode_number)
            .where(Media.id.in_(all_ids[start:start + 1000]))
        )
        for mid, sid, sn, en in res.all():
            if sid is not None and sn is not None and en is not None:
                watched[sid][(sn, en)] = mid
    needed = {(show_tmdb[sid], sn) for sid, eps in watched.items() if sid in show_tmdb for (sn, _en) in eps}
    cached = {}
    if needed:
        res = await db.execute(select(EpisodeCredits.tmdb_show_id, EpisodeCredits.season_number, EpisodeCredits.data))
        for tid, sn, data in res.all():
            if (tid, sn) in needed and (data or {}).get("v") == _CREDITS_CACHE_VERSION:
                cached[(tid, sn)] = data
    return cached, watched, len(needed - set(cached))


# Cast & crew is the slowest part of the stats page (~10 s for All Time), so the
# result is kept, keyed on everything it depends on: the watched titles, episodes
# per show and the state of the episode credits cache. Any new watch or credits
# fetch changes the key; the TTL only bounds staleness from metadata refreshes.
_PEOPLE_CACHE_TTL = 6 * 3600
_PEOPLE_CACHE: dict[int, tuple[float, dict]] = {}


async def _so_build_people(db, movie_info, show_info, episodes_by_show):
    credits_state = None
    try:
        from models.episode_credits import EpisodeCredits
        async with db.begin_nested():
            credits_state = (await db.execute(
                select(func.count(), func.max(EpisodeCredits.fetched_at))
            )).one()
            credits_state = tuple(credits_state)
    except Exception:
        pass
    key = hash((
        tuple(sorted(movie_info.items())),
        tuple(sorted(show_info.items())),
        tuple(sorted((sid, tuple(sorted(ids))) for sid, ids in episodes_by_show.items())),
        credits_state,
    ))
    now = time.monotonic()
    for stale in [k for k, (at, _) in _PEOPLE_CACHE.items() if now - at > _PEOPLE_CACHE_TTL]:
        _PEOPLE_CACHE.pop(stale, None)
    hit = _PEOPLE_CACHE.get(key)
    if hit:
        return hit[1]
    people = await _so_build_people_uncached(db, movie_info, show_info, episodes_by_show)
    _PEOPLE_CACHE[key] = (now, people)
    return people


async def _so_build_people_uncached(db, movie_info, show_info, episodes_by_show):
    """Most-watched cast & crew, counting title-level credits plus guest roles and
    one-off crew credits on the individual episodes that were watched.

    movie_info: {media_id: (title, year)}   show_info: {show_id: (title, year)}
    Returns {} when no credits are stored, so the page simply hides the section.
    """
    categories = ["actors", "actresses", *_SO_CREW_CATEGORIES.keys()]
    acc = {cat: {} for cat in categories}

    def add(cat, person, title_key, title, year, ep_ids=None):
        pid = person.get("id") or person.get("name")
        if not pid or not person.get("name"):
            return
        entry = acc[cat].setdefault(
            pid, {"name": person["name"], "profile_path": None, "titles": {}}
        )
        if not entry["profile_path"] and person.get("profile_path"):
            entry["profile_path"] = person["profile_path"]
        t = entry["titles"].setdefault(
            title_key, {"title": title, "year": year, "ep_ids": set(), "kind": title_key[0]}
        )
        if ep_ids:
            t["ep_ids"].update(ep_ids)

    def read(credits, aggregate, cast_top, crew_top):
        credits = credits if isinstance(credits, dict) else {}
        aggregate = aggregate if isinstance(aggregate, dict) else {}
        cast = credits.get("cast") or aggregate.get("cast") or cast_top or []
        crew = credits.get("crew") or aggregate.get("crew") or crew_top or []
        return (cast if isinstance(cast, list) else []), (crew if isinstance(crew, list) else [])

    def consume(cast, crew, title_key, title, year, ep_ids=None):
        for person in cast:
            if not isinstance(person, dict):
                continue
            cat = "actresses" if person.get("gender") == 1 else "actors"
            add(cat, person, title_key, title, year, ep_ids)
        for person in crew:
            if not isinstance(person, dict):
                continue
            jobs = [
                str(j.get("job") or "").lower()
                for j in (person.get("jobs") or [])
                if isinstance(j, dict)
            ] or [str(person.get("job") or "").lower()]
            for cat in _so_crew_cats(jobs):
                add(cat, person, title_key, title, year, ep_ids)

    movie_ids = list(movie_info.keys())
    for start in range(0, len(movie_ids), 500):
        chunk = movie_ids[start:start + 500]
        res = await db.execute(
            select(
                Media.id,
                Media.tmdb_data["credits"],
                Media.tmdb_data["aggregate_credits"],
                Media.tmdb_data["cast"],
                Media.tmdb_data["crew"],
            ).where(Media.id.in_(chunk))
        )
        for media_id, credits, aggregate, cast_top, crew_top in res.all():
            cast, crew = read(credits, aggregate, cast_top, crew_top)
            title, year = movie_info[media_id]
            consume(cast, crew, f"m{media_id}", title, year)

    # TV is credited per watched episode, like Trakt: a person gets each show once,
    # with the number of watched episodes they appear in (season regulars, guest stars
    # and episode crew from the cached season credits). Episodes whose season hasn't
    # been fetched yet fall back to the show-level credits for just those episodes.
    show_ids = list(show_info.keys())
    show_tmdb = {}
    show_credits = {}
    for start in range(0, len(show_ids), 500):
        chunk = show_ids[start:start + 500]
        res = await db.execute(
            select(
                ShowModel.id,
                ShowModel.tmdb_id,
                ShowModel.tmdb_data["credits"],
                ShowModel.tmdb_data["aggregate_credits"],
                ShowModel.tmdb_data["cast"],
                ShowModel.tmdb_data["crew"],
            ).where(ShowModel.id.in_(chunk))
        )
        for show_id, tmdb_id, credits, aggregate, cast_top, crew_top in res.all():
            if tmdb_id:
                show_tmdb[show_id] = tmdb_id
            show_credits[show_id] = read(credits, aggregate, cast_top, crew_top)

    pending = 0
    cached, watched = {}, {}
    try:
        # Savepoint: a failure here (e.g. table not created yet) must not poison the outer transaction.
        async with db.begin_nested():
            cached, watched, pending = await _so_episode_credit_rows(db, episodes_by_show, show_tmdb)
    except Exception as exc:
        print(f"[stats] episode credits skipped: {exc}")

    for show_id, (cast, crew) in show_credits.items():
        title, year = show_info[show_id]
        key = f"s{show_id}"
        tid = show_tmdb.get(show_id)
        eps = watched.get(show_id) or {}
        unfetched = set(episodes_by_show.get(show_id, ())) - set(eps.values())
        for (sn, en), media_id in eps.items():
            season = cached.get((tid, sn)) if tid else None
            if not season:
                unfetched.add(media_id)
                continue
            ep = (season.get("eps") or {}).get(str(en)) or {}
            for p in [*(season.get("r") or []), *(ep.get("g") or [])]:
                person = {"id": p[0], "name": p[1], "profile_path": p[2]}
                add("actresses" if p[3] == 1 else "actors", person, key, title, year, {media_id})
            for c in ep.get("c") or []:
                person = {"id": c[0], "name": c[1], "profile_path": c[2]}
                for cat in _so_crew_cats([str(c[3]).lower()]):
                    add(cat, person, key, title, year, {media_id})
        if unfetched:
            consume(cast, crew, key, title, year, unfetched)

    out = {}
    for cat, people in acc.items():
        rows = []
        for entry in people.values():
            titles = list(entry["titles"].values())
            movies = sum(1 for t in titles if t["kind"] == "m")
            shows = sum(1 for t in titles if t["kind"] == "s")
            for t in titles:
                t["episodes"] = len(t["ep_ids"])
            episodes = sum(t["episodes"] for t in titles)
            titles.sort(key=lambda t: (t["year"] or 0, t["title"] or ""), reverse=True)
            rows.append({
                "name": entry["name"],
                "profile_path": entry["profile_path"],
                "movies": movies,
                "shows": shows,
                "episodes": episodes,
                "titles": [
                    {"title": t["title"], "year": t["year"], "episodes": t["episodes"]}
                    for t in titles
                ],
            })
        rows.sort(key=lambda r: (-(r["movies"] + r["shows"]), -r["episodes"], r["name"].casefold()))
        out[cat] = rows[:100]

    if any(out.values()):
        out["_pending"] = pending
        return out
    return {}


# ── Episode credits backfill (guest stars / one-off crew for Cast & Crew stats) ──

_CREDITS_BACKFILL: dict[int, dict] = {}


@router.post("/me/credits/backfill")
async def start_credits_backfill(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user.id
    if _CREDITS_BACKFILL.get(user_id, {}).get("running"):
        raise HTTPException(status_code=409, detail="Credits fetch already running")
    from routers.media import get_user_tmdb_key
    tmdb_key = await get_user_tmdb_key(db, user_id)
    if not tmdb_key:
        raise HTTPException(status_code=400, detail="TMDB API key not configured")
    await _ensure_credits_table()
    _CREDITS_BACKFILL[user_id] = {"running": True, "progress": 0, "total": 0, "done": False, "error": None}
    background_tasks.add_task(_run_credits_backfill, user_id, tmdb_key)
    return {"status": "started"}


@router.get("/me/credits/backfill/status")
async def get_credits_backfill_status(current_user: User = Depends(get_current_user)):
    return _CREDITS_BACKFILL.get(current_user.id) or {
        "running": False, "progress": 0, "total": 0, "done": False, "error": None,
    }


@router.delete("/me/credits/backfill")
async def abort_credits_backfill(current_user: User = Depends(get_current_user)):
    state = _CREDITS_BACKFILL.get(current_user.id)
    if state and state.get("running"):
        state["abort"] = True
    return {"status": "ok"}


async def _run_credits_backfill(user_id: int, tmdb_key: str) -> None:
    from models.episode_credits import EpisodeCredits
    from datetime import datetime as _DT, timedelta as _TD

    state = _CREDITS_BACKFILL[user_id]
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(ShowModel.tmdb_id, Media.season_number, Media.episode_number)
                .join(Media, Media.show_id == ShowModel.id)
                .where(
                    Media.media_type == "episode",
                    Media.season_number.isnot(None),
                    Media.episode_number.isnot(None),
                    ShowModel.tmdb_id.isnot(None),
                    Media.id.in_(
                        select(WatchEvent.media_id).where(
                            WatchEvent.user_id == user_id, WatchEvent.completed == True
                        )
                    ),
                )
                .distinct()
            )
            wanted = defaultdict(set)
            for tid, sn, en in res.all():
                wanted[(tid, sn)].add(en)
            cres = await db.execute(
                select(EpisodeCredits.tmdb_show_id, EpisodeCredits.season_number,
                       EpisodeCredits.data, EpisodeCredits.fetched_at)
            )
            cached = {(t, s): (d, f) for t, s, d, f in cres.all()}

        recent = _DT.utcnow() - _TD(days=7)
        todo = []
        for key, eps in wanted.items():
            hit = cached.get(key)
            if hit and (hit[0] or {}).get("v") == _CREDITS_CACHE_VERSION:
                have = (hit[0] or {}).get("eps") or {}
                if all(str(e) in have for e in eps) or (hit[1] and hit[1] > recent):
                    continue
            todo.append(key)

        state["total"] = len(todo)
        state["failed"] = 0
        if not todo:
            return

        sem = asyncio.Semaphore(5)
        results = []

        async def save(batch):
            async with AsyncSessionLocal() as db:
                for (tid, sn), data in batch:
                    row = await db.get(EpisodeCredits, (tid, sn))
                    if row:
                        row.data = data
                        row.fetched_at = _DT.utcnow()
                    else:
                        db.add(EpisodeCredits(tmdb_show_id=tid, season_number=sn, data=data))
                await db.commit()

        async def fetch(key):
            async with sem:
                if not state.get("abort"):
                    try:
                        data = await tmdb_client.get_season(
                            key[0], key[1], api_key=tmdb_key, append_to_response="credits"
                        )
                        regulars = [
                            [p.get("id"), p.get("name"), p.get("profile_path"), p.get("gender")]
                            for p in ((data.get("credits") or {}).get("cast") or [])
                            if p.get("id") and p.get("name")
                        ]
                        eps = {}
                        for ep in data.get("episodes") or []:
                            g = [[p.get("id"), p.get("name"), p.get("profile_path"), p.get("gender")]
                                 for p in (ep.get("guest_stars") or []) if p.get("id") and p.get("name")]
                            c = [[p.get("id"), p.get("name"), p.get("profile_path"), p.get("job")]
                                 for p in (ep.get("crew") or [])
                                 if p.get("id") and p.get("name") and p.get("job")
                                 and _so_crew_cats([str(p["job"]).lower()])]
                            eps[str(ep.get("episode_number"))] = {"g": g, "c": c}
                        results.append(
                            (key, {"v": _CREDITS_CACHE_VERSION, "r": regulars, "eps": eps})
                        )
                    except Exception as exc:
                        state["failed"] += 1
                        print(f"[credits] season fetch failed for tmdb {key[0]} S{key[1]}: {exc}")
            state["progress"] += 1

        # Save in batches so a long run keeps its progress if it's aborted or crashes.
        for start in range(0, len(todo), 50):
            await asyncio.gather(*[fetch(k) for k in todo[start:start + 50]])
            if results:
                await save(results)
                results.clear()
            if state.get("abort"):
                break

        if state["failed"] and state["failed"] == state["total"]:
            state["error"] = "Every TMDB season request failed; check the TMDB API key in Settings."
    except Exception as exc:
        state["error"] = str(exc)
    finally:
        state["running"] = False
        state["done"] = not state.get("error") and not state.get("abort")


@router.get("/{user_id}/stats/top-shows")
async def get_stats_top_shows(
    user_id: int,
    since: Optional[DateType] = None,
    until: Optional[DateType] = None,
    page: int = 1,
    page_size: int = 60,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_user),
):
    """Every show the user has watched, ranked by distinct episodes watched.

    Paged (60 per page by default) so the full ranking can be browsed.
    """
    await _check_profile_access(user_id, current_user, db)

    page_size = max(1, min(int(page_size), 120))
    page = max(1, int(page))

    filters = [
        WatchEvent.user_id == user_id,
        WatchEvent.completed == True,
        Media.media_type == "episode",
        Media.show_id.isnot(None),
    ]
    if since:
        filters.append(WatchEvent.watched_at >= since)
    if until:
        filters.append(WatchEvent.watched_at < until + TimeDelta(days=1))

    counts = (
        select(
            Media.show_id.label("show_id"),
            func.count(func.distinct(Media.id)).label("episodes"),
        )
        .select_from(WatchEvent)
        .join(Media, Media.id == WatchEvent.media_id)
        .where(*filters)
        .group_by(Media.show_id)
        .subquery()
    )

    total_shows = (await db.execute(select(func.count()).select_from(counts))).scalar() or 0
    total_episodes = (
        await db.execute(select(func.coalesce(func.sum(counts.c.episodes), 0)))
    ).scalar() or 0

    pages = max(1, -(-total_shows // page_size))
    page = min(page, pages)
    offset = (page - 1) * page_size

    rows = await db.execute(
        select(
            ShowModel.tmdb_id,
            ShowModel.tvdb_id,
            ShowModel.title,
            ShowModel.poster_path,
            ShowModel.first_air_date,
            counts.c.episodes,
        )
        .join(counts, counts.c.show_id == ShowModel.id)
        .order_by(counts.c.episodes.desc(), func.lower(ShowModel.title))
        .limit(page_size)
        .offset(offset)
    )

    results = [
        {
            "rank": offset + i + 1,
            "tmdb_id": tmdb_id,
            "tvdb_id": tvdb_id,
            "title": title,
            "poster_path": poster,
            "year": _so_year(first_air),
            "episodes": int(episodes),
        }
        for i, (tmdb_id, tvdb_id, title, poster, first_air, episodes) in enumerate(rows.all())
    ]

    return {
        "results": results,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "total_shows": int(total_shows),
        "total_episodes": int(total_episodes),
    }


@router.get("/{user_id}/stats/overview")
async def get_stats_overview(
    user_id: int,
    since: Optional[DateType] = None,
    until: Optional[DateType] = None,
    tz: str = "UTC",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_user),
):
    await _check_profile_access(user_id, current_user, db)

    try:
        from core.genres import normalise_genre
    except Exception:  # fall back to the raw genre name
        def normalise_genre(name):
            return name

    try:
        zone = _ZoneInfo(tz)
    except Exception:
        zone = _ZoneInfo("UTC")

    play_filters = [WatchEvent.user_id == user_id, WatchEvent.completed == True]
    if since:
        play_filters.append(WatchEvent.watched_at >= since)
    if until:
        play_filters.append(WatchEvent.watched_at < until + TimeDelta(days=1))

    # Same runtime rule as the dashboard header: an episode with no runtime of its
    # own counts as its show's average, so the hours on both pages agree.
    show_avg = (
        select(
            Media.show_id.label("show_id"),
            func.avg(Media.runtime).label("avg_runtime"),
        )
        .where(Media.media_type == "episode", Media.runtime.isnot(None))
        .group_by(Media.show_id)
        .subquery()
    )

    events_q = await db.execute(
        select(
            WatchEvent.watched_at,
            Media.media_type,
            Media.id,
            Media.tmdb_id,
            Media.show_id,
            func.coalesce(Media.runtime, show_avg.c.avg_runtime, 0),
            WatchEvent.watch_source,
        )
        .select_from(WatchEvent)
        .join(Media, Media.id == WatchEvent.media_id)
        .outerjoin(show_avg, show_avg.c.show_id == Media.show_id)
        .where(*play_filters, Media.media_type.in_(["movie", "episode"]))
    )

    def new_bucket():
        return {
            "plays": 0,
            "minutes": 0.0,
            "year": defaultdict(int),
            "month": [0] * 12,
            "weekday": [0] * 7,
            "hour": [0] * 24,
            "sources": defaultdict(int),
        }

    tv, mv = new_bucket(), new_bucket()
    episodes_by_show = defaultdict(set)
    movie_plays = defaultdict(int)
    movie_media_by_key = {}
    first_event = None
    last_event = None

    for watched_at, mtype, media_id, tmdb_id, show_id, minutes, source in events_q.all():
        is_movie = str(getattr(mtype, "value", mtype)) == "movie"
        bucket = mv if is_movie else tv
        bucket["plays"] += 1
        bucket["minutes"] += float(minutes or 0)
        if source:
            bucket["sources"][str(source)] += 1

        if is_movie:
            key = tmdb_id or media_id
            movie_plays[key] += 1
            movie_media_by_key.setdefault(key, media_id)
        elif show_id:
            episodes_by_show[show_id].add(media_id)

        if watched_at is not None:
            stamp = watched_at if watched_at.tzinfo else watched_at.replace(tzinfo=_Timezone.utc)
            local = stamp.astimezone(zone)
            bucket["year"][local.year] += 1
            bucket["month"][local.month - 1] += 1
            bucket["weekday"][local.weekday()] += 1
            bucket["hour"][local.hour] += 1
            if first_event is None or stamp < first_event[0]:
                first_event = (stamp, media_id)
            if last_event is None or stamp > last_event[0]:
                last_event = (stamp, media_id)

    # ── Shows ────────────────────────────────────────────────────────────────
    show_ids = list(episodes_by_show.keys())
    show_rows = []
    for start in range(0, len(show_ids), 500):
        res = await db.execute(
            select(
                ShowModel.id, ShowModel.tmdb_id, ShowModel.tvdb_id, ShowModel.title,
                ShowModel.poster_path, ShowModel.first_air_date,
                ShowModel.tmdb_data["genres"], ShowModel.tmdb_data["networks"],
            ).where(ShowModel.id.in_(show_ids[start:start + 500]))
        )
        show_rows.extend(res.all())

    show_genres = defaultdict(int)
    show_networks = defaultdict(int)
    network_logos = {}
    tv_release_years = defaultdict(int)
    show_info = {}
    show_cards = []

    for sid, s_tmdb, s_tvdb, s_title, s_poster, s_first_air, s_genres, s_networks in show_rows:
        year = _so_year(s_first_air)
        show_info[sid] = (s_title, year)
        if year:
            tv_release_years[year] += 1
        seen = set()
        for g in s_genres or []:
            name = _so_label(g)
            name = normalise_genre(name) if name else None
            if name and name not in seen:
                seen.add(name)
                show_genres[name] += 1
        for n in s_networks or []:
            name = _so_label(n)
            if name:
                show_networks[name] += 1
                if isinstance(n, dict) and n.get("logo_path") and name not in network_logos:
                    network_logos[name] = n["logo_path"]
        show_cards.append({
            "id": sid, "tmdb_id": s_tmdb, "tvdb_id": s_tvdb, "title": s_title,
            "poster_path": s_poster, "year": year,
            "episodes": len(episodes_by_show[sid]),
        })

    show_cards.sort(key=lambda c: (-c["episodes"], (c["title"] or "").casefold()))
    top_shows = [
        {k: v for k, v in c.items() if k != "id"} for c in show_cards[:10]
    ]

    # ── Movies ───────────────────────────────────────────────────────────────
    movie_media_ids = list(movie_media_by_key.values())
    movie_rows = []
    for start in range(0, len(movie_media_ids), 500):
        res = await db.execute(
            select(
                Media.id, Media.tmdb_id, Media.title, Media.poster_path, Media.release_date,
                Media.tmdb_data["genres"], Media.tmdb_data["production_companies"],
            ).where(Media.id.in_(movie_media_ids[start:start + 500]))
        )
        movie_rows.extend(res.all())

    movie_genres = defaultdict(int)
    movie_studios = defaultdict(int)
    movie_release_years = defaultdict(int)
    movie_info = {}
    movie_cards = []

    for mid, m_tmdb, m_title, m_poster, m_release, m_genres, m_companies in movie_rows:
        year = _so_year(m_release)
        movie_info[mid] = (m_title, year)
        if year:
            movie_release_years[year] += 1
        seen = set()
        for g in m_genres or []:
            name = _so_label(g)
            name = normalise_genre(name) if name else None
            if name and name not in seen:
                seen.add(name)
                movie_genres[name] += 1
        for company in m_companies or []:
            name = _so_label(company)
            if name:
                movie_studios[name] += 1
        key = m_tmdb or mid
        movie_cards.append({
            "tmdb_id": m_tmdb, "title": m_title, "poster_path": m_poster,
            "year": year, "plays": movie_plays.get(key, 0),
        })

    movie_cards.sort(key=lambda c: (-c["plays"], (c["title"] or "").casefold()))
    top_movies = movie_cards[:10]

    # ── Ratings (show-level and movie ratings only) ──────────────────────────
    rating_filters = [
        Rating.user_id == user_id,
        Rating.rating.isnot(None),
        Rating.season_number.is_(None),
    ]
    if since:
        rating_filters.append(Rating.rated_at >= since)
    if until:
        rating_filters.append(Rating.rated_at < until + TimeDelta(days=1))

    rating_q = await db.execute(
        select(
            Rating.rating, Rating.rated_at, Media.media_type,
            Media.tmdb_id, Media.title, Media.poster_path,
        )
        .join(Media, Media.id == Rating.media_id)
        .where(*rating_filters, Media.media_type.in_(["movie", "series"]))
        .order_by(Rating.rated_at.desc())
    )
    scores = {"movie": [], "series": []}
    tens = {"movie": [], "series": []}
    for rating, rated_at, mtype, r_tmdb, r_title, r_poster in rating_q.all():
        kind = "movie" if str(getattr(mtype, "value", mtype)) == "movie" else "series"
        value = float(rating)
        scores[kind].append(value)
        if value >= 10:
            tens[kind].append({"tmdb_id": r_tmdb, "title": r_title, "poster_path": r_poster})

    # Series ratings can lack a poster on the Media row; use the Show row instead
    series_ids = [t["tmdb_id"] for t in tens["series"] if t["tmdb_id"]]
    if series_ids:
        poster_q = await db.execute(
            select(ShowModel.tmdb_id, ShowModel.poster_path)
            .where(ShowModel.tmdb_id.in_(series_ids))
        )
        posters = {tmdb: poster for tmdb, poster in poster_q.all()}
        for t in tens["series"]:
            t["poster_path"] = posters.get(t["tmdb_id"]) or t["poster_path"]

    def rating_block(values):
        dist = defaultdict(int)
        for v in values:
            dist[v] += 1
        return {
            "count": len(values),
            "average": round(sum(values) / len(values), 2) if values else None,
            "tens": sum(1 for v in values if v >= 10),
            "distribution": [{"rating": k, "count": c} for k, c in sorted(dist.items())],
        }

    # ── Years that have plays (drives the year switcher) ─────────────────────
    years_q = await db.execute(
        select(func.extract("year", WatchEvent.watched_at))
        .where(
            WatchEvent.user_id == user_id,
            WatchEvent.completed == True,
            WatchEvent.watched_at.isnot(None),
        )
        .distinct()
    )
    years = sorted({int(y) for (y,) in years_q.all() if y is not None}, reverse=True)

    # ── Cast & crew (optional; empty when no credits are stored) ─────────────
    people = {}
    try:
        people = await _so_build_people(db, movie_info, show_info, episodes_by_show)
    except Exception as exc:  # never take the whole page down for this section
        print(f"[stats] cast & crew skipped: {exc}")

    # ── First and last play cards ────────────────────────────────────────────
    async def play_card(event):
        if not event:
            return None
        stamp, media_id = event
        res = await db.execute(
            select(Media, ShowModel)
            .outerjoin(ShowModel, Media.show_id == ShowModel.id)
            .where(Media.id == media_id)
        )
        row = res.first()
        if not row:
            return None
        media, show = row
        return {
            "watched_at": _so_utc_iso(stamp),
            "media_type": str(getattr(media.media_type, "value", media.media_type)),
            "title": media.title,
            "poster_path": media.poster_path,
            "backdrop_path": media.backdrop_path,
            "season_number": media.season_number,
            "episode_number": media.episode_number,
            "tmdb_id": media.tmdb_id,
            "show_title": show.title if show else None,
            "show_poster_path": show.poster_path if show else None,
            "show_backdrop_path": show.backdrop_path if show else None,
            "show_tmdb_id": show.tmdb_id if show else None,
        }

    first_play = await play_card(first_event)
    last_play = await play_card(last_event)

    def series(counter):
        return [{"label": str(k), "count": v} for k, v in sorted(counter.items())]

    def ranked(counter, limit):
        return [
            {"name": name, "count": count}
            for name, count in sorted(counter.items(), key=lambda p: (-p[1], p[0].casefold()))[:limit]
        ]

    def bucket_out(bucket):
        return {
            "plays": bucket["plays"],
            "minutes": round(bucket["minutes"]),
            "by_year": series(bucket["year"]),
            "by_month": bucket["month"],
            "by_weekday": bucket["weekday"],  # Monday first
            "by_hour": bucket["hour"],
            "sources": ranked(bucket["sources"], 12),
        }

    tv_out = bucket_out(tv)
    tv_out.update({
        "episodes": sum(len(v) for v in episodes_by_show.values()),
        "shows": len(episodes_by_show),
        "top_shows": top_shows,
        "genres": ranked(show_genres, 30),
        "release_years": series(tv_release_years),
        "networks": [
            {"name": n["name"], "count": n["count"], "logo_path": network_logos.get(n["name"])}
            for n in ranked(show_networks, 25)
        ],
    })

    movies_out = bucket_out(mv)
    movies_out.update({
        "movies": len(movie_plays),
        "top_movies": top_movies,
        "genres": ranked(movie_genres, 30),
        "release_years": series(movie_release_years),
        "studios": ranked(movie_studios, 20),
    })

    return {
        "years": years,
        "first_play": first_play,
        "last_play": last_play,
        "totals": {
            "plays": tv["plays"] + mv["plays"],
            "minutes": round(tv["minutes"] + mv["minutes"]),
        },
        "tv": tv_out,
        "movies": movies_out,
        "ratings": {
            "shows": rating_block(scores["series"]),
            "movies": rating_block(scores["movie"]),
        },
        "top_rated": {
            "shows": tens["series"][:10],
            "movies": tens["movie"][:10],
        },
        "people": people,
    }
