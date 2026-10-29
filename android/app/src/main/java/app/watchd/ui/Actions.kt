package app.watchd.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.List
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.FileDownload
import androidx.compose.material.icons.outlined.Storefront
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import kotlinx.coroutines.launch
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.Disc
import app.watchd.data.Person
import app.watchd.data.UserList
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage

// The site's detail-page pieces (ActionStack.astro, OnDisc.astro, the cast
// tabs and the rating popover), for the film, show, season and episode pages.

/** The colour a button takes once on, as the site's data-tone. */
enum class Tone(val base: Color, val text: Color) {
    Red(Color(0xFFEF4444), Color(0xFFFCA5A5)),
    Amber(Color(0xFFF59E0B), Color(0xFFFCD34D)),
    Sky(Color(0xFF0EA5E9), Color(0xFF7DD3FC)),
    Purple(Color(0xFFA855F7), Color(0xFFD8B4FE)),
    Orange(Color(0xFFF97316), Color(0xFFFDBA74)),
}

/** One button of the stack. [icon] draws in the colour it is given. */
class ActionItem(
    val label: String,
    val tone: Tone,
    val active: Boolean,
    val value: String? = null,
    val enabled: Boolean = true,
    val onLongClick: (() -> Unit)? = null,
    val icon: @Composable (Color) -> Unit,
    val onClick: () -> Unit,
)

fun iconOf(vector: ImageVector): @Composable (Color) -> Unit = { tint -> Icon(vector, contentDescription = null, tint = tint, modifier = Modifier.size(18.dp)) }

/** The W, red once watched, as the site's Watched button. */
fun watchedIcon(watched: Boolean): @Composable (Color) -> Unit = { WatchedMark(watched, Modifier.size(22.dp)) }

val ListsIcon = iconOf(Icons.AutoMirrored.Outlined.List)
val CollectionIcon = iconOf(Icons.Outlined.Storefront)
val RequestIcon = iconOf(Icons.Outlined.FileDownload)

/** Labelled buttons two to a row; one left on its own takes the whole row. */
@Composable
fun ActionStack(items: List<ActionItem>, modifier: Modifier = Modifier) {
    Column(modifier.padding(horizontal = 16.dp, vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { ActionButton(it, Modifier.weight(1f)) }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ActionButton(item: ActionItem, modifier: Modifier) {
    val haptics = LocalHapticFeedback.current
    val shape = RoundedCornerShape(12.dp)
    val text = if (item.active) item.tone.text else Watchd.Muted
    Row(
        modifier.heightIn(min = 46.dp).clip(shape)
            .background(if (item.active) item.tone.base.copy(alpha = 0.2f) else Watchd.Surface.copy(alpha = 0.85f))
            .border(1.dp, if (item.active) item.tone.base.copy(alpha = 0.45f) else Watchd.SurfaceHigh, shape)
            .combinedClickable(
                enabled = item.enabled,
                onLongClick = item.onLongClick?.let { long -> { haptics.performHapticFeedback(HapticFeedbackType.LongPress); long() } },
                onClick = item.onClick,
            )
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item.icon(text)
        Text(item.label, color = text, fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        item.value?.let { Text(it, color = text.copy(alpha = 0.9f), fontWeight = FontWeight.ExtraBold, fontSize = 12.sp) }
    }
}

// ------------------------------------------------------------------ lists

/** Your lists with a tick by each this is on: tick to add, untick to take it off. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ListsSheet(tmdbId: Int, mediaType: String, title: String, inLists: List<Int>, onChanged: (List<Int>) -> Unit, onDismiss: () -> Unit) {
    val app = LocalApp.current
    val lists by produceState<List<UserList>?>(null) {
        value = runCatching { app.api.lists().lists }.getOrDefault(emptyList())
    }
    val on = remember { mutableStateListOf<Int>().apply { addAll(inLists) } }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Watchd.Surface, contentColor = Watchd.Text) {
        Text("Lists", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(start = 20.dp, bottom = 8.dp))
        when {
            lists == null -> Text("Loading…", color = Watchd.Muted, modifier = Modifier.padding(20.dp))
            lists!!.isEmpty() -> Text("No lists yet.", color = Watchd.Muted, modifier = Modifier.padding(20.dp))
            else -> Column(Modifier.padding(bottom = 24.dp)) {
                lists!!.forEach { list ->
                    val ticked = list.id in on
                    Row(
                        Modifier.fillMaxWidth().clickable {
                            if (ticked) on.remove(list.id) else on.add(list.id)
                            onChanged(on.toList())
                            app.act(
                                if (ticked) "Taken off ${list.name}" else "Added to ${list.name}",
                                action = { if (ticked) removeFromList(list.id, tmdbId, mediaType) else addToList(list.id, tmdbId, mediaType) },
                                onFail = { if (ticked) on.add(list.id) else on.remove(list.id); onChanged(on.toList()) },
                            )
                        }.padding(horizontal = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(ticked, onCheckedChange = null, colors = CheckboxDefaults.colors(checkedColor = Tone.Sky.base), modifier = Modifier.padding(12.dp))
                        Text(list.name, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    }
                }
            }
        }
        Spacer(Modifier.height(8.dp))
    }
}

// ------------------------------------------------------------------ rating

/**
 * The site's rating popover: ten stars, the left half of each for half a
 * star; tap to save. Remove takes your rating off.
 */
@Composable
fun RateDialog(current: Double?, onPick: (Double?) -> Unit, onDismiss: () -> Unit) {
    val haptics = LocalHapticFeedback.current
    var preview by remember { mutableStateOf(current) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Watchd.Surface,
        title = { Text("Your rating") },
        text = {
            Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                Row {
                    (1..10).forEach { n ->
                        val lit = preview?.let { (it - (n - 1)).coerceIn(0.0, 1.0) } ?: 0.0
                        Box(
                            Modifier.size(26.dp).pointerInput(n) {
                                detectTapGestures { at ->
                                    haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                                    val value = if (at.x < size.width / 2) n - 0.5 else n.toDouble()
                                    preview = value
                                    onPick(value)
                                }
                            }.padding(1.dp),
                        ) {
                            Icon(Icons.Default.Star, contentDescription = "Rate $n out of 10", tint = Watchd.SurfaceHigh, modifier = Modifier.size(24.dp))
                            if (lit > 0) {
                                Icon(
                                    Icons.Default.Star, contentDescription = null, tint = Watchd.Red,
                                    modifier = Modifier.size(24.dp).drawWithContent { clipRect(right = size.width * lit.toFloat()) { this@drawWithContent.drawContent() } },
                                )
                            }
                        }
                    }
                }
                Text(
                    preview?.let { outOfTen(it) } ?: "Tap a star; its left half for half a star",
                    color = if (preview != null) Watchd.Red else Watchd.Muted,
                    fontWeight = if (preview != null) FontWeight.Black else FontWeight.Normal,
                    fontSize = if (preview != null) 22.sp else 13.sp,
                    modifier = Modifier.padding(top = 12.dp),
                )
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close", color = Watchd.Muted) } },
        dismissButton = {
            if (current != null) TextButton(onClick = { onPick(null) }) { Text("Remove", color = Watchd.Red) }
        },
    )
}

/** "7" or "7.5". */
fun outOfTen(r: Double) = if (r % 1.0 == 0.0) r.toInt().toString() else r.toString()

// ------------------------------------------------------------------ on disc

private val discState = mapOf("sold" to "Previously owned", "ordered" to "On order", "for_sale" to "For sale", "wishlist" to "Wish list")

/**
 * Your discs of it, as the site lists them under the buttons: the format's
 * label, the edition, box set or (for a show) season, and its state. Sold
 * discs are dimmed and wish-list ones dashed. Tap one to open it.
 */
@Composable
fun OnDiscChips(discs: List<Disc>, seriesTitle: String? = null, openDisc: (Int) -> Unit) {
    if (discs.isEmpty()) return
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("ON DISC", color = Watchd.Faint, fontSize = 10.sp, fontWeight = FontWeight.Black, letterSpacing = 1.sp)
        discs.forEach { d ->
            val shape = RoundedCornerShape(10.dp)
            val wish = d.status == "wishlist"
            val label = if (seriesTitle != null) seasonOf(d.title, seriesTitle) else d.inSet ?: d.edition
            Row(
                Modifier.fillMaxWidth().alpha(if (d.status == "sold") 0.55f else 1f).clip(shape).background(Watchd.Surface)
                    .then(
                        if (wish) Modifier.drawBehind {
                            drawRoundRect(
                                Watchd.SurfaceHigh, cornerRadius = CornerRadius(10.dp.toPx()),
                                style = Stroke(1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6f, 4f))),
                            )
                        } else Modifier.border(1.dp, Watchd.SurfaceHigh, shape),
                    )
                    .clickable { openDisc(d.id) }
                    .padding(start = 6.dp, end = 10.dp, top = 5.dp, bottom = 5.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                val badge = FORMAT_BADGES[d.format]
                if (badge != null) {
                    AsyncImage(badge.url, contentDescription = d.format, modifier = Modifier.height(22.dp).aspectRatio(badge.shape).clip(RoundedCornerShape(3.dp)))
                } else {
                    Text(
                        d.format ?: "Disc", fontSize = 11.sp, fontWeight = FontWeight.Black,
                        modifier = Modifier.clip(RoundedCornerShape(5.dp)).background(Watchd.SurfaceHigh).padding(horizontal = 6.dp, vertical = 2.dp),
                    )
                }
                Text(label.orEmpty(), color = Watchd.Muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                discState[d.status]?.let { Text(it, color = Watchd.Muted, fontSize = 11.sp, fontWeight = FontWeight.ExtraBold) }
            }
        }
    }
}

/** "Breaking Bad: The First Season" as "The First Season" on Breaking Bad's page. */
private fun seasonOf(title: String?, series: String): String? {
    if (title == null) return null
    val short = title.replace(Regex("^${Regex.escape(series)}\\s*[:\\-–]\\s*", RegexOption.IGNORE_CASE), "").trim()
    return short.ifEmpty { title }
}

// ------------------------------------------------------------------ cast

/**
 * The site's Cast and Guest Stars: two headings, the one showing in red,
 * over a row of cards. [withEpisodes] adds how many episodes each is in.
 */
@Composable
fun CastTabs(cast: List<Person>, guestStars: List<Person>, openPerson: (Int) -> Unit, withEpisodes: Boolean = false, castTitle: String = "Cast") {
    if (cast.isEmpty() && guestStars.isEmpty()) return
    var guests by remember { mutableStateOf(cast.isEmpty()) }
    Row(Modifier.padding(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 12.dp), horizontalArrangement = Arrangement.spacedBy(24.dp)) {
        listOf(false to castTitle.uppercase(), true to "GUEST STARS").forEach { (tab, name) ->
            if (tab && guestStars.isEmpty() || !tab && cast.isEmpty()) return@forEach
            Text(
                name, fontSize = 26.sp, fontWeight = FontWeight.Black, letterSpacing = (-1).sp,
                color = if (guests == tab) Color(0xFFEF4444) else Watchd.Faint,
                modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable { guests = tab },
            )
        }
    }
    val people = if (guests) guestStars else cast.take(12)
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        items(people, key = { "${if (guests) "g" else "c"}-${it.tmdbId}-${it.name}" }) { person ->
            val shape = RoundedCornerShape(22.dp)
            val role = listOfNotNull(
                person.character?.takeIf { it.isNotBlank() },
                person.episodeCount?.takeIf { withEpisodes && it > 0 }?.let { "$it episode${if (it == 1) "" else "s"}" },
            ).joinToString(" · ")
            PersonPress(person, role, openPerson, Modifier.width(176.dp).clip(shape)) {
            Column(
                Modifier.fillMaxWidth().background(Watchd.Surface.copy(alpha = 0.2f)).border(1.dp, Watchd.SurfaceHigh.copy(alpha = 0.4f), shape).padding(12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(
                    Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(16.dp)).background(Watchd.SurfaceHigh),
                    contentAlignment = Alignment.Center,
                ) {
                    if (person.profilePath != null) {
                        AsyncImage(person.profilePath, contentDescription = person.name, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxWidth().aspectRatio(1f))
                    } else {
                        Icon(Icons.Default.Person, contentDescription = null, tint = Watchd.Faint, modifier = Modifier.size(48.dp))
                    }
                }
                Text(
                    person.name, fontWeight = FontWeight.Black, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    textAlign = TextAlign.Center, modifier = Modifier.padding(top = 14.dp),
                )
                Text(
                    role.uppercase(), color = Watchd.Faint, fontWeight = FontWeight.Bold, fontSize = 11.sp, letterSpacing = 0.5.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp),
                )
            }
            }
        }
    }
}

// ------------------------------------------------------------------ stepping

/** The site's step buttons: "‹ E3" and "E5 ›" (or S for seasons), each only when there is one. */
@Composable
fun StepRow(label: String, prev: Int?, next: Int?, onStep: (Int) -> Unit) {
    if (prev == null && next == null) return
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        prev?.let { StepButton("$label$it", Icons.AutoMirrored.Filled.KeyboardArrowLeft, leading = true) { onStep(it) } }
        Spacer(Modifier.weight(1f))
        next?.let { StepButton("$label$it", Icons.AutoMirrored.Filled.KeyboardArrowRight, leading = false) { onStep(it) } }
    }
}

@Composable
private fun StepButton(text: String, icon: ImageVector, leading: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Row(
        Modifier.clip(shape).background(Watchd.Surface.copy(alpha = 0.6f)).border(1.dp, Watchd.SurfaceHigh.copy(alpha = 0.5f), shape)
            .clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (leading) Icon(icon, contentDescription = null, tint = Watchd.Muted, modifier = Modifier.size(18.dp))
        Text(text, color = Watchd.Muted, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        if (!leading) Icon(icon, contentDescription = null, tint = Watchd.Muted, modifier = Modifier.size(18.dp))
    }
}

// ------------------------------------------------------------------ crew

/** The site's crew groups (CrewSection.astro): each key role its own row, everyone else under Show all crew. */
private val CREW_GROUPS = listOf(
    "Director" to listOf("Director"),
    "TV Series Creators" to listOf("Creator"),
    "Writers" to listOf("Writer", "Staff Writer", "Head Writer", "Screenplay", "Story", "Screenstory", "Teleplay", "Adaptation", "Series Composition"),
    "Original Work" to listOf("Based On", "Novel", "Book", "Comic Book", "Original Story", "Original Material By", "Characters"),
    "Executive producers" to listOf("Executive Producer"),
    "Producers" to listOf("Producer", "Supervising Producer", "Line Producer", "Associate Producer"),
    "Co-producers" to listOf("Co-Producer"),
    "Composer" to listOf("Original Music Composer", "Composer", "Music"),
    "Cinematographer" to listOf("Director of Photography", "Cinematography"),
)

/**
 * The crew as the site shows it: a heading, a row of cards for each key
 * role, then Show all crew for the rest. [withEpisodes] adds how many
 * episodes each worked on (a show's page).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CrewSection(crew: List<Person>, openPerson: (Int) -> Unit, title: String = "Crew", withEpisodes: Boolean = false) {
    if (crew.isEmpty()) return
    val known = CREW_GROUPS.flatMap { it.second }.toSet()
    val sourceJobs = CREW_GROUPS.first { it.first == "Original Work" }.second
    // Where Wikipedia gave a "Based On", TMDB's own source credits go with the rest.
    val hasBasedOn = crew.any { it.job == "Based On" }
    fun demoted(p: Person) = hasBasedOn && p.job in sourceJobs && p.job != "Based On"
    fun unique(people: List<Person>) = people.distinctBy { it.tmdbId to it.job }
    fun role(p: Person) = p.job.orEmpty() + (p.episodeCount?.takeIf { withEpisodes && it > 0 }?.let { " · $it episodes" } ?: "")
    val groups = CREW_GROUPS.map { (name, jobs) -> name to unique(crew.filter { it.job in jobs && !demoted(it) }) }.filter { it.second.isNotEmpty() }
    val others = unique(crew.filter { it.job !in known || demoted(it) })
    var showAll by remember { mutableStateOf(false) }

    Column {
        Text(
            title.uppercase(), fontSize = 26.sp, fontWeight = FontWeight.Black, letterSpacing = (-1).sp,
            modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 28.dp, bottom = 4.dp),
        )
        groups.forEach { (name, people) ->
            Text(
                name.uppercase(), fontSize = 16.sp, fontWeight = FontWeight.Black, color = Watchd.Text.copy(alpha = 0.85f),
                modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 10.dp),
            )
            LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                items(people, key = { "${it.tmdbId}-${it.job}" }) { CrewCard(it, role(it), openPerson) }
            }
        }
        if (others.isNotEmpty()) {
            Text(
                if (showAll) "Hide other crew" else "Show all crew (${others.size})",
                color = Watchd.Muted, fontWeight = FontWeight.Bold, fontSize = 14.sp,
                modifier = Modifier.padding(start = 10.dp, top = 18.dp).clip(RoundedCornerShape(8.dp)).clickable { showAll = !showAll }.padding(6.dp),
            )
            if (showAll) {
                FlowRow(
                    Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    others.forEach { CrewCard(it, role(it), openPerson) }
                }
            }
        }
    }
}

@Composable
private fun CrewCard(person: Person, role: String, openPerson: (Int) -> Unit) {
    val shape = RoundedCornerShape(16.dp)
    PersonPress(person, role, openPerson, Modifier.width(150.dp).clip(shape)) {
    Column(
        Modifier.fillMaxWidth().background(Watchd.Surface.copy(alpha = 0.2f)).border(1.dp, Watchd.SurfaceHigh.copy(alpha = 0.4f), shape).padding(10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(12.dp)).background(Watchd.SurfaceHigh), contentAlignment = Alignment.Center) {
            if (person.profilePath != null) {
                AsyncImage(person.profilePath, contentDescription = person.name, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxWidth().aspectRatio(1f))
            } else {
                Icon(Icons.Default.Person, contentDescription = null, tint = Watchd.Faint, modifier = Modifier.size(40.dp))
            }
        }
        Text(
            person.name, fontWeight = FontWeight.Black, fontSize = 14.sp, lineHeight = 17.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.Center, modifier = Modifier.padding(top = 10.dp),
        )
        Text(
            role.uppercase(), color = Watchd.Faint, fontWeight = FontWeight.Bold, fontSize = 11.sp, lineHeight = 14.sp, letterSpacing = 0.5.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp),
        )
    }
    }
}

/**
 * A cast or crew card: tap to open the person; touch and hold for their name
 * and part in full (the card keeps each to one line), as hovering does on the site.
 */
@Composable
private fun PersonPress(person: Person, role: String, openPerson: (Int) -> Unit, modifier: Modifier, card: @Composable () -> Unit) {
    val haptics = LocalHapticFeedback.current
    var tip by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    Box(
        modifier.pointerInput(person.tmdbId) {
            detectTapGestures(
                // A press held past half a second shows the tip and doesn't open them.
                onTap = { if (!tip) person.tmdbId?.let(openPerson) },
                onPress = {
                    val hold = scope.launch {
                        kotlinx.coroutines.delay(500)
                        haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                        tip = true
                    }
                    tryAwaitRelease()
                    hold.cancel()
                    if (tip) scope.launch { kotlinx.coroutines.delay(1500); tip = false }
                },
            )
        },
    ) {
        card()
        if (tip) {
            Column(
                Modifier.align(Alignment.BottomCenter).padding(6.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp))
                    .background(Watchd.SurfaceHigh).border(1.dp, Color(0xFF3F3F46), RoundedCornerShape(10.dp)).padding(horizontal = 10.dp, vertical = 8.dp),
            ) {
                Text(person.name, color = Color.White, fontWeight = FontWeight.Black, fontSize = 13.sp, lineHeight = 16.sp)
                if (role.isNotBlank()) {
                    Text(role.uppercase(), color = Watchd.Muted, fontWeight = FontWeight.Bold, fontSize = 11.sp, lineHeight = 14.sp, letterSpacing = 0.5.sp, modifier = Modifier.padding(top = 3.dp))
                }
            }
        }
    }
}

// ------------------------------------------------------------------ plays and the file

private val playDate = java.time.format.DateTimeFormatter.ofPattern("d MMM yyyy")
private val playTime = java.time.format.DateTimeFormatter.ofPattern("HH:mm")

/** Your plays, as the site lists them under the buttons: date, time, edition and where. */
@Composable
fun WatchHistoryList(watches: List<app.watchd.data.WatchEvent>) {
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            "WATCHED" + if (watches.size > 1) " · ${watches.size} TIMES" else "",
            color = Watchd.Faint, fontSize = 10.sp, fontWeight = FontWeight.Black, letterSpacing = 1.sp,
        )
        watches.sortedByDescending { it.watchedAt.orEmpty() }.forEach { watch ->
            // Stored in UTC; shown in the phone's time.
            val at = watch.watchedAt?.let {
                runCatching { java.time.LocalDateTime.parse(it.take(19)).atZone(java.time.ZoneOffset.UTC).withZoneSameInstant(java.time.ZoneId.systemDefault()) }.getOrNull()
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (at != null) {
                    Text(at.format(playDate), fontWeight = FontWeight.Bold, fontSize = 13.sp)
                    Text(at.format(playTime), color = Watchd.Faint, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                } else {
                    Text("Date unknown", color = Watchd.Faint, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                }
                watch.edition?.let {
                    Text(
                        it.uppercase(), color = Color(0xFFF87171), fontSize = 10.sp, fontWeight = FontWeight.Bold, maxLines = 1,
                        modifier = Modifier.border(1.dp, Color(0x66EF4444), RoundedCornerShape(4.dp)).padding(horizontal = 4.dp, vertical = 1.dp),
                    )
                }
                watch.watchSource?.let { Text(it.uppercase(), color = Watchd.Muted, fontSize = 10.sp, fontWeight = FontWeight.Black) }
            }
        }
    }
}

/** The media server's file, as the site's tags: picture, sound, then 🔊 and 💬 languages. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun LibraryTags(file: app.watchd.data.LibraryFile) {
    val tags = listOfNotNull(file.resolution, file.videoCodec, file.audioCodec, file.audioChannels) +
        file.audioLanguages.map { "🔊 $it" } + file.subtitleLanguages.map { "💬 $it" }
    if (tags.isEmpty()) return
    FlowRow(
        Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        tags.forEach {
            Text(
                it, color = Watchd.Muted, fontSize = 12.sp, fontWeight = FontWeight.Bold, fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(Watchd.Surface).border(1.dp, Watchd.SurfaceHigh, RoundedCornerShape(8.dp))
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            )
        }
    }
}
