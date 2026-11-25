package it.mull2five.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Una notifica della campanella (routers/notifications.py). La frase non arriva:
 * arriva il tipo (`kind`) e i pezzi, e la frase la scrive l'app nella sua lingua
 * (notify/Inbox.kt), come fa il sito in js/inbox.js.
 */
@Serializable
data class AppNotification(
    val id: Int,
    val kind: String,
    val context: String = "",
    val title: String = "",
    val body: String = "",
    val detail: String = "",
    val url: String = "",
    @SerialName("created_at") val createdAt: String = "",
    val read: Boolean = false,
    /** Il profilo di un figlio: la notifica è sua, la legge il genitore. */
    @SerialName("for_name") val forName: String = "",
)

@Serializable
data class NotificationsPage(val items: List<AppNotification> = emptyList(), val unread: Int = 0)

@Serializable
data class UnreadCount(val unread: Int = 0, @SerialName("latest_id") val latestId: Int = 0)

/** Quali segnare come lette: null vuol dire tutte. */
@Serializable
data class NotificationsReadIn(val ids: List<Int>? = null)

/** Il token che Firebase dà a questo telefono (notify/Push.kt, services/fcm.py). */
@Serializable
data class DeviceIn(val token: String)
