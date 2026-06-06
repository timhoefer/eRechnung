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

rm -rf build dist
.venv/bin/pyinstaller eRechnung.spec --noconfirm

echo
echo "Fertig: dist/eRechnung.app"
echo "Headless-Selbsttest: ./dist/eRechnung.app/Contents/MacOS/eRechnung --selftest"
echo
echo "Hinweis: Die App ist unsigniert. Beim ersten Öffnen auf einem anderen Mac"
echo "Rechtsklick auf die App > 'Öffnen' wählen (Gatekeeper). Für eine Weitergabe"
echo "ohne Warnung ist Code-Signing + Notarisierung (Apple Developer Program) nötig."
