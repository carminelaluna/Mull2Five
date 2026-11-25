package it.mull2five.app.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.annotation.StringRes
import androidx.browser.customtabs.CustomTabColorSchemeParams
import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewmodel.compose.viewModel
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.ui.theme.Brand

val LocalContainer = staticCompositionLocalOf<AppContainer> { error("AppContainer mancante") }

/** Un ViewModel che riceve il contenitore: legato alla schermata in cui nasce. */
@Composable
inline fun <reified VM : ViewModel> appViewModel(key: String? = null, crossinline create: (AppContainer) -> VM): VM {
    val container = LocalContainer.current
    return viewModel(key = key) { create(container) }
}

/** Quello che una schermata sta caricando. */
sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Ready<T>(val value: T) : Load<T>
    data class Failed(val message: String) : Load<Nothing>
}

/** Un testo da mostrare: dal server (già tradotto) o dalle risorse dell'app. */
sealed interface UiText {
    data class Raw(val text: String) : UiText
    data class Res(@StringRes val id: Int) : UiText
}

@Composable
fun UiText.asString(): String = when (this) {
    is UiText.Raw -> text
    is UiText.Res -> stringResource(id)
}

@Composable
fun LoadingBox(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}

@Composable
fun MessageBox(
    text: String,
    modifier: Modifier = Modifier,
    action: String? = null,
    onAction: () -> Unit = {},
) {
    Column(
        modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        if (action != null) {
            Spacer(Modifier.size(16.dp))
            Button(onClick = onAction) { Text(action) }
        }
    }
}

@Composable
fun ErrorBox(message: String, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    MessageBox(message, modifier, action = stringResource(R.string.retry), onAction = onRetry)
}

enum class Tone { Neutral, Accent, Ok, Warn, Danger }

/** Le etichette colorate del sito (`.badge`, `.badge.ok`, `.badge.warn`). */
@Composable
fun Badge(text: String, tone: Tone = Tone.Neutral) {
    val (background, foreground) = when (tone) {
        Tone.Neutral -> Brand.Panel2 to Brand.Muted
        Tone.Accent -> Brand.AccentDim to Brand.Accent
        Tone.Ok -> Brand.Green.copy(alpha = 0.16f) to Brand.Green
        Tone.Warn -> Brand.Warn.copy(alpha = 0.16f) to Brand.Warn
        Tone.Danger -> Brand.Danger.copy(alpha = 0.16f) to Brand.Danger
    }
    Surface(color = background, contentColor = foreground, shape = RoundedCornerShape(50)) {
        Text(
            text,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        modifier = modifier.padding(top = 20.dp, bottom = 8.dp),
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

/** Una riga con l'icona a sinistra: data, luogo, quota. */
@Composable
fun InfoRow(icon: ImageVector, text: String, modifier: Modifier = Modifier, detail: String? = null) {
    Row(modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.Top) {
        Icon(icon, contentDescription = null, tint = Brand.Accent, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(12.dp))
        Column {
            Text(text, style = MaterialTheme.typography.bodyLarge)
            if (!detail.isNullOrBlank()) {
                Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** Un riquadro come i `.panel` del sito. */
@Composable
fun Panel(modifier: Modifier = Modifier, color: Color = Brand.Panel, content: @Composable () -> Unit) {
    Surface(modifier.fillMaxWidth(), color = color, shape = RoundedCornerShape(16.dp)) {
        Box(Modifier.padding(16.dp)) { content() }
    }
}

/**
 * Una pagina del sito, Google o il pagamento in una scheda di Chrome dentro
 * l'app: chi la chiude torna dove era.
 */
fun Context.openInTab(url: String) {
    val colors = CustomTabColorSchemeParams.Builder().setToolbarColor(0xFF0D0D0F.toInt()).build()
    val tab = CustomTabsIntent.Builder().setDefaultColorSchemeParams(colors).setShowTitle(true).build()
    try {
        tab.launchUrl(this, Uri.parse(url))
    } catch (e: ActivityNotFoundException) {
        openExternal(url)
    }
}

fun Context.openExternal(url: String) {
    try {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: ActivityNotFoundException) {
        // Nessuna app per aprirlo: non c'è altro da fare.
    }
}

fun Context.share(text: String) {
    val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
    startActivity(Intent.createChooser(send, null))
}

@Composable
fun rememberOpenInTab(): (String) -> Unit {
    val context = LocalContext.current
    return { url -> context.openInTab(url) }
}
