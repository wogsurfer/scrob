"""TVDB's genres for shows and films, kept on disk.

TVDB names genres singly ("Science Fiction", "Fantasy") where TMDB pairs
them ("Sci-Fi & Fantasy"). Stats read the cache only, so a page never waits on
TVDB; titles not looked up yet use their TMDB genres in TVDB's words, and
fill() fetches them in the background.

Everything is one file, held in memory: thousands of little files are slow to
open on the data folder Docker shares from Windows.
"""
import asyncio
import time

from core import disk_cache
from core import tvdb
from core.genres import HIDDEN_GENRES

_NS = "tvdb_genres"
_KEY = "all"
_TTL = 30 * 86400

# TMDB's paired TV genres, and its other names, as TVDB words them.
_FROM_TMDB = {
    "Sci-Fi & Fantasy": ["Science Fiction", "Fantasy"],
    "Action & Adventure": ["Action", "Adventure"],
    "War & Politics": ["War", "Politics"],
    "Kids": ["Children"],
    "TV Movie": [],
}

# key -> [looked up at, genres]
_entries: dict[str, list] | None = None
_filling: set[str] = set()


def _all() -> dict[str, list]:
    global _entries
    if _entries is None:
        hit = disk_cache.load(_NS, _KEY, float("inf"))
        _entries = hit[1] if hit else {}
    return _entries


def _key(kind: str, ref) -> str:
    # Shows by TVDB id, films by IMDb id (TVDB finds a film from that).
    return f"series-{ref}" if kind == "series" else f"movie-{ref}"


def from_tmdb(names: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        for g in _FROM_TMDB.get(name, [name]):
            if g not in out:
                out.append(g)
    return out


def cached(kind: str, ref) -> list[str] | None:
    """The saved TVDB genres, or None if this title hasn't been looked up lately."""
    if not ref:
        return None
    hit = _all().get(_key(kind, ref))
    if not hit or time.time() - hit[0] > _TTL:
        return None
    return hit[1]


def _names(raw: dict) -> list[str]:
    return [g["name"] for g in raw.get("genres") or [] if g.get("name") and g["name"] not in HIDDEN_GENRES]


async def _fetch(kind: str, ref, api_key: str) -> list[str] | None:
    if kind == "series":
        data = await tvdb._get(f"/series/{ref}/extended", api_key, params={"short": "true"})
        return _names(data.get("data") or {})
    movie_id = await tvdb.find_movie_by_imdb(ref, api_key)
    if not movie_id:
        return None
    data = await tvdb._get(f"/movies/{movie_id}/extended", api_key, params={"short": "true"})
    return _names(data.get("data") or {})


def fill(titles: list[tuple[str, object]], api_key: str | None) -> None:
    """Looks up, in the background, the titles not in the cache yet."""
    if not api_key:
        return
    todo = [(k, r) for k, r in dict.fromkeys(titles) if r and _key(k, r) not in _filling and cached(k, r) is None]
    if not todo:
        return
    _filling.update(_key(k, r) for k, r in todo)

    async def run():
        gate = asyncio.Semaphore(6)
        done = 0

        async def one(kind, ref):
            nonlocal done
            async with gate:
                try:
                    # Not on TVDB: saved empty, so it isn't asked for again this month.
                    _all()[_key(kind, ref)] = [time.time(), await _fetch(kind, ref, api_key) or []]
                    done += 1
                    if done % 200 == 0:
                        disk_cache.save(_NS, _KEY, _all())
                except Exception as e:
                    print(f"TVDB genres for {kind} {ref} failed: {e!r}")
                finally:
                    _filling.discard(_key(kind, ref))

        await asyncio.gather(*(one(k, r) for k, r in todo))
        disk_cache.save(_NS, _KEY, _all())

    asyncio.get_running_loop().create_task(run())
