from pathlib import Path
import sys
import asyncio

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT
                id,
                show_id,
                season_number,
                episode_number,
                tmdb_id,
                tvdb_id,
                imdb_id
            FROM media
            WHERE
                show_id = (
                    SELECT id
                    FROM shows
                    WHERE title = 'It''s Always Sunny in Philadelphia'
                )
            AND season_number = 15
            AND episode_number = 2;

        rows = result.fetchall()

        if not rows:
            print("No duplicate episodes found.")
            return

        for row in rows:
            print(row)


asyncio.run(main())