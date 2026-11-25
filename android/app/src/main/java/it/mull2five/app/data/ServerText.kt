package it.mull2five.app.data

import android.content.Context
import it.mull2five.app.R
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

/**
 * I messaggi del server sono in italiano ("Iscrizioni chiuse", "Torneo pieno"…).
 * Il sito li traduce con frontend/locales/<lingua>.json, dove la chiave è la
 * frase italiana: l'app usa gli stessi file, che Gradle copia negli asset.
 */
class ServerText(private val context: Context) {
    private val table: Map<String, String> by lazy(::load)

    fun translate(text: String): String = table[text] ?: text

    val offline: String get() = context.getString(R.string.error_offline)

    val unexpected: String get() = context.getString(R.string.error_unexpected)

    fun generic(status: Int): String = context.getString(R.string.error_generic, status)

    private fun load(): Map<String, String> {
        val language = context.resources.configuration.locales[0].language
        if (language == "it") return emptyMap()
        return runCatching {
            val text = context.assets.open("locales/$language.json").bufferedReader().use { it.readText() }
            Json.parseToJsonElement(text).jsonObject
                .mapNotNull { (key, value) -> (value as? JsonPrimitive)?.takeIf { it.isString }?.let { key to it.content } }
                .toMap()
        }.getOrDefault(emptyMap())
    }
}
