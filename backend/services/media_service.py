from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import tmdb
from core.config import settings

from models.media import Media
from models.base import MediaType

async def get_or_create_movie(
    db: AsyncSession,
    tmdb_id: int,
) -> Media:

    media = (
        await db.execute(
            select(Media).where(
                Media.tmdb_id == tmdb_id,
                Media.media_type == MediaType.movie,
            )
        )
    ).scalar_one_or_none()

    if media:
        return media

    details = await tmdb.get_movie(
        tmdb_id,
        api_key=settings.tmdb_api_key,
    )

    media = Media(
        tmdb_id=details["id"],
        media_type=MediaType.movie,
        title=details["title"],
        original_title=details.get("original_title"),
        overview=details.get("overview"),
        poster_path=details.get("poster_path"),
        backdrop_path=details.get("backdrop_path"),
        release_date=details.get("release_date"),
        runtime=details.get("runtime"),
        tmdb_rating=details.get("vote_average"),
        tagline=details.get("tagline"),
        status=details.get("status"),
        adult=details.get("adult", False),
        tmdb_data=details,
    )

    db.add(media)
    await db.flush()

    return media