"""Which holiday theme the site and app wear today (Malta time).

Each theme swaps Watchd's red for the holiday's colours and names a few
decorations and a greeting; the site and app draw them. Most run for a few
days around the day; one-day ones (Star Wars Day, Mother's Day...) just on
it. Where two overlap the shorter, more particular one wins (New Year's
two days inside Christmas).
"""

from datetime import date, timedelta
from zoneinfo import ZoneInfo
from datetime import datetime

MALTA = ZoneInfo("Europe/Malta")

# Oscars night moves each year; add a year's date once the Academy sets it.
# The show starts at 7pm in New York, midnight in Malta, so it runs into the next day.
OSCARS = {
    2027: date(2027, 3, 14),
    2028: date(2028, 3, 5),
}

# accent: the red scale it replaces (300 to 700); second: its other colour.
THEMES = {
    "new_year": {
        "name": "New Year", "greeting": "Happy New Year!", "decoration": "confetti",
        "accent": ["#fde68a", "#fcd34d", "#f5b82e", "#d99a16", "#a87410"], "second": "#e5e7eb",
    },
    "valentines": {
        "name": "Valentine's Day", "greeting": "Happy Valentine's Day", "decoration": "hearts",
        "accent": ["#fbcfe8", "#f9a8d4", "#f472b6", "#e64a9b", "#be2a7b"], "second": "#ef4444",
    },
    "st_patricks": {
        "name": "St Patrick's Day", "greeting": "Happy St Patrick's Day", "decoration": "shamrocks",
        "accent": ["#86efac", "#4ade80", "#22c55e", "#16a34a", "#15803d"], "second": "#f59e0b",
    },
    "oscars": {
        "name": "Oscars night", "greeting": "And the Oscar goes to…", "decoration": "sparkles",
        "accent": ["#fde68a", "#f5d06f", "#e3b448", "#c8962c", "#9c7219"], "second": "#fafafa",
    },
    "easter": {
        "name": "Easter", "greeting": "Happy Easter", "decoration": "eggs",
        "accent": ["#e9d5ff", "#d8b4fe", "#c084fc", "#a855f7", "#9333ea"], "second": "#fde047",
    },
    "star_wars": {
        "name": "Star Wars Day", "greeting": "May the 4th be with you", "decoration": "stars",
        "accent": ["#fff7a8", "#fff066", "#ffe81f", "#e6cf00", "#b8a500"], "second": "#60a5fa",
    },
    "mothers_day": {
        "name": "Mother's Day", "greeting": "Happy Mother's Day", "decoration": "petals",
        "accent": ["#fecdd3", "#fda4af", "#fb7185", "#f43f5e", "#e11d48"], "second": "#f9a8d4",
    },
    "fathers_day": {
        "name": "Father's Day", "greeting": "Happy Father's Day", "decoration": "none",
        "accent": ["#bfdbfe", "#93c5fd", "#60a5fa", "#3b82f6", "#2563eb"], "second": "#94a3b8",
    },
    "back_to_the_future": {
        "name": "Back to the Future Day", "greeting": "Great Scott! It's 21 October", "decoration": "flames",
        "accent": ["#fed7aa", "#fdba74", "#fb923c", "#f97316", "#ea580c"], "second": "#38bdf8",
    },
    "halloween": {
        "name": "Halloween", "greeting": "Happy Halloween", "decoration": "bats",
        "accent": ["#fdba74", "#fb923c", "#f97316", "#ea580c", "#c2410c"], "second": "#a855f7",
    },
    "thanksgiving": {
        "name": "Thanksgiving", "greeting": "Happy Thanksgiving", "decoration": "leaves",
        "accent": ["#fcd9a8", "#f5b971", "#e8963e", "#cc7a24", "#a35d17"], "second": "#b45309",
    },
    "christmas": {
        "name": "Christmas", "greeting": "Merry Christmas", "decoration": "snow",
        "accent": ["#fca5a5", "#f87171", "#ef4444", "#dc2626", "#b91c1c"], "second": "#22c55e",
    },
}


def easter_sunday(year: int) -> date:
    """Western Easter Sunday (the anonymous Gregorian computus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth (1-based) given weekday (Monday 0) of a month."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _spans(year: int) -> list[tuple[str, date, date]]:
    """(theme, first day, last day) for a year, most particular first."""
    easter = easter_sunday(year)
    spans = [
        ("new_year", date(year, 1, 1), date(year, 1, 1)),
        ("new_year", date(year, 12, 31), date(year, 12, 31)),
        ("star_wars", date(year, 5, 4), date(year, 5, 4)),
        ("back_to_the_future", date(year, 10, 21), date(year, 10, 21)),
        ("mothers_day", nth_weekday(year, 5, 6, 2), nth_weekday(year, 5, 6, 2)),
        ("fathers_day", nth_weekday(year, 6, 6, 3), nth_weekday(year, 6, 6, 3)),
        ("thanksgiving", nth_weekday(year, 11, 3, 4), nth_weekday(year, 11, 3, 4)),
        ("valentines", date(year, 2, 12), date(year, 2, 14)),
        ("st_patricks", date(year, 3, 15), date(year, 3, 17)),
        ("easter", easter - timedelta(days=2), easter + timedelta(days=1)),
        ("halloween", date(year, 10, 25), date(year, 10, 31)),
        ("christmas", date(year, 12, 18), date(year, 12, 31)),
        ("christmas", date(year, 1, 1), date(year, 1, 6)),
    ]
    if year in OSCARS:
        spans.insert(0, ("oscars", OSCARS[year], OSCARS[year] + timedelta(days=1)))
    return spans


def theme_for(day: date) -> dict | None:
    """The theme for a day, or None on an ordinary one."""
    for key, first, last in _spans(day.year):
        if first <= day <= last:
            return {"key": key, **THEMES[key]}
    return None


def today() -> date:
    return datetime.now(MALTA).date()
