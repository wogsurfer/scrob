package app.watchd.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.Play
import app.watchd.data.SignedOut
import app.watchd.data.WATCH_SOURCES
import app.watchd.data.WatchSession
import app.watchd.data.WatchTarget
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * The W as a button: a tap marks watched just now, a long press opens the
 * Watch sheet (check in, pick a date, choose where it was watched).
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WatchButton(watched: Boolean, size: androidx.compose.ui.unit.Dp = 32.dp, onTap: () -> Unit, onLongPress: () -> Unit) {
    val haptics = LocalHapticFeedback.current
    Box(
        Modifier.size(size + 20.dp).clip(CircleShape).combinedClickable(
            onClick = onTap,
            onLongClick = { haptics.performHapticFeedback(HapticFeedbackType.LongPress); onLongPress() },
            onClickLabel = if (watched) "Unmark watched" else "Mark watched",
            onLongClickLabel = "Watch options",
        ),
        contentAlignment = Alignment.Center,
    ) { WatchedMark(watched, Modifier.size(size)) }
}

private val playDate = DateTimeFormatter.ofPattern("d MMM yyyy, HH:mm")

/** "2024-03-12T19:30:00" (UTC) in local time. */
private fun localPlayTime(utc: String?): String = utc?.let {
    runCatching { LocalDateTime.parse(it.take(19)).atOffset(ZoneOffset.UTC).atZoneSameInstant(ZoneId.systemDefault()).format(playDate) }.getOrNull()
} ?: "Unknown date"

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun WatchSheet(target: WatchTarget, onChanged: () -> Unit, onDismiss: () -> Unit) {
    val app = LocalApp.current
    val scope = rememberCoroutineScope()
    val haptics = LocalHapticFeedback.current
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var source by remember { mutableStateOf<String?>(null) }
    var plays by remember { mutableStateOf<List<Play>?>(null) }
    var busy by remember { mutableStateOf(false) }
    var picking by remember { mutableStateOf(false) }

    LaunchedEffect(target) {
        plays = runCatching { app.api.plays(target) }.getOrNull() ?: emptyList()
    }

    fun close() {
        scope.launch { sheet.hide() }.invokeOnCompletion { onDismiss() }
    }

    fun run(message: String, work: suspend () -> Unit) {
        busy = true
        scope.launch {
            try {
                work()
                haptics.performHapticFeedback(HapticFeedbackType.Confirm)
                onChanged()
                close()
                app.snackbar.currentSnackbarData?.dismiss()
                app.snackbar.showSnackbar(message)
            } catch (e: SignedOut) {
                app.signOut()
            } catch (e: Exception) {
                busy = false
                app.snackbar.showSnackbar(e.message ?: "Couldn't reach Watchd")
            }
        }
    }

    val label = buildString {
        if (target.season != null && target.episode != null) append(episodeCode(target.season, target.episode)).append("  ")
        append(target.title.orEmpty())
    }
    val via = source?.let { " · $it" }.orEmpty()

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = Watchd.Surface, contentColor = Watchd.Text) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 24.dp).navigationBarsPadding(),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(label, style = MaterialTheme.typography.headlineSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)

            Text("WATCHED VIA", style = MaterialTheme.typography.labelSmall, color = Watchd.Faint)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                WATCH_SOURCES.forEach { s ->
                    FilterChip(
                        selected = source == s,
                        onClick = { source = if (source == s) null else s },
                        label = { Text(s) },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = Watchd.Red, selectedLabelColor = Color.White,
                            containerColor = Watchd.SurfaceHigh, labelColor = Watchd.Muted,
                        ),
                        border = null,
                    )
                }
            }

            Button(
                onClick = { run("Checked in$via") { app.api.checkIn(target, source); app.refreshSessions() } },
                enabled = !busy,
                colors = ButtonDefaults.buttonColors(containerColor = Watchd.Red),
                modifier = Modifier.fillMaxWidth().height(52.dp),
            ) {
                Icon(Icons.Default.PlayArrow, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Check in · watching now", fontWeight = FontWeight.Bold)
            }

            Text("OR LOG A PLAY", style = MaterialTheme.typography.labelSmall, color = Watchd.Faint)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(
                    "Just now" to { run("Marked watched$via") { app.api.logWatch(target, source) } },
                    "Pick date" to { picking = true },
                    "Unknown" to { run("Marked watched$via") { app.api.logWatch(target, source, unknownDate = true) } },
                ).forEach { (text, action) ->
                    OutlinedButton(onClick = action, enabled = !busy, modifier = Modifier.weight(1f)) { Text(text, maxLines = 1) }
                }
            }

            val history = plays
            if (!history.isNullOrEmpty()) {
                Text("PLAYS", style = MaterialTheme.typography.labelSmall, color = Watchd.Faint, modifier = Modifier.padding(top = 6.dp))
                history.sortedByDescending { it.watchedAt ?: "" }.forEach { play ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        WatchedMark(true, Modifier.size(20.dp))
                        Column(Modifier.weight(1f).padding(start = 12.dp)) {
                            Text(localPlayTime(play.watchedAt), fontWeight = FontWeight.Bold, fontSize = 14.sp)
                            play.watchSource?.let { Text(it, color = Watchd.Muted, fontSize = 13.sp) }
                        }
                        IconButton(onClick = {
                            run("Play removed") { app.api.deletePlay(play.id) }
                        }) { Icon(Icons.Outlined.DeleteOutline, contentDescription = "Remove play", tint = Watchd.Faint) }
                    }
                }
                TextButton(onClick = { run("Removed from history") { app.api.unwatch(target.tmdbId, target.mediaType) } }) {
                    Text("Mark as unwatched", color = Watchd.Muted)
                }
            }
        }
    }

    if (picking) {
        DateTimePicker(onDismiss = { picking = false }) { local ->
            picking = false
            val utc = local.atZone(ZoneId.systemDefault()).withZoneSameInstant(ZoneOffset.UTC).toLocalDateTime()
            run("Marked watched$via") { app.api.logWatch(target, source, watchedAt = utc) }
        }
    }
}

/** A date, then a time; returns local date-time. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DateTimePicker(onDismiss: () -> Unit, onPicked: (LocalDateTime) -> Unit) {
    var date by remember { mutableStateOf<LocalDate?>(null) }
    val dateState = rememberDatePickerState(
        initialSelectedDateMillis = LocalDate.now().atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli(),
    )
    val now = LocalTime.now()
    val timeState = rememberTimePickerState(initialHour = now.hour, initialMinute = now.minute, is24Hour = true)
    if (date == null) {
        DatePickerDialog(
            onDismissRequest = onDismiss,
            confirmButton = {
                TextButton(onClick = {
                    dateState.selectedDateMillis?.let { date = Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate() }
                }) { Text("Next") }
            },
            dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
        ) { DatePicker(dateState) }
    } else {
        AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text("What time?") },
            text = { TimePicker(timeState) },
            confirmButton = { TextButton(onClick = { onPicked(date!!.atTime(timeState.hour, timeState.minute)) }) { Text("Save") } },
            dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
        )
    }
}

/**
 * The running check-in, above the tabs: what, where, how far in, with
 * pause/resume, finish (records it now) and cancel.
 */
@Composable
fun NowWatchingBar(session: WatchSession, openShow: (Int) -> Unit, openMovie: (Int) -> Unit) {
    val app = LocalApp.current
    val scope = rememberCoroutineScope()
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var confirm by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(session) {
        while (true) {
            delay(1000)
            now = System.currentTimeMillis()
            // Watchd records it itself once the runtime is up; catch up with that.
            val runtime = session.runtime ?: continue
            if (session.elapsedSeconds(Instant.ofEpochMilli(now)) > runtime * 60 + 90) {
                app.refreshSessions()
                delay(30_000)
            }
        }
    }
    val elapsed = session.elapsedSeconds(Instant.ofEpochMilli(now))
    val total = (session.runtime ?: 0) * 60L
    val media = session.media
    val paused = session.state == "paused"

    fun act(work: suspend () -> Unit, message: String) {
        scope.launch {
            runCatching { work() }.onFailure { app.snackbar.showSnackbar("Couldn't reach Watchd"); return@launch }
            app.refreshSessions()
            if (message.isNotEmpty()) app.snackbar.showSnackbar(message)
        }
    }

    Column(
        Modifier.fillMaxWidth().background(Watchd.SurfaceHigh).clickable {
            val show = media.showTmdbId
            if (show != null) openShow(show) else media.tmdbId?.let(openMovie)
        },
    ) {
        LinearProgressIndicator(
            progress = { if (total > 0) (elapsed.toFloat() / total).coerceIn(0f, 1f) else 0f },
            color = Watchd.Red, trackColor = Color.Transparent, gapSize = 0.dp, drawStopIndicator = {},
            modifier = Modifier.fillMaxWidth().height(3.dp),
        )
        Row(Modifier.padding(start = 12.dp, end = 4.dp, top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            AsyncImage(media.posterPath, contentDescription = null, modifier = Modifier.width(34.dp).height(50.dp).clip(RoundedCornerShape(5.dp)).background(Watchd.Surface))
            Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                Text(
                    if (paused) "PAUSED" else "NOW WATCHING",
                    style = MaterialTheme.typography.labelSmall, color = if (paused) Watchd.Muted else Watchd.Red, fontSize = 10.sp,
                )
                Text(
                    media.showTitle?.let { "$it ${episodeCode(media.seasonNumber, media.episodeNumber)}" } ?: media.title.orEmpty(),
                    fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
                Text(
                    listOfNotNull(
                        session.watchSource,
                        if (total > 0) "${((total - elapsed).coerceAtLeast(0) + 59) / 60} min left" else "${elapsed / 60} min in",
                    ).joinToString(" · "),
                    color = Watchd.Muted, fontSize = 12.sp,
                )
            }
            IconButton(onClick = { act({ app.api.pauseSession(session, pause = !paused) }, "") }) {
                Icon(if (paused) Icons.Default.PlayArrow else Icons.Default.Pause, contentDescription = if (paused) "Resume" else "Pause")
            }
            IconButton(onClick = { confirm = "finish" }) { WatchedMark(true, Modifier.size(26.dp)) }
            IconButton(onClick = { confirm = "cancel" }) { Icon(Icons.Default.Close, contentDescription = "Cancel", tint = Watchd.Muted) }
        }
    }

    confirm?.let { which ->
        val title = media.showTitle?.let { "$it ${episodeCode(media.seasonNumber, media.episodeNumber)}" } ?: media.title.orEmpty()
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(if (which == "finish") "Finish now?" else "Cancel check-in?") },
            text = {
                Text(if (which == "finish") "Record $title as watched now." else "Stop without recording $title as watched.")
            },
            confirmButton = {
                TextButton(onClick = {
                    confirm = null
                    if (which == "finish") act({ app.api.finishSession(session) }, "$title watched")
                    else act({ app.api.cancelSession(session) }, "Check-in cancelled")
                }) { Text(if (which == "finish") "Finish" else "Cancel check-in", color = Watchd.Red) }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Keep watching") } },
            containerColor = Watchd.Surface,
        )
    }
}
