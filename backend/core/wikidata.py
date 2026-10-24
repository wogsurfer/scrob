"""Award wins and nominations from Wikidata, looked up by TMDB id.

TVDB's film award lists name the film but never the person, so Wikidata fills
in who was nominated (and adds people's awards that TVDB can't attribute).
Its coverage is good for the Oscars and patchier for other awards, so callers
treat it as a supplement rather than the full record.
"""
import asyncio
import re
import time

import httpx

from core import disk_cache

_ENDPOINT = "https://query.wikidata.org/sparql"
# Wikimedia's robot policy wants the client, a contact URL and the library;
# requests without them get blocked.
_HEADERS = {
    "User-Agent": f"Watchd/1.0 (https://github.com/wogsurfer/scrob) httpx/{httpx.__version__}",
    "Accept": "application/sparql-results+json",
}
# The query service throttles parallel requests per client.
_semaphore = asyncio.Semaphore(2)
_TTL = 24 * 3600
_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}

# Award family from a Wikidata award label, with the name shown for it.
_FAMILIES = (
    (re.compile(r"^Academy Award"), "Academy Awards"),
    (re.compile(r"^Golden Globe"), "Golden Globe Awards"),
    (re.compile(r"BAFTA|^British Academy"), "BAFTA Awards"),
    (re.compile(r"^Primetime Emmy"), "Primetime Emmy Awards"),
    (re.compile(r"^Daytime Emmy"), "Daytime Emmy Awards"),
    (re.compile(r"^International Emmy"), "International Emmy Awards"),
    (re.compile(r"Emmy"), "Emmy Awards"),
)


def award_family(label: str) -> str | None:
    for pattern, name in _FAMILIES:
        if pattern.search(label or ""):
            return name
    return None


def _category(label: str) -> str:
    """'Academy Award for Best Actress' -> 'Best Actress'."""
    _, sep, rest = (label or "").partition(" for ")
    return rest if sep else label


async def _query(sparql: str) -> list[dict]:
    async with _semaphore, httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
        r = await client.get(_ENDPOINT, params={"query": sparql})
        r.raise_for_status()
        return r.json()["results"]["bindings"]


def _value(row: dict, key: str) -> str | None:
    return (row.get(key) or {}).get("value")


def _qid_tmdb(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _rows(bindings: list[dict]) -> list[dict]:
    seen, out = set(), []
    for row in bindings:
        label = _value(row, "awardLabel") or ""
        family = award_family(label)
        if not family:
            continue
        year = (_value(row, "time") or "")[:4] or None
        item = {
            "award_name": family,
            "award_label": label,
            "category_name": _category(label),
            "year": year,
            "is_winner": _value(row, "kind") == "won",
            "person_tmdb_id": _qid_tmdb(_value(row, "personTmdb")),
            "person_name": _value(row, "personLabel"),
            "work_name": _value(row, "workLabel"),
            "work_movie_tmdb_id": _qid_tmdb(_value(row, "workMovie")),
            "work_tv_tmdb_id": _qid_tmdb(_value(row, "workTv")),
        }
        key = (label, year, item["is_winner"], item["person_tmdb_id"], item["work_name"])
        if key not in seen:
            seen.add(key)
            out.append(item)
    # A win is usually also listed as a nomination; keep just the win.
    wins = {(r["award_label"], r["year"], r["person_tmdb_id"], r["work_name"]) for r in out if r["is_winner"]}
    return [r for r in out if r["is_winner"] or (r["award_label"], r["year"], r["person_tmdb_id"], r["work_name"]) not in wins]


async def _cached(kind: str, tmdb_id: int, *queries: str) -> list[dict]:
    hit = _cache.get((kind, tmdb_id)) or disk_cache.load("wikidata", f"{kind}_{tmdb_id}", 7 * _TTL)
    if hit and time.time() - hit[0] < _TTL:
        _cache[(kind, tmdb_id)] = hit
        return hit[1]
    try:
        rows = _rows([b for q in queries for b in await _query(q)])
    except Exception as e:
        print(f"Wikidata award lookup failed for {kind} {tmdb_id}: {e!r}")
        return hit[1] if hit else []  # a stale answer beats none
    _cache[(kind, tmdb_id)] = (time.time(), rows)
    disk_cache.save("wikidata", f"{kind}_{tmdb_id}", rows)
    return rows


async def film_award_people(movie_tmdb_id: int) -> list[dict]:
    """Awards for a film, by TMDB movie id: people's nominations "for" the film,
    and the film's own (person_name None unless a nominee is recorded on it)."""
    return await _title_award_people("film", "P4947", movie_tmdb_id)


async def tv_award_people(tv_tmdb_id: int) -> list[dict]:
    """Awards for a TV show, by TMDB TV id; as film_award_people."""
    return await _title_award_people("tv", "P4983", tv_tmdb_id)


async def _title_award_people(kind: str, prop: str, tmdb_id: int) -> list[dict]:
    # Two simple queries, each starting from the film with the optimizer off:
    # left to reorder (or given a UNION) the service starts from every award
    # statement in Wikidata and times out.
    for_film = f"""
    SELECT ?kind ?awardLabel ?time ?personLabel ?personTmdb WHERE {{
      hint:Query hint:optimizer "None" .
      ?film wdt:{prop} "{tmdb_id}" .
      ?st pq:P1686 ?film .
      ?person ?pp ?st .
      VALUES (?pp ?ps ?kind) {{ (p:P166 ps:P166 "won") (p:P1411 ps:P1411 "nom") }}
      ?st ?ps ?award .
      OPTIONAL {{ ?person wdt:P4985 ?personTmdb }}
      OPTIONAL {{ ?st pq:P585 ?time }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    film_own = f"""
    SELECT ?kind ?awardLabel ?time ?personLabel ?personTmdb WHERE {{
      hint:Query hint:optimizer "None" .
      ?film wdt:{prop} "{tmdb_id}" .
      VALUES (?pp ?ps ?pq ?kind) {{ (p:P166 ps:P166 pq:P1346 "won") (p:P1411 ps:P1411 pq:P2453 "nom") }}
      ?film ?pp ?st .
      ?st ?ps ?award .
      OPTIONAL {{ ?st ?pq ?person . OPTIONAL {{ ?person wdt:P4985 ?personTmdb }} }}
      OPTIONAL {{ ?st pq:P585 ?time }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    return await _cached(kind, tmdb_id, for_film, film_own)


async def person_awards(person_tmdb_id: int) -> list[dict]:
    """A person's award wins and nominations, by TMDB person id."""
    sparql = f"""
    SELECT ?kind ?awardLabel ?time ?workLabel ?workMovie ?workTv WHERE {{
      ?person wdt:P4985 "{person_tmdb_id}" .
      {{ ?person p:P166 ?st . ?st ps:P166 ?award . BIND("won" AS ?kind) }}
      UNION {{ ?person p:P1411 ?st . ?st ps:P1411 ?award . BIND("nom" AS ?kind) }}
      OPTIONAL {{ ?st pq:P585 ?time }}
      OPTIONAL {{
        ?st pq:P1686 ?work .
        OPTIONAL {{ ?work wdt:P4947 ?workMovie }}
        OPTIONAL {{ ?work wdt:P4983 ?workTv }}
      }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}"""
    rows = await _cached("person", person_tmdb_id, sparql)
    for row in rows:
        row["person_tmdb_id"] = person_tmdb_id
    return rows
