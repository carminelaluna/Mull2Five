package it.mull2five.app.ui.tickets

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.data.Formats
import it.mull2five.app.data.Ticket
import it.mull2five.app.data.TicketIn
import it.mull2five.app.data.TicketMessage
import it.mull2five.app.data.Tournament
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.Loaded
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.Notice
import it.mull2five.app.ui.SubScreen
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.UiText
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.event.Choice
import it.mull2five.app.ui.login.SubmitButton
import it.mull2five.app.ui.rememberLoad
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

@Composable
private fun StatusBadge(status: String) = when (status) {
    "answered" -> Badge(stringResource(R.string.ticket_answered), Tone.Ok)
    "closed" -> Badge(stringResource(R.string.ticket_closed))
    else -> Badge(stringResource(R.string.ticket_open), Tone.Warn)
}

@Composable
private fun recipient(t: Ticket): String =
    if (t.scope == "organizer") stringResource(R.string.ticket_to_organizer, t.tournamentName.orEmpty())
    else stringResource(R.string.ticket_to_site)

// ── Le mie segnalazioni ───────────────────────────────────────────────────

/** Le segnalazioni aperte (tickets.html): a un organizzatore o a chi tiene il sito. */
@Composable
fun TicketsScreen(onBack: () -> Unit, onOpen: (Int) -> Unit, onNew: () -> Unit) {
    val vm = rememberLoad("segnalazioni") { it.api.tickets() }
    LifecycleResumeEffect(vm) {
        vm.load()
        onPauseOrDispose { }
    }
    SubScreen(
        stringResource(R.string.tickets_title),
        onBack,
        floating = {
            ExtendedFloatingActionButton(
                onClick = onNew,
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text(stringResource(R.string.tickets_new)) },
            )
        },
    ) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { tickets ->
            if (tickets.isEmpty()) {
                MessageBox(stringResource(R.string.tickets_empty), Modifier.padding(padding))
            } else {
                LazyColumn(
                    Modifier.padding(padding).fillMaxSize(),
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 96.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(tickets.sortedByDescending { it.updatedAt }, key = { it.id }) { t ->
                        Surface(
                            color = Brand.Panel,
                            shape = RoundedCornerShape(16.dp),
                            modifier = Modifier.fillMaxWidth().clickable { onOpen(t.id) },
                        ) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        t.subject,
                                        Modifier.weight(1f),
                                        style = MaterialTheme.typography.titleMedium,
                                        maxLines = 2,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    StatusBadge(t.status)
                                }
                                Text(
                                    recipient(t) + " · " + Formats.date(t.updatedAt),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── Una segnalazione ──────────────────────────────────────────────────────

class TicketViewModel(private val c: AppContainer, private val id: Int) : ViewModel() {
    var state by mutableStateOf<Load<Ticket>>(Load.Loading)
        private set
    var reply by mutableStateOf("")
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<UiText?>(null)
        private set
    val me: Int? get() = c.session.user.value?.id

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            c.attempt { c.api.ticket(id) }
                .onSuccess { state = Load.Ready(it) }
                .onFailure { if (state !is Load.Ready) state = Load.Failed(c.messageOf(it)) }
        }
    }

    fun send() = act {
        state = Load.Ready(c.api.replyTicket(id, reply.trim()))
        reply = ""
    }

    fun close() = act { state = Load.Ready(c.api.closeTicket(id)) }
    fun reopen() = act { state = Load.Ready(c.api.reopenTicket(id)) }

    private fun act(block: suspend () -> Unit) {
        if (busy) return
        busy = true
        error = null
        viewModelScope.launch {
            c.attempt { block() }.onFailure { error = UiText.Raw(c.messageOf(it)) }
            busy = false
        }
    }
}

@Composable
fun TicketScreen(id: Int, onBack: () -> Unit) {
    val vm = appViewModel(key = "segnalazione-$id") { TicketViewModel(it, id) }
    val title = (vm.state as? Load.Ready)?.value?.subject ?: stringResource(R.string.tickets_title)
    SubScreen(title, onBack) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { t ->
            Column(Modifier.padding(padding).fillMaxSize().imePadding()) {
                LazyColumn(
                    Modifier.weight(1f).fillMaxWidth(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item(key = "testa") {
                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(t.subject, style = MaterialTheme.typography.headlineSmall)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    recipient(t),
                                    Modifier.weight(1f),
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                StatusBadge(t.status)
                            }
                        }
                    }
                    items(t.messages, key = { it.id }) { Bubble(it, mine = it.authorId == vm.me) }
                }
                Notice(vm.error, isError = true, modifier = Modifier.padding(horizontal = 16.dp))
                Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (t.status == "closed") {
                        Text(stringResource(R.string.ticket_closed_text), color = MaterialTheme.colorScheme.onSurfaceVariant)
                        TextButton(onClick = vm::reopen, enabled = !vm.busy) { Text(stringResource(R.string.ticket_reopen)) }
                    } else {
                        OutlinedTextField(
                            vm.reply,
                            { vm.reply = it.take(4000) },
                            label = { Text(stringResource(R.string.ticket_reply)) },
                            minLines = 2,
                            maxLines = 6,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        SubmitButton(stringResource(R.string.send), vm.busy, enabled = vm.reply.isNotBlank()) { vm.send() }
                        TextButton(onClick = vm::close, enabled = !vm.busy) { Text(stringResource(R.string.ticket_close)) }
                    }
                }
            }
        }
    }
}

/** Un messaggio: i propri a destra, quelli dell'altro a sinistra. */
@Composable
private fun Bubble(m: TicketMessage, mine: Boolean) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        Surface(
            color = if (mine) Brand.AccentDim else Brand.Panel,
            shape = RoundedCornerShape(14.dp),
            modifier = Modifier.widthIn(max = 320.dp),
        ) {
            Column(Modifier.padding(12.dp)) {
                Text(
                    listOf(m.authorName, Formats.date(m.createdAt), Formats.time(m.createdAt)).filter { it.isNotBlank() }.joinToString(" · "),
                    style = MaterialTheme.typography.labelSmall,
                    color = if (mine) Brand.Accent else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(4.dp))
                Text(m.body, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

// ── Una segnalazione nuova ────────────────────────────────────────────────

class NewTicketViewModel(private val c: AppContainer, profileRequest: Boolean) : ViewModel() {
    var scope by mutableStateOf("admin")
    var tournament by mutableStateOf<Tournament?>(null)
    var subject by mutableStateOf("")
    var body by mutableStateOf("")
    var tournaments by mutableStateOf<List<Tournament>>(emptyList())
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<UiText?>(null)
        private set

    private val _created = Channel<Int>(Channel.BUFFERED)
    val created = _created.receiveAsFlow()

    init {
        if (!profileRequest) {
            // Come tickets.js: si scrive all'organizzatore di un torneo a cui si è iscritti, o al sito.
            viewModelScope.launch {
                tournaments = c.attempt { c.api.myRegistrations() }.getOrDefault(emptyList())
                    .map { it.tournament }.sortedByDescending { it.startsOn }
                if (tournaments.isNotEmpty()) {
                    scope = "organizer"
                    tournament = tournaments.first()
                }
            }
        }
    }

    fun send() {
        if (busy) return
        if (subject.trim().length < 3 || body.trim().length < 3) {
            error = UiText.Res(R.string.ticket_needs_text)
            return
        }
        busy = true
        error = null
        viewModelScope.launch {
            val toOrganizer = scope == "organizer" && tournament != null
            c.attempt {
                c.api.openTicket(
                    TicketIn(
                        scope = if (toOrganizer) "organizer" else "admin",
                        tournamentId = if (toOrganizer) tournament?.id else null,
                        subject = subject.trim(),
                        body = body.trim(),
                    ),
                )
            }.onSuccess { _created.send(it.id) }
                .onFailure { error = UiText.Raw(c.messageOf(it)) }
            busy = false
        }
    }
}

@Composable
fun NewTicketScreen(profileRequest: Boolean, onBack: () -> Unit, onCreated: (Int) -> Unit) {
    val vm = appViewModel(key = "nuova-$profileRequest") { NewTicketViewModel(it, profileRequest) }
    val profileSubject = stringResource(R.string.ticket_profile_subject)
    val profileBody = stringResource(R.string.ticket_profile_body)
    LaunchedEffect(vm) {
        if (profileRequest && vm.subject.isEmpty()) {
            vm.subject = profileSubject
            vm.body = profileBody
        }
        vm.created.collect(onCreated)
    }
    SubScreen(stringResource(R.string.tickets_new), onBack) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(stringResource(R.string.ticket_to), style = MaterialTheme.typography.labelLarge)
            if (vm.tournaments.isNotEmpty()) {
                Choice(stringResource(R.string.ticket_scope_organizer), selected = vm.scope == "organizer") { vm.scope = "organizer" }
            }
            Choice(stringResource(R.string.ticket_scope_site), selected = vm.scope == "admin") { vm.scope = "admin" }
            if (vm.scope == "organizer") {
                Text(stringResource(R.string.ticket_which_tournament), style = MaterialTheme.typography.labelLarge)
                vm.tournaments.forEach { t ->
                    Choice("${t.name} · ${Formats.date(t.startsOn)}", selected = vm.tournament?.id == t.id) { vm.tournament = t }
                }
            }
            OutlinedTextField(
                vm.subject,
                { vm.subject = it.take(180) },
                label = { Text(stringResource(R.string.ticket_subject)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                vm.body,
                { vm.body = it.take(4000) },
                label = { Text(stringResource(R.string.ticket_body)) },
                minLines = 5,
                modifier = Modifier.fillMaxWidth(),
            )
            Notice(vm.error, isError = true)
            SubmitButton(stringResource(R.string.send), vm.busy) { vm.send() }
        }
    }
}
