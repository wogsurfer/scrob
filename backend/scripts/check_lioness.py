from pathlib import Path
import asyncio
import sys

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from models.show import Show
from models.media import Media


async def main():

    async with AsyncSessionLocal() as session:

        result = await session.execute(
            select(Media)
            .join(Show)
            .where(
                Show.title == "Lioness",
                Media.season_number == 3,
                Media.episode_number == 1,
            )
        )

        episodes = result.scalars().all()

        print(f"Found {len(episodes)} matching episodes\n")

        for ep in episodes:
            print("---------------------")
            print(f"ID: {ep.id}")
            print(f"TMDB: {ep.tmdb_id}")
            print(f"Title: {ep.title}")
            print(f"Release: {ep.release_date}")
            print(f"Show ID: {ep.show_id}")

        if ep is None:
            print("Episode not found")
            return

        print(f"Show: Lioness")
        print(f"Episode: S03E01")
        print(f"Title: {ep.title}")
        print(f"TMDB ID: {ep.tmdb_id}")
        print(f"Release: {ep.release_date}")
        print(f"Poster: {ep.poster_path}")


if __name__ == "__main__":
    asyncio.run(main())