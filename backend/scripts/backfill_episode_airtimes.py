from pathlib import Path
import asyncio
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from core.trakt_backfill import backfill_episode_airtimes


async def main():

    async with AsyncSessionLocal() as session:
        await backfill_episode_airtimes(session)


if __name__ == "__main__":
    asyncio.run(main())
