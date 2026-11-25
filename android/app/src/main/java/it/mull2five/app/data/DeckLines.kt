package it.mull2five.app.data

/**
 * Il testo di una lista come lo legge il sito (frontend/js/deck-view.js):
 * "4 Lightning Bolt", "4x Bolt", "SB: 2 Pyroblast"; la riga "Sideboard" o una
 * riga vuota dopo il main aprono il sideboard. Serve all'editor per aggiungere
 * una carta cercata: il testo torna scritto come lo scrive il sito.
 */
object DeckLines {
    data class Card(val quantity: Int, val name: String)
    data class Deck(val main: List<Card>, val side: List<Card>)

    private val CARD_LINE = Regex("""^(?:(sb)\s*:\s*)?(\d+)\s*x?\s+(.+)$""", RegexOption.IGNORE_CASE)
    private val SIDE_HEADER = Regex("""^(?://\s*)?(sideboard|side|sb|companion|compagno)\b""", RegexOption.IGNORE_CASE)
    private val MAIN_HEADER = Regex(
        """^(?://\s*)?(deck|main|maindeck|mazzo|commander|comandante|creatures?|lands?|terre|instants?|istantanei|""" +
            """sorcery|sorceries|stregonerie|artifacts?|artefatti|enchantments?|incantesimi|planeswalkers?|battles?|""" +
            """battaglie|other|altro)\b""",
        RegexOption.IGNORE_CASE,
    )

    /** Il nome come lo cerca Scryfall: senza foil, set e numero di collezione. */
    fun cleanName(raw: String): String {
        var name = raw.trim()
            .replace(Regex("""\s*\*[A-Za-z]+\*$"""), "")
            .replace(Regex("""\s+\([A-Za-z0-9]{2,6}\)(?:\s+\S+)?$"""), "")
        if ("//" in name) name = name.split("//").joinToString(" // ") { it.trim() }
        return name.replace(Regex("""\s+"""), " ").trim()
    }

    fun parse(raw: String): Deck {
        val main = mutableListOf<Card>()
        val side = mutableListOf<Card>()
        var inSide = false
        for (rawLine in raw.lines()) {
            val line = rawLine.trim()
            if (line.isEmpty()) {
                // Una riga vuota dopo il main: il resto è sideboard (MTGO e Arena).
                if (!inSide && main.isNotEmpty()) inSide = true
                continue
            }
            val card = CARD_LINE.matchEntire(line)
            if (card != null) {
                val name = cleanName(card.groupValues[3])
                val quantity = card.groupValues[2].toIntOrNull() ?: 0
                if (name.isNotEmpty() && quantity > 0) {
                    (if (card.groupValues[1].isNotEmpty() || inSide) side else main).add(Card(quantity, name))
                }
                continue
            }
            if (SIDE_HEADER.containsMatchIn(line)) inSide = true
            else if (MAIN_HEADER.containsMatchIn(line)) inSide = false
        }
        return Deck(main, side)
    }

    /** Le righe con lo stesso nome diventano una sola, con le copie sommate. */
    fun merge(cards: List<Card>): List<Card> {
        val byName = LinkedHashMap<String, Card>()
        for (card in cards) {
            val key = card.name.lowercase()
            val seen = byName[key]
            byName[key] = if (seen == null) card else seen.copy(quantity = seen.quantity + card.quantity)
        }
        return byName.values.toList()
    }

    fun toText(deck: Deck): String {
        val lines = deck.main.map { "${it.quantity} ${it.name}" }
        val side = deck.side.map { "${it.quantity} ${it.name}" }
        return (lines + if (side.isNotEmpty()) listOf("", "Sideboard") + side else emptyList()).joinToString("\n")
    }

    /** Una copia in più di `name`, nel main o nel sideboard. */
    fun add(raw: String, name: String, side: Boolean): String {
        val deck = parse(raw)
        return toText(
            if (side) deck.copy(main = merge(deck.main), side = merge(deck.side + Card(1, name)))
            else deck.copy(main = merge(deck.main + Card(1, name)), side = merge(deck.side))
        )
    }
}
