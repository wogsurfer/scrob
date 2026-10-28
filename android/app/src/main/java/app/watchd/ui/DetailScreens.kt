package app.watchd.ui

import kotlinx.serialization.Serializable
import kotlin.math.roundToInt
import androidx.compose.material.icons.filled.StarBorder
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.BookmarkBorder
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.CollectionPart
import app.watchd.data.Episode
import app.watchd.data.NextUpItem
import app.watchd.data.Person
import app.watchd.data.Show
import app.watchd.data.WatchTarget
import app.watchd.data.WhereToWatch
import androidx.compose.material.icons.filled.PlayArrow
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

private val longDate = DateTimeFormatter.ofPattern("d MMM yyyy")

private fun plural(n: Int, word: String) = "$n $word${if (n == 1) "" else "s"}"

// ------------------------------------------------------------------ film

@Composable
fun MovieScreen(tmdbId: Int, onBack: () -> Unit, openMovie: (Int) -> Unit, openPerson: (Int) -> Unit) {
    val (state, reload) = rememberLoad(tmdbId, saved("movie-$tmdbId")) { movie(tmdbId) }
    val awards = rememberAwards(tmdbId) { filmAwards(tmdbId).awards }
    val soundtrack = rememberSoundtrack("movie", tmdbId)
    val app = LocalApp.current
    val haptics = LocalHapticFeedback.current
    val list = rememberLazyListState()
    LoadContent(state, reload) { movie ->
        var watched by remember(movie) { mutableStateOf(movie.watched) }
        var plays by remember(movie) { mutableStateOf(movie.playCount) }
        var inWatchlist by remember(movie) { mutableStateOf(movie.inWatchlist) }
        DetailScaffold(movie.title, list, onBack) {
            item {
                DetailHeader(
                    backdrop = movie.backdropPath, poster = movie.posterPath, title = movie.title,
                    facts = listOfNotNull(year(movie.releaseDate), movie.runtime?.takeIf { it > 0 }?.let { "${it / 60}h ${it % 60}m" }, movie.ageRating),
                )
            }
            item { RatingsRow(movie.tmdbId, "movie", movie.imdbRating, movie.tmdbRating, movie.userRating) }
            item {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    WatchedButton(watched, if (watched) (if (plays > 1) "Watched · ${plays}×" else "Watched") else "Mark watched") {
                        // Once watched, the button opens the plays (add a rewatch,
                        // remove one) rather than wiping the history in one tap.
                        if (watched) {
                            app.openWatchSheet(WatchTarget(movie.tmdbId, "movie", movie.title, runtime = movie.runtime), reload)
                            return@WatchedButton
                        }
                        haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                        watched = true
                        plays += 1
                        app.act(
                            "Marked watched",
                            action = { markWatched(movie.tmdbId, "movie") },
                            onFail = { watched = false; plays -= 1 },
                            undo = { unwatch(movie.tmdbId, "movie") },
                            onUndo = { watched = false; plays = (plays - 1).coerceAtLeast(0) },
                        )
                    }
                    FilledTonalButton(
                        onClick = { app.openWatchSheet(WatchTarget(movie.tmdbId, "movie", movie.title, runtime = movie.runtime), reload) },
                        colors = ButtonDefaults.filledTonalButtonColors(containerColor = Watchd.Surface, contentColor = Color.White),
                    ) {
                        Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Check in")
                    }
                    IconButton(
                        onClick = {
                        haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                        val was = inWatchlist
                        inWatchlist = !was
                        app.act(
                            if (was) "Removed from watchlist" else "Added to watchlist",
                            action = { if (was) removeFromWatchlist(movie.tmdbId) else addToWatchlist(movie.tmdbId) },
                            onFail = { inWatchlist = was },
                            undo = { if (was) addToWatchlist(movie.tmdbId) else removeFromWatchlist(movie.tmdbId) },
                            onUndo = { inWatchlist = was },
                        )
                        },
                        colors = IconButtonDefaults.iconButtonColors(containerColor = Watchd.Surface),
                    ) {
                        Icon(
                            if (inWatchlist) Icons.Default.Bookmark else Icons.Default.BookmarkBorder,
                            contentDescription = if (inWatchlist) "Remove from watchlist" else "Add to watchlist",
                            tint = if (inWatchlist) Watchd.Red else Color.White,
                        )
                    }
                }
            }
            movie.watchHistory.mapNotNull { it.watchedAt }.maxOrNull()?.let { last ->
                item { Text("Last watched ${formatDate(last)}", color = Watchd.Faint, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 16.dp)) }
            }
            if (movie.discs.isNotEmpty()) item { OnDisc(movie.discs) }
            item { Overview(movie.tagline, movie.overview, movie.genres) }
            val directors = movie.crew.filter { it.job == "Director" }.map { it.name }.distinct()
            val writers = movie.crew.filter { it.job in setOf("Screenplay", "Writer") }.map { it.name }.distinct()
            if (directors.isNotEmpty() || writers.isNotEmpty()) {
                item {
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                        if (directors.isNotEmpty()) Credit("Directed by", directors.take(2).joinToString(", "), Modifier.weight(1f))
                        if (writers.isNotEmpty()) Credit("Written by", writers.take(2).joinToString(", "), Modifier.weight(1f))
                    }
                }
            }
            if (movie.whereToWatch.isNotEmpty()) item { WhereToWatchRow(movie.whereToWatch) }
            if (movie.cast.isNotEmpty()) {
                item { CastSection(movie.cast, openPerson) }
            }
            movie.collection?.takeIf { it.parts.size > 1 }?.let { collection ->
                item { SectionTitle(collection.name ?: "Collection", Modifier.padding(top = 8.dp)) }
                item { CollectionRow(collection.parts, current = movie.tmdbId, openMovie = openMovie) }
            }
            item { AwardsSection(awards) }
            item { SoundtrackSection(soundtrack) }
        }
    }
}

// ------------------------------------------------------------------ show

@Serializable
private data class ShowPage(val show: Show, val next: NextUpItem?)

@Composable
fun ShowScreen(tmdbId: Int, onBack: () -> Unit, openSeason: (Int, Int) -> Unit, openPerson: (Int) -> Unit) {
    val (state, reload) = rememberLoad(tmdbId, saved<ShowPage>("show-$tmdbId")) {
        coroutineScope {
            val show = async { show(tmdbId) }
            val next = async { runCatching { nextUp(limit = 500).nextUp.firstOrNull { it.showTmdbId == tmdbId } }.getOrNull() }
            ShowPage(show.await(), next.await())
        }
    }
    val app = LocalApp.current
    val haptics = LocalHapticFeedback.current
    val list = rememberLazyListState()
    val soundtrack = rememberSoundtrack("tv", tmdbId)
    val tvdbId = (state as? Load.Ready)?.value?.show?.tvdbId
    val awards = rememberAwards(tvdbId ?: 0) { tvdbId?.let { showAwards(it, tmdbId).awards } ?: emptyList() }
    LoadContent(state, reload) { page ->
        val show = page.show
        // Seasons ticked or unticked here, ahead of the next reload.
        val seasonWatched = remember(show) { mutableStateMapOf<Int, Boolean>() }
        DetailScaffold(show.title, list, onBack) {
            item {
                DetailHeader(
                    backdrop = show.backdropPath, poster = show.posterPath, title = show.title,
                    facts = listOfNotNull(
                        year(show.firstAirDate)?.let { start -> if (show.status == "Ended" || show.status == "Canceled") "$start–${year(show.lastAirDate) ?: ""}" else start },
                        show.networks.firstOrNull()?.name, show.ageRating,
                    ),
                )
            }
            item { RatingsRow(show.tmdbId, "series", show.imdbRating, show.tmdbRating, show.userRating) }
            if (show.discs.isNotEmpty()) item { OnDisc(show.discs) }
            if (show.watchPct in 1..99) {
                item {
                    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                        Text("${show.watchPct}% watched", color = Watchd.Muted, fontSize = 13.sp)
                        Progress(show.watchPct)
                    }
                }
            }
            page.next?.let { next ->
                item {
                    NextEpisodeCard(
                        next,
                        onOpen = { next.seasonNumber?.let { openSeason(show.tmdbId, it) } },
                        onLongPress = {
                            app.openWatchSheet(WatchTarget(next.tmdbId, "episode", next.title, show.tmdbId, next.seasonNumber, next.episodeNumber), reload)
                        },
                    ) {
                        haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                        app.act(
                            "Marked ${episodeCode(next.seasonNumber, next.episodeNumber)} watched",
                            action = { markWatched(next.tmdbId, "episode") },
                            onFail = {},
                            undo = { unwatch(next.tmdbId, "episode") },
                            onDone = reload,
                        )
                    }
                }
            }
            item { Overview(show.tagline, show.overview, show.genres) }
            if (show.createdBy.isNotEmpty()) {
                item { Credit("Created by", show.createdBy.joinToString(", ") { it.name }, Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) }
            }
            if (show.whereToWatch.isNotEmpty()) item { WhereToWatchRow(show.whereToWatch) }
            item { SectionTitle("Seasons", Modifier.padding(top = 8.dp)) }
            items(show.seasonsMeta.sortedBy { if (it.seasonNumber == 0) Int.MAX_VALUE else it.seasonNumber }, key = { it.seasonNumber }) { season ->
                val seasonState = show.seasonStates[season.seasonNumber.toString()]
                val upcoming = season.episodeCount == 0 || runCatching { LocalDate.parse(season.airDate).isAfter(LocalDate.now()) }.getOrDefault(false)
                val watched = seasonWatched[season.seasonNumber] ?: (seasonState?.watched == true)
                Row(
                    Modifier.fillMaxWidth().clickable { openSeason(show.tmdbId, season.seasonNumber) }.padding(start = 16.dp, top = 8.dp, bottom = 8.dp, end = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Poster(season.posterPath ?: show.posterPath, Modifier.width(56.dp))
                    Column(Modifier.weight(1f)) {
                        Text(season.name ?: "Season ${season.seasonNumber}", fontWeight = FontWeight.Bold)
                        Text(
                            if (upcoming) listOfNotNull("Coming soon", season.airDate?.let { formatDate(it) }.takeIf { season.airDate != null }).joinToString(" · ")
                            else listOfNotNull(year(season.airDate), plural(season.episodeCount, "episode")).joinToString(" · "),
                            color = if (upcoming) Watchd.Red else Watchd.Muted, fontSize = 13.sp,
                        )
                        val pct = if (watched) 100 else seasonState?.watchPct ?: 0
                        if (pct > 0) Progress(pct)
                    }
                    if (!upcoming) {
                        WatchedTick(watched) {
                            haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                            seasonWatched[season.seasonNumber] = !watched
                            val name = season.name ?: "Season ${season.seasonNumber}"
                            app.act(
                                if (watched) "$name unmarked" else "$name marked watched",
                                action = { if (watched) unwatchSeason(show.tmdbId, season.seasonNumber) else markSeasonWatched(show.tmdbId, season.seasonNumber) },
                                onFail = { seasonWatched[season.seasonNumber] = watched },
                                undo = { if (watched) markSeasonWatched(show.tmdbId, season.seasonNumber) else unwatchSeason(show.tmdbId, season.seasonNumber) },
                                onUndo = { seasonWatched[season.seasonNumber] = watched },
                            )
                        }
                    }
                }
            }
            if (show.cast.isNotEmpty()) {
                item { CastSection(show.cast, openPerson) }
            }
            item { AwardsSection(awards) }
            item { SoundtrackSection(soundtrack) }
        }
    }
}

@Composable
private fun NextEpisodeCard(next: NextUpItem, onOpen: () -> Unit, onLongPress: () -> Unit, onWatched: () -> Unit) {
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text("UP NEXT", style = MaterialTheme.typography.labelSmall, color = Watchd.Red, modifier = Modifier.padding(bottom = 8.dp))
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Watchd.Surface).clickable(onClick = onOpen).padding(10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            AsyncImage(
                model = next.posterPath ?: next.showBackdropPath, contentDescription = null, contentScale = ContentScale.Crop,
                modifier = Modifier.width(120.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(8.dp)).background(Watchd.SurfaceHigh),
            )
            Column(Modifier.weight(1f)) {
                Text(episodeCode(next.seasonNumber, next.episodeNumber), color = Watchd.Red, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                Text(next.title.orEmpty(), fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text("${next.showEpisodesWatched} of ${next.showEpisodesTotal} watched", color = Watchd.Faint, fontSize = 12.sp)
            }
            WatchButton(false, onTap = onWatched, onLongPress = onLongPress)
        }
    }
}

// ------------------------------------------------------------------ season

@Composable
fun SeasonScreen(showTmdbId: Int, seasonNumber: Int, onBack: () -> Unit) {
    val (state, reload) = rememberLoad(showTmdbId to seasonNumber, saved("season-$showTmdbId-$seasonNumber")) { season(showTmdbId, seasonNumber) }
    val app = LocalApp.current
    val haptics = LocalHapticFeedback.current
    val list = rememberLazyListState()
    LoadContent(state, reload) { season ->
        val watched = remember(season) { mutableStateMapOf<Int, Boolean>().apply { season.episodes.forEach { put(it.tmdbId, it.watched) } } }
        val aired = season.episodes.filter { !isFuture(it.airDate) }
        val done = aired.count { watched[it.tmdbId] == true }
        val title = season.name ?: "Season $seasonNumber"
        DetailScaffold(title, list, onBack, header = false) {
            item {
                Row(
                    Modifier.statusBarsPadding().padding(start = 16.dp, end = 16.dp, top = 64.dp, bottom = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                    verticalAlignment = Alignment.Bottom,
                ) {
                    Poster(season.posterPath, Modifier.width(96.dp))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(title, style = MaterialTheme.typography.headlineSmall)
                        Text("$done of ${aired.size} watched", color = Watchd.Muted, fontSize = 13.sp)
                        if (aired.isNotEmpty()) Progress(done * 100 / aired.size)
                    }
                }
            }
            if (aired.isNotEmpty()) {
                item {
                    val all = done == aired.size
                    WatchedButton(all, if (all) "Season watched" else "Mark season watched", Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                        haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                        val before = aired.associate { it.tmdbId to (watched[it.tmdbId] == true) }
                        aired.forEach { watched[it.tmdbId] = !all }
                        app.act(
                            if (all) "$title unmarked" else "$title marked watched",
                            action = { if (all) unwatchSeason(showTmdbId, seasonNumber) else markSeasonWatched(showTmdbId, seasonNumber) },
                            onFail = { watched.putAll(before) },
                            undo = { if (all) markSeasonWatched(showTmdbId, seasonNumber) else unwatchSeason(showTmdbId, seasonNumber) },
                            onUndo = { watched.putAll(before) },
                        )
                    }
                }
            }
            if (!season.overview.isNullOrBlank()) {
                item { Text(season.overview, color = Watchd.Muted, modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) }
            }
            items(season.episodes, key = { it.tmdbId }) { episode ->
                val target = WatchTarget(episode.tmdbId, "episode", episode.title, showTmdbId, seasonNumber, episode.episodeNumber, episode.runtime)
                EpisodeRow(episode, watched[episode.tmdbId] == true, onLongPress = { app.openWatchSheet(target, reload) }) {
                    haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                    val was = watched[episode.tmdbId] == true
                    watched[episode.tmdbId] = !was
                    app.act(
                        if (was) "Unmarked ${episodeCode(seasonNumber, episode.episodeNumber)}" else "Marked ${episodeCode(seasonNumber, episode.episodeNumber)} watched",
                        action = { if (was) unwatch(episode.tmdbId, "episode") else markWatched(episode.tmdbId, "episode") },
                        onFail = { watched[episode.tmdbId] = was },
                        undo = { if (was) markWatched(episode.tmdbId, "episode") else unwatch(episode.tmdbId, "episode") },
                        onUndo = { watched[episode.tmdbId] = was },
                    )
                }
            }
        }
    }
}

@Composable
private fun EpisodeRow(episode: Episode, watched: Boolean, onLongPress: () -> Unit, onToggle: () -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val future = isFuture(episode.airDate)
    Column(Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(start = 16.dp, end = 4.dp, top = 10.dp, bottom = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            AsyncImage(
                model = episode.posterPath, contentDescription = null, contentScale = ContentScale.Crop,
                modifier = Modifier.width(128.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(8.dp)).background(Watchd.Surface),
            )
            Column(Modifier.weight(1f)) {
                Text("Episode ${episode.episodeNumber}", color = Watchd.Red, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                Text(episode.title.orEmpty(), fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(
                    listOfNotNull(episode.airDate?.let { formatDate(it) }, episode.runtime?.let { "$it min" }).joinToString(" · "),
                    color = Watchd.Faint, fontSize = 12.sp,
                )
                EpisodeBadge(episode.badge, Modifier.padding(top = 3.dp))
            }
            if (!future) WatchButton(watched, onTap = onToggle, onLongPress = onLongPress)
        }
        if (expanded && !episode.overview.isNullOrBlank()) {
            Text(episode.overview, color = Watchd.Muted, modifier = Modifier.padding(top = 8.dp, end = 12.dp))
        }
    }
}

// ------------------------------------------------------------------ shared pieces

/**
 * A detail page: the list under a top bar that is clear over the backdrop
 * and fills in, with the title, once the page scrolls.
 */
@Composable
internal fun DetailScaffold(title: String, list: LazyListState, onBack: () -> Unit, header: Boolean = true, content: LazyListScope.() -> Unit) {
    val solid by remember {
        derivedStateOf { if (!header || list.firstVisibleItemIndex > 0) 1f else (list.firstVisibleItemScrollOffset / 500f).coerceIn(0f, 1f) }
    }
    Box(Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), state = list, contentPadding = PaddingValues(bottom = 32.dp), content = content)
        Row(
            Modifier.fillMaxWidth().background(Watchd.Background.copy(alpha = solid)).statusBarsPadding().height(56.dp).padding(horizontal = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(
                onClick = onBack,
                colors = IconButtonDefaults.iconButtonColors(containerColor = Color.Black.copy(alpha = 0.5f * (1 - solid))),
            ) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Color.White) }
            Text(
                title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(start = 8.dp).alpha(if (header) solid else 1f),
            )
        }
    }
}

@Composable
internal fun DetailHeader(backdrop: String?, poster: String?, title: String, facts: List<String>, cover: Boolean = false) {
    // The poster overlaps the bottom of the backdrop, which fades into the page.
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val backdropHeight = maxWidth * 10 / 16
        AsyncImage(
            model = backdrop ?: poster, contentDescription = null, contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxWidth().height(backdropHeight).background(Watchd.Surface),
        )
        Box(
            Modifier.fillMaxWidth().height(backdropHeight)
                .background(Brush.verticalGradient(0f to Color.Black.copy(alpha = 0.45f), 0.4f to Color.Transparent, 1f to Watchd.Background)),
        )
        Row(
            Modifier.padding(start = 16.dp, end = 16.dp, top = backdropHeight - 64.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            // A disc's case scan keeps its own shape; posters are 2:3.
            if (cover) Cover(poster, Modifier.width(110.dp)) else Poster(poster, Modifier.width(104.dp))
            Column(Modifier.weight(1f).padding(bottom = 4.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(title, style = MaterialTheme.typography.headlineSmall)
                if (facts.isNotEmpty()) Text(facts.joinToString(" · "), color = Watchd.Muted, fontSize = 13.sp)
            }
        }
    }
}

/** IMDb, TMDB and your own rating, in the site's pill. */
@Composable
private fun RatingsRow(tmdbId: Int, mediaType: String, imdb: Double?, tmdb: Double?, mine: Double?) {
    val app = LocalApp.current
    // Shown at once; put back if the server says no.
    var rating by remember(tmdbId, mine) { mutableStateOf(mine?.roundToInt()) }
    RatingsPill(tmdb, imdb, rating?.toDouble(), Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp))
    RateStars(rating) { stars ->
        val before = rating
        rating = stars
        app.act(
            if (stars == null) "Rating cleared" else "Rated $stars/10",
            action = { if (stars == null) unrate(tmdbId, mediaType) else rate(tmdbId, mediaType, stars) },
            onFail = { rating = before },
        )
    }
}

/** Ten stars, as on the site: tap one to rate, tap your rating again to clear it. */
@Composable
private fun RateStars(rating: Int?, onRate: (Int?) -> Unit) {
    val haptics = LocalHapticFeedback.current
    Row(Modifier.padding(start = 12.dp, end = 16.dp, top = 6.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        (1..10).forEach { n ->
            val on = rating != null && n <= rating
            Icon(
                if (on) Icons.Default.Star else Icons.Default.StarBorder,
                contentDescription = "Rate $n out of 10",
                tint = if (on) Watchd.Red else Watchd.Faint,
                modifier = Modifier.size(30.dp).clip(CircleShape).clickable {
                    haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                    onRate(if (rating == n) null else n)
                }.padding(3.dp),
            )
        }
        Text(rating?.let { "$it/10" } ?: "Rate", color = if (rating != null) Watchd.Red else Watchd.Muted, fontWeight = FontWeight.Bold, fontSize = 13.sp, modifier = Modifier.padding(start = 6.dp))
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
internal fun Credit(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier) {
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = Watchd.Faint)
        Text(value, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun WhereToWatchRow(services: List<WhereToWatch>) {
    Column(Modifier.padding(vertical = 8.dp)) {
        Text("WHERE TO WATCH", style = MaterialTheme.typography.labelSmall, color = Watchd.Faint, modifier = Modifier.padding(horizontal = 16.dp))
        LazyRow(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            items(services.distinctBy { it.name }) { service ->
                Row(
                    Modifier.clip(RoundedCornerShape(10.dp)).background(Watchd.Surface).padding(end = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    AsyncImage(service.logo, contentDescription = null, modifier = Modifier.size(36.dp).clip(RoundedCornerShape(10.dp)))
                    Text(service.name, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                }
            }
        }
    }
}

/** "Mark Scout · 19 eps": the role, and for a show how much of it they're in. */
private fun role(person: Person) = listOfNotNull(
    person.character?.takeIf { it.isNotBlank() },
    person.episodeCount?.takeIf { it > 0 }?.let { "$it ep${if (it == 1) "" else "s"}" },
).joinToString(" · ")

/** Cast heading with a See all that opens everyone, then the top-billed few. */
@Composable
private fun CastSection(cast: List<Person>, openPerson: (Int) -> Unit) {
    var showAll by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        SectionTitle("Cast", Modifier.weight(1f))
        if (cast.size > 5) {
            TextButton(onClick = { showAll = true }, modifier = Modifier.padding(end = 8.dp)) {
                Text("See all ${cast.size}", color = Watchd.Red, fontWeight = FontWeight.Bold)
            }
        }
    }
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        items(cast.take(12)) { person ->
            Column(Modifier.width(76.dp).clickable(enabled = person.tmdbId != null) { person.tmdbId?.let(openPerson) }) {
                AsyncImage(
                    model = person.profilePath, contentDescription = null, contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxWidth().aspectRatio(3f / 4f).clip(RoundedCornerShape(8.dp)).background(Watchd.Surface),
                )
                Text(person.name, fontWeight = FontWeight.Bold, fontSize = 12.sp, lineHeight = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
                Text(person.character.orEmpty(), color = Watchd.Muted, fontSize = 11.sp, lineHeight = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
    if (showAll) CastSheet(cast, openPerson = { showAll = false; openPerson(it) }) { showAll = false }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CastSheet(cast: List<Person>, openPerson: (Int) -> Unit, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Watchd.Surface, contentColor = Watchd.Text) {
        Text("Cast", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(start = 20.dp, bottom = 8.dp))
        LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
            items(cast) { person ->
                Row(
                    Modifier.fillMaxWidth().clickable(enabled = person.tmdbId != null) { person.tmdbId?.let(openPerson) }.padding(horizontal = 20.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    AsyncImage(
                        model = person.profilePath, contentDescription = null, contentScale = ContentScale.Crop,
                        modifier = Modifier.size(44.dp).clip(CircleShape).background(Watchd.SurfaceHigh),
                    )
                    Column(Modifier.weight(1f)) {
                        Text(person.name, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        role(person).takeIf { it.isNotEmpty() }?.let { Text(it, color = Watchd.Muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis) }
                    }
                }
            }
        }
    }
}

@Composable
private fun CollectionRow(parts: List<CollectionPart>, current: Int, openMovie: (Int) -> Unit) {
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        items(parts.sortedBy { it.releaseDate ?: "9999" }, key = { it.tmdbId }) { part ->
            Column(Modifier.width(110.dp).clickable(enabled = part.tmdbId != current) { openMovie(part.tmdbId) }) {
                Box {
                    Poster(part.posterPath, Modifier.fillMaxWidth().alpha(if (part.tmdbId == current) 0.45f else 1f))
                    if (part.watched) WatchedMark(true, Modifier.align(Alignment.TopEnd).padding(6.dp).size(24.dp))
                }
                Text(part.title.orEmpty(), fontWeight = FontWeight.Bold, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
                year(part.releaseDate)?.let { Text(it, color = Watchd.Faint, fontSize = 12.sp) }
            }
        }
    }
}

@Composable
private fun WatchedTick(watched: Boolean, onClick: () -> Unit) {
    IconButton(onClick = onClick, modifier = Modifier.size(52.dp)) { WatchedMark(watched, Modifier.size(32.dp)) }
}

/** Mark watched / Watched, with the W: red once watched. */
@Composable
private fun WatchedButton(watched: Boolean, label: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    FilledTonalButton(
        onClick = onClick,
        modifier = modifier,
        colors = ButtonDefaults.filledTonalButtonColors(containerColor = Watchd.Surface, contentColor = Color.White),
    ) {
        WatchedMark(watched, Modifier.size(20.dp))
        Spacer(Modifier.width(8.dp))
        Text(label)
    }
}

@Composable
private fun ToggleButton(active: Boolean, label: String, icon: ImageVector, modifier: Modifier = Modifier, onClick: () -> Unit) {
    FilledTonalButton(
        onClick = onClick,
        modifier = modifier,
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

private fun isFuture(date: String?) =
    runCatching { LocalDate.parse(date).isAfter(LocalDate.now()) }.getOrDefault(false)

/** "2024-03-12" or "2024-03-12T20:15:00" as "12 Mar 2024". */
private fun formatDate(value: String): String = runCatching {
    if (value.length > 10) LocalDateTime.parse(value.take(19)).toLocalDate().format(longDate) else LocalDate.parse(value).format(longDate)
}.getOrDefault(value)
