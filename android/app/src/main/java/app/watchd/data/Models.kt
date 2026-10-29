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
data class User(val id: Int = 0, val username: String, val displayName: String? = null)

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
    val seasonPosterPath: String? = null,
    val showImdbRating: Double? = null,
    /** The episode's own IMDb rating; none until IMDb has one. */
    val imdbRating: Double? = null,
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
    val seasonPosterPath: String? = null,
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
data class WatchEvent(val watchedAt: String? = null, val watchSource: String? = null, val edition: String? = null)

/** The media server's file of a film: its picture, sound and languages. */
@Serializable
data class LibraryFile(
    val resolution: String? = null,
    val videoCodec: String? = null,
    val audioCodec: String? = null,
    val audioChannels: String? = null,
    val audioLanguages: List<String> = emptyList(),
    val subtitleLanguages: List<String> = emptyList(),
)

@Serializable
data class Country(val name: String? = null)

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
    val discs: List<Disc> = emptyList(),
    val inLists: List<Int> = emptyList(),
    val collectionPct: Int = 0,
    val isMonitored: Boolean = false,
    val requestEnabled: Boolean = false,
    val requestStatus: String? = null,
    val library: LibraryFile? = null,
    val productionCountries: List<Country> = emptyList(),
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
    val tvdbId: Int? = null,
    val discs: List<Disc> = emptyList(),
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
    val guestStars: List<Person> = emptyList(),
    val crew: List<Person> = emptyList(),
    val createdBy: List<Person> = emptyList(),
    val whereToWatch: List<WhereToWatch> = emptyList(),
    val inLists: List<Int> = emptyList(),
    val collectionPct: Int = 0,
    val isMonitored: Boolean = false,
    val requestEnabled: Boolean = false,
    val requestStatus: String? = null,
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
    val imdbRating: Double? = null,
    val tmdbRating: Double? = null,
    val seasonUserRating: Double? = null,
    val seasonDiscId: Int? = null,
    val seasonCollectionPct: Int = 0,
    val show: SeasonShow? = null,
)

/** The show a season or episode belongs to, with its seasons for moving between them. */
@Serializable
data class SeasonShow(val tmdbId: Int? = null, val title: String? = null, val seasonsMeta: List<SeasonMeta> = emptyList())

// ------------------------------------------------------------------ round 2

@Serializable
data class HistoryMedia(
    val tmdbId: Int? = null,
    val type: String = "movie",
    val title: String? = null,
    val posterPath: String? = null,
    val releaseDate: String? = null,
    val seasonNumber: Int? = null,
    val episodeNumber: Int? = null,
    val showTitle: String? = null,
    val showPosterPath: String? = null,
    val seasonPosterPath: String? = null,
    val showTmdbId: Int? = null,
)

@Serializable
data class HistoryEvent(
    val id: Int,
    val watchedAt: String? = null,
    val watchSource: String? = null,
    val media: HistoryMedia,
)

@Serializable
data class HistoryPage(
    val page: Int = 1,
    val totalPages: Int = 1,
    val totalResults: Int = 0,
    val results: List<HistoryEvent> = emptyList(),
)

@Serializable
data class PosterRef(val url: String? = null)

@Serializable
data class UserList(
    val id: Int,
    val name: String,
    val description: String? = null,
    val itemCount: Int = 0,
    val movieCount: Int = 0,
    val showCount: Int = 0,
    val lastAdded: String? = null,
    val privacyLevel: String? = null,
    val previewPosters: List<PosterRef> = emptyList(),
)

@Serializable
data class ListsResponse(val lists: List<UserList> = emptyList())

@Serializable
data class ListMedia(
    val tmdbId: Int? = null,
    val type: String = "movie",
    val title: String? = null,
    val posterPath: String? = null,
    val releaseDate: String? = null,
    val imdbRating: Double? = null,
)

@Serializable
data class ListEntry(val id: Int, val media: ListMedia, val addedAt: String? = null, val sortOrder: Int = 0)

@Serializable
data class ListDetail(
    val id: Int,
    val name: String,
    val description: String? = null,
    val itemCount: Int = 0,
    val items: List<ListEntry> = emptyList(),
)

@Serializable
data class WatchlistMovie(
    val tmdbId: Int,
    val title: String? = null,
    val year: Int? = null,
    val posterPath: String? = null,
    val imdbRating: Double? = null,
    val runtime: Int? = null,
    val releaseDate: String? = null,
    val watched: Boolean = false,
)

@Serializable
data class TvTotals(val minutes: Long = 0, val episodes: Int = 0, val shows: Int = 0)

@Serializable
data class FilmTotals(val minutes: Long = 0, val plays: Int = 0, val movies: Int = 0)

@Serializable
data class LibraryTotals(val shows: Int = 0, val movies: Int = 0)

@Serializable
data class Totals(
    val tv: TvTotals = TvTotals(),
    val movies: FilmTotals = FilmTotals(),
    val library: LibraryTotals = LibraryTotals(),
)

@Serializable
data class NamedCount(val name: String, val count: Int = 0)

@Serializable
data class MonthActivity(val month: String, val movies: Int = 0, val episodes: Int = 0)

@Serializable
data class ProfileStats(
    val avgMovieRating: Double? = null,
    val avgShowRating: Double? = null,
    val topMovieGenres: List<NamedCount> = emptyList(),
    val topShowGenres: List<NamedCount> = emptyList(),
    val watchActivity: List<MonthActivity> = emptyList(),
)

// ------------------------------------------------------------------ round 3

@Serializable
data class Award(
    val awardName: String,
    val categoryName: String,
    val year: String? = null,
    val isWinner: Boolean = false,
    val details: String? = null,
    val personName: String? = null,
    val nameInferred: Boolean = false,
    val workTitle: String? = null,
    val workType: String? = null,
    val workTmdbId: Int? = null,
)

@Serializable
data class AwardsResponse(val awards: List<Award> = emptyList(), val pending: Boolean = false)

@Serializable
data class Track(val title: String, val artist: String? = null, val length: Int? = null)

@Serializable
data class Album(val title: String? = null, val year: Int? = null, val tracks: List<Track> = emptyList())

@Serializable
data class SoundtrackResponse(val albums: List<Album> = emptyList())

@Serializable
data class Disc(
    val id: Int,
    val title: String? = null,
    val releaseYear: Int? = null,
    val status: String? = null,
    val format: String? = null,
    val edition: String? = null,
    val inSet: String? = null,
)

@Serializable
data class PersonCredit(
    val tmdbId: Int,
    val type: String = "movie",
    val title: String? = null,
    val posterPath: String? = null,
    val releaseDate: String? = null,
    val character: String? = null,
    val job: String? = null,
    val watched: Boolean = false,
)

@Serializable
data class PersonDetail(
    val tmdbId: Int,
    val name: String,
    val biography: String? = null,
    val profilePath: String? = null,
    val birthday: String? = null,
    val deathday: String? = null,
    val placeOfBirth: String? = null,
    val knownForDepartment: String? = null,
    val credits: List<PersonCredit> = emptyList(),
    val totalCredits: Int = 0,
    val creditCounts: Map<String, Int> = emptyMap(),
    val watchedCreditCounts: Map<String, Int> = emptyMap(),
    val page: Int = 1,
    val pageSize: Int = 20,
)

@Serializable
data class PhysicalItem(
    val id: Int,
    val status: String? = null,
    val title: String? = null,
    val sortTitle: String? = null,
    val tmdbId: Int? = null,
    val tmdbKind: String? = null,
    val releaseYear: Int? = null,
    val format: String? = null,
    val edition: String? = null,
    val cover: String? = null,
    val seen: Boolean = false,
    val parentId: Int? = null,
    val isSet: Boolean = false,
    val unedited: Boolean = false,
    val dateAdded: String? = null,
)

@Serializable
data class PhysicalItems(val items: List<PhysicalItem> = emptyList())

@Serializable
data class PhysicalStats(
    val owned: Int = 0,
    val titles: Int = 0,
    val discs: Int = 0,
    val films: Int = 0,
    val tv: Int = 0,
    val seen: Int = 0,
    val unseen: Int = 0,
    val wishlist: Int = 0,
    val formats: List<NamedCount> = emptyList(),
)

// ------------------------------------------------------------------ a disc in the collection

@Serializable
data class DiscContent(
    val id: Int,
    val title: String? = null,
    val releaseYear: Int? = null,
    val format: String? = null,
    val seen: Boolean = false,
    val cover: String? = null,
)

@Serializable
data class DiscParent(
    val id: Int,
    val title: String? = null,
    val cover: String? = null,
    val format: String? = null,
    val edition: String? = null,
    val barcode: String? = null,
    val location: String? = null,
    val purchaseDate: String? = null,
    val purchasePrice: Double? = null,
    val store: String? = null,
    val condition: String? = null,
    val distributor: String? = null,
)

@Serializable
data class OtherEdition(val id: Int, val format: String? = null, val edition: String? = null, val status: String? = null)

@Serializable
data class DiscCast(val name: String, val character: String? = null)

@Serializable
data class DiscOnDisc(val title: String? = null, val format: String? = null, val features: List<String> = emptyList())

@Serializable
data class DiscSpecs(
    val cast: List<DiscCast> = emptyList(),
    val plot: String? = null,
    val tagline: String? = null,
    val discs: List<DiscOnDisc> = emptyList(),
    val features: List<String> = emptyList(),
    val extraFeatures: String? = null,
)

@Serializable
data class DiscDetail(
    val id: Int,
    val status: String? = null,
    val title: String,
    val titleExtension: String? = null,
    val tmdbId: Int? = null,
    val tmdbKind: String? = null,
    val releaseYear: Int? = null,
    val format: String? = null,
    val edition: String? = null,
    val distributor: String? = null,
    val barcode: String? = null,
    val `package`: String? = null,
    val discCount: Int? = null,
    val discReleaseDate: String? = null,
    val runtime: Int? = null,
    val purchaseDate: String? = null,
    val purchasePrice: Double? = null,
    val store: String? = null,
    val condition: String? = null,
    val location: String? = null,
    val myRating: Double? = null,
    val seen: Boolean = false,
    val plays: Int = 0,
    val genres: List<String> = emptyList(),
    val regions: List<String> = emptyList(),
    val audienceRating: String? = null,
    val imdbRating: Double? = null,
    val imdbVotes: Int? = null,
    val director: String? = null,
    val writer: String? = null,
    val composer: String? = null,
    val country: String? = null,
    val language: String? = null,
    val studios: List<String> = emptyList(),
    val ratios: List<String> = emptyList(),
    val audio: List<String> = emptyList(),
    val subtitles: List<String> = emptyList(),
    val hdr: String? = null,
    val extras: List<String> = emptyList(),
    val notes: String? = null,
    val isSet: Boolean = false,
    val tags: List<String> = emptyList(),
    val dateAdded: String? = null,
    val coverFull: String? = null,
    val cover: String? = null,
    val backdrop: String? = null,
    val lastWatched: String? = null,
    val contents: List<DiscContent> = emptyList(),
    val parent: DiscParent? = null,
    val otherEditions: List<OtherEdition> = emptyList(),
    val specs: DiscSpecs? = null,
)

// ------------------------------------------------------------------ round 4

@Serializable
data class FoundTitle(val tmdbId: Int, val type: String = "series", val title: String? = null)

@Serializable
data class Hero(val posters: List<String> = emptyList())

@Serializable
data class PipelineHealth(val status: String = "unknown", val problems: Int = 0)

@Serializable
data class Count(val count: Int = 0)

/** The newest published build of the app. */
@Serializable
data class AppBuild(val versionCode: Int, val versionName: String? = null, val size: Long = 0)

@Serializable
data class AppLink(val url: String)

/** A film Radarr has downloaded. */
@Serializable
data class DownloadedFilm(val tmdbId: Int, val title: String? = null, val year: Int? = null, val quality: String? = null, val importedAt: String? = null, val posterPath: String? = null)

// ------------------------------------------------------------------ an episode

@Serializable
data class EpisodeShow(
    val tmdbId: Int? = null, val title: String? = null, val posterPath: String? = null, val backdropPath: String? = null,
    val seasonsMeta: List<SeasonMeta> = emptyList(),
)

/** An episode of the same season, for stepping between them. */
@Serializable
data class EpisodeNav(val episodeNumber: Int, val title: String? = null)

@Serializable
data class EpisodeDetail(
    val tmdbId: Int? = null,
    val seasonNumber: Int = 0,
    val episodeNumber: Int = 0,
    val title: String? = null,
    val overview: String? = null,
    val stillPath: String? = null,
    val airDate: String? = null,
    val runtime: Int? = null,
    val tmdbRating: Double? = null,
    val imdbRating: Double? = null,
    val userRating: Double? = null,
    val watched: Boolean = false,
    val playCount: Int = 0,
    val badge: String? = null,
    val guestStars: List<Person> = emptyList(),
    val cast: List<Person> = emptyList(),
    val crew: List<Person> = emptyList(),
    val show: EpisodeShow? = null,
    val episodes: List<EpisodeNav> = emptyList(),
    val inLists: List<Int> = emptyList(),
    val collectionPct: Int = 0,
)

// ------------------------------------------------------------------ the home screen widget

@Serializable
data class Watched(val episodes: Int = 0, val movies: Int = 0, val minutes: Int = 0)

@Serializable
data class TopShow(val title: String, val episodes: Int = 0)

@Serializable
data class AtAGlance(
    val week: Watched = Watched(),
    val previousWeek: Watched = Watched(),
    val month: Watched = Watched(),
    val previousMonth: Watched = Watched(),
    val streakDays: Int = 0,
    val topShow: TopShow? = null,
)
