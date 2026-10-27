package app.watchd.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset

// The backend's JSON is snake_case; Api's Json maps it onto these names.
// Only the fields the app shows are listed; the rest are ignored.

@Serializable
data class LoginResponse(
    val accessToken: String? = null,
    @SerialName("requires_2fa") val requires2fa: Boolean = false,
    val tempToken: String? = null,
)

@Serializable
data class User(val username: String, val displayName: String? = null)

@Serializable
data class NextUpResponse(val nextUp: List<NextUpItem> = emptyList())

@Serializable
data class NextUpItem(
    val tmdbId: Int,
    val title: String? = null,
    val seasonNumber: Int? = null,
    val episodeNumber: Int? = null,
    val posterPath: String? = null,
    val releaseDate: String? = null,
    val showTitle: String? = null,
    val showTmdbId: Int? = null,
    val showPosterPath: String? = null,
    val showBackdropPath: String? = null,
    val showImdbRating: Double? = null,
    val showWatchPct: Int = 0,
    val showEpisodesWatched: Int = 0,
    val showEpisodesTotal: Int = 0,
)

@Serializable
data class Upcoming(
    val today: String? = null,
    val episodes: List<UpcomingEpisode> = emptyList(),
    val movies: List<UpcomingMovie> = emptyList(),
)

@Serializable
data class UpcomingEpisode(
    val showTitle: String? = null,
    val title: String? = null,
    val season: Int? = null,
    val episode: Int? = null,
    val airDate: String? = null,
    val airTime: String? = null,
    val network: String? = null,
    val showPosterPath: String? = null,
    val showTmdbId: Int? = null,
    val badge: String? = null,
    val watched: Boolean = false,
)

@Serializable
data class UpcomingMovie(
    val tmdbId: Int,
    val title: String? = null,
    val posterPath: String? = null,
    val date: String? = null,
    val label: String? = null,
)

@Serializable
data class SearchResponse(val results: List<MediaItem> = emptyList())

@Serializable
data class MediaItem(
    val tmdbId: Int? = null,
    val type: String = "movie",
    val title: String? = null,
    val posterPath: String? = null,
    val releaseDate: String? = null,
    val imdbRating: Double? = null,
    val tmdbRating: Double? = null,
    val watched: Boolean = false,
    val inLibrary: Boolean = false,
    val inWatchlist: Boolean = false,
)

@Serializable
data class Person(
    val tmdbId: Int? = null,
    val name: String,
    val character: String? = null,
    val job: String? = null,
    val profilePath: String? = null,
    val episodeCount: Int? = null,
)

@Serializable
data class WhereToWatch(val type: String? = null, val name: String, val logo: String? = null)

@Serializable
data class CollectionPart(
    val tmdbId: Int,
    val title: String? = null,
    val posterPath: String? = null,
    val releaseDate: String? = null,
    val watched: Boolean = false,
)

@Serializable
data class FilmCollection(val name: String? = null, val parts: List<CollectionPart> = emptyList())

@Serializable
data class WatchEvent(val watchedAt: String? = null)

/** Where a play was watched; the backend accepts exactly these. */
val WATCH_SOURCES = listOf(
    "Cinema", "4K", "Blu-ray", "DVD", "TV", "Cable", "VHS",
    "Netflix", "Amazon", "Disney+", "AppleTV", "PLEX", "YouTube", "Digital file",
)

/** A film or episode to log or check in to. */
data class WatchTarget(
    val tmdbId: Int,
    val mediaType: String,
    val title: String?,
    val showTmdbId: Int? = null,
    val season: Int? = null,
    val episode: Int? = null,
    val runtime: Int? = null,
)

@Serializable
data class Play(val id: Int, val watchedAt: String? = null, val watchSource: String? = null)

@Serializable
data class SessionMedia(
    val tmdbId: Int? = null,
    val type: String = "movie",
    val title: String? = null,
    val posterPath: String? = null,
    val showTitle: String? = null,
    val showTmdbId: Int? = null,
    val seasonNumber: Int? = null,
    val episodeNumber: Int? = null,
)

/** A running check-in ("Watch now" session). */
@Serializable
data class WatchSession(
    val sessionKey: String,
    val state: String = "playing",
    val progressSeconds: Int = 0,
    val updatedAt: String,
    val watchSource: String? = null,
    val runtime: Int? = null,
    val media: SessionMedia,
) {
    /** Seconds watched so far: the saved progress, plus the time since if playing. */
    fun elapsedSeconds(now: Instant = Instant.now()): Long {
        if (state != "playing") return progressSeconds.toLong()
        val since = runCatching { LocalDateTime.parse(updatedAt.take(19)).toInstant(ZoneOffset.UTC) }.getOrNull() ?: return progressSeconds.toLong()
        return progressSeconds + Duration.between(since, now).seconds.coerceAtLeast(0)
    }
}

@Serializable
data class Movie(
    val tmdbId: Int,
    val title: String,
    val overview: String? = null,
    val tagline: String? = null,
    val posterPath: String? = null,
    val backdropPath: String? = null,
    val releaseDate: String? = null,
    val runtime: Int? = null,
    val ageRating: String? = null,
    val genres: List<String> = emptyList(),
    val imdbRating: Double? = null,
    val tmdbRating: Double? = null,
    val userRating: Double? = null,
    val watched: Boolean = false,
    val playCount: Int = 0,
    val inWatchlist: Boolean = false,
    val inLibrary: Boolean = false,
    val cast: List<Person> = emptyList(),
    val crew: List<Person> = emptyList(),
    val whereToWatch: List<WhereToWatch> = emptyList(),
    val collection: FilmCollection? = null,
    val watchHistory: List<WatchEvent> = emptyList(),
)

@Serializable
data class SeasonMeta(
    val seasonNumber: Int,
    val name: String? = null,
    val airDate: String? = null,
    val posterPath: String? = null,
    val episodeCount: Int = 0,
)

@Serializable
data class SeasonState(
    val watched: Boolean = false,
    val watchPct: Int = 0,
    val watchedCount: Int = 0,
    val episodeCount: Int = 0,
)

@Serializable
data class Network(val name: String)

@Serializable
data class Show(
    val tmdbId: Int,
    val title: String,
    val overview: String? = null,
    val tagline: String? = null,
    val posterPath: String? = null,
    val backdropPath: String? = null,
    val firstAirDate: String? = null,
    val lastAirDate: String? = null,
    val status: String? = null,
    val ageRating: String? = null,
    val genres: List<String> = emptyList(),
    val networks: List<Network> = emptyList(),
    val imdbRating: Double? = null,
    val tmdbRating: Double? = null,
    val userRating: Double? = null,
    val watched: Boolean = false,
    val watchPct: Int = 0,
    val seasonsMeta: List<SeasonMeta> = emptyList(),
    val seasonStates: Map<String, SeasonState> = emptyMap(),
    val cast: List<Person> = emptyList(),
    val createdBy: List<Person> = emptyList(),
    val whereToWatch: List<WhereToWatch> = emptyList(),
)

@Serializable
data class Episode(
    val tmdbId: Int,
    val title: String? = null,
    val overview: String? = null,
    val posterPath: String? = null,
    val airDate: String? = null,
    val episodeNumber: Int,
    val seasonNumber: Int,
    val runtime: Int? = null,
    val imdbRating: Double? = null,
    val tmdbRating: Double? = null,
    val badge: String? = null,
    val watched: Boolean = false,
)

@Serializable
data class Season(
    val seasonNumber: Int,
    val name: String? = null,
    val overview: String? = null,
    val posterPath: String? = null,
    val airDate: String? = null,
    val episodes: List<Episode> = emptyList(),
    val seasonWatchPct: Int = 0,
    val seasonWatched: Boolean = false,
)
