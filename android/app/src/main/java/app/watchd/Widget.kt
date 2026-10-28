package app.watchd

import android.content.Context
import android.content.Intent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.Image
import androidx.glance.ImageProvider
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.lazy.LazyColumn
import androidx.glance.appwidget.lazy.items
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import app.watchd.data.Api
import app.watchd.data.NextUpItem
import app.watchd.data.SessionStore
import kotlinx.coroutines.flow.first

/**
 * Next Up on the home screen: the next few episodes, each with the W to tick
 * it off (the widget then shows that show's next one), and a tap to open the
 * show in the app.
 */
class NextUpWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val episodes = runCatching { api(context)?.nextUp(limit = 4)?.nextUp }.getOrNull()
        provideContent { Content(context, episodes) }
    }

    @androidx.compose.runtime.Composable
    private fun Content(context: Context, episodes: List<NextUpItem>?) {
        Column(
            GlanceModifier.fillMaxSize().background(Color(0xF0101012)).cornerRadius(18.dp).padding(12.dp),
        ) {
            Text("NEXT UP", style = TextStyle(color = ColorProvider(Color(0xFFE50914)), fontSize = 12.sp, fontWeight = FontWeight.Bold))
            Spacer(GlanceModifier.height(6.dp))
            when {
                episodes == null -> Text("Can't reach Watchd", style = TextStyle(color = ColorProvider(Color(0xFFA1A1AA)), fontSize = 13.sp))
                episodes.isEmpty() -> Text("You're all caught up.", style = TextStyle(color = ColorProvider(Color(0xFFA1A1AA)), fontSize = 13.sp))
                else -> LazyColumn {
                    items(episodes, itemId = { it.tmdbId.toLong() }) { ep -> EpisodeRow(context, ep) }
                }
            }
        }
    }

    @androidx.compose.runtime.Composable
    private fun EpisodeRow(context: Context, ep: NextUpItem) {
        val open = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(NewEpisodesWorker.EXTRA_SHOW, ep.showTmdbId ?: 0)
        }
        Row(GlanceModifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
            Image(
                ImageProvider(R.drawable.watched_off), contentDescription = "Mark watched",
                modifier = GlanceModifier.size(30.dp).clickable(actionRunCallback<TickEpisode>(actionParametersOf(TickEpisode.EPISODE to ep.tmdbId))),
            )
            Column(GlanceModifier.defaultWeight().padding(start = 10.dp).clickable(actionStartActivity(open))) {
                Text(ep.showTitle.orEmpty(), maxLines = 1, style = TextStyle(color = ColorProvider(Color.White), fontSize = 14.sp, fontWeight = FontWeight.Bold))
                Text(
                    "%02dx%02d %s".format(ep.seasonNumber ?: 0, ep.episodeNumber ?: 0, ep.title.orEmpty()), maxLines = 1,
                    style = TextStyle(color = ColorProvider(Color(0xFFA1A1AA)), fontSize = 12.sp),
                )
            }
        }
    }

    companion object {
        suspend fun api(context: Context): Api? {
            val session = SessionStore(context).session.first()
            return session.token?.let { Api(session.server, it) }
        }

        /** Brings every Next Up widget up to date (after a tick in the app). */
        suspend fun refresh(context: Context) = runCatching { NextUpWidget().updateAll(context) }
    }
}

/** The W on the widget: marks the episode watched, then shows what's next. */
class TickEpisode : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val episode = parameters[EPISODE] ?: return
        runCatching { NextUpWidget.api(context)?.markWatched(episode, "episode") }
        NextUpWidget().update(context, glanceId)
    }

    companion object {
        val EPISODE = ActionParameters.Key<Int>("episode")
    }
}

class NextUpWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = NextUpWidget()
}
