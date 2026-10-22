from pathlib import Path
import asyncio
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from db import AsyncSessionLocal
from models.users import UserSettings
from models.show import Show
from core import trakt


async def main():

    async with AsyncSessionLocal() as session:

        settings_result = await session.execute(
            select(UserSettings)
        )

        settings = settings_result.scalar_one_or_none()

        if not settings or not settings.trakt_client_id:
            print("No Trakt client ID configured.")
            return

        result = await session.execute(
            select(Show)
            .order_by(Show.title)
        )

        shows = result.scalars().all()

        print(f"{len(shows)} shows found")

        updated = 0
        skipped = 0

        for show in shows:

            if show.trakt_id:
                skipped += 1
                continue

            if not show.tmdb_id:
                print(f"Skipping {show.title} (no TMDB id)")
                continue

            try:
                trakt_show = await trakt.get_show_by_tmdb(
                    settings.trakt_client_id,
                    show.tmdb_id,
                )

                if not trakt_show:
                    print(f"Not found: {show.title}")
                    continue

                show.trakt_id = trakt_show["ids"]["trakt"]

                updated += 1

                print(
                    f"{show.title} -> Trakt {show.trakt_id}"
                )

                if updated % 25 == 0:
                    await session.commit()
                    print(f"Committed {updated}")

            except Exception as e:
                print(f"{show.title}: {e}")

        await session.commit()

        print()
        print(f"Updated : {updated}")
        print(f"Skipped : {skipped}")

if __name__ == "__main__":
    asyncio.run(main())