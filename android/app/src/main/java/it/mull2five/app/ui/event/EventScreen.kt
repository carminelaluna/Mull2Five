package it.mull2five.app.ui.event

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.CalendarContract
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.data.Formats
import it.mull2five.app.data.Registration
import it.mull2five.app.data.RegistrationField
import it.mull2five.app.data.RegistrationIn
import it.mull2five.app.data.Tournament
import it.mull2five.app.ui.Badge
import it.mull2five.app.ui.ErrorBox
import it.mull2five.app.ui.InfoRow
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.LoadingBox
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.Panel
import it.mull2five.app.ui.SectionTitle
import it.mull2five.app.ui.Tone
import it.mull2five.app.ui.UiText
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.asString
import it.mull2five.app.ui.events.feeText
import it.mull2five.app.ui.openExternal
import it.mull2five.app.ui.openInTab
import it.mull2five.app.ui.share
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId

data class EventData(val tournament: Tournament, val registration: Registration?)

/** Quello che serve al modulo d'iscrizione, chiesto all'API quando lo si apre. */
data class RegisterForm(
    val fields: List<RegistrationField>,
    val methods: List<String>,
    val publisherId: String,
    val handle: String,
)

/** La pagina di un torneo (event.html): cosa, dove, quanto, e l'iscrizione. */
class EventViewModel(private val c: AppContainer, private val id: Int, openRegistration: Boolean) : ViewModel() {
    var state by mutableStateOf<Load<EventData>>(Load.Loading)
        private set
    var form by mutableStateOf<RegisterForm?>(null)
        private set
    var preparing by mutableStateOf(false)
        private set
    var submitting by mutableStateOf(false)
        private set
    var formError by mutableStateOf<String?>(null)
        private set
    var notice by mutableStateOf<UiText?>(null)
        private set

    /** Chi apre il link del QR, o chi è andato ad accedere per iscriversi: il modulo si apre da solo. */
    private var wantsToRegister = openRegistration
    private var userId: Int? = c.session.user.value?.id

    private val _links = Channel<String>(Channel.BUFFERED)
    val links = _links.receiveAsFlow()

    val signedIn: Boolean get() = c.session.user.value != null

    // Il primo caricamento lo fa la schermata quando si apre (LifecycleResumeEffect).

    /** Dopo l'accesso (o l'uscita) la pagina si ricarica: cambia l'iscrizione da mostrare. */
    fun onSession(id: Int?) {
        if (id == userId) return
        userId = id
        load()
    }

    fun load(quiet: Boolean = false) {
        viewModelScope.launch {
            if (!quiet && state !is Load.Ready) state = Load.Loading
            c.attempt {
                val tournament = c.api.tournament(id)
                EventData(tournament, if (signedIn) c.api.myRegistration(id) else null)
            }.onSuccess { data ->
                state = Load.Ready(data)
                if (wantsToRegister && signedIn && data.registration == null && canRegister(data.tournament)) {
                    wantsToRegister = false
                    openRegistration()
                }
            }.onFailure { if (!quiet || state !is Load.Ready) state = Load.Failed(c.messageOf(it)) }
        }
    }

    fun loginToRegister() {
        wantsToRegister = true
    }

    fun openRegistration() {
        val t = (state as? Load.Ready)?.value?.tournament ?: return
        if (preparing) return
        preparing = true
        notice = null
        viewModelScope.launch {
            // Come event.js: quello che manca si salta, l'iscrizione resta possibile.
            val fields = c.attempt { c.api.fields(id) }.getOrDefault(emptyList())
            val online = c.attempt { c.api.paymentOptions() }.getOrNull()?.online ?: false
            val ids = c.attempt { c.api.publisherIds() }.getOrDefault(emptyMap())
            val handles = if (t.isOnline) c.attempt { c.api.handles() }.getOrDefault(emptyMap()) else emptyMap()
            formError = null
            form = RegisterForm(
                fields = fields,
                methods = if (t.entryFeeNowCents > 0) t.paymentMethods(online) else emptyList(),
                publisherId = ids[t.game].orEmpty(),
                handle = handles[t.onlinePlatform].orEmpty(),
            )
            preparing = false
        }
    }

    fun closeForm() {
        form = null
    }

    fun submit(input: RegistrationIn) {
        if (submitting) return
        submitting = true
        formError = null
        viewModelScope.launch {
            c.attempt { c.api.register(id, input) }
                .onSuccess { registration ->
                    form = null
                    if (registration.checkoutUrl.isNotBlank()) {
                        // Ha scelto di pagare online: si paga adesso, e l'iscrizione vale dopo.
                        _links.send(registration.checkoutUrl)
                    } else {
                        notice = UiText.Res(if (registration.waitlisted) R.string.event_waitlisted else R.string.event_registered_now)
                    }
                    load(quiet = true)
                }
                .onFailure { formError = c.messageOf(it) }
            submitting = false
        }
    }

    companion object {
        fun canRegister(t: Tournament) = t.status == "published" && t.registrationMode == "open" && !t.isShowcase
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EventScreen(id: Int, openRegistration: Boolean, onBack: () -> Unit, onLogin: () -> Unit, onOpenMine: () -> Unit) {
    val container = LocalContainer.current
    val vm = appViewModel(key = "evento-$id") { EventViewModel(it, id, openRegistration) }
    val context = LocalContext.current
    val user by container.session.user.collectAsStateWithLifecycle()
    LaunchedEffect(user) { vm.onSession(user?.id) }
    LaunchedEffect(vm) { vm.links.collect { context.openInTab(it) } }
    // Di ritorno dal pagamento (o da un'altra app) l'iscrizione può essere cambiata.
    LifecycleResumeEffect(vm) {
        vm.load(quiet = true)
        onPauseOrDispose { }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.event_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back)) }
                },
                actions = {
                    IconButton(onClick = { context.share("${container.siteUrl}/event.html?id=$id") }) {
                        Icon(Icons.Filled.Share, stringResource(R.string.event_share))
                    }
                },
            )
        },
    ) { padding ->
        when (val state = vm.state) {
            Load.Loading -> LoadingBox(Modifier.padding(padding))
            is Load.Failed -> ErrorBox(state.message, onRetry = { vm.load() }, modifier = Modifier.padding(padding))
            is Load.Ready -> EventBody(
                data = state.value,
                vm = vm,
                modifier = Modifier.padding(padding),
                onLogin = {
                    vm.loginToRegister()
                    onLogin()
                },
                onOpenMine = onOpenMine,
            )
        }
    }

    val data = (vm.state as? Load.Ready)?.value
    val form = vm.form
    if (data != null && form != null) {
        RegisterSheet(
            t = data.tournament,
            form = form,
            busy = vm.submitting,
            error = vm.formError,
            onDismiss = vm::closeForm,
            onSubmit = vm::submit,
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EventBody(data: EventData, vm: EventViewModel, modifier: Modifier, onLogin: () -> Unit, onOpenMine: () -> Unit) {
    val t = data.tournament
    val context = LocalContext.current
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        Text(t.name, style = MaterialTheme.typography.headlineSmall)
        val organizer = listOfNotNull(t.organizerName, t.organizationName).distinct().joinToString(" · ")
        if (organizer.isNotBlank()) {
            Text(
                stringResource(R.string.event_organized_by, organizer),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
        FlowRow(
            Modifier.padding(vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (t.format.isNotBlank()) Badge(t.format, Tone.Accent)
            when (t.status) {
                "running" -> Badge(stringResource(R.string.status_running), Tone.Ok)
                "completed" -> Badge(stringResource(R.string.status_completed))
                "cancelled" -> Badge(stringResource(R.string.status_cancelled), Tone.Danger)
            }
            if (t.isFull) Badge(stringResource(R.string.event_full), Tone.Warn)
        }

        Panel {
            Column {
                val time = t.startTime?.let { " · $it" }.orEmpty()
                InfoRow(Icons.Filled.DateRange, Formats.date(t.startsOn) + time)
                if (t.isOnline) {
                    InfoRow(Icons.Filled.LocationOn, stringResource(R.string.event_online), detail = t.onlinePlatform)
                } else if (t.place.isNotBlank()) {
                    InfoRow(
                        Icons.Filled.LocationOn,
                        t.venue.ifBlank { t.city },
                        detail = t.city.takeIf { t.venue.isNotBlank() },
                        modifier = Modifier.clickable { context.openMap(t) },
                    )
                }
                InfoRow(
                    Icons.Filled.ShoppingCart,
                    feeText(t),
                    detail = if (t.earlyBirdOn) stringResource(
                        R.string.event_early_bird,
                        Formats.date(t.earlyBirdUntil.orEmpty()),
                        Formats.money(t.entryFeeCents, t.currency),
                    ) else null,
                )
                InfoRow(
                    Icons.Filled.Person,
                    if (t.capacity > 0) stringResource(R.string.event_players_of, t.registeredPlayers, t.capacity)
                    else stringResource(R.string.event_players, t.registeredPlayers),
                )
                structureText(t)?.let { InfoRow(Icons.Filled.Info, it) }
            }
        }

        Spacer(Modifier.height(16.dp))
        Action(data, vm, onLogin, onOpenMine)
        vm.notice?.let {
            Text(it.asString(), color = Brand.Green, modifier = Modifier.padding(top = 12.dp))
        }

        Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { context.addToCalendar(t) }) { Text(stringResource(R.string.event_calendar)) }
            if (!t.isOnline && t.place.isNotBlank()) {
                OutlinedButton(onClick = { context.openMap(t) }) { Text(stringResource(R.string.event_map)) }
            }
        }

        if (t.description.isNotBlank()) {
            SectionTitle(stringResource(R.string.event_details))
            Text(t.description, style = MaterialTheme.typography.bodyMedium)
        }
        if (t.refundPolicy.isNotBlank()) {
            SectionTitle(stringResource(R.string.event_refunds))
            Text(t.refundPolicy, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Spacer(Modifier.height(24.dp))
    }
}

/** Il pulsante che conta: iscriversi, o andare al proprio torneo. */
@Composable
private fun Action(data: EventData, vm: EventViewModel, onLogin: () -> Unit, onOpenMine: () -> Unit) {
    val t = data.tournament
    val context = LocalContext.current
    val wide = Modifier.fillMaxWidth().height(52.dp)
    val registration = data.registration
    when {
        registration != null -> Panel(color = Brand.AccentDim) {
            Column {
                Text(
                    stringResource(if (registration.waitlisted) R.string.event_waitlisted else R.string.event_registered),
                    style = MaterialTheme.typography.titleMedium,
                    color = Brand.Accent,
                )
                Spacer(Modifier.height(12.dp))
                Button(onClick = onOpenMine, modifier = wide) { Text(stringResource(R.string.event_open_mine)) }
            }
        }
        t.isShowcase && t.externalUrl.isNotBlank() ->
            Button(onClick = { context.openExternal(t.externalUrl) }, modifier = wide) {
                Text(stringResource(R.string.event_register_elsewhere))
            }
        EventViewModel.canRegister(t) ->
            if (vm.signedIn) {
                Button(onClick = vm::openRegistration, enabled = !vm.preparing, modifier = wide) {
                    if (vm.preparing) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
                    else Text(stringResource(R.string.event_register))
                }
            } else {
                Button(onClick = onLogin, modifier = wide) { Text(stringResource(R.string.event_login_to_register)) }
            }
        t.status == "published" && t.registrationMode == "invite_only" ->
            Text(stringResource(R.string.event_invite_only), color = MaterialTheme.colorScheme.onSurfaceVariant)
        t.status == "published" ->
            Text(stringResource(R.string.event_registration_closed), color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun structureText(t: Tournament): String? {
    // top_cut_size ha sempre un valore (8 di partenza): conta solo con "Svizzera + top cut".
    val parts = buildList {
        if (t.structure in setOf("swiss", "swiss_topcut") && t.swissRounds > 0) {
            add(stringResource(R.string.event_swiss_rounds, t.swissRounds))
        }
        if (t.structure == "swiss_topcut" && t.topCutSize > 0) add(stringResource(R.string.event_top_cut, t.topCutSize))
    }
    return parts.takeIf { it.isNotEmpty() }?.joinToString(" · ")
}

private fun Context.openMap(t: Tournament) {
    val query = if (t.latitude != null && t.longitude != null) "${t.latitude},${t.longitude}(${t.venue.ifBlank { t.name }})"
    else t.place
    openExternal("geo:0,0?q=" + Uri.encode(query))
}

/** Il torneo nel calendario del telefono: si apre l'app del calendario, con i campi già scritti. */
private fun Context.addToCalendar(t: Tournament) {
    val intent = Intent(Intent.ACTION_INSERT, CalendarContract.Events.CONTENT_URI)
        .putExtra(CalendarContract.Events.TITLE, t.name)
        .putExtra(CalendarContract.Events.EVENT_LOCATION, t.place)
    val day = runCatching { LocalDate.parse(t.startsOn) }.getOrNull()
    val time = t.startTime?.let { runCatching { LocalTime.parse(it) }.getOrNull() }
    if (day != null) {
        val start = day.atTime(time ?: LocalTime.MIDNIGHT).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
        intent.putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, start)
        if (time == null) intent.putExtra(CalendarContract.EXTRA_EVENT_ALL_DAY, true)
        else intent.putExtra(CalendarContract.EXTRA_EVENT_END_TIME, start + 4 * 3600_000L)
    }
    try {
        startActivity(intent)
    } catch (_: ActivityNotFoundException) {
        // Nessuna app di calendario.
    }
}
