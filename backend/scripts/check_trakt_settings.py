from pathlib import Path
import asyncio
import sys

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from models.users import UserSettings


async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserSettings))
        rows = result.scalars().all()

        print(f"{len(rows)} UserSettings rows found")

        for row in rows:
            print(
                f"user_id={row.user_id}, "
                f"client_id={'YES' if row.trakt_client_id else 'NO'}, "
                f"access_token={'YES' if row.trakt_access_token else 'NO'}"
            )


if __name__ == "__main__":
    asyncio.run(main())