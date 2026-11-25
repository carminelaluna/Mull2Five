package it.mull2five.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.lifecycleScope
import it.mull2five.app.notify.Inbox
import it.mull2five.app.ui.AppRoot
import it.mull2five.app.ui.theme.Mull2FiveTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val container: AppContainer get() = (application as Mull2FiveApp).container

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) receive(intent)
        setContent { Mull2FiveTheme { AppRoot(container) } }
    }

    // singleTask: il ritorno da Google e i link arrivano qui, all'attività che c'è già.
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        receive(intent)
    }

    override fun onResume() {
        super.onResume()
        // Il token si rinnova a metà vita, come fa il sito a ogni pagina.
        if (container.session.user.value?.needsRefresh() == true) {
            lifecycleScope.launch {
                container.attempt { container.api.refresh() }.onSuccess(container.session::save)
            }
        }
        // Il numero sulla campanella: può essere cambiato mentre l'app era chiusa.
        lifecycleScope.launch { container.attempt { container.inbox.refreshUnread() } }
    }

    private fun receive(intent: Intent?) {
        intent?.getStringExtra(Inbox.EXTRA_URL)?.let { url ->
            container.incoming.value = Incoming.FromBell(url, intent.getIntExtra(Inbox.EXTRA_ID, 0))
            return
        }
        val uri = intent?.data ?: return
        container.incoming.value = incomingOf(uri) ?: return
    }

    private fun incomingOf(uri: Uri): Incoming? = when {
        uri.scheme == BuildConfig.APPLICATION_ID && uri.host == "google" ->
            Incoming.GoogleReturn(uri.getQueryParameter("code"), uri.getQueryParameter("error"))
        uri.scheme == "https" && uri.path == "/event.html" ->
            uri.getQueryParameter("id")?.toIntOrNull()?.let {
                Incoming.OpenTournament(it, register = uri.getQueryParameter("iscriviti") == "1")
            }
        else -> null
    }
}
