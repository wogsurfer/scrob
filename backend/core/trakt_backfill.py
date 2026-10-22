from datetime import datetime

from sqlalchemy import select

from models.show import Show
from models.media import Media, MediaType
from models.users import UserSettings

from core import trakt


async def backfill_episode_airtimes(session):

    settings = (
        await session.execute(select(UserSettings))
    ).scalar_one()

    result = await session.execute(
        select(Show)
        .where(Show.trakt_id.is_not(None))
        .order_by(Show.title)
    )

    shows = result.scalars().all()

    updated = 0

    for show in shows:

        media_result = await session.execute(
            select(Media).where(
                Media.show_id == show.id,
                Media.media_type == MediaType.episode,
                Media.first_aired_at.is_(None),
            )
        )

        episode_lookup = {
            (m.season_number, m.episode_number): m
            for m in media_result.scalars().all()
        }

        if not episode_lookup:
            continue

        print(show.title)

        try:

            seasons = await trakt.get_show_seasons(
                settings.trakt_client_id,
                show.trakt_id,
            )

            for season in seasons:

                season_number = season["number"]

                for ep in season.get("episodes", []):

                    media = episode_lookup.get(
                        (season_number, ep["number"])
                    )

                    if media is None:
                        continue

                    episode_details = await trakt.get_episode(
                        settings.trakt_client_id,
                        show.trakt_id,
                        season_number,
                        ep["number"],
                    )

                    first_aired = episode_details.get("first_aired")

                    if not first_aired:
                        continue

                    media.first_aired_at = datetime.fromisoformat(
                        first_aired.replace("Z", "+00:00")
                    )

                    updated += 1

            if updated % 500 == 0:
                await session.commit()

        except Exception as e:
            print(f"❌ {show.title}: {e}")
            continue

    await session.commit()
    print(f"\nUpdated {updated} episodes")