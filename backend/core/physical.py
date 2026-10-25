"""Shared helpers for the physical disc collection: cover images, linking a
release to its film, and keeping the site-wide "in collection" entries in
step with the discs the user owns."""

import io
from datetime import datetime
from pathlib import Path

from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core import tmdb
from core.enrichment import enrich_media
from models.base import CollectionSource, MediaType
from models.collection import Collection, CollectionFile
from models.media import Media
from models.physical import PhysicalItem

COVERS_DIR = "physical/covers"
THUMB_WIDTH = 400


def covers_root() -> Path:
    root = Path(settings.data_dir) / COVERS_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def cover_path(name: str | None, thumb: bool = False) -> Path | None:
    """The file for a stored cover name, or its thumbnail."""
    if not name:
        return None
    path = covers_root() / name
    if thumb:
        path = path.with_name(f"{path.stem}-thumb.jpg")
    return path


def save_cover(data: bytes, name: str) -> str:
    """Store a cover image as `name`.jpg with a small thumbnail beside it, and
    return the stored name."""
    image = Image.open(io.BytesIO(data))
    image = image.convert("RGB")
    stored = f"{name}.jpg"
    full = covers_root() / stored
    image.save(full, "JPEG", quality=90)
    if image.width > THUMB_WIDTH:
        image = image.resize((THUMB_WIDTH, round(image.height * THUMB_WIDTH / image.width)), Image.LANCZOS)
    image.save(cover_path(stored, thumb=True), "JPEG", quality=82)
    return stored


async def link_media(db: AsyncSession, item: PhysicalItem, api_key: str | None) -> None:
    """Point a film release at its movie row, creating the row from TMDB if
    the film isn't in Watchd yet. Series releases aren't linked to a row."""
    if item.is_tv or not item.tmdb_id or (item.specs or {}).get("tmdb_kind") == "tv":
        item.media_id = None
        return
    media = (await db.execute(
        select(Media).where(Media.media_type == MediaType.movie, Media.tmdb_id == item.tmdb_id)
        .order_by(Media.id).limit(1)
    )).scalar_one_or_none()
    if media is None:
        media = Media(media_type=MediaType.movie, tmdb_id=item.tmdb_id, title=item.title)
        await enrich_media(media, api_key=api_key)
        if not media.tmdb_data:
            # Collectorz sometimes holds a stale TMDB id; its IMDb id finds the film.
            corrected = await _tmdb_id_from_imdb((item.specs or {}).get("imdb_id"), api_key)
            if corrected and corrected != item.tmdb_id:
                item.tmdb_id = corrected
                await link_media(db, item, api_key)
                return
            # Not a film TMDB knows: keep the release unlinked rather than
            # adding an empty movie row.
            item.media_id = None
            return
        db.add(media)
        await db.flush()
    item.media_id = media.id


async def _tmdb_id_from_imdb(imdb_id: str | None, api_key: str | None) -> int | None:
    if not imdb_id:
        return None
    try:
        found = await tmdb.find_by_external_id(imdb_id, "imdb_id", api_key=api_key)
    except Exception:
        return None
    results = found.get("movie_results") or []
    return results[0].get("id") if results else None


async def rebuild_collection_mirror(db: AsyncSession, user_id: int) -> int:
    """Make the user's collection entries exactly the films they own on disc.

    The rest of the site (card badges, filters, the film page) reads the
    collection table, so it mirrors the physical collection. Returns how many
    films are in it.
    """
    owned = (await db.execute(
        select(PhysicalItem.media_id, PhysicalItem.id, PhysicalItem.date_added).where(
            PhysicalItem.user_id == user_id,
            PhysicalItem.status == "owned",
            PhysicalItem.media_id.is_not(None),
        ).order_by(PhysicalItem.date_added)
    )).all()

    await db.execute(delete(Collection).where(Collection.user_id == user_id))
    await db.flush()

    by_media: dict[int, list[tuple[int, datetime]]] = {}
    for media_id, item_id, added in owned:
        by_media.setdefault(media_id, []).append((item_id, added))
    for media_id, releases in by_media.items():
        collection = Collection(user_id=user_id, media_id=media_id, added_at=releases[0][1])
        db.add(collection)
        await db.flush()
        for item_id, _ in releases:
            db.add(CollectionFile(collection_id=collection.id, source=CollectionSource.physical, source_id=str(item_id)))
    await db.flush()
    return len(by_media)


# Columns a Collectorz import fills in (everything but ids, links and covers).
_IMPORTED_COLUMNS = (
    "status", "title", "sort_title", "is_tv", "series", "tmdb_id", "release_year",
    "format", "edition", "distributor", "barcode", "package", "disc_count",
    "disc_release_date", "runtime", "purchase_date", "purchase_price", "current_value",
    "store", "condition", "location", "owner", "index_no", "my_rating", "seen_it",
    "viewing_date", "notes", "tags", "specs",
)


async def import_clz_records(
    db: AsyncSession,
    user_id: int,
    items: list[dict],
    box_sets: list[dict],
    read_image,
    api_key: str | None,
) -> dict:
    """Add or update releases and box sets parsed from a Collectorz export.

    Releases are matched on their Collectorz id; ones edited in Watchd since
    are left alone. `read_image(path)` returns a cover's bytes, or None when
    it isn't available. Returns counts of what changed.
    """
    from models.physical import PhysicalBoxSet

    counts = {"added": 0, "updated": 0, "kept_local_edits": 0, "covers": 0, "box_sets": 0}

    existing_sets = {
        b.name: b for b in (await db.execute(select(PhysicalBoxSet).where(PhysicalBoxSet.user_id == user_id))).scalars()
    }
    for data in box_sets:
        box = existing_sets.get(data["name"])
        if box is None:
            box = PhysicalBoxSet(user_id=user_id, name=data["name"])
            db.add(box)
            existing_sets[data["name"]] = box
            counts["box_sets"] += 1
        for key in ("upc", "purchase_date", "release_date", "store", "condition", "notes"):
            setattr(box, key, data.get(key))
    await db.flush()
    for data in box_sets:
        box = existing_sets[data["name"]]
        for side in ("front", "back"):
            raw = read_image(data.get(f"cover_{side}"))
            if raw:
                setattr(box, f"cover_{side}", save_cover(raw, f"boxset-{box.id}-{side}"))

    existing = {
        i.clz_id: i for i in (await db.execute(
            select(PhysicalItem).where(PhysicalItem.user_id == user_id, PhysicalItem.clz_id.is_not(None))
        )).scalars()
    }
    for data in items:
        item = existing.get(data["clz_id"])
        if item is not None and item.edited_locally:
            counts["kept_local_edits"] += 1
            continue
        if item is None:
            item = PhysicalItem(user_id=user_id, clz_id=data["clz_id"])
            if data.get("date_added"):
                item.date_added = data["date_added"]
            db.add(item)
            counts["added"] += 1
        else:
            counts["updated"] += 1
        for key in _IMPORTED_COLUMNS:
            setattr(item, key, data.get(key))
        item.box_set_id = existing_sets[data["box_set"]].id if data.get("box_set") in existing_sets else None
        await link_media(db, item, api_key)
        for side in ("front", "back"):
            raw = read_image(data.get(f"cover_{side}"))
            if raw:
                setattr(item, f"cover_{side}", save_cover(raw, f"{data['clz_id']}-{side}"))
                counts["covers"] += 1
    await db.flush()
    counts["collection_films"] = await rebuild_collection_mirror(db, user_id)
    return counts


# How often each disc's IMDb rating is looked up again.
IMDB_REFRESH_DAYS = 7


async def refresh_imdb_ratings(db: AsyncSession, items: list[PhysicalItem], api_key: str | None) -> int:
    """Look up the current IMDb rating and votes of each release (finding
    its IMDb id through TMDB when Collectorz didn't have one). Returns how
    many ratings it got."""
    import asyncio
    from datetime import date

    async def one(item: PhysicalItem) -> bool:
        specs = dict(item.specs or {})
        # Collectorz writes 0.0 when it has no rating.
        if not specs.get("imdb_rating"):
            specs.pop("imdb_rating", None)
        imdb_id = specs.get("imdb_id")

        async def external_imdb(tmdb_id: int, kind: str) -> str | None:
            try:
                return (await tmdb.get_external_ids(tmdb_id, kind, api_key=api_key)).get("imdb_id")
            except Exception:
                return None

        # The stored TMDB id, as the kind Collectorz recorded it as (the same
        # number is an unrelated title as the other kind).
        if not imdb_id and item.tmdb_id:
            imdb_id = await external_imdb(item.tmdb_id, specs.get("tmdb_kind") or "movie")
        # No link, or a stale one: find the title on TMDB by name and year.
        # TV specials are often films on TMDB (and the reverse), so try both.
        kinds = ("tv", "movie") if item.is_tv else ("movie", "tv")
        for kind in kinds:
            if imdb_id:
                break
            try:
                search = tmdb.search_shows if kind == "tv" else tmdb.search_movies
                found = (await search(item.title, year=item.release_year, api_key=api_key)).get("results") or []
            except Exception:
                found = []
            if found:
                imdb_id = await external_imdb(found[0]["id"], kind)
        if imdb_id:
            specs["imdb_id"] = imdb_id
        rating, votes = await tmdb.get_imdb_score(imdb_id) if imdb_id else (None, None)
        if rating is not None:
            specs["imdb_rating"] = rating
            if votes is not None:
                specs["imdb_votes"] = votes
        specs["imdb_checked"] = date.today().isoformat()
        item.specs = specs
        return rating is not None

    got = sum(await asyncio.gather(*(one(i) for i in items)))
    await db.flush()
    return got


async def fill_from_tmdb(item: PhysicalItem, api_key: str | None) -> None:
    """Fill a new release's film details (plot, genres, cast, crew...) from
    TMDB, keeping anything already entered."""
    if not item.tmdb_id:
        return
    is_tv = item.is_tv or (item.specs or {}).get("tmdb_kind") == "tv"
    try:
        data = await (tmdb.get_show(item.tmdb_id, api_key=api_key) if is_tv else tmdb.get_movie(item.tmdb_id, api_key=api_key))
    except Exception:
        return
    credits = data.get("aggregate_credits") or data.get("credits") or {}
    jobs = {"Director": "Director", "Screenplay": "Writer", "Writer": "Writer", "Original Music Composer": "Composer", "Producer": "Producer", "Director of Photography": "Cinematography"}
    found = {
        "tmdb_kind": "tv" if is_tv else "movie",
        "plot": data.get("overview"),
        "tagline": data.get("tagline"),
        "genres": [g["name"] for g in data.get("genres") or []],
        "studios": [c["name"] for c in data.get("production_companies") or []][:4],
        "country": next((c.get("name") for c in data.get("production_countries") or []), None),
        "language": next((lang.get("english_name") for lang in data.get("spoken_languages") or []), None),
        "imdb_id": (data.get("external_ids") or {}).get("imdb_id") or data.get("imdb_id"),
        "imdb_rating": None,
        "cast": [
            {"name": c.get("name"), "character": c.get("character") or ", ".join(r.get("character", "") for r in c.get("roles") or [])}
            for c in (credits.get("cast") or [])[:30]
        ],
        "crew": [
            {"name": c.get("name"), "role": jobs[c["job"]]}
            for c in credits.get("crew") or [] if c.get("job") in jobs
        ][:20],
    }
    specs = dict(item.specs or {})
    for key, value in found.items():
        if value and not specs.get(key):
            specs[key] = value
    item.specs = specs
    year = (data.get("release_date") or data.get("first_air_date") or "")[:4]
    if not item.release_year and year.isdigit():
        item.release_year = int(year)
    if not item.runtime:
        item.runtime = data.get("runtime") or next(iter(data.get("episode_run_time") or []), None)
    if is_tv:
        item.is_tv = True


async def fetch_cover(url: str) -> bytes | None:
    """An image from the web for a release's cover (a TMDB poster or a shop's
    product photo)."""
    import httpx

    if not url.startswith("https://"):
        return None
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            res = await client.get(url)
    except httpx.HTTPError:
        return None
    if res.status_code != 200 or not res.headers.get("content-type", "").startswith("image/") or len(res.content) > 15_000_000:
        return None
    return res.content
