package it.mull2five.app.ui.login

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.BuildConfig
import it.mull2five.app.Incoming
import it.mull2five.app.LinkOutcome
import it.mull2five.app.R
import it.mull2five.app.data.AuthRules
import it.mull2five.app.data.GoogleSignupIn
import it.mull2five.app.data.Pkce
import it.mull2five.app.data.SignupIn
import it.mull2five.app.ui.UiText
import it.mull2five.app.ui.openInTab
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

sealed interface AuthEvent {
    data object SignedIn : AuthEvent
    data object NeedsGoogleSignup : AuthEvent
}

/** Chi entra con Google per la prima volta: l'email l'ha detta Google, il resto lo sceglie lui. */
data class GoogleSignup(val email: String, val name: String, val code: String)

/**
 * L'accesso, per tutta l'app: vive finché vive l'attività, perché il ritorno da
 * Google arriva dall'esterno, a qualunque schermata ci si trovi.
 */
class AuthViewModel(private val c: AppContainer) : ViewModel() {
    var rules by mutableStateOf(AuthRules())
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<UiText?>(null)
        private set
    var notice by mutableStateOf<UiText?>(null)
        private set
    var googleSignup by mutableStateOf<GoogleSignup?>(null)
        private set

    private val _events = Channel<AuthEvent>(Channel.BUFFERED)
    val events = _events.receiveAsFlow()

    init {
        viewModelScope.launch { c.attempt { c.api.rules() }.onSuccess { rules = it } }
    }

    fun clearMessages() {
        error = null
        notice = null
    }

    fun login(email: String, password: String) = launchBusy {
        c.session.save(c.api.login(email.trim(), password))
        _events.send(AuthEvent.SignedIn)
    }

    fun signup(name: String, email: String, password: String, ageConfirmed: Boolean, termsAccepted: Boolean) = launchBusy {
        c.session.save(c.api.signup(SignupIn(email.trim(), name.trim(), password, ageConfirmed, termsAccepted)))
        _events.send(AuthEvent.SignedIn)
    }

    fun forgotPassword(email: String) {
        if (email.isBlank()) {
            error = UiText.Res(R.string.login_forgot_needs_email)
            return
        }
        launchBusy {
            c.api.forgotPassword(email.trim())
            notice = UiText.Res(R.string.login_forgot_sent)
        }
    }

    /** La scheda di Chrome va da Google; il segreto resta all'app (Pkce). */
    fun startGoogle(context: Context) {
        clearMessages()
        val verifier = Pkce.newVerifier()
        c.session.googleVerifier = verifier
        // Un collegamento lasciato a metà non deve trasformare questo accesso in un collegamento.
        c.session.googleLinking = false
        context.openInTab(c.api.googleStartUrl(BuildConfig.APPLICATION_ID, Pkce.challenge(verifier)))
    }

    fun finishGoogle(back: Incoming.GoogleReturn) {
        if (c.session.googleLinking) {
            finishLink(back)
            return
        }
        clearMessages()
        val verifier = c.session.googleVerifier
        if (back.code == null || verifier == null) {
            error = UiText.Res(googleErrorText(back.error))
            return
        }
        launchBusy {
            val out = c.api.googleFinish(back.code, verifier)
            val token = out.accessToken
            if (token != null) {
                c.session.googleVerifier = null
                c.session.save(token)
                _events.send(AuthEvent.SignedIn)
            } else {
                googleSignup = GoogleSignup(out.signupEmail.orEmpty(), out.signupName.orEmpty(), back.code)
                _events.send(AuthEvent.NeedsGoogleSignup)
            }
        }
    }

    /**
     * Il ritorno da Google partito dall'account ("Collega Google"): si ritira il
     * `code` con il segreto e il token di chi è dentro, e Google si collega.
     */
    private fun finishLink(back: Incoming.GoogleReturn) {
        c.session.googleLinking = false
        val verifier = c.session.googleVerifier
        c.session.googleVerifier = null
        if (back.code == null || verifier == null) {
            c.googleLink.value = LinkOutcome(UiText.Res(googleErrorText(back.error)), isError = true)
            return
        }
        viewModelScope.launch {
            c.attempt { c.api.googleLinkFinish(back.code, verifier) }
                .onSuccess { c.googleLink.value = LinkOutcome(UiText.Res(R.string.account_google_linked_now), isError = false) }
                .onFailure { c.googleLink.value = LinkOutcome(UiText.Raw(c.messageOf(it)), isError = true) }
        }
    }

    fun completeGoogleSignup(name: String, ageConfirmed: Boolean, termsAccepted: Boolean) {
        val pending = googleSignup ?: return
        val verifier = c.session.googleVerifier ?: return
        launchBusy {
            c.session.save(
                c.api.googleSignup(GoogleSignupIn(pending.code, verifier, name.trim(), ageConfirmed, termsAccepted))
            )
            c.session.googleVerifier = null
            googleSignup = null
            _events.send(AuthEvent.SignedIn)
        }
    }

    private fun launchBusy(block: suspend () -> Unit) {
        if (busy) return
        clearMessages()
        busy = true
        viewModelScope.launch {
            c.attempt { block() }.onFailure { error = UiText.Raw(c.messageOf(it)) }
            busy = false
        }
    }

    /** I codici che il server mette nell'indirizzo di ritorno (session.js, googleErrorText). */
    private fun googleErrorText(code: String?): Int = when (code) {
        "annullato" -> R.string.google_error_cancelled
        "stato" -> R.string.google_error_expired
        "rifiutato" -> R.string.google_error_refused
        "non_verificata" -> R.string.google_error_unverified
        "disattivato" -> R.string.google_error_disabled
        "gia_collegato" -> R.string.google_error_linked_elsewhere
        "altro_google" -> R.string.google_error_other_google
        "non_disponibile" -> R.string.google_error_unavailable
        else -> R.string.google_error_generic
    }
}
