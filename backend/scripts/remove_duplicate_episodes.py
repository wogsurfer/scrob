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
                id,
                show_id,
                season_number,
                episode_number
            FROM media
            WHERE media_type = 'episode'
            ORDER BY
                show_id,
                season_number,
                episode_number,
                id;
        """))

        rows = result.fetchall()

        groups = {}

        for row in rows:
            key = (row.show_id, row.season_number, row.episode_number)
            groups.setdefault(key, []).append(row.id)

        delete_ids = []

        for ids in groups.values():
            if len(ids) > 1:
                delete_ids.extend(ids[1:])   # keep the oldest

        print(f"Deleting {len(delete_ids)} duplicate rows")

        if delete_ids:
            await session.execute(
                text("DELETE FROM media WHERE id = ANY(:ids)")
                .bindparams(ids=delete_ids)
            )

            await session.commit()

        print("Done")


if __name__ == "__main__":
    asyncio.run(main())