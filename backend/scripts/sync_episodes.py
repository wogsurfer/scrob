from pathlib import Path
import asyncio
import sys
import os
import httpx

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from sqlalchemy import select

from models.users import UserSettings
from core import trakt
from db import AsyncSessionLocal
from models.show import Show
from models.media import Media
from models.base import MediaType
from core import tmdb
from core.enrichment import enrich_media
from routers.media import get_user_tmdb_key


async def sync_show(session, api_key, trakt_client_id, show):

    data = await tmdb.get_show(show.tmdb_id, api_key)

    season_count = data.get("number_of_seasons", 0)

    print(f"{show.title} ({season_count} seasons)")

    for season in range(1, season_count + 1):

        season_data = await tmdb.get_season(
            show.tmdb_id,
            season,
            api_key,
        )

        episodes = season_data.get("episodes", [])

        print(f"    Season {season}: {len(episodes)} episodes")

        for ep in episodes:

            existing = await session.scalar(
                select(Media).where(
                    Media.show_id == show.id,
                    Media.season_number == season,
                    Media.episode_number == ep["episode_number"],
                )
            )

            if existing:

                if existing:
                    if existing.runtime:
                        continue

                try:
                    trakt_data = await trakt.get_episode(
                        trakt_client_id,
                        show.trakt_id,
                        season,
                        ep["episode_number"],
                    )
                except httpx.ReadTimeout:
                    print(
                        f"Timeout: {show.title} "
                        f"S{season}E{ep['episode_number']}"
                    )
                    continue

                existing.runtime = trakt_data.get("runtime")
                existing.tmdb_id = ep["id"]
                existing.title = ep.get("name")
                existing.overview = ep.get("overview")
                existing.release_date = ep.get("air_date")
                existing.poster_path = tmdb.poster_url(
                    ep.get("still_path"),
                    size="w500",
                )
                existing.tmdb_rating = ep.get("vote_average")

                continue

            session.add(
                Media(
                    show_id=show.id,
                    tmdb_id=ep["id"],
                    media_type=MediaType.episode,
                    title=ep.get("name"),
                    season_number=season,
                    episode_number=ep["episode_number"],
                    overview=ep.get("overview"),
                    release_date=ep.get("air_date"),
                    poster_path=tmdb.poster_url(
                        ep.get("still_path"),
                        size="w500",
                    ),
                    tmdb_rating=ep.get("vote_average"),
                )
            )


async def main():

    async with AsyncSessionLocal() as session:

        api_key = await get_user_tmdb_key(session, 1)

        settings = (
            await session.execute(select(UserSettings))
        ).scalar_one()

        result = await session.execute(
            select(Show)
            .order_by(Show.title)
        )

        shows = result.scalars().all()

        print(f"{len(shows)} shows")

        for i, show in enumerate(shows, start=1):

            await sync_show(
                session,
                api_key,
                settings.trakt_client_id,
                show,
            )

            if i % 10 == 0:
                await session.commit()
                print(f"Committed {i}/{len(shows)} shows")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())