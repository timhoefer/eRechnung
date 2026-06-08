"""Erzeugt assets/icon.icns aus assets/horse_source.png (reproduzierbar).

Motiv: galoppierendes Pferd (weiße Silhouette, blaue Mähnen-Linie) auf blauem
Verlauf im macOS-Squircle. Quelle ist eine schwarze Silhouette auf Weiß; die
Helligkeit wird invertiert -> dunkel = Pferd (weiß gefärbt), weiß = transparent
(die helle Mähnen-Linie bleibt als blaue Aussparung erhalten).

Voraussetzung: Pillow.
Aufruf:  python make_icon.py   (danach iconutil -> .icns; erledigt build_icon.sh)
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageOps

S = 1024
TOP, BOT = (63, 125, 244), (36, 87, 191)  # Markenblau (Verlauf)
# macOS-Icon-Raster (Big Sur): farbiger Körper 824x824 zentriert (je 100px Rand).
MARGIN = 100
BODY = S - 2 * MARGIN
RADIUS = round(BODY * 0.2237)
HORSE_WIDTH = 0.66  # Anteil der Körper-Breite


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


src = Image.open("assets/horse_source.png").convert("L")
alpha = ImageOps.invert(src)  # dunkel -> deckend, weiß -> transparent
white = Image.new("RGBA", src.size, (255, 255, 255, 255))
white.putalpha(alpha)
horse = white.crop(alpha.getbbox())

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
