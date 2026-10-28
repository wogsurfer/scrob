package app.watchd

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.watchd.data.Api
import app.watchd.data.SessionStore
import app.watchd.data.SignedOut
import app.watchd.data.UpcomingEpisode
import kotlinx.coroutines.flow.first
import java.time.Duration
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.concurrent.TimeUnit

/**
 * "VisionQuest 01x06 Deadlock is out": every 15 minutes, the schedule's
 * episodes that came out in the last half day (Watchd's times are Malta's)
 * and aren't watched yet, each told once. Tapping one opens the show.
 */
class NewEpisodesWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val session = SessionStore(applicationContext).session.first()
        val token = session.token ?: return Result.success().also { Log.i(TAG, "not signed in") }
        val episodes = try {
            Api(session.server, token).upcoming(days = 2).episodes
        } catch (e: SignedOut) {
            return Result.success().also { Log.i(TAG, "signed out") }
        } catch (e: Exception) {
            Log.w(TAG, "schedule unavailable", e)
            return Result.retry()
        }
        Log.i(TAG, "checking ${episodes.size} episodes")
        val prefs = applicationContext.getSharedPreferences("new_episodes", Context.MODE_PRIVATE)
        val told = prefs.getStringSet("told", emptySet()).orEmpty().toMutableSet()
        val now = ZonedDateTime.now(MALTA)
        for (ep in episodes) {
            val out = releaseTime(ep) ?: continue
            val key = "${ep.showTmdbId}-${ep.season}-${ep.episode}"
            if (ep.watched || key in told || out.isAfter(now) || Duration.between(out, now) > FRESH) continue
            if (notify(ep, key)) told += key
            Log.i(TAG, "new: $key")
        }
        // Keep the list short: only episodes still on the schedule matter.
        val current = episodes.map { "${it.showTmdbId}-${it.season}-${it.episode}" }.toSet()
        prefs.edit().putStringSet("told", told.filter { it in current }.toSet()).apply()
        return Result.success()
    }

    private fun releaseTime(ep: UpcomingEpisode): ZonedDateTime? {
        val day = runCatching { LocalDate.parse(ep.airDate) }.getOrNull() ?: return null
        val time = runCatching { LocalTime.parse(ep.airTime) }.getOrNull() ?: LocalTime.MIDNIGHT
        return day.atTime(time).atZone(MALTA)
    }

    /** Shows it; false when notifications aren't allowed (yet), so it's tried again. */
    private fun notify(ep: UpcomingEpisode, key: String): Boolean {
        val context = applicationContext
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return false
        ensureChannel(context)
        val open = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_SHOW, ep.showTmdbId ?: 0)
        }
        val tap = PendingIntent.getActivity(context, key.hashCode(), open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val code = "%02dx%02d".format(ep.season ?: 0, ep.episode ?: 0)
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(0xFFE50914.toInt())
            .setContentTitle("${ep.showTitle.orEmpty()} $code is out")
            .setContentText(listOfNotNull(ep.title, ep.network).joinToString(" · "))
            .setContentIntent(tap)
            .setAutoCancel(true)
            .setGroup(CHANNEL)
            .build()
        return runCatching { NotificationManagerCompat.from(context).notify(key.hashCode(), notification) }.isSuccess
    }

    companion object {
        const val EXTRA_SHOW = "show_tmdb_id"
        private const val TAG = "NewEpisodes"
        private const val CHANNEL = "new_episodes"
        private const val WORK = "new_episodes"
        private val MALTA: ZoneId = ZoneId.of("Europe/Malta")
        private val FRESH: Duration = Duration.ofHours(12)

        fun ensureChannel(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java)
            if (manager.getNotificationChannel(CHANNEL) == null) {
                manager.createNotificationChannel(
                    NotificationChannel(CHANNEL, context.getString(R.string.channel_episodes), NotificationManager.IMPORTANCE_DEFAULT),
                )
            }
        }

        /** Starts the 15-minute check (once; later calls leave it running),
         *  and checks once now, as the app opens. */
        fun schedule(context: Context) {
            val online = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            val work = WorkManager.getInstance(context)
            work.enqueueUniquePeriodicWork(
                WORK, ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<NewEpisodesWorker>(15, TimeUnit.MINUTES).setConstraints(online).build(),
            )
            work.enqueueUniqueWork(
                "$WORK-now", ExistingWorkPolicy.REPLACE,
                OneTimeWorkRequestBuilder<NewEpisodesWorker>().setConstraints(online).build(),
            )
        }
    }
}
