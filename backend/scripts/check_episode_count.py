import asyncio
from pathlib import Path
import sys

from sqlalchemy import select, func

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from models.media import Media
from models.base import MediaType


async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count()).where(
                Media.media_type == MediaType.episode
            )
        )

        print(result.scalar())


asyncio.run(main())