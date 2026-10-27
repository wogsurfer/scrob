package app.watchd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
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
import app.watchd.data.NextUpItem
import app.watchd.data.NextUpResponse
import app.watchd.data.Upcoming
import app.watchd.data.UpcomingEpisode
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter

private data class Dashboard(val nextUp: NextUpResponse, val upcoming: Upcoming)

@Composable
fun DashboardScreen(openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    val (state, reload) = rememberLoad(Unit) {
        coroutineScope {
            val nextUp = async { nextUp() }
            val upcoming = async { upcoming() }
            Dashboard(nextUp.await(), upcoming.await())
        }
    }
    var refreshing by remember { mutableStateOf(false) }
    if (state !is Load.Loading) refreshing = false

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = { refreshing = true; reload() }) {
        LoadContent(state, reload) { data ->
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                item { Spacer(Modifier.statusBarsPadding().height(8.dp)) }
                item { SectionTitle("Next Up") }
                item {
                    if (data.nextUp.nextUp.isEmpty()) {
                        Text("You're all caught up.", color = Watchd.Muted, modifier = Modifier.padding(horizontal = 16.dp))
                    }
                    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        items(data.nextUp.nextUp, key = { it.tmdbId }) { item ->
                            NextUpCard(item, onOpen = { item.showTmdbId?.let(openShow) }, onWatched = reload)
                        }
                    }
                }
                item { SectionTitle("Upcoming", Modifier.padding(top = 12.dp)) }
                val byDay = data.upcoming.episodes.filter { !it.airDate.isNullOrBlank() }.groupBy { it.airDate!! }.toSortedMap()
                if (byDay.isEmpty()) {
                    item { Text("Nothing scheduled.", color = Watchd.Muted, modifier = Modifier.padding(horizontal = 16.dp)) }
                }
                byDay.forEach { (day, episodes) ->
                    item(key = "day-$day") { DayHeader(day, data.upcoming.today) }
                    items(episodes.sortedBy { it.airTime ?: "99:99" }, key = { "$day-${it.showTmdbId}-${it.season}-${it.episode}" }) { ep ->
                        UpcomingRow(ep, onOpen = { ep.showTmdbId?.let(openShow) })
                    }
                }
            }
        }
    }
}

@Composable
private fun NextUpCard(item: NextUpItem, onOpen: () -> Unit, onWatched: () -> Unit) {
    val app = LocalApp.current
    val scope = rememberCoroutineScope()
    var marking by remember { mutableStateOf(false) }
    Column(Modifier.width(300.dp).clip(RoundedCornerShape(12.dp)).background(Watchd.Surface).clickable(onClick = onOpen)) {
        Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f)) {
            AsyncImage(
                model = item.posterPath ?: item.showBackdropPath,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize().background(Watchd.SurfaceHigh),
            )
            Box(Modifier.fillMaxSize().background(Brush.verticalGradient(0.4f to Color.Transparent, 1f to Color.Black.copy(alpha = 0.85f))))
            Column(Modifier.align(Alignment.BottomStart).padding(12.dp)) {
                Text(item.showTitle.orEmpty(), color = Watchd.Muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    "${episodeCode(item.seasonNumber, item.episodeNumber)}  ${item.title.orEmpty()}",
                    fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
            }
            IconButton(
                onClick = {
                    marking = true
                    scope.launch {
                        runCatching { app.api.markWatched(item.tmdbId, "episode") }
                        marking = false
                        onWatched()
                    }
                },
                enabled = !marking,
                colors = IconButtonDefaults.iconButtonColors(containerColor = Color.Black.copy(alpha = 0.6f)),
                modifier = Modifier.align(Alignment.TopEnd).padding(8.dp).size(36.dp),
            ) { Icon(Icons.Default.Check, contentDescription = "Mark watched", tint = if (marking) Watchd.Faint else Color.White) }
        }
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                ImdbBadge(item.showImdbRating)
                Spacer(Modifier.weight(1f))
                Text("${item.showEpisodesWatched} of ${item.showEpisodesTotal}", color = Watchd.Muted, fontSize = 12.sp)
            }
            LinearProgressIndicator(
                progress = { item.showWatchPct / 100f },
                color = Watchd.Red,
                trackColor = Watchd.SurfaceHigh,
                gapSize = 0.dp,
                drawStopIndicator = {},
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp).height(4.dp).clip(CircleShape),
            )
        }
    }
}

private val dayFormat = DateTimeFormatter.ofPattern("EEEE d MMMM")

@Composable
private fun DayHeader(day: String, today: String?) {
    val date = runCatching { LocalDate.parse(day) }.getOrNull()
    val label = when {
        day == today -> "Today"
        date != null && today != null && date == runCatching { LocalDate.parse(today).plusDays(1) }.getOrNull() -> "Tomorrow"
        date != null -> date.format(dayFormat)
        else -> day
    }
    Text(
        label.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        color = if (day == today) Watchd.Red else Watchd.Muted,
        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 6.dp),
    )
}

@Composable
private fun UpcomingRow(ep: UpcomingEpisode, onOpen: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Poster(ep.showPosterPath, Modifier.width(44.dp))
        Column(Modifier.weight(1f)) {
            Text(ep.showTitle.orEmpty(), fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                buildString {
                    append(episodeCode(ep.season, ep.episode))
                    ep.title?.let { append("  ").append(it) }
                },
                color = Watchd.Muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            ep.badge?.let { Text(it.uppercase(), color = Watchd.Red, style = MaterialTheme.typography.labelSmall) }
        }
        Column(horizontalAlignment = Alignment.End) {
            ep.airTime?.let { Text(it, fontWeight = FontWeight.Bold) }
            ep.network?.let { Text(it.uppercase(), color = Watchd.Faint, fontSize = 10.sp, fontWeight = FontWeight.Bold) }
        }
    }
}
