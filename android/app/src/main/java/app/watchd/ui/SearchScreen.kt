package app.watchd.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.MediaItem
import app.watchd.data.SignedOut
import app.watchd.ui.theme.Watchd
import kotlinx.coroutines.delay

@Composable
fun SearchScreen(openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    val app = LocalApp.current
    var query by rememberSaveable { mutableStateOf("") }
    var results by remember { mutableStateOf<List<MediaItem>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    // Search once typing pauses.
    LaunchedEffect(query) {
        val q = query.trim()
        if (q.length < 2) {
            results = emptyList()
            return@LaunchedEffect
        }
        delay(350)
        busy = true
        error = null
        try {
            results = app.api.search(q).results.filter { it.tmdbId != null && it.type in setOf("movie", "series") }
        } catch (e: SignedOut) {
            app.signOut()
        } catch (e: Exception) {
            error = e.message
        } finally {
            busy = false
        }
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        OutlinedTextField(
            query, { query = it },
            placeholder = { Text("Search films and shows") },
            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
            trailingIcon = { if (busy) CircularProgressIndicator(Modifier.padding(12.dp), strokeWidth = 2.dp, color = Watchd.Red) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(16.dp),
        )
        error?.let { Text(it, color = Watchd.Muted, modifier = Modifier.padding(horizontal = 16.dp)) }
        LazyVerticalGrid(
            columns = GridCells.Adaptive(110.dp),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            items(results, key = { "${it.type}-${it.tmdbId}" }) { item ->
                Column(Modifier.clickable { if (item.type == "series") openShow(item.tmdbId!!) else openMovie(item.tmdbId!!) }) {
                    Box {
                        Poster(item.posterPath, Modifier.fillMaxWidth())
                        if (item.watched) {
                            Icon(
                                Icons.Default.CheckCircle, contentDescription = "Watched", tint = Watchd.Red,
                                modifier = Modifier.align(Alignment.TopEnd).padding(6.dp),
                            )
                        }
                    }
                    Text(item.title.orEmpty(), fontWeight = FontWeight.Bold, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
                    Text(
                        listOfNotNull(year(item.releaseDate), if (item.type == "series") "TV" else "Film").joinToString(" · "),
                        color = Watchd.Faint, fontSize = 12.sp,
                    )
                }
            }
        }
    }
}
