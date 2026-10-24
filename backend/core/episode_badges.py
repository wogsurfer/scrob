"""Premiere and finale labels for episodes, from TMDB's episode types."""

ENDED_STATUSES = {"ended", "canceled", "cancelled"}


def episode_badge(
    season_number: int | None,
    episode_number: int | None,
    episode_type: str | None,
    previous_type: str | None = None,
    show_status: str | None = None,
) -> str | None:
    """ "Series premiere", "Season premiere", "Mid-season premiere",
    "Mid-season finale", "Season finale" or "Series finale", or None.

    `episode_type` is TMDB's ("standard", "mid_season" or "finale"), which it
    sets once a finale is announced; `previous_type` is the previous
    episode's, so the episode after a mid-season finale is the mid-season
    premiere. A finale of a show that has ended is the series finale.
    Specials (season 0) get no label.
    """
    if not season_number or not episode_number:
        return None
    if episode_number == 1:
        return "Series premiere" if season_number == 1 else "Season premiere"
    if previous_type == "mid_season":
        return "Mid-season premiere"
    if episode_type == "mid_season":
        return "Mid-season finale"
    if episode_type == "finale":
        ended = (show_status or "").strip().lower() in ENDED_STATUSES
        return "Series finale" if ended else "Season finale"
    return None


def season_badges(season_data: dict, show_status: str | None = None) -> dict[int, str]:
    """Labels for the episodes of a TMDB season response, by episode number."""
    episodes = sorted(season_data.get("episodes") or [], key=lambda e: e.get("episode_number") or 0)
    types = {e.get("episode_number"): e.get("episode_type") for e in episodes}
    badges = {}
    for e in episodes:
        number = e.get("episode_number")
        badge = episode_badge(
            e.get("season_number", season_data.get("season_number")),
            number,
            e.get("episode_type"),
            types.get(number - 1) if number else None,
            show_status,
        )
        if badge:
            badges[number] = badge
    return badges
