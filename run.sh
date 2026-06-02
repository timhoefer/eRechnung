#!/usr/bin/env bash
# Startet die lokale E-Rechnung-Web-App auf http://127.0.0.1:5000
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
exec ./.venv/bin/python app.py
