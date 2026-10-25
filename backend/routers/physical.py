"""The user's physical disc collection: browsing, editing, covers, loans,
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
from core.physical import cover_path, fetch_cover, fill_from_tmdb, link_media, rebuild_collection_mirror, refresh_imdb_ratings, save_cover
from db import get_db
from dependencies import get_current_user
from models.base import MediaType
from models.events import WatchEvent
from models.media import Media
from models.physical import PhysicalBoxSet, PhysicalItem, PhysicalLoan
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


def _director(specs: dict) -> str | None:
    names = [c.get("name") for c in specs.get("crew") or [] if c.get("role") == "Director" and c.get("name")]
    return "; ".join(names) or None


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


def _summary(item: PhysicalItem, plays: dict[int, int], on_loan: set[int], poster: str | None = None) -> dict:
    specs = item.specs or {}
    watched = bool(item.tmdb_id and plays.get(item.tmdb_id))
    return {
        "id": item.id,
        "status": item.status,
        "title": item.title,
        "sort_title": item.sort_title or item.title,
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
        "plays": plays.get(item.tmdb_id, 0) if item.tmdb_id else 0,
        "genres": specs.get("genres", []),
        "regions": specs.get("regions", []),
        "audience_rating": specs.get("audience_rating"),
        "imdb_rating": specs.get("imdb_rating"),
        "director": _director(specs),
        "box_set": item.box_set.name if item.box_set else None,
        "box_set_id": item.box_set_id,
        "tags": item.tags or [],
        "date_added": item.date_added,
        "on_loan": item.id in on_loan,
        "cover": _cover_url(item.cover_front, thumb=True) or _poster_thumb(poster),
    }


async def _active_loans(db: AsyncSession, user_id: int) -> dict[int, PhysicalLoan]:
    rows = await db.execute(
        select(PhysicalLoan)
        .join(PhysicalItem, PhysicalItem.id == PhysicalLoan.item_id)
        .where(PhysicalItem.user_id == user_id, PhysicalLoan.returned_on.is_(None))
    )
    return {loan.item_id: loan for loan in rows.scalars()}


async def _own_item(db: AsyncSession, user_id: int, item_id: int) -> PhysicalItem:
    item = (await db.execute(
        select(PhysicalItem)
        .options(selectinload(PhysicalItem.box_set), selectinload(PhysicalItem.loans))
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
        select(PhysicalItem, Media.poster_path)
        .outerjoin(Media, Media.id == PhysicalItem.media_id)
        .options(selectinload(PhysicalItem.box_set))
        .where(PhysicalItem.user_id == current_user.id)
    )).all()
    plays = await _watched_tmdb_ids(db, current_user.id)
    on_loan = set(await _active_loans(db, current_user.id))
    # Empty fields are left out: it's the whole collection in one response.
    return {"items": [
        {k: v for k, v in _summary(i, plays, on_loan, poster).items() if v not in (None, "", [], False)}
        for i, poster in rows
    ]}


@router.get("/items/{item_id}")
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await _own_item(db, current_user.id, item_id)
    plays = await _watched_tmdb_ids(db, current_user.id)
    active = {loan.item_id: loan for loan in item.loans if loan.returned_on is None}
    data = _summary(item, plays, set(active))
    specs = item.specs or {}
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
    data["cover"] = data["cover"] or _poster_thumb(poster)

    siblings = []
    if item.box_set_id:
        rows = await db.execute(
            select(PhysicalItem.id, PhysicalItem.title, PhysicalItem.release_year, PhysicalItem.cover_front)
            .where(PhysicalItem.box_set_id == item.box_set_id, PhysicalItem.id != item.id)
            .order_by(PhysicalItem.release_year, PhysicalItem.title)
        )
        siblings = [
            {"id": i, "title": t, "release_year": y, "cover": _cover_url(c, thumb=True)} for i, t, y, c in rows.all()
        ]
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
        "current_value": _num(item.current_value),
        "owner": item.owner,
        "notes": item.notes,
        "viewing_date": item.viewing_date,
        "seen_it": item.seen_it,
        "last_watched": last_watched,
        "cover_full": _cover_url(item.cover_front) or poster,
        "cover_back": _cover_url(item.cover_back),
        "backdrop": backdrop,
        "box_set_items": siblings,
        "other_editions": other_editions,
        "loans": [
            {
                "id": loan.id, "loaned_to": loan.loaned_to, "loan_date": loan.loan_date,
                "due_date": loan.due_date, "returned_on": loan.returned_on, "notes": loan.notes,
            }
            for loan in sorted(item.loans, key=lambda loan: loan.loan_date, reverse=True)
        ],
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
    box_set: str | None = None
    # Merged into the stored specs; a key set to null removes it.
    specs: dict | None = None
    # On create: an image to use as the front cover until one is uploaded.
    cover_url: str | None = None


async def _apply(db: AsyncSession, user_id: int, item: PhysicalItem, fields: ItemFields) -> None:
    data = fields.model_dump(exclude_unset=True)
    data.pop("cover_url", None)
    tmdb_changed = "tmdb_id" in data and data["tmdb_id"] != item.tmdb_id
    if "box_set" in data:
        name = (data.pop("box_set") or "").strip()
        if name:
            box = (await db.execute(
                select(PhysicalBoxSet).where(PhysicalBoxSet.user_id == user_id, PhysicalBoxSet.name == name)
            )).scalar_one_or_none()
            if box is None:
                box = PhysicalBoxSet(user_id=user_id, name=name)
                db.add(box)
                await db.flush()
            item.box_set_id = box.id
        else:
            item.box_set_id = None
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
    if tmdb_changed or item.media_id is None:
        await link_media(db, item, await get_user_tmdb_key(db, user_id))


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
    for name in (item.cover_front, item.cover_back):
        for thumb in (False, True):
            path = cover_path(name, thumb)
            if path and path.exists():
                path.unlink()
    await db.delete(item)
    await db.flush()
    await rebuild_collection_mirror(db, current_user.id)
    await db.commit()
    return {"deleted": item_id}


@router.post("/items/{item_id}/cover")
async def upload_cover(
    item_id: int,
    side: str = Query("front", pattern="^(front|back)$"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await _own_item(db, current_user.id, item_id)
    try:
        stored = save_cover(await file.read(), f"item-{item.id}-{side}")
    except Exception:
        raise HTTPException(status_code=422, detail="That file isn't an image")
    setattr(item, f"cover_{side}", stored)
    item.edited_locally = True
    await db.commit()
    return {"cover": _cover_url(stored)}


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


# ── Loans ────────────────────────────────────────────────────────────────────

class LoanFields(BaseModel):
    loaned_to: str
    loan_date: date | None = None
    due_date: date | None = None
    notes: str | None = None


@router.post("/items/{item_id}/loans")
async def lend_item(
    item_id: int,
    fields: LoanFields,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await _own_item(db, current_user.id, item_id)
    if any(loan.returned_on is None for loan in item.loans):
        raise HTTPException(status_code=409, detail="It's already out on loan")
    if not fields.loaned_to.strip():
        raise HTTPException(status_code=422, detail="Who has it?")
    loan = PhysicalLoan(
        item_id=item.id, loaned_to=fields.loaned_to.strip(), loan_date=fields.loan_date or date.today(),
        due_date=fields.due_date, notes=fields.notes,
    )
    db.add(loan)
    await db.commit()
    return {"id": loan.id}


@router.post("/loans/{loan_id}/return")
async def return_loan(
    loan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loan = (await db.execute(
        select(PhysicalLoan).join(PhysicalItem, PhysicalItem.id == PhysicalLoan.item_id)
        .where(PhysicalLoan.id == loan_id, PhysicalItem.user_id == current_user.id)
    )).scalar_one_or_none()
    if loan is None:
        raise HTTPException(status_code=404)
    loan.returned_on = date.today()
    await db.commit()
    return {"returned_on": loan.returned_on}


@router.get("/loans")
async def list_loans(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = await db.execute(
        select(PhysicalLoan, PhysicalItem.title, PhysicalItem.format, PhysicalItem.cover_front)
        .join(PhysicalItem, PhysicalItem.id == PhysicalLoan.item_id)
        .where(PhysicalItem.user_id == current_user.id)
        .order_by(PhysicalLoan.returned_on.is_not(None), PhysicalLoan.loan_date.desc())
    )
    today = date.today()
    return {"loans": [
        {
            "id": loan.id, "item_id": loan.item_id, "title": title, "format": fmt,
            "cover": _cover_url(cover, thumb=True), "loaned_to": loan.loaned_to,
            "loan_date": loan.loan_date, "due_date": loan.due_date, "returned_on": loan.returned_on,
            "notes": loan.notes,
            "overdue": bool(loan.returned_on is None and loan.due_date and loan.due_date < today),
        }
        for loan, title, fmt, cover in rows.all()
    ]}


# ── Statistics ───────────────────────────────────────────────────────────────

@router.get("/stats")
async def collection_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = (await db.execute(
        select(PhysicalItem).where(PhysicalItem.user_id == current_user.id, PhysicalItem.status == "owned")
    )).scalars().all()
    plays = await _watched_tmdb_ids(db, current_user.id)

    def top(values, n=12):
        return [{"name": k, "count": v} for k, v in Counter(v for v in values if v).most_common(n)]

    by_year: dict[int, dict] = {}
    for i in items:
        if i.purchase_date:
            year = by_year.setdefault(i.purchase_date.year, {"year": i.purchase_date.year, "count": 0, "spent": 0.0})
            year["count"] += 1
            year["spent"] += float(i.purchase_price or 0)
    decades = Counter((i.release_year // 10) * 10 for i in items if i.release_year)
    seen = sum(1 for i in items if (i.tmdb_id and plays.get(i.tmdb_id)) or i.seen_it)
    priced = [float(i.purchase_price) for i in items if i.purchase_price is not None]
    return {
        "owned": len(items),
        "wishlist": await db.scalar(select(func.count(PhysicalItem.id)).where(
            PhysicalItem.user_id == current_user.id, PhysicalItem.status == "wishlist")),
        "discs": sum(i.disc_count or 1 for i in items),
        "films": sum(1 for i in items if not i.is_tv),
        "tv": sum(1 for i in items if i.is_tv),
        "seen": seen,
        "unseen": len(items) - seen,
        "runtime_minutes": sum(i.runtime or 0 for i in items),
        "spent": round(sum(priced), 2) if priced else None,
        "priced_count": len(priced),
        "formats": top((i.format for i in items), 10),
        "packages": top((i.package for i in items)),
        "distributors": top((i.distributor for i in items), 15),
        "stores": top((i.store for i in items), 15),
        "conditions": top((i.condition for i in items)),
        "regions": top((r for i in items for r in (i.specs or {}).get("regions", []))),
        "genres": top((g for i in items for g in (i.specs or {}).get("genres", [])), 15),
        "directors": top((d for i in items for d in (_director(i.specs or {}) or "").split("; ")), 15),
        "decades": [{"name": f"{d}s", "count": c} for d, c in sorted(decades.items())],
        "by_purchase_year": [by_year[y] for y in sorted(by_year)],
    }


# ── Adding releases ──────────────────────────────────────────────────────────

_PRODUCT_NOISE = re.compile(
    r"\[[^\]]*\]|\((?:[^)]*(?:blu-?ray|4k|uhd|dvd|digital|steelbook|edition|disc)[^)]*)\)|"
    r"\b(?:4k|ultra hd|uhd|blu-?ray|dvd|digital(?: code| hd)?|steelbook|\d+[- ]disc)\b",
    re.I,
)


def clean_product_title(title: str) -> str:
    """A film title from a shop listing, e.g. "Dune (4K Ultra HD + Blu-ray)
    [Steelbook]" -> "Dune"."""
    cleaned = _PRODUCT_NOISE.sub(" ", title or "")
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
            q = q or clean_product_title(found.get("title") or "")
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


@router.get("/options")
async def field_options(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Values already used for the pick-list fields, for the edit form."""
    items = (await db.execute(select(PhysicalItem).where(PhysicalItem.user_id == current_user.id))).scalars().all()
    boxes = (await db.execute(select(PhysicalBoxSet.name).where(PhysicalBoxSet.user_id == current_user.id))).scalars().all()

    def used(values):
        return sorted({v for v in values if v}, key=str.lower)

    return {
        "format": used(i.format for i in items) or ["Blu-ray", "4K UHD", "Blu-ray 3D", "DVD"],
        "package": used(i.package for i in items),
        "distributor": used(i.distributor for i in items),
        "store": used(i.store for i in items),
        "condition": used(i.condition for i in items),
        "location": used(i.location for i in items),
        "owner": used(i.owner for i in items),
        "series": used(i.series for i in items),
        "tags": used(t for i in items for t in i.tags or []),
        "regions": used(r for i in items for r in (i.specs or {}).get("regions", [])),
        "audio": used(a for i in items for a in (i.specs or {}).get("audio", [])),
        "subtitles": used(s for i in items for s in (i.specs or {}).get("subtitles", [])),
        "ratios": used(r for i in items for r in (i.specs or {}).get("ratios", [])),
        "features": used(f for i in items for f in (i.specs or {}).get("features", [])),
        "extras": used(e for i in items for e in (i.specs or {}).get("extras", [])),
        "audience_rating": used((i.specs or {}).get("audience_rating") for i in items),
        "adaptation_of": used((i.specs or {}).get("adaptation_of") for i in items),
        "box_set": sorted(boxes, key=str.lower),
    }
