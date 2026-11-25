package it.mull2five.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * L'account del giocatore (backend/app/schemas.py): le liste salvate, Google,
 * i profili dei figli, le segnalazioni.
 */

/** SavedDeckIn: una lista da salvare nel profilo. */
@Serializable
data class SavedDeckIn(
    val name: String,
    val game: String = "mtg",
    val format: String = "",
    val archetype: String = "",
    @SerialName("raw_text") val rawText: String = "",
)

/** DeckValidateIn: il controllo delle regole del formato, senza salvare. */
@Serializable
data class DeckValidateIn(
    @SerialName("raw_text") val rawText: String,
    val game: String = "mtg",
    val format: String = "",
    val legality: Boolean = false,
)

/** DeckValidateOut. */
@Serializable
data class DeckCheck(
    @SerialName("main_count") val mainCount: Int = 0,
    @SerialName("side_count") val sideCount: Int = 0,
    val status: String = "",
    val errors: List<String> = emptyList(),
)

/** La risposta di /cards/search: i nomi per l'autocompletamento. */
@Serializable
data class CardNames(val names: List<String> = emptyList())

/** DecklistOut: la lista già consegnata a un torneo. */
@Serializable
data class SubmittedDeck(
    val id: Int,
    val format: String = "",
    @SerialName("raw_text") val rawText: String = "",
    @SerialName("main_count") val mainCount: Int = 0,
    @SerialName("side_count") val sideCount: Int = 0,
    val status: String = "",
    @SerialName("validation_errors") val validationErrors: String = "",
)

/** ProfileOut: il profilo di un figlio, che il genitore iscrive e paga. */
@Serializable
data class ManagedProfile(
    val id: Int,
    @SerialName("display_name") val displayName: String,
    val registrations: Int = 0,
)

/** GoogleStatusOut. */
@Serializable
data class GoogleStatus(
    val available: Boolean = false,
    val linked: Boolean = false,
    val email: String = "",
    @SerialName("has_password") val hasPassword: Boolean = true,
)

@Serializable
data class GoogleLinkIn(val challenge: String)

@Serializable
data class GoogleLinkTicket(val ticket: String)

/** TicketMessageOut. */
@Serializable
data class TicketMessage(
    val id: Int,
    @SerialName("author_id") val authorId: Int,
    @SerialName("author_name") val authorName: String,
    val body: String,
    @SerialName("created_at") val createdAt: String,
)

/** TicketOut: una segnalazione, con la conversazione. */
@Serializable
data class Ticket(
    val id: Int,
    val scope: String = "admin",
    val status: String = "open",
    val subject: String,
    @SerialName("tournament_id") val tournamentId: Int? = null,
    @SerialName("tournament_name") val tournamentName: String? = null,
    @SerialName("opened_by_id") val openedById: Int = 0,
    @SerialName("updated_at") val updatedAt: String = "",
    val messages: List<TicketMessage> = emptyList(),
)

/** TicketCreate: all'organizzatore di un torneo, o a chi tiene il sito. */
@Serializable
data class TicketIn(
    val scope: String,
    @SerialName("tournament_id") val tournamentId: Int? = null,
    val subject: String,
    val body: String,
)

@Serializable
data class TicketMessageIn(val body: String)

@Serializable
data class PublisherIdIn(@SerialName("publisher_id") val publisherId: String)

@Serializable
data class GameHandleIn(@SerialName("game_handle") val gameHandle: String)

/** Le risposte che dicono solo com'è andata. */
@Serializable
data class Detail(val detail: String = "")
