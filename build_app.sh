#!/bin/bash
# Baut die Menubar-App zu einer eigenständigen macOS .app mit py2app.
# Ergebnis: dist/Screentime.app  (kann z.B. in /Applications gezogen werden)

set -e
cd "$(dirname "$0")"

echo "Installiere py2app & rumps ..."
python3 -m pip install --user py2app rumps

cat > setup.py <<'PY'
from setuptools import setup

APP = ['menubar_app.py']
DATA_FILES = ['blocker_daemon.py']
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'Screentime',
        'CFBundleDisplayName': 'Screentime Blocker',
        'CFBundleIdentifier': 'com.local.screentime.blocker',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,  # nur Menubar, kein Dock-Icon
    },
    'packages': ['rumps'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
PY

echo "Baue die App (kann 1–2 Minuten dauern) ..."
python3 setup.py py2app

echo ""
echo "Fertig! App liegt in: $(pwd)/dist/Screentime.app"
echo "Du kannst sie per Drag & Drop nach /Applications verschieben."
