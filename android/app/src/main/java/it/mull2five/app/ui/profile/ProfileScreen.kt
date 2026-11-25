package it.mull2five.app.ui.profile

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.BuildConfig
import it.mull2five.app.R
import it.mull2five.app.data.User
import it.mull2five.app.ui.ActingBanner
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.NavRow
import it.mull2five.app.ui.appViewModel
import it.mull2five.app.ui.inbox.InboxAction
import it.mull2five.app.ui.openInTab
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.launch

class ProfileViewModel(private val c: AppContainer) : ViewModel() {
    var me by mutableStateOf<User?>(null)
        private set

    fun load() {
        if (c.session.user.value == null) {
            me = null
            return
        }
        viewModelScope.launch { c.attempt { c.api.me() }.onSuccess { me = it } }
    }

    fun stopActing() = c.session.actAs(null)

    fun logout() {
        val bearer = c.session.token
        c.session.clear()
        // Dopo, senza far aspettare chi esce: il server smetta di svegliare questo
        // telefono per l'account appena uscito. Senza rete pazienza.
        if (bearer != null) viewModelScope.launch { c.attempt { c.inbox.forgetDevice(bearer) } }
    }
}

/**
 * Il profilo: le statistiche, le liste salvate, le segnalazioni e l'account,
 * tutto dentro l'app. Fuori restano solo privacy e termini, che sono pagine del sito.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    onLogin: () -> Unit,
    onStats: () -> Unit,
    onDecks: () -> Unit,
    onTickets: () -> Unit,
    onAccount: () -> Unit,
) {
    val vm = appViewModel { ProfileViewModel(it) }
    val container = LocalContainer.current
    val user by container.session.user.collectAsStateWithLifecycle()
    val acting by container.session.acting.collectAsStateWithLifecycle()
    LaunchedEffect(user) { vm.load() }
    val context = LocalContext.current
    val open = { page: String -> context.openInTab("${container.siteUrl}/$page") }

    Scaffold(topBar = { TopAppBar(title = { Text(stringResource(R.string.profile_title)) }, actions = { InboxAction() }) }) { padding ->
        Column(Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState())) {
            if (user == null) {
                Column(Modifier.padding(vertical = 24.dp)) {
                    MessageBox(
                        stringResource(R.string.profile_signed_out),
                        Modifier.padding(0.dp),
                        stringResource(R.string.login_submit),
                        onLogin,
                    )
                }
            } else {
                acting?.let { ActingBanner(it.name, onStop = vm::stopActing) }
                ListItem(
                    headlineContent = { Text(vm.me?.displayName ?: user?.email.orEmpty(), style = MaterialTheme.typography.titleMedium) },
                    supportingContent = { Text(user?.email.orEmpty()) },
                    leadingContent = { Icon(Icons.Filled.AccountCircle, contentDescription = null, tint = Brand.Accent) },
                    colors = ListItemDefaults.colors(containerColor = Brand.Bg),
                )
                HorizontalDivider(color = Brand.Line)
                NavRow(stringResource(R.string.profile_stats), icon = Icons.Filled.Star, onClick = onStats)
                NavRow(stringResource(R.string.profile_decks), icon = Icons.AutoMirrored.Filled.List, onClick = onDecks)
                NavRow(stringResource(R.string.profile_tickets), icon = Icons.Filled.Email, onClick = onTickets)
                NavRow(stringResource(R.string.profile_account), icon = Icons.Filled.Lock, onClick = onAccount)
                Item(Icons.AutoMirrored.Filled.ExitToApp, stringResource(R.string.profile_logout), onClick = vm::logout)
                HorizontalDivider(color = Brand.Line)
            }
            Item(Icons.Filled.Info, stringResource(R.string.link_privacy)) { open("privacy.html") }
            Item(Icons.Filled.Info, stringResource(R.string.link_terms)) { open("termini.html") }
            Text(
                stringResource(R.string.profile_version, BuildConfig.VERSION_NAME),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(16.dp),
            )
        }
    }
}

@Composable
private fun Item(icon: ImageVector, text: String, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(text) },
        leadingContent = { Icon(icon, contentDescription = null) },
        colors = ListItemDefaults.colors(containerColor = Brand.Bg),
        modifier = Modifier.clickable(onClick = onClick),
    )
}
