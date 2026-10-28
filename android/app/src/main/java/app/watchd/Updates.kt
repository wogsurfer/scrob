package app.watchd

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
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
import androidx.core.content.FileProvider
import app.watchd.data.AppBuild
import app.watchd.ui.LocalApp
import app.watchd.ui.theme.Watchd
import kotlinx.coroutines.launch
import java.io.File

/** This install's version code. */
fun installedVersion(context: Context): Long =
    context.packageManager.getPackageInfo(context.packageName, 0).longVersionCode

/**
 * Looks for a newer build on Watchd as the app opens and, when there is one,
 * offers it: download, then Android's installer (it asks once to let Watchd
 * install apps). "Later" waits for the next time the app opens.
 */
@Composable
fun UpdateCheck() {
    val app = LocalApp.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var offer by remember { mutableStateOf<AppBuild?>(null) }
    var progress by remember { mutableStateOf<Float?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        val latest = runCatching { app.api.latestApp() }.getOrNull() ?: return@LaunchedEffect
        if (latest.versionCode > installedVersion(context)) offer = latest
    }

    val build = offer ?: return
    AlertDialog(
        onDismissRequest = { if (progress == null) offer = null },
        containerColor = Watchd.Surface,
        title = { Text("Update ready") },
        text = {
            Column {
                Text("Watchd ${build.versionName.orEmpty()} (%.0f MB)".format(build.size / 1_048_576.0))
                problem?.let { Text(it, color = Watchd.Red, modifier = Modifier.padding(top = 8.dp)) }
                progress?.let {
                    LinearProgressIndicator(
                        progress = { it }, color = Watchd.Red, trackColor = Watchd.SurfaceHigh,
                        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                    )
                }
            }
        },
        confirmButton = {
            TextButton(enabled = progress == null, onClick = {
                // Android asks once to let Watchd install apps.
                if (!context.packageManager.canRequestPackageInstalls()) {
                    context.startActivity(
                        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    )
                    problem = "Allow Watchd to install apps, come back, and tap Install again."
                    return@TextButton
                }
                problem = null
                progress = 0f
                scope.launch {
                    val file = File(File(context.cacheDir, "updates"), "watchd.apk")
                    try {
                        app.api.downloadApp(file) { progress = it }
                        install(context, file)
                        offer = null
                    } catch (e: Exception) {
                        problem = "The download didn't finish. Try again."
                    }
                    progress = null
                }
            }) { Text(if (progress != null) "Downloading…" else "Install", color = Watchd.Red) }
        },
        dismissButton = {
            TextButton(enabled = progress == null, onClick = { offer = null }) { Text("Later", color = Watchd.Muted) }
        },
    )
}

private fun install(context: Context, file: File) {
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", file)
    context.startActivity(
        Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK),
    )
}
