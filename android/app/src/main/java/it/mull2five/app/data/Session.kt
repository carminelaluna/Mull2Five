package it.mull2five.app.data

import android.content.Context
import androidx.core.content.edit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.util.Base64

/**
 * La sessione: il token di accesso (lo stesso JWT del sito, security.py) nelle
 * preferenze private dell'app. Come session.js sul sito: lo si legge senza
 * verificarlo, perché la verifica la fa il server.
 */
class Session(context: Context) {
    private val prefs = context.getSharedPreferences("sessione", Context.MODE_PRIVATE)
    private val _user = MutableStateFlow(SessionUser.from(prefs.getString(KEY_TOKEN, null))?.takeIf { it.isValid() })

    /** Chi è dentro, o null. Le schermate lo osservano: uscire le aggiorna tutte. */
    val user: StateFlow<SessionUser?> = _user.asStateFlow()

    /** Il token, se c'è e non è scaduto. */
    val token: String?
        get() = prefs.getString(KEY_TOKEN, null)?.takeIf { SessionUser.from(it)?.isValid() == true }

    fun save(token: String) {
        prefs.edit { putString(KEY_TOKEN, token) }
        _user.value = SessionUser.from(token)
    }

    fun clear() {
        prefs.edit { remove(KEY_TOKEN) }
        _user.value = null
    }

    /**
     * Il segreto del giro con Google. Sta qui e non in memoria: mentre si sceglie
     * l'account Android può chiudere l'app, e al ritorno serve ancora.
     */
    var googleVerifier: String?
        get() = prefs.getString(KEY_VERIFIER, null)
        set(value) = prefs.edit { if (value == null) remove(KEY_VERIFIER) else putString(KEY_VERIFIER, value) }

    private companion object {
        const val KEY_TOKEN = "token"
        const val KEY_VERIFIER = "google_verifier"
    }
}

/** Il contenuto del token: chi è e quando scade (secondi dal 1970). */
data class SessionUser(
    val id: Int,
    val email: String,
    val role: String,
    val issuedAt: Long,
    val expiresAt: Long,
) {
    fun isValid(now: Long = nowSeconds()): Boolean = expiresAt > now

    /** Il token vale tre giorni: dopo mezza giornata se ne chiede uno nuovo (session.js). */
    fun needsRefresh(now: Long = nowSeconds()): Boolean = isValid(now) && now - issuedAt >= REFRESH_AFTER_SECONDS

    companion object {
        const val REFRESH_AFTER_SECONDS = 12 * 3600L

        fun from(token: String?): SessionUser? = runCatching {
            val payload = token!!.split('.')[1]
            val claims = Json.parseToJsonElement(String(Base64.getUrlDecoder().decode(payload))).jsonObject
            SessionUser(
                id = claims.getValue("sub").jsonPrimitive.content.toInt(),
                email = claims["email"]?.jsonPrimitive?.content.orEmpty(),
                role = claims["role"]?.jsonPrimitive?.content.orEmpty(),
                issuedAt = claims["iat"]?.jsonPrimitive?.long ?: 0,
                expiresAt = claims.getValue("exp").jsonPrimitive.long,
            )
        }.getOrNull()

        private fun nowSeconds() = System.currentTimeMillis() / 1000
    }
}
