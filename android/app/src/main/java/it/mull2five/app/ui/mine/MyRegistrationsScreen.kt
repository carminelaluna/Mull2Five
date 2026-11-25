package it.mull2five.app.ui.mine

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.data.Formats
import it.mull2five.app.data.MyRegistration
import it.mull2five.app.data.Registration
import it.mull2five.app.data.Tournament
import it.mull2five.app.ui.ActingBanner
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.ErrorBox
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.LoadingBox
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.SectionTitle
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.inbox.InboxAction
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.launch

/** Le proprie iscrizioni (my-registrations.html): prima quelle da giocare, poi le concluse. */
class MyRegistrationsViewModel(private val c: AppContainer) : ViewModel() {
    var state by mutableStateOf<Load<List<MyRegistration>>>(Load.Loading)
        private set
    var refreshing by mutableStateOf(false)
        private set

    fun load(pull: Boolean = false) {
        if (c.session.user.value == null) return
        viewModelScope.launch {
            if (pull) refreshing = true
            c.attempt { c.api.myRegistrations() }
                .onSuccess { state = Load.Ready(it) }
                .onFailure { if (state !is Load.Ready || pull) state = Load.Failed(c.messageOf(it)) }
            refreshing = false
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MyRegistrationsScreen(onOpen: (Int) -> Unit, onLogin: () -> Unit, onBrowse: () -> Unit) {
    val vm = appViewModel { MyRegistrationsViewModel(it) }
    val session = LocalContainer.current.session
    val user by session.user.collectAsStateWithLifecycle()
    // Con il profilo di un figlio le iscrizioni sono le sue.
    val acting by session.acting.collectAsStateWithLifecycle()
    LaunchedEffect(user, acting) { vm.load() }
    LifecycleResumeEffect(vm) {
        vm.load()
        onPauseOrDispose { }
    }
    Scaffold(topBar = { TopAppBar(title = { Text(stringResource(R.string.mine_title)) }, actions = { InboxAction() }) }) { padding ->
        val modifier = Modifier.padding(padding)
        if (user == null) {
            MessageBox(stringResource(R.string.mine_login), modifier, stringResource(R.string.login_submit), onLogin)
            return@Scaffold
        }
        Column(modifier.fillMaxSize()) {
            acting?.let { ActingBanner(it.name, onStop = { session.actAs(null) }) }
            PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = { vm.load(pull = true) }, modifier = Modifier.fillMaxSize()) {
                when (val state = vm.state) {
                    Load.Loading -> LoadingBox()
                    is Load.Failed -> ErrorBox(state.message, onRetry = { vm.load(pull = true) })
                    is Load.Ready -> {
                        val (current, past) = state.value.partition { it.tournament.status in setOf("published", "running") }
                        if (state.value.isEmpty()) {
                            MessageBox(stringResource(R.string.mine_empty), action = stringResource(R.string.mine_browse), onAction = onBrowse)
                        } else {
                            LazyColumn(
                                contentPadding = PaddingValues(16.dp),
                                verticalArrangement = Arrangement.spacedBy(10.dp),
                                modifier = Modifier.fillMaxSize(),
                            ) {
                                if (current.isNotEmpty()) {
                                    item { SectionTitle(stringResource(R.string.mine_upcoming), Modifier.padding(top = 0.dp)) }
                                    items(current.sortedBy { it.tournament.startsOn }, key = { it.registration.id }) {
                                        RegistrationCard(it, onClick = { onOpen(it.tournament.id) })
                                    }
                                }
                                if (past.isNotEmpty()) {
                                    item { SectionTitle(stringResource(R.string.mine_past)) }
                                    items(past.sortedByDescending { it.tournament.startsOn }, key = { it.registration.id }) {
                                        RegistrationCard(it, onClick = { onOpen(it.tournament.id) })
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RegistrationCard(item: MyRegistration, onClick: () -> Unit) {
    val t = item.tournament
    Surface(
        color = Brand.Panel,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(t.name, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            val time = t.startTime?.let { " · $it" }.orEmpty()
            val where = if (t.isOnline) stringResource(R.string.event_online) else t.place
            Text(
                Formats.date(t.startsOn) + time + if (where.isNotBlank()) " · $where" else "",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.size(10.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                StatusBadges(t, item.registration)
            }
        }
    }
}

/** Le etichette di un'iscrizione: stato del torneo, lista d'attesa, pagamento, check-in. */
@Composable
fun StatusBadges(t: Tournament, r: Registration) {
    when (t.status) {
        "running" -> Badge(stringResource(R.string.status_running), Tone.Ok)
        "published" -> Badge(stringResource(R.string.status_published), Tone.Accent)
        "completed" -> Badge(stringResource(R.string.status_completed))
        "cancelled" -> Badge(stringResource(R.string.status_cancelled), Tone.Danger)
    }
    if (r.waitlisted) Badge(stringResource(R.string.mine_waitlisted), Tone.Warn)
    if (r.dropped) Badge(stringResource(R.string.mine_dropped))
    if (!r.isPaid && r.amountDueCents > 0 && t.status != "completed") Badge(stringResource(R.string.mine_to_pay), Tone.Warn)
    if (r.checkedIn) Badge(stringResource(R.string.mine_checked_in), Tone.Ok)
}
