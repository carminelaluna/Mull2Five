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

    /** La ricerca degli eventi, come events.js: in calendario fra oggi e `days` giorni. */
    suspend fun tournaments(name: String, days: Int, online: Boolean?): List<Tournament> {
        val query = buildList {
            add("status" to "published,running")
            add("days" to days.toString())
            if (name.isNotBlank()) add("name" to name.trim())
            if (online != null) add("online" to online.toString())
            add("limit" to "300")
        }
        return get("/tournaments", query)
    }

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

    suspend fun decks(): List<SavedDeck> = get("/decks")
    suspend fun sendDecklist(id: Int, body: DecklistIn) {
        send("POST", "/tournaments/$id/decklist", json.encodeToString(body))
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
    ): String = withContext(Dispatchers.IO) {
        val url = "$base$path".toHttpUrl().newBuilder()
            .apply { query.forEach { (key, value) -> addQueryParameter(key, value) } }
            .build()
        val content = when {
            body != null -> body.toRequestBody(JSON_TYPE)
            method == "GET" || method == "DELETE" -> null
            else -> ByteArray(0).toRequestBody(null)
        }
        val token = session.token
        val request = Request.Builder().url(url).method(method, content)
            .header("Accept", "application/json")
            .apply { if (token != null) header("Authorization", "Bearer $token") }
            .build()
        val response = try {
            client.newCall(request).execute()
        } catch (e: IOException) {
            throw ApiException(0, texts.offline)
        }
        response.use {
            val text = it.body?.string().orEmpty()
            if (it.code == 401 && token != null) session.clear()
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
    }
}
