from pathlib import Path
import json
import asyncio
import sys
from datetime import datetime

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from models.media import Media
from models.show import Show
from models.events import WatchEvent
from models.users import User
from models.base import MediaType


IMPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "imports"


# --------------------------------------------------
# Parse Trakt Watch
# --------------------------------------------------

def parse_watch(item: dict):

    if item["type"] == "movie":
        movie = item["movie"]

        return {
            "media_type": "movie",
            "tmdb_id": movie["ids"]["tmdb"],
            "title": movie["title"],
            "year": movie["year"],
            "watched_at": item["watched_at"],
        }

    if item["type"] == "episode":
        show = item["show"]
        episode = item["episode"]

        return {
            "media_type": "episode",
            "show_tmdb": show["ids"]["tmdb"],
            "show_title": show["title"],
            "episode_tmdb": episode["ids"]["tmdb"],
            "episode_title": episode["title"],
            "season": episode["season"],
            "episode": episode["number"],
            "watched_at": item["watched_at"],
        }

    return None


# --------------------------------------------------
# Movies
# --------------------------------------------------

async def get_or_create_movie(session, watch):

    result = await session.execute(
        select(Media).where(
            Media.media_type == MediaType.movie,
            Media.tmdb_id == watch["tmdb_id"],
        )
    )

    movie = result.scalar_one_or_none()

    if movie:
        return movie

    movie = Media(
        media_type=MediaType.movie,
        tmdb_id=watch["tmdb_id"],
        title=watch["title"],
    )

    session.add(movie)
    await session.flush()

    print(f"Created movie: {movie.title}")

    return movie


# --------------------------------------------------
# TV Shows
# --------------------------------------------------

async def get_or_create_show(session, watch):

    result = await session.execute(
        select(Show).where(
            Show.tmdb_id == watch["show_tmdb"]
        )
    )

    show = result.scalar_one_or_none()

    if show:
        return show

    show = Show(
        tmdb_id=watch["show_tmdb"],
        title=watch["show_title"],
    )

    session.add(show)
    await session.flush()

    print(f"Created show: {show.title}")

    return show


# --------------------------------------------------
# Episodes
# --------------------------------------------------

async def get_or_create_episode(session, show, watch):

    result = await session.execute(
        select(Media).where(
            Media.media_type == MediaType.episode,
            Media.tmdb_id == watch["episode_tmdb"],
        )
    )

    episode = result.scalars().first()

    if episode:
        return episode

    episode = Media(
        media_type=MediaType.episode,
        tmdb_id=watch["episode_tmdb"],
        title=watch["episode_title"],
        show_id=show.id,
        season_number=watch["season"],
        episode_number=watch["episode"],
    )

    session.add(episode)
    await session.flush()

    print(
        f"Created episode: "
        f"{show.title} "
        f"S{watch['season']:02d}E{watch['episode']:02d}"
    )

    return episode


# --------------------------------------------------
# Watch Events
# --------------------------------------------------

async def create_watch_event(session, user, media, watch):

    watched_at = datetime.fromisoformat(
        watch["watched_at"].replace("Z", "+00:00")
    ).replace(tzinfo=None)

    result = await session.execute(
        select(WatchEvent).where(
            WatchEvent.user_id == user.id,
            WatchEvent.media_id == media.id,
            WatchEvent.watched_at == watched_at,
        )
    )

    if result.scalar_one_or_none():
        return

    event = WatchEvent(
        user_id=user.id,
        media_id=media.id,
        watched_at=watched_at,
        completed=True,
        play_count=1,
    )

    session.add(event)

# --------------------------------------------------
# Import One History File
# --------------------------------------------------

async def import_file(session, user, file: Path):

    print(f"\nProcessing {file.name}")

    with open(file, "r", encoding="utf-8") as f:
        data = json.load(f)

    movies = 0
    episodes = 0

    for item in data:

        watch = parse_watch(item)

        if watch is None:
            continue

        if watch["media_type"] == "movie":

            media = await get_or_create_movie(session, watch)
            movies += 1

        elif watch["media_type"] == "episode":

            show = await get_or_create_show(session, watch)
            media = await get_or_create_episode(session, show, watch)
            episodes += 1

        else:
            continue

        await create_watch_event(session, user, media, watch)

    print(
        f"Finished {file.name} "
        f"({movies} movies, {episodes} episodes)"
    )

# --------------------------------------------------
# Main
# --------------------------------------------------

async def main():

    files = sorted(
        IMPORT_DIR.glob("watched-history-*.json"),
        key=lambda p: int(p.stem.split("-")[-1]),
    )

    print(f"Found {len(files)} history files")

    async with AsyncSessionLocal() as session:

        result = await session.execute(
            select(User).where(User.username == USERNAME)
        )

        user = result.scalar_one()

        for file in files:
            await import_file(session, user, file)

        await session.commit()

    print("\nImport complete.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/import_watch_history.py <username>")
    USERNAME = sys.argv[1]
    asyncio.run(main())