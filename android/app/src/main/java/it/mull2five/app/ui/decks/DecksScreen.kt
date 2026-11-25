package it.mull2five.app.ui.decks

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.data.ApiException
import it.mull2five.app.data.DeckCheck
import it.mull2five.app.data.DeckLines
import it.mull2five.app.data.DeckValidateIn
import it.mull2five.app.data.DecklistIn
import it.mull2five.app.data.Formats
import it.mull2five.app.data.Game
import it.mull2five.app.data.MyRegistration
import it.mull2five.app.data.SavedDeck
import it.mull2five.app.data.SavedDeckIn
import it.mull2five.app.data.Tournament
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.ChoiceChip
import it.mull2five.app.ui.ErrorBox
import it.mull2five.app.ui.Loaded
import it.mull2five.app.ui.LoadingBox
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.Notice
import it.mull2five.app.ui.Panel
import it.mull2five.app.ui.SubScreen
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.UiText
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.event.Choice
import it.mull2five.app.ui.login.SubmitButton
import it.mull2five.app.ui.rememberLoad
import it.mull2five.app.ui.rememberTextFilePicker
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

// ── Le liste salvate ──────────────────────────────────────────────────────

/** Le liste salvate nel profilo (decks.html): si scrivono una volta, si mandano a ogni torneo. */
@Composable
fun DecksScreen(onBack: () -> Unit, onOpen: (Int) -> Unit) {
    val vm = rememberLoad("liste") { it.api.decks() }
    // Di ritorno dall'editor l'elenco va riletto.
    LifecycleResumeEffect(vm) {
        vm.load()
        onPauseOrDispose { }
    }
    SubScreen(
        stringResource(R.string.decks_title),
        onBack,
        floating = {
            ExtendedFloatingActionButton(
                onClick = { onOpen(0) },
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text(stringResource(R.string.decks_new)) },
            )
        },
    ) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { decks ->
            if (decks.isEmpty()) {
                MessageBox(stringResource(R.string.decks_empty), Modifier.padding(padding))
            } else {
                LazyColumn(
                    Modifier.padding(padding).fillMaxSize(),
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 96.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(decks, key = { it.id }) { deck -> SavedDeckCard(deck, onClick = { onOpen(deck.id) }) }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SavedDeckCard(d: SavedDeck, onClick: () -> Unit) {
    Surface(
        color = Brand.Panel,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(d.name, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            val line = listOf(d.format, d.archetype).filter { it.isNotBlank() }.joinToString(" · ")
            if (line.isNotEmpty()) {
                Text(line, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.height(8.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Badge(stringResource(R.string.deck_counts, d.mainCount, d.sideCount))
                if (d.format.isNotBlank()) {
                    if (d.errors.isEmpty()) Badge(stringResource(R.string.deck_valid), Tone.Ok)
                    else Badge(stringResource(R.string.deck_invalid), Tone.Danger)
                }
            }
        }
    }
}

// ── L'editor ──────────────────────────────────────────────────────────────

/**
 * Una lista da scrivere o cambiare: le carte si cercano (Scryfall, attraverso il
 * server) e le regole del formato le controlla il server mentre si scrive.
 */
class DeckEditorViewModel(private val c: AppContainer, id: Int) : ViewModel() {
    var deckId by mutableIntStateOf(id)
        private set
    var loading by mutableStateOf(id != 0)
        private set
    var loadError by mutableStateOf<String?>(null)
        private set
    var name by mutableStateOf("")
        private set
    var archetype by mutableStateOf("")
        private set
    var format by mutableStateOf("")
        private set
    var rawText by mutableStateOf("")
        private set
    var check by mutableStateOf<DeckCheck?>(null)
        private set
    var checking by mutableStateOf(false)
        private set

    /** Il controllo completo (ogni carta legale nel formato) è più lento: si chiede a parte, come sul sito. */
    var legalityChecked by mutableStateOf(false)
        private set
    var cardQuery by mutableStateOf("")
        private set
    var suggestions by mutableStateOf<List<String>>(emptyList())
        private set
    var busy by mutableStateOf(false)
        private set
    var message by mutableStateOf<UiText?>(null)
        private set
    var messageIsError by mutableStateOf(false)
        private set

    /** I tornei a cui mandare la lista, quando si apre la scelta. */
    var targets by mutableStateOf<List<MyRegistration>?>(null)
        private set

    private var game by mutableStateOf("mtg")
    private var games by mutableStateOf<List<Game>>(emptyList())
    val formats: List<String>
        get() = games.firstOrNull { it.code == game }?.let { (it.formats + it.limitedFormats).distinct() }.orEmpty()

    private val _closed = Channel<Unit>(Channel.BUFFERED)
    val closed = _closed.receiveAsFlow()
    private var checkJob: Job? = null
    private var searchJob: Job? = null

    init {
        viewModelScope.launch { c.attempt { c.api.games() }.onSuccess { games = it } }
        if (id != 0) load()
    }

    fun load() {
        loading = true
        loadError = null
        viewModelScope.launch {
            c.attempt {
                c.api.decks().firstOrNull { it.id == deckId } ?: throw ApiException(404, c.texts.translate("Lista non trovata"))
            }.onSuccess { d ->
                name = d.name
                archetype = d.archetype
                format = d.format
                rawText = d.rawText
                game = d.game
                validateSoon(now = true)
            }.onFailure { loadError = c.messageOf(it) }
            loading = false
        }
    }

    fun editName(value: String) {
        name = value.take(120)
    }

    fun editArchetype(value: String) {
        archetype = value.take(120)
    }

    fun editFormat(value: String) {
        format = value
        validateSoon()
    }

    fun editText(value: String) {
        rawText = value.take(20_000)
        validateSoon()
    }

    fun checkLegality() = validateSoon(now = true, legality = true)

    private fun validateSoon(now: Boolean = false, legality: Boolean = false) {
        checkJob?.cancel()
        legalityChecked = false
        if (rawText.isBlank()) {
            check = null
            checking = false
            return
        }
        val body = DeckValidateIn(rawText, game, format, legality)
        checkJob = viewModelScope.launch {
            if (!now) delay(700)
            checking = true
            c.attempt { c.api.checkDeck(body) }.onSuccess {
                check = it
                legalityChecked = legality
            }
            checking = false
        }
    }

    fun searchCard(query: String) {
        cardQuery = query
        searchJob?.cancel()
        if (query.trim().length < 2) {
            suggestions = emptyList()
            return
        }
        searchJob = viewModelScope.launch {
            delay(300)
            suggestions = c.attempt { c.api.searchCards(query.trim(), game) }.getOrDefault(emptyList()).take(8)
        }
    }

    fun clearSearch() = searchCard("")

    /** Una copia in più: la ricerca resta aperta, per aggiungerne altre. */
    fun addCard(card: String, side: Boolean) = editText(DeckLines.add(rawText, card, side))

    fun save() = act {
        val body = SavedDeckIn(name.trim(), game, format, archetype.trim(), rawText)
        deckId = (if (deckId == 0) c.api.createDeck(body) else c.api.updateDeck(deckId, body)).id
        note(R.string.deck_saved_ok)
    }

    fun delete() = act {
        c.api.deleteDeck(deckId)
        _closed.send(Unit)
    }

    /** I tornei dello stesso gioco a cui si è iscritti e che aspettano ancora la lista. */
    fun openTargets() {
        viewModelScope.launch {
            targets = c.attempt { c.api.myRegistrations() }.getOrDefault(emptyList()).filter { (t, r) ->
                t.status == "published" && !t.decklistLocked && !r.dropped && t.game == game
            }
        }
    }

    fun closeTargets() {
        targets = null
    }

    fun sendTo(t: Tournament, segment: String) = act {
        c.api.sendDecklist(t.id, DecklistIn(rawText, archetype.trim(), segment))
        targets = null
        note(R.string.deck_sent)
    }

    private fun note(text: Int) {
        message = UiText.Res(text)
        messageIsError = false
    }

    private fun act(block: suspend () -> Unit) {
        if (busy) return
        busy = true
        message = null
        viewModelScope.launch {
            c.attempt { block() }.onFailure {
                message = UiText.Raw(c.messageOf(it))
                messageIsError = true
            }
            busy = false
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DeckEditorScreen(id: Int, onBack: () -> Unit) {
    val vm = appViewModel(key = "editor-$id") { DeckEditorViewModel(it, id) }
    val clipboard = LocalClipboardManager.current
    val pickFile = rememberTextFilePicker(vm::editText)
    var deleting by remember { mutableStateOf(false) }
    LaunchedEffect(vm) { vm.closed.collect { onBack() } }

    SubScreen(stringResource(if (vm.deckId == 0) R.string.decks_new else R.string.deck_edit_title), onBack) { padding ->
        val error = vm.loadError
        when {
            vm.loading -> LoadingBox(Modifier.padding(padding))
            error != null -> ErrorBox(error, vm::load, Modifier.padding(padding))
            else -> Column(
                Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                OutlinedTextField(
                    vm.name,
                    vm::editName,
                    label = { Text(stringResource(R.string.deck_name)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    ChoiceChip(
                        label = stringResource(R.string.events_format),
                        options = vm.formats.map { it to it },
                        selected = vm.format,
                        onSelect = vm::editFormat,
                        allLabel = stringResource(R.string.deck_no_format),
                    )
                    OutlinedTextField(
                        vm.archetype,
                        vm::editArchetype,
                        label = { Text(stringResource(R.string.archive_archetype)) },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
                CardSearch(vm)
                OutlinedTextField(
                    vm.rawText,
                    vm::editText,
                    label = { Text(stringResource(R.string.deck_text)) },
                    placeholder = { Text("4 Lightning Bolt\n…\n\nSideboard\n2 Blood Moon") },
                    minLines = 10,
                    textStyle = LocalTextStyle.current.copy(fontFamily = FontFamily.Monospace),
                    modifier = Modifier.fillMaxWidth(),
                )
                CheckPanel(vm)
                Notice(vm.message, vm.messageIsError)
                SubmitButton(stringResource(R.string.deck_save), vm.busy, enabled = vm.name.isNotBlank()) { vm.save() }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = pickFile) { Text(stringResource(R.string.deck_import_file)) }
                    OutlinedButton(onClick = { clipboard.setText(AnnotatedString(vm.rawText)) }, enabled = vm.rawText.isNotBlank()) {
                        Text(stringResource(R.string.copy))
                    }
                    if (vm.deckId != 0) {
                        OutlinedButton(onClick = vm::openTargets, enabled = !vm.busy && vm.rawText.isNotBlank()) {
                            Text(stringResource(R.string.deck_send_to))
                        }
                    }
                }
                if (vm.deckId != 0) {
                    TextButton(onClick = { deleting = true }, enabled = !vm.busy) {
                        Text(stringResource(R.string.deck_delete), color = MaterialTheme.colorScheme.error)
                    }
                }
            }
        }
    }

    if (deleting) {
        AlertDialog(
            onDismissRequest = { deleting = false },
            title = { Text(stringResource(R.string.deck_delete)) },
            text = { Text(stringResource(R.string.deck_delete_text, vm.name)) },
            confirmButton = {
                TextButton(onClick = {
                    deleting = false
                    vm.delete()
                }) { Text(stringResource(R.string.confirm), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { deleting = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
    vm.targets?.let { list -> TargetsDialog(list, vm.format, onDismiss = vm::closeTargets, onPick = vm::sendTo) }
}

@Composable
private fun CardSearch(vm: DeckEditorViewModel) {
    Column {
        OutlinedTextField(
            vm.cardQuery,
            vm::searchCard,
            label = { Text(stringResource(R.string.deck_search_card)) },
            leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
            trailingIcon = {
                if (vm.cardQuery.isNotEmpty()) {
                    IconButton(onClick = vm::clearSearch) { Icon(Icons.Filled.Clear, stringResource(R.string.events_search_clear)) }
                }
            },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        vm.suggestions.forEach { card ->
            Row(Modifier.fillMaxWidth().padding(start = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(card, Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                TextButton(onClick = { vm.addCard(card, side = false) }) { Text(stringResource(R.string.deck_add_main)) }
                TextButton(onClick = { vm.addCard(card, side = true) }) { Text(stringResource(R.string.deck_add_side)) }
            }
        }
    }
}

/** Quante carte, e cosa non torna con le regole del formato. */
@Composable
private fun CheckPanel(vm: DeckEditorViewModel) {
    val check = vm.check ?: return
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.deck_counts_long, check.mainCount, check.sideCount), Modifier.weight(1f))
                when {
                    vm.checking -> CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                    check.errors.isEmpty() -> Badge(stringResource(R.string.deck_valid), Tone.Ok)
                    else -> Badge(stringResource(R.string.deck_invalid), Tone.Danger)
                }
            }
            check.errors.forEach {
                Text("• $it", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            }
            if (vm.format.isNotBlank()) {
                if (vm.legalityChecked && check.errors.isEmpty()) {
                    Text(stringResource(R.string.deck_legal, vm.format), color = Brand.Green, style = MaterialTheme.typography.bodySmall)
                } else if (!vm.legalityChecked) {
                    TextButton(onClick = vm::checkLegality, enabled = !vm.checking) { Text(stringResource(R.string.deck_check_legality)) }
                }
            }
        }
    }
}

/** A quale torneo mandare la lista, e per quale segmento se il torneo ne ha più d'uno. */
@Composable
private fun TargetsDialog(list: List<MyRegistration>, deckFormat: String, onDismiss: () -> Unit, onPick: (Tournament, String) -> Unit) {
    var picked by remember { mutableStateOf<Tournament?>(null) }
    var segment by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.deck_send_to)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (list.isEmpty()) Text(stringResource(R.string.deck_no_targets))
                list.forEach { (t, _) ->
                    Choice("${t.name} · ${Formats.date(t.startsOn)}", selected = picked?.id == t.id) {
                        picked = t
                        segment = t.decklistFormats.firstOrNull { it.equals(deckFormat, ignoreCase = true) }
                            ?: t.decklistFormats.firstOrNull().orEmpty()
                    }
                }
                val t = picked
                if (t != null && t.decklistFormats.size > 1) {
                    Text(stringResource(R.string.deck_format), style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(top = 8.dp))
                    t.decklistFormats.forEach { f ->
                        Choice(f.ifBlank { stringResource(R.string.deck_main_format) }, selected = segment == f) { segment = f }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { picked?.let { onPick(it, segment) } }, enabled = picked != null) { Text(stringResource(R.string.send)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}
