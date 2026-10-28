package app.watchd

import androidx.lifecycle.lifecycleScope
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsTopHeight
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.compose.LifecycleResumeEffect
import app.watchd.ui.NowWatchingBar
import app.watchd.ui.WatchSheet
import kotlinx.coroutines.delay
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Person
import app.watchd.ui.CalendarScreen
import app.watchd.ui.HistoryScreen
import app.watchd.ui.ListScreen
import app.watchd.ui.WatchlistScreen
import app.watchd.ui.YouScreen
import app.watchd.ui.StatsScreen
import app.watchd.ui.PersonScreen
import app.watchd.ui.CollectionScreen
import app.watchd.ui.AddDiscScreen
import app.watchd.ui.clearSaved
import app.watchd.ui.DiscScreen
import coil3.ImageLoader
import coil3.compose.setSingletonImageLoaderFactory
import coil3.map.Mapper
import coil3.svg.SvgDecoder
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import coil3.request.Options
import coil3.request.crossfade
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
@Serializable object CalendarRoute
@Serializable object HistoryRoute
@Serializable object YouRoute
@Serializable object WatchlistRoute
@Serializable object StatsRoute
@Serializable data class ListRoute(val id: Int)
@Serializable data class PersonRoute(val id: Int)
@Serializable object CollectionRoute
@Serializable object AddDiscRoute
@Serializable data class DiscRoute(val id: Int)

/** The signed-in server and token, for images Watchd serves itself. */
private object ImageAuth {
    @Volatile var server: String? = null
    @Volatile var token: String? = null
}

/**
 * Bare paths: Watchd's own images ("/api/proxy/physical/covers/…", your
 * disc covers) come from the server; any other "/abc.jpg" is TMDB's.
 */
private object ImagePaths : Mapper<String, String> {
    override fun map(data: String, options: Options): String? = when {
        data.startsWith("/api/") -> ImageAuth.server?.let { it.trimEnd('/') + data }
        data.startsWith("/") -> "https://image.tmdb.org/t/p/w500$data"
        else -> null
    }
}

/** Sends the token with requests to the Watchd server (its covers need it). */
private val imageClient = OkHttpClient.Builder().addInterceptor { chain ->
    val request = chain.request()
    val server = ImageAuth.server?.toHttpUrlOrNull()
    val token = ImageAuth.token
    if (server != null && token != null && request.url.host == server.host && request.url.port == server.port) {
        chain.proceed(request.newBuilder().header("Authorization", "Bearer $token").build())
    } else {
        chain.proceed(request)
    }
}.build()

class MainActivity : ComponentActivity() {
    /** A notification tap or a Share waiting to be opened. */
    private var incoming by mutableStateOf<Intent?>(null)

    // Leaving the app: the home screen widget catches up with anything ticked here.
    override fun onStop() {
        super.onStop()
        lifecycleScope.launch { NextUpWidget.refresh(applicationContext) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        incoming = intent
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) incoming = intent
        val store = SessionStore(applicationContext)
        setContent {
            setSingletonImageLoaderFactory { context ->
                ImageLoader.Builder(context).components {
                    add(ImagePaths)
                    add(SvgDecoder.Factory())
                    add(OkHttpNetworkFetcherFactory(callFactory = { imageClient }))
                }.crossfade(true).build()
            }
            WatchdTheme {
                val session by store.session.collectAsState(initial = null)
                val scope = rememberCoroutineScope()
                when (val s = session) {
                    null -> Box(Modifier.fillMaxSize())
                    else -> if (s.token == null) {
                        LoginScreen(s.server) { server, token -> scope.launch { store.signIn(server, token) } }
                    } else {
                        SignedIn(s, incoming, onHandled = { incoming = null }) { clearSaved(this@MainActivity); scope.launch { store.signOut() } }
                    }
                }
            }
        }
    }
}

@Composable
private fun SignedIn(session: Session, incoming: Intent?, onHandled: () -> Unit, signOut: () -> Unit) {
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val app = remember(session) { AppContext(Api(session.server, session.token), session.server, session.token, signOut, snackbar, scope) }
    ImageAuth.server = session.server
    ImageAuth.token = session.token
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val destination = entry?.destination
    val openShow: (Int) -> Unit = { nav.navigate(ShowRoute(it)) }
    val openMovie: (Int) -> Unit = { nav.navigate(MovieRoute(it)) }
    val openPerson: (Int) -> Unit = { nav.navigate(PersonRoute(it)) }
    val context = LocalContext.current

    // New-episode notifications: ask once (Android 13+), then check every 15 minutes.
    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
    LaunchedEffect(Unit) {
        NewEpisodesWorker.schedule(context)
        val prefs = context.getSharedPreferences("app", Context.MODE_PRIVATE)
        if (Build.VERSION.SDK_INT >= 33 && !prefs.getBoolean("asked_notifications", false) &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            prefs.edit().putBoolean("asked_notifications", true).apply()
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    // A tapped notification opens its show; a Share opens the film or show
    // it links to, or searches for the text.
    LaunchedEffect(incoming) {
        val intent = incoming ?: return@LaunchedEffect
        // Cleared only once handled: clearing it first would cancel the IMDb lookup.
        val show = intent.getIntExtra(NewEpisodesWorker.EXTRA_SHOW, 0)
        val film = intent.getIntExtra(NewEpisodesWorker.EXTRA_MOVIE, 0)
        if (show > 0) {
            openShow(show)
        } else if (film > 0) {
            openMovie(film)
        } else if (intent.action == Intent.ACTION_SEND) {
            val text = listOfNotNull(intent.getStringExtra(Intent.EXTRA_TEXT), intent.getStringExtra(Intent.EXTRA_SUBJECT)).joinToString(" ")
            when (val target = shareTarget(text, app.api)) {
                is ShareTarget.Film -> openMovie(target.tmdbId)
                is ShareTarget.Show -> openShow(target.tmdbId)
                is ShareTarget.Search -> {
                    app.searchPrefill = target.query
                    nav.navigate(SearchRoute) { launchSingleTop = true }
                }
            }
        }
        onHandled()
    }

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
        UpdateCheck()
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
                    listOf(
                        Triple(HomeRoute, "Home", Icons.Default.Home),
                        Triple(CalendarRoute, "Calendar", Icons.Default.CalendarMonth),
                        Triple(SearchRoute, "Search", Icons.Default.Search),
                        Triple(HistoryRoute, "History", Icons.Default.History),
                        Triple(YouRoute, "You", Icons.Default.Person),
                    ).forEach { (route, label, icon) ->
                        val selected = destination?.hasRoute(route::class) == true
                        NavigationBarItem(
                            selected = selected,
                            onClick = {
                                // Already in this tab (or it's Home, which is always beneath):
                                // go back to its main page rather than restoring the page
                                // opened from it, such as the disc collection from Home.
                                if (nav.popBackStack(route, inclusive = false)) return@NavigationBarItem
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
                composable<HomeRoute> { DashboardScreen(openShow, openMovie, openCollection = { nav.navigate(CollectionRoute) }) }
                composable<SearchRoute> { SearchScreen(openShow, openMovie) }
                composable<CalendarRoute> { CalendarScreen(openShow, openMovie) }
                composable<HistoryRoute> { HistoryScreen(openShow, openMovie) }
                composable<YouRoute> { YouScreen(openWatchlist = { nav.navigate(WatchlistRoute) }, openList = { nav.navigate(ListRoute(it)) }, openStats = { nav.navigate(StatsRoute) }) }
                composable<StatsRoute> { StatsScreen(onBack = { nav.popBackStack() }) }
                composable<PersonRoute> { PersonScreen(it.toRoute<PersonRoute>().id, onBack = { nav.popBackStack() }, openShow = openShow, openMovie = openMovie) }
                composable<CollectionRoute> { CollectionScreen(onBack = { nav.popBackStack() }, openDisc = { nav.navigate(DiscRoute(it)) }, addDisc = { nav.navigate(AddDiscRoute) }) }
                composable<AddDiscRoute> {
                    // The new (or already owned) disc replaces this screen, so Back goes to the collection.
                    AddDiscScreen(onBack = { nav.popBackStack() }, openDisc = { id -> nav.navigate(DiscRoute(id)) { popUpTo<AddDiscRoute> { inclusive = true } } })
                }
                composable<DiscRoute> { DiscScreen(it.toRoute<DiscRoute>().id, onBack = { nav.popBackStack() }, openDisc = { id -> nav.navigate(DiscRoute(id)) }, openShow = openShow, openMovie = openMovie) }
                composable<WatchlistRoute> { WatchlistScreen(onBack = { nav.popBackStack() }, openMovie = openMovie) }
                composable<ListRoute> { ListScreen(it.toRoute<ListRoute>().id, onBack = { nav.popBackStack() }, openShow = openShow, openMovie = openMovie) }
                composable<MovieRoute> { MovieScreen(it.toRoute<MovieRoute>().tmdbId, onBack = { nav.popBackStack() }, openMovie = openMovie, openPerson = openPerson) }
                composable<ShowRoute> {
                    ShowScreen(it.toRoute<ShowRoute>().tmdbId, onBack = { nav.popBackStack() }, openSeason = { show, season -> nav.navigate(SeasonRoute(show, season)) }, openPerson = openPerson)
                }
                composable<SeasonRoute> {
                    val route = it.toRoute<SeasonRoute>()
                    SeasonScreen(route.showTmdbId, route.season, onBack = { nav.popBackStack() })
                }
            }
            // Behind the clock and battery on list pages, so content scrolls
            // under a solid strip; film and show pages draw their own bar.
            val detail = destination?.let { d -> d.hasRoute(MovieRoute::class) || d.hasRoute(ShowRoute::class) || d.hasRoute(SeasonRoute::class) || d.hasRoute(DiscRoute::class) } == true
            if (!detail) {
                Box(Modifier.fillMaxWidth().windowInsetsTopHeight(WindowInsets.statusBars).background(Watchd.Background.copy(alpha = 0.94f)))
            }
        }
    }
}
