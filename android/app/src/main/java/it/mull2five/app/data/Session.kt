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
        actAs(null)
    }

    private val _acting = MutableStateFlow(
        prefs.getInt(KEY_ACTING_ID, 0).takeIf { it > 0 }?.let { ActingProfile(it, prefs.getString(KEY_ACTING_NAME, "").orEmpty()) }
    )

    /**
     * Il profilo di un figlio per cui si sta agendo (acting.js sul sito): iscrizioni,
     * pagamenti e liste vanno a nome suo, l'account resta quello del genitore.
     */
    val acting: StateFlow<ActingProfile?> = _acting.asStateFlow()

    fun actAs(profile: ActingProfile?) {
        prefs.edit {
            if (profile == null) remove(KEY_ACTING_ID).remove(KEY_ACTING_NAME)
            else putInt(KEY_ACTING_ID, profile.id).putString(KEY_ACTING_NAME, profile.name)
        }
        _acting.value = profile
    }

    /**
     * Il segreto del giro con Google. Sta qui e non in memoria: mentre si sceglie
     * l'account Android può chiudere l'app, e al ritorno serve ancora.
     */
    var googleVerifier: String?
        get() = prefs.getString(KEY_VERIFIER, null)
        set(value) = prefs.edit { if (value == null) remove(KEY_VERIFIER) else putString(KEY_VERIFIER, value) }

    /** Il giro con Google in corso collega Google all'account invece di entrare. */
    var googleLinking: Boolean
        get() = prefs.getBoolean(KEY_LINKING, false)
        set(value) = prefs.edit { putBoolean(KEY_LINKING, value) }

    private companion object {
        const val KEY_TOKEN = "token"
        const val KEY_VERIFIER = "google_verifier"
        const val KEY_LINKING = "google_linking"
        const val KEY_ACTING_ID = "acting_id"
        const val KEY_ACTING_NAME = "acting_name"
    }
}

/** Il profilo gestito per cui si agisce: l'id va nell'intestazione X-Act-As. */
data class ActingProfile(val id: Int, val name: String)

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
