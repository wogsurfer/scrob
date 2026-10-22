from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))
import asyncio

from sqlalchemy import select

from db import AsyncSessionLocal
from models.users import User


async def main():
    async with AsyncSessionLocal() as session:
        users = await session.execute(select(User))

        print("Users:")
        for user in users.scalars():
            print(f"  ID={user.id}  Username={user.username}")

        from sqlalchemy import func
        from models.media import Media
        from models.events import WatchEvent
        from models.show import Show

        media_count = await session.scalar(
            select(func.count()).select_from(Media)
        )

        show_count = await session.scalar(
            select(func.count()).select_from(Show)
        )

        watch_count = await session.scalar(
            select(func.count()).select_from(WatchEvent)
        )

        print()
        print(f"Shows      : {show_count}")
        print(f"Media      : {media_count}")
        print(f"WatchEvents: {watch_count}")


if __name__ == "__main__":
    asyncio.run(main())