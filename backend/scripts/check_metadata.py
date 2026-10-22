from pathlib import Path
import sys
import asyncio

from sqlalchemy import select, func

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from models.media import Media
from models.show import Show
from models.base import MediaType


async def main():
    async with AsyncSessionLocal() as session:

        result = await session.execute(
            select(
                func.count(),
                func.count(Media.poster_path),
            ).where(
                Media.media_type == MediaType.movie
            )
        )

        total_movies, movies_with_posters = result.one()

        result = await session.execute(
            select(
                func.count(),
                func.count(Show.poster_path),
            )
        )

        total_shows, shows_with_posters = result.one()

        print(f"Movies : {movies_with_posters}/{total_movies} have posters")
        print(f"Shows  : {shows_with_posters}/{total_shows} have posters")


if __name__ == "__main__":
    asyncio.run(main())