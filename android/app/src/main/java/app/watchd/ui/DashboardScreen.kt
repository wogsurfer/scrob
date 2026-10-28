package app.watchd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.material.icons.filled.Album
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.Tv
import app.watchd.data.PipelineHealth
import app.watchd.data.Totals
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
import androidx.compose.foundation.layout.wrapContentHeight
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
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
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
import app.watchd.data.WatchTarget
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter

private data class Dashboard(val nextUp: NextUpResponse, val upcoming: Upcoming)

private data class Header(val posters: List<String>, val totals: Totals?, val health: PipelineHealth?)

@Composable
fun DashboardScreen(openShow: (Int) -> Unit, openMovie: (Int) -> Unit, openCollection: () -> Unit) {
    val (state, reload) = rememberLoad(Unit) {
        coroutineScope {
            val nextUp = async { nextUp() }
            // Home shows the rest of this week, through Sunday.
            val upcoming = async { upcoming(days = 8 - LocalDate.now().dayOfWeek.value) }
            Dashboard(nextUp.await(), upcoming.await())
        }
    }
    // The header loads on its own, so a slow stat never holds up Next Up.
    val (header, reloadHeader) = rememberLoad("header") {
        coroutineScope {
            val hero = async { runCatching { hero().posters }.getOrDefault(emptyList()) }
            val totals = async { runCatching { totals() }.getOrNull() }
            val health = async { runCatching { pipelineHealth() }.getOrNull() }
            Header(hero.await(), totals.await(), health.await())
        }
    }
    var refreshing by remember { mutableStateOf(false) }
    if (state !is Load.Loading) refreshing = false
    val app = LocalApp.current
    val haptics = LocalHapticFeedback.current
    // Ticked cards leave at once; the reload then brings each show's next episode.
    val ticked = remember { mutableStateListOf<Int>() }

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = { refreshing = true; reload(); reloadHeader() }) {
        LoadContent(state, reload) { data ->
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                item { HeroHeader((header as? Load.Ready)?.value, openCollection) }
                item { SectionTitle("Next Up") }
                item {
                    val nextUp = data.nextUp.nextUp.filter { it.tmdbId !in ticked }
                    if (nextUp.isEmpty()) {
                        Text("You're all caught up.", color = Watchd.Muted, modifier = Modifier.padding(horizontal = 16.dp))
                    }
                    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        items(nextUp, key = { it.tmdbId }) { item ->
                            NextUpCard(
                                item, Modifier.animateItem(),
                                onOpen = { item.showTmdbId?.let(openShow) },
                                onLongPress = {
                                    app.openWatchSheet(
                                        WatchTarget(item.tmdbId, "episode", item.title, item.showTmdbId, item.seasonNumber, item.episodeNumber),
                                        reload,
                                    )
                                },
                            ) {
                                haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                                ticked.add(item.tmdbId)
                                app.act(
                                    "${item.showTitle.orEmpty()} ${episodeCode(item.seasonNumber, item.episodeNumber)} watched",
                                    action = { markWatched(item.tmdbId, "episode") },
                                    onFail = { ticked.remove(item.tmdbId) },
                                    undo = { unwatch(item.tmdbId, "episode") },
                                    onUndo = { ticked.remove(item.tmdbId) },
                                    onDone = reload,
                                )
                            }
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

/**
 * The site's dashboard header: a dimmed wall of posters behind the greeting,
 * the downloads health chip, and what you've watched and own.
 */
@Composable
private fun HeroHeader(header: Header?, openCollection: () -> Unit) {
    Box(Modifier.fillMaxWidth().clipToBounds()) {
        val posters = header?.posters.orEmpty()
        if (posters.isNotEmpty()) {
            // Full-size rows from the top; the header crops whatever runs past its foot.
            Column(Modifier.matchParentSize().wrapContentHeight(Alignment.Top, unbounded = true), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                posters.chunked(6).take(4).forEach { row ->
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        row.forEach { poster ->
                            AsyncImage(
                                poster, contentDescription = null, contentScale = ContentScale.Crop,
                                modifier = Modifier.weight(1f).aspectRatio(2f / 3f).background(Watchd.Surface),
                            )
                        }
                        repeat(6 - row.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
            }
        }
        Box(
            Modifier.matchParentSize().background(
                Brush.verticalGradient(0f to Color.Black.copy(alpha = 0.55f), 0.6f to Color.Black.copy(alpha = 0.8f), 1f to Watchd.Background),
            ),
        )
        Column(Modifier.statusBarsPadding().padding(start = 16.dp, end = 16.dp, top = 20.dp, bottom = 12.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    // As on the site, which also greets David by name.
                    Text("Hello, David", fontSize = 28.sp, fontWeight = FontWeight.Black, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("WATCHING SINCE 1989", color = Watchd.Muted, fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
                }
                header?.health?.let { DownloadsChip(it) }
            }
            val totals = header?.totals
            Column(Modifier.padding(top = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                HeroStat(
                    Icons.Default.Tv,
                    totals?.let { "${duration(it.tv.minutes)} watched" },
                    totals?.let { "${"%,d".format(it.tv.episodes)} episodes · ${"%,d".format(it.tv.shows)} shows" },
                )
                HeroStat(
                    Icons.Default.Movie,
                    totals?.let { "${duration(it.movies.minutes)} watched" },
                    totals?.let { "${"%,d".format(it.movies.movies)} movies · ${"%,d".format(it.movies.plays)} plays" },
                )
                HeroStat(
                    Icons.Default.Album,
                    totals?.let { "${"%,d".format(it.library.movies)} films on disc" },
                    totals?.let { "${"%,d".format(it.library.shows)} TV series on disc" },
                    onClick = openCollection,
                )
            }
        }
    }
}

@Composable
private fun HeroStat(icon: ImageVector, line1: String?, line2: String?, onClick: (() -> Unit)? = null) {
    Row(
        Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = Watchd.Red, modifier = Modifier.size(26.dp))
        Column(Modifier.padding(start = 12.dp)) {
            Text(line1 ?: " ", fontWeight = FontWeight.Bold, fontSize = 16.sp)
            Text(line2 ?: " ", color = Watchd.Muted, fontSize = 12.sp)
        }
    }
}

/** Green when the download pipeline is fine, amber or red with a count when not. */
@Composable
private fun DownloadsChip(health: PipelineHealth) {
    val dot = when (health.status) {
        "ok" -> Color(0xFF22C55E)
        "warn" -> Color(0xFFF59E0B)
        "error" -> Color(0xFFEF4444)
        else -> Watchd.Muted
    }
    val text = when {
        health.status == "ok" -> "DOWNLOADS OK"
        health.problems > 0 -> "DOWNLOADS: ${health.problems} PROBLEM${if (health.problems == 1) "" else "S"}"
        else -> "DOWNLOADS"
    }
    Row(
        Modifier.clip(RoundedCornerShape(50)).background(Color.Black.copy(alpha = 0.5f))
            .border(1.dp, dot.copy(alpha = 0.5f), RoundedCornerShape(50)).padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(7.dp).clip(CircleShape).background(dot))
        Text(text, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp, modifier = Modifier.padding(start = 6.dp))
    }
}

/** "12d 4h 30m", as the site writes watch time. */
private fun duration(minutes: Long): String {
    val days = minutes / 1440
    val hours = minutes % 1440 / 60
    val mins = minutes % 60
    return when {
        days > 0 -> "${days}d ${hours}h ${mins}m"
        hours > 0 -> "${hours}h ${mins}m"
        else -> "${mins}m"
    }
}

/**
 * Next Up as the site's card: the season's poster, a strip with the W and the
 * show's IMDb score, a thin red progress line, then the episode and progress.
 */
@Composable
private fun NextUpCard(item: NextUpItem, modifier: Modifier, onOpen: () -> Unit, onLongPress: () -> Unit, onWatched: () -> Unit) {
    Column(modifier.width(140.dp).clip(RoundedCornerShape(10.dp)).background(Watchd.Surface).clickable(onClick = onOpen)) {
        AsyncImage(
            model = item.seasonPosterPath ?: item.showPosterPath,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxWidth().aspectRatio(2f / 3f).background(Watchd.SurfaceHigh),
        )
        Row(Modifier.fillMaxWidth().padding(end = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            WatchButton(false, size = 26.dp, onTap = onWatched, onLongPress = onLongPress)
            Spacer(Modifier.weight(1f))
            ImdbBadge(item.showImdbRating, showEmpty = true)
        }
        Box(Modifier.fillMaxWidth().height(3.dp).background(Watchd.SurfaceHigh)) {
            Box(Modifier.fillMaxWidth(item.showWatchPct.coerceIn(0, 100) / 100f).fillMaxHeight().background(Watchd.Red))
        }
        Column(Modifier.padding(10.dp)) {
            Text(
                "${episodeCode(item.seasonNumber, item.episodeNumber)} ${item.title.orEmpty()}",
                fontWeight = FontWeight.Bold, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            Text(
                "${item.showEpisodesWatched} of ${item.showEpisodesTotal} watched · ${item.showWatchPct}%",
                color = Watchd.Muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            Text(item.showTitle.orEmpty(), color = Watchd.Muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

private val dayFormat = DateTimeFormatter.ofPattern("EEEE d MMMM")

@Composable
internal fun DayHeader(day: String, today: String?) {
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
internal fun UpcomingRow(ep: UpcomingEpisode, onOpen: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Poster(ep.seasonPosterPath ?: ep.showPosterPath, Modifier.width(44.dp))
        Column(Modifier.weight(1f)) {
            Text(ep.showTitle.orEmpty(), fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                buildString {
                    append(episodeCode(ep.season, ep.episode))
                    ep.title?.let { append("  ").append(it) }
                },
                color = Watchd.Muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            EpisodeBadge(ep.badge, Modifier.padding(top = 3.dp))
        }
        Column(horizontalAlignment = Alignment.End) {
            ep.airTime?.let { Text(it, fontWeight = FontWeight.Bold) }
            ep.network?.let { Text(it.uppercase(), color = Watchd.Faint, fontSize = 10.sp, fontWeight = FontWeight.Bold) }
        }
        if (ep.watched) WatchedMark(true, Modifier.size(22.dp))
    }
}
