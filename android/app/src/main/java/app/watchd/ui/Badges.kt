package app.watchd.ui

// The disc label images the site shows for format, region and age rating
// (frontend/public/badges, listed in frontend/src/lib/badges.json): sharp
// vector drawings, bundled as assets so they show offline.

/** One label: its file in assets/badges, and its width over its height. */
class Badge(val file: String, val shape: Float) {
    val url get() = "file:///android_asset/badges/$file"
}

val FORMAT_BADGES = mapOf(
    "4K UHD" to Badge("format-4kuhd.svg", 1.531f),
    "Blu-ray" to Badge("format-bluray.svg", 1.531f),
    "Blu-ray 3D" to Badge("format-bluray3d.svg", 1.531f),
    "DVD" to Badge("format-dvd.svg", 1.531f),
    "HD DVD" to Badge("format-hddvd.svg", 1.531f),
)

val REGION_BADGES = mapOf(
    "Region A" to Badge("region-regiona.svg", 0.900f),
    "Region B" to Badge("region-regionb.svg", 0.900f),
    "Region C" to Badge("region-regionc.svg", 0.900f),
    "Region Free" to Badge("region-regionfree.svg", 1.100f),
)

/** Keyed by the rating with only letters and digits, upper case: "MPAAPG-13" -> "MPAAPG13". */
val RATING_BADGES = mapOf(
    "AOFLCG" to Badge("rating-aoflcg.svg", 1.429f),
    "AOFLCM" to Badge("rating-aoflcm.svg", 1.429f),
    "AOFLCMA15" to Badge("rating-aoflcma15.svg", 1.429f),
    "AOFLCPG" to Badge("rating-aoflcpg.svg", 1.429f),
    "AOFLCR18" to Badge("rating-aoflcr18.svg", 1.429f),
    "BBFC12" to Badge("rating-bbfc12.svg", 1.000f),
    "BBFC12A" to Badge("rating-bbfc12a.svg", 1.000f),
    "BBFC15" to Badge("rating-bbfc15.svg", 1.000f),
    "BBFC18" to Badge("rating-bbfc18.svg", 1.000f),
    "BBFCPG" to Badge("rating-bbfcpg.svg", 1.146f),
    "BBFCU" to Badge("rating-bbfcu.svg", 1.146f),
    "CMPRS14" to Badge("rating-cmprs14.svg", 1.146f),
    "CMPRS18" to Badge("rating-cmprs18.svg", 1.146f),
    "CMPRSPG" to Badge("rating-cmprspg.svg", 1.000f),
    "CMPRSR" to Badge("rating-cmprsr.svg", 1.000f),
    "FSK18" to Badge("rating-fsk18.svg", 1.000f),
    "IFRST" to Badge("rating-ifrst.svg", 1.000f),
    "MPAAG" to Badge("rating-mpaag.svg", 1.310f),
    "MPAANC17" to Badge("rating-mpaanc17.svg", 2.857f),
    "MPAANR" to Badge("rating-mpaanr.svg", 1.429f),
    "MPAAPG" to Badge("rating-mpaapg.svg", 1.429f),
    "MPAAPG13" to Badge("rating-mpaapg13.svg", 2.857f),
    "MPAAR" to Badge("rating-mpaar.svg", 1.310f),
    "MPAATV14" to Badge("rating-mpaatv14.svg", 1.000f),
    "MPAATVMA" to Badge("rating-mpaatvma.svg", 1.000f),
    "MPAATVPG" to Badge("rating-mpaatvpg.svg", 1.000f),
    "MPAAUR" to Badge("rating-mpaaur.svg", 1.429f),
)

fun ratingBadge(code: String): Badge? = RATING_BADGES[code.filter(Char::isLetterOrDigit).uppercase()]
