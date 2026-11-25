package it.mull2five.app.ui.events

import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.data.EventSearch
import it.mull2five.app.data.Formats
import it.mull2five.app.data.Tournament
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.ChoiceChip
import it.mull2five.app.ui.ErrorBox
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.LoadingBox
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.MultiChoiceChip
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.inbox.InboxAction
import it.mull2five.app.ui.rememberLocationRequest
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

/** I tipi di evento (catalog.js, EVENT_TYPES). */
val EVENT_TYPES = listOf(
    "locals" to R.string.type_locals,
    "prerelease" to R.string.type_prerelease,
    "rcq" to R.string.type_rcq,
    "store_championship" to R.string.type_store_championship,
    "premier" to R.string.type_premier,
    "other" to R.string.type_other,
)

private val RELS = listOf("Regular", "Competitive", "Professional")

/** I periodi della ricerca (catalog.js, DATE_RANGES): da oggi in avanti, o all'indietro per i conclusi. */
private val PERIODS = listOf(
    1 to R.string.period_1,
    7 to R.string.period_7,
    14 to R.string.period_14,
    30 to R.string.period_30,
    90 to R.string.period_90,
    180 to R.string.period_180,
    365 to R.string.period_365,
)

/** Le distanze (catalog.js, DISTANCES): 1000 km è "tutta Italia". */
private val DISTANCES = listOf(10, 25, 50, 100, 250, 1000)

@Composable
fun eventTypeLabel(code: String): String =
    stringResource(EVENT_TYPES.firstOrNull { it.first == code }?.second ?: R.string.type_other)

private fun List<String>.toggled(value: String) = if (value in this) this - value else this + value

/**
 * La ricerca degli eventi (events.html): in programma, i più vicini nel tempo
 * in cima, o conclusi, i più recenti in cima. Gli stessi filtri del sito.
 */
class EventsViewModel(private val c: AppContainer) : ViewModel() {
    var search by mutableStateOf(EventSearch())
        private set
    var formats by mutableStateOf<List<String>>(emptyList())
        private set
    var state by mutableStateOf<Load<List<Tournament>>>(Load.Loading)
        private set
    var refreshing by mutableStateOf(false)
        private set

    /** Una ricerca nuova mentre l'elenco di prima resta a vista. */
    var searching by mutableStateOf(false)
        private set
    var locating by mutableStateOf(false)
        private set
    var locationMissing by mutableStateOf(false)
        private set

    private var job: Job? = null

    init {
        load()
        viewModelScope.launch {
            c.attempt { c.api.games() }
                .onSuccess { games -> formats = games.flatMap { it.formats + it.limitedFormats }.distinct() }
        }
    }

    fun update(debounce: Boolean = false, change: (EventSearch) -> EventSearch) {
        search = change(search)
        load(debounce)
    }

    fun toggleFormat(value: String) = update { it.copy(formats = it.formats.toggled(value)) }
    fun toggleType(value: String) = update { it.copy(eventTypes = it.eventTypes.toggled(value)) }
    fun toggleRel(value: String) = update { it.copy(rel = it.rel.toggled(value)) }

    fun startLocating() {
        locating = true
        locationMissing = false
    }

    fun located(point: Pair<Double, Double>?) {
        locating = false
        if (point == null) locationMissing = true else update { it.copy(near = point) }
    }

    fun reset() {
        locationMissing = false
        update { EventSearch() }
    }

    fun refresh() = load(pull = true)

    fun load(debounce: Boolean = false, pull: Boolean = false) {
        job?.cancel()
        val current = search
        job = viewModelScope.launch {
            val me = coroutineContext[Job]
            if (debounce) delay(350)
            if (pull) refreshing = true else if (state is Load.Ready) searching = true else state = Load.Loading
            try {
                c.attempt { c.api.tournaments(current) }
                    .onSuccess { list ->
                        val byDate = compareBy<Tournament>({ it.startsOn }, { it.startTime.orEmpty() })
                        state = Load.Ready(list.sortedWith(if (current.past) byDate.reversed() else byDate))
                    }
                    .onFailure { state = Load.Failed(c.messageOf(it)) }
            } finally {
                // Una ricerca superata da un'altra non spegne l'attesa di quella nuova.
                if (job === me) {
                    refreshing = false
                    searching = false
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EventsScreen(onOpen: (Int) -> Unit) {
    val vm = appViewModel { EventsViewModel(it) }
    Scaffold(
        topBar = {
            TopAppBar(title = {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Image(painterResource(R.drawable.logo_mark), contentDescription = null, modifier = Modifier.size(28.dp))
                    Spacer(Modifier.width(10.dp))
                    Text(stringResource(R.string.events_title))
                }
            }, actions = { InboxAction() })
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            OutlinedTextField(
                value = vm.search.name,
                onValueChange = { text -> vm.update(debounce = true) { it.copy(name = text) } },
                placeholder = { Text(stringResource(R.string.events_search)) },
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                trailingIcon = {
                    if (vm.search.name.isNotEmpty()) {
                        IconButton(onClick = { vm.update { it.copy(name = "") } }) {
                            Icon(Icons.Filled.Clear, stringResource(R.string.events_search_clear))
                        }
                    }
                },
                singleLine = true,
                shape = RoundedCornerShape(28.dp),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            )
            Filters(vm)
            PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
                when (val state = vm.state) {
                    Load.Loading -> LoadingBox()
                    is Load.Failed -> ErrorBox(state.message, onRetry = { vm.load() })
                    is Load.Ready -> if (state.value.isEmpty()) {
                        MessageBox(
                            stringResource(if (vm.search.past) R.string.events_empty_past else R.string.events_empty),
                            action = if (vm.search.filtered) stringResource(R.string.filter_reset) else null,
                            onAction = vm::reset,
                        )
                    } else {
                        LazyColumn(
                            contentPadding = PaddingValues(16.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                            modifier = Modifier.fillMaxSize(),
                        ) {
                            items(state.value, key = { it.id }) { EventCard(it, onClick = { onOpen(it.id) }) }
                        }
                    }
                }
                if (vm.searching) LinearProgressIndicator(Modifier.fillMaxWidth().align(Alignment.TopCenter))
            }
        }
    }
}

@Composable
private fun Filters(vm: EventsViewModel) {
    val s = vm.search
    val askLocation = rememberLocationRequest(vm::located)
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        FilterChip(
            selected = s.past,
            onClick = { vm.update { it.copy(past = !it.past) } },
            label = { Text(stringResource(R.string.events_past)) },
        )
        ChoiceChip(
            label = stringResource(R.string.events_period),
            options = PERIODS.map { (days, label) -> "$days" to stringResource(label) },
            selected = "${s.days}",
            onSelect = { value -> vm.update { it.copy(days = value.toInt()) } },
        )
        FilterChip(
            selected = s.online == false,
            onClick = { vm.update { it.copy(online = if (it.online == false) null else false) } },
            label = { Text(stringResource(R.string.events_in_person)) },
        )
        FilterChip(
            selected = s.online == true,
            onClick = { vm.update { it.copy(online = if (it.online == true) null else true) } },
            label = { Text(stringResource(R.string.events_online)) },
        )
        FilterChip(
            selected = s.near != null,
            onClick = {
                if (s.near != null) vm.update { it.copy(near = null) }
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
        if (s.near != null) {
            ChoiceChip(
                label = stringResource(R.string.events_distance),
                options = DISTANCES.map { "$it" to if (it == 1000) stringResource(R.string.distance_all) else "$it km" },
                selected = "${s.radiusKm}",
                onSelect = { value -> vm.update { it.copy(radiusKm = value.toInt()) } },
            )
        }
        MultiChoiceChip(
            label = stringResource(R.string.events_type),
            options = EVENT_TYPES.map { (code, label) -> code to stringResource(label) },
            selected = s.eventTypes,
            onToggle = vm::toggleType,
            onClear = { vm.update { it.copy(eventTypes = emptyList()) } },
        )
        if (vm.formats.isNotEmpty()) {
            MultiChoiceChip(
                label = stringResource(R.string.events_format),
                options = vm.formats.map { it to it },
                selected = s.formats,
                onToggle = vm::toggleFormat,
                onClear = { vm.update { it.copy(formats = emptyList()) } },
            )
        }
        MultiChoiceChip(
            label = stringResource(R.string.events_rel),
            options = RELS.map { it to it },
            selected = s.rel,
            onToggle = vm::toggleRel,
            onClear = { vm.update { it.copy(rel = emptyList()) } },
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
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EventCard(t: Tournament, onClick: () -> Unit) {
    Surface(
        color = Brand.Panel,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.Top) {
            DateTile(t.startsOn)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(t.name, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                val where = if (t.isOnline) stringResource(R.string.event_online) else t.place
                val line = listOfNotNull(t.startTime, where.ifBlank { null }, t.organizationName).distinct().joinToString(" · ")
                if (line.isNotEmpty()) {
                    Text(
                        line,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Spacer(Modifier.size(8.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (t.format.isNotBlank()) Badge(t.format)
                    if (t.eventType != "locals") Badge(eventTypeLabel(t.eventType), Tone.Accent)
                    when (t.status) {
                        "running" -> Badge(stringResource(R.string.status_running), Tone.Accent)
                        "completed" -> Badge(stringResource(R.string.status_completed))
                        "cancelled" -> Badge(stringResource(R.string.status_cancelled), Tone.Danger)
                        else -> {
                            Badge(feeText(t), if (t.entryFeeNowCents == 0) Tone.Ok else Tone.Neutral)
                            if (t.isFull) Badge(stringResource(R.string.event_full), Tone.Warn)
                            else if (t.capacity > 0) Badge(stringResource(R.string.event_places, t.registeredPlayers, t.capacity))
                        }
                    }
                    t.distanceKm?.let { Badge(stringResource(R.string.distance_km, it.roundToInt())) }
                }
            }
        }
    }
}

@Composable
fun feeText(t: Tournament): String =
    if (t.entryFeeNowCents == 0) stringResource(R.string.event_free) else Formats.money(t.entryFeeNowCents, t.currency)

@Composable
private fun DateTile(iso: String) {
    Surface(color = Brand.Panel2, shape = RoundedCornerShape(12.dp)) {
        Column(Modifier.width(52.dp).padding(vertical = 8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(Formats.month(iso), style = MaterialTheme.typography.labelSmall, color = Brand.Accent)
            Text(Formats.day(iso), style = MaterialTheme.typography.titleLarge)
        }
    }
}
