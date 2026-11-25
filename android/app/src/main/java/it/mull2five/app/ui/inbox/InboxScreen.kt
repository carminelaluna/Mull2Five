package it.mull2five.app.ui.inbox

import android.text.format.DateUtils
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.data.AppNotification
import it.mull2five.app.notify.epochMillis
import it.mull2five.app.notify.phrase
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.Loaded
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.Routes
import it.mull2five.app.ui.SubScreen
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.launch

/** Apre la campanella: lo fornisce AppRoot, lo usano le barre in alto delle schede. */
val LocalOpenInbox = staticCompositionLocalOf<() -> Unit> { {} }

/**
 * Dove porta una notifica, fra le schermate dell'app. Il server scrive percorsi
 * del sito (services/inbox.py): qui diventano rotte. Null: resta la campanella.
 */
fun routeOf(url: String): String? {
    if (!url.startsWith("/") || url.startsWith("//")) return null
    val query = url.substringAfter('?', "").split('&')
        .associate { it.substringBefore('=') to it.substringAfter('=', "") }
    val id = { name: String -> query[name]?.toIntOrNull() }
    return when (url.substringBefore('?')) {
        "/event.html" -> id("id")?.let { Routes.event(it) }
        "/my-registrations.html" -> id("t")?.let { Routes.myTournament(it) } ?: Routes.MINE
        "/tickets.html" -> Routes.TICKETS
        else -> null
    }
}

/** La campanella nella barra in alto, col numero da leggere. Solo a chi è dentro. */
@Composable
fun InboxAction() {
    val c = LocalContainer.current
    val user by c.session.user.collectAsStateWithLifecycle()
    if (user == null) return
    val unread by c.inbox.unread.collectAsStateWithLifecycle()
    val open = LocalOpenInbox.current
    val label = if (unread > 0) stringResource(R.string.inbox_unread, unread) else stringResource(R.string.inbox_title)
    IconButton(onClick = open) {
        BadgedBox(badge = { if (unread > 0) Badge { Text(if (unread > 99) "99+" else "$unread") } }) {
            Icon(Icons.Filled.Notifications, contentDescription = label)
        }
    }
}

private const val PAGE = 30

class InboxViewModel(private val c: AppContainer) : ViewModel() {
    var items by mutableStateOf<List<AppNotification>>(emptyList())
        private set
    var state by mutableStateOf<Load<Unit>>(Load.Loading)
        private set
    var hasMore by mutableStateOf(false)
        private set

    init {
        load()
    }

    /** Aperta vuol dire vista, come sul sito: il numero va a zero, l'evidenza resta. */
    fun load(more: Boolean = false) {
        viewModelScope.launch {
            c.attempt { c.api.notifications(offset = if (more) items.size else 0, limit = PAGE) }
                .onSuccess { page ->
                    items = if (more) items + page.items else page.items
                    hasMore = page.items.size == PAGE
                    state = Load.Ready(Unit)
                    if (page.unread > 0) {
                        c.attempt { c.api.markNotificationsRead() }.onSuccess { c.inbox.setUnread(it.unread) }
                    }
                }
                .onFailure { if (!more) state = Load.Failed(c.messageOf(it)) }
        }
    }
}

@Composable
fun InboxScreen(onBack: () -> Unit, onOpen: (String) -> Unit) {
    val vm = appViewModel { InboxViewModel(it) }
    val inbox = LocalContainer.current.inbox
    LaunchedEffect(Unit) { inbox.clearPosted() }
    SubScreen(title = stringResource(R.string.inbox_title), onBack = onBack) { padding ->
        val modifier = Modifier.padding(padding)
        Loaded(vm.state, onRetry = { vm.load() }, modifier) {
            if (vm.items.isEmpty()) {
                MessageBox(stringResource(R.string.inbox_empty), modifier)
                return@Loaded
            }
            LazyColumn(modifier.fillMaxSize()) {
                items(vm.items, key = { it.id }) { n ->
                    InboxRow(n, onClick = routeOf(n.url)?.let { route -> { onOpen(route) } })
                    HorizontalDivider(color = Brand.Line)
                }
                if (vm.hasMore) {
                    item {
                        TextButton(onClick = { vm.load(more = true) }, modifier = Modifier.fillMaxWidth().padding(8.dp)) {
                            Text(stringResource(R.string.inbox_more))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun InboxRow(n: AppNotification, onClick: (() -> Unit)?) {
    val context = LocalContext.current
    val where = listOf(n.context, n.title).filter { it.isNotBlank() }.joinToString(" · ")
    val whenText = epochMillis(n.createdAt)?.let {
        DateUtils.getRelativeTimeSpanString(it, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS).toString()
    }.orEmpty()
    Column(
        Modifier
            .fillMaxWidth()
            .background(if (n.read) Brand.Bg else Brand.AccentDim)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Text(
                phrase(context, n),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f),
            )
            Text(whenText, style = MaterialTheme.typography.labelSmall, color = Brand.Soft, modifier = Modifier.padding(start = 12.dp))
        }
        if (where.isNotBlank()) Text(where, style = MaterialTheme.typography.bodySmall, color = Brand.Muted)
        if (n.body.isNotBlank()) {
            Text(n.body, style = MaterialTheme.typography.bodySmall, color = Brand.Muted, maxLines = 3, overflow = TextOverflow.Ellipsis)
        }
        if (n.forName.isNotBlank()) {
            Text(stringResource(R.string.inbox_for, n.forName), style = MaterialTheme.typography.labelSmall, color = Brand.Teal)
        }
    }
}
