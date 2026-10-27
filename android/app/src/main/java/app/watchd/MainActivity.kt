package app.watchd

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.compose.LifecycleResumeEffect
import app.watchd.ui.NowWatchingBar
import app.watchd.ui.WatchSheet
import kotlinx.coroutines.delay
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import app.watchd.data.Api
import app.watchd.data.Session
import app.watchd.data.SessionStore
import app.watchd.ui.AppContext
import app.watchd.ui.DashboardScreen
import app.watchd.ui.LocalApp
import app.watchd.ui.LoginScreen
import app.watchd.ui.MovieScreen
import app.watchd.ui.SearchScreen
import app.watchd.ui.SeasonScreen
import app.watchd.ui.ShowScreen
import app.watchd.ui.theme.Watchd
import app.watchd.ui.theme.WatchdTheme
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable

@Serializable object HomeRoute
@Serializable object SearchRoute
@Serializable data class MovieRoute(val tmdbId: Int)
@Serializable data class ShowRoute(val tmdbId: Int)
@Serializable data class SeasonRoute(val showTmdbId: Int, val season: Int)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val store = SessionStore(applicationContext)
        setContent {
            WatchdTheme {
                val session by store.session.collectAsState(initial = null)
                val scope = rememberCoroutineScope()
                when (val s = session) {
                    null -> Box(Modifier.fillMaxSize())
                    else -> if (s.token == null) {
                        LoginScreen(s.server) { server, token -> scope.launch { store.signIn(server, token) } }
                    } else {
                        SignedIn(s) { scope.launch { store.signOut() } }
                    }
                }
            }
        }
    }
}

@Composable
private fun SignedIn(session: Session, signOut: () -> Unit) {
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val app = remember(session) { AppContext(Api(session.server, session.token), signOut, snackbar, scope) }
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val destination = entry?.destination
    val openShow: (Int) -> Unit = { nav.navigate(ShowRoute(it)) }
    val openMovie: (Int) -> Unit = { nav.navigate(MovieRoute(it)) }

    // Check-ins started or ended elsewhere (the site, or Watchd finishing
    // one) show up when the app comes back and once a minute.
    LifecycleResumeEffect(app) {
        app.refreshSessions()
        onPauseOrDispose {}
    }
    LaunchedEffect(app) {
        while (true) {
            delay(60_000)
            app.refreshSessions()
        }
    }

    CompositionLocalProvider(LocalApp provides app) {
        app.watchSheet?.let { (target, onChanged) ->
            WatchSheet(target, onChanged, onDismiss = { app.watchSheet = null })
        }
        Scaffold(
            containerColor = Watchd.Background,
            snackbarHost = {
                SnackbarHost(snackbar) {
                    Snackbar(it, containerColor = Watchd.SurfaceHigh, contentColor = Watchd.Text, actionColor = Watchd.Red)
                }
            },
            bottomBar = {
                Column {
                app.sessions.firstOrNull()?.let { NowWatchingBar(it, openShow, openMovie) }
                NavigationBar(containerColor = Watchd.Surface) {
                    listOf(Triple(HomeRoute, "Home", Icons.Default.Home), Triple(SearchRoute, "Search", Icons.Default.Search)).forEach { (route, label, icon) ->
                        val selected = destination?.hasRoute(route::class) == true
                        NavigationBarItem(
                            selected = selected,
                            onClick = {
                                nav.navigate(route) {
                                    popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = { Icon(icon, contentDescription = label) },
                            label = { Text(label) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = Watchd.Red, selectedTextColor = Watchd.Red,
                                indicatorColor = Watchd.SurfaceHigh,
                            ),
                        )
                    }
                }
                }
            },
        ) { padding ->
            NavHost(nav, startDestination = HomeRoute, modifier = Modifier.padding(bottom = padding.calculateBottomPadding())) {
                composable<HomeRoute> { DashboardScreen(openShow, openMovie) }
                composable<SearchRoute> { SearchScreen(openShow, openMovie) }
                composable<MovieRoute> { MovieScreen(it.toRoute<MovieRoute>().tmdbId, onBack = { nav.popBackStack() }, openMovie = openMovie) }
                composable<ShowRoute> {
                    ShowScreen(it.toRoute<ShowRoute>().tmdbId, onBack = { nav.popBackStack() }, openSeason = { show, season -> nav.navigate(SeasonRoute(show, season)) })
                }
                composable<SeasonRoute> {
                    val route = it.toRoute<SeasonRoute>()
                    SeasonScreen(route.showTmdbId, route.season, onBack = { nav.popBackStack() })
                }
            }
        }
    }
}
