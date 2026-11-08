#!/usr/bin/env bash
# Baut die macOS-App als dist/eRechnung.dmg und dist/eRechnung.app.zip.
#
# Voraussetzungen:
#   - .venv mit Runtime-Deps (requirements.txt) + Build-Deps (requirements-build.txt)
#   - Homebrew-Pango installiert (liefert die nativen Libs, die ins Bundle wandern):
#       brew install pango
#
# Optional – Signieren + Notarisieren (für Weitergabe ohne Gatekeeper-Warnung):
#   SIGN_IDENTITY="Developer ID Application: Name (TEAMID)"  -> signiert das Bundle
#   NOTARY_PROFILE="erechnung-notary"                        -> notarisiert + staple
#   (Profil einmalig anlegen: xcrun notarytool store-credentials erechnung-notary)
#   Beispiel:
#     SIGN_IDENTITY="Developer ID Application: …" NOTARY_PROFILE=erechnung-notary ./build_macos.sh
#   Ohne diese Variablen verhält sich der Build wie bisher (unsigniert).
#
# Der klassische Start (run.sh / start.command) bleibt davon unberührt.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/pyinstaller ] || [ ! -x .venv/bin/dmgbuild ]; then
  echo "Build-Abhängigkeiten fehlen. Einmalig installieren mit:"
  echo "  .venv/bin/pip install -r requirements-build.txt"
  exit 1
fi

# Apple-Zugriff vor dem Build prüfen; ein Vertrags-/Loginfehler wird so nicht
# erst nach dem Signieren sichtbar.
if [ -n "${NOTARY_PROFILE:-}" ]; then
  if [ -z "${SIGN_IDENTITY:-}" ]; then
    echo "NOTARY_PROFILE benötigt SIGN_IDENTITY." >&2
    exit 1
  fi
  xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null
fi

# Außerhalb synchronisierter Projektordner bauen: File Provider können sonst
# Finder-Metadaten in das signierte Bundle schreiben. Vorhandene Downloads bleiben
# bis zum erfolgreichen Abschluss erhalten; laufende Apps werden nicht beendet.
BUILD_STAGE=$(mktemp -d /private/tmp/erechnung-build.XXXXXX)
trap 'rm -rf "$BUILD_STAGE"' EXIT
.venv/bin/pyinstaller eRechnung.spec --noconfirm \
  --workpath "$BUILD_STAGE/build" --distpath "$BUILD_STAGE/dist"
APP="$BUILD_STAGE/dist/eRechnung.app"
xattr -cr "$APP"

# --- Optional: Signieren (Hardened Runtime) -----------------------------------
if [ -n "${SIGN_IDENTITY:-}" ]; then
  echo
  echo "Signiere mit: $SIGN_IDENTITY"
  # Erst alle eingebetteten Mach-O-Dateien, dann das Bundle selbst. Inside-out ist
  # robuster als --deep (Apple rät von --deep ab). WICHTIG: nicht nur nach *.so/*.dylib
  # filtern — Framework-Binärdateien heißen ohne Endung (z. B. Python.framework/.../Python)
  # und würden sonst durchrutschen -> Notarisierung lehnt ab ("not signed with a valid
  # Developer ID certificate / no secure timestamp"). Daher jede Datei per `file` prüfen
  # und alles Mach-O signieren.
  find "$APP" -type f -print0 | while IFS= read -r -d '' f; do
    case "$(file -b "$f")" in
      *Mach-O*)
        codesign --force --options runtime --timestamp \
          --entitlements entitlements.plist --sign "$SIGN_IDENTITY" "$f" ;;
    esac
  done
  codesign --force --options runtime --timestamp \
    --entitlements entitlements.plist --sign "$SIGN_IDENTITY" "$APP"
  echo "Prüfe Signatur ..."
  codesign --verify --strict --deep "$APP"
  echo "Signatur ok."
fi

# --- Optional: Notarisieren + Staple -------------------------------------------
if [ -n "${NOTARY_PROFILE:-}" ]; then
  echo
  echo "Notarisiere (Profil: $NOTARY_PROFILE) – dauert meist 1–5 Minuten ..."
  ZIP="$BUILD_STAGE/eRechnung-notarize.zip"
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
  xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
  rm -f "$ZIP"
  xcrun stapler staple "$APP"
  echo "Gatekeeper-Check:"
  spctl --assess --type execute -vv "$APP"
fi

VERSION=$(.venv/bin/python -c 'from version import __version__; print(__version__)')
RELEASE_ZIP="$BUILD_STAGE/eRechnung.app.zip"
# AppleDouble-Metadaten außerhalb des Bundles halten. Manche Entpacker lassen
# sonst ._*-Dateien an Framework-Symlinks zurück; Gatekeeper lehnt das Bundle ab.
ditto -c -k --sequesterRsrc --keepParent "$APP" "$RELEASE_ZIP"

RELEASE_DMG="$BUILD_STAGE/eRechnung.dmg"
# Nur der Hintergrund-Renderer braucht den Homebrew-Suchpfad, nicht die App.
DYLD_FALLBACK_LIBRARY_PATH="${HOMEBREW_LIB:-/opt/homebrew/lib}${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}" \
.venv/bin/python scripts/build_dmg.py --app "$APP" --output "$RELEASE_DMG"
if [ -n "${SIGN_IDENTITY:-}" ]; then
  codesign --force --timestamp --sign "$SIGN_IDENTITY" "$RELEASE_DMG"
fi
if [ -n "${NOTARY_PROFILE:-}" ]; then
  xcrun notarytool submit "$RELEASE_DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$RELEASE_DMG"
fi

CHECK_ARGS=(--version "$VERSION" --app "$APP" --archive "$RELEASE_ZIP" --dmg "$RELEASE_DMG")
if [ -z "${NOTARY_PROFILE:-}" ]; then
  CHECK_ARGS+=(--unsigned)
fi
.venv/bin/python scripts/check_macos_release.py "${CHECK_ARGS[@]}"
mkdir -p dist
cp "$RELEASE_ZIP" dist/eRechnung.app.zip
cp "$RELEASE_DMG" dist/eRechnung.dmg

echo
echo "Fertig: dist/eRechnung.dmg (empfohlen) und dist/eRechnung.app.zip"
echo "Zum Installieren das DMG öffnen und eRechnung auf den Programme-Ordner ziehen."
echo
if [ -z "${SIGN_IDENTITY:-}" ]; then
  echo "Hinweis: Die App ist unsigniert. Beim ersten Öffnen auf einem anderen Mac"
  echo "Die lokale Build-Prüfung ersetzt keine Signierung/Notarisierung. Für eine Weitergabe"
  echo "ohne Warnung: SIGN_IDENTITY + NOTARY_PROFILE setzen (siehe Kopf dieses Skripts)."
fi
