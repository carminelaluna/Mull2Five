package it.mull2five.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64
import java.util.Locale

class PkceTest {
    @Test
    fun `la sfida e quella dell'esempio della RFC 7636`() {
        assertEquals(
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            Pkce.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
        )
    }

    @Test
    fun `il segreto ha la lunghezza e i caratteri che il server accetta`() {
        val verifier = Pkce.newVerifier()
        assertEquals(64, verifier.length)
        assertTrue(verifier.matches(Regex("^[A-Za-z0-9_-]+$")))
        // La sfida è quella che /app/start controlla: 43 caratteri base64url.
        assertTrue(Pkce.challenge(verifier).matches(Regex("^[A-Za-z0-9_-]{43}$")))
    }
}

class SessionUserTest {
    private fun token(claims: String): String {
        val encode = { text: String -> Base64.getUrlEncoder().withoutPadding().encodeToString(text.toByteArray()) }
        return "${encode("""{"alg":"HS256","typ":"JWT"}""")}.${encode(claims)}.firma"
    }

    @Test
    fun `legge il token come lo scrive security py`() {
        val user = SessionUser.from(token("""{"sub":"42","email":"a@b.it","role":"player","pid":"x","tv":0,"iat":1000,"exp":2000}"""))
        assertEquals(SessionUser(42, "a@b.it", "player", 1000, 2000), user)
        assertTrue(user!!.isValid(now = 1999))
        assertFalse(user.isValid(now = 2000))
    }

    @Test
    fun `chiede un token nuovo dopo mezza giornata`() {
        val user = SessionUser(1, "", "", issuedAt = 0, expiresAt = 3 * 86400)
        assertFalse(user.needsRefresh(now = 12 * 3600 - 1))
        assertTrue(user.needsRefresh(now = 12 * 3600))
        assertFalse(user.needsRefresh(now = 3 * 86400))
    }

    @Test
    fun `un token rotto non e una sessione`() {
        assertNull(SessionUser.from(null))
        assertNull(SessionUser.from("niente"))
        assertNull(SessionUser.from(token("""{"email":"senza@sub.it"}""")))
    }
}

class FormatsTest {
    @Test
    fun `i centesimi solo se ci sono`() {
        assertEquals("10 €", Formats.money(1000, "EUR", Locale.ITALY).replace(' ', ' '))
        assertEquals("10,50 €", Formats.money(1050, "EUR", Locale.ITALY).replace(' ', ' '))
    }

    @Test
    fun `una data rotta resta com'e`() {
        assertEquals("domani", Formats.date("domani"))
        assertEquals("5", Formats.day("2026-12-05"))
    }
}

class ScoresTest {
    @Test
    fun `al meglio di tre senza patte intenzionali sparisce lo zero a zero`() {
        val scores = Scores.forMatch(bestOf = 3, playoff = false, intentionalDraws = false)
        assertFalse(0 to 0 in scores)
        assertTrue(1 to 1 in scores)
        assertTrue(2 to 1 in scores)
    }

    @Test
    fun `nei playoff una partita va vinta`() {
        val scores = Scores.forMatch(bestOf = 1, playoff = true, intentionalDraws = true)
        assertTrue(scores.none { it.first == it.second })
        assertTrue(2 to 1 in scores)
    }

    @Test
    fun `il risultato visto dall'altro lato del tavolo`() {
        assertEquals("1-2", Scores.invert("2-1"))
        assertEquals("ID", Scores.invert("ID"))
    }
}

class DeckLinesTest {
    @Test
    fun `legge main e sideboard come il sito`() {
        val deck = DeckLines.parse("4 Lightning Bolt\n4x Counterspell\n\n2 Pyroblast\nSB: 1 Negate")
        assertEquals(listOf(DeckLines.Card(4, "Lightning Bolt"), DeckLines.Card(4, "Counterspell")), deck.main)
        assertEquals(listOf(DeckLines.Card(2, "Pyroblast"), DeckLines.Card(1, "Negate")), deck.side)
    }

    @Test
    fun `l'esportazione di Arena con compagno e intestazioni`() {
        val deck = DeckLines.parse("Companion\n1 Lurrus of the Dream-Den\n\nDeck\n4 Ragavan (MH2) 138\n\nSideboard\n2 Duress")
        assertEquals(listOf(DeckLines.Card(4, "Ragavan")), deck.main)
        assertEquals(listOf(DeckLines.Card(1, "Lurrus of the Dream-Den"), DeckLines.Card(2, "Duress")), deck.side)
    }

    @Test
    fun `il nome si pulisce da set, numero e foil`() {
        assertEquals("Fire // Ice", DeckLines.cleanName("Fire//Ice (MH2) 290 *F*"))
        assertEquals("Sol Ring", DeckLines.cleanName("  Sol   Ring  "))
    }

    @Test
    fun `aggiungere una carta somma le copie e tiene il sideboard`() {
        val raw = "3 Lightning Bolt\n\nSideboard\n1 Negate"
        assertEquals("4 Lightning Bolt\n\nSideboard\n1 Negate", DeckLines.add(raw, "lightning bolt", side = false))
        assertEquals("3 Lightning Bolt\n\nSideboard\n2 Negate", DeckLines.add(raw, "Negate", side = true))
        assertEquals("1 Island", DeckLines.add("", "Island", side = false))
    }

    @Test
    fun `il testo riscritto si rilegge uguale`() {
        val deck = DeckLines.Deck(listOf(DeckLines.Card(4, "Bolt")), listOf(DeckLines.Card(2, "Duress")))
        assertEquals(deck, DeckLines.parse(DeckLines.toText(deck)))
    }
}
