from pathlib import Path
import sys

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from models.users import User
from core.security import get_password_hash


NEW_PASSWORD = "REMOVED"


import asyncio


async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.username == "your-username")
        )

        user = result.scalar_one()

        user.password_hash = get_password_hash(NEW_PASSWORD)

        await session.commit()

        print("Password updated successfully.")


asyncio.run(main())