GENRE_MAP = {
    # Combined
    "Action": "Action",
    "Action & Adventure": "Action",

    "Adventure": "Adventure",

    "Science Fiction": "Sci-Fi",
    "Sci-Fi & Fantasy": "Sci-Fi",

    "War": "War",
    "War & Politics": "War",

    "Family": None,
    "Kids": None,

    # Direct mappings
    "Animation": "Animation",
    "Comedy": "Comedy",
    "Crime": "Crime",
    "Documentary": "Documentary",
    "Drama": "Drama",
    "Fantasy": "Fantasy",
    "History": "History",
    "Horror": "Horror",
    "Music": "Music",
    "Mystery": "Mystery",
    "Romance": "Romance",
    "Thriller": "Thriller",
    "Western": "Western",
}


def normalise_genre(name: str) -> str:
    return GENRE_MAP.get(name, name)

# Not counted as genres: TMDB's "Family" (films and series) and "Kids"
# (series). They're left out wherever genres come in (TMDB, TVDB, Collectorz).
HIDDEN_GENRES = {"Family", "Kids"}
HIDDEN_GENRE_IDS = {10751, 10762}


def strip_hidden_genres(data):
    """Remove the hidden genres from a TMDB-style response in place, at any
    depth: `genres` lists (of names or {id, name}) and `genre_ids` lists.
    Returns `data`."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "genres" and isinstance(value, list):
                data[key] = [g for g in value if (g.get("name") if isinstance(g, dict) else g) not in HIDDEN_GENRES]
            elif key == "genre_ids" and isinstance(value, list):
                data[key] = [g for g in value if g not in HIDDEN_GENRE_IDS]
            elif isinstance(value, (dict, list)):
                strip_hidden_genres(value)
    elif isinstance(data, list):
        for item in data:
            strip_hidden_genres(item)
    return data
