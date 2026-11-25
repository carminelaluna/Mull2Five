package it.mull2five.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight

/** I colori del sito (frontend/styles.css, :root): scuro, con il lime come accento. */
object Brand {
    val Bg = Color(0xFF0D0D0F)
    val Panel = Color(0xFF16161A)
    val Panel2 = Color(0xFF1F1F25)
    val Ink = Color(0xFFFFFFFF)
    val Muted = Color(0xFF9A9AA5)
    val Soft = Color(0xFF6A6A75)
    val Line = Color(0xFF2A2A31)
    val Accent = Color(0xFFC6FF3D)
    val AccentDim = Color(0xFF2A3312)
    val Teal = Color(0xFF35C7BF)
    val Green = Color(0xFF7BD66F)
    val Warn = Color(0xFFE8A13C)
    val Danger = Color(0xFFEF6A5E)
}

private val colors = darkColorScheme(
    primary = Brand.Accent,
    onPrimary = Brand.Bg,
    primaryContainer = Brand.AccentDim,
    onPrimaryContainer = Brand.Accent,
    secondary = Brand.Teal,
    onSecondary = Brand.Bg,
    secondaryContainer = Brand.AccentDim,
    onSecondaryContainer = Brand.Accent,
    tertiary = Brand.Teal,
    background = Brand.Bg,
    onBackground = Brand.Ink,
    surface = Brand.Bg,
    onSurface = Brand.Ink,
    surfaceVariant = Brand.Panel2,
    onSurfaceVariant = Brand.Muted,
    surfaceContainerLowest = Brand.Bg,
    surfaceContainerLow = Brand.Panel,
    surfaceContainer = Brand.Panel,
    surfaceContainerHigh = Brand.Panel2,
    surfaceContainerHighest = Brand.Panel2,
    outline = Brand.Soft,
    outlineVariant = Brand.Line,
    error = Brand.Danger,
    onError = Brand.Bg,
)

private val base = Typography()
private val typography = base.copy(
    headlineSmall = base.headlineSmall.copy(fontWeight = FontWeight.Bold),
    titleLarge = base.titleLarge.copy(fontWeight = FontWeight.Bold),
    titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold),
)

@Composable
fun Mull2FiveTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = colors, typography = typography, content = content)
}
