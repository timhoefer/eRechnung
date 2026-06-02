#!/bin/bash
# Doppelklick startet die E-Rechnung-App und öffnet den Browser.
cd "$(dirname "$0")" || exit 1

PORT="${PORT:-5055}"
URL="http://127.0.0.1:${PORT}"

if [ ! -x ".venv/bin/python" ]; then
  echo "Kein .venv gefunden. Bitte zuerst die Abhängigkeiten installieren."
  echo "Fenster kann geschlossen werden."
  read -r _
  exit 1
fi

# Browser öffnen, sobald der Server antwortet (max. ~10 s warten).
(
  for _ in $(seq 1 50); do
    if curl -s -o /dev/null "$URL"; then break; fi
    sleep 0.2
  done
  open "$URL"
) &

echo "E-Rechnung läuft auf ${URL}"
echo "Zum Beenden dieses Fenster schließen oder Strg+C drücken."
PORT="$PORT" exec ./.venv/bin/python app.py
