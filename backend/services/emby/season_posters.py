"""Each show's poster in Emby becomes its latest season's poster.

For every series, the highest-numbered season (specials aside) that has a
poster gives its poster to the series. The series' own poster is saved first
(data/emby_posters/originals) so it can be put back, and what was applied is
noted (data/emby_posters/applied.json) so a later run only changes a show
when a newer season, or a new season poster, turns up.
"""

import base64
import json
import logging
from pathlib import Path

import httpx

from services.emby.client import EmbyClient

log = logging.getLogger("uvicorn.error")
DATA = Path(__file__).resolve().parents[2] / "data" / "emby_posters"
APPLIED = DATA / "applied.json"
ORIGINALS = DATA / "originals"


def _load() -> dict:
    try:
        return json.loads(APPLIED.read_text())
    except (OSError, ValueError):
        return {}


def _tag(tag: str) -> str:
    return "_".join(tag.split("_")[:2])


async def latest_season_posters(only: str | None = None, dry_run: bool = False) -> dict:
    """Give each series (or just the one titled [only]) its latest season's
    poster. Returns counts: changed, already, no_season_poster."""
    emby = EmbyClient()
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    applied = _load()
    counts = {"changed": 0, "already": 0, "no_season_poster": 0}
    series = (await emby.get("/Items", IncludeItemTypes="Series", Recursive="true", Fields="ImageTags"))["Items"]
    async with httpx.AsyncClient(timeout=60) as http:
        auth = {"api_key": emby.api_key}
        for show in series:
            if only and show.get("Name", "").casefold() != only.casefold():
                continue
            seasons = (await emby.get(f"/Shows/{show['Id']}/Seasons", Fields="ImageTags"))["Items"]
            with_poster = [
                s for s in seasons
                if (s.get("IndexNumber") or 0) > 0 and (s.get("ImageTags") or {}).get("Primary")
            ]
            if not with_poster:
                counts["no_season_poster"] += 1
                continue
            season = max(with_poster, key=lambda s: s["IndexNumber"])
            # Emby sometimes adds a suffix to the same image's tag; the first two parts name it.
            mark = f"{season['Id']}:{_tag(season['ImageTags']['Primary'])}"
            if _tag(applied.get(show["Id"], "")) == _tag(mark):
                counts["already"] += 1
                continue
            if dry_run:
                counts["changed"] += 1
                log.info(f"Emby posters: {show['Name']} would use season {season['IndexNumber']}")
                continue

            # Keep the show's own poster the first time, to put back if wanted.
            original = ORIGINALS / f"{show['Id']}.jpg"
            if not original.exists() and (show.get("ImageTags") or {}).get("Primary"):
                res = await http.get(f"{emby.server}/Items/{show['Id']}/Images/Primary", params=auth)
                if res.is_success:
                    original.write_bytes(res.content)

            res = await http.get(f"{emby.server}/Items/{season['Id']}/Images/Primary", params=auth)
            res.raise_for_status()
            # Emby takes the new image as base64 text in the body.
            up = await http.post(
                f"{emby.server}/Items/{show['Id']}/Images/Primary", params=auth,
                content=base64.b64encode(res.content), headers={"Content-Type": res.headers.get("content-type", "image/jpeg")},
            )
            up.raise_for_status()
            applied[show["Id"]] = mark
            counts["changed"] += 1
            log.info(f"Emby posters: {show['Name']} now shows season {season['IndexNumber']}")
    if not dry_run:
        APPLIED.write_text(json.dumps(applied, indent=1))
    return counts


async def restore_original(series_id: str) -> bool:
    """Put a show's own poster back (and stop it being changed again until a new season)."""
    emby = EmbyClient()
    original = ORIGINALS / f"{series_id}.jpg"
    if not original.exists():
        return False
    async with httpx.AsyncClient(timeout=60) as http:
        up = await http.post(
            f"{emby.server}/Items/{series_id}/Images/Primary", params={"api_key": emby.api_key},
            content=base64.b64encode(original.read_bytes()), headers={"Content-Type": "image/jpeg"},
        )
        up.raise_for_status()
    return True
