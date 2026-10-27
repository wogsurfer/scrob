package app.watchd.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNamingStrategy
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.FormBody
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import kotlinx.serialization.json.JsonNull
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

/** The token is missing, expired or revoked: sign in again. */
class SignedOut : Exception("Signed out")

class ApiError(val code: Int, message: String) : Exception(message)

@OptIn(ExperimentalSerializationApi::class)
val json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
    namingStrategy = JsonNamingStrategy.SnakeCase
}

/**
 * Watchd's backend, through the site's /api/proxy route: the same address the
 * browser uses, with the token sent as a Bearer header.
 */
class Api(server: String, private val token: String?) {
    private val base: HttpUrl = "${server.trimEnd('/')}/api/proxy/".toHttpUrl()

    suspend fun me(): User = get("auth/me")
    suspend fun nextUp(limit: Int = 20): NextUpResponse = get("history/next-up", "limit" to "$limit")
    suspend fun upcoming(days: Int = 14): Upcoming = get("calendar/upcoming", "days" to "$days")
    suspend fun search(query: String): SearchResponse = get("media/search", "q" to query)
    suspend fun movie(tmdbId: Int): Movie = get("media/movie/$tmdbId")
    suspend fun show(tmdbId: Int): Show = get("shows/$tmdbId")
    suspend fun season(showTmdbId: Int, season: Int): Season = get("shows/$showTmdbId/season/$season")

    /** Marks a film or an episode watched now; [mediaType] is "movie" or "episode". */
    suspend fun markWatched(tmdbId: Int, mediaType: String) {
        val body = buildJsonObject {
            put("tmdb_id", tmdbId)
            put("media_type", mediaType)
        }.toString().toRequestBody("application/json".toMediaType())
        send(request("history").post(body))
    }

    /**
     * Logs a play of [target]. [watchedAt] is UTC; null with [unknownDate]
     * records it without a date, null without it means now.
     */
    suspend fun logWatch(target: WatchTarget, source: String?, watchedAt: LocalDateTime? = null, unknownDate: Boolean = false) {
        val body = buildJsonObject {
            put("tmdb_id", target.tmdbId)
            put("media_type", target.mediaType)
            put("completed", true)
            when {
                unknownDate -> put("watched_at", JsonNull)
                watchedAt != null -> put("watched_at", watchedAt.format(utcMinutes))
            }
            source?.let { put("watch_source", it) }
            target.showTmdbId?.let { put("series_tmdb_id", it) }
            target.season?.let { put("season_number", it) }
            target.episode?.let { put("episode_number", it) }
        }
        send(request("history").post(body.toString().toRequestBody(jsonType)))
    }

    suspend fun plays(target: WatchTarget): List<Play> =
        get("history/item-events", "tmdb_id" to "${target.tmdbId}", "media_type" to target.mediaType)

    suspend fun deletePlay(id: Int) = send(request("history/event/$id").delete())

    /** Checks in: a "Watch now" session that records the watch when it ends. */
    suspend fun checkIn(target: WatchTarget, source: String?) {
        val body = buildJsonObject {
            put("tmdb_id", target.tmdbId)
            put("media_type", target.mediaType)
            target.title?.let { put("title", it) }
            target.runtime?.let { put("runtime", it) }
            source?.let { put("watch_source", it) }
            target.showTmdbId?.let { put("show_tmdb_id", it) }
            target.season?.let { put("season_number", it) }
            target.episode?.let { put("episode_number", it) }
        }
        send(request("history/session/start").post(body.toString().toRequestBody(jsonType)))
    }

    suspend fun sessions(): List<WatchSession> = get("history/session/active")

    suspend fun pauseSession(session: WatchSession, pause: Boolean) {
        val body = buildJsonObject {
            put("progress_seconds", session.elapsedSeconds().toInt())
            put("state", if (pause) "paused" else "playing")
        }
        send(request("history/session/${session.sessionKey}").patch(body.toString().toRequestBody(jsonType)))
    }

    suspend fun finishSession(session: WatchSession) =
        send(request("history/session/${session.sessionKey}/complete").post(ByteArray(0).toRequestBody()))

    suspend fun cancelSession(session: WatchSession) = send(request("history/session/${session.sessionKey}").delete())

    suspend fun markSeasonWatched(showTmdbId: Int, season: Int) {
        val body = buildJsonObject {
            put("series_tmdb_id", showTmdbId)
            put("season_number", season)
        }.toString().toRequestBody("application/json".toMediaType())
        send(request("history/season").post(body))
    }

    suspend fun unwatchSeason(showTmdbId: Int, season: Int) =
        send(request("history/season", "series_tmdb_id" to "$showTmdbId", "season_number" to "$season").delete())

    suspend fun unwatch(tmdbId: Int, mediaType: String) =
        send(request("history/item", "tmdb_id" to "$tmdbId", "media_type" to mediaType).delete())

    suspend fun addToWatchlist(tmdbId: Int) =
        send(request("watchlist", "tmdb_id" to "$tmdbId").post(ByteArray(0).toRequestBody()))

    suspend fun removeFromWatchlist(tmdbId: Int) = send(request("watchlist/$tmdbId").delete())

    suspend fun login(username: String, password: String): LoginResponse =
        decode(send(request("auth/login").post(FormBody.Builder().add("username", username).add("password", password).build())))

    suspend fun verify2fa(tempToken: String, code: String): LoginResponse {
        val body = buildJsonObject {
            put("temp_token", tempToken)
            put("code", code)
        }.toString().toRequestBody("application/json".toMediaType())
        return decode(send(request("auth/2fa/verify-login").post(body)))
    }

    private suspend inline fun <reified T> get(path: String, vararg query: Pair<String, String>): T =
        decode(send(request(path, *query).get()))

    private inline fun <reified T> decode(text: String): T = json.decodeFromString(text)

    private fun request(path: String, vararg query: Pair<String, String>): Request.Builder {
        val url = base.newBuilder().addPathSegments(path).apply {
            query.forEach { (k, v) -> addQueryParameter(k, v) }
        }.build()
        return Request.Builder().url(url).apply {
            token?.let { header("Authorization", "Bearer $it") }
        }
    }

    private suspend fun send(builder: Request.Builder): String = withContext(Dispatchers.IO) {
        client.newCall(builder.build()).execute().use { response ->
            val text = response.body.string()
            when {
                response.code == 401 && token != null -> throw SignedOut()
                // Without a token the site answers with its login page instead.
                response.isRedirect || response.request.url.encodedPath == "/login" -> throw SignedOut()
                !response.isSuccessful -> throw ApiError(response.code, detail(text) ?: "Error ${response.code}")
                else -> text
            }
        }
    }

    /** FastAPI's {"detail": "..."} message, when the error has one. */
    private fun detail(text: String): String? = runCatching {
        (json.parseToJsonElement(text) as? JsonObject)?.get("detail")?.let { (it as? JsonPrimitive)?.content }
    }.getOrNull()

    companion object {
        private val jsonType = "application/json".toMediaType()
        private val utcMinutes = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm")

        val client: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .followRedirects(false)
            .build()
    }
}
