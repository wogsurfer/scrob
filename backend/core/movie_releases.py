"""Film release dates for the calendar: cinema, digital, streaming and disc,
picked from TMDB's per-country release dates."""

from datetime import date

# TMDB release types.
_LIMITED, _THEATRICAL, _DIGITAL, _PHYSICAL = 2, 3, 4, 5

# Notes on digital releases that mean rental or purchase, not a streaming
# service.
_DIGITAL_NOTES = ("rental", "digital", "vod", "purchase", "itunes")

COUNTRY_NAMES = {"GB": "UK"}


def release_countries(user_country: str | None) -> list[str]:
    """Countries to take dates from, best first: the user's own, then the UK
    and the US, which TMDB covers most fully."""
    countries = [c for c in (user_country, "GB", "US") if c]
    return list(dict.fromkeys(c.upper() for c in countries))


def _kind_and_label(release: dict) -> tuple[str | None, str | None]:
    kind = release.get("type")
    note = (release.get("note") or "").strip()
    low = note.lower()
    if kind in (_LIMITED, _THEATRICAL):
        return "cinema", "Back in cinemas" if "re-release" in low or "rerelease" in low else "In cinemas"
    if kind == _DIGITAL:
        if not note or any(word in low for word in _DIGITAL_NOTES):
            return "digital", "Digital"
        return "streaming", f"On {note}"
    if kind == _PHYSICAL:
        if "4k" in low:
            label = "4K Blu-ray"
        elif "blu" in low or not note:
            label = "Blu-ray"
        elif "dvd" in low:
            label = "DVD"
        else:
            label = "Blu-ray"
        if "criterion" in low:
            label = f"Criterion {label}"
        return "disc", label
    return None, None


def upcoming_releases(results: list, start: date, end: date, countries: list[str]) -> list[dict]:
    """Releases between start and end, one per kind (one per service for
    streaming). For each kind the first country in `countries` with a date in
    the window wins, and within a country the earliest date."""
    by_country = {e.get("iso_3166_1"): e.get("release_dates") or [] for e in results or []}
    picked: dict[tuple, dict] = {}
    for country in countries:
        best: dict[tuple, dict] = {}
        for release in by_country.get(country, []):
            kind, label = _kind_and_label(release)
            if not kind:
                continue
            try:
                day = date.fromisoformat((release.get("release_date") or "")[:10])
            except ValueError:
                continue
            if not start <= day <= end:
                continue
            key = (kind, label) if kind == "streaming" else (kind,)
            if key in picked:
                continue
            if key not in best or day < best[key]["date"]:
                best[key] = {"date": day, "kind": kind, "label": label, "country": country}
        picked.update(best)
    return sorted(picked.values(), key=lambda r: (r["date"], r["kind"]))
