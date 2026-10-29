package app.watchd.ui

import coil3.compose.AsyncImage
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.height
import androidx.compose.ui.res.painterResource
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.DiscContent
import app.watchd.data.DiscDetail
import app.watchd.ui.theme.Watchd
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

private val discDate = DateTimeFormatter.ofPattern("d MMM yyyy")

private fun dateOf(value: String?): String? = value?.let {
    runCatching { (if (it.length > 10) LocalDateTime.parse(it.take(19)).toLocalDate() else LocalDate.parse(it)).format(discDate) }.getOrDefault(it)
}

/**
 * A disc in your collection, as the site's detail panel shows it: the
 * cover and edition, then its edition, picture and sound, discs, purchase,
 * film and cast. A disc in a box set takes its purchase details from the set.
 */
@Composable
fun DiscScreen(discId: Int, onBack: () -> Unit, openDisc: (Int) -> Unit, openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    val (state, reload) = rememberLoad(discId, saved("disc-$discId")) { disc(discId) }
    val list = rememberLazyListState()
    LoadContent(state, reload) { d ->
        val set = d.parent
        // The edition and purchase come from the box set when the disc is in one.
        val format = set?.format ?: d.format
        val edition = set?.edition ?: d.edition
        val seenOf = d.contents.count { it.seen }
        val seen = if (d.isSet) d.contents.isNotEmpty() && seenOf == d.contents.size else d.seen
        DetailScaffold(d.title, list, onBack) {
            item {
                DetailHeader(
                    backdrop = d.backdrop, poster = d.coverFull ?: d.cover ?: set?.cover, cover = true, title = d.title + (d.titleExtension?.let { " $it" } ?: ""),
                    facts = listOfNotNull(d.releaseYear?.toString(), d.studios.take(2).joinToString(" / ").ifBlank { null }),
                )
            }
            item { DiscBadges(d, format) }
            if (!edition.isNullOrBlank()) {
                item { Text(edition, color = Watchd.Red, fontWeight = FontWeight.Bold, fontSize = 14.sp, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) }
            }
            set?.let { s ->
                item {
                    Text(
                        "Part of ${s.title}", color = Watchd.Text, fontWeight = FontWeight.Bold, fontSize = 13.sp,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp).clip(RoundedCornerShape(8.dp)).background(Watchd.Surface)
                            .clickable { openDisc(s.id) }.padding(horizontal = 10.dp, vertical = 6.dp),
                    )
                }
            }
            item {
                // The stars go under the IMDb tag when both don't fit across.
                FlowRow(
                    Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp),
                    itemVerticalAlignment = Alignment.CenterVertically,
                ) {
                    ImdbPill(d.imdbRating, d.imdbVotes)
                    DiscStars(d.id, d.myRating)
                }
            }
            item {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    WatchedMark(seen, Modifier.size(22.dp))
                    Text(
                        "  " + when {
                            d.isSet -> "Seen $seenOf of ${d.contents.size}"
                            d.seen -> listOfNotNull("Seen", d.plays.takeIf { it > 1 }?.let { "$it plays" }, dateOf(d.lastWatched)?.let { "last on $it" }).joinToString(" · ")
                            else -> "Not seen yet"
                        },
                        color = if (seen) Watchd.Text else Watchd.Muted, fontSize = 13.sp,
                    )
                }
            }
            if (d.tmdbId != null && !d.isSet) {
                item {
                    FilledTonalButton(
                        onClick = { if (d.tmdbKind == "tv") openShow(d.tmdbId) else openMovie(d.tmdbId) },
                        colors = ButtonDefaults.filledTonalButtonColors(containerColor = Watchd.Surface, contentColor = Color.White),
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                    ) {
                        Text(if (d.tmdbKind == "tv") "Show page" else "Film page")
                        Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null, modifier = Modifier.padding(start = 6.dp).size(16.dp))
                    }
                }
            }
            d.specs?.let { s ->
                if (!s.tagline.isNullOrBlank() || !s.plot.isNullOrBlank()) {
                    item {
                        Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            s.tagline?.takeIf { it.isNotBlank() }?.let { Text("“$it”", fontWeight = FontWeight.Bold) }
                            s.plot?.takeIf { it.isNotBlank() }?.let { Text(it, color = Watchd.Muted) }
                        }
                    }
                }
            }

            if (d.isSet) {
                item { SectionTitle("In this set", Modifier.padding(top = 8.dp)) }
                items(d.contents, key = { "c-${it.id}" }) { SetRow(it) { openDisc(it.id) } }
            }

            facts("Edition", listOf(
                "Distributor" to (set?.distributor ?: d.distributor),
                "Barcode" to (set?.barcode ?: d.barcode),
                "Disc release" to dateOf(d.discReleaseDate),
                "Discs" to d.discCount?.toString(),
                "Packaging" to d.`package`,
                "Running time" to d.runtime?.let { "$it min" },
                "HDR" to d.hdr,
            ))
            chips("Picture and sound", listOf("Aspect ratio" to d.ratios, "Audio" to d.audio, "Subtitles" to d.subtitles, "In the box" to d.extras))
            val discs = d.specs?.discs.orEmpty().filter { !it.title.isNullOrBlank() }
            if (discs.size > 1 || discs.any { it.features.isNotEmpty() }) {
                item { SectionTitle("Discs", Modifier.padding(top = 8.dp)) }
                items(discs.size) { i ->
                    val disc = discs[i]
                    Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
                        Text(listOfNotNull(disc.title, disc.format).joinToString(" · "), fontWeight = FontWeight.Bold, fontSize = 14.sp)
                        if (disc.features.isNotEmpty()) Text(disc.features.joinToString(", "), color = Watchd.Muted, fontSize = 13.sp)
                    }
                }
            }
            d.specs?.extraFeatures?.takeIf { it.isNotBlank() }?.let { extra ->
                item { SectionTitle("Extra features", Modifier.padding(top = 8.dp)) }
                item { Text(extra, color = Watchd.Muted, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 16.dp)) }
            }
            facts(if (set != null) "Purchase (the set)" else "Purchase", listOf(
                "Purchased" to dateOf(set?.purchaseDate ?: d.purchaseDate),
                "Store" to (set?.store ?: d.store),
                "Price" to (set?.purchasePrice ?: d.purchasePrice)?.let { "%.2f".format(it) },
                "Condition" to (set?.condition ?: d.condition),
                "Location" to (set?.location ?: d.location),
                "Added" to dateOf(d.dateAdded),
            ))
            if (!d.notes.isNullOrBlank()) item { Text(d.notes, color = Watchd.Muted, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) }
            if (!d.isSet) {
                facts("Film", listOf(
                    "Director" to d.director,
                    "Writer" to d.writer?.replace("; ", ", "),
                    "Music" to d.composer,
                    "Genre" to d.genres.joinToString(", ").ifBlank { null },
                    "Country" to d.country,
                    "Language" to d.language,
                ))
            }
            val cast = d.specs?.cast.orEmpty()
            if (cast.isNotEmpty()) {
                item { SectionTitle("Cast", Modifier.padding(top = 8.dp)) }
                items(cast.take(24).size) { i ->
                    val c = cast[i]
                    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 3.dp)) {
                        Text(c.name, fontWeight = FontWeight.Bold, fontSize = 14.sp, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        c.character?.let { Text(it, color = Watchd.Muted, fontSize = 13.sp, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis) }
                    }
                }
            }
            if (set != null) {
                val others = d.contents.filter { it.id != d.id }
                if (others.isNotEmpty()) {
                    item { SectionTitle("Also in this set", Modifier.padding(top = 8.dp)) }
                    items(others, key = { "o-${it.id}" }) { SetRow(it) { openDisc(it.id) } }
                }
            }
            if (d.otherEditions.isNotEmpty()) {
                item { SectionTitle("Your other editions", Modifier.padding(top = 8.dp)) }
                items(d.otherEditions, key = { "e-${it.id}" }) { e ->
                    Text(
                        listOfNotNull(e.format, e.edition ?: "Edition").joinToString(" · ") + if (e.status == "wishlist") " (wish list)" else "",
                        color = Watchd.Red, fontWeight = FontWeight.Bold, fontSize = 14.sp,
                        modifier = Modifier.fillMaxWidth().clickable { openDisc(e.id) }.padding(horizontal = 16.dp, vertical = 8.dp),
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DiscBadges(d: DiscDetail, format: String?) {
    // Each label as its Collectorz image where there's one (as the Windows
    // app shows them), else as text: format, regions, age rating.
    val labels: List<Pair<String, Badge?>> = listOfNotNull(
        format?.let { it to FORMAT_BADGES[it] },
        *d.regions.map { it.replace("Region ", "") to REGION_BADGES[it] }.toTypedArray(),
        d.audienceRating?.let { ageRating(it) to ratingBadge(it) },
    )
    val chips = listOfNotNull(
        if (d.isSet) "Set · ${d.contents.size} titles" else null,
        if (d.status == "wishlist") "Wish list" else null,
    )
    if (labels.isEmpty() && chips.isEmpty()) return
    FlowRow(
        Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp),
        itemVerticalAlignment = Alignment.CenterVertically,
    ) {
        labels.forEach { (text, badge) ->
            if (badge != null) {
                // Vector drawings, so sharp at any size.
                AsyncImage(badge.url, contentDescription = text, modifier = Modifier.height(36.dp).aspectRatio(badge.shape))
            } else {
                Chip(text, Watchd.Text)
            }
        }
        chips.forEach { Chip(it, if (it == "Wish list") Watchd.Red else Watchd.Text) }
    }
}

/**
 * Your rating of the disc as the site shows it, ten stars with yours in
 * amber: tap a star to rate, its left half for half a star less, and tap
 * your rating again to clear it.
 */
@Composable
private fun DiscStars(discId: Int, mine: Double?) {
    val app = LocalApp.current
    val haptics = LocalHapticFeedback.current
    var rating by remember(discId, mine) { mutableStateOf(mine) }
    Row {
        (1..10).forEach { n ->
            val lit = rating?.let { (it - (n - 1)).coerceIn(0.0, 1.0) } ?: 0.0
            Box(
                Modifier.size(24.dp).clip(CircleShape).pointerInput(n) {
                    detectTapGestures { at ->
                        haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                        val before = rating
                        val tapped = if (at.x < size.width / 2) n - 0.5 else n.toDouble()
                        val stars = if (rating == tapped) null else tapped
                        rating = stars
                        app.act(
                            if (stars == null) "Rating cleared" else "Rated ${outOfTen(stars)}/10",
                            action = { rateDisc(discId, stars) },
                            onFail = { rating = before },
                        )
                    }
                }.padding(2.dp),
            ) {
                Icon(Icons.Default.Star, contentDescription = "Rate $n out of 10", tint = Color(0xFF3F3F46))
                if (lit > 0) {
                    // Amber over the grey, cut off at half way for a half star.
                    Icon(
                        Icons.Default.Star, contentDescription = null, tint = Color(0xFFFBBF24),
                        modifier = Modifier.drawWithContent { clipRect(right = size.width * lit.toFloat()) { this@drawWithContent.drawContent() } },
                    )
                }
            }
        }
    }
}

/** "7" or "7.5". */
private fun outOfTen(r: Double) = if (r % 1.0 == 0.0) r.toInt().toString() else r.toString()

/** IMDb's yellow tag as the site's disc details show it: "IMDb 6.6 204,067". */
@Composable
private fun ImdbPill(rating: Double?, votes: Int?) {
    if (rating == null || rating <= 0) return
    Row(
        Modifier.clip(RoundedCornerShape(6.dp)).background(Watchd.ImdbYellow).padding(horizontal = 9.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text("IMDb", color = Color.Black, fontWeight = FontWeight.Black, fontSize = 15.sp)
        Text("%.1f".format(rating), color = Color.Black, fontWeight = FontWeight.Black, fontSize = 15.sp)
        votes?.let { Text("%,d".format(it), color = Color.Black.copy(alpha = 0.65f), fontWeight = FontWeight.SemiBold, fontSize = 13.sp) }
    }
}

@Composable
private fun Chip(text: String, color: androidx.compose.ui.graphics.Color) {
    Text(
        text.uppercase(), style = MaterialTheme.typography.labelSmall, color = color,
        modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Watchd.Surface).padding(horizontal = 8.dp, vertical = 4.dp),
    )
}

/** "MPAAR" (as the disc database writes them) as "R"; others as given. */
private fun ageRating(code: String) = when {
    code.startsWith("MPAA") -> code.removePrefix("MPAA")
    else -> code
}

@Composable
private fun SetRow(item: DiscContent, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Cover(item.cover, Modifier.width(40.dp))
        Column(Modifier.weight(1f)) {
            Text(item.title.orEmpty(), fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(listOfNotNull(item.releaseYear?.toString(), item.format).joinToString(" · "), color = Watchd.Muted, fontSize = 13.sp)
        }
        WatchedMark(item.seen, Modifier.size(22.dp))
    }
}

/** A titled list of label–value facts; nothing when every value is empty. */
private fun androidx.compose.foundation.lazy.LazyListScope.facts(title: String, rows: List<Pair<String, String?>>) {
    val present = rows.filter { !it.second.isNullOrBlank() }
    if (present.isEmpty()) return
    item { SectionTitle(title, Modifier.padding(top = 8.dp)) }
    items(present.size) { i ->
        val (label, value) = present[i]
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
            Text(label, color = Watchd.Faint, fontSize = 13.sp, modifier = Modifier.width(120.dp))
            Text(value!!, fontSize = 14.sp, fontFamily = if (label == "Barcode") FontFamily.Monospace else null, modifier = Modifier.weight(1f))
        }
    }
}

/** A titled group of labelled chip rows (aspect ratios, audio tracks…). */
@OptIn(ExperimentalLayoutApi::class)
private fun androidx.compose.foundation.lazy.LazyListScope.chips(title: String, groups: List<Pair<String, List<String>>>) {
    val present = groups.filter { it.second.isNotEmpty() }
    if (present.isEmpty()) return
    item { SectionTitle(title, Modifier.padding(top = 8.dp)) }
    items(present.size) { i ->
        val (label, values) = present[i]
        Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
            Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = Watchd.Faint)
            FlowRow(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                values.forEach {
                    Text(it, fontSize = 12.sp, color = Watchd.Muted, modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Watchd.Surface).padding(horizontal = 8.dp, vertical = 3.dp))
                }
            }
        }
    }
}
