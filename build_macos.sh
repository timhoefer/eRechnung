#!/usr/bin/env bash
# Baut die macOS-Doppelklick-App (Option D)  ->  dist/eRechnung.app
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
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/pyinstaller ]; then
  echo "PyInstaller/pywebview fehlen. Einmalig installieren mit:"
  echo "  .venv/bin/pip install -r requirements-build.txt"
  exit 1
fi

# build/dist aufräumen. Eine laufende App hält dist/ offen ("rm: dist: Directory not
# empty"); daher: erst normal versuchen, bei Misserfolg die laufende Instanz beenden
# und erneut (mit kurzem Warten, falls Spotlight/Finder noch Dateien hält).
APP_BIN="dist/eRechnung.app/Contents/MacOS/eRechnung"
clean() { rm -rf build dist 2>/dev/null; [ ! -e dist ] && [ ! -e build ]; }
if ! clean; then
  if pgrep -f "$APP_BIN" >/dev/null 2>&1; then
    echo "Beende laufende eRechnung-App (hält dist/ offen) ..."
    pkill -f "$APP_BIN" || true
  fi
  for attempt in 1 2 3; do
    sleep 1
    clean && break
    echo "Aufräumen von build/dist erneut versucht ($attempt) ..."
  done
fi
if [ -e dist ] || [ -e build ]; then
  echo "FEHLER: build/dist ließ sich nicht entfernen – läuft die App noch?" >&2
  echo "        Bitte eRechnung beenden (Cmd+Q) und erneut bauen." >&2
  exit 1
fi

.venv/bin/pyinstaller eRechnung.spec --noconfirm

APP="dist/eRechnung.app"

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
  if [ -z "${SIGN_IDENTITY:-}" ]; then
    echo "FEHLER: NOTARY_PROFILE gesetzt, aber SIGN_IDENTITY fehlt (unsignierte Apps" >&2
    echo "        kann Apple nicht notarisieren)." >&2
    exit 1
  fi
  echo
  echo "Notarisiere (Profil: $NOTARY_PROFILE) – dauert meist 1–5 Minuten ..."
  ZIP="dist/eRechnung-notarize.zip"
  ditto -c -k --keepParent "$APP" "$ZIP"
  xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
  rm -f "$ZIP"
  xcrun stapler staple "$APP"
  echo "Gatekeeper-Check:"
  spctl --assess --type execute -vv "$APP"
fi

echo
echo "Fertig: $APP"
echo "Headless-Selbsttest: ./$APP/Contents/MacOS/eRechnung --selftest"
echo
if [ -z "${SIGN_IDENTITY:-}" ]; then
  echo "Hinweis: Die App ist unsigniert. Beim ersten Öffnen auf einem anderen Mac"
  echo "Rechtsklick auf die App > 'Öffnen' wählen (Gatekeeper). Für eine Weitergabe"
  echo "ohne Warnung: SIGN_IDENTITY + NOTARY_PROFILE setzen (siehe Kopf dieses Skripts)."
fi
