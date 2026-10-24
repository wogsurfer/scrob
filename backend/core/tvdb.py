"""TVDB v4 API client.

Token-based auth: POST /login returns a 30-day Bearer token.
We cache the token in memory (module-level) and refresh it when it expires.
"""
import asyncio
import json
import time
import httpx

TVDB_BASE = "https://api4.thetvdb.com/v4"

# In-memory token cache keyed by api_key
_token_cache: dict[str, tuple[str, float]] = {}  # api_key -> (token, expires_at)
_token_lock = asyncio.Lock()

# In-memory awards cache keyed by tvdb_id
_awards_cache: dict[tuple[int, str], tuple[float, list[dict]]] = {}
_AWARDS_CACHE_TTL = 86400  # 24 hours

TVDB_IMAGE_BASE = "https://artworks.thetvdb.com"

# BCP 47 (metadata_language) → ISO 639-3 used by TVDB
_TVDB_LANG: dict[str, str] = {
    "en":    "eng",
    "fr":    "fra",
    "de":    "deu",
    "es":    "spa",
    "es-MX": "spa",
    "it":    "ita",
    "pt-BR": "por",
    "pt-PT": "por",
    "ja":    "jpn",
    "ko":    "kor",
    "zh-CN": "zho",
    "zh-TW": "zho",
    "hi":    "hin",
    "ar":    "ara",
    "ru":    "rus",
    "nl":    "nld",
    "pl":    "pol",
    "tr":    "tur",
    "sv":    "swe",
    "cs":    "ces",
    "hu":    "hun",
    "hr":    "hrv",
    "sr":    "srp",
}


def tvdb_language(metadata_language: str | None) -> str | None:
    """Convert a BCP 47 metadata_language code to the ISO 639-3 code TVDB expects."""
    if not metadata_language:
        return None
    return _TVDB_LANG.get(metadata_language)


def _image_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http"):
        return path
    return f"{TVDB_IMAGE_BASE}{path}"


async def _get_token(api_key: str) -> str:
    """Return a valid TVDB Bearer token, refreshing if necessary."""
    async with _token_lock:
        cached = _token_cache.get(api_key)
        if cached:
            token, expires_at = cached
            # Refresh 1 hour before expiry
            if time.time() < expires_at - 3600:
                return token

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.post(
                f"{TVDB_BASE}/login",
                json={"apikey": api_key},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()

        token = data["data"]["token"]
        # TVDB tokens last 30 days; cache for 29 days
        expires_at = time.time() + 29 * 86400
        _token_cache[api_key] = (token, expires_at)
        return token


async def _get(path: str, api_key: str, params: dict | None = None) -> dict:
    token = await _get_token(api_key)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        r = await client.get(
            f"{TVDB_BASE}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params or {},
        )
        r.raise_for_status()
        return r.json()


async def validate_api_key(api_key: str) -> bool:
    if not api_key:
        return False
    try:
        await _get_token(api_key)
        return True
    except Exception:
        return False


async def search_series(query: str, api_key: str) -> list[dict]:
    """Search for TV series by title. Returns list of simplified series dicts."""
    data = await _get("/search", api_key, params={"query": query, "type": "series"})
    results = []
    for item in data.get("data") or []:
        tvdb_id_str = item.get("tvdb_id") or item.get("id") or ""
        try:
            tvdb_id = int(str(tvdb_id_str).lstrip("series-"))
        except (ValueError, TypeError):
            continue
        results.append({
            "tvdb_id": tvdb_id,
            "title": item.get("name") or item.get("translations", {}).get("eng", ""),
            "overview": item.get("overview") or item.get("overviews", {}).get("eng"),
            "year": item.get("year"),
            "image_url": _image_url(item.get("image_url") or item.get("thumbnail")),
            "status": item.get("status"),
            "network": item.get("network"),
        })
    return results


async def search_movies(query: str, api_key: str) -> list[dict]:
    """Search for movies by title. Returns list of simplified movie dicts."""
    data = await _get("/search", api_key, params={"query": query, "type": "movie"})
    results = []
    for item in data.get("data") or []:
        tvdb_id_str = item.get("tvdb_id") or item.get("id") or ""
        try:
            tvdb_id = int(str(tvdb_id_str).removeprefix("movie-"))
        except (ValueError, TypeError):
            continue
        results.append({
            "tvdb_id": tvdb_id,
            "title": item.get("name") or item.get("translations", {}).get("eng", ""),
            "overview": item.get("overview") or item.get("overviews", {}).get("eng"),
            "year": item.get("year"),
            "image_url": _image_url(item.get("image_url") or item.get("thumbnail")),
        })
    return results


async def get_movie(tvdb_id: int, api_key: str) -> dict:
    """Fetch movie extended info (artwork, runtime, release dates, translations)."""
    data = await _get(f"/movies/{tvdb_id}/extended", api_key, params={"meta": "translations"})
    return data.get("data") or {}


async def get_series(tvdb_id: int, api_key: str) -> dict:
    """Fetch series extended info including episodes for accurate per-season counts."""
    data = await _get(f"/series/{tvdb_id}/extended", api_key, params={"meta": "translations,episodes"})
    return data.get("data") or {}

# Every TVDB series award category with its nominees. The lists are the same
# for every show, so they are fetched once (about 3 minutes cold) and shared;
# each show's awards are then a quick filter. Rebuilt daily in the background
# while the previous index keeps serving.
_award_index: tuple[float, list[tuple[dict, dict, list[dict]]]] | None = None
_award_index_task: "asyncio.Task | None" = None
# Saved to disk so a restart doesn't mean another 3-minute crawl.
_AWARD_INDEX_FILE = "tvdb_award_index.json"


def _load_award_index() -> None:
    global _award_index
    from core.config import settings
    try:
        with open(settings.data_dir / _AWARD_INDEX_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        _award_index = (saved["built_at"], [tuple(entry) for entry in saved["index"]])
    except (OSError, ValueError, KeyError):
        pass


def _save_award_index() -> None:
    from core.config import settings
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = settings.data_dir / (_AWARD_INDEX_FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"built_at": _award_index[0], "index": _award_index[1]}, f)
        tmp.replace(settings.data_dir / _AWARD_INDEX_FILE)
    except OSError as e:
        print(f"Could not save TVDB award index: {e}")


async def _build_award_index(api_key: str) -> list[tuple[dict, dict, list[dict]]]:
    semaphore = asyncio.Semaphore(10)
    award_data = await _get("/awards", api_key)

    async def fetch_award(award):
        if not award.get("id"):
            return None
        async with semaphore:
            try:
                return award, await _get(f"/awards/{award['id']}/extended", api_key)
            except Exception:
                return None

    categories = []
    for result in await asyncio.gather(*(fetch_award(a) for a in award_data.get("data") or [])):
        if not result:
            continue
        award, extended = result
        for category in extended.get("data", {}).get("categories") or []:
            # Only categories that apply to TV series
            if category.get("id") and category.get("forSeries", False):
                categories.append((award, category))

    async def fetch_category(award, category):
        async with semaphore:
            try:
                data = await _get(f"/awards/categories/{category['id']}/extended", api_key)
            except Exception:
                return None
        return award, category, data.get("data", {}).get("nominees") or []

    results = await asyncio.gather(*(fetch_category(a, c) for a, c in categories))
    return [r for r in results if r]


async def _get_award_index(api_key: str) -> list[tuple[dict, dict, list[dict]]]:
    global _award_index, _award_index_task

    async def build():
        global _award_index
        _award_index = (time.time(), await _build_award_index(api_key))
        _awards_cache.clear()
        _save_award_index()

    if _award_index is None:
        _load_award_index()

    fresh = _award_index and time.time() - _award_index[0] < _AWARDS_CACHE_TTL
    if not fresh and (_award_index_task is None or _award_index_task.done()):
        _award_index_task = asyncio.create_task(build())
    if _award_index:
        return _award_index[1]  # serve the old index while a rebuild runs
    # shield: a client giving up must not cancel the build for everyone else
    await asyncio.shield(_award_index_task)
    return _award_index[1] if _award_index else []


async def get_series_awards(tvdb_id: int, api_key: str) -> list[dict]:
    """Fetch TVDB award nominations/wins for a series."""
    cached = _awards_cache.get(tvdb_id)
    if cached and time.time() - cached[0] < _AWARDS_CACHE_TTL:
        return cached[1]

    awards = []
    for award, category, nominees in await _get_award_index(api_key):
        for nominee in nominees:
            series = nominee.get("series") or {}
            if str(series.get("id")) != str(tvdb_id):
                continue
            awards.append({
                "award_id": award.get("id"),
                "award_name": award.get("name"),
                "category_id": category.get("id"),
                "category_name": category.get("name"),
                "year": nominee.get("year"),
                "is_winner": nominee.get("isWinner", False),
                "details": nominee.get("details"),
                "person_name": nominee.get("name"),
                "character": nominee.get("character"),
                "episode": nominee.get("episode"),
                "movie": nominee.get("movie"),
                "series": nominee.get("series"),
            })

    _awards_cache[tvdb_id] = (time.time(), awards)
    return awards

async def get_season(season_id: int, api_key: str) -> dict:
    """Fetch extended season metadata, including translated names and overviews."""
    data = await _get(
        f"/seasons/{season_id}/extended",
        api_key,
        params={"meta": "translations"},
    )
    return data.get("data") or {}


def format_season(raw: dict, language: str | None = None) -> dict:
    """Normalise extended TVDB season metadata."""
    translations = raw.get("translations") or {}

    def _pick(key: str, field: str) -> str | None:
        entries = translations.get(key) or []
        fallback = None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if language and entry.get("language") == language:
                return entry.get(field) or None
            if entry.get("language") == "eng":
                fallback = entry.get(field) or None
        return fallback

    return {
        "season_number": raw.get("number"),
        "name": _pick("nameTranslations", "name") or raw.get("name"),
        "overview": _pick("overviewTranslations", "overview") or raw.get("overview"),
        "poster_path": _image_url(raw.get("image")),
        "air_date": raw.get("premiereDate"),
        "id": raw.get("id"),
    }


async def get_series_episodes(tvdb_id: int, season_number: int, api_key: str, language: str | None = None) -> list[dict]:
    """Fetch episodes for a specific season (season_type=official)."""
    episodes = []
    page = 0
    while True:
        params: dict = {"page": page, "season": season_number}
        if language:
            params["language"] = language
        data = await _get(
            f"/series/{tvdb_id}/episodes/official",
            api_key,
            params=params,
        )
        batch = (data.get("data") or {}).get("episodes") or []
        if not batch:
            break
        episodes.extend(batch)
        # TVDB paginates at 500; if we got fewer, we're done
        if len(batch) < 500:
            break
        page += 1
    return episodes


def format_series(raw: dict, language: str | None = None) -> dict:
    """Normalise TVDB extended series data into a frontend-friendly dict."""
    image = raw.get("image") or ""
    poster = _image_url(image) if image else None

    translations = raw.get("translations") or {}

    def _pick(key: str, field: str) -> str | None:
        entries = translations.get(key) or []
        result = None
        for t in entries:
            if not isinstance(t, dict):
                continue
            if language and t.get("language") == language:
                return t.get(field) or None  # preferred language found
            if t.get("language") == "eng":
                result = t.get(field) or None  # English fallback
        return result

    translated_title = _pick("nameTranslations", "name")
    eng_overview = _pick("overviewTranslations", "overview")

    genres = [g.get("name") for g in (raw.get("genres") or []) if g.get("name")]

    # Count episodes per season and derive premiere dates from embedded episodes
    episode_counts: dict[int, int] = {}
    season_premiere_dates: dict[int, str] = {}
    for ep in raw.get("episodes") or []:
        sn = ep.get("seasonNumber")
        if sn is None:
            continue
        episode_counts[sn] = episode_counts.get(sn, 0) + 1
        if ep.get("number") == 1 and ep.get("aired") and sn not in season_premiere_dates:
            season_premiere_dates[sn] = ep["aired"]

    seasons = []
    for s in raw.get("seasons") or []:
        if s.get("type", {}).get("type") == "official":
            sn = s.get("number")
            count = episode_counts.get(sn) if sn in episode_counts else (s.get("episodeCount") or 0)
            seasons.append({
                "season_number": sn,
                "name": s.get("name") or f"Season {sn}",
                "overview": None,
                "poster_path": _image_url(s.get("image")),
                "episode_count": count,
                "air_date": s.get("premiereDate") or season_premiere_dates.get(sn),
                "id": s.get("id"),
            })
    seasons.sort(key=lambda x: x["season_number"] or 0)

    network = None
    for n in raw.get("networks") or []:
        if n.get("primaryLanguage") == "eng" or not network:
            network = n.get("name")

    age_rating = None
    for cr in raw.get("contentRatings") or []:
        if cr.get("country") == "usa" and cr.get("contentType") == "TV":
            age_rating = cr.get("name")
            break
    if not age_rating:
        for cr in raw.get("contentRatings") or []:
            age_rating = cr.get("name")
            break

    imdb_id = None
    tmdb_id_cross = None
    for rid in raw.get("remoteIds") or []:
        source = (rid.get("sourceName") or "").upper()
        if source == "IMDB" and not imdb_id:
            imdb_id = rid.get("id")
        elif "MOVIEDB" in source and not tmdb_id_cross:
            try:
                tmdb_id_cross = int(rid.get("id"))
            except (TypeError, ValueError):
                pass

    return {
        "tvdb_id": raw.get("id"),
        "title": translated_title or raw.get("name"),
        "original_title": raw.get("originalName") or raw.get("name"),
        "overview": eng_overview or raw.get("overview"),
        "poster_path": poster,
        "backdrop_path": _image_url(raw.get("artworks", [{}])[0].get("image") if raw.get("artworks") else None),
        "first_air_date": raw.get("firstAired"),
        "last_air_date": raw.get("lastAired"),
        "status": (raw.get("status") or {}).get("name"),
        "genres": genres,
        "network": network,
        "seasons": seasons,
        "original_language": raw.get("originalLanguage"),
        "age_rating": age_rating,
        "imdb_id": imdb_id,
        "tmdb_id_cross": tmdb_id_cross,
    }


def format_cast(raw: dict) -> list[dict]:
    """Extract actor list from TVDB extended series data."""
    characters = [c for c in (raw.get("characters") or []) if c.get("type") == 3]
    characters.sort(key=lambda x: x.get("sort") or 999)
    return [
        {
            "tmdb_id": None,
            "person_id": c.get("personId"),
            "name": c.get("personName") or "",
            "character": c.get("name") or "",
            "profile_path": _image_url(c.get("image")),
        }
        for c in characters[:12]
        if c.get("personName")
    ]


def format_episode(raw: dict) -> dict:
    return {
        "tvdb_id": raw.get("id"),
        "season_number": raw.get("seasonNumber"),
        "episode_number": raw.get("number"),
        "name": raw.get("name"),
        "overview": raw.get("overview"),
        "air_date": raw.get("aired"),
        "runtime": raw.get("runtime"),
        "image_url": _image_url(raw.get("image")),
    }
