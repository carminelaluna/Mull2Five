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
import it.mull2five.app.ui.LocalContainer
import it.mull2five.app.ui.MessageBox
import it.mull2five.app.ui.appViewModel
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

    fun logout() = c.session.clear()
}

/**
 * Il profilo. Quello che l'app non fa ancora (liste salvate, storico, dati e
 * privacy dell'account) si apre sul sito, in una scheda: lì si entra a parte.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(onLogin: () -> Unit) {
    val vm = appViewModel { ProfileViewModel(it) }
    val container = LocalContainer.current
    val user by container.session.user.collectAsStateWithLifecycle()
    LaunchedEffect(user) { vm.load() }
    val context = LocalContext.current
    val site = container.siteUrl
    val open = { page: String -> context.openInTab("$site/$page") }

    Scaffold(topBar = { TopAppBar(title = { Text(stringResource(R.string.profile_title)) }) }) { padding ->
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
                ListItem(
                    headlineContent = { Text(vm.me?.displayName ?: user?.email.orEmpty(), style = MaterialTheme.typography.titleMedium) },
                    supportingContent = { Text(user?.email.orEmpty()) },
                    leadingContent = { Icon(Icons.Filled.AccountCircle, contentDescription = null, tint = Brand.Accent) },
                    colors = ListItemDefaults.colors(containerColor = Brand.Bg),
                )
                HorizontalDivider(color = Brand.Line)
                Item(Icons.AutoMirrored.Filled.List, stringResource(R.string.profile_decks)) { open("decks.html") }
                Item(Icons.Filled.Star, stringResource(R.string.profile_history)) { open("history.html") }
                Item(Icons.Filled.Lock, stringResource(R.string.profile_account)) { open("my-registrations.html") }
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
