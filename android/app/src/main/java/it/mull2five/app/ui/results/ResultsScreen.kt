package it.mull2five.app.ui.results

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import it.mull2five.app.R
import it.mull2five.app.data.BracketMatch
import it.mull2five.app.data.Formats
import it.mull2five.app.data.MetaRow
import it.mull2five.app.data.PublicResults
import it.mull2five.app.ui.DeckText
import it.mull2five.app.ui.Loaded
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.Panel
import it.mull2five.app.ui.SectionTitle
import it.mull2five.app.ui.ShareButton
import it.mull2five.app.ui.SubScreen
import it.mull2five.app.ui.discover.percent
import it.mull2five.app.ui.rememberLoad
import it.mull2five.app.ui.theme.Brand

data class ResultsData(val results: PublicResults, val meta: List<MetaRow>, val bracket: List<BracketMatch>)

/**
 * I risultati di un torneo (coverage.html): la classifica, con le liste se
 * l'organizzatore le ha rese pubbliche, il metagame e il taglio.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ResultsScreen(id: Int, onBack: () -> Unit, onEvent: () -> Unit) {
    val vm = rememberLoad("risultati-$id") { c ->
        ResultsData(
            c.api.results(id),
            // Metagame e taglio non ci sono in tutti i tornei: senza, restano le schede che servono.
            c.attempt { c.api.meta(id) }.getOrDefault(emptyList()),
            c.attempt { c.api.bracket(id) }.getOrDefault(emptyList()),
        )
    }
    val c = LocalContainer.current
    var tab by rememberSaveable { mutableIntStateOf(0) }
    SubScreen(stringResource(R.string.results_title), onBack, actions = { ShareButton("${c.siteUrl}/coverage.html?t=$id") }) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { data ->
            val r = data.results
            val tabs = buildList {
                add(R.string.results_standings)
                if (data.meta.isNotEmpty()) add(R.string.results_meta)
                if (data.bracket.isNotEmpty()) add(R.string.results_bracket)
            }
            val current = tabs.getOrElse(tab) { tabs.first() }
            Column(Modifier.padding(padding).fillMaxSize()) {
                Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp)) {
                    Text(r.name, style = MaterialTheme.typography.headlineSmall)
                    Text(
                        listOf(Formats.date(r.startsOn), r.format).filter { it.isNotBlank() }.joinToString(" · "),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    TextButton(onClick = onEvent) { Text(stringResource(R.string.mine_open_event)) }
                }
                if (tabs.size > 1) {
                    PrimaryTabRow(selectedTabIndex = tabs.indexOf(current), containerColor = Brand.Bg) {
                        tabs.forEachIndexed { index, label ->
                            Tab(selected = current == label, onClick = { tab = index }, text = { Text(stringResource(label)) })
                        }
                    }
                }
                when (current) {
                    R.string.results_meta -> MetaList(data.meta)
                    R.string.results_bracket -> Bracket(data.bracket)
                    else -> StandingsList(r)
                }
            }
        }
    }
}

@Composable
private fun StandingsList(r: PublicResults) {
    var open by rememberSaveable { mutableStateOf<Int?>(null) }
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    when {
        !r.standingsPublic -> MessageBox(stringResource(R.string.results_hidden))
        r.standings.isEmpty() -> MessageBox(stringResource(R.string.results_none))
        else -> LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            itemsIndexed(r.standings) { index, s ->
                val deck = s.decklist
                Surface(
                    color = Brand.Panel,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth()
                        .then(if (deck != null) Modifier.clickable { open = if (open == index) null else index } else Modifier),
                ) {
                    Column(Modifier.padding(12.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "${s.position}",
                                Modifier.width(36.dp),
                                style = MaterialTheme.typography.titleMedium,
                                color = if (s.position <= 8) Brand.Accent else muted,
                            )
                            Column(Modifier.weight(1f)) {
                                Text(s.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                if (s.archetype.isNotBlank()) {
                                    Text(s.archetype, style = MaterialTheme.typography.bodySmall, color = muted)
                                }
                            }
                            Column(horizontalAlignment = Alignment.End) {
                                Text(stringResource(R.string.results_points, s.points), fontWeight = FontWeight.Bold)
                                if (s.record.isNotBlank()) Text(s.record, style = MaterialTheme.typography.bodySmall, color = muted)
                            }
                        }
                        if (deck != null) {
                            if (open == index) {
                                DeckText(deck, Modifier.padding(top = 10.dp))
                            } else {
                                Text(
                                    stringResource(R.string.results_show_deck),
                                    color = Brand.Accent,
                                    style = MaterialTheme.typography.labelLarge,
                                    modifier = Modifier.padding(top = 6.dp),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

/** Gli archetipi del torneo: quanti li giocavano e come sono andati. */
@Composable
private fun MetaList(rows: List<MetaRow>) {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    LazyColumn(contentPadding = PaddingValues(16.dp), modifier = Modifier.fillMaxSize()) {
        item {
            Row(Modifier.padding(bottom = 8.dp)) {
                Text(stringResource(R.string.archive_archetype), Modifier.weight(1f), color = muted, style = MaterialTheme.typography.labelSmall)
                Text(stringResource(R.string.results_players), Modifier.width(64.dp), color = muted, style = MaterialTheme.typography.labelSmall)
                Text(stringResource(R.string.record_header), Modifier.width(72.dp), color = muted, style = MaterialTheme.typography.labelSmall)
                Text(stringResource(R.string.results_win_rate), Modifier.width(64.dp), color = muted, style = MaterialTheme.typography.labelSmall)
            }
        }
        itemsIndexed(rows.sortedByDescending { it.players }) { _, m ->
            HorizontalDivider(color = Brand.Line)
            Row(Modifier.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(m.archetype.ifBlank { stringResource(R.string.archive_no_archetype) }, Modifier.weight(1f), maxLines = 2)
                Text("${m.players}", Modifier.width(64.dp))
                Text("${m.wins}/${m.draws}/${m.losses}", Modifier.width(72.dp), color = muted)
                Text(percent(m.winRate), Modifier.width(64.dp), fontWeight = FontWeight.Bold)
            }
        }
    }
}

/** Il taglio, turno per turno: chi ha vinto è in evidenza. */
@Composable
private fun Bracket(matches: List<BracketMatch>) {
    val rounds = matches.groupBy { it.roundNumber }.toSortedMap()
    LazyColumn(
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        rounds.forEach { (number, list) ->
            item(key = "turno-$number") {
                SectionTitle(
                    when (list.size) {
                        1 -> stringResource(R.string.bracket_final)
                        2 -> stringResource(R.string.bracket_semis)
                        4 -> stringResource(R.string.bracket_quarters)
                        else -> stringResource(R.string.round_title, number)
                    },
                )
            }
            itemsIndexed(list.sortedBy { it.tableNumber }, key = { _, m -> "match-${m.pairingId}" }) { _, m ->
                Panel {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Side(m.playerA, m.matchWinsA, m.winner != null && m.winner == m.playerA)
                        Side(m.playerB ?: stringResource(R.string.round_bye), m.matchWinsB, m.winner != null && m.winner == m.playerB)
                    }
                }
            }
        }
    }
}

@Composable
private fun Side(name: String, wins: Int, won: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            name,
            Modifier.weight(1f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            fontWeight = if (won) FontWeight.Bold else null,
            color = if (won) Brand.Accent else MaterialTheme.colorScheme.onSurface,
        )
        Text("$wins", fontWeight = if (won) FontWeight.Bold else null)
    }
}
