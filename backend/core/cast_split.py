"""A show's cast and guest stars, season by season.

TMDB's show credits list only the latest season's regulars, and its
aggregate credits mix regulars with every guest, so neither says who was a
regular. Each season's own credits do, and its episodes list their guests:
anyone a regular in any season is cast, and anyone who guested in an
episode is a guest star for those episodes. Someone who did both (a guest
who later joins the cast, a regular who comes back as a guest) is in both,
each with only that part: their seasons as a regular, their guest spots.

The split is kept on the show (tmdb_data["cast_split"]) and worked out again
weekly while a show runs, monthly once it has ended.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta

from core import tmdb

ENDED = {"ended", "canceled", "cancelled"}
FRESH_RUNNING = timedelta(days=7)
FRESH_ENDED = timedelta(days=30)
# Enough guest stars for the row of cards; the rest are one-off parts.
MAX_GUESTS = 60
MAX_CAST = 24


def is_fresh(show_data: dict | None, status: str | None) -> bool:
    split = (show_data or {}).get("cast_split") or {}
    try:
        at = datetime.fromisoformat(split["at"])
    except (KeyError, TypeError, ValueError):
        return False
    keep = FRESH_ENDED if (status or "").strip().lower() in ENDED else FRESH_RUNNING
    return datetime.now(UTC) - at < keep


async def build(tmdb_id: int, show_data: dict, api_key: str | None) -> dict | None:
    """The cast and guest stars of a show from its TMDB data (with
    aggregate_credits), or None when the seasons can't be read."""
    seasons = [s["season_number"] for s in show_data.get("seasons") or [] if s.get("season_number")]
    if not seasons:
        return None
    try:
        details = await asyncio.gather(
            *(tmdb.get_season(tmdb_id, n, api_key=api_key, append_to_response="credits") for n in seasons)
        )
    except Exception:
        return None

    # Counted here rather than taken from TMDB's totals, which can be out (one
    # for an episode the person isn't in): a regular has each aired episode of
    # their seasons, a guest each aired episode they guest in. A guest credit
    # in a season they're a regular in is already one of their regular episodes.
    today = date.today().isoformat()
    aired: dict[int, int] = {}
    regular_seasons: dict[int, set[int]] = {}
    guest_spots: dict[int, list[dict]] = {}
    for number, season in zip(seasons, details):
        episodes = [e for e in season.get("episodes") or [] if e.get("air_date") and e["air_date"] <= today]
        aired[number] = len(episodes)
        for person in (season.get("credits") or {}).get("cast") or []:
            if person.get("id"):
                regular_seasons.setdefault(person["id"], set()).add(number)
        for episode in episodes:
            for person in episode.get("guest_stars") or []:
                if person.get("id"):
                    guest_spots.setdefault(person["id"], []).append({**person, "season": number})
    for person_id, spots in list(guest_spots.items()):
        kept = [s for s in spots if s["season"] not in regular_seasons.get(person_id, ())]
        if kept:
            guest_spots[person_id] = kept
        else:
            del guest_spots[person_id]

    aggregate = {p["id"]: p for p in (show_data.get("aggregate_credits") or {}).get("cast") or [] if p.get("id")}

    def characters(names) -> str:
        return " / ".join(dict.fromkeys(n for n in names if n))

    cast = []
    for person_id, numbers in regular_seasons.items():
        agg = aggregate.get(person_id) or {}
        roles = agg.get("roles") or []
        spots = guest_spots.get(person_id, [])
        name = agg.get("name") or next((s.get("name") for s in spots), None)
        if not name:
            continue
        cast.append({
            "tmdb_id": person_id,
            "name": name,
            "character": characters(r.get("character") for r in roles) or characters(s.get("character") for s in spots),
            "profile_path": tmdb.poster_url(agg.get("profile_path") or next((s.get("profile_path") for s in spots), None)),
            "episode_count": sum(aired[n] for n in numbers) or None,
            "seasons": sorted(numbers),
            # Their guest spots besides, if any (also listed with the guest stars).
            "guest_episodes": len(spots),
        })

    guests = []
    for person_id, spots in guest_spots.items():
        guests.append({
            "tmdb_id": person_id,
            "name": spots[0].get("name"),
            "character": characters(s.get("character") for s in spots),
            "profile_path": tmdb.poster_url(next((s.get("profile_path") for s in spots if s.get("profile_path")), None)),
            "episode_count": len(spots),
            "also_regular": person_id in regular_seasons,
        })

    # Most episodes first; among regulars, those from the first seasons first on a tie.
    cast.sort(key=lambda p: (-(p["episode_count"] or 0), p["seasons"][0]))
    guests.sort(key=lambda p: -p["episode_count"])
    return {
        "at": datetime.now(UTC).isoformat(),
        "cast": cast[:MAX_CAST],
        "guest_stars": guests[:MAX_GUESTS],
    }
