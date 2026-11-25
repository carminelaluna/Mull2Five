package it.mull2five.app.notify

import android.content.Context
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import it.mull2five.app.Mull2FiveApp
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * Firebase Cloud Messaging: il server sveglia l'app appena c'è una notifica
 * (services/fcm.py). Il messaggio non ha testo, dice solo "c'è qualcosa": l'app
 * scarica la campanella come fa il giro dei quindici minuti, e la frase la
 * scrive lei, nella lingua del telefono. A Google non passa quello che c'è scritto.
 *
 * C'è solo se l'app è compilata con google-services.json (docs/android.md):
 * senza, Firebase non parte, available() è falso e resta il giro di InboxWorker.
 */
object Push {
    fun available(context: Context): Boolean = FirebaseApp.getApps(context).isNotEmpty()

    /** Il token di questo telefono, o null se Firebase non lo dà. */
    suspend fun token(): String? = suspendCancellableCoroutine { continuation ->
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            continuation.resume(if (task.isSuccessful) task.result else null)
        }
    }
}

/** Dove arrivano i messaggi di Firebase. Li chiama da un thread suo: si può aspettare la rete. */
class PushService : FirebaseMessagingService() {
    private val container get() = (application as Mull2FiveApp).container

    override fun onMessageReceived(message: RemoteMessage) {
        runBlocking { container.attempt { container.inbox.showNew() } }
    }

    // Firebase cambia il token ogni tanto (app reinstallata, dati cancellati): il server deve saperlo.
    override fun onNewToken(token: String) {
        runBlocking { container.attempt { container.inbox.registerDevice(token) } }
    }
}
