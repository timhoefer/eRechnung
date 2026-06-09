#!/usr/bin/env bash
# Baut die macOS-Doppelklick-App (Option D)  ->  dist/eRechnung.app
#
# Voraussetzungen:
#   - .venv mit Runtime-Deps (requirements.txt) + Build-Deps (requirements-build.txt)
#   - Homebrew-Pango installiert (liefert die nativen Libs, die ins Bundle wandern):
#       brew install pango
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

echo
echo "Fertig: dist/eRechnung.app"
echo "Headless-Selbsttest: ./dist/eRechnung.app/Contents/MacOS/eRechnung --selftest"
echo
echo "Hinweis: Die App ist unsigniert. Beim ersten Öffnen auf einem anderen Mac"
echo "Rechtsklick auf die App > 'Öffnen' wählen (Gatekeeper). Für eine Weitergabe"
echo "ohne Warnung ist Code-Signing + Notarisierung (Apple Developer Program) nötig."
