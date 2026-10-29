# Usage, from the repo root:  python frontend/scripts/make_badges.py frontend/public
# Then copy frontend/public/badges/*.svg to android/app/src/main/assets/badges/.
"""Sharp vector versions of the Collectorz label images (format, region,
age rating), drawn to match the originals. Writes <name>.svg next to them."""
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])  # frontend/public
OUT = ROOT / "badges"
SANS = "Arial, Helvetica, sans-serif"
SERIF = "'Times New Roman', Times, serif"


def svg(w, h, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{body}</svg>\n'


def text(x, y, s, size, fill="#000", weight="900", family=SANS, anchor="middle", extra=""):
    s = s.replace("&", "&amp;")
    return f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" {extra}>{s}</text>'


def tile(w, h, body, r=10, fill="#fff"):
    return svg(w, h, f'<rect width="{w}" height="{h}" rx="{r}" fill="{fill}"/>' + body)


def logo(name):
    """The inner drawing and viewBox of one of the site's logo SVGs."""
    raw = (ROOT / "logos" / name).read_text(encoding="utf-8")
    vb = re.search(r'viewBox="([^"]+)"', raw).group(1)
    inner = raw[raw.index(">", raw.index("<svg")) + 1: raw.rindex("</svg>")]
    inner = re.sub(r"<(metadata|defs)[\s\S]*?</\1>", "", inner)
    return vb, inner


def nested(vb, inner, x, y, w, h):
    return f'<svg x="{x}" y="{y}" width="{w}" height="{h}" viewBox="{vb}" preserveAspectRatio="xMidYMid meet">{inner}</svg>'


badges = {}

# ---- formats: white tiles, as Collectorz shows them
badges["format-4kuhd"] = tile(150, 98, '<rect x="14" y="16" width="122" height="66" rx="14" fill="#000"/>' + text(75, 69, "4K", 54, "#fff"))
vb, inner = logo("bluray.svg")
# Just the disc symbol, without the "Blu-ray Disc" lettering under it.
vb = "66 103 282 128"
badges["format-bluray"] = tile(150, 98, nested(vb, inner, 8, 18, 134, 61))
badges["format-bluray3d"] = tile(150, 98, nested(vb, inner, 23, 6, 104, 47) + text(75, 91, "3D", 42, "#0095D5", extra='font-style="italic"'))
vb, inner = logo("dvd.svg")
badges["format-dvd"] = tile(150, 98, nested(vb, inner, 12, 6, 126, 86))
badges["format-hddvd"] = tile(150, 98, text(75, 46, "HD", 40, "#7a0b14", extra='font-style="italic"') + text(75, 86, "DVD", 40, "#7a0b14", extra='font-style="italic"'))

# ---- regions: a hexagon with the letter in a ring; Region Free shows all three
def hexagon(cx, cy, r, letter, stroke=7):
    pts = " ".join(f"{cx + r * __import__('math').cos(a):.1f},{cy + r * __import__('math').sin(a):.1f}"
                   for a in [__import__("math").radians(30 + 60 * i) for i in range(6)])
    ring = r * 0.62
    return (f'<polygon points="{pts}" fill="#fff" stroke="#000" stroke-width="{stroke}" stroke-linejoin="round"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{ring:.1f}" fill="#fff" stroke="#000" stroke-width="{stroke * 0.8:.1f}"/>'
            + text(cx, cy + ring * 0.42, letter, ring * 1.2))

for letter in "ABC":
    badges[f"region-region{letter.lower()}"] = svg(90, 100, '<rect width="90" height="100" rx="8" fill="#fff"/>' + hexagon(45, 50, 40, letter))
badges["region-regionfree"] = svg(110, 100, '<rect width="110" height="100" rx="8" fill="#fff"/>'
                                  + hexagon(55, 27, 24, "A", 4.5) + hexagon(31, 70, 24, "B", 4.5) + hexagon(79, 70, 24, "C", 4.5))

# ---- US (MPAA): white tile, black frame, bold letters; NR and UR in sans
def mpaa(label, serif=True):
    w = max(110, 40 + len(label) * 40)
    return tile(w, 84, f'<rect x="5" y="5" width="{w - 10}" height="74" rx="4" fill="#fff" stroke="#000" stroke-width="7"/>'
                + text(w / 2, 65, label, 60, family=SERIF if serif else SANS, weight="900" if serif else "500",
                       # A thin outline thickens Times to the originals' heavy letters.
                       extra='stroke="#000" stroke-width="2.5"' if serif else ""), r=6)

badges["rating-mpaag"] = mpaa("G")
badges["rating-mpaapg"] = mpaa("PG")
badges["rating-mpaapg13"] = mpaa("PG-13")
badges["rating-mpaar"] = mpaa("R")
badges["rating-mpaanc17"] = mpaa("NC-17")
badges["rating-mpaanr"] = mpaa("NR", serif=False)
badges["rating-mpaaur"] = mpaa("UR", serif=False)

# ---- US TV: black square, "TV" above the rating
def tv(label):
    size = 56 if len(label) <= 2 else 44
    return tile(96, 96, text(48, 34, "TV", 30, "#fff", extra='letter-spacing="4"') + text(48, 84, label, size, "#fff"), r=8, fill="#000")

badges["rating-mpaatv14"] = tv("14")
badges["rating-mpaatvma"] = tv("MA")
badges["rating-mpaatvpg"] = tv("PG")

# ---- UK (BBFC): circles for 12, 12A, 15, 18; triangles for U and PG
def bbfc_circle(label, colour):
    size = 44 if len(label) <= 2 else 34
    return svg(96, 96, '<rect width="96" height="96" rx="10" fill="#fff"/>'
               f'<circle cx="48" cy="48" r="42" fill="{colour}"/><circle cx="48" cy="48" r="35" fill="none" stroke="#fff" stroke-width="3"/>'
               + text(48, 48 + size * 0.36, label, size, "#fff"))

def triangle(label, colour, fg="#fff", up=True, w=110, h=96):
    pts = f"55,6 104,90 6,90" if up else f"6,8 104,8 55,92"
    y = 76 if up else 50
    size = 30 if len(label) > 2 else 34
    return svg(w, h, f'<rect width="{w}" height="{h}" rx="10" fill="#fff"/>'
               f'<polygon points="{pts}" fill="{colour}" stroke="{colour}" stroke-width="6" stroke-linejoin="round"/>'
               + text(55, y, label, size, fg))

badges["rating-bbfc12"] = bbfc_circle("12", "#F28C1A")
badges["rating-bbfc12a"] = bbfc_circle("12A", "#F28C1A")
badges["rating-bbfc15"] = bbfc_circle("15", "#E2147A")
badges["rating-bbfc18"] = bbfc_circle("18", "#E3001B")
badges["rating-bbfcu"] = triangle("U", "#0E9F6E")
badges["rating-bbfcpg"] = triangle("PG", "#F6C400", fg="#000")

# ---- Australia (classification board): coloured tiles
def aus(label, colour, fg="#fff", note=None):
    body = text(60, 54 if note else 58, label, 40 if len(label) <= 2 else 30 if len(label) <= 5 else 25, fg)
    if note:
        body += f'<rect x="10" y="64" width="100" height="16" rx="3" fill="#fff"/>' + text(60, 77, note, 13, "#000")
    return tile(120, 84, body, r=10, fill=colour)

badges["rating-aoflcg"] = aus("G", "#00A651")
badges["rating-aoflcpg"] = aus("PG", "#FFDD00", fg="#000")
badges["rating-aoflcm"] = aus("M", "#00AEEF")
badges["rating-aoflcma15"] = aus("MA 15+", "#E2231A", note="RESTRICTED")
badges["rating-aoflcr18"] = aus("R 18+", "#111", note="RESTRICTED")

# ---- Canada (home video): 14A and 18A triangles, PG square, R octagon
badges["rating-cmprs14"] = triangle("14A", "#FFE600", fg="#000", up=False)
badges["rating-cmprs18"] = triangle("18A", "#F7941D", up=False)
badges["rating-cmprspg"] = tile(96, 96, '<rect x="6" y="6" width="84" height="84" rx="14" fill="#1F4FA3"/>' + text(48, 64, "PG", 42, "#fff"))
oct_pts = " ".join(f"{48 + 42 * __import__('math').cos(__import__('math').radians(22.5 + 45 * i)):.1f},{48 + 42 * __import__('math').sin(__import__('math').radians(22.5 + 45 * i)):.1f}" for i in range(8))
badges["rating-cmprsr"] = tile(96, 96, f'<polygon points="{oct_pts}" fill="#E31B23"/>' + text(48, 64, "R", 46, "#fff"))

# ---- Germany (FSK) and Ireland (IFCO)
badges["rating-fsk18"] = tile(96, 96, '<rect x="6" y="6" width="84" height="84" rx="10" fill="#E3001B"/>' + text(48, 30, "FSK", 16, "#fff") + text(48, 78, "18", 48, "#fff"))
badges["rating-ifrst"] = svg(96, 96, '<rect width="96" height="96" rx="10" fill="#fff"/><circle cx="48" cy="48" r="42" fill="#fff" stroke="#000" stroke-width="4"/>'
                             + text(48, 30, "IFCO", 13, "#000") + text(48, 78, "T", 48, "#000"))

for name, body in badges.items():
    (OUT / f"{name}.svg").write_text(body, encoding="utf-8")
print(len(badges), "badges written")
