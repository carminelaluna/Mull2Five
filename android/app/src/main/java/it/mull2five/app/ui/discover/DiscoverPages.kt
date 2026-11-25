package it.mull2five.app.ui.discover

import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.data.ArchiveDeck
import it.mull2five.app.data.Circuit
import it.mull2five.app.data.Formats
import it.mull2five.app.data.LeaderboardRow
import it.mull2five.app.data.SavedDeckIn
import it.mull2five.app.data.StoreLocation
import it.mull2five.app.data.Tournament
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.DeckText
import it.mull2five.app.ui.InfoRow
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.Loaded
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.Notice
import it.mull2five.app.ui.Panel
import it.mull2five.app.ui.SectionTitle
import it.mull2five.app.ui.ShareButton
import it.mull2five.app.ui.SubScreen
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.UiText
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.events.EventCard
import it.mull2five.app.ui.openExternal
import it.mull2five.app.ui.openPlace
import it.mull2five.app.ui.rememberLoad
import it.mull2five.app.ui.theme.Brand
import it.mull2five.app.ui.webUrl
import kotlinx.coroutines.launch

/** Un gruppo di tornei con il suo titolo, dentro una LazyColumn. */
private fun LazyListScope.tournaments(title: Int, list: List<Tournament>, prefix: String, onEvent: (Int) -> Unit) {
    if (list.isEmpty()) return
    item(key = "$prefix-titolo") { SectionTitle(stringResource(title)) }
    items(list, key = { "$prefix-${it.id}" }) { EventCard(it, onClick = { onEvent(it.id) }) }
}

private fun joined(vararg parts: String) = parts.filter { it.isNotBlank() }.joinToString(", ")

// ── Negozio ───────────────────────────────────────────────────────────────

/** La pagina di un negozio (store.html): chi è, dove, e i suoi tornei. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun StoreScreen(slug: String, onBack: () -> Unit, onEvent: (Int) -> Unit) {
    val vm = rememberLoad("negozio-$slug") { it.api.store(slug) }
    val c = LocalContainer.current
    val context = LocalContext.current
    val title = (vm.state as? Load.Ready)?.value?.organization?.name ?: stringResource(R.string.store_title)
    SubScreen(title, onBack, actions = { ShareButton("${c.siteUrl}/store.html?s=${Uri.encode(slug)}") }) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { page ->
            val o = page.organization
            LazyColumn(
                Modifier.padding(padding).fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item(key = "testa") {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(o.name, style = MaterialTheme.typography.headlineSmall)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (o.isPremium) Badge(stringResource(R.string.stores_premium), Tone.Accent)
                            Badge(stringResource(R.string.stores_upcoming, page.upcoming.size))
                        }
                        if (o.description.isNotBlank()) Text(o.description, style = MaterialTheme.typography.bodyMedium)
                        val places = page.locations
                            .ifEmpty { listOf(StoreLocation(0, "", o.address, o.city, o.latitude, o.longitude)) }
                            .filter { it.address.isNotBlank() || it.city.isNotBlank() }
                        if (places.isNotEmpty() || o.website.isNotBlank()) {
                            Panel {
                                Column {
                                    places.forEach { l ->
                                        val address = joined(l.address, l.city)
                                        InfoRow(
                                            Icons.Filled.LocationOn,
                                            l.name.ifBlank { address },
                                            detail = joined(if (l.name.isNotBlank()) address else "", l.notes).ifBlank { null },
                                            modifier = Modifier.clickable {
                                                context.openPlace(l.name.ifBlank { o.name }, address, l.latitude, l.longitude)
                                            },
                                        )
                                    }
                                    if (o.website.isNotBlank()) {
                                        InfoRow(
                                            Icons.Filled.Home,
                                            o.website.removePrefix("https://").removePrefix("http://").trimEnd('/'),
                                            modifier = Modifier.clickable { context.openExternal(webUrl(o.website)) },
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
                tournaments(R.string.store_upcoming, page.upcoming.sortedBy { it.startsOn }, "prossimi", onEvent)
                tournaments(R.string.store_past, page.past.sortedByDescending { it.startsOn }, "passati", onEvent)
                if (page.upcoming.isEmpty() && page.past.isEmpty()) {
                    item(key = "vuoto") {
                        Text(stringResource(R.string.store_no_events), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

// ── Circuito ──────────────────────────────────────────────────────────────

/** La pagina di un circuito (series.html): regole, classifica e tappe. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CircuitScreen(slug: String, onBack: () -> Unit, onEvent: (Int) -> Unit) {
    val vm = rememberLoad("circuito-$slug") { it.api.circuit(slug) }
    val c = LocalContainer.current
    val title = (vm.state as? Load.Ready)?.value?.season?.name ?: stringResource(R.string.circuit_title)
    SubScreen(title, onBack, actions = { ShareButton("${c.siteUrl}/series.html?c=${Uri.encode(slug)}") }) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { page ->
            val s = page.season
            LazyColumn(
                Modifier.padding(padding).fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item(key = "testa") {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(s.name, style = MaterialTheme.typography.headlineSmall)
                        circuitDates(s)?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (s.isActive) Badge(stringResource(R.string.circuit_active), Tone.Ok)
                            else Badge(stringResource(R.string.circuit_closed))
                            Badge(stringResource(R.string.circuit_stages, page.tournaments.size))
                        }
                        if (s.description.isNotBlank()) Text(s.description, style = MaterialTheme.typography.bodyMedium)
                        Rules(s)
                    }
                }
                item(key = "classifica-titolo") { SectionTitle(stringResource(R.string.circuit_leaderboard)) }
                item(key = "classifica") {
                    if (page.leaderboard.isEmpty()) {
                        Text(stringResource(R.string.circuit_no_leaderboard), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        Leaderboard(page.leaderboard, s)
                    }
                }
                tournaments(R.string.circuit_stages_title, page.tournaments.sortedBy { it.startsOn }, "tappa", onEvent)
            }
        }
    }
}

/** Come si fanno punti nel circuito: le stesse voci della pagina del sito. */
@Composable
private fun Rules(s: Circuit) {
    val lines = buildList {
        add(stringResource(R.string.circuit_rule_win_draw, s.pointsWin, s.pointsDraw))
        if (s.pointsParticipation > 0) add(stringResource(R.string.circuit_rule_participation, s.pointsParticipation))
        if (s.pointsChampionBonus > 0) add(stringResource(R.string.circuit_rule_champion, s.pointsChampionBonus))
        if (s.pointsUndefeatedBonus > 0) add(stringResource(R.string.circuit_rule_undefeated, s.pointsUndefeatedBonus))
        if (s.dropWorstScores > 0) add(stringResource(R.string.circuit_rule_drop, s.dropWorstScores, s.dropAboveTournaments))
        s.qualificationThreshold?.let { add(stringResource(R.string.circuit_rule_threshold, it)) }
    }
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.circuit_rules), style = MaterialTheme.typography.titleSmall)
            lines.forEach { Text("• $it", style = MaterialTheme.typography.bodyMedium) }
        }
    }
}

@Composable
private fun Leaderboard(rows: List<LeaderboardRow>, s: Circuit) {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Panel {
        Column {
            Row(Modifier.padding(bottom = 6.dp)) {
                Text("#", Modifier.width(32.dp), color = muted, style = MaterialTheme.typography.labelSmall)
                Text(stringResource(R.string.standings_player), Modifier.weight(1f), color = muted, style = MaterialTheme.typography.labelSmall)
                Text(stringResource(R.string.standings_points), Modifier.width(48.dp), color = muted, style = MaterialTheme.typography.labelSmall)
                Text(stringResource(R.string.record_header), Modifier.width(64.dp), color = muted, style = MaterialTheme.typography.labelSmall)
            }
            rows.forEach { r ->
                HorizontalDivider(color = Brand.Line)
                val qualified = s.qualificationThreshold?.let { r.points >= it } == true
                Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("${r.position}", Modifier.width(32.dp), color = muted)
                    Column(Modifier.weight(1f)) {
                        Text(
                            r.playerName,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            fontWeight = if (qualified) FontWeight.Bold else null,
                            color = if (qualified) Brand.Accent else MaterialTheme.colorScheme.onSurface,
                        )
                        val detail = buildList {
                            add(stringResource(R.string.circuit_row_tournaments, r.tournamentsPlayed))
                            if (r.titles > 0) add(stringResource(R.string.circuit_row_titles, r.titles))
                            if (r.undefeated > 0) add(stringResource(R.string.circuit_row_undefeated, r.undefeated))
                        }
                        Text(detail.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = muted)
                    }
                    Text("${r.points}", Modifier.width(48.dp), fontWeight = FontWeight.Bold)
                    Text("${r.wins}/${r.draws}/${r.losses}", Modifier.width(64.dp), color = muted)
                }
            }
        }
    }
}

// ── Manifestazione ────────────────────────────────────────────────────────

/** Una manifestazione (event-page.html): più tornei, giorno per giorno. */
@Composable
fun ManifestationScreen(slug: String, onBack: () -> Unit, onEvent: (Int) -> Unit) {
    val vm = rememberLoad("manifestazione-$slug") { it.api.manifestation(slug) }
    val c = LocalContainer.current
    val context = LocalContext.current
    val title = (vm.state as? Load.Ready)?.value?.event?.name ?: stringResource(R.string.manifestation_title)
    SubScreen(title, onBack, actions = { ShareButton("${c.siteUrl}/event-page.html?e=${Uri.encode(slug)}") }) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { page ->
            val e = page.event
            LazyColumn(
                Modifier.padding(padding).fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item(key = "testa") {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(e.name, style = MaterialTheme.typography.headlineSmall)
                        Text(
                            listOfNotNull(e.startsOn, e.endsOn?.takeIf { it != e.startsOn }).joinToString(" – ") { Formats.date(it) },
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (e.venue.isNotBlank() || e.city.isNotBlank()) {
                            InfoRow(
                                Icons.Filled.LocationOn,
                                e.venue.ifBlank { e.city },
                                detail = e.city.takeIf { e.venue.isNotBlank() && it.isNotBlank() },
                                modifier = Modifier.clickable { context.openPlace(e.venue, joined(e.venue, e.city), null, null) },
                            )
                        }
                        if (e.description.isNotBlank()) Text(e.description, style = MaterialTheme.typography.bodyMedium)
                    }
                }
                page.tournaments.groupBy { it.startsOn.take(10) }.toSortedMap().forEach { (day, list) ->
                    item(key = "giorno-$day") { SectionTitle(Formats.date(day)) }
                    items(list.sortedBy { it.startTime.orEmpty() }, key = { "torneo-${it.id}" }) {
                        EventCard(it, onClick = { onEvent(it.id) })
                    }
                }
            }
        }
    }
}

// ── Una lista dell'archivio ───────────────────────────────────────────────

class ArchiveDeckViewModel(private val c: AppContainer, private val id: Int) : ViewModel() {
    var state by mutableStateOf<Load<ArchiveDeck>>(Load.Loading)
        private set
    var saving by mutableStateOf(false)
        private set
    var message by mutableStateOf<UiText?>(null)
        private set
    var messageIsError by mutableStateOf(false)
        private set

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            c.attempt { c.api.archiveDeck(id) }
                .onSuccess { state = Load.Ready(it) }
                .onFailure { state = Load.Failed(c.messageOf(it)) }
        }
    }

    fun note(text: UiText) {
        message = text
        messageIsError = false
    }

    /** Una copia tra le proprie liste, da cambiare e mandare ai tornei. */
    fun save() {
        val d = (state as? Load.Ready)?.value ?: return
        if (saving) return
        saving = true
        message = null
        viewModelScope.launch {
            val name = listOf(d.archetype, d.playerName).filter { it.isNotBlank() }.joinToString(" – ").ifBlank { d.tournamentName }
            c.attempt { c.api.createDeck(SavedDeckIn(name.take(120), format = d.format, archetype = d.archetype, rawText = d.rawText)) }
                .onSuccess { note(UiText.Res(R.string.archive_saved)) }
                .onFailure {
                    message = UiText.Raw(c.messageOf(it))
                    messageIsError = true
                }
            saving = false
        }
    }
}

/** Una lista dell'archivio pubblico: chi, dove, com'è andata, e le carte. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ArchiveDeckScreen(id: Int, onBack: () -> Unit, onResults: (Int) -> Unit) {
    val vm = appViewModel(key = "lista-$id") { ArchiveDeckViewModel(it, id) }
    val user by LocalContainer.current.session.user.collectAsStateWithLifecycle()
    val clipboard = LocalClipboardManager.current
    val title = (vm.state as? Load.Ready)?.value?.archetype?.ifBlank { null } ?: stringResource(R.string.archive_deck_title)
    SubScreen(title, onBack) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { d ->
            Column(
                Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(d.archetype.ifBlank { stringResource(R.string.archive_no_archetype) }, style = MaterialTheme.typography.headlineSmall)
                if (d.playerName.isNotBlank()) Text(stringResource(R.string.archive_deck_by, d.playerName), style = MaterialTheme.typography.titleMedium)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Badge(if (d.players > 0) "#${d.position} / ${d.players}" else "#${d.position}", Tone.Accent)
                    if (d.record.isNotBlank()) Badge(d.record)
                    if (d.format.isNotBlank()) Badge(d.format)
                    Badge("${d.mainCount} + ${d.sideCount}")
                }
                Text(
                    listOfNotNull(d.tournamentName, Formats.date(d.startsOn), d.storeName).joinToString(" · "),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = {
                        clipboard.setText(AnnotatedString(d.rawText))
                        vm.note(UiText.Res(R.string.deck_copied))
                    }) { Text(stringResource(R.string.copy)) }
                    if (user != null) {
                        OutlinedButton(onClick = vm::save, enabled = !vm.saving) { Text(stringResource(R.string.archive_save)) }
                    }
                    TextButton(onClick = { onResults(d.tournamentId) }) { Text(stringResource(R.string.results_open)) }
                }
                Notice(vm.message, vm.messageIsError)
                DeckText(d.rawText)
            }
        }
    }
}
