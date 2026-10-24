"""Who a film or show is based on, read from its English Wikipedia infobox.

TMDB often leaves the source author out of a title's credits, or files them
under another job (Bones credits Kathy Reichs only as a producer and writer),
and Wikidata rarely records it either. The infobox's "based_on" and
"inspired_by" fields do. Names are taken from {{Based on|work|author}} and
from linked names in free text, then kept only if they match someone in the
title's TMDB credits; {{Based on}} authors who aren't credited are looked up
with a TMDB person search instead. Results are cached in memory and on disk.
"""

import re
import time

import httpx

from core import disk_cache, tmdb

_TTL = 7 * 24 * 3600
_HEADERS = {"User-Agent": f"Watchd/1.0 (https://github.com/wogsurfer/scrob) httpx/{httpx.__version__}"}
_WIKIDATA = "https://query.wikidata.org/sparql"
_WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
_TMDB_PROP = {"movie": "P4947", "tv": "P4983"}
_FIELDS = ("based_on", "inspired_by")  # _field() also matches the spaced spelling
JOB = "Based On"

_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}


def _field(wikitext: str, name: str) -> str | None:
    """The raw value of an infobox field, up to the next top-level "|".

    Template nesting is tracked so "|" inside {{...}} or [[...]] doesn't end it.
    """
    m = re.search(r"^\s*\|\s*" + "[ _]".join(map(re.escape, name.split("_"))) + r"\s*=", wikitext, re.M | re.I)
    if not m:
        return None
    depth, i, text = 0, m.end(), wikitext
    while i < len(text):
        two = text[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            i += 2
            continue
        if two in ("}}", "]]"):
            if depth == 0:
                break  # end of the infobox itself
            depth -= 1
            i += 2
            continue
        if text[i] == "|" and depth == 0:
            break
        i += 1
    return text[m.end():i].strip()


def _plain(text: str) -> str:
    """Wiki markup to plain text: links to their labels, templates and refs dropped."""
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\{\{\s*(?:nowrap|nobr)\s*\|(.*?)\}\}", r"\1", text, flags=re.I | re.S)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"<br\s*/?>", ",", text, flags=re.I)
    return re.sub(r"'{2,}", "", text).strip()


def _split_people(text: str) -> list[str]:
    parts = re.split(r",|;|\band\b|&|\n|\*", _plain(text))
    return [p.strip(" .") for p in parts if p.strip(" .")]


def _top_level_params(template_body: str) -> list[str]:
    """Split a template's body on "|" that aren't inside nested markup."""
    params, depth, start = [], 0, 0
    i = 0
    while i < len(template_body):
        two = template_body[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            i += 2
            continue
        if two in ("}}", "]]"):
            depth -= 1
            i += 2
            continue
        if template_body[i] == "|" and depth == 0:
            params.append(template_body[start:i])
            start = i + 1
        i += 1
    params.append(template_body[start:])
    return params


def parse_source(value: str) -> tuple[list[str], list[str]]:
    """(authors named in {{Based on}}, other linked names) from a field value."""
    authors: list[str] = []
    rest = value
    for m in re.finditer(r"\{\{\s*based on\s*\|", value, re.I):
        depth, i = 1, m.end()
        while i < len(value) and depth:
            if value.startswith("{{", i):
                depth += 1
                i += 2
            elif value.startswith("}}", i):
                depth -= 1
                i += 2
            else:
                i += 1
        params = _top_level_params(value[m.end():i - 2])
        for p in params[1:]:
            if "=" in p.split("[[")[0]:
                continue  # named parameters, not authors
            authors += _split_people(p)
        rest = rest.replace(value[m.start():i], " ")
    linked = [re.split(r"\|", l)[-1].strip() for l in re.findall(r"\[\[([^\]]+)\]\]", rest)]
    return authors, [l for l in linked if l and ":" not in l]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


async def _wikipedia_source(kind: str, tmdb_id: int) -> tuple[list[str], list[str]]:
    sparql = f"""
        SELECT ?title WHERE {{
          ?item wdt:{_TMDB_PROP[kind]} "{tmdb_id}" .
          ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?title .
        }} LIMIT 1"""
    async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
        r = await client.get(_WIKIDATA, params={"query": sparql},
                             headers={"Accept": "application/sparql-results+json"})
        r.raise_for_status()
        rows = r.json()["results"]["bindings"]
        if not rows:
            return [], []
        r = await client.get(_WIKIPEDIA, params={
            "action": "query", "prop": "revisions", "rvprop": "content", "rvsection": "0",
            "rvslots": "main", "format": "json", "formatversion": "2", "redirects": "1",
            "titles": rows[0]["title"]["value"],
        })
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages") or []
        if not pages or "revisions" not in pages[0]:
            return [], []
        wikitext = pages[0]["revisions"][0]["slots"]["main"]["content"]
    authors, linked = [], []
    for name in _FIELDS:
        value = _field(wikitext, name)
        if value:
            a, l = parse_source(value)
            authors += a
            linked += l
    return authors, linked


async def source_people(kind: str, tmdb_id: int, credited: list[dict], api_key: str | None) -> list[dict]:
    """People the title is based on, as {tmdb_id, name, profile_path}.

    `credited` is the title's TMDB cast and crew ({tmdb_id, name, profile_path}),
    used to match names to people.
    """
    key = (kind, tmdb_id)
    hit = _cache.get(key) or disk_cache.load("source_work", f"{kind}_{tmdb_id}", 4 * _TTL)
    if hit and time.time() - hit[0] < _TTL:
        _cache[key] = hit
        return hit[1]
    try:
        authors, linked = await _wikipedia_source(kind, tmdb_id)
        by_name = {_norm(p["name"]): p for p in credited if p.get("name") and p.get("tmdb_id")}
        people: list[dict] = []
        for name in authors + linked:
            person = by_name.get(_norm(name))
            if not person and name in authors:
                found = (await tmdb.search_people(name, api_key=api_key)).get("results") or []
                match = next((f for f in found if _norm(f.get("name", "")) == _norm(name)), None)
                if match:
                    person = {
                        "tmdb_id": match["id"],
                        "name": match["name"],
                        "profile_path": tmdb.poster_url(match.get("profile_path"), size="w185"),
                    }
            if person and all(p["tmdb_id"] != person["tmdb_id"] for p in people):
                people.append({k: person.get(k) for k in ("tmdb_id", "name", "profile_path")})
    except Exception as e:
        print(f"Source work lookup failed for {kind} {tmdb_id}: {e!r}")
        return hit[1] if hit else []
    _cache[key] = (time.time(), people)
    disk_cache.save("source_work", f"{kind}_{tmdb_id}", people)
    return people


async def with_source_credits(crew: list[dict], kind: str, tmdb_id: int, api_key: str | None,
                              cast: list[dict] | None = None) -> list[dict]:
    """`crew` plus a "Based On" credit for each person the title is based on."""
    credited = list(crew) + list(cast or [])
    people = await source_people(kind, tmdb_id, credited, api_key)
    return crew + [{**p, "job": JOB, "department": "Writing", "episode_count": None} for p in people]
