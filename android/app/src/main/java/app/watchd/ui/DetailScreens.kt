package app.watchd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.ButtonDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.Episode
import app.watchd.data.Person
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
import kotlinx.coroutines.launch

// ------------------------------------------------------------------ film

@Composable
fun MovieScreen(tmdbId: Int, onBack: () -> Unit) {
    val (state, reload) = rememberLoad(tmdbId) { movie(tmdbId) }
    val app = LocalApp.current
    val scope = rememberCoroutineScope()
    LoadContent(state, reload) { movie ->
        var watched by remember(movie) { mutableStateOf(movie.watched) }
        var inWatchlist by remember(movie) { mutableStateOf(movie.inWatchlist) }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 32.dp)) {
            item {
                DetailHeader(
                    backdrop = movie.backdropPath, poster = movie.posterPath, title = movie.title,
                    facts = listOfNotNull(year(movie.releaseDate), movie.runtime?.let { "${it / 60}h ${it % 60}m" }, movie.ageRating),
                    imdb = movie.imdbRating, onBack = onBack,
                )
            }
            item {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    ToggleButton(watched, if (watched) "Watched" else "Mark watched", Icons.Default.Check) {
                        scope.launch {
                            runCatching {
                                if (watched) app.api.unwatch(movie.tmdbId, "movie") else app.api.markWatched(movie.tmdbId, "movie")
                            }.onSuccess { watched = !watched }
                        }
                    }
                    ToggleButton(inWatchlist, "Watchlist", if (inWatchlist) Icons.Default.Bookmark else Icons.Default.BookmarkBorder) {
                        scope.launch {
                            runCatching {
                                if (inWatchlist) app.api.removeFromWatchlist(movie.tmdbId) else app.api.addToWatchlist(movie.tmdbId)
                            }.onSuccess { inWatchlist = !inWatchlist }
                        }
                    }
                }
            }
            item { Overview(movie.tagline, movie.overview, movie.genres) }
            val directors = movie.crew.filter { it.job == "Director" }.map { it.name }.distinct()
            if (directors.isNotEmpty()) {
                item { Credit("Directed by", directors.joinToString(", ")) }
            }
            if (movie.cast.isNotEmpty()) {
                item { SectionTitle("Cast", Modifier.padding(top = 8.dp)) }
                item { CastRow(movie.cast) }
            }
        }
    }
}

// ------------------------------------------------------------------ show

@Composable
fun ShowScreen(tmdbId: Int, onBack: () -> Unit, openSeason: (Int, Int) -> Unit) {
    val (state, reload) = rememberLoad(tmdbId) { show(tmdbId) }
    LoadContent(state, reload) { show ->
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 32.dp)) {
            item {
                DetailHeader(
                    backdrop = show.backdropPath, poster = show.posterPath, title = show.title,
                    facts = listOfNotNull(
                        year(show.firstAirDate)?.let { start -> if (show.status == "Ended") "$start–${year(show.lastAirDate) ?: ""}" else start },
                        show.networks.firstOrNull()?.name, show.ageRating,
                    ),
                    imdb = show.imdbRating, onBack = onBack,
                )
            }
            if (show.watchPct > 0) {
                item {
                    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                        Text("${show.watchPct}% watched", color = Watchd.Muted, fontSize = 13.sp)
                        Progress(show.watchPct)
                    }
                }
            }
            item { Overview(show.tagline, show.overview, show.genres) }
            item { SectionTitle("Seasons", Modifier.padding(top = 8.dp)) }
            items(show.seasonsMeta.sortedBy { if (it.seasonNumber == 0) Int.MAX_VALUE else it.seasonNumber }, key = { it.seasonNumber }) { season ->
                val seasonState = show.seasonStates[season.seasonNumber.toString()]
                Row(
                    Modifier.fillMaxWidth().clickable { openSeason(show.tmdbId, season.seasonNumber) }.padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Poster(season.posterPath ?: show.posterPath, Modifier.width(56.dp))
                    Column(Modifier.weight(1f)) {
                        Text(season.name ?: "Season ${season.seasonNumber}", fontWeight = FontWeight.Bold)
                        Text(
                            listOfNotNull(year(season.airDate), "${season.episodeCount} episodes").joinToString(" · "),
                            color = Watchd.Muted, fontSize = 13.sp,
                        )
                        if (seasonState != null && seasonState.watchPct > 0) Progress(seasonState.watchPct)
                    }
                    if (seasonState?.watched == true) Icon(Icons.Default.CheckCircle, contentDescription = "Watched", tint = Watchd.Red)
                }
            }
        }
    }
}

// ------------------------------------------------------------------ season

@Composable
fun SeasonScreen(showTmdbId: Int, seasonNumber: Int, onBack: () -> Unit) {
    val (state, reload) = rememberLoad(showTmdbId to seasonNumber) { season(showTmdbId, seasonNumber) }
    LoadContent(state, reload) { season ->
        LazyColumn(Modifier.fillMaxSize().statusBarsPadding(), contentPadding = PaddingValues(bottom = 32.dp)) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(8.dp)) {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
                    Text(season.name ?: "Season $seasonNumber", style = MaterialTheme.typography.headlineSmall)
                }
            }
            items(season.episodes, key = { it.tmdbId }) { EpisodeRow(it) }
        }
    }
}

@Composable
private fun EpisodeRow(episode: Episode) {
    val app = LocalApp.current
    val scope = rememberCoroutineScope()
    var watched by remember(episode) { mutableStateOf(episode.watched) }
    var expanded by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(horizontal = 16.dp, vertical = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            AsyncImage(
                model = episode.posterPath, contentDescription = null, contentScale = ContentScale.Crop,
                modifier = Modifier.width(128.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(8.dp)).background(Watchd.Surface),
            )
            Column(Modifier.weight(1f)) {
                Text("Episode ${episode.episodeNumber}", color = Watchd.Red, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                Text(episode.title.orEmpty(), fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(
                    listOfNotNull(episode.airDate, episode.runtime?.let { "$it min" }).joinToString(" · "),
                    color = Watchd.Faint, fontSize = 12.sp,
                )
                episode.badge?.let { Text(it.uppercase(), color = Watchd.Red, style = MaterialTheme.typography.labelSmall) }
            }
            IconButton(onClick = {
                scope.launch {
                    runCatching {
                        if (watched) app.api.unwatch(episode.tmdbId, "episode") else app.api.markWatched(episode.tmdbId, "episode")
                    }.onSuccess { watched = !watched }
                }
            }) {
                Icon(
                    if (watched) Icons.Default.CheckCircle else Icons.Outlined.Circle,
                    contentDescription = if (watched) "Watched" else "Mark watched",
                    tint = if (watched) Watchd.Red else Watchd.Faint,
                )
            }
        }
        if (expanded && !episode.overview.isNullOrBlank()) {
            Text(episode.overview, color = Watchd.Muted, modifier = Modifier.padding(top = 8.dp))
        }
    }
}

// ------------------------------------------------------------------ shared pieces

@Composable
private fun DetailHeader(backdrop: String?, poster: String?, title: String, facts: List<String>, imdb: Double?, onBack: () -> Unit) {
    // The poster overlaps the bottom of the backdrop, which fades into the page.
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val backdropHeight = maxWidth * 10 / 16
        AsyncImage(
            model = backdrop ?: poster, contentDescription = null, contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxWidth().height(backdropHeight).background(Watchd.Surface),
        )
        Box(
            Modifier.fillMaxWidth().height(backdropHeight)
                .background(Brush.verticalGradient(0f to Color.Black.copy(alpha = 0.35f), 0.45f to Color.Transparent, 1f to Watchd.Background)),
        )
        IconButton(
            onClick = onBack,
            colors = IconButtonDefaults.iconButtonColors(containerColor = Color.Black.copy(alpha = 0.5f)),
            modifier = Modifier.statusBarsPadding().padding(8.dp),
        ) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Color.White) }
        Row(
            Modifier.padding(start = 16.dp, end = 16.dp, top = backdropHeight - 64.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Poster(poster, Modifier.width(104.dp))
            Column(Modifier.weight(1f).padding(bottom = 4.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(title, style = MaterialTheme.typography.headlineSmall)
                if (facts.isNotEmpty()) Text(facts.joinToString(" · "), color = Watchd.Muted, fontSize = 13.sp)
                ImdbBadge(imdb)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Overview(tagline: String?, overview: String?, genres: List<String>) {
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (genres.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                genres.forEach {
                    Text(
                        it.uppercase(), style = MaterialTheme.typography.labelSmall, color = Watchd.Muted,
                        modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Watchd.Surface).padding(horizontal = 8.dp, vertical = 4.dp),
                    )
                }
            }
        }
        if (!tagline.isNullOrBlank()) Text(tagline, color = Watchd.Text, fontWeight = FontWeight.Bold)
        if (!overview.isNullOrBlank()) Text(overview, color = Watchd.Muted)
    }
}

@Composable
private fun Credit(label: String, value: String) {
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = Watchd.Faint)
        Text(value, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun CastRow(cast: List<Person>) {
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        items(cast.take(20)) { person ->
            Column(Modifier.width(96.dp)) {
                AsyncImage(
                    model = person.profilePath, contentDescription = null, contentScale = ContentScale.Crop,
                    modifier = Modifier.size(96.dp).clip(CircleShape).background(Watchd.Surface),
                )
                Text(person.name, fontWeight = FontWeight.Bold, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
                person.character?.let { Text(it, color = Watchd.Faint, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis) }
            }
        }
    }
}

@Composable
private fun ToggleButton(active: Boolean, label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, onClick: () -> Unit) {
    FilledTonalButton(
        onClick = onClick,
        colors = ButtonDefaults.filledTonalButtonColors(
            containerColor = if (active) Watchd.Red else Watchd.Surface,
            contentColor = Color.White,
        ),
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(6.dp))
        Text(label)
    }
}

@Composable
private fun Progress(pct: Int) {
    LinearProgressIndicator(
        progress = { pct / 100f }, color = Watchd.Red, trackColor = Watchd.SurfaceHigh,
        gapSize = 0.dp, drawStopIndicator = {},
        modifier = Modifier.fillMaxWidth().padding(top = 6.dp).height(4.dp).clip(CircleShape),
    )
}
