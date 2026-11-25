package it.mull2five.app.ui.mine

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.data.ApiException
import it.mull2five.app.data.DecklistIn
import it.mull2five.app.data.Formats
import it.mull2five.app.data.Pairing
import it.mull2five.app.data.Registration
import it.mull2five.app.data.ResultIn
import it.mull2five.app.data.Round
import it.mull2five.app.data.SavedDeck
import it.mull2five.app.data.Scores
import it.mull2five.app.data.Standing
import it.mull2five.app.data.SubmittedDeck
import it.mull2five.app.data.Tournament
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.DeckText
import it.mull2five.app.ui.ErrorBox
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.LoadingBox
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.Panel
import it.mull2five.app.ui.SectionTitle
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.UiText
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.asString
import it.mull2five.app.ui.event.Choice
import it.mull2five.app.ui.login.SubmitButton
import it.mull2five.app.ui.openExternal
import it.mull2five.app.ui.openInTab
import it.mull2five.app.ui.rememberTextFilePicker
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

data class MyTournament(
    val tournament: Tournament,
    val registration: Registration,
    val round: Round?,
    val standings: List<Standing>,
    /** L'ultimo turno con tutti i tavoli, se l'organizzatore pubblica gli abbinamenti. */
    val allRound: Round? = null,
) {
    /** Negli eventi ufficiali l'ID presso l'editore serve per risultati e inviti. */
    val official: Boolean
        get() = tournament.eventType in setOf("rcq", "store_championship", "premier") || tournament.invites > 0

    /** Il proprio tavolo nell'ultimo turno: si cerca per iscrizione, i nomi possono ripetersi. */
    val pairing: Pairing?
        get() = round?.pairings?.firstOrNull {
            it.playerARegistrationId == registration.id || it.playerBRegistrationId == registration.id
        }
}

sealed interface TournamentEffect {
    data class Open(val url: String) : TournamentEffect
    data object Closed : TournamentEffect
}

/** Il proprio torneo, mentre si gioca: check-in, pagamento, lista, tavolo, risultato, classifica. */
class MyTournamentViewModel(private val c: AppContainer, private val id: Int) : ViewModel() {
    var state by mutableStateOf<Load<MyTournament>>(Load.Loading)
        private set
    var busy by mutableStateOf(false)
        private set
    var message by mutableStateOf<UiText?>(null)
        private set
    var messageIsError by mutableStateOf(false)
        private set
    var decks by mutableStateOf<List<SavedDeck>?>(null)
        private set

    /** La lista già consegnata per ogni segmento, per ripartire da lì quando la si cambia. */
    var currentDecks by mutableStateOf<Map<String, String>>(emptyMap())
        private set

    /** La lista consegnata che si sta guardando. */
    var shownDeck by mutableStateOf<SubmittedDeck?>(null)
        private set

    private val _effects = Channel<TournamentEffect>(Channel.BUFFERED)
    val effects = _effects.receiveAsFlow()

    init {
        // A torneo in corso i turni cambiano da soli: ogni mezzo minuto si riguarda.
        viewModelScope.launch {
            while (true) {
                delay(30_000)
                if ((state as? Load.Ready)?.value?.tournament?.status == "running") load(quiet = true)
            }
        }
    }

    fun load(quiet: Boolean = false) {
        viewModelScope.launch {
            if (!quiet && state !is Load.Ready) state = Load.Loading
            c.attempt {
                val t = c.api.tournament(id)
                val registration = c.api.myRegistration(id)
                    ?: throw ApiException(404, c.texts.translate("Iscrizione non trovata"))
                val round = c.attempt { c.api.myPairings(id) }.getOrNull()?.lastOrNull()
                // La classifica può essere nascosta dall'organizzatore: allora non c'è.
                val started = t.status == "running" || t.status == "completed"
                val standings = if (started) c.attempt { c.api.standings(id) }.getOrDefault(emptyList()) else emptyList()
                // Anche gli abbinamenti possono essere nascosti: allora c'è solo il proprio tavolo.
                val allRound = if (started) c.attempt { c.api.rounds(id) }.getOrNull()?.maxByOrNull { it.number } else null
                MyTournament(t, registration, round, standings, allRound)
            }.onSuccess { state = Load.Ready(it) }
                .onFailure { if (!quiet || state !is Load.Ready) state = Load.Failed(c.messageOf(it)) }
        }
    }

    fun checkIn() = act(R.string.mine_checked_in_now) { c.api.selfCheckIn(id) }

    fun pay(provider: String) = act {
        val payment = c.api.checkout(id, provider)
        if (payment.checkoutUrl.isNotBlank()) _effects.send(TournamentEffect.Open(payment.checkoutUrl))
    }

    fun drop() = act(R.string.mine_dropped_now) { c.api.drop(id) }

    fun cancel() = act {
        c.api.cancel(id)
        _effects.send(TournamentEffect.Closed)
    }

    /** Il punteggio come lo vede chi lo scrive; il server lo vuole dal lato A e B del tavolo. */
    fun report(pairing: Pairing, mine: Int, theirs: Int) = act(R.string.result_sent) {
        val isA = pairing.playerARegistrationId == (state as Load.Ready).value.registration.id
        c.api.reportResult(id, pairing.id, if (isA) ResultIn(mine, theirs) else ResultIn(theirs, mine))
    }

    fun confirm(pairing: Pairing) = act(R.string.result_confirmed_now) { c.api.confirmResult(id, pairing.id) }

    fun reject(pairing: Pairing, note: String) = act(R.string.result_rejected_now) { c.api.rejectResult(id, pairing.id, note) }

    /** Se il pagamento online non si fa più: il posto torna libero subito, non fra mezz'ora. */
    fun abandonPayment() = act {
        c.api.abandonPayment(id)
        _effects.send(TournamentEffect.Closed)
    }

    fun setPublisherId(value: String) = act(R.string.mine_updated) { c.api.setPublisherId(id, value.trim()) }

    fun setGameHandle(value: String) = act(R.string.mine_updated) { c.api.setGameHandle(id, value.trim()) }

    fun openDecks(t: Tournament, hasDeck: Boolean) {
        viewModelScope.launch {
            // In modifica si riparte dalla lista già consegnata, non da un foglio bianco.
            currentDecks = if (hasDeck) {
                t.decklistFormats.associateWith { format ->
                    c.attempt { c.api.submittedDeck(id, format) }.getOrNull()?.rawText.orEmpty()
                }
            } else emptyMap()
            decks = c.attempt { c.api.decks() }.getOrDefault(emptyList()).filter { it.game == t.game }
        }
    }

    fun closeDecks() {
        decks = null
    }

    fun viewDeck(format: String) = act {
        shownDeck = c.api.submittedDeck(id, format) ?: throw ApiException(404, c.texts.translate("Lista non trovata"))
    }

    fun closeDeckView() {
        shownDeck = null
    }

    fun sendDeck(body: DecklistIn) = act(R.string.deck_sent) {
        c.api.sendDecklist(id, body)
        decks = null
    }

    private fun act(done: Int? = null, block: suspend () -> Unit) {
        if (busy) return
        busy = true
        message = null
        viewModelScope.launch {
            c.attempt { block() }
                .onSuccess { done?.let { message = UiText.Res(it); messageIsError = false } }
                .onFailure { message = UiText.Raw(c.messageOf(it)); messageIsError = true }
            busy = false
            load(quiet = true)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MyTournamentScreen(id: Int, onBack: () -> Unit, onOpenEvent: () -> Unit, onResults: () -> Unit) {
    val vm = appViewModel(key = "torneo-$id") { MyTournamentViewModel(it, id) }
    val context = LocalContext.current
    LaunchedEffect(vm) {
        vm.effects.collect {
            when (it) {
                is TournamentEffect.Open -> context.openInTab(it.url)
                TournamentEffect.Closed -> onBack()
            }
        }
    }
    LifecycleResumeEffect(vm) {
        vm.load(quiet = true)
        onPauseOrDispose { }
    }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.mine_tournament_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back)) }
                },
                actions = {
                    IconButton(onClick = { vm.load() }) { Icon(Icons.Filled.Refresh, stringResource(R.string.refresh)) }
                },
            )
        },
    ) { padding ->
        when (val state = vm.state) {
            Load.Loading -> LoadingBox(Modifier.padding(padding))
            is Load.Failed -> ErrorBox(state.message, onRetry = { vm.load() }, modifier = Modifier.padding(padding))
            is Load.Ready -> Body(state.value, vm, Modifier.padding(padding), onOpenEvent, onResults)
        }
    }
    val ready = (vm.state as? Load.Ready)?.value
    val decks = vm.decks
    if (ready != null && decks != null) {
        DeckSheet(ready.tournament, decks, vm.currentDecks, vm.busy, onDismiss = vm::closeDecks, onSend = vm::sendDeck)
    }
    vm.shownDeck?.let { deck ->
        AlertDialog(
            onDismissRequest = vm::closeDeckView,
            title = { Text(stringResource(R.string.deck_view_title) + if (deck.format.isNotBlank()) " · ${deck.format}" else "") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(stringResource(R.string.deck_counts, deck.mainCount, deck.sideCount), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (deck.validationErrors.isNotBlank()) Text(deck.validationErrors, color = MaterialTheme.colorScheme.error)
                    DeckText(deck.rawText)
                }
            },
            confirmButton = { TextButton(onClick = vm::closeDeckView) { Text(stringResource(R.string.close)) } },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Body(data: MyTournament, vm: MyTournamentViewModel, modifier: Modifier, onOpenEvent: () -> Unit, onResults: () -> Unit) {
    val t = data.tournament
    val r = data.registration
    val active = t.status == "published" || t.status == "running"
    val acting by LocalContainer.current.session.acting.collectAsStateWithLifecycle()
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        acting?.let { Text(stringResource(R.string.acting_banner, it.name), color = Brand.Accent, modifier = Modifier.padding(bottom = 8.dp)) }
        Text(t.name, style = MaterialTheme.typography.headlineSmall)
        val time = t.startTime?.let { " · $it" }.orEmpty()
        val where = if (t.isOnline) stringResource(R.string.event_online) else t.place
        Text(
            Formats.date(t.startsOn) + time + if (where.isNotBlank()) " · $where" else "",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        FlowRow(
            Modifier.padding(vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) { StatusBadges(t, r) }
        Row {
            TextButton(onClick = onOpenEvent) { Text(stringResource(R.string.mine_open_event)) }
            if (t.status == "running" || t.status == "completed") {
                TextButton(onClick = onResults) { Text(stringResource(R.string.results_open)) }
            }
        }

        vm.message?.let {
            Text(
                it.asString(),
                color = if (vm.messageIsError) MaterialTheme.colorScheme.error else Brand.Green,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        }

        val round = data.round
        val pairing = data.pairing
        if (round != null && pairing != null && !r.dropped) {
            SectionTitle(stringResource(R.string.round_title, round.number))
            PairingPanel(t, round, pairing, r, vm)
        }
        data.allRound?.takeIf { it.pairings.size > 1 }?.let { AllPairings(it, r.id) }

        SectionTitle(stringResource(R.string.mine_registration))
        Panel {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                PaymentRow(t, r, vm)
                CheckInRow(t, r, vm, active)
                DeckRow(t, r, vm)
                if (data.official) {
                    EditableLine(
                        label = stringResource(if (t.game == "mtg") R.string.register_wizards else R.string.register_player_id),
                        value = r.wizardsAccount,
                        missing = stringResource(R.string.mine_publisher_missing),
                        busy = vm.busy,
                        onSave = vm::setPublisherId,
                    )
                }
                if (t.isOnline && t.status != "completed") {
                    EditableLine(
                        label = stringResource(R.string.register_handle),
                        value = r.gameHandle,
                        missing = null,
                        busy = vm.busy,
                        onSave = vm::setGameHandle,
                    )
                }
                r.fixedTable?.let { Line(stringResource(R.string.mine_seat), stringResource(R.string.mine_fixed_table, it)) }
                r.teamName?.let { Line(stringResource(R.string.mine_team), it) }
                val link = r.onlineLink.ifBlank { t.onlineLink }
                if (link.isNotBlank()) {
                    val context = LocalContext.current
                    OutlinedButton(onClick = { context.openExternal(link) }) { Text(stringResource(R.string.mine_online_link)) }
                }
            }
        }

        if (data.standings.isNotEmpty()) {
            SectionTitle(stringResource(R.string.standings_title))
            Standings(data.standings, r.id)
        }

        if (active && !r.dropped) Leave(t, vm)
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun PairingPanel(t: Tournament, round: Round, p: Pairing, r: Registration, vm: MyTournamentViewModel) {
    val isA = p.playerARegistrationId == r.id
    val opponent = if (isA) p.playerB else p.playerA
    val handle = if (isA) p.playerBHandle else p.playerAHandle
    val reporter = p.reportReporterRegistrationId
    // report_score è "A-B": lo si gira dal proprio lato.
    val myScore = if (isA) p.reportScore else Scores.invert(p.reportScore)
    var choosing by remember { mutableStateOf(false) }
    var rejecting by remember { mutableStateOf(false) }

    Panel(color = Brand.AccentDim) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                stringResource(R.string.round_table, p.tableNumber),
                style = MaterialTheme.typography.headlineSmall,
                color = Brand.Accent,
            )
            Text(
                stringResource(R.string.round_vs, opponent ?: stringResource(R.string.round_bye)),
                style = MaterialTheme.typography.titleMedium,
            )
            if (handle.isNotBlank()) {
                val clipboard = LocalClipboardManager.current
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(handle, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    TextButton(onClick = { clipboard.setText(AnnotatedString(handle)) }) { Text(stringResource(R.string.copy)) }
                }
            }
            if (t.status == "running" && round.endsAt != null) {
                val ends = Formats.time(round.endsAt)
                if (ends.isNotEmpty()) Text(stringResource(R.string.round_ends, ends), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            when {
                opponent == null -> Badge(stringResource(R.string.round_bye), Tone.Ok)
                p.result.isNotBlank() ->
                    Badge(stringResource(R.string.result_confirmed, myScore.ifBlank { p.result }), Tone.Ok)
                p.reportStatus == "conflict" -> Badge(stringResource(R.string.result_conflict), Tone.Warn)
                reporter != null && reporter != r.id && p.reportStatus == "pending" -> Column {
                    Text(stringResource(R.string.result_opponent_sent, myScore), style = MaterialTheme.typography.bodyLarge)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 8.dp)) {
                        Button(onClick = { vm.confirm(p) }, enabled = !vm.busy) { Text(stringResource(R.string.result_confirm)) }
                        OutlinedButton(onClick = { rejecting = true }, enabled = !vm.busy) { Text(stringResource(R.string.result_reject)) }
                    }
                }
                reporter == r.id && p.reportStatus == "pending" ->
                    Badge(stringResource(R.string.result_waiting, myScore), Tone.Warn)
                t.status == "running" ->
                    Button(onClick = { choosing = true }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(R.string.result_send))
                    }
            }
        }
    }

    if (choosing) {
        val scores = Scores.forMatch(t.bestOf, playoff = round.phase != "swiss", intentionalDraws = t.allowIntentionalDraws)
        ResultDialog(opponent.orEmpty(), scores, onDismiss = { choosing = false }) { (mine, theirs) ->
            choosing = false
            vm.report(p, mine, theirs)
        }
    }
    if (rejecting) {
        RejectDialog(onDismiss = { rejecting = false }) { note ->
            rejecting = false
            vm.reject(p, note)
        }
    }
}

@Composable
private fun ResultDialog(opponent: String, scores: List<Pair<Int, Int>>, onDismiss: () -> Unit, onPick: (Pair<Int, Int>) -> Unit) {
    var picked by remember { mutableStateOf<Pair<Int, Int>?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.result_send)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(stringResource(R.string.round_vs, opponent), modifier = Modifier.padding(bottom = 8.dp))
                scores.forEach { score ->
                    Choice(scoreLabel(score), selected = picked == score) { picked = score }
                }
                Text(
                    stringResource(R.string.result_final),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { picked?.let(onPick) }, enabled = picked != null) { Text(stringResource(R.string.send)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

@Composable
private fun scoreLabel(score: Pair<Int, Int>): String {
    val text = "${score.first} – ${score.second}"
    return stringResource(
        when {
            score.first > score.second -> R.string.score_won
            score.first < score.second -> R.string.score_lost
            else -> R.string.score_draw
        },
        text,
    )
}

@Composable
private fun RejectDialog(onDismiss: () -> Unit, onSend: (String) -> Unit) {
    var note by rememberSaveable { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.result_reject)) },
        text = {
            Column {
                Text(stringResource(R.string.result_reject_text), modifier = Modifier.padding(bottom = 8.dp))
                OutlinedTextField(note, { note = it.take(500) }, label = { Text(stringResource(R.string.result_reject_note)) })
            }
        },
        confirmButton = { TextButton(onClick = { onSend(note.trim()) }) { Text(stringResource(R.string.send)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

@Composable
private fun Line(label: String, value: String) {
    Row {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(96.dp))
        Text(value)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PaymentRow(t: Tournament, r: Registration, vm: MyTournamentViewModel) {
    if (r.amountDueCents <= 0) {
        Line(stringResource(R.string.mine_fee), stringResource(R.string.event_free))
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.mine_fee), color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(96.dp))
            Text(Formats.money(r.amountDueCents, t.currency))
            Spacer(Modifier.width(8.dp))
            if (r.isPaid) Badge(stringResource(R.string.mine_paid), Tone.Ok) else Badge(stringResource(R.string.mine_to_pay), Tone.Warn)
        }
        if (!r.isPaid && t.status != "completed") {
            r.paymentDueBy?.let { Formats.time(it) }?.takeIf { it.isNotEmpty() }?.let {
                Text(stringResource(R.string.mine_pay_by, it), color = Brand.Warn)
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (t.payStripe) Button(onClick = { vm.pay("stripe") }, enabled = !vm.busy) { Text(stringResource(R.string.mine_pay_stripe)) }
                if (t.payPaypal) Button(onClick = { vm.pay("paypal") }, enabled = !vm.busy) { Text(stringResource(R.string.mine_pay_paypal)) }
            }
            if (t.payAtEvent && r.paymentDueBy == null) {
                Text(stringResource(R.string.mine_pay_at_event), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            // Chi ha scelto di pagare online e ci ripensa: il posto si libera subito.
            if (r.paymentDueBy != null && t.status == "published") {
                var asking by remember { mutableStateOf(false) }
                TextButton(onClick = { asking = true }, enabled = !vm.busy) {
                    Text(stringResource(R.string.mine_abandon_payment), color = MaterialTheme.colorScheme.error)
                }
                if (asking) {
                    AlertDialog(
                        onDismissRequest = { asking = false },
                        title = { Text(stringResource(R.string.mine_abandon_payment)) },
                        text = { Text(stringResource(R.string.mine_abandon_payment_text, t.name)) },
                        confirmButton = {
                            TextButton(onClick = {
                                asking = false
                                vm.abandonPayment()
                            }) { Text(stringResource(R.string.confirm), color = MaterialTheme.colorScheme.error) }
                        },
                        dismissButton = { TextButton(onClick = { asking = false }) { Text(stringResource(R.string.cancel)) } },
                    )
                }
            }
        }
    }
}

/** Un dato che il giocatore corregge da sé: l'ID presso l'editore o il nome in gioco. */
@Composable
private fun EditableLine(label: String, value: String, missing: String?, busy: Boolean, onSave: (String) -> Unit) {
    var editing by remember { mutableStateOf(false) }
    Column {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) {
                when {
                    value.isNotBlank() -> Text(value)
                    missing != null -> Badge(missing, Tone.Warn)
                    else -> Text("—", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            TextButton(onClick = { editing = true }, enabled = !busy) {
                Text(stringResource(if (value.isBlank()) R.string.mine_add else R.string.mine_change))
            }
        }
    }
    if (editing) {
        var text by rememberSaveable { mutableStateOf(value) }
        AlertDialog(
            onDismissRequest = { editing = false },
            title = { Text(label) },
            text = { OutlinedTextField(text, { text = it.take(120) }, singleLine = true, label = { Text(label) }) },
            confirmButton = {
                TextButton(
                    onClick = {
                        editing = false
                        if (text.trim() != value) onSave(text)
                    },
                ) { Text(stringResource(R.string.save)) }
            },
            dismissButton = { TextButton(onClick = { editing = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

/** Tutti i tavoli del turno, non solo il proprio. */
@Composable
private fun AllPairings(round: Round, myRegistrationId: Int) {
    var open by rememberSaveable { mutableStateOf(false) }
    TextButton(onClick = { open = !open }) {
        Text(stringResource(if (open) R.string.mine_all_pairings_hide else R.string.mine_all_pairings, round.number))
    }
    if (!open) return
    Panel {
        Column {
            round.pairings.sortedBy { it.tableNumber }.forEachIndexed { index, p ->
                if (index > 0) HorizontalDivider(color = Brand.Line)
                val mine = p.playerARegistrationId == myRegistrationId || p.playerBRegistrationId == myRegistrationId
                Row(
                    Modifier.fillMaxWidth()
                        .then(if (mine) Modifier.background(Brand.AccentDim, RoundedCornerShape(8.dp)) else Modifier)
                        .padding(vertical = 8.dp, horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("${p.tableNumber}", Modifier.width(32.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Column(Modifier.weight(1f)) {
                        Text(p.playerA, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = if (mine) FontWeight.Bold else null)
                        Text(
                            p.playerB ?: stringResource(R.string.round_bye),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Text(p.result, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@Composable
private fun CheckInRow(t: Tournament, r: Registration, vm: MyTournamentViewModel, active: Boolean) {
    when {
        r.checkedIn -> Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.mine_check_in), color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(96.dp))
            Badge(stringResource(R.string.mine_checked_in), Tone.Ok)
        }
        t.selfCheckInEnabled && active && !r.dropped && !r.waitlisted ->
            Button(onClick = vm::checkIn, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.mine_do_check_in))
            }
        t.checkInRequired && active -> Line(stringResource(R.string.mine_check_in), stringResource(R.string.mine_check_in_desk))
    }
}

@Composable
private fun DeckRow(t: Tournament, r: Registration, vm: MyTournamentViewModel) {
    val (label, tone) = when (r.decklistStatus) {
        "valid" -> R.string.deck_valid to Tone.Ok
        "invalid" -> R.string.deck_invalid to Tone.Danger
        "submitted" -> R.string.deck_submitted to Tone.Neutral
        else -> R.string.deck_missing to if (t.decklistRequired) Tone.Warn else Tone.Neutral
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.mine_deck), color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(96.dp))
            Badge(stringResource(label), tone)
        }
        val hasDeck = r.decklistStatus != "missing"
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            // Le liste si chiudono quando il torneo parte (o prima, se l'organizzatore lo decide).
            if (t.status == "published" && !t.decklistLocked && !r.dropped) {
                OutlinedButton(onClick = { vm.openDecks(t, hasDeck) }, enabled = !vm.busy) {
                    Text(stringResource(if (hasDeck) R.string.deck_change else R.string.deck_send))
                }
            }
            // Negli eventi misti c'è una lista per formato: si guarda una per una.
            if (hasDeck) {
                t.decklistFormats.forEach { format ->
                    TextButton(onClick = { vm.viewDeck(format) }, enabled = !vm.busy) {
                        Text(stringResource(R.string.deck_view) + if (format.isNotBlank()) " · $format" else "")
                    }
                }
            }
        }
    }
}

@Composable
private fun Standings(rows: List<Standing>, myRegistrationId: Int) {
    val me = rows.firstOrNull { it.registrationId == myRegistrationId }
    if (me != null) {
        Text(
            stringResource(R.string.standings_me, me.position, me.points, me.record),
            style = MaterialTheme.typography.titleMedium,
            color = Brand.Accent,
            modifier = Modifier.padding(bottom = 8.dp),
        )
    }
    Panel {
        Column {
            rows.forEachIndexed { index, s ->
                if (index > 0) HorizontalDivider(color = Brand.Line)
                val mine = s.registrationId == myRegistrationId
                Row(
                    Modifier.fillMaxWidth()
                        .then(if (mine) Modifier.background(Brand.AccentDim, RoundedCornerShape(8.dp)) else Modifier)
                        .padding(vertical = 8.dp, horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("${s.position}", modifier = Modifier.width(32.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(
                        s.name + if (s.dropped) " · " + stringResource(R.string.mine_dropped).lowercase() else "",
                        modifier = Modifier.weight(1f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        fontWeight = if (mine) FontWeight.Bold else null,
                    )
                    Text("${s.points}", modifier = Modifier.width(40.dp), fontWeight = FontWeight.Bold)
                    Text(s.record, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

/** Ritirarsi (si resta in classifica) o annullare l'iscrizione prima che il torneo parta. */
@Composable
private fun Leave(t: Tournament, vm: MyTournamentViewModel) {
    var asking by remember { mutableStateOf<String?>(null) }
    Column(Modifier.padding(top = 24.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { asking = "drop" }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.mine_drop), color = MaterialTheme.colorScheme.error)
        }
        if (t.status == "published") {
            TextButton(onClick = { asking = "cancel" }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.mine_cancel), color = MaterialTheme.colorScheme.error)
            }
        }
    }
    asking?.let { what ->
        val drop = what == "drop"
        AlertDialog(
            onDismissRequest = { asking = null },
            title = { Text(stringResource(if (drop) R.string.mine_drop else R.string.mine_cancel)) },
            text = { Text(stringResource(if (drop) R.string.mine_drop_text else R.string.mine_cancel_text, t.name)) },
            confirmButton = {
                TextButton(onClick = {
                    asking = null
                    if (drop) vm.drop() else vm.cancel()
                }) { Text(stringResource(R.string.confirm), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { asking = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

/** La lista per il torneo: una di quelle salvate nel profilo, o incollata. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DeckSheet(
    t: Tournament,
    decks: List<SavedDeck>,
    current: Map<String, String>,
    busy: Boolean,
    onDismiss: () -> Unit,
    onSend: (DecklistIn) -> Unit,
) {
    var picked by remember { mutableStateOf<SavedDeck?>(null) }
    var format by rememberSaveable { mutableStateOf(t.decklistFormats.firstOrNull().orEmpty()) }
    var pasted by rememberSaveable { mutableStateOf(current[format].orEmpty()) }
    val pickFile = rememberTextFilePicker {
        pasted = it
        picked = null
    }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).imePadding()
                .padding(horizontal = 24.dp).padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(stringResource(R.string.deck_title), style = MaterialTheme.typography.titleLarge)
            // Negli eventi misti ogni formato ha la sua lista.
            if (t.decklistFormats.size > 1) {
                Text(stringResource(R.string.deck_format), style = MaterialTheme.typography.labelLarge)
                t.decklistFormats.forEach { f ->
                    Choice(f.ifBlank { stringResource(R.string.deck_main_format) }, selected = format == f) {
                        // Cambiando segmento si riparte dalla sua lista, se c'è.
                        if (picked == null && pasted == current[format].orEmpty()) pasted = current[f].orEmpty()
                        format = f
                    }
                }
            }
            if (decks.isNotEmpty()) {
                Text(stringResource(R.string.deck_saved), style = MaterialTheme.typography.labelLarge)
                decks.forEach { deck ->
                    Choice("${deck.name} · ${deck.mainCount}+${deck.sideCount}", selected = picked?.id == deck.id) {
                        picked = deck
                        pasted = ""
                    }
                }
            } else {
                Text(stringResource(R.string.deck_none_saved), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            OutlinedTextField(
                pasted,
                {
                    pasted = it
                    if (it.isNotBlank()) picked = null
                },
                label = { Text(stringResource(R.string.deck_paste)) },
                minLines = 5,
                modifier = Modifier.fillMaxWidth(),
            )
            TextButton(onClick = pickFile) { Text(stringResource(R.string.deck_import_file)) }
            val deck = picked
            SubmitButton(stringResource(R.string.send), busy, enabled = deck != null || pasted.trim().length >= 5) {
                onSend(
                    if (deck != null) DecklistIn(deck.rawText, deck.archetype, format)
                    else DecklistIn(pasted.trim(), "", format)
                )
            }
        }
    }
}
