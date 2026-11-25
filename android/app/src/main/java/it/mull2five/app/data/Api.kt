package it.mull2five.app.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Un errore dell'API, col messaggio già pronto da mostrare. `status` 0: niente rete. */
class ApiException(val status: Int, message: String) : Exception(message)

/**
 * L'API del sito, la stessa che usano le pagine (session.js): il token va
 * nell'intestazione Authorization. Un 401 con un token in mano vuol dire
 * sessione scaduta o chiusa altrove: la sessione si svuota e l'app lo vede.
 */
class Api(siteUrl: String, private val session: Session, private val texts: ServerText) {
    private val base = "$siteUrl/api"
    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(40, TimeUnit.SECONDS)
        .build()

    val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        explicitNulls = false
        encodeDefaults = true
    }

    // ── L'account ─────────────────────────────────────────────────────────

    suspend fun rules(): AuthRules = get("/auth/rules")
    suspend fun me(): User = get("/auth/me")
    suspend fun login(email: String, password: String): String =
        post<LoginIn, TokenOut>("/auth/login", LoginIn(email, password)).accessToken
    suspend fun signup(body: SignupIn): String = post<SignupIn, TokenOut>("/auth/register", body).accessToken
    suspend fun forgotPassword(email: String) { send("POST", "/auth/forgot-password", json.encodeToString(EmailIn(email))) }
    suspend fun refresh(): String = decode<TokenOut>(send("POST", "/auth/refresh", null)).accessToken

    suspend fun googleFinish(code: String, verifier: String): GoogleFinish =
        post("/auth/google/app/finish", GoogleCodeIn(code, verifier))
    suspend fun googleSignup(body: GoogleSignupIn): String =
        post<GoogleSignupIn, TokenOut>("/auth/google/app/complete", body).accessToken

    /** Dove la scheda di Chrome comincia il giro con Google (routers/google_auth.py). */
    fun googleStartUrl(app: String, challenge: String): String =
        "$base/auth/google/app/start".toHttpUrl().newBuilder()
            .addQueryParameter("app", app).addQueryParameter("challenge", challenge).build().toString()

    // ── I tornei ──────────────────────────────────────────────────────────

    /**
     * La ricerca degli eventi, come events.js: in calendario fra oggi e `days`
     * giorni, oppure i conclusi degli ultimi `days`; vicino a un punto se c'è.
     */
    suspend fun tournaments(search: EventSearch): List<Tournament> {
        val today = java.time.LocalDate.now()
        val query = buildList {
            if (search.past) {
                add("status" to "completed")
                add("date_from" to today.minusDays(search.days.toLong()).toString())
                add("date_to" to today.toString())
            } else {
                add("status" to "published,running")
                add("days" to search.days.toString())
            }
            if (search.name.isNotBlank()) add("name" to search.name.trim())
            if (search.online != null) add("online" to search.online.toString())
            if (search.formats.isNotEmpty()) add("formats" to search.formats.joinToString(","))
            if (search.eventTypes.isNotEmpty()) add("event_types" to search.eventTypes.joinToString(","))
            if (search.rel.isNotEmpty()) add("rel" to search.rel.joinToString(","))
            search.near?.let { (lat, lng) ->
                add("near_lat" to lat.toString())
                add("near_lng" to lng.toString())
                add("radius_km" to search.radiusKm.toString())
            }
            add("limit" to "300")
        }
        return get("/tournaments", query)
    }

    suspend fun games(): List<Game> = get("/games")

    suspend fun tournament(id: Int): Tournament = get("/tournaments/$id")
    suspend fun fields(id: Int): List<RegistrationField> = get("/tournaments/$id/fields")
    suspend fun paymentOptions(): PaymentOptions = get("/payments/options")
    suspend fun publisherIds(): Map<String, String> = get("/auth/me/publisher-ids")
    suspend fun handles(): Map<String, String> = get("/auth/me/handles")

    /** La propria iscrizione al torneo, o null se non c'è. */
    suspend fun myRegistration(id: Int): Registration? = try {
        get("/tournaments/$id/my-registration")
    } catch (e: ApiException) {
        if (e.status == 404) null else throw e
    }

    suspend fun register(id: Int, body: RegistrationIn): Registration = post("/tournaments/$id/registrations", body)
    suspend fun myRegistrations(): List<MyRegistration> = get("/tournaments/me/registrations")
    suspend fun myPairings(id: Int): List<Round> = get("/tournaments/$id/my-pairings")
    suspend fun standings(id: Int): List<Standing> = get("/tournaments/$id/standings")
    suspend fun selfCheckIn(id: Int): Registration = decode(send("PATCH", "/tournaments/$id/self-check-in", null))
    suspend fun checkout(id: Int, provider: String): Payment = post("/tournaments/$id/checkout", CheckoutIn(provider))
    suspend fun drop(id: Int) { send("POST", "/tournaments/$id/my-registration/drop", null) }
    suspend fun cancel(id: Int) { send("POST", "/tournaments/$id/my-registration/cancel", null) }

    suspend fun reportResult(id: Int, pairingId: Int, body: ResultIn) {
        send("PATCH", "/tournaments/$id/pairings/$pairingId/player-result", json.encodeToString(body))
    }
    suspend fun confirmResult(id: Int, pairingId: Int) {
        send("POST", "/tournaments/$id/pairings/$pairingId/player-result/confirm", null)
    }
    suspend fun rejectResult(id: Int, pairingId: Int, note: String) {
        send("POST", "/tournaments/$id/pairings/$pairingId/player-result/reject", json.encodeToString(RejectIn(note)))
    }

    suspend fun rounds(id: Int): List<Round> = get("/tournaments/$id/rounds")
    suspend fun abandonPayment(id: Int) { send("POST", "/tournaments/$id/my-registration/abandon-payment", null) }
    suspend fun setPublisherId(id: Int, value: String): Registration =
        decode(send("PUT", "/tournaments/$id/my-publisher-id", json.encodeToString(PublisherIdIn(value))))
    suspend fun setGameHandle(id: Int, value: String): Registration =
        decode(send("PUT", "/tournaments/$id/my-handle", json.encodeToString(GameHandleIn(value))))

    /** La lista consegnata per un segmento, o null se non c'è ancora. */
    suspend fun submittedDeck(id: Int, format: String): SubmittedDeck? = try {
        get("/tournaments/$id/decklist", listOf("format" to format))
    } catch (e: ApiException) {
        if (e.status == 404) null else throw e
    }

    suspend fun sendDecklist(id: Int, body: DecklistIn) {
        send("POST", "/tournaments/$id/decklist", json.encodeToString(body))
    }

    // ── Le liste salvate ──────────────────────────────────────────────────

    suspend fun decks(): List<SavedDeck> = get("/decks")
    suspend fun createDeck(body: SavedDeckIn): SavedDeck = post("/decks", body)
    suspend fun updateDeck(id: Int, body: SavedDeckIn): SavedDeck =
        decode(send("PUT", "/decks/$id", json.encodeToString(body)))
    suspend fun deleteDeck(id: Int) { send("DELETE", "/decks/$id", null) }
    suspend fun checkDeck(body: DeckValidateIn): DeckCheck = post("/decks/validate", body)
    suspend fun searchCards(query: String, game: String): List<String> =
        get<CardNames>("/cards/search", listOf("q" to query, "game" to game)).names

    // ── Scoprire: negozi, circuiti, manifestazioni, liste, risultati ──────

    suspend fun stores(near: Pair<Double, Double>?): List<Store> =
        get("/organizations", near?.let { (lat, lng) -> listOf("near_lat" to "$lat", "near_lng" to "$lng") }.orEmpty())
    suspend fun store(slug: String): StorePage = get("/organizations/$slug/profile")
    suspend fun circuits(): List<Circuit> = get("/seasons/public")
    suspend fun circuit(slug: String): CircuitPage = get("/seasons/by-slug/$slug")
    suspend fun manifestation(slug: String): ManifestationPage = get("/events/by-slug/$slug")

    /** L'archivio delle liste (decklists.html): `days` 0 è da sempre, `top` 0 tutte le posizioni. */
    suspend fun archive(filter: ArchiveFilter, page: Int): ArchivePage =
        get("/decklists", buildList {
            if (filter.format.isNotBlank()) add("format" to filter.format)
            if (filter.archetype.isNotBlank()) add("archetype" to filter.archetype.trim())
            if (filter.card.isNotBlank()) add("card" to filter.card.trim())
            add("days" to filter.days.toString())
            add("top" to filter.top.toString())
            add("page" to page.toString())
        })
    suspend fun archiveMeta(format: String, days: Int): ArchiveMeta =
        get("/decklists/meta", buildList {
            if (format.isNotBlank()) add("format" to format)
            add("days" to days.toString())
        })
    suspend fun archiveDeck(id: Int): ArchiveDeck = get("/decklists/$id")

    suspend fun results(id: Int): PublicResults = get("/tournaments/$id/public-results")
    suspend fun meta(id: Int): List<MetaRow> = get("/tournaments/$id/public-meta")
    suspend fun bracket(id: Int): List<BracketMatch> = get("/tournaments/$id/public-bracket")
    suspend fun player(publicId: String): PlayerProfile = get("/tournaments/players/$publicId/public-history")
    suspend fun myHistory(): List<HistoryRow> = get("/tournaments/me/history")

    // ── L'account ─────────────────────────────────────────────────────────

    suspend fun logoutEverywhere(): String = decode<Detail>(send("POST", "/auth/logout-all", null)).detail
    suspend fun exportData(): String = send("GET", "/auth/me/export", null)
    suspend fun deleteAccount(): String = decode<Detail>(send("DELETE", "/auth/me", null)).detail
    suspend fun profiles(): List<ManagedProfile> = get("/auth/me/profiles")
    suspend fun deleteProfile(id: Int) { send("DELETE", "/auth/me/profiles/$id", null) }

    suspend fun googleStatus(): GoogleStatus = get("/auth/google/me")
    suspend fun googleUnlink(): GoogleStatus = decode(send("DELETE", "/auth/google/me", null))
    suspend fun googleLinkTicket(challenge: String): String =
        post<GoogleLinkIn, GoogleLinkTicket>("/auth/google/app/link", GoogleLinkIn(challenge)).ticket
    suspend fun googleLinkFinish(code: String, verifier: String): GoogleStatus =
        post("/auth/google/app/link/finish", GoogleCodeIn(code, verifier))

    /** La scheda che collega Google: come quella dell'accesso, col biglietto. */
    fun googleLinkUrl(app: String, challenge: String, ticket: String): String =
        "$base/auth/google/app/start".toHttpUrl().newBuilder()
            .addQueryParameter("app", app).addQueryParameter("challenge", challenge)
            .addQueryParameter("link", ticket).build().toString()

    // ── Le segnalazioni ───────────────────────────────────────────────────

    suspend fun tickets(): List<Ticket> = get("/tickets/mine")
    suspend fun ticket(id: Int): Ticket = get("/tickets/$id")
    suspend fun openTicket(body: TicketIn): Ticket = post("/tickets", body)
    suspend fun replyTicket(id: Int, body: String): Ticket = post("/tickets/$id/messages", TicketMessageIn(body))
    suspend fun closeTicket(id: Int): Ticket = decode(send("POST", "/tickets/$id/close", null))
    suspend fun reopenTicket(id: Int): Ticket = decode(send("POST", "/tickets/$id/reopen", null))

    // ── La campanella ─────────────────────────────────────────────────────
    // Sempre dell'account, anche agendo per un figlio: il server mette insieme
    // le sue e quelle dei profili che gestisce.

    suspend fun notifications(afterId: Int = 0, offset: Int = 0, limit: Int = 30): NotificationsPage =
        get("/notifications", listOf("after_id" to "$afterId", "offset" to "$offset", "limit" to "$limit"))
    suspend fun unreadNotifications(): UnreadCount = get("/notifications/unread")
    suspend fun markNotificationsRead(ids: List<Int>? = null): UnreadCount =
        post("/notifications/read", NotificationsReadIn(ids))
    suspend fun registerDevice(token: String) {
        send("POST", "/notifications/devices", json.encodeToString(DeviceIn(token)))
    }
    /** Dopo l'uscita: la sessione è già vuota, il token di chi è uscito lo passa chi chiama. */
    suspend fun forgetDevice(token: String, bearer: String) {
        send("POST", "/notifications/devices/forget", json.encodeToString(DeviceIn(token)), bearer = bearer)
    }

    // ── Il trasporto ──────────────────────────────────────────────────────

    private suspend inline fun <reified T> get(path: String, query: List<Pair<String, String>> = emptyList()): T =
        decode(send("GET", path, null, query))

    private suspend inline fun <reified B, reified T> post(path: String, body: B): T =
        decode(send("POST", path, json.encodeToString(body)))

    private inline fun <reified T> decode(text: String): T = json.decodeFromString(text)

    private suspend fun send(
        method: String,
        path: String,
        body: String?,
        query: List<Pair<String, String>> = emptyList(),
        bearer: String? = null,
    ): String = withContext(Dispatchers.IO) {
        val url = "$base$path".toHttpUrl().newBuilder()
            .apply { query.forEach { (key, value) -> addQueryParameter(key, value) } }
            .build()
        val content = when {
            body != null -> body.toRequestBody(JSON_TYPE)
            method == "GET" || method == "DELETE" -> null
            else -> ByteArray(0).toRequestBody(null)
        }
        val token = bearer ?: session.token
        // Per il profilo di un figlio: iscrizioni, pagamenti e liste (acting.js). L'account no.
        val acting = session.acting.value?.takeIf { token != null && ACTING_PATHS.any(path::startsWith) }
        val request = Request.Builder().url(url).method(method, content)
            .header("Accept", "application/json")
            .apply { if (token != null) header("Authorization", "Bearer $token") }
            .apply { if (acting != null) header("X-Act-As", acting.id.toString()) }
            .build()
        val response = try {
            client.newCall(request).execute()
        } catch (e: IOException) {
            throw ApiException(0, texts.offline)
        }
        response.use {
            val text = it.body?.string().orEmpty()
            // Con un token passato da fuori la sessione è un'altra: non è lei a essere scaduta.
            if (it.code == 401 && token != null && bearer == null) session.clear()
            if (!it.isSuccessful) throw ApiException(it.code, errorText(text, it.code))
            text
        }
    }

    /** Il `detail` di FastAPI: una frase, o la lista degli errori di validazione. */
    private fun errorText(body: String, status: Int): String {
        val detail = runCatching { json.parseToJsonElement(body).jsonObject["detail"] }.getOrNull()
        return when (detail) {
            is JsonPrimitive -> detail.contentOrNull?.let(texts::translate)
            is JsonArray -> detail.mapNotNull {
                (it as? JsonObject)?.get("msg")?.jsonPrimitive?.contentOrNull
            }.joinToString(" · ").ifBlank { null }
            else -> null
        } ?: texts.generic(status)
    }

    private companion object {
        val JSON_TYPE = "application/json; charset=utf-8".toMediaType()
        val ACTING_PATHS = listOf("/tournaments", "/decks", "/payments", "/cards")
    }
}

/** I filtri dell'archivio delle liste (decklists.js, readState). */
data class ArchiveFilter(
    val format: String = "",
    val archetype: String = "",
    val card: String = "",
    val days: Int = 90,
    val top: Int = 0,
)

/** I filtri della ricerca degli eventi (events.js, readState). */
data class EventSearch(
    val name: String = "",
    val days: Int = 30,
    val past: Boolean = false,
    val online: Boolean? = null,
    val formats: List<String> = emptyList(),
    val eventTypes: List<String> = emptyList(),
    val rel: List<String> = emptyList(),
    val near: Pair<Double, Double>? = null,
    val radiusKm: Int = 50,
) {
    val filtered: Boolean
        get() = name.isNotBlank() || online != null || formats.isNotEmpty() || eventTypes.isNotEmpty() ||
            rel.isNotEmpty() || near != null
}
