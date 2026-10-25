"""Reading a Collectorz.com Movie Collector XML export into physical
collection records.

parse_clz() turns the export into plain dicts: one per release (matching the
PhysicalItem columns, with everything else under "specs") and one per box
set. Cover paths are left as the file paths in the export; copying the images
is the importer's job.
"""

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime

STATUSES = {
    "in collection": "owned",
    "on wish list": "wishlist",
    "on order": "ordered",
    "for sale": "for_sale",
    "sold": "sold",
}

# Collectorz's user-defined fields, by label.
CUSTOM_FIELDS = {
    "movie tagline": "tagline",
    "adaptation of": "adaptation_of",
    "adapted title(s)": "adapted_titles",
    "cinema": "seen_in_cinema",
}


def _text(e: ET.Element | None, path: str) -> str | None:
    if e is None:
        return None
    value = e.findtext(path)
    value = value.strip() if value else None
    return value or None


def _names(e: ET.Element, path: str) -> list[str]:
    return [n for n in (_text(x, "displayname") for x in e.findall(path)) if n]


def _int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float(value: str | None) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_date(value: str | None) -> date | None:
    """"08/21/2024" (Collectorz is US-dated) or "08/21/2024 19:08:49"; a bare
    year isn't a date."""
    if not value:
        return None
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _bool(e: ET.Element, tag: str) -> bool:
    for x in e.findall(tag):
        if x.get("boolvalue") is not None:
            return x.get("boolvalue") in ("1", "True", "true")
    return False


def _person(p: ET.Element) -> dict:
    return {
        "name": _text(p, "person/displayname"),
        "imdb_url": _text(p, "person/url"),
        "image": _text(p, "person/imageurl"),
    }


def _imdb_id(url: str | None) -> str | None:
    match = re.search(r"(tt\d+)", url or "")
    return match.group(1) if match else None


def _episode(e: ET.Element) -> dict:
    return {
        "title": _text(e, "title"),
        "number": _int(_text(e, "sequencenumber")),
        "runtime": _int(_text(e, "runtimeminutes")),
        "first_aired": _text(e, "firstairdate/date"),
        "plot": _text(e, "plot"),
        "imdb_url": _text(e, "imdburl"),
    }


def _disc(d: ET.Element, extras_text: str | None) -> dict:
    disc = {
        "title": _text(d, "title"),
        "format": _text(d, "format/displayname"),
        "features": _names(d, "features/feature"),
        "episodes": [_episode(e) for e in d.findall("episodes/episode")],
    }
    extras = _text(d, "extrafeatures")
    # Single-disc releases repeat the release's extras on the disc.
    if extras and extras != extras_text:
        disc["extra_features"] = extras
    return disc


def _custom_fields(m: ET.Element) -> dict:
    fields = {}
    for u in m.findall("userdefinedvalues/userdefinedvalue"):
        key = CUSTOM_FIELDS.get((_text(u, "userdefinedfield/label") or "").lower())
        value = _text(u, "lookupitem/displayname") or _text(u, "value")
        if key and value:
            fields[key] = value
    return fields


def parse_box_set(m: ET.Element) -> dict | None:
    b = m.find("boxset")
    name = _text(b, "displayname")
    if not name:
        return None
    return {
        "name": name,
        "upc": _text(b, "upc"),
        "cover_front": _text(b, "frontcover"),
        "cover_back": _text(b, "backcover"),
        "purchase_date": parse_date(_text(b, "purchasedate/date")),
        "release_date": parse_date(_text(b, "releasedate/date")),
        "store": _text(b, "store/displayname"),
        "condition": _text(b, "condition/displayname"),
        "notes": _text(b, "notes"),
    }


def parse_movie(m: ET.Element) -> dict:
    extras_text = _text(m, "extrafeatures")
    tmdb_url = _text(m, "tmdburl") or ""
    imdb_url = _text(m, "imdburl")
    custom = _custom_fields(m)
    specs = {
        "original_title": _text(m, "originaltitle"),
        "title_extension": _text(m, "titleextension"),
        "tmdb_kind": "tv" if "/tv/" in tmdb_url else "movie",
        "imdb_id": _imdb_id(imdb_url),
        "imdb_rating": _float(_text(m, "imdbrating")),
        "imdb_votes": _int(_text(m, "imdbvotes")),
        "plot": _text(m, "plot"),
        "genres": _names(m, "genres/genre"),
        "studios": _names(m, "studios/studio"),
        "country": _text(m, "country/displayname"),
        "language": _text(m, "language/displayname"),
        "audience_rating": _text(m, "audiencerating/displayname"),
        "formats": _names(m, "formats/format"),
        "regions": _names(m, "regions/region"),
        "ratios": _names(m, "ratios/ratio"),
        "audio": _names(m, "audios/audio"),
        "subtitles": _names(m, "subtitles/subtitle"),
        "features": _names(m, "features/feature"),
        "extras": _names(m, "extras/extra"),
        "extra_features": extras_text,
        "layers": None if _text(m, "layers") in (None, "N/A") else _text(m, "layers"),
        "color": _text(m, "color"),
        "hdr": None if _text(m, "hdr") in (None, "N/A") else _text(m, "hdr"),
        "chapters": _int(_text(m, "chapters")) or None,
        "seen_where": _text(m, "seenwhere"),
        "discs": [_disc(d, extras_text) for d in m.findall("discs/disc")],
        "cast": [
            {**_person(s), "character": _text(s, "character")}
            for s in sorted(m.findall("cast/star"), key=lambda s: _int(_text(s, "sequence")) or 0)
        ],
        "crew": [
            {**_person(c), "role": _text(c, "role")}
            for c in sorted(m.findall("crew/crewmember"), key=lambda c: _int(_text(c, "sequence")) or 0)
        ],
        "links": [
            {"description": _text(link, "description"), "url": _text(link, "url")}
            for link in m.findall("links/link") if _text(link, "url")
        ],
        "clz_movie_id": _int(_text(m, "bpmovieid")),
        "clz_media_id": _int(_text(m, "bpmediaid")),
        **custom,
    }
    rating = _int(m.findtext("myrating"))
    return {
        "clz_id": _int(_text(m, "id")),
        "status": STATUSES.get((_text(m, "collectionstatus") or "").lower(), "owned"),
        "title": _text(m, "title") or "Untitled",
        "sort_title": _text(m, "titlesort"),
        "is_tv": _bool(m, "istvseries"),
        "series": _text(m, "series/displayname"),
        "tmdb_id": _int(_text(m, "tmdbid")),
        "release_year": _int(_text(m, "releasedate/year/displayname")),
        "format": _text(m, "format/displayname"),
        "edition": _text(m, "edition/displayname"),
        "distributor": _text(m, "distributor/displayname"),
        "barcode": _text(m, "upc"),
        "package": _text(m, "package/displayname"),
        "disc_count": _int(_text(m, "nritems")),
        "disc_release_date": parse_date(_text(m, "dvdreleasedate/date")),
        "runtime": _int(_text(m, "runtime")) or None,
        "purchase_date": parse_date(_text(m, "purchasedate/date")),
        "purchase_price": _float(_text(m, "purchaseprice")),
        "current_value": _float(_text(m, "currentvalue")),
        "store": _text(m, "store/displayname"),
        "condition": _text(m, "condition/displayname"),
        "location": _text(m, "location/displayname"),
        "owner": _text(m, "owner/displayname"),
        "index_no": _int(_text(m, "index")) or None,
        "my_rating": rating or None,
        "seen_it": _bool(m, "seenit"),
        "viewing_date": parse_date(_text(m, "viewingdate/date")),
        "notes": _text(m, "notes"),
        "tags": _names(m, "tags/tag"),
        "cover_front": _text(m, "coverfront"),
        "cover_back": _text(m, "coverback"),
        "date_added": parse_datetime(_text(m, "dateadded/date")),
        "box_set": _text(m, "boxset/displayname"),
        "specs": {k: v for k, v in specs.items() if v not in (None, [], "")},
    }


def parse_clz(source) -> tuple[list[dict], list[dict]]:
    """Releases and box sets from a Collectorz XML export (a path or file)."""
    root = ET.parse(source).getroot()
    movies = root.find("movielist")
    if movies is None:
        raise ValueError("Not a Collectorz Movie Collector export: no <movielist>")
    items, box_sets = [], {}
    for m in movies:
        items.append(parse_movie(m))
        box_set = parse_box_set(m)
        if box_set and box_set["name"] not in box_sets:
            box_sets[box_set["name"]] = box_set
    return items, list(box_sets.values())
