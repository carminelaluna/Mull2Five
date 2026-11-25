package it.mull2five.app.ui.profile

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import it.mull2five.app.R
import it.mull2five.app.data.Breakdown
import it.mull2five.app.data.Formats
import it.mull2five.app.data.HistoryRow
import it.mull2five.app.data.PlayerProfile
import it.mull2five.app.data.User
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.Loaded
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.Panel
import it.mull2five.app.ui.SectionTitle
import it.mull2five.app.ui.ShareButton
import it.mull2five.app.ui.Stat
import it.mull2five.app.ui.SubScreen
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.discover.percent
import it.mull2five.app.ui.events.eventTypeLabel
import it.mull2five.app.ui.rememberLoad
import it.mull2five.app.ui.theme.Brand

data class MyStats(val user: User, val profile: PlayerProfile)

/**
 * Le proprie statistiche, come le vede chi apre il profilo pubblico
 * (player.html): totali, record per formato e per archetipo, i tornei giocati.
 */
@Composable
fun StatsScreen(onBack: () -> Unit, onTournament: (id: Int, completed: Boolean) -> Unit) {
    val vm = rememberLoad("statistiche") { c ->
        val me = c.api.me()
        MyStats(me, c.api.player(me.publicId))
    }
    val c = LocalContainer.current
    val publicId = (vm.state as? Load.Ready)?.value?.user?.publicId.orEmpty()
    SubScreen(
        stringResource(R.string.stats_title),
        onBack,
        actions = { if (publicId.isNotBlank()) ShareButton("${c.siteUrl}/player.html?p=$publicId") },
    ) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { data ->
            val p = data.profile
            val played = p.wins + p.draws + p.losses
            LazyColumn(
                Modifier.padding(padding).fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item(key = "testa") {
                    Column {
                        Text(p.displayName, style = MaterialTheme.typography.headlineSmall)
                        Text(
                            stringResource(R.string.stats_public_note),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                item(key = "totali") {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Stat("${p.tournamentsPlayed}", stringResource(R.string.stats_tournaments), Modifier.weight(1f))
                        Stat("${p.totalPoints}", stringResource(R.string.standings_points), Modifier.weight(1f))
                        Stat("${p.wins}/${p.draws}/${p.losses}", stringResource(R.string.record_header), Modifier.weight(1f))
                        Stat(
                            if (played > 0) percent(p.wins * 100.0 / played) else "–",
                            stringResource(R.string.results_win_rate),
                            Modifier.weight(1f),
                        )
                    }
                }
                if (p.byFormat.isNotEmpty()) {
                    item(key = "formati-titolo") { SectionTitle(stringResource(R.string.stats_by_format)) }
                    item(key = "formati") { BreakdownTable(p.byFormat) }
                }
                if (p.byArchetype.isNotEmpty()) {
                    item(key = "archetipi-titolo") { SectionTitle(stringResource(R.string.stats_by_archetype)) }
                    item(key = "archetipi") { BreakdownTable(p.byArchetype) }
                }
                item(key = "storico-titolo") { SectionTitle(stringResource(R.string.stats_history)) }
                if (p.rows.isEmpty()) {
                    item(key = "storico-vuoto") {
                        Text(stringResource(R.string.stats_no_history), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                itemsIndexed(p.rows.sortedByDescending { it.startsOn }) { _, row ->
                    HistoryCard(row, onClick = { onTournament(row.tournamentId, row.status == "completed") })
                }
            }
        }
    }
}

/** Il record per formato o per archetipo. */
@Composable
private fun BreakdownTable(rows: List<Breakdown>) {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Panel {
        Column {
            rows.forEachIndexed { index, b ->
                if (index > 0) HorizontalDivider(color = Brand.Line)
                Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(b.label.ifBlank { stringResource(R.string.archive_no_archetype) }, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(stringResource(R.string.circuit_row_tournaments, b.tournaments), style = MaterialTheme.typography.bodySmall, color = muted)
                    }
                    Text("${b.wins}/${b.draws}/${b.losses}", Modifier.width(72.dp), color = muted)
                    Text(percent(b.winRate), Modifier.width(64.dp), fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun HistoryCard(row: HistoryRow, onClick: () -> Unit) {
    Surface(
        color = Brand.Panel,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(row.tournamentName, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(
                listOf(Formats.date(row.startsOn), row.format).filter { it.isNotBlank() }.joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(8.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                row.placement?.let { Badge("#$it", if (it <= 8) Tone.Accent else Tone.Neutral) }
                if (row.record.isNotBlank()) Badge(row.record)
                Badge(stringResource(R.string.results_points, row.points))
                if (row.eventType != "locals") Badge(eventTypeLabel(row.eventType))
                if (row.invited) Badge(stringResource(R.string.stats_invited), Tone.Ok)
            }
        }
    }
}
