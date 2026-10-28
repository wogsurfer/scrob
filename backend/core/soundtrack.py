"""The songs used in a film or show, from its soundtrack album.

MusicBrainz is searched for soundtrack albums whose title starts with the
title's name and that came out around its release (during its run, for a
show). Each album's track list comes with performers and, through the
recorded works, songwriters. When MusicBrainz has nothing, the {{Track
listing}} in the title's Wikipedia article is used instead.

Soundtrack albums mix songs with score and dialogue clips, so tracks are
dropped when they're performed or written by the title's composer (score),
when they're another film's score (no words, played by a film composer, like
the Morricone and Bacalov pieces on Kill Bill), or when they're short and
performed by its cast or written by its writers (dialogue, like the K-Billy
links on Reservoir Dogs). Results are cached in memory and on disk.
"""

import asyncio
import re
import time

import httpx

from core import disk_cache, source_work, tmdb

_TTL = 30 * 24 * 3600
_EMPTY_TTL = 7 * 24 * 3600  # look again sooner when nothing was found
_MB = "https://musicbrainz.org/ws/2"
_HEADERS = source_work._HEADERS
_MAX_ALBUMS = 3
_COMPOSER_JOBS = {"Original Music Composer", "Composer", "Music"}
# Scoring this many titles on TMDB makes someone a film composer.
_FILM_COMPOSER_CREDITS = 15
_COMPOSER_TTL = 90 * 24 * 3600
_WRITING_JOBS = {"Director", "Writer", "Screenplay", "Story", "Creator", "Teleplay"}
# Album titles that aren't the songs used in the title.
_NOT_SONGS = re.compile(r"\b(score|game|trailer|inspired|karaoke|tribute|covers?)\b", re.I)
# What follows a show's name in the title of its soundtrack album.
_TV_HINT = re.compile(r"\b(television|tv|series|season|music from|songs from|soundtrack)\b", re.I)

_cache: dict[str, tuple[float, dict]] = {}
_inflight: dict[str, asyncio.Task] = {}
_mb_lock = asyncio.Lock()
_mb_last = 0.0


def _norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", text)


def _names(names, whole: bool = True) -> set[str]:
    """Normalised names, with duos credited as one ("Kyle Dixon & Michael
    Stein") split into each person; the whole credit is kept too unless
    `whole` is False."""
    out = set()
    for name in names or []:
        if name:
            if whole:
                out.add(_norm(name))
            out |= {_norm(p) for p in re.split(r"\s*(?:&|,|\band\b|\bfeat\.?|\bwith\b)\s*", name) if p.strip()}
    return out - {""}


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def album_matches(album_title: str, title: str, kind: str) -> bool:
    """Whether an album title reads as the soundtrack of `title`: it starts
    with the name, followed by nothing or a separator (":", "(", "-", ","),
    and isn't a score, game or "inspired by" album. A show's album has to say
    it's from the series, so a same-named film's album doesn't match."""
    clean = album_title.replace("’", "'").strip()
    name = title.replace("’", "'").strip()
    # "Quentin Tarantino's Inglourious Basterds: ...", "Disney's ..."
    clean = re.sub(r"^[^:(]{2,40}?'s\s+(?=" + re.escape(name) + ")", "", clean, flags=re.I)
    if not clean.lower().startswith(name.lower()):
        return False
    rest = clean[len(name):].strip()
    if rest and rest[0] not in ":(-–—,[":
        return False
    if _NOT_SONGS.search(rest):
        return False
    return kind != "tv" or bool(_TV_HINT.search(rest))


def is_song(track: dict, composers: set[str], cast: set[str], writing: set[str],
            film_composers: frozenset[str] = frozenset()) -> bool:
    """Whether a track is a song rather than score or a dialogue clip.

    `track` has "performers" and "writers" (names), "length" (seconds or
    None), and from MusicBrainz "words" (True, False for an instrumental, or
    missing when unknown) and "score_work"; the sets are the title's
    composers, cast and writers/directors, and film composers in general, as
    normalised names.
    """
    performers = _names(track.get("performers"))
    writers = {_norm(w) for w in track.get("writers") or [] if w}
    length = track.get("length")
    if not performers and not writers:
        # Nobody credited: a score listing (Wikipedia's for VisionQuest's
        # "Original Soundtrack" has no performer or writer column).
        return False
    if performers & composers or (writers and writers <= composers):
        return False  # score
    if track.get("score_work") or (not track.get("words") and (performers | writers) & film_composers):
        return False  # another film's score
    if length is not None and length < 30:
        return False  # a sting or a few seconds of dialogue
    people = _names(track.get("performers"), whole=False)
    by_cast = bool(people) and people <= cast
    by_writers = bool(writers) and writers <= writing
    if (by_cast and (not writers or by_writers)) or ((length is None or length < 90) and (by_cast or by_writers)):
        return False  # dialogue
    return True


def split_dialogue(track: dict, cast: set[str], writing: set[str]) -> dict:
    """A track that runs a dialogue clip into a song ("Royale With Cheese /
    Misirlou" by "Samuel L. Jackson and John Travolta / Dick Dale") cut down
    to just the song: the parts performed by the cast or the title's own
    writers are dropped, along with those writers. Others are unchanged."""
    titles = [t.strip() for t in (track.get("title") or "").split(" / ")]
    artists = [a.strip() for a in (track.get("artist") or "").split(" / ")]
    if len(titles) < 2 or len(titles) != len(artists):
        return track
    people = cast | writing
    keep = []
    for title, artist in zip(titles, artists):
        names = [p for p in track.get("performers") or [] if p and p in artist] or [artist]
        if not all(_norm(n) in people for n in names):
            keep.append((title, artist, names))
    if not keep or len(keep) == len(titles):
        return track
    return {
        **track,
        "title": " / ".join(k[0] for k in keep),
        "artist": " / ".join(k[1] for k in keep),
        "performers": [n for k in keep for n in k[2]],
        "writers": [w for w in track.get("writers") or [] if _norm(w) not in writing],
    }


async def _mb(client: httpx.AsyncClient, path: str, **params) -> dict:
    """A MusicBrainz request, at most one a second as they ask, retrying when
    they're busy (503)."""
    global _mb_last
    for attempt in range(4):
        async with _mb_lock:
            wait = _mb_last + 1.1 - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            r = await client.get(f"{_MB}/{path}", params={**params, "fmt": "json"})
            _mb_last = time.monotonic()
        if r.status_code != 503:
            r.raise_for_status()
            return r.json()
        await asyncio.sleep(2 * (attempt + 1))
    r.raise_for_status()
    return r.json()


def _mb_track(track: dict) -> dict:
    rec = track.get("recording") or {}
    writers: list[str] = []
    for rel in rec.get("relations") or []:
        if rel.get("type") != "performance" or not rel.get("work"):
            continue
        for wr in rel["work"].get("relations") or []:
            name = (wr.get("artist") or {}).get("name")
            if wr.get("type") in ("composer", "lyricist", "writer") and name and name not in writers:
                writers.append(name)
    credit = track.get("artist-credit") or rec.get("artist-credit") or []
    length = track.get("length") or rec.get("length")
    works = [rel["work"] for rel in rec.get("relations") or [] if rel.get("type") == "performance" and rel.get("work")]
    # A work's language says whether it has words: "zxx" is none.
    languages = {lang for w in works for lang in (w.get("languages") or [w.get("language")]) if lang}
    return {
        "title": track.get("title") or rec.get("title"),
        "artist": "".join(a.get("name", "") + a.get("joinphrase", "") for a in credit).strip(),
        "performers": [a.get("name") for a in credit],
        "writers": writers,
        "length": round(length / 1000) if length else None,
        "words": bool(languages - {"zxx"}) if languages else None,
        "score_work": any(w.get("type") == "Soundtrack" for w in works),
    }


async def _musicbrainz_albums(meta: dict) -> list[dict]:
    query = f'releasegroup:"{meta["title"].replace(chr(34), "")}" AND secondarytype:soundtrack'
    async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
        found = (await _mb(client, "release-group/", query=query, limit=25)).get("release-groups") or []
        picked = []
        for rg in found:
            year = _year(rg.get("first-release-date"))
            if rg.get("primary-type") not in ("Album", "EP") or year is None:
                continue
            if not (meta["first_year"] - 1 <= year <= meta["last_year"] + 1):
                continue
            if not album_matches(rg.get("title", ""), meta["title"], meta["kind"]):
                continue
            artists = _names(a.get("name") for a in rg.get("artist-credit") or [])
            if artists & meta["composers"]:
                continue  # the composer's album: score
            picked.append(rg)
        picked.sort(key=lambda rg: rg.get("first-release-date") or "")

        albums = []
        for rg in picked[:_MAX_ALBUMS]:
            # The original release: official, earliest, and the plainest
            # edition of that year (fewest tracks, so no bonus interviews).
            group = (await _mb(client, "release", **{"release-group": rg["id"]}, inc="media", limit=100)).get("releases") or []
            releases = sorted(
                group,
                key=lambda r: (r.get("status") != "Official", (r.get("date") or "9999")[:4],
                               sum(m.get("track-count") or 0 for m in r.get("media") or [])),
            )
            if not releases:
                continue
            release = await _mb(
                client, f"release/{releases[0]['id']}",
                inc="recordings+artist-credits+recording-level-rels+work-rels+work-level-rels+artist-rels",
            )
            tracks = [_mb_track(t) for medium in release.get("media") or [] for t in medium.get("tracks") or []]
            albums.append({"title": rg["title"], "year": _year(rg.get("first-release-date")), "tracks": tracks})
        return albums


def _template_bodies(wikitext: str, name: str) -> list[str]:
    """The inside of each {{name ...}} template, with nesting respected."""
    bodies = []
    for m in re.finditer(r"\{\{\s*" + name + r"\s*\|", wikitext, re.I):
        depth, i = 1, m.end()
        while i < len(wikitext) and depth:
            if wikitext.startswith("{{", i):
                depth += 1
                i += 2
            elif wikitext.startswith("}}", i):
                depth -= 1
                i += 2
            else:
                i += 1
        bodies.append(wikitext[m.end():i - 2])
    return bodies


def _seconds(length: str) -> int | None:
    m = re.match(r"\s*(\d+):(\d{2})", length or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def parse_track_listings(wikitext: str) -> list[dict]:
    """Albums from the {{Track listing}} templates in an article, skipping
    any whose heading says it's the score."""
    albums = []
    for body in _template_bodies(wikitext, r"track ?list(?:ing)?"):
        params: dict[str, str] = {}
        for p in source_work._top_level_params(body):
            key, eq, value = p.partition("=")
            if eq:
                params[key.strip().lower()] = value.strip()
        heading = source_work._plain(params.get("headline") or params.get("head") or "")
        if re.search(r"\bscore\b", heading, re.I):
            continue
        tracks = []
        for n in range(1, 100):
            title = source_work._plain(params.get(f"title{n}", "")).strip('"')
            if not title:
                if n > 1:
                    break
                continue
            artist = source_work._plain(params.get(f"extra{n}", ""))
            tracks.append({
                "title": title,
                "artist": artist,
                "performers": source_work._split_people(params.get(f"extra{n}", "")),
                "writers": source_work._split_people(params.get(f"writer{n}", "")),
                "length": _seconds(params.get(f"length{n}", "")),
            })
        if tracks:
            albums.append({"title": heading or None, "year": None, "tracks": tracks})
    return albums


async def _meta(kind: str, tmdb_id: int, api_key: str | None) -> dict:
    if kind == "movie":
        data = await tmdb.get_movie(tmdb_id, api_key=api_key)
        title = data.get("title") or ""
        first = last = _year(data.get("release_date"))
        crew = (data.get("credits") or {}).get("crew") or []
        cast = (data.get("credits") or {}).get("cast") or []
    else:
        data = await tmdb.get_show(tmdb_id, api_key=api_key)
        title = data.get("name") or ""
        first = _year(data.get("first_air_date"))
        last = time.gmtime().tm_year if data.get("in_production") else _year(data.get("last_air_date")) or first
        agg = data.get("aggregate_credits") or {}
        crew = ((data.get("credits") or {}).get("crew") or []) + [
            {**c, "job": j.get("job")} for c in agg.get("crew") or [] for j in c.get("jobs") or []
        ]
        crew += [{"name": c.get("name"), "job": "Creator"} for c in data.get("created_by") or []]
        cast = ((data.get("credits") or {}).get("cast") or []) + (agg.get("cast") or [])
    names = lambda people, jobs=None: {_norm(p["name"]) for p in people if p.get("name") and (jobs is None or p.get("job") in jobs)}
    return {
        "kind": kind,
        "title": title,
        "first_year": first or 0,
        "last_year": last or first or 0,
        "composers": names(crew, _COMPOSER_JOBS),
        "writing": names(crew, _WRITING_JOBS),
        "cast": names(cast),
    }


_composer_cache: dict[str, bool] = {}


async def _is_film_composer(name: str, api_key: str | None) -> bool:
    """Whether TMDB's match for the name is someone who scores films (known
    for sound, with many credits as a title's composer)."""
    key = _norm(name)
    if key in _composer_cache:
        return _composer_cache[key]
    hit = disk_cache.load("film_composer", key, _COMPOSER_TTL)
    if hit:
        _composer_cache[key] = hit[1]
        return hit[1]
    try:
        people = (await tmdb.search_people(name, api_key=api_key)).get("results") or []
        person = next((p for p in people if _norm(p.get("name") or "") == key), None)
        answer = False
        if person and person.get("known_for_department") == "Sound":
            crew = ((await tmdb.get_person(person["id"], api_key=api_key)).get("combined_credits") or {}).get("crew") or []
            answer = len({c.get("id") for c in crew if c.get("job") in _COMPOSER_JOBS}) >= _FILM_COMPOSER_CREDITS
    except Exception:
        return False  # ask again next time
    _composer_cache[key] = answer
    disk_cache.save("film_composer", key, answer)
    return answer


async def _film_composers(albums: list[dict], api_key: str | None) -> frozenset[str]:
    """Which performers and writers of tracks without known words are film
    composers."""
    names = {
        p for a in albums for t in a["tracks"] if not t.get("words")
        for p in [*(t.get("performers") or []), *(t.get("writers") or [])] if p
    }
    found = await asyncio.gather(*(_is_film_composer(n, api_key) for n in names))
    return frozenset(_norm(n) for n, yes in zip(names, found) if yes)


def _songs(albums: list[dict], meta: dict, film_composers: frozenset[str] = frozenset()) -> list[dict]:
    """Albums with only their songs, each song listed once across albums,
    and empty albums dropped."""
    seen: set[tuple[str, str]] = set()
    kept = []
    for album in albums:
        songs = []
        for t in album["tracks"]:
            t = split_dialogue(t, meta["cast"], meta["writing"])
            t["writers"] = [w for w in t["writers"] if not w.startswith("[")]  # "[anonymous]", "[traditional]"
            key = (_norm(t["title"] or ""), _norm(t["artist"] or ""))
            if not t["title"] or key in seen or not is_song(t, meta["composers"], meta["cast"], meta["writing"], film_composers):
                continue
            seen.add(key)
            songs.append({k: t[k] for k in ("title", "artist", "writers", "length")})
        if songs:
            kept.append({**album, "tracks": songs})
    return kept


async def _lookup(kind: str, tmdb_id: int, api_key: str | None) -> dict:
    meta = await _meta(kind, tmdb_id, api_key)
    found = await _musicbrainz_albums(meta) if meta["title"] and meta["first_year"] else []
    albums = _songs(found, meta, await _film_composers(found, api_key))
    source = "MusicBrainz"
    if not albums:
        wikitext = await source_work.wikipedia_article(kind, tmdb_id, lead_only=False)
        found = parse_track_listings(wikitext or "")
        albums = _songs(found, meta, await _film_composers(found, api_key))
        source = "Wikipedia"
    return {"albums": albums, "source": source if albums else None}


async def soundtrack(kind: str, tmdb_id: int, api_key: str | None) -> dict:
    """{"albums": [{"title", "year", "tracks": [{"title", "artist",
    "writers", "length"}]}], "source"} for a "movie" or "tv" title."""
    key = f"{kind}_{tmdb_id}"
    hit = _cache.get(key) or disk_cache.load("soundtrack_v3", key, _TTL)
    if hit:
        ttl = _TTL if hit[1].get("albums") else _EMPTY_TTL
        if time.time() - hit[0] < ttl:
            _cache[key] = hit
            return hit[1]
    task = _inflight.get(key)
    if task is None:
        task = _inflight[key] = asyncio.ensure_future(_lookup(kind, tmdb_id, api_key))
    try:
        result = await task
    except Exception as e:
        print(f"Soundtrack lookup failed for {key}: {e!r}")
        return hit[1] if hit else {"albums": [], "source": None}
    finally:
        _inflight.pop(key, None)
    _cache[key] = (time.time(), result)
    disk_cache.save("soundtrack_v3", key, result)
    return result
