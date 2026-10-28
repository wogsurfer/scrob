package app.watchd.ui

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import app.watchd.ui.theme.Watchd

/**
 * The site's full stats, inside the app and already signed in: the app's
 * token goes in as the site's sign-in cookie. Links within the stats (year to
 * date, all time) stay here; Back steps back through them, then leaves.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun StatsScreen(onBack: () -> Unit) {
    val app = LocalApp.current
    var web by remember { mutableStateOf<WebView?>(null) }
    var canGoBack by remember { mutableStateOf(false) }
    BackHandler(enabled = canGoBack) { web?.goBack() }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.statusBarsPadding().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
            SectionTitle("Stats")
        }
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { context ->
                CookieManager.getInstance().apply {
                    setAcceptCookie(true)
                    app.token?.let { setCookie(app.server, "token=$it; path=/") }
                    flush()
                }
                WebView(context).apply {
                    setBackgroundColor(Watchd.Background.toArgb())
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    webViewClient = object : WebViewClient() {
                        override fun doUpdateVisitedHistory(view: WebView, url: String?, isReload: Boolean) {
                            canGoBack = view.canGoBack()
                        }

                        // The app has its own bars: the site's top bar and bottom tabs go.
                        override fun onPageFinished(view: WebView, url: String?) {
                            view.evaluateJavascript(HIDE_SITE_BARS, null)
                        }
                    }
                    loadUrl("${app.server.trimEnd('/')}/stats/all-time")
                    web = this
                }
            },
        )
    }
}

private const val HIDE_SITE_BARS = """
(function () {
  var s = document.createElement('style');
  s.textContent = 'body > nav.fixed.top-0, #bottom-nav { display: none !important; } main { padding-top: 16px !important; padding-bottom: 24px !important; }';
  document.head.appendChild(s);
})();
"""
