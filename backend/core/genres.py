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