from pathlib import Path
import asyncio
import sys

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from models.media import Media
from models.show import Show
from models.base import MediaType
from core import tmdb

async def sync_movie(session, movie):

    data = await tmdb.get_movie(movie.tmdb_id)

    movie.original_title = data.get("original_title")
    movie.overview = data.get("overview")
    movie.poster_path = tmdb.poster_url(data.get("poster_path"))
    movie.backdrop_path = tmdb.poster_url(data.get("backdrop_path"), size="w1280")
    movie.release_date = data.get("release_date")
    movie.runtime = data.get("runtime")
    movie.tmdb_rating = data.get("vote_average")
    movie.tagline = data.get("tagline")
    movie.status = data.get("status")
    movie.adult = data.get("adult", False)
    movie.tmdb_data = data

    print(f"✓ {movie.title}")

async def sync_show(session, show):

    data = await tmdb.get_show(show.tmdb_id)

    show.original_title = data.get("original_name")
    show.overview = data.get("overview")
    show.poster_path = tmdb.poster_url(data.get("poster_path"))
    show.backdrop_path = tmdb.poster_url(data.get("backdrop_path"), size="w1280")
    show.first_air_date = data.get("first_air_date")
    show.last_air_date = data.get("last_air_date")
    show.tmdb_rating = data.get("vote_average")
    show.tagline = data.get("tagline")
    show.status = data.get("status")
    show.tmdb_data = data

    print(f"✓ {show.title}")

async def main():

    async with AsyncSessionLocal() as session:

        print("Syncing movies...")

        result = await session.execute(
            select(Media).where(
                Media.media_type == MediaType.movie,
                Media.poster_path.is_(None),
            )
        )

        movies = result.scalars().all()

        print(f"{len(movies)} movies to update")

        for i, movie in enumerate(movies, start=1):

            try:
                await sync_movie(session, movie)
            except Exception as e:
                print(f"Movie failed ({movie.tmdb_id}): {e}")

            if i % 25 == 0:
                await session.commit()
                print(f"Committed {i} movies")

        await session.commit()

        print("\nSyncing shows...")

        result = await session.execute(
            select(Show).where(
                Show.poster_path.is_(None),
            )
        )

        shows = result.scalars().all()

        print(f"{len(shows)} shows to update")

        for i, show in enumerate(shows, start=1):

            try:
                await sync_show(session, show)
            except Exception as e:
                print(f"Show failed ({show.tmdb_id}): {e}")

            if i % 25 == 0:
                await session.commit()
                print(f"Committed {i} shows")

        await session.commit()

    print("\nTMDB sync complete.")


if __name__ == "__main__":
    asyncio.run(main())