"""Import a Collectorz.com Movie Collector XML export into the physical
collection, with its cover images, then replace the user's collection entries
with the films they own on disc.

Run from the backend folder, where the export's image paths can be read:
    python scripts/import_clz.py CollectionData.xml [--user 1]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete  # noqa: E402

from core.clz_import import parse_clz  # noqa: E402
from core.physical import import_clz_records  # noqa: E402
from db import AsyncSessionLocal  # noqa: E402
from models.emby_library_stats import EmbyLibraryStats  # noqa: E402
from routers.media import get_user_tmdb_key  # noqa: E402


def read_image(path: str | None) -> bytes | None:
    if not path:
        return None
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


async def main(xml_path: str, user_id: int) -> None:
    items, box_sets = parse_clz(xml_path)
    print(f"Read {len(items)} releases and {len(box_sets)} box sets")
    async with AsyncSessionLocal() as db:
        api_key = await get_user_tmdb_key(db, user_id)
        counts = await import_clz_records(db, user_id, items, box_sets, read_image, api_key)
        # The collection is the physical discs now: drop the media servers'
        # library counts the dashboard used to show.
        await db.execute(delete(EmbyLibraryStats))
        await db.commit()
    print(counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("xml")
    parser.add_argument("--user", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main(args.xml, args.user))
