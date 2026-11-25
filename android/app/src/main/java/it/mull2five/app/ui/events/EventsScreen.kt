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
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
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
import it.mull2five.app.data.Formats
import it.mull2five.app.data.Tournament
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.ErrorBox
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.LoadingBox
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** La ricerca degli eventi (events.html): i tornei in calendario, i più vicini nel tempo in cima. */
class EventsViewModel(private val c: AppContainer) : ViewModel() {
    var query by mutableStateOf("")
        private set
    var days by mutableIntStateOf(30)
        private set

    /** null: tutti; true: solo online; false: solo dal vivo. */
    var online by mutableStateOf<Boolean?>(null)
        private set
    var state by mutableStateOf<Load<List<Tournament>>>(Load.Loading)
        private set
    var refreshing by mutableStateOf(false)
        private set

    private var job: Job? = null

    init {
        load()
    }

    fun search(text: String) {
        query = text
        load(debounce = true)
    }

    fun window(value: Int) {
        days = value
        load()
    }

    fun where(value: Boolean?) {
        online = value
        load()
    }

    fun refresh() = load(pull = true)

    fun load(debounce: Boolean = false, pull: Boolean = false) {
        job?.cancel()
        job = viewModelScope.launch {
            if (debounce) delay(350)
            if (pull) refreshing = true else if (state !is Load.Ready) state = Load.Loading
            c.attempt { c.api.tournaments(query, days, online) }
                .onSuccess { list -> state = Load.Ready(list.sortedWith(compareBy({ it.startsOn }, { it.startTime.orEmpty() }))) }
                .onFailure { state = Load.Failed(c.messageOf(it)) }
            refreshing = false
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
            })
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            OutlinedTextField(
                value = vm.query,
                onValueChange = vm::search,
                placeholder = { Text(stringResource(R.string.events_search)) },
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                trailingIcon = {
                    if (vm.query.isNotEmpty()) {
                        IconButton(onClick = { vm.search("") }) {
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
                        MessageBox(stringResource(R.string.events_empty))
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
            }
        }
    }
}

@Composable
private fun Filters(vm: EventsViewModel) {
    val windows = listOf(
        7 to R.string.events_days_7,
        30 to R.string.events_days_30,
        90 to R.string.events_days_90,
    )
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        windows.forEach { (value, label) ->
            FilterChip(selected = vm.days == value, onClick = { vm.window(value) }, label = { Text(stringResource(label)) })
        }
        FilterChip(
            selected = vm.online == false,
            onClick = { vm.where(if (vm.online == false) null else false) },
            label = { Text(stringResource(R.string.events_in_person)) },
        )
        FilterChip(
            selected = vm.online == true,
            onClick = { vm.where(if (vm.online == true) null else true) },
            label = { Text(stringResource(R.string.events_online)) },
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
                val line = listOfNotNull(t.startTime, where.ifBlank { null }).joinToString(" · ")
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
                    Badge(feeText(t), if (t.entryFeeNowCents == 0) Tone.Ok else Tone.Neutral)
                    if (t.status == "running") Badge(stringResource(R.string.status_running), Tone.Accent)
                    if (t.isFull) Badge(stringResource(R.string.event_full), Tone.Warn)
                    else if (t.capacity > 0) Badge(stringResource(R.string.event_places, t.registeredPlayers, t.capacity))
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
