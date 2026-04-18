#!/bin/bash
# Doppelklick zum Starten der Menubar-App.
# Legt beim ersten Start eine virtuelle Python-Umgebung an und installiert rumps dort.
set -e
cd "$(dirname "$0")"

VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "Erstelle virtuelle Umgebung (einmalig) ..."
  python3 -m venv "$VENV"
fi

# rumps sicherstellen
"$VENV/bin/python" -c "import rumps" 2>/dev/null || {
  echo "Installiere rumps in der venv ..."
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet rumps
}

echo "Starte Screentime Blocker ..."
exec "$VENV/bin/python" menubar_app.py
