package app.watchd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.HistoryEvent
import app.watchd.data.SignedOut
import app.watchd.data.UpcomingMovie
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.TemporalAdjusters

private val shortDay = DateTimeFormatter.ofPattern("d MMM")

/** A titled page under the status bar, with an optional back arrow. */
@Composable
private fun PageTitle(title: String, onBack: (() -> Unit)? = null) {
    Row(Modifier.statusBarsPadding().padding(start = if (onBack != null) 4.dp else 0.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        onBack?.let { IconButton(onClick = it) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") } }
        SectionTitle(title, Modifier.padding(start = if (onBack != null) 0.dp else 0.dp))
    }
}

// ------------------------------------------------------------------ calendar

/** Five weeks from this Monday: episodes from your shows and release dates of films you follow. */
@Composable
fun CalendarScreen(openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    val (state, reload) = rememberLoad(Unit) { calendar(35) }
    LoadContent(state, reload) { data ->
        val today = data.today?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: LocalDate.now()
        val thisMonday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        val episodes = data.episodes.filter { !it.airDate.isNullOrBlank() }.groupBy { it.airDate!! }
        val movies = data.movies.filter { !it.date.isNullOrBlank() }.groupBy { it.date!! }
        val days = (episodes.keys + movies.keys).sorted()
        val byWeek = days.groupBy { runCatching { LocalDate.parse(it).with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY)) }.getOrDefault(thisMonday) }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
            item { PageTitle("Calendar") }
            if (days.isEmpty()) item { Text("Nothing scheduled.", color = Watchd.Muted, modifier = Modifier.padding(16.dp)) }
            byWeek.toSortedMap().forEach { (monday, weekDays) ->
                item(key = "week-$monday") {
                    val label = when (monday) {
                        thisMonday -> "This week"
                        thisMonday.plusWeeks(1) -> "Next week"
                        else -> "${monday.format(shortDay)} – ${monday.plusDays(6).format(shortDay)}"
                    }
                    Text(
                        label, style = MaterialTheme.typography.titleMedium, color = Watchd.Text,
                        modifier = Modifier.fillMaxWidth().background(Watchd.Surface).padding(horizontal = 16.dp, vertical = 10.dp),
                    )
                }
                weekDays.forEach { day ->
                    item(key = "day-$day") { DayHeader(day, data.today) }
                    items(episodes[day].orEmpty().sortedBy { it.airTime ?: "99:99" }, key = { "ep-$day-${it.showTmdbId}-${it.season}-${it.episode}" }) { ep ->
                        UpcomingRow(ep, onOpen = { ep.showTmdbId?.let(openShow) })
                    }
                    items(movies[day].orEmpty(), key = { "film-$day-${it.tmdbId}-${it.label}" }) { film ->
                        FilmReleaseRow(film) { openMovie(film.tmdbId) }
                    }
                }
            }
        }
    }
}

@Composable
private fun FilmReleaseRow(film: UpcomingMovie, onOpen: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Poster(film.posterPath, Modifier.width(44.dp))
        Column(Modifier.weight(1f)) {
            Text(film.title.orEmpty(), fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text("Film", color = Watchd.Muted, fontSize = 13.sp)
        }
        film.label?.let {
            Text(
                it.uppercase(), style = MaterialTheme.typography.labelSmall, color = Watchd.Red,
                modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Watchd.Surface).padding(horizontal = 8.dp, vertical = 4.dp),
            )
        }
    }
}

// ------------------------------------------------------------------ history

private val historyDay = DateTimeFormatter.ofPattern("EEEE d MMMM yyyy")
private val historyTime = DateTimeFormatter.ofPattern("HH:mm")

/** UTC "2026-10-27T21:18:39" as local time. */
private fun localTime(utc: String?): LocalDateTime? = utc?.let {
    runCatching { LocalDateTime.parse(it.take(19)).atOffset(ZoneOffset.UTC).atZoneSameInstant(ZoneId.systemDefault()).toLocalDateTime() }.getOrNull()
}

/** Everything watched, newest first, a page at a time as you scroll. */
@Composable
fun HistoryScreen(openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    val app = LocalApp.current
    val events = remember { mutableStateListOf<HistoryEvent>() }
    var page by remember { mutableIntStateOf(0) }
    var lastPage by remember { mutableIntStateOf(Int.MAX_VALUE) }
    var total by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val list = rememberLazyListState()
    val nearEnd by remember { derivedStateOf { list.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0 >= list.layoutInfo.totalItemsCount - 10 } }

    LaunchedEffect(nearEnd, page) {
        if (!nearEnd || loading || page >= lastPage) return@LaunchedEffect
        loading = true
        try {
            val next = app.api.history(page + 1)
            events.addAll(next.results.filter { e -> events.none { it.id == e.id } })
            lastPage = next.totalPages
            total = next.totalResults
            page = next.page
            error = null
        } catch (e: SignedOut) {
            app.signOut()
        } catch (e: Exception) {
            error = e.message ?: "Couldn't reach Watchd"
            lastPage = page  // stop retrying until Try again
        } finally {
            loading = false
        }
    }

    val today = LocalDate.now()
    val grouped = events.groupBy { localTime(it.watchedAt)?.toLocalDate() }
    LazyColumn(Modifier.fillMaxSize(), state = list, contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            PageTitle("History")
            if (total > 0) Text("%,d plays".format(total), color = Watchd.Muted, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 16.dp))
        }
        grouped.forEach { (day, dayEvents) ->
            item(key = "h-day-$day") {
                val label = when (day) {
                    null -> "Unknown date"
                    today -> "Today"
                    today.minusDays(1) -> "Yesterday"
                    else -> day.format(historyDay)
                }
                Text(
                    label.uppercase(), style = MaterialTheme.typography.labelSmall,
                    color = if (day == today) Watchd.Red else Watchd.Muted,
                    modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 6.dp),
                )
            }
            items(dayEvents, key = { "h-${it.id}" }) { event -> HistoryRow(event, openShow, openMovie) }
        }
        item {
            Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                when {
                    loading -> CircularProgressIndicator(color = Watchd.Red)
                    error != null -> OutlinedButton(onClick = { error = null; lastPage = Int.MAX_VALUE }) { Text("Try again") }
                }
            }
        }
    }
}

@Composable
private fun HistoryRow(event: HistoryEvent, openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    val media = event.media
    val episode = media.type == "episode"
    Row(
        Modifier.fillMaxWidth().clickable {
            if (episode) media.showTmdbId?.let(openShow) else media.tmdbId?.let(openMovie)
        }.padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Poster(if (episode) media.seasonPosterPath ?: media.showPosterPath ?: media.posterPath else media.posterPath, Modifier.width(44.dp))
        Column(Modifier.weight(1f)) {
            Text(if (episode) media.showTitle.orEmpty() else media.title.orEmpty(), fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                if (episode) "${episodeCode(media.seasonNumber, media.episodeNumber)}  ${media.title.orEmpty()}" else listOfNotNull("Film", year(media.releaseDate)).joinToString(" · "),
                color = Watchd.Muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
        Column(horizontalAlignment = Alignment.End) {
            localTime(event.watchedAt)?.let { Text(it.format(historyTime), fontWeight = FontWeight.Bold, fontSize = 13.sp) }
            event.watchSource?.let { Text(it.uppercase(), color = Watchd.Faint, fontSize = 10.sp, fontWeight = FontWeight.Bold) }
        }
    }
}

// ------------------------------------------------------------------ you

private data class You(val name: String, val totals: app.watchd.data.Totals, val stats: app.watchd.data.ProfileStats?, val lists: List<app.watchd.data.UserList>, val watchlistPoster: String?)

/** "504d 0h": days and hours of watching. */
private fun watchTime(minutes: Long): String {
    val days = minutes / (60 * 24)
    val hours = (minutes / 60) % 24
    return if (days > 0) "${days}d ${hours}h" else "${hours}h ${minutes % 60}m"
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun YouScreen(openWatchlist: () -> Unit, openList: (Int) -> Unit) {
    val app = LocalApp.current
    val (state, reload) = rememberLoad(Unit) {
        coroutineScope {
            val me = me()
            val totals = async { totals() }
            val stats = async { runCatching { profileStats(me.id) }.getOrNull() }
            // As on the site's Lists page: "Movies" was merged into the
            // Watchlist (27 Oct 2026), which comes first; then this order.
            val order = listOf("following", "watchlist tv", "ended & completed")
            val lists = async {
                runCatching {
                    lists().lists
                        .filter { !it.name.equals("Movies", ignoreCase = true) }
                        .sortedWith(compareBy({ order.indexOf(it.name.lowercase()).let { i -> if (i < 0) order.size else i } }, { it.name.lowercase() }))
                }.getOrDefault(emptyList())
            }
            val poster = async { runCatching { watchlistPreview().firstOrNull { it.posterPath != null }?.posterPath }.getOrNull() }
            You(me.displayName ?: me.username, totals.await(), stats.await(), lists.await(), poster.await())
        }
    }
    LoadContent(state, reload) { you ->
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
            item { PageTitle(you.name) }
            item {
                Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    StatTile("TV", watchTime(you.totals.tv.minutes), "%,d eps · %,d shows".format(you.totals.tv.episodes, you.totals.tv.shows), Modifier.weight(1f))
                    StatTile("Films", watchTime(you.totals.movies.minutes), "%,d films · %,d plays".format(you.totals.movies.movies, you.totals.movies.plays), Modifier.weight(1f))
                }
            }
            item {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    StatTile("On disc", "%,d".format(you.totals.library.movies), "films · %,d series".format(you.totals.library.shows), Modifier.weight(1f))
                    StatTile(
                        "Average rating",
                        you.stats?.avgMovieRating?.let { "%.1f".format(it) } ?: "–",
                        you.stats?.avgShowRating?.let { "films · %.1f shows".format(it) } ?: "films",
                        Modifier.weight(1f),
                    )
                }
            }
            you.stats?.watchActivity?.takeLast(12)?.takeIf { it.isNotEmpty() }?.let { months ->
                item { ActivityChart(months) }
            }
            you.stats?.let { stats ->
                val genres = (stats.topShowGenres + stats.topMovieGenres).groupBy { it.name }.map { (name, g) -> name to g.sumOf { it.count } }.sortedByDescending { it.second }.take(8)
                if (genres.isNotEmpty()) {
                    item {
                        Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                            Text("TOP GENRES", style = MaterialTheme.typography.labelSmall, color = Watchd.Faint)
                            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                genres.forEach { (name, _) ->
                                    Text(
                                        name.uppercase(), style = MaterialTheme.typography.labelSmall, color = Watchd.Muted,
                                        modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Watchd.Surface).padding(horizontal = 8.dp, vertical = 4.dp),
                                    )
                                }
                            }
                        }
                    }
                }
            }
            item { SectionTitle("Collections", Modifier.padding(top = 8.dp)) }
            item { LinkRow("Watchlist", "Films you want to see", you.watchlistPoster, openWatchlist) }
            items(you.lists, key = { "list-${it.id}" }) { list ->
                LinkRow(list.name, "%,d titles".format(list.itemCount), list.previewPosters.firstOrNull()?.url) { openList(list.id) }
            }
            item {
                OutlinedButton(onClick = app.signOut, modifier = Modifier.padding(16.dp)) { Text("Sign out", color = Watchd.Muted) }
            }
        }
    }
}

@Composable
private fun StatTile(label: String, value: String, detail: String, modifier: Modifier = Modifier) {
    Column(modifier.clip(RoundedCornerShape(12.dp)).background(Watchd.Surface).padding(14.dp)) {
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = Watchd.Faint)
        Text(value, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(top = 4.dp))
        Text(detail, color = Watchd.Muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** The last twelve months: episodes and films watched each month. */
@Composable
private fun ActivityChart(months: List<app.watchd.data.MonthActivity>) {
    val peak = months.maxOf { it.episodes + it.movies }.coerceAtLeast(1)
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text("LAST 12 MONTHS", style = MaterialTheme.typography.labelSmall, color = Watchd.Faint)
        // Bars standing on one baseline, month initials in their own row below.
        Row(Modifier.fillMaxWidth().height(90.dp).padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            months.forEach { m ->
                Box(Modifier.weight(1f).fillMaxHeight(), contentAlignment = Alignment.BottomCenter) {
                    val share = (m.episodes + m.movies).toFloat() / peak
                    Box(Modifier.fillMaxWidth().fillMaxHeight(share.coerceAtLeast(0.03f)).clip(RoundedCornerShape(topStart = 3.dp, topEnd = 3.dp)).background(Watchd.Red))
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            months.forEach { m ->
                Text(
                    runCatching { LocalDate.parse("${m.month}-01").month.name.take(1) }.getOrDefault(""),
                    color = Watchd.Faint, fontSize = 10.sp, textAlign = TextAlign.Center, modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

@Composable
private fun LinkRow(title: String, detail: String, poster: String?, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (poster != null) Poster(poster, Modifier.width(40.dp))
        else Box(Modifier.width(40.dp).height(60.dp).clip(RoundedCornerShape(10.dp)).background(Watchd.Surface), contentAlignment = Alignment.Center) {
            WatchedMark(false, Modifier.size(22.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, fontWeight = FontWeight.Bold)
            Text(detail, color = Watchd.Muted, fontSize = 13.sp)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = Watchd.Faint)
    }
}

// ------------------------------------------------------------------ watchlist and lists

private data class GridItem(val tmdbId: Int, val type: String, val title: String?, val poster: String?, val sub: String?)

@Composable
fun WatchlistScreen(onBack: () -> Unit, openMovie: (Int) -> Unit) {
    val (state, reload) = rememberLoad(Unit) { watchlist() }
    LoadContent(state, reload) { films ->
        PosterGrid(
            "Watchlist", "%,d films".format(films.size), onBack,
            films.map { GridItem(it.tmdbId, "movie", it.title, it.posterPath, listOfNotNull(it.year?.toString(), it.runtime?.let { r -> "${r / 60}h ${r % 60}m" }).joinToString(" · ")) },
            openShow = {}, openMovie = openMovie,
        )
    }
}

@Composable
fun ListScreen(listId: Int, onBack: () -> Unit, openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    val (state, reload) = rememberLoad(listId) { list(listId) }
    LoadContent(state, reload) { list ->
        PosterGrid(
            list.name, list.description ?: "%,d titles".format(list.itemCount), onBack,
            list.items.mapNotNull { e -> e.media.tmdbId?.let { GridItem(it, e.media.type, e.media.title, e.media.posterPath, year(e.media.releaseDate)) } },
            openShow, openMovie,
        )
    }
}

@Composable
private fun PosterGrid(title: String, subtitle: String, onBack: () -> Unit, items: List<GridItem>, openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    LazyVerticalGrid(
        columns = GridCells.Adaptive(104.dp),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Column {
                Box(Modifier.padding(start = 0.dp)) { PageTitle(title, onBack) }
                Text(subtitle, color = Watchd.Muted, fontSize = 13.sp, modifier = Modifier.padding(bottom = 8.dp))
            }
        }
        items(items, key = { "${it.type}-${it.tmdbId}" }) { item ->
            Column(Modifier.clickable { if (item.type == "series" || item.type == "show") openShow(item.tmdbId) else openMovie(item.tmdbId) }) {
                Poster(item.poster, Modifier.fillMaxWidth())
                Text(item.title.orEmpty(), fontWeight = FontWeight.Bold, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
                item.sub?.takeIf { it.isNotBlank() }?.let { Text(it, color = Watchd.Faint, fontSize = 11.sp) }
            }
        }
    }
}
