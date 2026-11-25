package it.mull2five.app.notify

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.content.edit
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import it.mull2five.app.MainActivity
import it.mull2five.app.Mull2FiveApp
import it.mull2five.app.R
import it.mull2five.app.data.Api
import it.mull2five.app.data.AppNotification
import it.mull2five.app.data.Session
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import java.text.NumberFormat
import java.time.OffsetDateTime
import java.util.Currency
import java.util.concurrent.TimeUnit

/**
 * La campanella nell'app: il numero da leggere e le notifiche del telefono.
 *
 * Il sito le scrive nello storico (services/inbox.py). Se l'app ha Firebase
 * (Push.kt) il server la sveglia appena ce n'è una; in ogni caso, ogni quindici
 * minuti WorkManager sveglia InboxWorker. Tutti e due scaricano quelle arrivate
 * dopo l'ultima mostrata e le mettono fra le notifiche del telefono.
 * Quando il telefono dorme Android può ritardare il giro. Il giro rinnova anche
 * il token, come l'app aperta: si ferma solo uscendo.
 */
class Inbox(private val context: Context, private val api: Api, private val session: Session) {
    private val prefs = context.getSharedPreferences("campanella", Context.MODE_PRIVATE)
    private val _unread = MutableStateFlow(0)
    private val showing = Mutex()

    /** Quante da leggere: il numero sulla campanella in alto. */
    val unread: StateFlow<Int> = _unread.asStateFlow()

    fun setUnread(count: Int) {
        _unread.value = count
    }

    suspend fun refreshUnread() {
        if (session.user.value == null) setUnread(0) else setUnread(api.unreadNotifications().unread)
    }

    /**
     * Le arrivate dopo l'ultima mostrata, fra le notifiche del telefono. La prima
     * volta per un account segna il punto e basta: chi installa l'app non si
     * trova addosso le notifiche di un mese. Una alla volta: Firebase e il giro
     * dei quindici minuti possono arrivare insieme.
     */
    suspend fun showNew() = showing.withLock { fetchAndPost() }

    /** Con Firebase: il server sveglia questo telefono per chi c'è dentro (notify/Push.kt). */
    suspend fun registerDevice(token: String? = null) {
        if (session.user.value == null || !Push.available(context)) return
        val value = token ?: withTimeoutOrNull(TOKEN_WAIT_MS) { Push.token() } ?: return
        api.registerDevice(value)
    }

    /**
     * Uscendo: il server smette di svegliare questo telefono per quell'account.
     * `bearer` è il token di chi è uscito, già tolto dalla sessione.
     */
    suspend fun forgetDevice(bearer: String) {
        if (!Push.available(context)) return
        val value = withTimeoutOrNull(TOKEN_WAIT_MS) { Push.token() } ?: return
        api.forgetDevice(value, bearer)
    }

    private suspend fun fetchAndPost() {
        val user = session.user.value ?: return
        val key = "ultima_${user.id}"
        val last = prefs.getInt(key, -1)
        if (last < 0) {
            val counter = api.unreadNotifications()
            setUnread(counter.unread)
            prefs.edit { putInt(key, counter.latestId) }
            return
        }
        val page = api.notifications(afterId = last, limit = 20)
        setUnread(page.unread)
        if (page.items.isEmpty()) return
        page.items.filterNot { it.read }.sortedBy { it.id }.forEach(::post)
        prefs.edit { putInt(key, page.items.maxOf { it.id }) }
    }

    /** Il permesso per le notifiche (Android 13+) si chiede una volta, appena si entra. */
    fun needsPermissionPrompt(): Boolean =
        Build.VERSION.SDK_INT >= 33 && !prefs.getBoolean(KEY_ASKED, false) &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED

    fun permissionAsked() {
        prefs.edit { putBoolean(KEY_ASKED, true) }
    }

    /** Aperta la campanella nell'app, quelle sul telefono non servono più. */
    fun clearPosted() {
        NotificationManagerCompat.from(context).cancelAll()
    }

    @SuppressLint("MissingPermission")   // controllato in canPost()
    private fun post(n: AppNotification) {
        if (!canPost()) return
        ensureChannel()
        val where = listOf(n.context, n.title).filter { it.isNotBlank() }.joinToString(" · ")
        val forWhom = n.forName.takeIf { it.isNotBlank() }?.let { context.getString(R.string.inbox_for, it) }
        val open = Intent(context, MainActivity::class.java)
            .putExtra(EXTRA_URL, n.url)
            .putExtra(EXTRA_ID, n.id)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val tap = PendingIntent.getActivity(
            context, n.id, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_bell)
            .setColor(ACCENT)
            .setContentTitle(phrase(context, n))
            .setContentText(where.ifBlank { n.body })
            .setStyle(NotificationCompat.BigTextStyle().bigText(
                listOfNotNull(where.ifBlank { null }, n.body.ifBlank { null }, forWhom).joinToString("\n"),
            ))
            .setWhen(epochMillis(n.createdAt) ?: System.currentTimeMillis())
            .setShowWhen(true)
            .setContentIntent(tap)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(n.id, notification)
        } catch (_: SecurityException) {
            // Permesso tolto fra il controllo e l'invio: la notifica resta nella campanella.
        }
    }

    private fun canPost(): Boolean {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return false
        return Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun ensureChannel() {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) != null) return
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, context.getString(R.string.inbox_channel), NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = context.getString(R.string.inbox_channel_info) },
        )
    }

    companion object {
        const val EXTRA_URL = "campanella_url"
        const val EXTRA_ID = "campanella_id"
        private const val CHANNEL = "tornei"
        private const val KEY_ASKED = "permesso_chiesto"
        private const val ACCENT = 0xFFC6FF3D.toInt()
        private const val TOKEN_WAIT_MS = 10_000L
    }
}

/** Il giro dei quindici minuti. Fallito o no, riprova al prossimo: non insiste. */
class InboxWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val container = (applicationContext as Mull2FiveApp).container
        // Il token si rinnova a metà vita, come fa l'app aperta: senza, dopo tre
        // giorni lontano dall'app il giro si fermerebbe in silenzio.
        if (container.session.user.value?.needsRefresh() == true) {
            container.attempt { container.api.refresh() }.onSuccess(container.session::save)
        }
        container.attempt { container.inbox.showNew() }
        return Result.success()
    }

    companion object {
        private const val NAME = "campanella"

        /** Una volta sola per installazione: KEEP lascia il giro che c'è già. */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<InboxWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}

/** La riga in grassetto, dal tipo: le stesse frasi di phrase() in js/inbox.js. */
fun phrase(context: Context, n: AppNotification): String {
    val d = n.detail
    return when (n.kind) {
        "registered" -> context.getString(R.string.inbox_registered)
        "waitlisted" -> context.getString(R.string.inbox_waitlisted)
        "waitlist_in" -> if (d.isNotBlank()) context.getString(R.string.inbox_waitlist_pay, d)
            else context.getString(R.string.inbox_waitlist_in)
        "paid" -> context.getString(R.string.inbox_paid, money(d))
        "reminder" -> if (d.isNotBlank()) context.getString(R.string.inbox_reminder_at, d)
            else context.getString(R.string.inbox_reminder)
        "started" -> context.getString(R.string.inbox_started)
        "pairings" -> context.getString(R.string.inbox_pairings, d)
        "announcement" -> context.getString(R.string.inbox_announcement)
        "cancelled" -> context.getString(
            when (d) {
                "refunded" -> R.string.inbox_cancelled_refunded
                "requested" -> R.string.inbox_cancelled_requested
                else -> R.string.inbox_cancelled
            },
        )
        "ticket_new" -> context.getString(R.string.inbox_ticket_new)
        "ticket_reply" -> context.getString(R.string.inbox_ticket_reply)
        else -> context.getString(R.string.inbox_other)
    }
}

/** "10.00 EUR" come si scrive nella lingua del telefono. */
private fun money(detail: String): String {
    val parts = detail.split(" ")
    val amount = parts.firstOrNull()?.toDoubleOrNull() ?: return detail
    val currency = runCatching { Currency.getInstance(parts.getOrNull(1)) }.getOrNull() ?: return detail
    return NumberFormat.getCurrencyInstance().apply { this.currency = currency }.format(amount)
}

fun epochMillis(iso: String): Long? = runCatching { OffsetDateTime.parse(iso).toInstant().toEpochMilli() }.getOrNull()
