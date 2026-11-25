package it.mull2five.app.ui.account

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.BuildConfig
import it.mull2five.app.R
import it.mull2five.app.data.ActingProfile
import it.mull2five.app.data.GoogleStatus
import it.mull2five.app.data.ManagedProfile
import it.mull2five.app.data.Pkce
import it.mull2five.app.data.User
import it.mull2five.app.ui.ActingBanner
import it.mull2five.app.ui.InfoRow
import it.mull2five.app.ui.Load
import it.mull2five.app.ui.Loaded
import it.mull2five.app.ui.Notice
import it.mull2five.app.ui.Panel
import it.mull2five.app.ui.SectionTitle
import it.mull2five.app.ui.SubScreen
import it.mull2five.app.ui.UiText
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.openInTab
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class AccountData(
    val user: User,
    val google: GoogleStatus?,
    val profiles: List<ManagedProfile>,
    val minAge: Int,
)

sealed interface AccountEffect {
    data class Open(val url: String) : AccountEffect
    data object SaveExport : AccountEffect
    data object SignedOut : AccountEffect
}

/** L'account (la parte "Account e privacy" di my-registrations.html): accesso, profili dei figli, dati. */
class AccountViewModel(private val c: AppContainer) : ViewModel() {
    var state by mutableStateOf<Load<AccountData>>(Load.Loading)
        private set
    var busy by mutableStateOf(false)
        private set
    var message by mutableStateOf<UiText?>(null)
        private set
    var messageIsError by mutableStateOf(false)
        private set
    val acting = c.session.acting

    private var pendingExport: String? = null
    private val _effects = Channel<AccountEffect>(Channel.BUFFERED)
    val effects = _effects.receiveAsFlow()

    init {
        load()
        // Il ritorno da Google arriva all'attività: l'esito passa da qui.
        viewModelScope.launch {
            c.googleLink.collect { outcome ->
                if (outcome != null) {
                    message = outcome.text
                    messageIsError = outcome.isError
                    c.googleLink.value = null
                    load()
                }
            }
        }
    }

    fun load() {
        viewModelScope.launch {
            if (state !is Load.Ready) state = Load.Loading
            c.attempt {
                AccountData(
                    user = c.api.me(),
                    google = c.attempt { c.api.googleStatus() }.getOrNull(),
                    profiles = c.attempt { c.api.profiles() }.getOrDefault(emptyList()),
                    minAge = c.attempt { c.api.rules() }.getOrNull()?.minAccountAge ?: 14,
                )
            }.onSuccess { state = Load.Ready(it) }
                .onFailure { if (state !is Load.Ready) state = Load.Failed(c.messageOf(it)) }
        }
    }

    /** "Collega Google": un biglietto per il giro, che torna all'app con un `code` (AuthViewModel). */
    fun linkGoogle() = act {
        val verifier = Pkce.newVerifier()
        val challenge = Pkce.challenge(verifier)
        val ticket = c.api.googleLinkTicket(challenge)
        c.session.googleVerifier = verifier
        c.session.googleLinking = true
        _effects.send(AccountEffect.Open(c.api.googleLinkUrl(BuildConfig.APPLICATION_ID, challenge, ticket)))
    }

    fun unlinkGoogle() = act {
        c.api.googleUnlink()
        note(R.string.account_google_unlinked)
        load()
    }

    /** Una password nuova si sceglie dal link che arriva per email, come "Password dimenticata?". */
    fun choosePassword() = act {
        val email = (state as? Load.Ready)?.value?.user?.email ?: return@act
        c.api.forgotPassword(email)
        note(R.string.account_password_sent)
    }

    fun actAs(profile: ManagedProfile) {
        c.session.actAs(ActingProfile(profile.id, profile.displayName))
        note(R.string.account_acting_now)
    }

    fun stopActing() = c.session.actAs(null)

    fun deleteProfile(profile: ManagedProfile) = act {
        c.api.deleteProfile(profile.id)
        if (c.session.acting.value?.id == profile.id) c.session.actAs(null)
        load()
    }

    /** I dati dell'account in un file: prima si chiedono al server, poi si sceglie dove salvarli. */
    fun export() = act {
        pendingExport = c.api.exportData()
        _effects.send(AccountEffect.SaveExport)
    }

    fun writeExport(context: Context, uri: Uri?) {
        val text = pendingExport ?: return
        pendingExport = null
        if (uri == null) return
        viewModelScope.launch {
            val saved = withContext(Dispatchers.IO) {
                runCatching { context.contentResolver.openOutputStream(uri)?.use { it.write(text.toByteArray()) } != null }
                    .getOrDefault(false)
            }
            if (saved) note(R.string.account_export_saved)
            else {
                message = UiText.Res(R.string.error_unexpected)
                messageIsError = true
            }
        }
    }

    fun logoutEverywhere() = act {
        c.api.logoutEverywhere()
        c.session.clear()
        _effects.send(AccountEffect.SignedOut)
    }

    fun deleteAccount() = act {
        c.api.deleteAccount()
        c.session.clear()
        _effects.send(AccountEffect.SignedOut)
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

private sealed interface Asking {
    data object LogoutAll : Asking
    data object Delete : Asking
    data class DropProfile(val profile: ManagedProfile) : Asking
}

@Composable
fun AccountScreen(onBack: () -> Unit, onRequestProfile: () -> Unit, onSignedOut: () -> Unit) {
    val vm = appViewModel { AccountViewModel(it) }
    val context = LocalContext.current
    val acting by vm.acting.collectAsStateWithLifecycle()
    val save = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        vm.writeExport(context, uri)
    }
    var asking by remember { mutableStateOf<Asking?>(null) }
    LaunchedEffect(vm) {
        vm.effects.collect {
            when (it) {
                is AccountEffect.Open -> context.openInTab(it.url)
                AccountEffect.SaveExport -> save.launch("mull2five-dati.json")
                AccountEffect.SignedOut -> onSignedOut()
            }
        }
    }

    SubScreen(stringResource(R.string.account_title), onBack) { padding ->
        Loaded(vm.state, vm::load, Modifier.padding(padding)) { data ->
            Column(
                Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Notice(vm.message, vm.messageIsError)

                SectionTitle(stringResource(R.string.account_data))
                Panel {
                    Column {
                        InfoRow(Icons.Filled.AccountCircle, data.user.displayName, detail = data.user.email)
                        Text(
                            stringResource(R.string.account_name_note),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }

                SectionTitle(stringResource(R.string.account_access))
                Access(data.google, vm)

                SectionTitle(stringResource(R.string.account_profiles))
                val who = acting
                if (who != null) {
                    ActingBanner(who.name, onStop = vm::stopActing)
                } else {
                    Profiles(data, vm, onRequestProfile, onDrop = { asking = Asking.DropProfile(it) })
                }

                SectionTitle(stringResource(R.string.account_privacy))
                Panel {
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text(
                            stringResource(R.string.account_export_text),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        OutlinedButton(onClick = vm::export, enabled = !vm.busy) { Text(stringResource(R.string.account_export)) }
                        OutlinedButton(onClick = { asking = Asking.LogoutAll }, enabled = !vm.busy) {
                            Text(stringResource(R.string.account_logout_all))
                        }
                        TextButton(onClick = { asking = Asking.Delete }, enabled = !vm.busy) {
                            Text(stringResource(R.string.account_delete), color = MaterialTheme.colorScheme.error)
                        }
                    }
                }
                Column(Modifier.padding(bottom = 24.dp)) {}
            }
        }
    }

    asking?.let { what ->
        val (title, text) = when (what) {
            Asking.LogoutAll -> stringResource(R.string.account_logout_all) to stringResource(R.string.account_logout_all_text)
            Asking.Delete -> stringResource(R.string.account_delete) to stringResource(R.string.account_delete_text)
            is Asking.DropProfile ->
                stringResource(R.string.account_profile_delete) to stringResource(R.string.account_profile_delete_text, what.profile.displayName)
        }
        AlertDialog(
            onDismissRequest = { asking = null },
            title = { Text(title) },
            text = { Text(text) },
            confirmButton = {
                TextButton(onClick = {
                    asking = null
                    when (what) {
                        Asking.LogoutAll -> vm.logoutEverywhere()
                        Asking.Delete -> vm.deleteAccount()
                        is Asking.DropProfile -> vm.deleteProfile(what.profile)
                    }
                }) { Text(stringResource(R.string.confirm), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { asking = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

/** Come si entra: la password (si sceglie dal link per email) e Google. */
@Composable
private fun Access(google: GoogleStatus?, vm: AccountViewModel) {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (google != null && (google.available || google.linked)) {
                if (google.linked) {
                    Text(stringResource(R.string.account_google_linked_as, google.email.ifBlank { "Google" }))
                    OutlinedButton(onClick = vm::unlinkGoogle, enabled = !vm.busy && google.hasPassword) {
                        Text(stringResource(R.string.account_google_unlink))
                    }
                    if (!google.hasPassword) {
                        Text(stringResource(R.string.account_google_needs_password), style = MaterialTheme.typography.bodySmall, color = muted)
                    }
                } else {
                    Text(stringResource(R.string.account_google_not_linked))
                    OutlinedButton(onClick = vm::linkGoogle, enabled = !vm.busy) { Text(stringResource(R.string.account_google_link)) }
                }
            }
            val hasPassword = google?.hasPassword != false
            Text(
                stringResource(if (hasPassword) R.string.account_password_text else R.string.account_password_none),
                style = MaterialTheme.typography.bodySmall,
                color = muted,
            )
            OutlinedButton(onClick = vm::choosePassword, enabled = !vm.busy) {
                Text(stringResource(if (hasPassword) R.string.account_password_change else R.string.account_password_choose))
            }
        }
    }
}

/** I profili dei figli: sotto l'età minima non si apre un account, li iscrive e paga il genitore. */
@Composable
private fun Profiles(data: AccountData, vm: AccountViewModel, onRequest: () -> Unit, onDrop: (ManagedProfile) -> Unit) {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(stringResource(R.string.account_profiles_text, data.minAge), style = MaterialTheme.typography.bodySmall, color = muted)
            data.profiles.forEach { p ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(p.displayName)
                        Text(
                            stringResource(R.string.account_profile_tournaments, p.registrations),
                            style = MaterialTheme.typography.bodySmall,
                            color = muted,
                        )
                    }
                    TextButton(onClick = { vm.actAs(p) }) { Text(stringResource(R.string.account_profile_manage)) }
                    if (p.registrations == 0) {
                        TextButton(onClick = { onDrop(p) }, enabled = !vm.busy) {
                            Text(stringResource(R.string.account_profile_delete), color = MaterialTheme.colorScheme.error)
                        }
                    }
                }
            }
            Text(stringResource(R.string.account_profile_request_text), style = MaterialTheme.typography.bodySmall, color = muted)
            OutlinedButton(onClick = onRequest) { Text(stringResource(R.string.account_profile_request)) }
        }
    }
}
