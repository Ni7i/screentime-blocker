#!/bin/bash
# Doppelklick zum Starten der Menubar-App
cd "$(dirname "$0")"
# rumps ggf. installieren
python3 -c "import rumps" 2>/dev/null || python3 -m pip install --user rumps
exec python3 menubar_app.py
