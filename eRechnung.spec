# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Spec für die macOS-Doppelklick-App (Option D).
# Bauen mit:  .venv/bin/pyinstaller eRechnung.spec --noconfirm
# Ergebnis:   dist/eRechnung.app
#
# Der klassische Start (run.sh / start.command) bleibt davon unberührt.
import glob
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("schematron", "schematron"),
]
binaries = []
hiddenimports = ["cffi"]

# Pakete mit eigenen Daten/Native-Libs vollständig einsammeln.
for pkg in ("weasyprint", "saxonche", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# drafthorse bringt die Factur-X-/EN16931-XSD mit (für die XML-Validierung).
datas += collect_data_files("drafthorse")

# Nativer Pango-Stack (Homebrew). PyInstaller löst die transitiven
# Abhängigkeiten dieser dylibs automatisch mit auf.
_HB = os.environ.get("HOMEBREW_LIB", "/opt/homebrew/lib")
_NATIVE = [
    "libglib-2.0.0.dylib", "libgobject-2.0.0.dylib", "libgio-2.0.0.dylib",
    "libgmodule-2.0.0.dylib", "libfreetype.6.dylib", "libfontconfig.1.dylib",
    "libharfbuzz.0.dylib", "libharfbuzz-subset.0.dylib",
    "libpango-1.0.0.dylib", "libpangoft2-1.0.0.dylib", "libpangocairo-1.0.0.dylib",
    "libfribidi.0.dylib", "libintl.8.dylib", "libpcre2-8.0.dylib",
    "libpng16.16.dylib", "libgraphite2.3.dylib", "libexpat.1.dylib",
]
for leaf in _NATIVE:
    for f in glob.glob(os.path.join(_HB, leaf)):
        binaries.append((f, "."))

block_cipher = None

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="eRechnung", debug=False, strip=False, upx=False, console=False,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="eRechnung",
)
app = BUNDLE(
    coll,
    name="eRechnung.app",
    icon="assets/icon.icns",
    bundle_identifier="com.machineandfolk.erechnung",
    info_plist={
        "CFBundleName": "eRechnung",
        "CFBundleDisplayName": "eRechnung",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        # WKWebView darf den lokalen Server über http://127.0.0.1 ansprechen.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "LSMinimumSystemVersion": "11.0",
    },
)

# WeasyPrint sucht 'libpango-1.0.dylib' / 'libpangoft2-1.0.dylib', das Bundle
# enthält aber nur die '...-1.0.0.dylib'-Dateien. Symlinks mit den gesuchten
# Namen anlegen, damit der cffi-dlopen-Patch (app.py) sie im Bundle findet.
_fw = os.path.join(DISTPATH, "eRechnung.app", "Contents", "Frameworks")
for _real, _alias in (
    ("libpango-1.0.0.dylib", "libpango-1.0.dylib"),
    ("libpangoft2-1.0.0.dylib", "libpangoft2-1.0.dylib"),
):
    _lp = os.path.join(_fw, _alias)
    if os.path.exists(os.path.join(_fw, _real)) and not os.path.lexists(_lp):
        os.symlink(_real, _lp)
