package it.mull2five.app.ui

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import it.mull2five.app.AppContainer
import it.mull2five.app.Incoming
import it.mull2five.app.R
import it.mull2five.app.ui.event.EventScreen
import it.mull2five.app.ui.events.EventsScreen
import it.mull2five.app.ui.login.AuthEvent
import it.mull2five.app.ui.login.AuthViewModel
import it.mull2five.app.ui.login.GoogleSignupScreen
import it.mull2five.app.ui.login.LoginScreen
import it.mull2five.app.ui.mine.MyRegistrationsScreen
import it.mull2five.app.ui.mine.MyTournamentScreen
import it.mull2five.app.ui.profile.ProfileScreen
import kotlinx.coroutines.flow.first

object Routes {
    const val EVENTS = "eventi"
    const val MINE = "iscrizioni"
    const val PROFILE = "profilo"
    const val LOGIN = "accesso"
    const val GOOGLE_SIGNUP = "google"
    const val EVENT = "evento/{id}?iscriviti={iscriviti}"
    const val MY_TOURNAMENT = "torneo/{id}"

    fun event(id: Int, register: Boolean = false) = "evento/$id?iscriviti=$register"
    fun myTournament(id: Int) = "torneo/$id"
}

private data class TabItem(val route: String, val icon: ImageVector, @StringRes val label: Int)

private val tabs = listOf(
    TabItem(Routes.EVENTS, Icons.Filled.DateRange, R.string.tab_events),
    TabItem(Routes.MINE, Icons.AutoMirrored.Filled.List, R.string.tab_mine),
    TabItem(Routes.PROFILE, Icons.Filled.Person, R.string.tab_profile),
)

@Composable
fun AppRoot(container: AppContainer) {
    CompositionLocalProvider(LocalContainer provides container) {
        val nav = rememberNavController()
        // Fuori dal NavHost: l'accesso vale per tutta l'attività, e il ritorno da
        // Google può arrivare mentre si guarda qualunque schermata.
        val auth = appViewModel { AuthViewModel(it) }

        val incoming by container.incoming.collectAsStateWithLifecycle()
        LaunchedEffect(incoming) {
            // Il NavHost sta dentro lo Scaffold e prende il grafo poco dopo: lo si aspetta.
            nav.currentBackStackEntryFlow.first()
            when (val link = incoming) {
                is Incoming.OpenTournament -> nav.navigate(Routes.event(link.id, link.register))
                is Incoming.GoogleReturn -> auth.finishGoogle(link)
                null -> return@LaunchedEffect
            }
            container.incoming.value = null
        }
        LaunchedEffect(auth) {
            nav.currentBackStackEntryFlow.first()
            auth.events.collect { event ->
                when (event) {
                    AuthEvent.SignedIn -> {
                        nav.popBackStack(Routes.GOOGLE_SIGNUP, inclusive = true)
                        nav.popBackStack(Routes.LOGIN, inclusive = true)
                    }
                    AuthEvent.NeedsGoogleSignup -> nav.navigate(Routes.GOOGLE_SIGNUP)
                }
            }
        }

        val entry by nav.currentBackStackEntryAsState()
        val route = entry?.destination?.route
        Scaffold(
            contentWindowInsets = WindowInsets(0),
            bottomBar = { if (tabs.any { it.route == route }) TabBar(nav, route) },
        ) { padding ->
            NavHost(
                nav,
                startDestination = Routes.EVENTS,
                modifier = Modifier.padding(padding).consumeWindowInsets(padding),
            ) {
                composable(Routes.EVENTS) {
                    EventsScreen(onOpen = { nav.navigate(Routes.event(it)) })
                }
                composable(
                    Routes.EVENT,
                    arguments = listOf(
                        navArgument("id") { type = NavType.IntType },
                        navArgument("iscriviti") { type = NavType.BoolType; defaultValue = false },
                    ),
                ) { backStack ->
                    val id = backStack.arguments?.getInt("id") ?: 0
                    EventScreen(
                        id = id,
                        openRegistration = backStack.arguments?.getBoolean("iscriviti") == true,
                        onBack = { nav.popBackStack() },
                        // Al ritorno dall'accesso la pagina apre da sola il modulo d'iscrizione.
                        onLogin = { nav.navigate(Routes.LOGIN) },
                        onOpenMine = { nav.navigate(Routes.myTournament(id)) },
                    )
                }
                composable(Routes.MINE) {
                    MyRegistrationsScreen(
                        onOpen = { nav.navigate(Routes.myTournament(it)) },
                        onLogin = { nav.navigate(Routes.LOGIN) },
                        onBrowse = { nav.switchTab(Routes.EVENTS) },
                    )
                }
                composable(Routes.MY_TOURNAMENT, arguments = listOf(navArgument("id") { type = NavType.IntType })) { backStack ->
                    val id = backStack.arguments?.getInt("id") ?: 0
                    MyTournamentScreen(
                        id = id,
                        onBack = { nav.popBackStack() },
                        onOpenEvent = { nav.navigate(Routes.event(id)) },
                    )
                }
                composable(Routes.PROFILE) {
                    ProfileScreen(onLogin = { nav.navigate(Routes.LOGIN) })
                }
                composable(Routes.LOGIN) {
                    LoginScreen(auth, onBack = { nav.popBackStack() })
                }
                composable(Routes.GOOGLE_SIGNUP) {
                    GoogleSignupScreen(auth, onBack = { nav.popBackStack() })
                }
            }
        }
    }
}

@Composable
private fun TabBar(nav: NavHostController, route: String?) {
    NavigationBar {
        tabs.forEach { tab ->
            NavigationBarItem(
                selected = route == tab.route,
                onClick = { nav.switchTab(tab.route) },
                icon = { Icon(tab.icon, contentDescription = null) },
                label = { Text(stringResource(tab.label)) },
            )
        }
    }
}

/** Le schede in basso tengono ognuna la sua storia, come nelle app di sistema. */
private fun NavHostController.switchTab(route: String) {
    navigate(route) {
        popUpTo(graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
