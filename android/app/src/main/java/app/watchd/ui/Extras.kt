package app.watchd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.EmojiEvents
import androidx.compose.material.icons.filled.Search
import kotlin.math.roundToInt
import androidx.compose.ui.platform.LocalContext
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Slider
import androidx.compose.material.icons.filled.GridView
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.outlined.EmojiEvents
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.layout
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.Album
import app.watchd.data.Award
import app.watchd.data.Disc
import app.watchd.data.PersonCredit
import app.watchd.data.PhysicalItem
import app.watchd.data.SignedOut
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
import java.time.LocalDate
import java.time.format.DateTimeFormatter

private val Gold = Color(0xFFF5C518)

/** Widens content by [h] each side, past a parent's padding. */
private fun Modifier.bleed(h: androidx.compose.ui.unit.Dp) = layout { measurable, constraints ->
    val extra = (h * 2).roundToPx()
    val placeable = measurable.measure(constraints.copy(minWidth = constraints.minWidth + extra, maxWidth = constraints.maxWidth + extra))
    layout(placeable.width - extra, placeable.height) { placeable.place(-extra / 2, 0) }
}

// ------------------------------------------------------------------ on disc

/** Your editions of a title, in the site's red: "4K UHD · Steelbook". */
@Composable
fun OnDisc(discs: List<Disc>) {
    if (discs.isEmpty()) return
    Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        discs.forEach { d ->
            val wish = d.status == "wishlist"
            Text(
                buildString {
                    append(if (wish) "Wishlist · " else "On disc · ")
                    // "1 Disc: Blu-ray + Ultraviolet" already says Blu-ray.
                    val edition = d.edition?.takeIf { it.isNotBlank() }
                    val format = d.format?.takeUnless { f -> edition?.contains(f, ignoreCase = true) == true }
                    append(listOfNotNull(format, edition).joinToString(" · ").ifEmpty { "Disc" })
                    d.inSet?.let { append(" · in ").append(it) }
                },
                color = if (wish) Watchd.Muted else Watchd.Red, fontSize = 13.sp, fontWeight = FontWeight.Bold,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

// ------------------------------------------------------------------ awards

/** Loaded on its own so the page shows first; empty until it arrives. */
@Composable
fun rememberAwards(key: Any, load: suspend app.watchd.data.Api.() -> List<Award>): List<Award>? {
    val app = LocalApp.current
    val awards by produceState<List<Award>?>(null, key) {
        value = try { app.api.load() } catch (e: SignedOut) { app.signOut(); emptyList() } catch (_: Exception) { emptyList() }
    }
    return awards
}

private fun sortAwards(awards: List<Award>) =
    awards.sortedWith(compareByDescending<Award> { it.year ?: "" }.thenByDescending { it.isWinner })

/** Wins and nominations: the first few, then See all. [showWork] for a person's page. */
@Composable
fun AwardsSection(awards: List<Award>?, showWork: Boolean = false, openWork: (Award) -> Unit = {}) {
    if (awards.isNullOrEmpty()) return
    var all by remember { mutableStateOf(false) }
    val sorted = remember(awards) { sortAwards(awards) }
    val wins = awards.count { it.isWinner }
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        SectionTitle("Awards")
        Text(
            listOfNotNull(
                wins.takeIf { it > 0 }?.let { "$it win${if (it == 1) "" else "s"}" },
                "${awards.size} nomination${if (awards.size == 1) "" else "s"}",
            ).joinToString(" · "),
            color = Watchd.Muted, fontSize = 13.sp, modifier = Modifier.weight(1f),
        )
        if (awards.size > 5) {
            TextButton(onClick = { all = true }, modifier = Modifier.padding(end = 8.dp)) { Text("See all", color = Watchd.Red, fontWeight = FontWeight.Bold) }
        }
    }
    sorted.take(5).forEach { AwardRow(it, showWork, openWork) }
    if (all) {
        Sheet("Awards", onDismiss = { all = false }) {
            items(sorted) { AwardRow(it, showWork, openWork) }
        }
    }
}

@Composable
private fun AwardRow(award: Award, showWork: Boolean, openWork: (Award) -> Unit) {
    Row(
        Modifier.fillMaxWidth()
            .clickable(enabled = showWork && award.workTmdbId != null) { openWork(award) }
            .padding(horizontal = 16.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(
            if (award.isWinner) Icons.Filled.EmojiEvents else Icons.Outlined.EmojiEvents,
            contentDescription = if (award.isWinner) "Won" else "Nominated",
            tint = if (award.isWinner) Gold else Watchd.Faint,
            modifier = Modifier.size(22.dp),
        )
        Column(Modifier.weight(1f)) {
            Text(award.categoryName, fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
            // "BAFTA Awards 2004 · Sally Menke": the award first, so a long list
            // of names wraps rather than pushing it out; a name worked out
            // rather than on record in italics, as on the site.
            val who = (if (showWork) award.workTitle else award.personName)?.takeIf { it.isNotBlank() }
            Text(
                buildAnnotatedString {
                    withStyle(SpanStyle(color = Watchd.Muted)) { append(listOfNotNull(award.awardName, award.year).joinToString(" ")) }
                    if (who != null) {
                        append(" · ")
                        withStyle(SpanStyle(color = Watchd.Text, fontStyle = if (award.nameInferred) FontStyle.Italic else FontStyle.Normal)) { append(who) }
                    }
                },
                fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
            )
        }
        if (award.isWinner) {
            Text(
                "WON", style = MaterialTheme.typography.labelSmall, color = Color.Black,
                modifier = Modifier.clip(RoundedCornerShape(5.dp)).background(Gold).padding(horizontal = 6.dp, vertical = 2.dp),
            )
        }
    }
}

// ------------------------------------------------------------------ soundtrack

@Composable
fun rememberSoundtrack(kind: String, tmdbId: Int): List<Album>? {
    val app = LocalApp.current
    val albums by produceState<List<Album>?>(null, kind, tmdbId) {
        value = try { app.api.soundtrack(kind, tmdbId).albums } catch (e: SignedOut) { app.signOut(); emptyList() } catch (_: Exception) { emptyList() }
    }
    return albums
}

/** The songs, without links (as on the site): the first six, then See all. */
@Composable
fun SoundtrackSection(albums: List<Album>?) {
    val tracks = albums.orEmpty().flatMap { it.tracks }
    if (tracks.isEmpty()) return
    var all by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        SectionTitle("Soundtrack")
        Text("${tracks.size} songs", color = Watchd.Muted, fontSize = 13.sp, modifier = Modifier.weight(1f))
        if (tracks.size > 6) {
            TextButton(onClick = { all = true }, modifier = Modifier.padding(end = 8.dp)) { Text("See all", color = Watchd.Red, fontWeight = FontWeight.Bold) }
        }
    }
    tracks.take(6).forEachIndexed { i, t -> TrackRow(i + 1, t) }
    if (all) {
        Sheet("Soundtrack", onDismiss = { all = false }) {
            albums.orEmpty().filter { it.tracks.isNotEmpty() }.forEach { album ->
                item {
                    Text(
                        listOfNotNull(album.title, album.year?.toString()).joinToString(" · ").uppercase(),
                        style = MaterialTheme.typography.labelSmall, color = Watchd.Faint,
                        modifier = Modifier.padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 4.dp),
                    )
                }
                items(album.tracks.size) { i -> TrackRow(i + 1, album.tracks[i]) }
            }
        }
    }
}

@Composable
private fun TrackRow(n: Int, track: app.watchd.data.Track) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("$n", color = Watchd.Faint, fontSize = 13.sp, modifier = Modifier.width(28.dp))
        Column(Modifier.weight(1f)) {
            Text(track.title, fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            track.artist?.let { Text(it, color = Watchd.Muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis) }
        }
        track.length?.takeIf { it > 0 }?.let { Text("%d:%02d".format(it / 60, it % 60), color = Watchd.Faint, fontSize = 12.sp) }
    }
}

/** A bottom sheet with a title over a list. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Sheet(title: String, onDismiss: () -> Unit, content: androidx.compose.foundation.lazy.LazyListScope.() -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Watchd.Surface, contentColor = Watchd.Text) {
        Text(title, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(start = 20.dp, bottom = 8.dp))
        LazyColumn(contentPadding = PaddingValues(bottom = 24.dp), content = content)
    }
}

// ------------------------------------------------------------------ person

private val bornFormat = DateTimeFormatter.ofPattern("d MMMM yyyy")

private val CATEGORIES = listOf("all" to "All", "acting" to "Acting", "directing" to "Directing", "writing" to "Writing", "producing" to "Producing", "other" to "Other")

@Composable
fun PersonScreen(personId: Int, onBack: () -> Unit, openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    val app = LocalApp.current
    var category by rememberSaveable { mutableStateOf("all") }
    val (state, reload) = rememberLoad(personId) { person(personId) }
    val awards = rememberAwards(personId) { personAwards(personId).awards }
    LoadContent(state, reload) { person ->
        // Credits a page at a time, per category, as you scroll.
        val credits = remember(category) { mutableStateListOf<PersonCredit>().apply { if (category == "all") addAll(person.credits) } }
        var page by remember(category) { mutableIntStateOf(if (category == "all") 1 else 0) }
        var total by remember(category) { mutableIntStateOf(if (category == "all") person.totalCredits else Int.MAX_VALUE) }
        var loading by remember { mutableStateOf(false) }
        val grid = rememberLazyGridState()
        val nearEnd by remember { derivedStateOf { (grid.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0) >= grid.layoutInfo.totalItemsCount - 8 } }
        LaunchedEffect(category, nearEnd, page) {
            if (!nearEnd || loading || credits.size >= total) return@LaunchedEffect
            loading = true
            runCatching { app.api.person(personId, page + 1, category) }.onSuccess { next ->
                credits.addAll(next.credits.filter { c -> credits.none { it.tmdbId == c.tmdbId && it.type == c.type } })
                total = if (next.credits.isEmpty()) credits.size else next.totalCredits
                page = next.page
            }.onFailure { total = credits.size }
            loading = false
        }

        LazyVerticalGrid(
            columns = GridCells.Adaptive(104.dp), state = grid, modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Column {
                    Row(Modifier.statusBarsPadding().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = onBack, modifier = Modifier.padding(start = 0.dp)) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.Bottom) {
                        AsyncImage(
                            person.profilePath, contentDescription = null, contentScale = ContentScale.Crop,
                            modifier = Modifier.width(110.dp).height(150.dp).clip(RoundedCornerShape(12.dp)).background(Watchd.Surface),
                        )
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(person.name, style = MaterialTheme.typography.headlineSmall)
                            person.knownForDepartment?.let { Text(it, color = Watchd.Red, fontWeight = FontWeight.Bold, fontSize = 13.sp) }
                            person.birthday?.let { b ->
                                val born = runCatching { LocalDate.parse(b) }.getOrNull()
                                val died = person.deathday?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
                                val age = born?.let { java.time.Period.between(it, died ?: LocalDate.now()).years }
                                Text(
                                    listOfNotNull("Born ${born?.format(bornFormat) ?: b}", age?.let { if (died != null) "died aged $it" else "age $it" }).joinToString(", "),
                                    color = Watchd.Muted, fontSize = 13.sp,
                                )
                            }
                            person.placeOfBirth?.let { Text(it, color = Watchd.Faint, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                        }
                    }
                    val watched = person.watchedCreditCounts["all"] ?: 0
                    val all = person.creditCounts["all"] ?: person.totalCredits
                    if (all > 0) {
                        Row(Modifier.padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                            WatchedMark(watched > 0, Modifier.size(20.dp))
                            Text("  You've watched $watched of their $all titles", color = Watchd.Muted, fontSize = 13.sp)
                        }
                    }
                    person.biography?.takeIf { it.isNotBlank() }?.let { Biography(it) }
                    // These pad themselves like the page sections elsewhere; reach past the grid's margin so they line up.
                    Column(Modifier.bleed(16.dp)) {
                        AwardsSection(awards, showWork = true) { a -> a.workTmdbId?.let { if (a.workType == "series") openShow(it) else openMovie(it) } }
                        SectionTitle("Credits", Modifier.padding(top = 8.dp))
                    }
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(bottom = 8.dp)) {
                        items(CATEGORIES.filter { (k, _) -> k == "all" || (person.creditCounts[k] ?: 0) > 0 }) { (key, label) ->
                            FilterChip(
                                selected = category == key, onClick = { category = key },
                                label = { Text("$label ${person.creditCounts[key] ?: ""}".trim()) },
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = Watchd.Red, selectedLabelColor = Color.White,
                                    containerColor = Watchd.Surface, labelColor = Watchd.Muted,
                                ),
                                border = null,
                            )
                        }
                    }
                }
            }
            items(credits, key = { "${it.type}-${it.tmdbId}-${it.character}-${it.job}" }) { credit ->
                Column(Modifier.clickable { if (credit.type == "tv" || credit.type == "series") openShow(credit.tmdbId) else openMovie(credit.tmdbId) }) {
                    Box {
                        Poster(credit.posterPath, Modifier.fillMaxWidth())
                        if (credit.watched) WatchedMark(true, Modifier.align(Alignment.TopEnd).padding(5.dp).size(24.dp))
                    }
                    Text(credit.title.orEmpty(), fontWeight = FontWeight.Bold, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
                    Text(
                        listOfNotNull(year(credit.releaseDate), (credit.character ?: credit.job)?.takeIf { it.isNotBlank() }).joinToString(" · "),
                        color = Watchd.Faint, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            if (loading) {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Watchd.Red) }
                }
            }
        }
    }
}

@Composable
private fun Biography(text: String) {
    var open by remember { mutableStateOf(false) }
    Text(
        text, color = Watchd.Muted, maxLines = if (open) Int.MAX_VALUE else 4, overflow = TextOverflow.Ellipsis,
        modifier = Modifier.padding(top = 12.dp).clickable { open = !open },
    )
    if (!open && text.length > 240) {
        Text("Read more", color = Watchd.Red, fontWeight = FontWeight.Bold, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp).clickable { open = true })
    }
}

// ------------------------------------------------------------------ disc collection

private data class Shelf(val items: List<PhysicalItem>, val stats: app.watchd.data.PhysicalStats)

private val SHELVES = listOf("All", "4K UHD", "Blu-ray", "Blu-ray 3D", "Sets", "Wishlist")

@Composable
fun CollectionScreen(onBack: () -> Unit, openDisc: (Int) -> Unit, addDisc: () -> Unit) {
    val (state, reload) = rememberLoad(Unit) { Shelf(discItems().items, discStats()) }
    var shelf by rememberSaveable { mutableStateOf("All") }
    var query by rememberSaveable { mutableStateOf("") }
    // Covers a row, 2 to 6, kept between visits.
    val prefs = LocalContext.current.getSharedPreferences("watchd", android.content.Context.MODE_PRIVATE)
    var columns by remember { mutableIntStateOf(prefs.getInt("collection_columns", 3).coerceIn(2, 6)) }
    LoadContent(state, reload) { data ->
        val children = remember(data) { data.items.filter { it.parentId != null }.groupBy { it.parentId!! } }
        val top = remember(data) { data.items.filter { it.parentId == null } }
        val q = query.trim().lowercase()
        val shown = top.filter { item ->
            val inSet = children[item.id].orEmpty()
            when (shelf) {
                "Wishlist" -> item.status == "wishlist"
                "Sets" -> item.isSet && item.status != "wishlist"
                "All" -> item.status != "wishlist"
                else -> item.status != "wishlist" && (item.format == shelf || inSet.any { it.format == shelf })
            } && (q.isEmpty() || item.title.orEmpty().lowercase().contains(q) || inSet.any { it.title.orEmpty().lowercase().contains(q) })
        }.sortedBy { (it.sortTitle ?: it.title).orEmpty().lowercase() }

        LazyVerticalGrid(
            columns = GridCells.Fixed(columns), modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(if (columns >= 5) 6.dp else 10.dp),
            verticalArrangement = Arrangement.spacedBy(if (columns >= 5) 6.dp else 10.dp),
        ) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Column {
                    Row(Modifier.statusBarsPadding().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
                        SectionTitle("Collection", Modifier.weight(1f))
                        IconButton(onClick = addDisc) { Icon(Icons.Default.QrCodeScanner, contentDescription = "Add a disc", tint = Watchd.Red) }
                    }
                    val s = data.stats
                    Text(
                        "%,d discs · %,d titles · %,d seen · %,d unseen".format(s.discs, s.titles, s.seen, s.unseen),
                        color = Watchd.Muted, fontSize = 13.sp,
                    )
                    OutlinedTextField(
                        query, { query = it }, placeholder = { Text("Search your discs") },
                        leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) }, singleLine = true,
                        modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                    )
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(vertical = 8.dp)) {
                        items(SHELVES) { name ->
                            FilterChip(
                                selected = shelf == name, onClick = { shelf = name }, label = { Text(name) },
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = Watchd.Red, selectedLabelColor = Color.White,
                                    containerColor = Watchd.Surface, labelColor = Watchd.Muted,
                                ),
                                border = null,
                            )
                        }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("${shown.size} shown", color = Watchd.Faint, fontSize = 12.sp, modifier = Modifier.weight(1f))
                        Icon(Icons.Default.GridView, contentDescription = null, tint = Watchd.Faint, modifier = Modifier.size(16.dp))
                        Slider(
                            value = columns.toFloat(),
                            onValueChange = { v -> columns = v.roundToInt().also { prefs.edit().putInt("collection_columns", it).apply() } },
                            valueRange = 2f..6f, steps = 3, modifier = Modifier.width(150.dp).padding(start = 6.dp),
                            colors = SliderDefaults.colors(thumbColor = Watchd.Red, activeTrackColor = Watchd.Red),
                        )
                        Text("$columns wide", color = Watchd.Faint, fontSize = 12.sp, modifier = Modifier.padding(start = 6.dp))
                    }
                }
            }
            items(shown, key = { it.id }) { item ->
                // Just the cover: no title under it, so rows stay even.
                val small = columns >= 5
                Box(Modifier.clickable { openDisc(item.id) }) {
                        CaseCover(item.cover, Modifier.fillMaxWidth())
                        if (item.seen) WatchedMark(true, Modifier.align(Alignment.TopEnd).padding(if (small) 3.dp else 5.dp).size(if (small) 15.dp else 22.dp))
                        // As on the site: never edited, no cover scan or details yet.
                        if (item.unedited) {
                            Text(
                                "NEW", fontWeight = FontWeight.Black, fontSize = if (small) 7.sp else 10.sp, letterSpacing = 0.6.sp, color = Color(0xFF052E16),
                                modifier = Modifier.align(Alignment.TopStart).padding(if (small) 3.dp else 5.dp).clip(RoundedCornerShape(4.dp)).background(Color(0xFF22C55E)).padding(horizontal = 5.dp, vertical = 1.dp),
                            )
                        }
                }
            }
        }

    }
}
