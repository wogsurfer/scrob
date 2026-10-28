package app.watchd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.watchd.data.DiscLookup
import app.watchd.data.LookupResult
import app.watchd.data.SignedOut
import app.watchd.ui.theme.Watchd
import coil3.compose.AsyncImage
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import kotlinx.coroutines.launch

/**
 * Adding a disc: scan its barcode (or type it, or a title), pick the film or
 * series it's of, choose the format and whether it's owned or wished for.
 * The rest (edition, covers, specs) is filled in from TMDB or on the site.
 */
@Composable
fun AddDiscScreen(onBack: () -> Unit, openDisc: (Int) -> Unit) {
    val app = LocalApp.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var input by rememberSaveable { mutableStateOf("") }
    var barcode by rememberSaveable { mutableStateOf<String?>(null) }
    var lookup by remember { mutableStateOf<DiscLookup?>(null) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var picked by remember { mutableStateOf<LookupResult?>(null) }
    var formats by remember { mutableStateOf(listOf("Blu-ray", "4K UHD", "Blu-ray 3D", "DVD")) }

    LaunchedEffect(Unit) {
        runCatching { app.api.discOptions()["format"] }.getOrNull()?.takeIf { it.isNotEmpty() }?.let { formats = it }
    }

    fun find(code: String?, query: String?) {
        busy = true; message = null; lookup = null; picked = null
        barcode = code
        scope.launch {
            try {
                val found = app.api.lookupDisc(code, query)
                lookup = found
                message = when {
                    found.results.isEmpty() && code != null && found.product?.title == null ->
                        "That barcode isn't in the free barcode database. Search by title instead."
                    found.results.isEmpty() -> "No matches on TMDB."
                    else -> null
                }
            } catch (e: SignedOut) {
                app.signOut()
            } catch (e: Exception) {
                message = "The lookup didn't work. Try the title instead."
            }
            busy = false
        }
    }

    // Google's scanner: its own camera screen, no camera permission needed here.
    fun scan() {
        val options = GmsBarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_EAN_13, Barcode.FORMAT_UPC_A, Barcode.FORMAT_EAN_8, Barcode.FORMAT_UPC_E)
            .enableAutoZoom()
            .build()
        GmsBarcodeScanning.getClient(context, options).startScan()
            .addOnSuccessListener { code -> code.rawValue?.filter(Char::isDigit)?.takeIf { it.isNotEmpty() }?.let { input = it; find(it, null) } }
            .addOnFailureListener { message = "The scanner couldn't start: ${it.message}" }
    }

    // Straight to the camera when the screen opens.
    LaunchedEffect(Unit) { if (lookup == null && input.isEmpty()) scan() }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 32.dp)) {
        item {
            Row(Modifier.statusBarsPadding().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back") }
                SectionTitle("Add a disc")
            }
        }
        item {
            Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(
                    onClick = ::scan, modifier = Modifier.fillMaxWidth().height(52.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Watchd.Red, contentColor = Color.White),
                ) {
                    Icon(Icons.Default.QrCodeScanner, contentDescription = null)
                    Text("Scan a barcode", fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 10.dp))
                }
                val submit = {
                    val text = input.trim()
                    val digits = text.filter(Char::isDigit)
                    if (text.isNotEmpty()) {
                        if (digits.length >= 8 && digits.length == text.replace(" ", "").length) find(digits, null) else find(null, text)
                    }
                }
                OutlinedTextField(
                    input, { input = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("Or type a barcode or title") },
                    trailingIcon = { IconButton(onClick = submit) { Icon(Icons.Default.Search, contentDescription = "Look up") } },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text, imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(onSearch = { submit() }),
                )
            }
        }
        if (busy) {
            item { CircularProgressIndicator(color = Watchd.Red, modifier = Modifier.padding(24.dp)) }
        }
        message?.let { item { Text(it, color = Watchd.Muted, modifier = Modifier.padding(16.dp)) } }
        lookup?.product?.let { product ->
            product.already?.let { owned ->
                item {
                    Text(
                        "You already have this barcode: ${owned.title.orEmpty()}${if (owned.status == "wishlist") " (wish list)" else ""}. Tap to open it.",
                        color = Color(0xFFFBBF24), fontWeight = FontWeight.Bold, fontSize = 14.sp,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp).fillMaxWidth()
                            .clip(RoundedCornerShape(10.dp)).background(Color(0x22F59E0B)).clickable { openDisc(owned.id) }.padding(12.dp),
                    )
                }
            }
            product.title?.let { title ->
                item {
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        product.images.firstOrNull { it.startsWith("https://") }?.let {
                            AsyncImage(it, contentDescription = null, modifier = Modifier.size(56.dp).clip(RoundedCornerShape(6.dp)).background(Color.White))
                        }
                        Column(Modifier.padding(start = 12.dp)) {
                            Text(title, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            product.brand?.let { Text(it, color = Watchd.Muted, fontSize = 13.sp) }
                        }
                    }
                }
            }
        }
        val results = lookup?.results.orEmpty()
        if (results.isNotEmpty() && picked == null) {
            item { Text("Which film or series is it?", fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 16.dp, top = 12.dp, bottom = 4.dp)) }
            items(results, key = { "${it.kind}-${it.tmdbId}" }) { r ->
                Row(
                    Modifier.fillMaxWidth().clickable { picked = r }.padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Poster(r.poster, Modifier.width(46.dp))
                    Column(Modifier.padding(start = 12.dp).weight(1f)) {
                        Text(r.title.orEmpty(), fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(listOfNotNull(r.year, if (r.kind == "tv") "TV series" else "Film").joinToString(" · "), color = Watchd.Muted, fontSize = 13.sp)
                    }
                }
            }
        }
        picked?.let { pick ->
            item {
                AddDetails(
                    pick, formats,
                    guessedFormat = formatFrom(lookup?.product?.title),
                    onChange = { picked = null },
                ) { format, wishlist ->
                    val cover = lookup?.product?.images?.firstOrNull { it.startsWith("https://") } ?: pick.poster?.replace("/w185/", "/w500/")
                    app.act(
                        "${pick.title} added to your ${if (wishlist) "wish list" else "collection"}",
                        action = { openDisc(addDisc(pick, barcode, format, wishlist, cover)) },
                        onFail = {},
                    )
                }
            }
        }
    }
}

/** The format the product's name gives away ("… [4K Ultra HD]"), if any. */
private fun formatFrom(title: String?): String? = when {
    title == null -> null
    Regex("4k|uhd", RegexOption.IGNORE_CASE).containsMatchIn(title) -> "4K UHD"
    Regex("3d", RegexOption.IGNORE_CASE).containsMatchIn(title) -> "Blu-ray 3D"
    Regex("blu-?ray", RegexOption.IGNORE_CASE).containsMatchIn(title) -> "Blu-ray"
    Regex("dvd", RegexOption.IGNORE_CASE).containsMatchIn(title) -> "DVD"
    else -> null
}

@Composable
private fun AddDetails(
    pick: LookupResult, formats: List<String>, guessedFormat: String?,
    onChange: () -> Unit, onAdd: (format: String?, wishlist: Boolean) -> Unit,
) {
    var format by remember(pick) { mutableStateOf(guessedFormat ?: formats.firstOrNull()) }
    var wishlist by remember(pick) { mutableStateOf(false) }
    var adding by remember(pick) { mutableStateOf(false) }
    val chipColors = FilterChipDefaults.filterChipColors(
        selectedContainerColor = Watchd.Red, selectedLabelColor = Color.White,
        containerColor = Watchd.Surface, labelColor = Watchd.Muted,
    )
    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Poster(pick.poster, Modifier.width(70.dp))
            Column(Modifier.padding(start = 14.dp).weight(1f)) {
                Text(pick.title.orEmpty(), fontSize = 18.sp, fontWeight = FontWeight.Black)
                Text(listOfNotNull(pick.year, if (pick.kind == "tv") "TV series" else "Film").joinToString(" · "), color = Watchd.Muted)
                Text("Not this one?", color = Watchd.Red, fontWeight = FontWeight.Bold, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp).clickable(onClick = onChange))
            }
        }
        Text("FORMAT", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = Watchd.Faint, letterSpacing = 1.sp)
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(formats) { f -> FilterChip(format == f, { format = f }, label = { Text(f) }, colors = chipColors, border = null) }
        }
        Text("WHERE", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = Watchd.Faint, letterSpacing = 1.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(!wishlist, { wishlist = false }, label = { Text("My collection") }, colors = chipColors, border = null)
            FilterChip(wishlist, { wishlist = true }, label = { Text("Wish list") }, colors = chipColors, border = null)
        }
        Spacer(Modifier.height(4.dp))
        Button(
            onClick = { adding = true; onAdd(format, wishlist) }, enabled = !adding,
            modifier = Modifier.fillMaxWidth().height(52.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Watchd.Red, contentColor = Color.White),
        ) { Text(if (adding) "Adding…" else "Add to ${if (wishlist) "wish list" else "collection"}", fontWeight = FontWeight.Bold) }
        Text("Edition, covers and the rest can be filled in on the disc's page on the site.", color = Watchd.Faint, fontSize = 12.sp)
    }
}
