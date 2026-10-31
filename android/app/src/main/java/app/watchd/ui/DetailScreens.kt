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
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.runtime.produceState
import app.watchd.data.StripEpisode
import app.watchd.data.EpisodeStrip
import app.watchd.data.Disc
import kotlinx.coroutines.launch
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.material3.AlertDialog
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
fun MovieScreen(tmdbId: Int, onBack: () -> Unit, openMovie: (Int) -> Unit, openPerson: (Int) -> Unit, openDisc: (Int) -> Unit) {
    val (state, reload) = rememberLoad(tmdbId, saved("movie-$tmdbId")) { movie(tmdbId) }
    val awards = rememberAwards(tmdbId) { filmAwards(tmdbId).awards }
    val soundtrack = rememberSoundtrack("movie", tmdbId)
    val app = LocalApp.current
    val list = rememberLazyListState()
    LoadContent(state, reload) { movie ->
        var inLists by remember(movie) { mutableStateOf(movie.inLists) }
        var listsOpen by remember { mutableStateOf(false) }
        val rate = rememberRating(movie.tmdbId, "movie", movie.userRating)
        val openDiscs = rememberDiscOpener(openDisc)
        val target = WatchTarget(movie.tmdbId, "movie", movie.title, runtime = movie.runtime)
        DetailScaffold(movie.title, list, onBack) {
            item {
                DetailHeader(
                    backdrop = movie.backdropPath, poster = movie.posterPath, title = movie.title,
                    facts = listOfNotNull(year(movie.releaseDate), movie.runtime?.takeIf { it > 0 }?.let { "${it / 60}h ${it % 60}m" }, movie.ageRating),
                )
            }
            item { RatingsPill(movie.tmdbRating, movie.imdbRating, rate.value, Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 4.dp), onRate = rate.open) }
            val released = listOfNotNull(
                movie.releaseDate?.let { "Released ${formatDate(it)}" },
                movie.productionCountries.mapNotNull { it.name }.takeIf { it.isNotEmpty() }?.joinToString(" • "),
            )
            if (released.isNotEmpty()) {
                item { Text(released.joinToString("   "), color = Watchd.Muted, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) }
            }
            item {
                ActionStack(
                    listOfNotNull(
                        // As on the site, Watched opens the plays: add one (a rewatch, or a check-in) or take one off.
                        ActionItem(
                            "Watched", Tone.Red, movie.watched, value = movie.playCount.takeIf { it > 1 }?.let { "$it×" },
                            icon = watchedIcon(movie.watched),
                        ) { app.openWatchSheet(target, reload) },
                        ActionItem("Lists", Tone.Sky, inLists.isNotEmpty(), icon = ListsIcon) { listsOpen = true },
                        ActionItem("Collection", Tone.Purple, movie.inLibrary, icon = CollectionIcon) { openDiscs(movie.discs) },
                        requestItem("movie", movie.tmdbId, movie.requestEnabled, movie.isMonitored, movie.requestStatus, done = movie.inLibrary),
                    ),
                )
            }
            movie.library?.let { item { LibraryTags(it) } }
            if (movie.discs.isNotEmpty()) item { OnDiscChips(movie.discs, openDisc = openDisc) }
            if (movie.watchHistory.isNotEmpty()) item { WatchHistoryList(movie.watchHistory) }
            item { Overview(movie.tagline, movie.overview, movie.genres) }
            if (movie.whereToWatch.isNotEmpty()) item { WhereToWatchRow(movie.whereToWatch) }
            movie.collection?.takeIf { it.parts.size > 1 }?.let { collection ->
                item { SectionTitle(collection.name ?: "Collection", Modifier.padding(top = 8.dp)) }
                item { CollectionRow(collection.parts, current = movie.tmdbId, openMovie = openMovie) }
            }
            item { AwardsSection(awards) }
            item { CastTabs(movie.cast, emptyList(), openPerson, castTitle = "Top Cast") }
            item { CrewSection(movie.crew, openPerson) }
            item { SoundtrackSection(soundtrack) }
        }
        if (listsOpen) ListsSheet(movie.tmdbId, "movie", movie.title, inLists, onChanged = { inLists = it }) { listsOpen = false }
    }
}

// ------------------------------------------------------------------ show

@Serializable
private data class ShowPage(val show: Show)

@Composable
fun ShowScreen(
    tmdbId: Int, onBack: () -> Unit, openSeason: (Int, Int) -> Unit, openPerson: (Int) -> Unit, openDisc: (Int) -> Unit,
    openEpisode: (Int, Int, Int) -> Unit = { _, _, _ -> },
) {
    val (state, reload) = rememberLoad(tmdbId, saved<ShowPage>("show-$tmdbId")) {
        ShowPage(show(tmdbId))
    }
    val app = LocalApp.current
    val haptics = LocalHapticFeedback.current
    val list = rememberLazyListState()
    val soundtrack = rememberSoundtrack("tv", tmdbId)
    val tvdbId = (state as? Load.Ready)?.value?.show?.tvdbId
    val awards = rememberAwards(tvdbId ?: 0) { tvdbId?.let { showAwards(it, tmdbId).awards } ?: emptyList() }
    // Loaded on its own so the page shows first.
    val strip by produceState<EpisodeStrip?>(null, tmdbId) { value = runCatching { app.api.episodeStrip(tmdbId) }.getOrNull() }
    LoadContent(state, reload) { page ->
        val show = page.show
        // Seasons ticked or unticked here, ahead of the next reload.
        val seasonWatched = remember(show) { mutableStateMapOf<Int, Boolean>() }
        var inLists by remember(show) { mutableStateOf(show.inLists) }
        var listsOpen by remember { mutableStateOf(false) }
        val rate = rememberRating(show.tmdbId, "series", show.userRating)
        val openDiscs = rememberDiscOpener(openDisc, show.title)
        val confirm = rememberConfirm()
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
            item { RatingsPill(show.tmdbRating, show.imdbRating, rate.value, Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 4.dp), onRate = rate.open) }
            item {
                val all = show.watchPct == 100
                ActionStack(
                    listOfNotNull(
                        ActionItem("Watched", Tone.Red, all, value = "${show.watchPct}%", icon = watchedIcon(all)) {
                            if (all) {
                                confirm("Remove all watch history?", "This will remove all watch events for every episode of this show.") {
                                    app.act("${show.title} unmarked", action = { unwatchShow(show.tmdbId) }, onFail = {}, onDone = reload)
                                }
                            } else {
                                confirm("Mark all episodes as watched?", "This will add a watch event for every episode in your library for this show.") {
                                    app.act("${show.title} marked watched", action = { markShowWatched(show.tmdbId) }, onFail = {}, onDone = reload)
                                }
                            }
                        },
                        ActionItem("Lists", Tone.Sky, inLists.isNotEmpty(), icon = ListsIcon) { listsOpen = true },
                        ActionItem("Collection", Tone.Purple, show.collectionPct > 0, value = "${show.collectionPct}%", icon = CollectionIcon) { openDiscs(show.discs) },
                        requestItem("series", show.tmdbId, show.requestEnabled, show.isMonitored, show.requestStatus, done = show.collectionPct == 100),
                    ),
                )
            }
            if (show.discs.isNotEmpty()) item { OnDiscChips(show.discs, show.title, openDisc) }
            strip?.let { s ->
                val latest = show.seasonsMeta.map { it.seasonNumber }.filter { it > 0 }.maxOrNull()
                item { EpisodeStripRow(s, show.tmdbId, openEpisode, openAll = latest?.let { n -> { openSeason(show.tmdbId, n) } }) }
            }
            item { Overview(show.tagline, show.overview, show.genres) }
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
            item { CastTabs(show.cast, show.guestStars, openPerson, withEpisodes = true) }
            item { CrewSection(show.crew, openPerson, withEpisodes = true) }
            item { AwardsSection(awards) }
            item { SoundtrackSection(soundtrack) }
        }
        if (listsOpen) ListsSheet(show.tmdbId, "series", show.title, inLists, onChanged = { inLists = it }) { listsOpen = false }
    }
}

// ------------------------------------------------------------------ season

@Composable
fun SeasonScreen(
    showTmdbId: Int, seasonNumber: Int, onBack: () -> Unit, openSeason: (Int, Int) -> Unit, openDisc: (Int) -> Unit,
    openEpisode: (Int, Int, Int) -> Unit = { _, _, _ -> },
) {
    val (state, reload) = rememberLoad(showTmdbId to seasonNumber, saved("season-$showTmdbId-$seasonNumber")) { season(showTmdbId, seasonNumber) }
    val app = LocalApp.current
    val haptics = LocalHapticFeedback.current
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()
    LoadContent(state, reload) { season ->
        val watched = remember(season) { mutableStateMapOf<Int, Boolean>().apply { season.episodes.forEach { put(it.tmdbId, it.watched) } } }
        val aired = season.episodes.filter { !isFuture(it.airDate) }
        val done = aired.count { watched[it.tmdbId] == true }
        val title = season.name ?: "Season $seasonNumber"
        val openDiscs = rememberDiscOpener(openDisc, season.show?.title)
        val confirm = rememberConfirm()
        // The show's seasons, specials aside, to step between.
        val numbers = season.show?.seasonsMeta?.map { it.seasonNumber }?.filter { it > 0 }?.sorted().orEmpty()
        val at = numbers.indexOf(seasonNumber)
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
            item {
                StepRow("S", numbers.getOrNull(at - 1).takeIf { at > 0 }, numbers.getOrNull(at + 1).takeIf { at >= 0 }) { openSeason(showTmdbId, it) }
            }
            item { RatingsPill(season.tmdbRating, season.imdbRating, season.seasonUserRating, Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) }
            item {
                val all = aired.isNotEmpty() && done == aired.size
                val pct = if (aired.isEmpty()) 0 else done * 100 / aired.size
                ActionStack(
                    listOf(
                        ActionItem("Watched", Tone.Red, all, value = "$pct%", enabled = aired.isNotEmpty(), icon = watchedIcon(all)) {
                            val (ask, detail) = if (all) "Mark season as unwatched?" to "This will remove all watch events for every episode in this season."
                            else "Mark season as watched?" to "This will add a watch event for every episode in your library for this season."
                            confirm(ask, detail) {
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
                        },
                        ActionItem("Collection", Tone.Purple, season.seasonCollectionPct > 0, value = "${season.seasonCollectionPct}%", icon = CollectionIcon) {
                            // Your disc of this season, else the show's discs.
                            season.seasonDiscId?.let(openDisc) ?: scope.launch {
                                openDiscs(runCatching { app.api.show(showTmdbId).discs }.getOrDefault(emptyList()))
                            }
                        },
                    ),
                )
            }
            if (!season.overview.isNullOrBlank()) {
                item { Text(season.overview, color = Watchd.Muted, modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) }
            }
            items(season.episodes, key = { it.tmdbId }) { episode ->
                val target = WatchTarget(episode.tmdbId, "episode", episode.title, showTmdbId, seasonNumber, episode.episodeNumber, episode.runtime)
                EpisodeRow(episode, watched[episode.tmdbId] == true, onOpen = { openEpisode(showTmdbId, seasonNumber, episode.episodeNumber) }, onLongPress = { app.openWatchSheet(target, reload) }) {
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

/**
 * One episode, as the site's episode page: its still, the show and season it
 * belongs to (tap for them), the step to the episodes either side, ratings,
 * the site's buttons, the story, and its cast and guest stars.
 */
@Composable
fun EpisodeScreen(
    showTmdbId: Int, seasonNumber: Int, episodeNumber: Int, onBack: () -> Unit,
    openShow: (Int) -> Unit, openSeason: (Int, Int) -> Unit, openEpisode: (Int, Int, Int) -> Unit,
    openPerson: (Int) -> Unit, openDisc: (Int) -> Unit,
) {
    val (state, reload) = rememberLoad(Triple(showTmdbId, seasonNumber, episodeNumber), saved("episode-$showTmdbId-$seasonNumber-$episodeNumber")) {
        episode(showTmdbId, seasonNumber, episodeNumber)
    }
    val app = LocalApp.current
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()
    LoadContent(state, reload) { ep ->
        var inLists by remember(ep) { mutableStateOf(ep.inLists) }
        var listsOpen by remember { mutableStateOf(false) }
        val openDiscs = rememberDiscOpener(openDisc, ep.show?.title)
        val code = episodeCode(ep.seasonNumber, ep.episodeNumber)
        val numbers = ep.episodes.map { it.episodeNumber }
        val at = numbers.indexOf(ep.episodeNumber)
        DetailScaffold(ep.title ?: code, list, onBack) {
            item {
                DetailHeader(
                    backdrop = ep.stillPath ?: ep.show?.backdropPath, poster = ep.show?.posterPath, title = ep.title ?: code,
                    facts = listOfNotNull(code, ep.airDate?.let { formatDate(it) }, ep.runtime?.takeIf { it > 0 }?.let { "$it min" }),
                )
            }
            item {
                // The show, then the season: each opens its page.
                Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        ep.show?.title.orEmpty(), color = Watchd.Text, fontWeight = FontWeight.Bold,
                        modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable { openShow(showTmdbId) }.padding(vertical = 6.dp, horizontal = 2.dp),
                    )
                    Text("  ·  ", color = Watchd.Faint)
                    Text(
                        "Season ${ep.seasonNumber}", color = Watchd.Red, fontWeight = FontWeight.Bold,
                        modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable { openSeason(showTmdbId, ep.seasonNumber) }.padding(vertical = 6.dp, horizontal = 2.dp),
                    )
                }
            }
            item {
                StepRow("E", numbers.getOrNull(at - 1).takeIf { at > 0 }, numbers.getOrNull(at + 1).takeIf { at >= 0 }) {
                    openEpisode(showTmdbId, ep.seasonNumber, it)
                }
            }
            ep.badge?.let { item { EpisodeBadge(it, Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) } }
            item { RatingsPill(ep.tmdbRating, ep.imdbRating, ep.userRating, Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) }
            ep.tmdbId?.let { id ->
                item {
                    ActionStack(
                        listOf(
                            ActionItem("Watched", Tone.Red, ep.watched, value = ep.playCount.takeIf { it > 1 }?.let { "$it×" }, icon = watchedIcon(ep.watched)) {
                                app.openWatchSheet(WatchTarget(id, "episode", ep.title, showTmdbId, ep.seasonNumber, ep.episodeNumber, ep.runtime), reload)
                            },
                            ActionItem("Lists", Tone.Sky, inLists.isNotEmpty(), icon = ListsIcon) { listsOpen = true },
                            ActionItem("Collection", Tone.Purple, ep.collectionPct > 0, icon = CollectionIcon) {
                                scope.launch { openDiscs(runCatching { app.api.show(showTmdbId).discs }.getOrDefault(emptyList())) }
                            },
                        ),
                    )
                }
            }
            item { Overview(null, ep.overview, emptyList()) }
            item { CastTabs(ep.cast, ep.guestStars, openPerson) }
            item { CrewSection(ep.crew, openPerson, title = "Episode Crew") }
        }
        if (listsOpen) ep.tmdbId?.let { id -> ListsSheet(id, "episode", ep.title ?: code, inLists, onChanged = { inLists = it }) { listsOpen = false } }
    }
}

/** Your rating and the dialog that sets it, shown at once and put back if the server says no. */
private class RatingControl(val value: Double?, val open: () -> Unit)

@Composable
private fun rememberRating(tmdbId: Int, mediaType: String, mine: Double?): RatingControl {
    val app = LocalApp.current
    var rating by remember(tmdbId, mine) { mutableStateOf(mine) }
    var picking by remember { mutableStateOf(false) }
    if (picking) {
        RateDialog(rating, onDismiss = { picking = false }, onPick = { value ->
            picking = false
            val before = rating
            rating = value
            app.act(
                if (value == null) "Rating cleared" else "Rated ${outOfTen(value)}/10",
                action = { if (value == null) unrate(tmdbId, mediaType) else rate(tmdbId, mediaType, value) },
                onFail = { rating = before },
            )
        })
    }
    return RatingControl(rating) { picking = true }
}

/**
 * The Collection button: your one disc opens, several come up to pick from,
 * and with none it says so (discs are added on the computer).
 */
@Composable
private fun rememberDiscOpener(openDisc: (Int) -> Unit, seriesTitle: String? = null): (List<Disc>) -> Unit {
    val app = LocalApp.current
    var sheet by remember { mutableStateOf<List<Disc>?>(null) }
    sheet?.let { discs -> DiscsSheet(discs, seriesTitle, openDisc = { sheet = null; openDisc(it) }) { sheet = null } }
    return { discs ->
        when {
            discs.size == 1 -> openDisc(discs.first().id)
            discs.size > 1 -> sheet = discs
            else -> app.act("Not in your collection", action = {}, onFail = {})
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DiscsSheet(discs: List<Disc>, seriesTitle: String?, openDisc: (Int) -> Unit, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Watchd.Background, contentColor = Watchd.Text) {
        Text("Your discs", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(start = 20.dp, bottom = 4.dp))
        OnDiscChips(discs, seriesTitle, openDisc)
        Spacer(Modifier.height(24.dp))
    }
}

/** Asks first, as the site does before marking a whole show or season. */
@Composable
private fun rememberConfirm(): (String, String, () -> Unit) -> Unit {
    var ask by remember { mutableStateOf<Triple<String, String, () -> Unit>?>(null) }
    ask?.let { (title, text, yes) ->
        AlertDialog(
            onDismissRequest = { ask = null }, containerColor = Watchd.Surface,
            title = { Text(title) }, text = { Text(text, color = Watchd.Muted) },
            confirmButton = { TextButton(onClick = { ask = null; yes() }) { Text("Confirm", color = Watchd.Red, fontWeight = FontWeight.Bold) } },
            dismissButton = { TextButton(onClick = { ask = null }) { Text("Cancel", color = Watchd.Muted) } },
        )
    }
    return { title, text, yes -> ask = Triple(title, text, yes) }
}

/** Radarr or Sonarr, as the site's last button: done once it's there or asked for. */
@Composable
private fun requestItem(mediaType: String, tmdbId: Int, enabled: Boolean, monitored: Boolean, status: String?, done: Boolean): ActionItem? {
    if (!enabled) return null
    val app = LocalApp.current
    var asked by remember(tmdbId) { mutableStateOf(false) }
    val sent = monitored || status != null || asked || done
    val service = if (mediaType == "movie") "Radarr" else "Sonarr"
    return ActionItem(service, Tone.Orange, sent, enabled = !sent, icon = RequestIcon) {
        asked = true
        app.act("Sent to $service", action = { requestMedia(mediaType, tmdbId) }, onFail = { asked = false })
    }
}

/**
 * An episode as Trakt lays them out: the still, with the W and IMDb rating
 * under it, then the code and title, date, runtime and any premiere or finale,
 * and the synopsis (tap it for all of it). The still or title opens the episode.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EpisodeRow(episode: Episode, watched: Boolean, onOpen: () -> Unit, onLongPress: () -> Unit, onToggle: () -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val future = isFuture(episode.airDate)
    Column(Modifier.fillMaxWidth().alpha(if (future) 0.65f else 1f).padding(horizontal = 16.dp, vertical = 12.dp)) {
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Watchd.Surface)) {
            AsyncImage(
                model = episode.posterPath, contentDescription = null, contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f).background(Watchd.SurfaceHigh).clickable(onClick = onOpen),
            )
            Row(Modifier.fillMaxWidth().padding(start = 4.dp, end = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                if (!future) WatchButton(watched, onTap = onToggle, onLongPress = onLongPress) else Spacer(Modifier.height(48.dp))
                Spacer(Modifier.weight(1f))
                ImdbBadge(episode.imdbRating)
            }
        }
        Text(
            buildAnnotatedString {
                withStyle(SpanStyle(color = Watchd.Red)) { append(episodeCode(episode.seasonNumber, episode.episodeNumber)) }
                append(" ${episode.title.orEmpty()}")
            },
            fontWeight = FontWeight.Black, fontSize = 19.sp, lineHeight = 23.sp,
            modifier = Modifier.padding(top = 12.dp).clickable(onClick = onOpen),
        )
        FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            episode.airDate?.let {
                Text(
                    (if (future) "Airs " else "") + formatDate(it), color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.ExtraBold,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Watchd.Red).padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
            episode.runtime?.takeIf { it > 0 }?.let {
                Text(
                    "${it}m", color = Watchd.Text, fontSize = 12.sp, fontWeight = FontWeight.ExtraBold,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Watchd.SurfaceHigh).padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
            EpisodeBadge(episode.badge)
        }
        if (!episode.overview.isNullOrBlank()) {
            Text(
                episode.overview, color = Watchd.Muted, maxLines = if (expanded) Int.MAX_VALUE else 3, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 10.dp).clickable { expanded = !expanded },
            )
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

/** Everyone in the cast, credited first; uncredited roles folded away at the end. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun CastSheet(cast: List<Person>, openPerson: (Int) -> Unit, onDismiss: () -> Unit) {
    val (credited, extras) = cast.partition { !(it.character ?: "").contains("uncredited", ignoreCase = true) }
    var showExtras by remember { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Watchd.Surface, contentColor = Watchd.Text) {
        Text("Full cast (${cast.size})", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(start = 20.dp, bottom = 8.dp))
        LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
            items(credited) { person -> CastSheetRow(person, openPerson) }
            if (extras.isNotEmpty()) {
                item {
                    TextButton(onClick = { showExtras = !showExtras }, modifier = Modifier.padding(start = 8.dp, top = 8.dp)) {
                        Text(if (showExtras) "Hide uncredited" else "Show uncredited (${extras.size})", color = Watchd.Red, fontWeight = FontWeight.Bold)
                    }
                }
                if (showExtras) items(extras) { person -> CastSheetRow(person, openPerson) }
            }
        }
    }
}

@Composable
private fun CastSheetRow(person: Person, openPerson: (Int) -> Unit) {
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


private val stripDay = DateTimeFormatter.ofPattern("EEE d MMM")

/**
 * The site's Next Episode and Recently Aired: the next episode to air and the
 * last two that aired, or for an ended show the last three. Tap one to open it.
 */
@Composable
private fun EpisodeStripRow(strip: EpisodeStrip, showTmdbId: Int, openEpisode: (Int, Int, Int) -> Unit, openAll: (() -> Unit)?) {
    val cards = listOfNotNull(strip.next) + strip.recent
    if (cards.isEmpty()) return
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        SectionTitle(if (strip.next != null) "Next & recently aired" else "Latest episodes", Modifier.weight(1f))
        openAll?.let { TextButton(onClick = it, modifier = Modifier.padding(end = 8.dp)) { Text("All episodes", color = Watchd.Red, fontWeight = FontWeight.Bold) } }
    }
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        items(cards, key = { "${it.seasonNumber}x${it.episodeNumber}" }) { e ->
            val next = e == strip.next
            Column(
                Modifier.width(264.dp).clip(RoundedCornerShape(14.dp)).background(Watchd.Surface)
                    .clickable { openEpisode(showTmdbId, e.seasonNumber, e.episodeNumber) },
            ) {
                Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f).background(Watchd.SurfaceHigh)) {
                    AsyncImage(e.stillPath, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(0.4f to Color.Transparent, 1f to Color.Black.copy(alpha = 0.85f))))
                    Column(Modifier.align(Alignment.BottomStart).padding(12.dp)) {
                        e.airDate?.let { date ->
                            val day = runCatching { LocalDate.parse(date).format(stripDay) }.getOrDefault(date)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    listOfNotNull(day, e.airTime).joinToString(" · "), color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.ExtraBold,
                                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Watchd.Red).padding(horizontal = 8.dp, vertical = 3.dp),
                                )
                                if (next) {
                                    val days = runCatching { java.time.temporal.ChronoUnit.DAYS.between(LocalDate.now(), LocalDate.parse(date)) }.getOrNull()
                                    days?.let { Text(if (it <= 0) "today" else if (it == 1L) "tomorrow" else "in $it days", color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 6.dp)) }
                                }
                            }
                        }
                        Text(
                            buildAnnotatedString {
                                withStyle(SpanStyle(color = Watchd.Red)) { append(episodeCode(e.seasonNumber, e.episodeNumber)) }
                                append(" ${e.title.orEmpty()}")
                            },
                            color = Color.White, fontWeight = FontWeight.Black, fontSize = 16.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }
                }
                Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    WatchedMark(e.watched, Modifier.size(22.dp))
                    // The W alone says whether it's watched.
                    Spacer(Modifier.weight(1f))
                    if (!next) ImdbBadge(e.imdbRating)
                }
            }
        }
    }
}
