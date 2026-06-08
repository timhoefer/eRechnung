"""Erzeugt assets/icon.icns aus assets/horse.svg (reproduzierbar).

Motiv: laufendes Pferd (weiße Silhouette) auf blauem Verlauf im macOS-Squircle.
Die Pferd-Vektorgrafik liegt als assets/horse.svg vor (fill=currentColor wird
beim Rendern auf Weiß gesetzt).

Voraussetzungen: Pillow + cairosvg (siehe requirements-build.txt; cairosvg
benötigt die native libcairo, z. B. via Homebrew `brew install cairo`).

Aufruf:  python make_icon.py   (danach iconutil -> .icns; erledigt build_icon.sh)
"""
from __future__ import annotations

import io
import os

import cairosvg
from PIL import Image, ImageDraw

S = 1024
TOP, BOT = (63, 125, 244), (36, 87, 191)  # Markenblau (Verlauf)
# macOS-Icon-Raster (Big Sur): farbiger Körper 824x824 zentriert in 1024 (je 100px
# Rand), Eckradius ~185. So sitzt das Icon wie native Apps – nicht randlos.
MARGIN = 100
BODY = S - 2 * MARGIN          # 824
RADIUS = round(BODY * 0.2237)  # ~184
HORSE_WIDTH = 0.60             # Anteil der KÖRPER-Breite (nicht der Leinwand)


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


svg = open("assets/horse.svg", encoding="utf-8").read().replace("currentColor", "#ffffff")
png = cairosvg.svg2png(bytestring=svg.encode(), output_width=1600)
horse = Image.open(io.BytesIO(png)).convert("RGBA")
horse = horse.crop(horse.getbbox())

img = squircle_bg()
w = int(BODY * HORSE_WIDTH)
h = horse.resize((w, int(w * horse.height / horse.width)), Image.LANCZOS)
img.alpha_composite(h, ((S - h.width) // 2, (S - h.height) // 2))

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
