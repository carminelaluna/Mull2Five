package it.mull2five.app.ui.discover

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.data.ArchiveDeck
import it.mull2five.app.data.ArchiveFilter
import it.mull2five.app.data.ArchiveMeta
import it.mull2five.app.data.Circuit
import it.mull2five.app.data.Formats
import it.mull2five.app.data.Store
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.ChoiceChip
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.Loaded
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.Panel
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.rememberLoad
import it.mull2five.app.ui.rememberLocationRequest
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Locale
import kotlin.math.roundToInt

/** Scopri: i negozi (stores.html), i circuiti (circuits.html) e l'archivio delle liste (decklists.html). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiscoverScreen(onStore: (String) -> Unit, onCircuit: (String) -> Unit, onDeck: (Int) -> Unit) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    Scaffold(topBar = { TopAppBar(title = { Text(stringResource(R.string.discover_title)) }) }) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            PrimaryTabRow(selectedTabIndex = tab, containerColor = Brand.Bg) {
                listOf(R.string.discover_stores, R.string.discover_circuits, R.string.discover_decks).forEachIndexed { index, label ->
                    Tab(selected = tab == index, onClick = { tab = index }, text = { Text(stringResource(label)) })
                }
            }
            when (tab) {
                0 -> Stores(onStore)
                1 -> Circuits(onCircuit)
                else -> Archive(onDeck)
            }
        }
    }
}

// ── Negozi ────────────────────────────────────────────────────────────────

class StoresViewModel(private val c: AppContainer) : ViewModel() {
    var state by mutableStateOf<Load<List<Store>>>(Load.Loading)
        private set
    var query by mutableStateOf("")
    var premiumOnly by mutableStateOf(false)
    var near by mutableStateOf<Pair<Double, Double>?>(null)
        private set
    var locating by mutableStateOf(false)
        private set
    var locationMissing by mutableStateOf(false)
        private set

    init {
        load()
    }

    fun load() {
        val point = near
        viewModelScope.launch {
            if (state !is Load.Ready) state = Load.Loading
            c.attempt { c.api.stores(point) }
                .onSuccess { list ->
                    state = Load.Ready(if (point != null) list.sortedBy { it.distanceKm ?: Double.MAX_VALUE } else list)
                }
                .onFailure { if (state !is Load.Ready) state = Load.Failed(c.messageOf(it)) }
        }
    }

    fun startLocating() {
        locating = true
        locationMissing = false
    }

    fun located(point: Pair<Double, Double>?) {
        locating = false
        if (point == null) {
            locationMissing = true
        } else {
            near = point
            load()
        }
    }

    fun clearNear() {
        near = null
        load()
    }
}

@Composable
private fun Stores(onOpen: (String) -> Unit) {
    val vm = appViewModel { StoresViewModel(it) }
    val askLocation = rememberLocationRequest(vm::located)
    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = vm.query,
            onValueChange = { vm.query = it },
            placeholder = { Text(stringResource(R.string.stores_search)) },
            leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
            singleLine = true,
            shape = RoundedCornerShape(28.dp),
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(top = 12.dp),
        )
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = vm.near != null,
                onClick = {
                    if (vm.near != null) vm.clearNear()
                    else if (!vm.locating) {
                        vm.startLocating()
                        askLocation()
                    }
                },
                label = { Text(stringResource(R.string.events_near)) },
                leadingIcon = {
                    if (vm.locating) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                    else Icon(Icons.Filled.LocationOn, contentDescription = null, modifier = Modifier.size(18.dp))
                },
            )
            FilterChip(
                selected = vm.premiumOnly,
                onClick = { vm.premiumOnly = !vm.premiumOnly },
                label = { Text(stringResource(R.string.stores_premium)) },
            )
        }
        if (vm.locationMissing) {
            Text(
                stringResource(R.string.location_missing),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(horizontal = 16.dp).padding(bottom = 8.dp),
            )
        }
        Loaded(vm.state, vm::load) { stores ->
            val needle = vm.query.trim().lowercase()
            val shown = stores.filter {
                (!vm.premiumOnly || it.isPremium) &&
                    (needle.isEmpty() || needle in it.name.lowercase() || needle in it.city.lowercase())
            }
            if (shown.isEmpty()) {
                MessageBox(stringResource(R.string.stores_empty))
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    items(shown, key = { it.id }) { StoreCard(it, onClick = { onOpen(it.slug) }) }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun StoreCard(store: Store, onClick: () -> Unit) {
    Surface(
        color = Brand.Panel,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(store.name, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (store.city.isNotBlank()) {
                Text(store.city, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.height(8.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (store.isPremium) Badge(stringResource(R.string.stores_premium), Tone.Accent)
                Badge(
                    stringResource(R.string.stores_upcoming, store.upcomingCount),
                    if (store.upcomingCount > 0) Tone.Ok else Tone.Neutral,
                )
                store.distanceKm?.let { Badge(stringResource(R.string.distance_km, it.roundToInt())) }
            }
        }
    }
}

// ── Circuiti ──────────────────────────────────────────────────────────────

@Composable
private fun Circuits(onOpen: (String) -> Unit) {
    val vm = rememberLoad("circuiti") { it.api.circuits() }
    Loaded(vm.state, vm::load) { circuits ->
        val shown = circuits.filter { !it.slug.isNullOrBlank() }
        if (shown.isEmpty()) {
            MessageBox(stringResource(R.string.circuits_empty))
        } else {
            LazyColumn(
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                items(shown, key = { it.id }) { circuit -> CircuitCard(circuit, onClick = { onOpen(circuit.slug.orEmpty()) }) }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CircuitCard(circuit: Circuit, onClick: () -> Unit) {
    Surface(
        color = Brand.Panel,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(circuit.name, style = MaterialTheme.typography.titleMedium)
            circuitDates(circuit)?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.height(8.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (circuit.isActive) Badge(stringResource(R.string.circuit_active), Tone.Ok)
                else Badge(stringResource(R.string.circuit_closed))
                Badge(stringResource(R.string.circuit_stages, circuit.tournamentCount))
            }
        }
    }
}

/** "1 gen 2027 – 30 giu 2027", o null se il circuito non ha date. */
fun circuitDates(circuit: Circuit): String? =
    listOfNotNull(circuit.startsOn, circuit.endsOn).takeIf { it.isNotEmpty() }?.joinToString(" – ") { Formats.date(it) }

// ── Archivio delle liste ──────────────────────────────────────────────────

private val ARCHIVE_PERIODS = listOf(
    30 to R.string.period_30,
    90 to R.string.period_90,
    365 to R.string.period_365,
    0 to R.string.period_all,
)

private val TOPS = listOf(
    0 to R.string.archive_top_all,
    8 to R.string.archive_top_8,
    1 to R.string.archive_top_winners,
)

class ArchiveViewModel(private val c: AppContainer) : ViewModel() {
    var filter by mutableStateOf(ArchiveFilter())
        private set
    var formats by mutableStateOf<List<String>>(emptyList())
        private set
    var meta by mutableStateOf<ArchiveMeta?>(null)
        private set
    var state by mutableStateOf<Load<List<ArchiveDeck>>>(Load.Loading)
        private set
    var total by mutableIntStateOf(0)
        private set
    var searching by mutableStateOf(false)
        private set
    var loadingMore by mutableStateOf(false)
        private set

    private var page = 1
    private var job: Job? = null

    /** Il metagame dipende solo da formato e periodo: archetipo e carta non lo cambiano. */
    private var metaFor: Pair<String, Int>? = null

    init {
        load()
        viewModelScope.launch {
            c.attempt { c.api.games() }
                .onSuccess { games -> formats = games.flatMap { it.formats + it.limitedFormats }.distinct() }
        }
    }

    fun update(debounce: Boolean = false, change: (ArchiveFilter) -> ArchiveFilter) {
        filter = change(filter)
        load(debounce)
    }

    fun load(debounce: Boolean = false) {
        job?.cancel()
        val current = filter
        job = viewModelScope.launch {
            val me = coroutineContext[Job]
            if (debounce) delay(400)
            if (state is Load.Ready) searching = true else state = Load.Loading
            try {
                val key = current.format to current.days
                if (metaFor != key) {
                    meta = c.attempt { c.api.archiveMeta(current.format, current.days) }.getOrNull()
                    metaFor = key
                }
                c.attempt { c.api.archive(current, 1) }
                    .onSuccess {
                        page = 1
                        total = it.total
                        state = Load.Ready(it.items)
                    }
                    .onFailure { state = Load.Failed(c.messageOf(it)) }
            } finally {
                if (job === me) searching = false
            }
        }
    }

    fun more() {
        val shown = (state as? Load.Ready)?.value ?: return
        if (loadingMore || shown.size >= total) return
        loadingMore = true
        val current = filter
        viewModelScope.launch {
            c.attempt { c.api.archive(current, page + 1) }.onSuccess { next ->
                if (current == filter) {
                    page += 1
                    total = next.total
                    val seen = shown.map { it.decklistId }.toSet()
                    state = Load.Ready(shown + next.items.filter { it.decklistId !in seen })
                }
            }
            loadingMore = false
        }
    }
}

@Composable
private fun Archive(onOpen: (Int) -> Unit) {
    val vm = appViewModel { ArchiveViewModel(it) }
    val f = vm.filter
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(top = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            ChoiceChip(
                label = stringResource(R.string.events_format),
                options = vm.formats.map { it to it },
                selected = f.format,
                onSelect = { value -> vm.update { it.copy(format = value) } },
                allLabel = stringResource(R.string.archive_all_formats),
            )
            ChoiceChip(
                label = stringResource(R.string.events_period),
                options = ARCHIVE_PERIODS.map { (days, label) -> "$days" to stringResource(label) },
                selected = "${f.days}",
                onSelect = { value -> vm.update { it.copy(days = value.toInt()) } },
            )
            ChoiceChip(
                label = stringResource(R.string.archive_position),
                options = TOPS.map { (top, label) -> "$top" to stringResource(label) },
                selected = "${f.top}",
                onSelect = { value -> vm.update { it.copy(top = value.toInt()) } },
            )
        }
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = f.archetype,
                onValueChange = { text -> vm.update(debounce = true) { it.copy(archetype = text) } },
                label = { Text(stringResource(R.string.archive_archetype)) },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = f.card,
                onValueChange = { text -> vm.update(debounce = true) { it.copy(card = text) } },
                label = { Text(stringResource(R.string.archive_card)) },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
        }
        Box(Modifier.fillMaxSize()) {
            Loaded(vm.state, { vm.load() }) { decks ->
                LazyColumn(
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    vm.meta?.takeIf { it.totalLists > 0 }?.let { meta ->
                        item(key = "meta") { MetaPanel(meta, onArchetype = { name -> vm.update { it.copy(archetype = name) } }) }
                    }
                    if (decks.isEmpty()) {
                        item(key = "vuoto") {
                            Text(
                                stringResource(R.string.archive_empty),
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(vertical = 24.dp),
                            )
                        }
                    }
                    items(decks, key = { it.decklistId }) { ArchiveDeckCard(it, onClick = { onOpen(it.decklistId) }) }
                    if (decks.size < vm.total) {
                        item(key = "altre") {
                            OutlinedButton(onClick = vm::more, enabled = !vm.loadingMore, modifier = Modifier.fillMaxWidth()) {
                                Text(stringResource(R.string.archive_more, vm.total - decks.size))
                            }
                        }
                    }
                }
            }
            if (vm.searching) LinearProgressIndicator(Modifier.fillMaxWidth().align(Alignment.TopCenter))
        }
    }
}

/** Il metagame dell'archivio: gli archetipi più giocati (si toccano per filtrare) e le carte più usate. */
@Composable
private fun MetaPanel(meta: ArchiveMeta, onArchetype: (String) -> Unit) {
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(stringResource(R.string.archive_meta_title), style = MaterialTheme.typography.titleMedium)
            Text(
                stringResource(R.string.archive_lists, meta.totalLists),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            val max = (meta.archetypes.maxOfOrNull { it.share } ?: 1.0).coerceAtLeast(1.0)
            meta.archetypes.take(8).forEach { a ->
                Column(Modifier.fillMaxWidth().clickable { onArchetype(a.archetype) }.padding(vertical = 4.dp)) {
                    Row {
                        Text(a.archetype, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(percent(a.share), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Box(
                        Modifier.padding(top = 4.dp)
                            .fillMaxWidth((a.share / max).toFloat().coerceIn(0.02f, 1f))
                            .height(6.dp)
                            .background(Brand.Accent, RoundedCornerShape(3.dp)),
                    )
                }
            }
            if (meta.topCards.isNotEmpty()) {
                Text(
                    stringResource(R.string.archive_top_cards),
                    style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.padding(top = 10.dp),
                )
                meta.topCards.take(8).forEach { card ->
                    Row(Modifier.padding(vertical = 2.dp)) {
                        Text(card.name, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(
                            "${percent(card.share)} · ${String.format(Locale.getDefault(), "%.1f", card.copies)}×",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

fun percent(value: Double): String = String.format(Locale.getDefault(), "%.1f%%", value)

/** Una lista dell'archivio: posizione, archetipo, chi l'ha giocata e dove. */
@Composable
fun ArchiveDeckCard(d: ArchiveDeck, onClick: () -> Unit) {
    Surface(
        color = Brand.Panel,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.width(52.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text("#${d.position}", style = MaterialTheme.typography.titleLarge, color = Brand.Accent)
                if (d.players > 0) {
                    Text(
                        stringResource(R.string.archive_of_players, d.players),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    d.archetype.ifBlank { stringResource(R.string.archive_no_archetype) },
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(listOf(d.playerName, d.record).filter { it.isNotBlank() }.joinToString(" · "))
                Text(
                    listOfNotNull(d.tournamentName, Formats.date(d.startsOn), d.storeName).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}
