package it.mull2five.app.data

import java.text.NumberFormat
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Currency
import java.util.Locale

/** Date e cifre nella lingua del telefono. */
object Formats {
    /** 1000 → "10 €", 1050 → "10,50 €": i centesimi solo se ci sono. */
    fun money(cents: Int, currency: String, locale: Locale = Locale.getDefault()): String {
        val format = NumberFormat.getCurrencyInstance(locale)
        runCatching { format.currency = Currency.getInstance(currency) }
        val digits = if (cents % 100 == 0) 0 else 2
        format.minimumFractionDigits = digits
        format.maximumFractionDigits = digits
        return format.format(cents / 100.0)
    }

    /** "2026-12-05" → "sab 5 dic 2026". */
    fun date(iso: String, locale: Locale = Locale.getDefault()): String =
        parse(iso)?.format(DateTimeFormatter.ofPattern("EEE d MMM yyyy", locale)) ?: iso

    /** Il giorno del mese, per il riquadro della data negli elenchi. */
    fun day(iso: String): String = parse(iso)?.dayOfMonth?.toString() ?: ""

    fun month(iso: String, locale: Locale = Locale.getDefault()): String =
        parse(iso)?.format(DateTimeFormatter.ofPattern("MMM", locale))?.trimEnd('.')?.uppercase(locale) ?: ""

    /** Un istante del server (ISO 8601) come ora locale, "18:30". */
    fun time(isoDateTime: String, zone: ZoneId = ZoneId.systemDefault()): String =
        runCatching {
            OffsetDateTime.parse(isoDateTime).atZoneSameInstant(zone).format(DateTimeFormatter.ofPattern("HH:mm"))
        }.getOrDefault("")

    private fun parse(iso: String): LocalDate? = runCatching { LocalDate.parse(iso.take(10)) }.getOrNull()
}

/**
 * I punteggi possibili di un match, dal punto di vista di chi lo scrive
 * (frontend/js/games.js, `scoresFor`; il server controlla con ALLOWED_SCORES).
 */
object Scores {
    private val byBestOf = mapOf(
        1 to listOf(1 to 0, 0 to 1, 0 to 0),
        2 to listOf(2 to 0, 1 to 0, 1 to 1, 0 to 1, 0 to 2, 0 to 0),
        3 to listOf(2 to 0, 2 to 1, 1 to 0, 1 to 1, 0 to 1, 1 to 2, 0 to 2, 0 to 0),
    )

    fun forMatch(bestOf: Int, playoff: Boolean, intentionalDraws: Boolean): List<Pair<Int, Int>> {
        // Nei playoff sempre al meglio di 3, e una partita va vinta.
        var scores = if (playoff) byBestOf.getValue(3).filter { it.first != it.second }
        else byBestOf[bestOf] ?: byBestOf.getValue(3)
        // Senza patte intenzionali sparisce lo 0-0; la patta a tempo (1-1) resta.
        if (!intentionalDraws) scores = scores.filter { it != (0 to 0) }
        return scores
    }

    /** "2-1" visto dall'altro lato del tavolo: "1-2". */
    fun invert(score: String): String {
        val parts = score.split('-')
        return if (parts.size == 2) "${parts[1]}-${parts[0]}" else score
    }
}
