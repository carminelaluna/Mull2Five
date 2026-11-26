package it.mull2five.app.ui

import android.Manifest
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
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
import androidx.navigation.NavBackStackEntry
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
import it.mull2five.app.ui.account.AccountScreen
import it.mull2five.app.ui.decks.DeckEditorScreen
import it.mull2five.app.ui.decks.DecksScreen
import it.mull2five.app.ui.discover.ArchiveDeckScreen
import it.mull2five.app.ui.discover.CircuitScreen
import it.mull2five.app.ui.discover.DiscoverScreen
import it.mull2five.app.ui.discover.ManifestationScreen
import it.mull2five.app.ui.discover.StoreScreen
import it.mull2five.app.ui.event.EventScreen
import it.mull2five.app.ui.events.EventsScreen
import it.mull2five.app.ui.inbox.InboxScreen
import it.mull2five.app.ui.inbox.LocalOpenInbox
import it.mull2five.app.ui.inbox.routeOf
import it.mull2five.app.ui.login.AuthEvent
import it.mull2five.app.ui.login.AuthViewModel
import it.mull2five.app.ui.login.GoogleSignupScreen
import it.mull2five.app.ui.login.LoginScreen
import it.mull2five.app.ui.mine.MyRegistrationsScreen
import it.mull2five.app.ui.mine.MyTournamentScreen
import it.mull2five.app.ui.profile.ProfileScreen
import it.mull2five.app.ui.profile.StatsScreen
import it.mull2five.app.ui.results.ResultsScreen
import it.mull2five.app.ui.tickets.NewTicketScreen
import it.mull2five.app.ui.tickets.TicketScreen
import it.mull2five.app.ui.tickets.TicketsScreen
import kotlinx.coroutines.flow.first

object Routes {
    const val EVENTS = "eventi"
    const val DISCOVER = "scopri"
    const val MINE = "iscrizioni"
    const val PROFILE = "profilo"
    const val LOGIN = "accesso"
    const val GOOGLE_SIGNUP = "google"
    const val EVENT = "evento/{id}?iscriviti={iscriviti}"
    const val MY_TOURNAMENT = "torneo/{id}"
    const val RESULTS = "risultati/{id}"
    const val STORE = "negozio/{slug}"
    const val CIRCUIT = "circuito/{slug}"
    const val MANIFESTATION = "manifestazione/{slug}"
    const val ARCHIVE_DECK = "lista-archivio/{id}"
    const val STATS = "statistiche"
    const val DECKS = "liste"
    const val DECK_EDITOR = "lista/{id}"
    const val ACCOUNT = "account"
    const val TICKETS = "segnalazioni"
    const val TICKET = "segnalazione/{id}"
    const val NEW_TICKET = "nuova-segnalazione?profilo={profilo}"
    const val INBOX = "campanella"

    fun event(id: Int, register: Boolean = false) = "evento/$id?iscriviti=$register"
    fun myTournament(id: Int) = "torneo/$id"
    fun results(id: Int) = "risultati/$id"
    fun store(slug: String) = "negozio/${Uri.encode(slug)}"
    fun circuit(slug: String) = "circuito/${Uri.encode(slug)}"
    fun manifestation(slug: String) = "manifestazione/${Uri.encode(slug)}"
    fun archiveDeck(id: Int) = "lista-archivio/$id"

    /** 0 è una lista nuova. */
    fun deckEditor(id: Int) = "lista/$id"
    fun ticket(id: Int) = "segnalazione/$id"
    fun newTicket(profileRequest: Boolean = false) = "nuova-segnalazione?profilo=$profileRequest"
}

private data class TabItem(val route: String, val icon: ImageVector, @StringRes val label: Int)

private val tabs = listOf(
    TabItem(Routes.EVENTS, Icons.Filled.DateRange, R.string.tab_events),
    TabItem(Routes.DISCOVER, Icons.Filled.Search, R.string.tab_discover),
    TabItem(Routes.MINE, Icons.AutoMirrored.Filled.List, R.string.tab_mine),
    TabItem(Routes.PROFILE, Icons.Filled.Person, R.string.tab_profile),
)

private val idArgument = listOf(navArgument("id") { type = NavType.IntType })
private val slugArgument = listOf(navArgument("slug") { type = NavType.StringType })

private fun NavBackStackEntry.id(): Int = arguments?.getInt("id") ?: 0
private fun NavBackStackEntry.slug(): String = arguments?.getString("slug").orEmpty()

@Composable
fun AppRoot(container: AppContainer) {
    val nav = rememberNavController()
    CompositionLocalProvider(LocalContainer provides container, LocalOpenInbox provides { nav.navigate(Routes.INBOX) }) {
        // Fuori dal NavHost: l'accesso vale per tutta l'attività, e il ritorno da
        // Google può arrivare mentre si guarda qualunque schermata.
        val auth = appViewModel { AuthViewModel(it) }
        // Una scheda si raggiunge cambiando scheda, il resto aprendolo sopra.
        val openRoute: (String) -> Unit = { route ->
            if (tabs.any { it.route == route }) nav.switchTab(route) else nav.navigate(route)
        }

        val incoming by container.incoming.collectAsStateWithLifecycle()
        LaunchedEffect(incoming) {
            // Il NavHost sta dentro lo Scaffold e prende il grafo poco dopo: lo si aspetta.
            nav.currentBackStackEntryFlow.first()
            when (val link = incoming) {
                is Incoming.OpenTournament -> nav.navigate(Routes.event(link.id, link.register))
                is Incoming.GoogleReturn -> auth.finishGoogle(link)
                is Incoming.FromBell -> {
                    openRoute(routeOf(link.url) ?: Routes.INBOX)
                    if (link.id > 0) {
                        container.attempt { container.api.markNotificationsRead(listOf(link.id)) }
                            .onSuccess { container.inbox.setUnread(it.unread) }
                    }
                }
                null -> return@LaunchedEffect
            }
            container.incoming.value = null
        }

        // Appena si entra: il numero sulla campanella e, da Android 13, il permesso
        // per le notifiche del telefono, chiesto una volta sola.
        val user by container.session.user.collectAsStateWithLifecycle()
        val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
        LaunchedEffect(user?.id) {
            if (user == null) return@LaunchedEffect
            // Prima di registrare il telefono: `showNew` segna il punto di partenza
            // della campanella. Senza, il primo messaggio che arriva — l'iscrizione
            // appena fatta — verrebbe preso per quel punto e non comparirebbe fra
            // le notifiche del telefono.
            container.attempt { container.inbox.showNew() }
            // Con Firebase, il server sveglia questo telefono per chi è appena entrato.
            container.attempt { container.inbox.registerDevice() }
            if (container.inbox.needsPermissionPrompt()) {
                container.inbox.permissionAsked()
                askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
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
        val back: () -> Unit = { nav.popBackStack() }
        val openEvent: (Int) -> Unit = { nav.navigate(Routes.event(it)) }
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
                    EventsScreen(onOpen = openEvent)
                }
                composable(
                    Routes.EVENT,
                    arguments = listOf(
                        navArgument("id") { type = NavType.IntType },
                        navArgument("iscriviti") { type = NavType.BoolType; defaultValue = false },
                    ),
                ) { backStack ->
                    val id = backStack.id()
                    EventScreen(
                        id = id,
                        openRegistration = backStack.arguments?.getBoolean("iscriviti") == true,
                        onBack = back,
                        // Al ritorno dall'accesso la pagina apre da sola il modulo d'iscrizione.
                        onLogin = { nav.navigate(Routes.LOGIN) },
                        onOpenMine = { nav.navigate(Routes.myTournament(id)) },
                        onResults = { nav.navigate(Routes.results(id)) },
                        onStore = { nav.navigate(Routes.store(it)) },
                        onCircuit = { nav.navigate(Routes.circuit(it)) },
                        onManifestation = { nav.navigate(Routes.manifestation(it)) },
                    )
                }
                composable(Routes.RESULTS, arguments = idArgument) { backStack ->
                    val id = backStack.id()
                    ResultsScreen(id, onBack = back, onEvent = { openEvent(id) })
                }

                composable(Routes.DISCOVER) {
                    DiscoverScreen(
                        onStore = { nav.navigate(Routes.store(it)) },
                        onCircuit = { nav.navigate(Routes.circuit(it)) },
                        onDeck = { nav.navigate(Routes.archiveDeck(it)) },
                    )
                }
                composable(Routes.STORE, arguments = slugArgument) { backStack ->
                    StoreScreen(backStack.slug(), onBack = back, onEvent = openEvent)
                }
                composable(Routes.CIRCUIT, arguments = slugArgument) { backStack ->
                    CircuitScreen(backStack.slug(), onBack = back, onEvent = openEvent)
                }
                composable(Routes.MANIFESTATION, arguments = slugArgument) { backStack ->
                    ManifestationScreen(backStack.slug(), onBack = back, onEvent = openEvent)
                }
                composable(Routes.ARCHIVE_DECK, arguments = idArgument) { backStack ->
                    ArchiveDeckScreen(backStack.id(), onBack = back, onResults = { nav.navigate(Routes.results(it)) })
                }

                composable(Routes.MINE) {
                    MyRegistrationsScreen(
                        onOpen = { nav.navigate(Routes.myTournament(it)) },
                        onLogin = { nav.navigate(Routes.LOGIN) },
                        onBrowse = { nav.switchTab(Routes.EVENTS) },
                    )
                }
                composable(Routes.MY_TOURNAMENT, arguments = idArgument) { backStack ->
                    val id = backStack.id()
                    MyTournamentScreen(
                        id = id,
                        onBack = back,
                        onOpenEvent = { openEvent(id) },
                        onResults = { nav.navigate(Routes.results(id)) },
                    )
                }

                composable(Routes.PROFILE) {
                    ProfileScreen(
                        onLogin = { nav.navigate(Routes.LOGIN) },
                        onStats = { nav.navigate(Routes.STATS) },
                        onDecks = { nav.navigate(Routes.DECKS) },
                        onTickets = { nav.navigate(Routes.TICKETS) },
                        onAccount = { nav.navigate(Routes.ACCOUNT) },
                    )
                }
                composable(Routes.STATS) {
                    StatsScreen(onBack = back, onTournament = { id, completed ->
                        nav.navigate(if (completed) Routes.results(id) else Routes.event(id))
                    })
                }
                composable(Routes.DECKS) {
                    DecksScreen(onBack = back, onOpen = { nav.navigate(Routes.deckEditor(it)) })
                }
                composable(Routes.DECK_EDITOR, arguments = idArgument) { backStack ->
                    DeckEditorScreen(backStack.id(), onBack = back)
                }
                composable(Routes.ACCOUNT) {
                    AccountScreen(
                        onBack = back,
                        onRequestProfile = { nav.navigate(Routes.newTicket(profileRequest = true)) },
                        onSignedOut = back,
                    )
                }
                composable(Routes.TICKETS) {
                    TicketsScreen(
                        onBack = back,
                        onOpen = { nav.navigate(Routes.ticket(it)) },
                        onNew = { nav.navigate(Routes.newTicket()) },
                    )
                }
                composable(Routes.TICKET, arguments = idArgument) { backStack ->
                    TicketScreen(backStack.id(), onBack = back)
                }
                composable(
                    Routes.NEW_TICKET,
                    arguments = listOf(navArgument("profilo") { type = NavType.BoolType; defaultValue = false }),
                ) { backStack ->
                    NewTicketScreen(
                        profileRequest = backStack.arguments?.getBoolean("profilo") == true,
                        onBack = back,
                        // Aperta la segnalazione, si va alla conversazione al posto del modulo.
                        onCreated = { id ->
                            nav.popBackStack()
                            nav.navigate(Routes.ticket(id))
                        },
                    )
                }

                composable(Routes.INBOX) {
                    InboxScreen(onBack = back, onOpen = openRoute)
                }

                composable(Routes.LOGIN) {
                    LoginScreen(auth, onBack = back)
                }
                composable(Routes.GOOGLE_SIGNUP) {
                    GoogleSignupScreen(auth, onBack = back)
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
