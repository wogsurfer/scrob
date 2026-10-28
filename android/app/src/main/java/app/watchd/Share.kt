package app.watchd

import app.watchd.data.Api

/** Where a shared link or title should go. */
sealed interface ShareTarget {
    data class Film(val tmdbId: Int) : ShareTarget
    data class Show(val tmdbId: Int) : ShareTarget
    data class Search(val query: String) : ShareTarget
}

private val TMDB = Regex("""themoviedb\.org/(movie|tv)/(\d+)""")
private val IMDB = Regex("""\b(tt\d{6,10})\b""")
private val URL = Regex("""https?://\S+""")

/**
 * A TMDB link opens its film or show; an IMDb link (or id) is looked up;
 * anything else (a Letterboxd share, "Kill Bill: Vol. 1 (2003)") is searched,
 * without its links and year.
 */
suspend fun shareTarget(text: String, api: Api): ShareTarget {
    TMDB.find(text)?.let { m ->
        val id = m.groupValues[2].toInt()
        return if (m.groupValues[1] == "tv") ShareTarget.Show(id) else ShareTarget.Film(id)
    }
    IMDB.find(text)?.let { m ->
        val found = runCatching { api.findImdb(m.groupValues[1]) }.getOrNull()?.firstOrNull()
        if (found != null) return if (found.type == "movie") ShareTarget.Film(found.tmdbId) else ShareTarget.Show(found.tmdbId)
    }
    val words = text.replace(URL, " ")
        .replace(Regex("""\((19|20)\d{2}\)"""), " ")
        .replace(Regex("""(?i)\b(on letterboxd|on imdb|watch|check out)\b"""), " ")
        .replace(Regex("""\s+"""), " ")
        .trim(' ', '-', '–', '|', ':', '"', '“', '”')
    return ShareTarget.Search(words.take(80))
}
