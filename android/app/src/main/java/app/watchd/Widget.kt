package app.watchd

import android.content.Context
import android.content.Intent
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import app.watchd.data.Api
import app.watchd.data.AtAGlance
import app.watchd.data.SessionStore
import app.watchd.data.Watched
import kotlinx.coroutines.flow.first

private val Red = Color(0xFFE50914)
private val Muted = Color(0xFFA1A1AA)
private val Faint = Color(0xFF71717A)
private val Up = Color(0xFF4ADE80)
private val Down = Color(0xFFF87171)

/**
 * What you've watched lately, on the home screen: the last 7 and 30 days
 * (episodes, films, hours, and how that compares with the period before),
 * your run of days in a row, and this week's most-watched show. Tap to open
 * the app.
 */
class WatchedWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val glance = runCatching { api(context)?.atAGlance() }.getOrNull()
        provideContent { Content(context, glance) }
    }

    @Composable
    private fun Content(context: Context, g: AtAGlance?) {
        val open = Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        Column(
            GlanceModifier.fillMaxSize().background(Color(0xF0101012)).cornerRadius(18.dp).padding(horizontal = 14.dp, vertical = 10.dp)
                .clickable(actionStartActivity(open)),
        ) {
            if (g == null) {
                Text("WATCHD", style = TextStyle(color = ColorProvider(Red), fontSize = 12.sp, fontWeight = FontWeight.Bold))
                Text("Can't reach Watchd", style = TextStyle(color = ColorProvider(Muted), fontSize = 13.sp))
                return@Column
            }
            Row(GlanceModifier.fillMaxWidth()) {
                Period("LAST 7 DAYS", g.week, g.previousWeek, "Week before", GlanceModifier.defaultWeight())
                Spacer(GlanceModifier.width(12.dp))
                Period("LAST 30 DAYS", g.month, g.previousMonth, "Month before", GlanceModifier.defaultWeight())
            }
            Spacer(GlanceModifier.height(6.dp))
            if (g.streakDays > 0) {
                Text(
                    "%,d day%s in a row".format(g.streakDays, if (g.streakDays == 1) "" else "s"),
                    style = TextStyle(color = ColorProvider(Red), fontSize = 12.sp, fontWeight = FontWeight.Bold),
                )
            }
            // This week's most-watched show, on a line of its own.
            g.topShow?.let {
                Text(
                    "Most this week: ${it.title} · ${it.episodes} eps", maxLines = 2,
                    style = TextStyle(color = ColorProvider(Muted), fontSize = 12.sp),
                )
            }
        }
    }

    @Composable
    private fun Period(label: String, now: Watched, before: Watched, beforeName: String, modifier: GlanceModifier) {
        Column(modifier) {
            Text(label, style = TextStyle(color = ColorProvider(Red), fontSize = 11.sp, fontWeight = FontWeight.Bold))
            Text(hours(now.minutes), style = TextStyle(color = ColorProvider(Color.White), fontSize = 24.sp, fontWeight = FontWeight.Bold))
            Text(
                "%,d eps · %,d film%s".format(now.episodes, now.movies, if (now.movies == 1) "" else "s"),
                maxLines = 1, style = TextStyle(color = ColorProvider(Muted), fontSize = 12.sp),
            )
            // The period before, to compare: ▲ green when this one is ahead, ▼ red when behind.
            val change = now.minutes - before.minutes
            Text(
                "${if (change > 0) "▲ " else if (change < 0) "▼ " else ""}$beforeName: ${roughHours(before.minutes)}",
                maxLines = 1,
                style = TextStyle(color = ColorProvider(if (change > 0) Up else if (change < 0) Down else Faint), fontSize = 11.sp),
            )
        }
    }

    companion object {
        suspend fun api(context: Context): Api? {
            val session = SessionStore(context).session.first()
            return session.token?.let { Api(session.server, it) }
        }

        /** Brings every widget up to date (as the app closes). */
        suspend fun refresh(context: Context) = runCatching { WatchedWidget().updateAll(context) }
    }
}

/** "16h 35m", or "45m" under an hour. */
private fun hours(minutes: Int): String = if (minutes >= 60) "${minutes / 60}h ${minutes % 60}m" else "${minutes}m"

/** As [hours], but whole hours from 10h up ("25h"), to fit the comparison line. */
private fun roughHours(minutes: Int): String = if (minutes >= 600) "${(minutes + 30) / 60}h" else hours(minutes)

class WatchedWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = WatchedWidget()
}
