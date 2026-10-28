package app.watchd

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.watchd.data.AppBuild
import app.watchd.ui.LocalApp
import app.watchd.ui.theme.Watchd
import kotlinx.coroutines.launch

/** This install's version code. */
fun installedVersion(context: Context): Long =
    context.packageManager.getPackageInfo(context.packageName, 0).longVersionCode

/**
 * Looks for a newer build on Watchd as the app opens and, when there is one,
 * offers it. Install opens a short-lived download link in the phone's
 * browser, which hands the file to Android's installer: Watchd doesn't
 * install apps itself, which Play Protect treats as harmful. "Later" waits
 * for the next time the app opens.
 */
@Composable
fun UpdateCheck() {
    val app = LocalApp.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var offer by remember { mutableStateOf<AppBuild?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        val latest = runCatching { app.api.latestApp() }.getOrNull() ?: return@LaunchedEffect
        if (latest.versionCode > installedVersion(context)) offer = latest
    }

    val build = offer ?: return
    AlertDialog(
        onDismissRequest = { offer = null },
        containerColor = Watchd.Surface,
        title = { Text("Update ready") },
        text = {
            Column {
                Text("Watchd ${build.versionName.orEmpty()} (%.0f MB)".format(build.size / 1_048_576.0))
                Text(
                    "It downloads in your browser: open it from the download when it finishes, then tap Install.",
                    color = Watchd.Muted, modifier = Modifier.padding(top = 8.dp),
                )
                problem?.let { Text(it, color = Watchd.Red, modifier = Modifier.padding(top = 8.dp)) }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                scope.launch {
                    try {
                        val link = app.api.appLink()
                        context.startActivity(
                            Intent(Intent.ACTION_VIEW, Uri.parse(app.server.trimEnd('/') + link.url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                        )
                        offer = null
                    } catch (e: Exception) {
                        problem = "Couldn't reach Watchd. Try again."
                    }
                }
            }) { Text("Download", color = Watchd.Red) }
        },
        dismissButton = {
            TextButton(onClick = { offer = null }) { Text("Later", color = Watchd.Muted) }
        },
    )
}
