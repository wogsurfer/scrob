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
    """Point a release at its film or series row (by its TMDB id and TMDB
    type), creating the row from TMDB if it isn't in Watchd yet."""
    if not item.tmdb_id:
        item.media_id = None
        return
    kind = MediaType.series if (item.specs or {}).get("tmdb_kind") == "tv" else MediaType.movie
    media = (await db.execute(
        select(Media).where(Media.media_type == kind, Media.tmdb_id == item.tmdb_id)
        .order_by(Media.id).limit(1)
    )).scalar_one_or_none()
    if media is None:
        media = Media(media_type=kind, tmdb_id=item.tmdb_id, title=item.series or item.title)
        await enrich_media(media, api_key=api_key)
        if not media.tmdb_data:
            if kind == MediaType.series:
                item.media_id = None
                return
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
    found = await tmdb_entry_from_imdb(imdb_id, api_key, prefer="movie")
    return found[0] if found and found[1] == "movie" else None


async def tmdb_entry_from_imdb(imdb_id: str | None, api_key: str | None, prefer: str = "movie") -> tuple[int, str] | None:
    """The TMDB (id, "movie" or "tv") for an IMDb id. A season set's IMDb
    id is its series'; a TV special is often a film on TMDB, so both are
    looked at, `prefer` first."""
    if not imdb_id:
        return None
    try:
        found = await tmdb.find_by_external_id(imdb_id, "imdb_id", api_key=api_key)
    except Exception:
        return None
    for kind in (prefer, "tv" if prefer == "movie" else "movie"):
        results = found.get(f"{kind}_results") or []
        if results:
            return results[0]["id"], kind
    return None


async def rebuild_collection_mirror(db: AsyncSession, user_id: int) -> int:
    """Make the user's collection entries exactly the films they own on disc.

    The rest of the site (card badges, filters, the film page) reads the
    collection table, so it mirrors the physical collection. Returns how many
    films are in it.
    """
    owned = (await db.execute(
        select(PhysicalItem.media_id, PhysicalItem.id, PhysicalItem.date_added)
        .join(Media, Media.id == PhysicalItem.media_id)
        .where(
            PhysicalItem.user_id == user_id,
            PhysicalItem.status == "owned",
            Media.media_type == MediaType.movie,
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
    are left alone. A box set becomes a set release (matched on its name)
    with its films inside. `read_image(path)` returns a cover's bytes, or
    None when it isn't available. Returns counts of what changed.
    """
    counts = {"added": 0, "updated": 0, "kept_local_edits": 0, "covers": 0, "box_sets": 0}

    existing_sets = {
        b.title: b for b in (await db.execute(
            select(PhysicalItem).where(PhysicalItem.user_id == user_id, PhysicalItem.is_set.is_(True))
        )).scalars()
    }
    for data in box_sets:
        box = existing_sets.get(data["name"])
        if box is None:
            box = PhysicalItem(user_id=user_id, title=data["name"], is_set=True, specs={}, tags=[])
            db.add(box)
            existing_sets[data["name"]] = box
            counts["box_sets"] += 1
        elif box.edited_locally:
            continue
        box.barcode = data.get("upc") or box.barcode
        box.disc_release_date = data.get("release_date") or box.disc_release_date
        for key in ("purchase_date", "store", "condition", "notes"):
            setattr(box, key, data.get(key) or getattr(box, key))
    await db.flush()
    for data in box_sets:
        box = existing_sets[data["name"]]
        raw = read_image(data.get("cover_front"))
        if raw:
            box.cover_front = save_cover(raw, f"boxset-{box.id}-front")

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
            existing[data["clz_id"]] = item
            counts["added"] += 1
        else:
            counts["updated"] += 1
        for key in _IMPORTED_COLUMNS:
            setattr(item, key, data.get(key))
        box = existing_sets.get(data.get("box_set") or "")
        if box is not None and item.parent_id != box.id:
            item.parent_id = box.id
            item.position = 1 + max((i.position or 0 for i in existing.values() if i.parent_id == box.id), default=0)
        elif box is None:
            item.parent_id = item.position = None
        await link_media(db, item, api_key)
        raw = read_image(data.get("cover_front"))
        if raw:
            item.cover_front = save_cover(raw, f"{data['clz_id']}-front")
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


# The pick lists the edit form offers, by key: (label, group, where it's
# kept, whether a disc holds a list of values). "column" is a PhysicalItem
# column, "specs" a key in its specs.
PICK_LISTS: dict[str, tuple[str, str, str, bool]] = {
    "format": ("Format", "Edition", "column", False),
    "edition": ("Edition", "Edition", "column", False),
    "distributor": ("Distributor", "Edition", "column", False),
    "package": ("Packaging", "Edition", "column", False),
    "series": ("Series", "Edition", "column", False),
    "audience_rating": ("Age rating", "Edition", "specs", False),
    "adaptation_of": ("Adaptation of", "Edition", "specs", False),
    "layers": ("Layers", "Edition", "specs", False),
    "hdr": ("HDR", "Edition", "specs", False),
    "color": ("Colour", "Edition", "specs", False),
    "regions": ("Regions", "Picture, sound and extras", "specs", True),
    "ratios": ("Aspect ratios", "Picture, sound and extras", "specs", True),
    "audio": ("Audio tracks", "Picture, sound and extras", "specs", True),
    "subtitles": ("Subtitles", "Picture, sound and extras", "specs", True),
    "features": ("On the disc", "Picture, sound and extras", "specs", True),
    "extras": ("In the box", "Picture, sound and extras", "specs", True),
    "store": ("Store", "Personal", "column", False),
    "condition": ("Condition", "Personal", "column", False),
    "location": ("Location", "Personal", "column", False),
    "owner": ("Owner", "Personal", "column", False),
    "tags": ("Tags", "Personal", "column", True),
}


def pick_values(item: PhysicalItem, field: str) -> list[str]:
    """A disc's values for a pick list (one or none for a single field)."""
    _, _, where, many = PICK_LISTS[field]
    raw = getattr(item, field) if where == "column" else (item.specs or {}).get(field)
    if many:
        return [v for v in raw or [] if v]
    return [raw] if raw else []


def set_pick_values(item: PhysicalItem, field: str, values: list[str]) -> None:
    _, _, where, many = PICK_LISTS[field]
    # Kept once each, in order.
    values = list(dict.fromkeys(v for v in values if v))
    value = (values or None) if many else (values[0] if values else None)
    if where == "column":
        setattr(item, field, value if value is not None or not many else [])
        return
    specs = dict(item.specs or {})
    if value is None:
        specs.pop(field, None)
    else:
        specs[field] = value
    item.specs = specs


def replace_pick_value(items: list[PhysicalItem], field: str, old: str, new: str | None) -> int:
    """Rename a value on every disc that has it (merging it into `new` when
    that's already used), or remove it when `new` is None. Returns how many
    discs changed."""
    changed = 0
    for item in items:
        values = pick_values(item, field)
        if old not in values:
            continue
        set_pick_values(item, field, [new if v == old else v for v in values if new is not None or v != old])
        item.edited_locally = True
        changed += 1
    return changed


# ── Franchise sort titles ────────────────────────────────────────────────────

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


def _episode(title: str) -> int | None:
    """Star Wars style numbering: "Episode IV - A New Hope" -> 4."""
    import re

    m = re.search(r"\bEpisode\s+([IVX]+)\b", title or "")
    return _ROMAN.get(m.group(1)) if m else None


def franchise_order(parts: list[dict]) -> list[int]:
    """A franchise's films in order: by episode number where they have one
    (Star Wars), otherwise by release date. Returns their TMDB ids."""
    def key(p):
        episode = _episode(p.get("title") or "")
        return (episode if episode is not None else 100, p.get("release_date") or "9999", p.get("title") or "")
    return [p["id"] for p in sorted(parts, key=key) if p.get("id")]


def franchise_name(name: str) -> str:
    """"The Fast and the Furious Collection" -> "The Fast and the Furious"."""
    import re

    return re.sub(r"\s*[-–]?\s*Collection$", "", name or "").strip()


async def franchise_sort_keys(
    items: list[PhysicalItem], api_key: str | None, min_films: int = 2,
) -> dict[int, tuple[str, str] | None]:
    """For each film, its TMDB franchise and a sort title that files it there
    in order ("Alien 03"), or None when it isn't part of one (or fewer than
    `min_films` of `items` are). Sets and series aren't looked up."""
    import asyncio
    from collections import Counter

    limit = asyncio.Semaphore(8)
    collections: dict[int, asyncio.Task] = {}

    async def collection(cid: int) -> dict:
        async with limit:
            return await tmdb.get_collection(cid, api_key=api_key)

    async def one(item: PhysicalItem):
        if item.is_set or not item.tmdb_id or (item.specs or {}).get("tmdb_kind") == "tv":
            return item.id, None
        try:
            async with limit:
                movie = await tmdb.get_movie_light(item.tmdb_id, api_key=api_key)
            belongs = movie.get("belongs_to_collection") or {}
            if not belongs.get("id"):
                return item.id, None
            if belongs["id"] not in collections:
                collections[belongs["id"]] = asyncio.ensure_future(collection(belongs["id"]))
            coll = await collections[belongs["id"]]
        except Exception:
            return item.id, "error"
        order = franchise_order(coll.get("parts") or [])
        if item.tmdb_id not in order:
            return item.id, None
        name = franchise_name(coll.get("name") or belongs.get("name") or "")
        return item.id, (name, f"{name} {order.index(item.tmdb_id) + 1:02d}")

    results = [r for r in await asyncio.gather(*(one(i) for i in items)) if r[1] != "error"]
    # A franchise you have one film of isn't worth filing as one.
    owned = Counter(found[0] for _, found in results if found)
    return {item_id: (found if found and owned[found[0]] >= min_films else None) for item_id, found in results}


def set_franchise(item: PhysicalItem, found: tuple[str, str] | None) -> None:
    specs = dict(item.specs or {})
    if found:
        specs["franchise"], specs["auto_sort"] = found
    else:
        specs.pop("franchise", None)
        specs.pop("auto_sort", None)
    item.specs = specs
