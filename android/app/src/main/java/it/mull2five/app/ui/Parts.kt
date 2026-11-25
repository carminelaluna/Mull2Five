package it.mull2five.app.ui

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import it.mull2five.app.AppContainer
import it.mull2five.app.R
import it.mull2five.app.ui.theme.Brand
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream
import java.io.InputStream

/** Una schermata dentro una scheda: il titolo e la freccia per tornare. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SubScreen(
    title: String,
    onBack: () -> Unit,
    actions: @Composable RowScope.() -> Unit = {},
    floating: @Composable () -> Unit = {},
    content: @Composable (PaddingValues) -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back)) }
                },
                actions = actions,
            )
        },
        floatingActionButton = floating,
        content = content,
    )
}

/** Una pagina che chiede una cosa sola all'API: la tiene finché la schermata vive. */
class LoadViewModel<T>(private val c: AppContainer, private val block: suspend (AppContainer) -> T) : ViewModel() {
    var state by mutableStateOf<Load<T>>(Load.Loading)
        private set
    private var job: Job? = null

    init {
        load()
    }

    /** Una richiesta alla volta: aprire la schermata e tornarci non la manda due volte. */
    fun load() {
        if (job?.isActive == true) return
        job = viewModelScope.launch {
            if (state !is Load.Ready) state = Load.Loading
            c.attempt { block(c) }
                .onSuccess { state = Load.Ready(it) }
                .onFailure { if (state !is Load.Ready) state = Load.Failed(c.messageOf(it)) }
        }
    }
}

@Composable
fun <T> rememberLoad(key: String, block: suspend (AppContainer) -> T): LoadViewModel<T> =
    appViewModel(key) { LoadViewModel(it, block) }

/** Attesa, errore con "Riprova", o il contenuto. */
@Composable
fun <T> Loaded(state: Load<T>, onRetry: () -> Unit, modifier: Modifier = Modifier, content: @Composable (T) -> Unit) {
    when (state) {
        Load.Loading -> LoadingBox(modifier)
        is Load.Failed -> ErrorBox(state.message, onRetry, modifier)
        is Load.Ready -> content(state.value)
    }
}

/** Una voce che porta a un'altra schermata. */
@Composable
fun NavRow(title: String, modifier: Modifier = Modifier, icon: ImageVector? = null, detail: String? = null, onClick: () -> Unit) {
    Row(
        modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = Brand.Accent)
            Spacer(Modifier.width(16.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            if (!detail.isNullOrBlank()) {
                Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Un filtro con il menu: la scelta si vede sul chip. Le opzioni sono (valore, etichetta). */
@Composable
fun ChoiceChip(
    label: String,
    options: List<Pair<String, String>>,
    selected: String,
    onSelect: (String) -> Unit,
    allLabel: String? = null,
) {
    var open by remember { mutableStateOf(false) }
    Box {
        val current = options.firstOrNull { it.first == selected }?.second
        FilterChip(
            selected = selected.isNotEmpty() && allLabel != null,
            onClick = { open = true },
            label = { Text(current ?: label) },
            trailingIcon = { Icon(Icons.Filled.ArrowDropDown, contentDescription = null, modifier = Modifier.size(18.dp)) },
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            if (allLabel != null) {
                DropdownMenuItem(text = { Text(allLabel) }, onClick = { open = false; onSelect("") })
            }
            options.forEach { (value, text) ->
                DropdownMenuItem(
                    text = { Text(text) },
                    leadingIcon = { if (value == selected) Icon(Icons.Filled.Check, contentDescription = null) },
                    onClick = { open = false; onSelect(value) },
                )
            }
        }
    }
}

/** Più scelte nello stesso menu (i formati della ricerca): il menu resta aperto. Opzioni (valore, etichetta). */
@Composable
fun MultiChoiceChip(
    label: String,
    options: List<Pair<String, String>>,
    selected: List<String>,
    onToggle: (String) -> Unit,
    onClear: () -> Unit,
) {
    var open by remember { mutableStateOf(false) }
    Box {
        val text = when (selected.size) {
            0 -> label
            1 -> options.firstOrNull { it.first == selected.first() }?.second ?: selected.first()
            else -> "$label · ${selected.size}"
        }
        FilterChip(
            selected = selected.isNotEmpty(),
            onClick = { open = true },
            label = { Text(text) },
            trailingIcon = { Icon(Icons.Filled.ArrowDropDown, contentDescription = null, modifier = Modifier.size(18.dp)) },
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            if (selected.isNotEmpty()) {
                DropdownMenuItem(text = { Text(stringResource(R.string.filter_clear)) }, onClick = { onClear(); open = false })
            }
            options.forEach { (value, name) ->
                DropdownMenuItem(
                    text = { Text(name) },
                    leadingIcon = { if (value in selected) Icon(Icons.Filled.Check, contentDescription = null) },
                    onClick = { onToggle(value) },
                )
            }
        }
    }
}

/**
 * Una lista di carte come la scrive il giocatore: le righe "Sideboard" e quelle
 * vuote fanno da titoli. Testo a spaziatura fissa, perché i numeri si allineino.
 */
@Composable
fun DeckText(raw: String, modifier: Modifier = Modifier) {
    Panel(modifier, color = Brand.Panel2) {
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            raw.lines().map { it.trimEnd() }.dropWhile { it.isBlank() }.forEach { line ->
                val heading = line.isNotBlank() && !line.first().isDigit()
                when {
                    line.isBlank() -> Spacer(Modifier.size(8.dp))
                    heading -> Text(
                        line,
                        style = MaterialTheme.typography.labelLarge,
                        color = Brand.Accent,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                    else -> Text(line, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

/** Un numero grande con l'etichetta sotto, per i totali (profilo, circuito). */
@Composable
fun Stat(value: String, label: String, modifier: Modifier = Modifier) {
    Surface(modifier, color = Brand.Panel, shape = MaterialTheme.shapes.large) {
        Column(Modifier.padding(vertical = 12.dp, horizontal = 8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
        }
    }
}

/** Un messaggio dopo un'azione: verde se è andata, rosso se no. */
@Composable
fun Notice(text: UiText?, isError: Boolean, modifier: Modifier = Modifier) {
    text ?: return
    Text(
        text.asString(),
        color = if (isError) MaterialTheme.colorScheme.error else Brand.Green,
        modifier = modifier.padding(vertical = 8.dp),
    )
}

@Composable
fun ShareButton(url: String) {
    val context = LocalContext.current
    IconButton(onClick = { context.share(url) }) { Icon(Icons.Filled.Share, stringResource(R.string.event_share)) }
}

/** Un indirizzo nell'app delle mappe: le coordinate se ci sono, se no il testo. */
fun Context.openPlace(label: String, address: String, latitude: Double?, longitude: Double?) {
    val query = if (latitude != null && longitude != null) "$latitude,$longitude(${label.ifBlank { address }})" else address
    if (query.isNotBlank()) openExternal("geo:0,0?q=" + Uri.encode(query))
}

/** Un file di testo scelto dal telefono: una lista esportata da Arena, MTGO o un sito di liste. */
@Composable
fun rememberTextFilePicker(onText: (String) -> Unit): () -> Unit {
    val context = LocalContext.current
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            runCatching { context.contentResolver.openInputStream(uri)?.use { it.readUpTo(64 * 1024) } }
                .getOrNull()
                ?.let { onText(it.decodeToString()) }
        }
    }
    return { launcher.launch(arrayOf("text/*", "application/octet-stream")) }
}

private fun InputStream.readUpTo(limit: Int): ByteArray {
    val out = ByteArrayOutputStream()
    val buffer = ByteArray(8192)
    while (out.size() < limit) {
        val read = read(buffer, 0, minOf(buffer.size, limit - out.size()))
        if (read < 0) break
        out.write(buffer, 0, read)
    }
    return out.toByteArray()
}

/** Un sito scritto senza "https://" dall'organizzatore. */
fun webUrl(text: String): String = if (text.startsWith("http://") || text.startsWith("https://")) text else "https://$text"

/** Il banner del profilo gestito (acting.js): chi si sta gestendo, e il ritorno a sé. */
@Composable
fun ActingBanner(name: String, onStop: () -> Unit, modifier: Modifier = Modifier) {
    Surface(modifier.fillMaxWidth(), color = Brand.AccentDim) {
        Row(Modifier.padding(start = 16.dp, end = 8.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(
                stringResource(R.string.acting_banner, name),
                color = Brand.Accent,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onStop) { Text(stringResource(R.string.acting_stop)) }
        }
    }
}
