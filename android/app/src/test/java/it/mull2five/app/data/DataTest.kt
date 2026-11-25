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
