package app.watchd.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Icon
import androidx.compose.foundation.layout.size
import androidx.compose.ui.res.painterResource
import app.watchd.R
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.Api
import app.watchd.data.SignedOut
import app.watchd.data.WatchSession
import app.watchd.data.WatchTarget
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
import coil3.compose.AsyncImagePainter
import coil3.compose.rememberAsyncImagePainter
import androidx.compose.runtime.collectAsState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** The signed-in API, what to do when the token stops working, and the
 *  snackbar that confirms actions. */
class AppContext(
    val api: Api,
    val signOut: () -> Unit,
    val snackbar: SnackbarHostState,
    private val scope: CoroutineScope,
) {
    /** Running check-ins, for the Now watching bar. */
    var sessions by mutableStateOf<List<WatchSession>>(emptyList())
        private set

    /** Text shared into the app, for Search to start with. */
    var searchPrefill by mutableStateOf<String?>(null)

    /** The Watch sheet's film or episode, and what to refresh after a change. */
    var watchSheet by mutableStateOf<Pair<WatchTarget, () -> Unit>?>(null)

    fun openWatchSheet(target: WatchTarget, onChanged: () -> Unit = {}) {
        watchSheet = target to onChanged
    }

    fun refreshSessions() {
        scope.launch {
            try {
                sessions = api.sessions()
            } catch (e: SignedOut) {
                signOut()
            } catch (_: Exception) {
            }
        }
    }
    /**
     * Sends a change the screen has already shown (so a tick is instant).
     * On success, [message] is confirmed with an Undo that runs [undo] and
     * then [onUndo]; on failure [onFail] puts the screen back.
     */
    fun act(
        message: String?,
        action: suspend Api.() -> Unit,
        onFail: () -> Unit,
        undo: (suspend Api.() -> Unit)? = null,
        onUndo: () -> Unit = {},
        onDone: () -> Unit = {},
    ) {
        scope.launch {
            try {
                api.action()
            } catch (e: SignedOut) {
                signOut()
                return@launch
            } catch (e: Exception) {
                onFail()
                snackbar.currentSnackbarData?.dismiss()
                snackbar.showSnackbar("Couldn't reach Watchd")
                return@launch
            }
            onDone()
            if (message == null) return@launch
            snackbar.currentSnackbarData?.dismiss()
            val result = snackbar.showSnackbar(message, actionLabel = if (undo != null) "Undo" else null, duration = SnackbarDuration.Short)
            if (result == SnackbarResult.ActionPerformed && undo != null) {
                onUndo()
                runCatching { api.undo() }
                onDone()
            }
        }
    }
}

val LocalApp = compositionLocalOf<AppContext> { error("No AppContext") }

sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Ready<T>(val value: T) : Load<T>
    data class Failed(val message: String) : Load<Nothing>
}

/** Loads [block] when [key] changes; returns the state and a retry. A
 *  rejected token signs the app out instead of showing an error. */
@Composable
fun <T> rememberLoad(key: Any?, block: suspend Api.() -> T): Pair<Load<T>, () -> Unit> {
    val app = LocalApp.current
    var attempt by remember { mutableIntStateOf(0) }
    var state by remember(key) { mutableStateOf<Load<T>>(Load.Loading) }
    LaunchedEffect(key, attempt) {
        if (state !is Load.Ready) state = Load.Loading
        state = try {
            Load.Ready(app.api.block())
        } catch (e: SignedOut) {
            app.signOut()
            Load.Loading
        } catch (e: Exception) {
            Load.Failed(e.message ?: "Couldn't reach Watchd")
        }
    }
    return state to { attempt++ }
}

@Composable
fun <T> LoadContent(state: Load<T>, retry: () -> Unit, content: @Composable (T) -> Unit) {
    when (state) {
        is Load.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = Watchd.Red)
        }
        is Load.Failed -> Column(
            Modifier.fillMaxSize().padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(state.message, color = Watchd.Muted)
            Button(onClick = retry, modifier = Modifier.padding(top = 16.dp)) { Text("Try again") }
        }
        is Load.Ready -> content(state.value)
    }
}

@Composable
fun Poster(url: String?, modifier: Modifier = Modifier, ratio: Float = 2f / 3f) {
    AsyncImage(
        model = url,
        contentDescription = null,
        contentScale = ContentScale.Crop,
        modifier = modifier
            .aspectRatio(ratio)
            .clip(RoundedCornerShape(10.dp))
            .background(Watchd.Surface),
    )
}

/**
 * A disc's cover at its own shape, never cropped: case scans aren't 2:3 like
 * posters (a Blu-ray case is nearer 4:5). Until the picture arrives it holds
 * a Blu-ray case's shape.
 */
@Composable
fun Cover(url: String?, modifier: Modifier = Modifier) {
    val painter = rememberAsyncImagePainter(url)
    val state by painter.state.collectAsState()
    val size = (state as? AsyncImagePainter.State.Success)?.painter?.intrinsicSize
    val ratio = size?.takeIf { it.width > 0 && it.height > 0 }?.let { it.width / it.height } ?: (148f / 188f)
    Image(
        painter, contentDescription = null, contentScale = ContentScale.Fit,
        modifier = modifier.aspectRatio(ratio).clip(RoundedCornerShape(8.dp)).background(Watchd.Surface),
    )
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.headlineSmall,
        modifier = modifier.padding(horizontal = 16.dp, vertical = 12.dp),
    )
}

/** "IMDb 8.1" as the site's cards show it: the yellow tag and a yellow score ("—" without one). */
@Composable
fun ImdbBadge(rating: Double?, showEmpty: Boolean = false) {
    val has = rating != null && rating > 0
    if (!has && !showEmpty) return
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        Text(
            "IMDb",
            color = Color.Black,
            fontWeight = FontWeight.Black,
            fontSize = 10.sp,
            modifier = Modifier.clip(RoundedCornerShape(3.dp)).background(Watchd.ImdbYellow).padding(horizontal = 4.dp, vertical = 1.dp),
        )
        Text(if (has) "%.1f".format(rating) else "—", fontWeight = FontWeight.ExtraBold, fontSize = 15.sp, color = if (has) Watchd.ImdbYellow else Watchd.Muted)
    }
}

private val TmdbBlue = Color(0xFF01B4E4)

/**
 * A title page's ratings as the site shows them, in one pill: the TMDB logo
 * and score in TMDB blue, the IMDb logo and score in yellow, and your rating
 * as a red star.
 */
@Composable
fun RatingsPill(tmdb: Double?, imdb: Double?, mine: Double?, modifier: Modifier = Modifier) {
    val hasTmdb = (tmdb ?: 0.0) > 0
    val hasImdb = (imdb ?: 0.0) > 0
    if (!hasTmdb && !hasImdb && mine == null) return
    Row(
        modifier.clip(RoundedCornerShape(12.dp)).background(Watchd.Surface.copy(alpha = 0.6f))
            .border(1.dp, Watchd.SurfaceHigh, RoundedCornerShape(12.dp)).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        if (hasTmdb) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                AsyncImage("file:///android_asset/tmdb.svg", contentDescription = "TMDB", modifier = Modifier.width(30.dp).height(18.dp))
                Text("%.1f".format(tmdb), color = TmdbBlue, fontWeight = FontWeight.Black, fontSize = 15.sp)
            }
        }
        if (hasImdb) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Image(painterResource(R.drawable.logo_imdb), contentDescription = "IMDb", modifier = Modifier.width(34.dp).height(18.dp))
                Text("%.1f".format(imdb), color = Watchd.ImdbYellow, fontWeight = FontWeight.Black, fontSize = 15.sp)
            }
        }
        if (mine != null) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                Icon(Icons.Default.Star, contentDescription = "Your rating", tint = Watchd.Red, modifier = Modifier.size(18.dp))
                Text(if (mine % 1.0 == 0.0) "${mine.toInt()}" else "$mine", color = Watchd.Red, fontWeight = FontWeight.Black, fontSize = 15.sp)
            }
        }
    }
}

/**
 * A premiere or finale label coloured by kind, as on the site: green for a
 * series premiere, blue a season premiere, pink a mid-season premiere, amber
 * a mid-season finale, red a season finale and violet a series finale.
 */
@Composable
fun EpisodeBadge(label: String?, modifier: Modifier = Modifier) {
    if (label.isNullOrBlank()) return
    val (text, tint) = when (label.lowercase()) {
        "series premiere" -> Color(0xFF34D399) to Color(0xFF10B981)
        "season premiere" -> Color(0xFF38BDF8) to Color(0xFF0EA5E9)
        "mid-season premiere" -> Color(0xFFF472B6) to Color(0xFFEC4899)
        "mid-season finale" -> Color(0xFFFBBF24) to Color(0xFFF59E0B)
        "season finale" -> Color(0xFFFF4D55) to Color(0xFFE50914)
        "series finale" -> Color(0xFFC4B5FD) to Color(0xFF8B5CF6)
        else -> Color(0xFFD4D4D8) to Color(0xFFA1A1AA)
    }
    Text(
        label.uppercase(), color = text, fontSize = 9.sp, fontWeight = FontWeight.ExtraBold, letterSpacing = 0.8.sp,
        maxLines = 1,
        modifier = modifier.clip(RoundedCornerShape(50)).background(tint.copy(alpha = 0.15f))
            .border(1.dp, tint.copy(alpha = 0.5f), RoundedCornerShape(50)).padding(horizontal = 7.dp, vertical = 1.dp),
    )
}

/** The Watchd W, as on the site: red when watched, white when not. */
@Composable
fun WatchedMark(watched: Boolean, modifier: Modifier = Modifier.size(28.dp)) {
    Image(
        painterResource(if (watched) R.drawable.watched_on else R.drawable.watched_off),
        contentDescription = if (watched) "Watched" else "Not watched",
        modifier = modifier,
    )
}

fun episodeCode(season: Int?, episode: Int?) =
    "%02dx%02d".format(season ?: 0, episode ?: 0)

fun year(date: String?) = date?.take(4)?.takeIf { it.length == 4 }
