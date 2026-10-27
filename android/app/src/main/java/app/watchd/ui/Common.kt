package app.watchd.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
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
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
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

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.headlineSmall,
        modifier = modifier.padding(horizontal = 16.dp, vertical = 12.dp),
    )
}

/** "IMDb 8.1" in the site's yellow badge style. */
@Composable
fun ImdbBadge(rating: Double?) {
    if (rating == null || rating <= 0) return
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            "IMDb",
            color = Color.Black,
            fontWeight = FontWeight.Black,
            fontSize = 10.sp,
            modifier = Modifier.clip(RoundedCornerShape(3.dp)).background(Watchd.ImdbYellow).padding(horizontal = 4.dp, vertical = 1.dp),
        )
        Text("%.1f".format(rating), fontWeight = FontWeight.Bold, fontSize = 13.sp)
    }
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
