package app.watchd.ui

import android.provider.Settings
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.HolidayTheme
import app.watchd.ui.theme.Watchd
import kotlin.math.floor
import kotlin.math.sin

// A holiday's decorations, as on the site (HolidayFx.astro): a few shapes
// drifting over every page, faint, never in the way of a tap, and still when
// the phone's animations are turned off.

private enum class Motion { Fall, Rise, Twinkle, Drift }

private val KINDS = mapOf(
    "snow" to (listOf("❄", "❅", "❆") to Motion.Fall),
    "hearts" to (listOf("♥", "❤") to Motion.Rise),
    "shamrocks" to (listOf("☘") to Motion.Fall),
    "confetti" to (listOf("▬", "●", "◆", "▲") to Motion.Fall),
    "sparkles" to (listOf("✦", "✧", "★") to Motion.Twinkle),
    "stars" to (listOf("✦", "·", "✧") to Motion.Twinkle),
    "eggs" to (listOf("⬮") to Motion.Drift),
    "petals" to (listOf("✿", "❀") to Motion.Fall),
    "flames" to (listOf("🔥") to Motion.Rise),
    "bats" to (listOf("🦇") to Motion.Drift),
    "leaves" to (listOf("🍂", "🍁") to Motion.Fall),
)

@Composable
fun HolidayFx(theme: HolidayTheme?) {
    val (glyphs, motion) = theme?.let { KINDS[it.decoration] } ?: return
    val context = LocalContext.current
    val still = remember {
        Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
    // Spread out, the same every time.
    fun r(i: Int, n: Int): Float { val x = sin(i * 12.9898 + n * 78.233) * 43758.5453; return (x - floor(x)).toFloat() }
    val time = rememberInfiniteTransition(label = "holiday")
    val t by time.animateFloat(0f, 1f, infiniteRepeatable(tween(20_000, easing = LinearEasing), RepeatMode.Restart), label = "t")
    val pulse by time.animateFloat(0f, 1f, infiniteRepeatable(tween(4_000), RepeatMode.Reverse), label = "pulse")

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val w = maxWidth.value
        val h = maxHeight.value
        repeat(14) { i ->
            val speed = 0.6f + r(i, 5) * 0.8f
            val phase = ((if (still) 0f else t) * speed + r(i, 4)) % 1f
            val x = r(i, 1) * w
            val (dx, dy, alpha) = when (motion) {
                Motion.Fall -> Triple(phase * 40f, -40f + phase * (h + 80f), 0.35f)
                Motion.Rise -> Triple(-phase * 30f, h + 40f - phase * (h + 80f), 0.35f * (1 - phase))
                Motion.Twinkle -> Triple(0f, r(i, 2) * h, if (still) 0.3f else 0.08f + 0.42f * ((pulse + r(i, 3)) % 1f))
                Motion.Drift -> Triple(sin(phase * 6.283f) * 30f, r(i, 2) * h + sin(phase * 6.283f) * 20f, 0.35f)
            }
            if (still && motion != Motion.Twinkle && motion != Motion.Drift) return@repeat
            val colour = when {
                theme.decoration == "snow" -> if (i % 3 == 0) Color(0xFFDBEAFE) else Color.White
                i % 3 == 2 -> Watchd.Second
                else -> Watchd.Red
            }
            Text(
                glyphs[i % glyphs.size], color = colour, fontSize = (10 + r(i, 3) * 14).sp,
                modifier = Modifier.offset((x + dx).dp, dy.dp).alpha(alpha).graphicsLayer { rotationZ = if (motion == Motion.Fall) phase * 300f else 0f },
            )
        }
    }
}
