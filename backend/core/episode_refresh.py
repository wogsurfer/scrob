"""Keep the details of recent and upcoming episodes current.

An episode is saved with whatever TMDB knew when its season was first
fetched, which for a new season is often "Episode 1" with no synopsis or
still. Nothing else revisits it, so the placeholder stayed on Next Up and the
calendar long after the real title was out. This re-fetches the seasons of
episodes airing from two weeks ago to two weeks ahead (and any aired episode
still carrying a placeholder title) until it has been checked a few days
after airing. Titles that really are "Episode 1" are left alone after that.
"""

import re
from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select

from core import tmdb
from models.base import MediaType
from models.media import Media
from models.show import Show

PLACEHOLDER = re.compile(r"^(episode|chapter|ep\.?)\s*\d+$", re.I)
_WINDOW = timedelta(days=14)
_SETTLED = timedelta(days=3)  # stop once details were saved this long after airing


def needs_refresh(title: str | None, release_date: str | None, updated: date, today: date) -> bool:
    """Whether an episode's saved details may still change."""
    try:
        aired = date.fromisoformat(release_date) if release_date else None
    except ValueError:
        aired = None
    if aired is None or updated >= aired + _SETTLED:
        return False
    placeholder = aired <= today and PLACEHOLDER.match((title or "").strip())
    return bool(placeholder) or abs(aired - today) <= _WINDOW


async def refresh_recent_episodes(db, api_key: str, today: date | None = None) -> int:
    """Re-fetch from TMDB the seasons of every episode that needs_refresh;
    returns how many episodes were checked."""
    today = today or date.today()
    rows = (await db.execute(
        select(Media, Show.tmdb_id)
        .join(Show, Show.id == Media.show_id)
        .where(
            Media.media_type == MediaType.episode,
            Show.tmdb_id.is_not(None),
            Media.release_date.is_not(None),
            or_(
                and_(
                    Media.release_date >= (today - _WINDOW).isoformat(),
                    Media.release_date <= (today + _WINDOW).isoformat(),
                ),
                Media.title.op("~*")(PLACEHOLDER.pattern),
            ),
        )
    )).all()

    seasons: dict[tuple[int, int], list[Media]] = {}
    for media, show_tmdb_id in rows:
        if media.season_number is None or media.episode_number is None:
            continue
        if needs_refresh(media.title, media.release_date, media.updated_at.date(), today):
            seasons.setdefault((show_tmdb_id, media.season_number), []).append(media)

    refreshed = 0
    for (show_tmdb_id, season), episodes in seasons.items():
        try:
            data = await tmdb.get_season(show_tmdb_id, season, api_key=api_key)
        except Exception:
            continue
        by_number = {ep.get("episode_number"): ep for ep in data.get("episodes") or []}
        for media in episodes:
            ep = by_number.get(media.episode_number)
            if not ep:
                continue
            # Never trade a real title for a placeholder, or details for nothing.
            name = ep.get("name")
            if name and not (PLACEHOLDER.match(name) and not PLACEHOLDER.match(media.title or "")):
                media.title = name
            media.overview = ep.get("overview") or media.overview
            if ep.get("still_path"):
                media.poster_path = tmdb.poster_url(ep["still_path"], size="w500")
            media.release_date = ep.get("air_date") or media.release_date
            media.runtime = ep.get("runtime") or media.runtime
            media.tmdb_rating = ep.get("vote_average") or media.tmdb_rating
            media.updated_at = func.now()  # marks it checked, so it settles
            refreshed += 1
    return refreshed
