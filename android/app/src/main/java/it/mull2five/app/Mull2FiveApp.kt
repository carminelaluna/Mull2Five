package it.mull2five.app

import android.app.Application
import android.content.Context
import it.mull2five.app.data.Api
import it.mull2five.app.data.ApiException
import it.mull2five.app.data.ServerText
import it.mull2five.app.data.Session
import it.mull2five.app.ui.UiText
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow

class Mull2FiveApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}

/** Quello che serve a tutte le schermate, creato una volta sola. */
class AppContainer(context: Context) {
    /** Il sito dell'ambiente, o l'API di sviluppo se l'app è stata compilata con -Api. */
    val siteUrl: String = BuildConfig.API_OVERRIDE.ifEmpty { BuildConfig.SITE_URL }
    val session = Session(context)
    val texts = ServerText(context)
    val api = Api(siteUrl, session, texts)

    /** Un indirizzo arrivato da fuori, in attesa che l'interfaccia lo prenda. */
    val incoming = MutableStateFlow<Incoming?>(null)

    /** Com'è andato il collegamento con Google chiesto dall'account: lo mostra la schermata dell'account. */
    val googleLink = MutableStateFlow<LinkOutcome?>(null)

    /** Il messaggio da mostrare per un errore: quello del server, o uno generico. */
    fun messageOf(error: Throwable): String = (error as? ApiException)?.message ?: texts.unexpected

    /** Come runCatching, ma lascia passare la cancellazione delle coroutine. */
    suspend fun <T> attempt(block: suspend () -> T): Result<T> = try {
        Result.success(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Result.failure(e)
    }
}

/** L'esito di un giro con Google per collegarlo all'account. */
data class LinkOutcome(val text: UiText, val isError: Boolean)

sealed interface Incoming {
    /** Un link alla pagina di un torneo (event.html?id=…), anche dal QR dell'iscrizione. */
    data class OpenTournament(val id: Int, val register: Boolean) : Incoming

    /** Il ritorno dalla scheda di Google: il `code` da ritirare, o il motivo del rifiuto. */
    data class GoogleReturn(val code: String?, val error: String?) : Incoming
}
