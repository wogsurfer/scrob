from pathlib import Path
import asyncio
import sys

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal


async def main():
    async with AsyncSessionLocal() as session:

        result = await session.execute(text("""
            SELECT
                show_id,
                season_number,
                episode_number,
                COUNT(*) AS copies
            FROM media
            WHERE media_type = 'episode'
            GROUP BY
                show_id,
                season_number,
                episode_number
            HAVING COUNT(*) > 1
            ORDER BY copies DESC;
        """))

        rows = result.fetchall()

        print(f"Duplicate episode groups: {len(rows)}")

        for row in rows[:30]:
            print(row)


if __name__ == "__main__":
    asyncio.run(main())