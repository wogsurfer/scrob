"""Award nominations on record, from three open datasets on GitHub:

- DLu/oscar_data: every Academy Award nomination, films and nominees by IMDb id.
- SteveHedden/fckg: Golden Globe and BAFTA film nominations, with IMDb (and
  often TMDB) ids for the films and IMDb ids for many nominees.
- dmase2/emmys-data: Primetime Emmy nominations by show, nominee and role.
  Its TMDB links are sparse and sometimes wrong, so only the names are used.

TVDB lists nominations by title only, leaving the nominee to be worked out;
these say who it was. They're downloaded once a week, boiled down to one
shape and kept on disk:

    {"award": "Academy Awards", "category": "Actor in a Leading Role",
     "year": 2025 (the ceremony's, as TVDB has it), "winner": True,
     "works": [{"title", "imdb", "tmdb"}], "people": [{"name", "imdb"}],
     "detail": 'For playing "X"' | 'For episode "Y"' | None}
"""
import asyncio
import collections
import csv
import io
import re
import time
import unicodedata

import httpx

from core import disk_cache

_RAW = "https://raw.githubusercontent.com"
SOURCES = {
    "oscars": f"{_RAW}/DLu/oscar_data/main/oscars.csv",
    "emmys": f"{_RAW}/dmase2/emmys-data/HEAD/assets/data/emmy_nominations.csv",
    "globes": f"{_RAW}/SteveHedden/fckg/HEAD/data/instances/golden_globes_nominations.ttl",
    "baftas": f"{_RAW}/SteveHedden/fckg/HEAD/data/instances/bafta_nominations.ttl",
    "films": f"{_RAW}/SteveHedden/fckg/HEAD/data/instances/films.ttl",
    "people": f"{_RAW}/SteveHedden/fckg/HEAD/data/instances/people.ttl",
}
OSCARS, GLOBES, BAFTAS, EMMYS = "Academy Awards", "Golden Globe Awards", "BAFTA Awards", "Primetime Emmy Awards"
FILM_AWARDS = (OSCARS, GLOBES, BAFTAS)
_FRESH = 7 * 24 * 3600
_CACHE = ("award_data", "v3")

# Oscar classes that aren't nominations for a film's work.
_OSCAR_SKIP = {"SciTech", "Special"}
_SMALL = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to"}

_records: list[dict] | None = None
_index: dict | None = None
_loaded_at = 0.0
_lock = asyncio.Lock()
_refreshing: asyncio.Task | None = None


def norm(text: str | None) -> str:
    """Comparable titles and names: "Kill Bill: Volume 1" and "Kill Bill: Vol. 1"
    are the same, as are "&" and "and"."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", " ", t.replace("&", " and ")).strip()
    t = re.sub(r"\bvolume\b", "vol", t)
    return re.sub(r"^(the|a|an) ", "", t)


def _title_case(category: str) -> str:
    """"ACTOR IN A LEADING ROLE" -> "Actor in a Leading Role"; mixed case kept."""
    words = category.split()
    out = []
    for i, w in enumerate(words):
        if w.isupper():
            w = w.lower() if i and w.lower() in _SMALL else w.capitalize()
        out.append(w)
    return " ".join(out)


def _year(value) -> int | None:
    m = re.search(r"\d{4}", str(value or ""))
    return int(m.group()) if m else None


# ---------------------------------------------------------------- parsing

def parse_oscars(text: str) -> list[dict]:
    out = []
    for r in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if r.get("Class") in _OSCAR_SKIP or not r.get("Film"):
            continue
        films = r["Film"].split("|")
        film_ids = (r.get("FilmId") or "").split("|")
        names = [n for n in (r.get("Nominees") or "").split("|")]
        ids = (r.get("NomineeIds") or "").split("|")
        try:
            ceremony = 1928 + int(r["Ceremony"])
        except (TypeError, ValueError):
            continue
        out.append({
            "award": OSCARS,
            "category": _title_case(r.get("CanonicalCategory") or r.get("Category") or ""),
            "year": ceremony,
            "winner": (r.get("Winner") or "").lower() == "true",
            "works": [
                {"title": f, "imdb": film_ids[i] if i < len(film_ids) and film_ids[i].startswith("tt") else None, "tmdb": None}
                for i, f in enumerate(films) if f
            ],
            "people": [
                {"name": n.strip(), "imdb": ids[i] if i < len(ids) and ids[i].startswith("nm") else None}
                for i, n in enumerate(names) if n.strip()
            ],
            "detail": None,
        })
    return out


_EMMY_WORK = re.compile(r'^(.*?):\s*"(.+)"\s*$')
_SPLIT_NAMES = re.compile(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*")


def parse_emmys(text: str) -> list[dict]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        work = (r.get("work") or "").strip()
        if not work:
            continue
        m = _EMMY_WORK.match(work)
        show, episode = (m.group(1).strip(), m.group(2)) if m else (work, None)
        role = (r.get("role") or "").strip()
        detail = f'For playing "{role}"' if role else f'For episode "{episode}"' if episode else None
        out.append({
            "award": EMMYS,
            # The newest rows are written "Outstanding Casting For A Drama Series".
            "category": " ".join(
                w.lower() if i and w.lower() in _SMALL else w
                for i, w in enumerate((r.get("category") or "").split())
            ),
            "year": _year(r.get("year")),
            "winner": (r.get("winner") or "").lower() == "true",
            "works": [{"title": show, "imdb": None, "tmdb": None}],
            "people": [{"name": n, "imdb": None} for n in _SPLIT_NAMES.split(r.get("nominee") or "") if n.strip()],
            "detail": detail,
        })
    return out


_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"(?:\^\^\S+|@\w+)?|<[^>]+>|[^\s,]+')


def parse_turtle(text: str) -> dict[str, tuple[str, dict[str, list[str]]]]:
    """The subset of Turtle fckg writes: one subject per blank-line-separated
    block, `subject a Type ;` then `predicate object, object ;` lines."""
    out = {}
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        m = re.match(r"(\S+)\s+a\s+(\S+)\s*;(.*)\.\s*$", block, re.S)
        if not m:
            continue
        subject, kind, rest = m.groups()
        props: dict[str, list[str]] = collections.defaultdict(list)
        for statement in re.split(r";\s*\n", rest):
            predicate, _, objects = statement.strip().rstrip(";").strip().partition(" ")
            if predicate:
                props[predicate].extend(_TOKEN.findall(objects))
        out[subject] = (kind, props)
    return out


def _literal(values: list[str]) -> str | None:
    for v in values:
        m = re.match(r'"((?:[^"\\]|\\.)*)"', v)
        if m:
            return m.group(1).replace('\\"', '"')
    return None


def _ids(values: list[str]) -> dict[str, str | int]:
    ids: dict[str, str | int] = {}
    for v in values:
        if m := re.search(r"imdb\.com/(?:title|name)/((?:tt|nm)\d+)", v):
            ids["imdb"] = m.group(1)
        elif m := re.search(r"themoviedb\.org/movie/(\d+)", v):
            ids["tmdb"] = int(m.group(1))
    return ids


def parse_fckg(award: str, nominations: str, films: dict, people: dict) -> list[dict]:
    """fckg's nominations for one award, with films and people resolved."""
    graph = parse_turtle(nominations)
    categories = {s: _literal(p.get("rdfs:label", [])) for s, (k, p) in graph.items() if k == "msh:AwardCategory"}
    out = []
    shared: dict[tuple, dict] = {}
    for subject, (kind, p) in graph.items():
        if kind != "msh:Nomination":
            continue
        works = []
        for f in p.get("msh:hasFilm", []):
            fk, fp = films.get(f, (None, {}))
            ids = _ids(fp.get("msh:hasIdentifier", []))
            works.append({"title": _literal(fp.get("msh:title", []) or fp.get("rdfs:label", [])) or "",
                          "imdb": ids.get("imdb"), "tmdb": ids.get("tmdb")})
        nominees = []
        if _literal(p.get("msh:nomineeType", [])) != "FILM":
            for n in p.get("msh:hasNominee", []):
                nk, np_ = people.get(n, (None, {}))
                name = _literal(np_.get("msh:fullName", []) or np_.get("rdfs:label", []))
                if name:
                    nominees.append({"name": name, "imdb": _ids(np_.get("msh:hasIdentifier", [])).get("imdb")})
        film_year = _year(_literal(p.get("msh:yearFilm", [])))
        category = p.get("msh:hasCategory", [""])[0]
        # msh:Category_golden_globes_Best_Director... -> "Best Director..."
        label = categories.get(category) or re.sub(r"^msh:Category_[a-z_]+?_(?=[A-Z])", "", category).replace("_", " ")
        label = label.replace(" - ", " – ")  # as TVDB writes them
        record = {
            "award": award,
            "category": label,
            # The ceremony is early the next year.
            "year": film_year + 1 if film_year else None,
            "winner": "true" in p.get("msh:winner", []),
            "works": works,
            "people": nominees,
            "detail": None,
        }
        # A shared nomination (a film's producers) is one record per person
        # here; put them back together. Acting nominations stay apart: two
        # supporting actresses from one film are two nominations.
        key = (label, record["year"], record["winner"], tuple(w["title"] for w in works))
        same = shared.get(key) if not _ACTING.search(label) else None
        if same:
            same["people"].extend(n for n in nominees if n not in same["people"])
            continue
        shared[key] = record
        out.append(record)
    return out


_ACTING = re.compile(r"actor|actress|performance", re.I)


# ---------------------------------------------------------------- loading

async def _download() -> dict[str, str] | None:
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            texts = {}
            for name, url in SOURCES.items():
                response = await client.get(url)
                response.raise_for_status()
                texts[name] = response.text
            return texts
    except Exception as e:
        print(f"Award data download failed: {e!r}")
        return None


def build(texts: dict[str, str]) -> list[dict]:
    films = parse_turtle(texts["films"])
    people = parse_turtle(texts["people"])
    return [
        *parse_oscars(texts["oscars"]),
        *parse_fckg(GLOBES, texts["globes"], films, people),
        *parse_fckg(BAFTAS, texts["baftas"], films, people),
        *parse_emmys(texts["emmys"]),
    ]


def _build_index(records: list[dict]) -> dict:
    index = {key: collections.defaultdict(list) for key in ("imdb", "tmdb", "film_title", "show_title", "person_imdb", "person_name")}
    for i, r in enumerate(records):
        film = r["award"] in FILM_AWARDS
        for w in r["works"]:
            if w.get("imdb"):
                index["imdb"][w["imdb"]].append(i)
            if w.get("tmdb"):
                index["tmdb"][w["tmdb"]].append(i)
            if norm(w.get("title")):
                index["film_title" if film else "show_title"][norm(w["title"])].append(i)
        for p in r["people"]:
            if p.get("imdb"):
                index["person_imdb"][p["imdb"]].append(i)
            if norm(p.get("name")):
                index["person_name"][norm(p["name"])].append(i)
    return index


def _use(records: list[dict], saved_at: float) -> None:
    global _records, _index, _loaded_at
    _records, _index, _loaded_at = records, _build_index(records), saved_at


async def _refresh() -> None:
    texts = await _download()
    if not texts:
        return
    try:
        records = await asyncio.to_thread(build, texts)
    except Exception as e:
        print(f"Award data parse failed: {e!r}")
        return
    if records:
        disk_cache.save(*_CACHE, records)
        _use(records, time.time())


async def ensure_loaded() -> bool:
    """Load the records (from disk, or downloading them the first time);
    a week-old copy is used while a fresh one downloads in the background."""
    global _refreshing
    if _records is None:
        async with _lock:
            if _records is None:
                hit = await asyncio.to_thread(disk_cache.load, *_CACHE, float("inf"))
                if hit:
                    _use(hit[1], hit[0])
                else:
                    await _refresh()
    if _records is not None and time.time() - _loaded_at > _FRESH and (_refreshing is None or _refreshing.done()):
        _refreshing = asyncio.create_task(_refresh())
    return _records is not None


# ---------------------------------------------------------------- lookups

def _rows(ids) -> list[dict]:
    return [_records[i] for i in dict.fromkeys(ids)]


def film_records(imdb: str | None, tmdb_id: int | None, titles: set[str], year: int | None) -> list[dict]:
    """A film's Oscar, Golden Globe and BAFTA nominations. By id where the
    record has one; by title (and a ceremony a year or two after the film)
    where it doesn't."""
    if _index is None:
        return []
    found = [*_index["imdb"].get(imdb, []), *_index["tmdb"].get(tmdb_id, [])] if imdb or tmdb_id else []
    keys = {norm(t) for t in titles} - {""}
    for key in keys:
        for i in _index["film_title"].get(key, []):
            r = _records[i]
            ids = ({w.get("imdb") for w in r["works"]} | {w.get("tmdb") for w in r["works"]}) - {None}
            if ids and (imdb in ids or tmdb_id in ids or not (imdb or tmdb_id)):
                found.append(i)
            elif not ids and year and r["year"] and 0 <= r["year"] - year <= 2:
                found.append(i)
    return _rows(found)


def show_records(titles: set[str], first_year: int | None, last_year: int | None) -> list[dict]:
    """A show's Primetime Emmy nominations, by title, in the years it ran."""
    if _index is None:
        return []
    out = []
    for key in {norm(t) for t in titles} - {""}:
        for i in _index["show_title"].get(key, []):
            y = _records[i]["year"]
            if y and first_year and y < first_year:
                continue
            if y and last_year and y > last_year + 1:
                continue
            out.append(i)
    return _rows(out)


def person_records(imdb: str | None, name: str | None) -> list[dict]:
    """A person's nominations: by IMDb id, and by name where the record has
    no id for them (all the Emmys, some Globes and BAFTAs). Name matches
    still need checking against the person's credits."""
    if _index is None:
        return []
    found = list(_index["person_imdb"].get(imdb, [])) if imdb else []
    for i in _index["person_name"].get(norm(name), []):
        person = next((p for p in _records[i]["people"] if norm(p["name"]) == norm(name)), None)
        if person and (not person.get("imdb") or person["imdb"] == imdb):
            found.append(i)
    return _rows(found)
