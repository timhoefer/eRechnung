"""Erzeugt assets/icon.icns für die macOS-App (reproduzierbar).

Motiv: blauer Verlauf (Markenfarbe), weißes Rechnungsdokument mit Textzeilen
und einem Häkchen-Badge – steht für die validierte E-Rechnung. Nutzt Pillow
(ist über WeasyPrint ohnehin vorhanden).

Aufruf:  python make_icon.py   (danach iconutil -> .icns; erledigt build_icon.sh)
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter

S = 1024
ACCENT = (47, 111, 235, 255)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# Hintergrund: vertikaler Verlauf, in abgerundete Maske (macOS-Squircle ~22 %)
top, bot = (63, 125, 244), (36, 87, 191)
grad = Image.new("RGB", (1, S))
gd = ImageDraw.Draw(grad)
for y in range(S):
    f = y / (S - 1)
    gd.point((0, y), fill=tuple(int(top[i] + (bot[i] - top[i]) * f) for i in range(3)))
grad = grad.resize((S, S))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=230, fill=255)
img.paste(grad, (0, 0), mask)

# Dokument-Geometrie
pw, ph = 540, 680
px, py = (S - pw) // 2, (S - ph) // 2 + 6

# weicher Schlagschatten unter dem Dokument
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle(
    [px, py + 20, px + pw, py + ph + 20], radius=40, fill=(0, 0, 0, 95)
)
img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(26)))

d = ImageDraw.Draw(img)
# weißes Dokument
d.rounded_rectangle([px, py, px + pw, py + ph], radius=40, fill=(255, 255, 255, 255))

m = 64
# Kopfzeile (Akzentbalken)
d.rounded_rectangle([px + m, py + 74, px + pw - m, py + 74 + 46], radius=20, fill=ACCENT)
# Textzeilen (grau)
grey = (208, 213, 221, 255)
ly = py + 206
for w in (1.0, 0.84, 0.92, 0.6):
    d.rounded_rectangle(
        [px + m, ly, px + m + int((pw - 2 * m) * w), ly + 26], radius=13, fill=grey
    )
    ly += 64

# Häkchen-Badge unten rechts (validierte Rechnung)
r = 94
cx, cy = px + pw - m - r // 2, py + ph - m - r // 2
d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ACCENT)
d.line(
    [(cx - 40, cy - 2), (cx - 10, cy + 32), (cx + 44, cy - 36)],
    fill=(255, 255, 255, 255), width=24, joint="curve",
)

os.makedirs("assets", exist_ok=True)
iconset = "assets/eRechnung.iconset"
os.makedirs(iconset, exist_ok=True)
img.save("assets/icon_master.png")

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
