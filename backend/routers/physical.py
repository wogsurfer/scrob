"""The user's physical disc collection: browsing, editing, covers,
statistics and barcode lookup."""

import re
from collections import Counter
from datetime import date
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core import tmdb
from core.physical import (
    PICK_LISTS, cover_path, fetch_cover, fill_from_tmdb, franchise_sort_keys, link_media, set_franchise, pick_values, rebuild_collection_mirror,
    refresh_imdb_ratings, replace_pick_value, save_cover,
)
from db import get_db
from dependencies import get_current_user
from models.base import MediaType
from models.events import WatchEvent
from models.media import Media
from models.show import Show
from models.physical import PhysicalItem, PhysicalPickValue
from models.users import User
from routers.media import get_user_tmdb_key

router = APIRouter()

_COVER_NAME = re.compile(r"^[\w-]+\.jpg$")


def _cover_url(name: str | None, thumb: bool = False) -> str | None:
    if not name:
        return None
    return f"/api/proxy/physical/covers/{name}{'?thumb=1' if thumb else ''}"


def _num(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _crew(specs: dict, role: str) -> str | None:
    names = [c.get("name") for c in specs.get("crew") or [] if c.get("role") == role and c.get("name")]
    return "; ".join(dict.fromkeys(names)) or None


def _director(specs: dict) -> str | None:
    return _crew(specs, "Director")


async def _watched_tmdb_ids(db: AsyncSession, user_id: int) -> dict[int, int]:
    """Plays per movie TMDB id, from the user's watch history."""
    rows = await db.execute(
        select(Media.tmdb_id, func.count(WatchEvent.id))
        .join(WatchEvent, WatchEvent.media_id == Media.id)
        .where(
            WatchEvent.user_id == user_id,
            WatchEvent.completed.is_(True),
            Media.media_type == MediaType.movie,
            Media.tmdb_id.is_not(None),
        )
        .group_by(Media.tmdb_id)
    )
    return dict(rows.all())


def _poster_thumb(poster: str | None) -> str | None:
    """A TMDB poster, used when a release has no cover scan of its own."""
    return poster.replace("/w500/", "/w342/") if poster else None


# The artwork a release can have: its covers (columns) and its own poster
# and backdrop, which replace the film's from TMDB (stored names in specs).
ART_SLOTS = ("front", "poster", "backdrop")


def _own_art(item: PhysicalItem, slot: str) -> str | None:
    if slot == "front":
        return item.cover_front
    return (item.specs or {}).get(f"{slot}_image")


def _set_art(item: PhysicalItem, slot: str, stored: str | None) -> None:
    if slot == "front":
        item.cover_front = stored
        return
    specs = dict(item.specs or {})
    if stored:
        specs[f"{slot}_image"] = stored
    else:
        specs.pop(f"{slot}_image", None)
    item.specs = specs


def _remove_files(stored: str | None) -> None:
    for thumb in (False, True):
        path = cover_path(stored, thumb)
        if path and path.exists():
            path.unlink()


def _franchise_sort(specs: dict) -> str | None:
    """Where a franchise film files, without a leading article, as Collectorz
    files titles: "The Avengers 03" -> "Avengers 03"."""
    auto = specs.get("auto_sort") if specs.get("franchise") else None
    return re.sub(r"^(?:the|a|an)\s+", "", auto, flags=re.I) if auto else None


def _summary(item: PhysicalItem, plays: dict[int, int], poster: str | None = None) -> dict:
    specs = item.specs or {}
    # Plays are counted per film TMDB id; a series id is a different title.
    film_id = item.tmdb_id if specs.get("tmdb_kind", "movie") == "movie" else None
    watched = bool(film_id and plays.get(film_id))
    return {
        "id": item.id,
        "status": item.status,
        "title": item.title,
        # A film in a franchise files with the rest of it ("Avengers 03"), ahead
        # of Collectorz's sort title, which drops "The" and so split series
        # in two; otherwise the sort title, else the title.
        "sort_title": _franchise_sort(specs) or item.sort_title or item.title,
        "own_sort": bool(item.sort_title),
        "franchise": specs.get("franchise"),
        "title_extension": specs.get("title_extension"),
        "is_tv": item.is_tv,
        "series": item.series,
        "tmdb_id": item.tmdb_id,
        "tmdb_kind": specs.get("tmdb_kind", "movie"),
        "release_year": item.release_year,
        "format": item.format,
        "edition": item.edition,
        "distributor": item.distributor,
        "barcode": item.barcode,
        "package": item.package,
        "disc_count": item.disc_count,
        "disc_release_date": item.disc_release_date,
        "runtime": item.runtime,
        "purchase_date": item.purchase_date,
        "purchase_price": _num(item.purchase_price),
        "store": item.store,
        "condition": item.condition,
        "location": item.location,
        "index_no": item.index_no,
        "my_rating": item.my_rating,
        # Watched in Watchd, or marked seen in Collectorz.
        "seen": watched or item.seen_it,
        "plays": plays.get(film_id, 0) if film_id else 0,
        "genres": specs.get("genres", []),
        "regions": specs.get("regions", []),
        "audience_rating": specs.get("audience_rating"),
        "imdb_rating": specs.get("imdb_rating"),
        "director": _director(specs),
        # The rest of what the list view can show as columns.
        "original_title": specs.get("original_title"),
        "imdb_votes": specs.get("imdb_votes"),
        "current_value": _num(item.current_value),
        "owner": item.owner,
        "viewing_date": item.viewing_date,
        "updated_at": item.updated_at,
        "seen_in_cinema": specs.get("seen_in_cinema"),
        "country": specs.get("country"),
        "language": specs.get("language"),
        "studios": (specs.get("studios") or [])[:3],
        "writer": _crew(specs, "Writer"),
        "producer": _crew(specs, "Producer"),
        "composer": _crew(specs, "Composer") or _crew(specs, "Musician"),
        "cinematography": _crew(specs, "Cinematography"),
        "actors": [c.get("name") for c in (specs.get("cast") or [])[:4] if c.get("name")],
        "adaptation_of": specs.get("adaptation_of"),
        "ratios": specs.get("ratios", []),
        "audio": specs.get("audio", []),
        "subtitles": specs.get("subtitles", []),
        "layers": specs.get("layers"),
        "hdr": specs.get("hdr"),
        "color": specs.get("color"),
        "extras": specs.get("extras", []),
        "notes": (item.notes or "")[:160] or None,
        # A box set or multi-film disc, or a film in one.
        "is_set": item.is_set,
        "parent_id": item.parent_id,
        "position": item.position,
        "tags": item.tags or [],
        "date_added": item.date_added,
        # Never filled in: recent Collectorz imports come without a cover
        # scan of their own (and often no edition or distributor).
        "unedited": not item.edited_locally and not item.cover_front and item.parent_id is None,
        "cover": (
            _cover_url(item.cover_front, thumb=True)
            or _cover_url((item.specs or {}).get("poster_image"), thumb=True)
            or _poster_thumb(poster)
        ),
    }


async def _own_item(db: AsyncSession, user_id: int, item_id: int) -> PhysicalItem:
    item = (await db.execute(
        select(PhysicalItem)
        .options(selectinload(PhysicalItem.parent), selectinload(PhysicalItem.contents))
        .where(PhysicalItem.id == item_id, PhysicalItem.user_id == user_id)
    )).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Not in your collection")
    return item


@router.get("/items")
async def list_items(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every release in the collection and wish list, with the fields the
    browser sorts, filters and groups by. Small enough to send whole."""
    rows = (await db.execute(
        select(PhysicalItem, func.coalesce(Media.poster_path, Show.poster_path))
        .outerjoin(Media, Media.id == PhysicalItem.media_id)
        # Series keep their artwork in shows.
        .outerjoin(Show, (Show.tmdb_id == PhysicalItem.tmdb_id) & (PhysicalItem.specs["tmdb_kind"].astext == "tv"))
        .where(PhysicalItem.user_id == current_user.id)
    )).all()
    plays = await _watched_tmdb_ids(db, current_user.id)
    # A franchise you have one film of isn't filed as one.
    franchises = Counter((i.specs or {}).get("franchise") for i, _ in rows if not i.is_set)
    # The year each franchise began, for filing it among films of the same name.
    began: dict[str, int] = {}
    for i, _ in rows:
        fr = (i.specs or {}).get("franchise")
        if fr and not i.is_set and franchises[fr] >= 2 and i.release_year:
            began[fr] = min(began.get(fr, 9999), i.release_year)
    summaries = []
    for i, poster in rows:
        data = _summary(i, plays, poster)
        _drop_lone_franchise(data, franchises[data["franchise"]], i)
        data["sort_title"] = _shelf_sort(data, began)
        # Empty fields are left out: it's the whole collection in one response.
        summaries.append({k: v for k, v in data.items() if v not in (None, "", [], False)})
    return {"items": summaries}


def _shelf_sort(data: dict, began: dict[str, int]) -> str:
    """The sort title with the year in it, so films of the same name go in
    the order they came out ("Black Widow 1987", "Black Widow 2021"), and a
    franchise files by the year it began with its films in order after it
    ("Wonder Woman 2009", then "Wonder Woman 2017 01", "Wonder Woman 2017 02")."""
    title = data["sort_title"]
    fr = data.get("franchise")
    if fr and fr in began:
        base = re.sub(r"^(?:the|a|an)\s+", "", fr, flags=re.I)
        place = title[len(base):].strip() if title.lower().startswith(base.lower()) else ""
        return f"{base} {began[fr]} {place}".strip()
    # Collectorz's sort title is often the title plus extras ("Wonder Woman:
    # DC Universe Animated Original Movie #4", "Black Widow 1987"), which would
    # keep a film from its namesakes; the title itself files it.
    own = data.get("title") or title
    bare = re.sub(r"^(?:the|a|an)\s+", "", own, flags=re.I).lower()
    if not data.get("is_set") and bare and title.lower().startswith(bare):
        title = own
    year = data.get("release_year")
    return f"{title} {year}" if year else title


def _drop_lone_franchise(data: dict, films_in_it: int, item: PhysicalItem) -> None:
    if data.get("franchise") and films_in_it < 2:
        data["franchise"] = None
        data["sort_title"] = item.sort_title or item.title


@router.get("/items/{item_id}")
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await _own_item(db, current_user.id, item_id)
    plays = await _watched_tmdb_ids(db, current_user.id)
    data = _summary(item, plays)
    specs = item.specs or {}
    if data["franchise"]:
        films_in_it = await db.scalar(select(func.count(PhysicalItem.id)).where(
            PhysicalItem.user_id == current_user.id, PhysicalItem.is_set.is_(False),
            PhysicalItem.specs["franchise"].astext == data["franchise"],
        ))
        _drop_lone_franchise(data, films_in_it, item)
    last_watched = None
    if item.tmdb_id and data["plays"]:
        last_watched = await db.scalar(
            select(func.max(WatchEvent.watched_at))
            .join(Media, Media.id == WatchEvent.media_id)
            .where(
                WatchEvent.user_id == current_user.id,
                WatchEvent.completed.is_(True),
                Media.media_type == MediaType.movie,
                Media.tmdb_id == item.tmdb_id,
            )
        )

    # Backdrop and film page from the film's TMDB entry when Watchd has it.
    backdrop = poster = None
    if item.media_id:
        backdrop, poster = (await db.execute(
            select(Media.backdrop_path, Media.poster_path).where(Media.id == item.media_id)
        )).one()
    if specs.get("tmdb_kind") == "tv" and item.tmdb_id and not (backdrop and poster):
        # Series keep their artwork in shows, or it's fetched from TMDB.
        show = (await db.execute(
            select(Show.backdrop_path, Show.poster_path).where(Show.tmdb_id == item.tmdb_id)
        )).first()
        if show and show[1]:
            backdrop, poster = backdrop or show[0], poster or show[1]
        else:
            try:
                data = await tmdb.get_show_light(item.tmdb_id, api_key=await get_user_tmdb_key(db, current_user.id))
                backdrop = backdrop or tmdb.poster_url(data.get("backdrop_path"), size="w1280")
                poster = poster or tmdb.poster_url(data.get("poster_path"))
            except Exception:
                pass
    data["cover"] = data["cover"] or _poster_thumb(poster)
    own_poster = _cover_url(specs.get("poster_image"))
    own_backdrop = _cover_url(specs.get("backdrop_image"))

    # A set's films, or the set a film is in (with the films beside it).
    set_item = item if item.is_set else item.parent
    contents = []
    if set_item is not None:
        rows = (await db.execute(
            select(PhysicalItem, func.coalesce(Media.poster_path, Show.poster_path))
            .outerjoin(Media, Media.id == PhysicalItem.media_id)
            .outerjoin(Show, (Show.tmdb_id == PhysicalItem.tmdb_id) & (PhysicalItem.specs["tmdb_kind"].astext == "tv"))
            .where(PhysicalItem.parent_id == set_item.id)
            .order_by(PhysicalItem.position.nulls_last(), PhysicalItem.release_year, PhysicalItem.title)
        )).all()
        contents = [
            {k: v for k, v in _summary(f, plays, p).items() if k in (
                "id", "title", "title_extension", "release_year", "cover", "seen", "plays", "is_tv", "format", "imdb_rating",
            )}
            for f, p in rows
        ]
    parent = None
    if item.parent is not None:
        p = item.parent
        parent = {
            "id": p.id, "title": p.title, "cover": _cover_url(p.cover_front, thumb=True), "format": p.format,
            "edition": p.edition, "barcode": p.barcode, "location": p.location, "purchase_date": p.purchase_date,
            "purchase_price": _num(p.purchase_price), "store": p.store, "condition": p.condition,
            "distributor": p.distributor,
        }
    other_editions = []
    if item.tmdb_id:
        rows = await db.execute(
            select(PhysicalItem.id, PhysicalItem.format, PhysicalItem.edition, PhysicalItem.status)
            .where(PhysicalItem.user_id == current_user.id, PhysicalItem.tmdb_id == item.tmdb_id, PhysicalItem.id != item.id)
        )
        other_editions = [{"id": i, "format": f, "edition": e, "status": s} for i, f, e, s in rows.all()]

    return {
        **data,
        "specs": specs,
        "own_sort_title": item.sort_title,
        "auto_sort": specs.get("auto_sort") if data["franchise"] else None,
        "current_value": _num(item.current_value),
        "owner": item.owner,
        "notes": item.notes,
        "viewing_date": item.viewing_date,
        "seen_it": item.seen_it,
        "last_watched": last_watched,
        "cover_full": _cover_url(item.cover_front) or own_poster or poster,
        # The disc's own poster and backdrop when set, else the film's.
        "front_cover": _cover_url(item.cover_front),
        "poster": own_poster or poster,
        "poster_is_own": bool(own_poster),
        "backdrop_is_own": bool(own_backdrop),
        "backdrop": own_backdrop or backdrop,
        "contents": contents,
        "parent": parent,
        "other_editions": other_editions,
    }


class ItemFields(BaseModel):
    status: str | None = None
    title: str | None = None
    sort_title: str | None = None
    is_tv: bool | None = None
    series: str | None = None
    tmdb_id: int | None = None
    release_year: int | None = None
    format: str | None = None
    edition: str | None = None
    distributor: str | None = None
    barcode: str | None = None
    package: str | None = None
    disc_count: int | None = None
    disc_release_date: date | None = None
    runtime: int | None = None
    purchase_date: date | None = None
    purchase_price: float | None = None
    current_value: float | None = None
    store: str | None = None
    condition: str | None = None
    location: str | None = None
    owner: str | None = None
    index_no: int | None = None
    my_rating: int | None = None
    seen_it: bool | None = None
    viewing_date: date | None = None
    notes: str | None = None
    tags: list[str] | None = None
    is_set: bool | None = None
    # The title of the set this release is in ("" takes it out); a new
    # title starts a new set.
    in_set: str | None = None
    # Merged into the stored specs; a key set to null removes it.
    specs: dict | None = None
    # On create: an image to use as the front cover until one is uploaded.
    cover_url: str | None = None


async def _apply(db: AsyncSession, user_id: int, item: PhysicalItem, fields: ItemFields) -> None:
    data = fields.model_dump(exclude_unset=True)
    data.pop("cover_url", None)
    tmdb_changed = "tmdb_id" in data and data["tmdb_id"] != item.tmdb_id
    if "in_set" in data:
        await _place_in_set(db, user_id, item, (data.pop("in_set") or "").strip())
    if "specs" in data:
        specs = dict(item.specs or {})
        for key, value in (data.pop("specs") or {}).items():
            if value in (None, "", []):
                specs.pop(key, None)
            else:
                specs[key] = value
        item.specs = specs
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(item, key, value)
    if not item.title:
        raise HTTPException(status_code=422, detail="A title is needed")
    item.edited_locally = True
    if item.is_set:
        item.parent_id = None
    if item.is_set and item.id is not None:
        # The films in a set are in the collection (or wish list) with it.
        for film in (await db.execute(select(PhysicalItem).where(PhysicalItem.parent_id == item.id))).scalars():
            film.status = item.status
    if tmdb_changed or (item.media_id is None and not item.is_set):
        await link_media(db, item, await get_user_tmdb_key(db, user_id))
    if tmdb_changed and not item.is_set:
        # Its franchise, so it files with the rest of it.
        found = await franchise_sort_keys([item], await get_user_tmdb_key(db, user_id), min_films=1)
        if item.id in found:
            set_franchise(item, found[item.id])


async def _place_in_set(db: AsyncSession, user_id: int, item: PhysicalItem, title: str) -> None:
    """Put a release in the set with this title (starting the set, with the
    release's shelf details, when there's none yet), or take it out."""
    if not title:
        item.parent_id = item.position = None
        return
    box = (await db.execute(
        select(PhysicalItem).where(PhysicalItem.user_id == user_id, PhysicalItem.is_set.is_(True), PhysicalItem.title == title)
        .order_by(PhysicalItem.id).limit(1)
    )).scalar_one_or_none()
    if box is None:
        box = PhysicalItem(
            user_id=user_id, title=title, is_set=True, status=item.status, specs={}, tags=[], edited_locally=True,
            **{k: getattr(item, k) for k in (
                "format", "distributor", "barcode", "package", "purchase_date", "purchase_price", "store",
                "condition", "location", "owner",
            )},
        )
        db.add(box)
        await db.flush()
    if box.id == item.id or item.is_set:
        raise HTTPException(status_code=422, detail="A set can't go inside a set")
    if item.parent_id != box.id:
        item.parent_id = box.id
        last = await db.scalar(select(func.max(PhysicalItem.position)).where(PhysicalItem.parent_id == box.id))
        item.position = (last or 0) + 1
    item.status = box.status


class SetOrder(BaseModel):
    ids: list[int]


@router.put("/items/{item_id}/contents")
async def reorder_set(
    item_id: int,
    body: SetOrder,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Put a set's films in this order."""
    item = await _own_item(db, current_user.id, item_id)
    by_id = {f.id: f for f in item.contents}
    for position, film_id in enumerate(body.ids, 1):
        if film_id in by_id:
            by_id[film_id].position = position
    await db.commit()
    return {"ok": True}


@router.post("/items")
async def create_item(
    fields: ItemFields,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = PhysicalItem(user_id=current_user.id, title=fields.title or "", status=fields.status or "owned", specs={}, tags=[])
    db.add(item)
    await _apply(db, current_user.id, item, fields)
    api_key = await get_user_tmdb_key(db, current_user.id)
    if not item.is_set:
        await fill_from_tmdb(item, api_key)
        await refresh_imdb_ratings(db, [item], api_key)
    await db.flush()
    if fields.cover_url:
        raw = await fetch_cover(fields.cover_url)
        if raw:
            try:
                item.cover_front = save_cover(raw, f"item-{item.id}-front")
            except Exception:
                pass
    await rebuild_collection_mirror(db, current_user.id)
    await db.commit()
    return {"id": item.id}


@router.patch("/items/{item_id}")
async def update_item(
    item_id: int,
    fields: ItemFields,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await _own_item(db, current_user.id, item_id)
    await _apply(db, current_user.id, item, fields)
    await db.flush()
    await rebuild_collection_mirror(db, current_user.id)
    await db.commit()
    return {"id": item.id}


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await _own_item(db, current_user.id, item_id)
    # Deleting a set deletes the films in it too.
    for release in [item, *item.contents]:
        for slot in ART_SLOTS:
            _remove_files(_own_art(release, slot))
    for film in item.contents:
        await db.delete(film)
    await db.delete(item)
    await db.flush()
    await rebuild_collection_mirror(db, current_user.id)
    await db.commit()
    return {"deleted": item_id}


async def _store_art(db: AsyncSession, item: PhysicalItem, slot: str, data: bytes) -> str:
    # A fresh name each time, so browsers don't show the old image from cache.
    import time as _time

    try:
        stored = save_cover(data, f"item-{item.id}-{slot}-{int(_time.time())}")
    except Exception:
        raise HTTPException(status_code=422, detail="That isn't an image")
    old = _own_art(item, slot)
    _set_art(item, slot, stored)
    item.edited_locally = True
    await db.commit()
    if old and old != stored:
        _remove_files(old)
    return stored


@router.post("/items/{item_id}/cover")
async def upload_cover(
    item_id: int,
    side: str = Query("front", pattern="^(front|poster|backdrop)$"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a release's front cover, poster or backdrop."""
    item = await _own_item(db, current_user.id, item_id)
    stored = await _store_art(db, item, side, await file.read())
    return {"cover": _cover_url(stored)}


class ArtLink(BaseModel):
    side: str
    url: str


@router.post("/items/{item_id}/art-link")
async def art_from_link(
    item_id: int,
    body: ArtLink,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set one of a release's images from an image on the web (a TMDB
    image from the picker, or any https link)."""
    if body.side not in ART_SLOTS:
        raise HTTPException(status_code=422, detail="Unknown image")
    item = await _own_item(db, current_user.id, item_id)
    url = body.url.strip()
    # TMDB images in the picker are previews: fetch the original.
    url = re.sub(r"image\.tmdb\.org/t/p/w\d+/", "image.tmdb.org/t/p/original/", url)
    raw = await fetch_cover(url)
    if not raw:
        raise HTTPException(status_code=422, detail="Couldn't get an image from that link")
    stored = await _store_art(db, item, body.side, raw)
    return {"cover": _cover_url(stored)}


@router.delete("/items/{item_id}/art")
async def remove_art(
    item_id: int,
    side: str = Query(..., pattern="^(front|poster|backdrop)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove one of a release's images; a poster or backdrop goes back to
    the film's own from TMDB."""
    item = await _own_item(db, current_user.id, item_id)
    old = _own_art(item, side)
    _set_art(item, side, None)
    item.edited_locally = True
    await db.commit()
    _remove_files(old)
    return {"removed": side}


@router.get("/items/{item_id}/tmdb-images")
async def tmdb_images(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The film's or series' posters and backdrops on TMDB, to pick from."""
    item = await _own_item(db, current_user.id, item_id)
    if not item.tmdb_id:
        return {"posters": [], "backdrops": []}
    kind = (item.specs or {}).get("tmdb_kind") or ("tv" if item.is_tv else "movie")
    try:
        data = await tmdb.get_images(item.tmdb_id, kind, api_key=await get_user_tmdb_key(db, current_user.id))
    except Exception:
        return {"posters": [], "backdrops": []}

    def urls(images, size):
        ranked = sorted(images or [], key=lambda i: (i.get("vote_count") or 0, i.get("vote_average") or 0), reverse=True)
        return [f"https://image.tmdb.org/t/p/{size}{i['file_path']}" for i in ranked[:40] if i.get("file_path")]

    return {"posters": urls(data.get("posters"), "w342"), "backdrops": urls(data.get("backdrops"), "w780")}


@router.get("/covers/{name}")
async def get_cover(name: str, thumb: bool = False, current_user: User = Depends(get_current_user)):
    if not _COVER_NAME.match(name):
        raise HTTPException(status_code=404)
    path = cover_path(name, thumb)
    if thumb and (path is None or not path.exists()):
        path = cover_path(name)
    if path is None or not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# ── Statistics ───────────────────────────────────────────────────────────────

@router.get("/stats")
async def collection_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owned = (await db.execute(
        select(PhysicalItem).where(PhysicalItem.user_id == current_user.id, PhysicalItem.status == "owned")
    )).scalars().all()
    items = [i for i in owned if i.parent_id is None]
    titles = [i for i in owned if not i.is_set]
    plays = await _watched_tmdb_ids(db, current_user.id)

    def top(values, n=12):
        return [{"name": k, "count": v} for k, v in Counter(v for v in values if v).most_common(n)]

    by_year: dict[int, dict] = {}
    for i in items:
        if i.purchase_date:
            year = by_year.setdefault(i.purchase_date.year, {"year": i.purchase_date.year, "count": 0, "spent": 0.0})
            year["count"] += 1
            year["spent"] += float(i.purchase_price or 0)
    decades = Counter((i.release_year // 10) * 10 for i in titles if i.release_year)
    seen = sum(1 for i in titles if (i.tmdb_id and (i.specs or {}).get("tmdb_kind", "movie") == "movie" and plays.get(i.tmdb_id)) or i.seen_it)
    priced = [float(i.purchase_price) for i in items if i.purchase_price is not None]
    return {
        "owned": len(items),
        "titles": len(titles),
        "sets": sum(1 for i in items if i.is_set),
        "wishlist": await db.scalar(select(func.count(PhysicalItem.id)).where(
            PhysicalItem.user_id == current_user.id, PhysicalItem.status == "wishlist", PhysicalItem.parent_id.is_(None))),
        "discs": sum(i.disc_count or 1 for i in items),
        "films": sum(1 for i in titles if not i.is_tv),
        "tv": sum(1 for i in titles if i.is_tv),
        "seen": seen,
        "unseen": len(titles) - seen,
        "runtime_minutes": sum(i.runtime or 0 for i in titles),
        "spent": round(sum(priced), 2) if priced else None,
        "priced_count": len(priced),
        "formats": top((i.format for i in items), 10),
        "packages": top((i.package for i in items)),
        "distributors": top((i.distributor for i in items), 15),
        "stores": top((i.store for i in items), 15),
        "conditions": top((i.condition for i in items)),
        "regions": top((r for i in items for r in (i.specs or {}).get("regions", []))),
        "genres": top((g for i in titles for g in (i.specs or {}).get("genres", [])), 15),
        "directors": top((d for i in titles for d in (_director(i.specs or {}) or "").split("; ")), 15),
        "decades": [{"name": f"{d}s", "count": c} for d, c in sorted(decades.items())],
        "by_purchase_year": [by_year[y] for y in sorted(by_year)],
    }


# ── Adding releases ──────────────────────────────────────────────────────────

_PRODUCT_NOISE = re.compile(
    r"\[[^\]]*\]|\((?:[^)]*(?:blu-?ray|4k|uhd|dvd|digital|steelbook|edition|disc)[^)]*)\)|"
    r"\b(?:4k|ultra hd|uhd|blu-?ray|dvd|digital(?: code| hd)?|steelbook|\d+[- ]disc)\b",
    re.I,
)


# A studio or label put before the title: "Warner Home Video - Wonder Woman".
_STUDIO_PREFIX = re.compile(
    r"^[^-]*\b(?:video|entertainment|pictures|studios?|films?|home|media|distribution|"
    r"warner|universal|disney|paramount|sony|lionsgate|fox|mgm|criterion|arrow|kino)\b[^-]*\s+-\s+",
    re.I,
)


def clean_product_title(title: str, brand: str | None = None) -> str:
    """A film title from a shop listing, e.g. "Dune (4K Ultra HD + Blu-ray)
    [Steelbook]" -> "Dune", "Warner Home Video - Wonder Woman" -> "Wonder Woman"."""
    title = title or ""
    if brand and title.lower().startswith(brand.lower()):
        title = title[len(brand):].lstrip(" -:")
    title = _STUDIO_PREFIX.sub("", title)
    cleaned = _PRODUCT_NOISE.sub(" ", title)
    cleaned = re.sub(r"[\s+/&,:-]+$", "", re.sub(r"\s{2,}", " ", cleaned)).strip(" -+/,:")
    return cleaned or (title or "").strip()


@router.get("/lookup")
async def lookup(
    barcode: str | None = None,
    q: str | None = None,
    tmdb_id: int | None = None,
    kind: str = Query("movie", pattern="^(movie|tv)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Candidates for a new release: the product a barcode belongs to (from
    UPCitemdb's free lookup) and matching TMDB films and series, or the one
    film or series with `tmdb_id`."""
    if tmdb_id:
        api_key = await get_user_tmdb_key(db, current_user.id)
        try:
            data = await (tmdb.get_show_light(tmdb_id, api_key=api_key) if kind == "tv" else tmdb.get_movie_releases(tmdb_id, api_key=api_key))
        except Exception:
            raise HTTPException(status_code=404, detail="Not found on TMDB")
        return {"product": None, "query": None, "results": [{
            "kind": kind,
            "tmdb_id": tmdb_id,
            "title": data.get("title") or data.get("name"),
            "year": (data.get("release_date") or data.get("first_air_date") or "")[:4] or None,
            "poster": tmdb.poster_url(data.get("poster_path"), size="w185"),
        }]}
    product = None
    if barcode:
        existing = (await db.execute(
            select(PhysicalItem.id, PhysicalItem.title, PhysicalItem.status)
            .where(PhysicalItem.user_id == current_user.id, PhysicalItem.barcode == barcode.strip())
        )).first()
        if existing:
            product = {"already": {"id": existing[0], "title": existing[1], "status": existing[2]}}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.get("https://api.upcitemdb.com/prod/trial/lookup", params={"upc": barcode.strip()})
            found = (res.json().get("items") or [None])[0] if res.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            found = None
        if found:
            product = {
                **(product or {}),
                "title": found.get("title"),
                "brand": found.get("brand"),
                "images": found.get("images") or [],
            }
            q = q or clean_product_title(found.get("title") or "", found.get("brand"))
    results = []
    if q:
        api_key = await get_user_tmdb_key(db, current_user.id)
        movies = await tmdb.search_movies(q, api_key=api_key)
        shows = await tmdb.search_shows(q, api_key=api_key)
        for kind, data in (("movie", movies), ("tv", shows)):
            for r in (data.get("results") or [])[:6]:
                results.append({
                    "kind": kind,
                    "tmdb_id": r.get("id"),
                    "title": r.get("title") or r.get("name"),
                    "year": (r.get("release_date") or r.get("first_air_date") or "")[:4] or None,
                    "poster": tmdb.poster_url(r.get("poster_path"), size="w185"),
                    "popularity": r.get("popularity") or 0,
                })
        results.sort(key=lambda r: r["popularity"], reverse=True)
    return {"product": product, "query": q, "results": results}


# Offered before any disc has one.
_DEFAULT_PICKS = {"format": ["Blu-ray", "4K UHD", "Blu-ray 3D", "DVD"], "color": ["Color", "Black & White"]}


async def _pick_counts(db: AsyncSession, user_id: int) -> dict[str, Counter]:
    """How many discs use each value of each pick list, with hand-added
    values (used by none yet) at 0."""
    items = (await db.execute(select(PhysicalItem).where(PhysicalItem.user_id == user_id))).scalars().all()
    counts = {field: Counter() for field in PICK_LISTS}
    for item in items:
        for field in PICK_LISTS:
            counts[field].update(set(pick_values(item, field)))
    added = (await db.execute(
        select(PhysicalPickValue.field, PhysicalPickValue.value).where(PhysicalPickValue.user_id == user_id)
    )).all()
    for field, value in added:
        if field in counts:
            counts[field].setdefault(value, 0)
    for field, values in _DEFAULT_PICKS.items():
        if not counts[field]:
            for value in values:
                counts[field].setdefault(value, 0)
    return counts


@router.get("/options")
async def field_options(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The values of each pick list, for the edit form."""
    counts = await _pick_counts(db, current_user.id)
    boxes = (await db.execute(select(PhysicalItem.title).where(
        PhysicalItem.user_id == current_user.id, PhysicalItem.is_set.is_(True)))).scalars().all()
    options = {field: sorted(c, key=str.lower) for field, c in counts.items()}
    options["in_set"] = sorted(set(boxes), key=str.lower)
    return options


@router.get("/picklists")
async def picklists(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every pick list with its values and how many discs use each."""
    counts = await _pick_counts(db, current_user.id)
    return {"lists": [
        {
            "key": field,
            "label": label,
            "group": group,
            "many": many,
            "values": [{"value": v, "count": counts[field][v]} for v in sorted(counts[field], key=str.lower)],
        }
        for field, (label, group, _, many) in PICK_LISTS.items()
    ]}


class PickChange(BaseModel):
    value: str
    new_value: str | None = None


def _pick_field(field: str) -> str:
    if field not in PICK_LISTS:
        raise HTTPException(status_code=404, detail="No such pick list")
    return field


@router.post("/picklists/{field}")
async def add_pick_value(
    field: str,
    body: PickChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a value to a pick list before any disc uses it."""
    _pick_field(field)
    value = body.value.strip()
    if not value:
        raise HTTPException(status_code=422, detail="Type a value")
    exists = await db.scalar(select(PhysicalPickValue.id).where(
        PhysicalPickValue.user_id == current_user.id, PhysicalPickValue.field == field, PhysicalPickValue.value == value,
    ))
    if not exists:
        db.add(PhysicalPickValue(user_id=current_user.id, field=field, value=value))
        await db.commit()
    return {"added": value}


@router.patch("/picklists/{field}")
async def rename_pick_value(
    field: str,
    body: PickChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rename a value on every disc that has it. Renaming to a value that's
    already in the list merges the two."""
    _pick_field(field)
    new = (body.new_value or "").strip()
    if not new:
        raise HTTPException(status_code=422, detail="Type the new name")
    items = (await db.execute(select(PhysicalItem).where(PhysicalItem.user_id == current_user.id))).scalars().all()
    changed = replace_pick_value(items, field, body.value, new)
    await _rename_added(db, current_user.id, field, body.value, new)
    await db.commit()
    return {"changed": changed}


@router.delete("/picklists/{field}")
async def remove_pick_value(
    field: str,
    value: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Take a value off the list and off every disc that has it."""
    _pick_field(field)
    items = (await db.execute(select(PhysicalItem).where(PhysicalItem.user_id == current_user.id))).scalars().all()
    changed = replace_pick_value(items, field, value, None)
    await _rename_added(db, current_user.id, field, value, None)
    await db.commit()
    return {"changed": changed}


async def _rename_added(db: AsyncSession, user_id: int, field: str, old: str, new: str | None) -> None:
    """Keep a hand-added value's entry in step when it's renamed or removed."""
    row = await db.scalar(select(PhysicalPickValue).where(
        PhysicalPickValue.user_id == user_id, PhysicalPickValue.field == field, PhysicalPickValue.value == old,
    ))
    if row is None:
        return
    taken = new is not None and await db.scalar(select(PhysicalPickValue.id).where(
        PhysicalPickValue.user_id == user_id, PhysicalPickValue.field == field, PhysicalPickValue.value == new,
    ))
    if new is None or taken:
        await db.delete(row)
    else:
        row.value = new
