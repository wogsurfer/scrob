package app.watchd.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// The site's palette: near-black, zinc greys and the Watchd red.
object Watchd {
    val Red = Color(0xFFE50914)
    val Background = Color(0xFF09090B)
    val Surface = Color(0xFF18181B)
    val SurfaceHigh = Color(0xFF27272A)
    val Text = Color(0xFFFAFAFA)
    val Muted = Color(0xFFA1A1AA)
    val Faint = Color(0xFF71717A)
    val ImdbYellow = Color(0xFFF5C518)
}

private val colors = darkColorScheme(
    primary = Watchd.Red,
    onPrimary = Color.White,
    secondary = Watchd.Muted,
    background = Watchd.Background,
    onBackground = Watchd.Text,
    surface = Watchd.Background,
    onSurface = Watchd.Text,
    surfaceVariant = Watchd.Surface,
    onSurfaceVariant = Watchd.Muted,
    surfaceContainer = Watchd.Surface,
    surfaceContainerHigh = Watchd.SurfaceHigh,
    outline = Watchd.SurfaceHigh,
    error = Color(0xFFF87171),
)

private val type = Typography(
    headlineLarge = TextStyle(fontWeight = FontWeight.Black, fontSize = 30.sp, lineHeight = 34.sp),
    headlineSmall = TextStyle(fontWeight = FontWeight.Black, fontSize = 22.sp, lineHeight = 26.sp),
    titleMedium = TextStyle(fontWeight = FontWeight.Bold, fontSize = 16.sp, lineHeight = 20.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    labelSmall = TextStyle(fontWeight = FontWeight.Bold, fontSize = 11.sp, letterSpacing = 1.2.sp),
)

@Composable
fun WatchdTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = colors, typography = type) {
        // Gives every screen the page colour and light text by default.
        Surface(color = Watchd.Background, contentColor = Watchd.Text, content = content)
    }
}
