package it.mull2five.app.data

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

/**
 * PKCE (RFC 7636) per l'accesso con Google: l'app tiene un segreto, al server
 * manda solo il suo hash. Il `code` che torna nell'indirizzo si ritira solo col
 * segreto, quindi un'altra app che lo intercettasse non ne farebbe niente.
 */
object Pkce {
    /** 64 caratteri base64url da 48 byte casuali: dentro i 43–128 della norma. */
    fun newVerifier(random: SecureRandom = SecureRandom()): String =
        ByteArray(48).also(random::nextBytes).let(::base64Url)

    fun challenge(verifier: String): String =
        base64Url(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray(Charsets.US_ASCII)))

    private fun base64Url(bytes: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
}
