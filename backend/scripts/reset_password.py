"""Set a user's password from the command line:

    python scripts/reset_password.py <username>

The new password is asked for, not passed, so it never lands in the shell's history.
"""

import asyncio
import getpass
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parent.parent))

from db import AsyncSessionLocal
from models.users import User
from core.security import get_password_hash


async def main(username: str, password: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.username == username)
        )

        user = result.scalar_one()

        user.password_hash = get_password_hash(password)

        await session.commit()

        print("Password updated successfully.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/reset_password.py <username>")
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Again: "):
        sys.exit("The passwords don't match.")
    asyncio.run(main(sys.argv[1], password))
