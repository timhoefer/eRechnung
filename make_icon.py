"""Erzeugt assets/icon.icns aus assets/horse.svg (reproduzierbar).

Motiv: galoppierendes Pferd (weiße Silhouette) auf blauem Verlauf im macOS-
Squircle. Quelle ist ein Vektor-SVG (schwarze Pfade); #000000 wird beim Rendern
auf Weiß gesetzt, der Hintergrund bleibt transparent.

Voraussetzung: Pillow + cairosvg (siehe requirements-build.txt; cairosvg braucht
die native libcairo, z. B. `brew install cairo`).
Aufruf:  python make_icon.py   (danach iconutil -> .icns; erledigt build_icon.sh)
"""
from __future__ import annotations

import io
import os

import cairosvg
from PIL import Image, ImageDraw, ImageFilter

S = 1024
TOP, BOT = (63, 125, 244), (36, 87, 191)  # Markenblau (Verlauf)
# macOS-Icon-Raster (Big Sur): farbiger Körper 824x824 zentriert (je 100px Rand).
MARGIN = 100
BODY = S - 2 * MARGIN
RADIUS = round(BODY * 0.2237)
HORSE_WIDTH = 0.78  # Anteil der Körper-Breite
# Optischer Ausgleich: Pferd minimal nach oben/links (Masse liegt rechts/oben).
OFFSET_X = -16
OFFSET_Y = -16


def squircle_bg() -> Image.Image:
    grad = Image.new("RGB", (1, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        f = y / (S - 1)
        gd.point((0, y), fill=tuple(int(TOP[i] + (BOT[i] - TOP[i]) * f) for i in range(3)))
    grad = grad.resize((S, S))
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [MARGIN, MARGIN, S - MARGIN - 1, S - MARGIN - 1], radius=RADIUS, fill=255
    )
    img.paste(grad, (0, 0), mask)
    return img


svg = open("assets/horse.svg", encoding="utf-8").read().replace("#000000", "#ffffff").replace("#000", "#fff")
png = cairosvg.svg2png(bytestring=svg.encode(), output_width=1600)
horse = Image.open(io.BytesIO(png)).convert("RGBA")
horse = horse.crop(horse.getbbox())

img = squircle_bg()
w = int(BODY * HORSE_WIDTH)
h = horse.resize((w, int(w * horse.height / horse.width)), Image.LANCZOS)
hx, hy = (S - h.width) // 2 + OFFSET_X, (S - h.height) // 2 + OFFSET_Y

# Subtiler Schlagschatten hinter dem Pferd (Pferdeform, abgedunkelt, weich, leicht
# nach unten versetzt) -> etwas Tiefe, ohne aufdringlich zu wirken.
sil = h.split()[3].point(lambda a: int(a * 0.30))  # halbtransparente Pferdeform
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
dark = Image.new("RGBA", h.size, (6, 22, 56, 255))
dark.putalpha(sil)
shadow.alpha_composite(dark, (hx, hy + 16))
shadow = shadow.filter(ImageFilter.GaussianBlur(18))
img = Image.alpha_composite(img, shadow)

img.alpha_composite(h, (hx, hy))

os.makedirs("assets", exist_ok=True)
img.save("assets/icon_master.png")
iconset = "assets/eRechnung.iconset"
os.makedirs(iconset, exist_ok=True)
pairs = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]
for name, sz in pairs:
    img.resize((sz, sz), Image.LANCZOS).save(os.path.join(iconset, name))

print("iconset geschrieben:", iconset)
