"""Fill in TMDB credits for movies saved without them.

The profile stats count directors, writers, actors and studios from each
movie's stored credits. Movies added through some imports or enriched before
crew was stored have none (only an IMDb rating, say), so they're missing from
those stats. This fetches each one from TMDB and adds credits, genres and
production companies to its stored data, keeping what's already there. Movies
missing their release date, poster or synopsis get those filled in too.

Run from backend/:  python scripts/backfill_movie_credits.py [--dry-run]
"""
from pathlib import Path
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

sys.path.append(str(Path(__file__).resolve().parent.parent))

from core import tmdb
from core.enrichment import movie_credits_fields
from db import AsyncSessionLocal
from models.base import MediaType
from models.media import Media
from models.global_settings import GlobalSettings
from models.users import UserSettings


async def _api_key(session) -> str | None:
    """The server-wide TMDB key, else the first user's."""
    global_key = (await session.execute(select(GlobalSettings.tmdb_api_key))).scalars().first()
    if global_key:
        return global_key
    return (await session.execute(
        select(UserSettings.tmdb_api_key).where(UserSettings.tmdb_api_key.isnot(None))
    )).scalars().first()


async def main(dry_run: bool) -> None:
    async with AsyncSessionLocal() as session:
        api_key = await _api_key(session)
        movies = (await session.execute(
            select(Media).where(Media.media_type == MediaType.movie, Media.tmdb_id.isnot(None))
        )).scalars().all()
        missing = [
            m for m in movies
            if not isinstance((m.tmdb_data or {}).get("credits"), dict) or not m.release_date or not m.poster_path
        ]
        print(f"{len(missing)} of {len(movies)} movies have no stored credits or basic details")
        if dry_run:
            return

        semaphore = asyncio.Semaphore(8)
        fetched: dict[int, dict] = {}

        async def fetch(tmdb_id: int) -> None:
            async with semaphore:
                try:
                    fetched[tmdb_id] = await tmdb.get_movie(tmdb_id, api_key=api_key)
                except Exception as e:
                    print(f"  skipped {tmdb_id}: {e!r}")

        await asyncio.gather(*(fetch(t) for t in {m.tmdb_id for m in missing}))

        for media in missing:
            data = fetched.get(media.tmdb_id)
            if not data:
                continue
            stored = dict(media.tmdb_data or {})
            stored.update(movie_credits_fields(data))
            stored.setdefault("genres", [g["name"] for g in data.get("genres", [])])
            stored.setdefault("runtime", data.get("runtime"))
            media.tmdb_data = stored
            flag_modified(media, "tmdb_data")
            media.release_date = media.release_date or data.get("release_date") or None
            media.poster_path = media.poster_path or tmdb.poster_url(data.get("poster_path"))
            media.backdrop_path = media.backdrop_path or tmdb.poster_url(data.get("backdrop_path"), size="w1280")
            media.overview = media.overview or data.get("overview")
        await session.commit()
        print(f"Added credits to {sum(1 for m in missing if m.tmdb_id in fetched)} movies")


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
