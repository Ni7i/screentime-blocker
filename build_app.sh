#!/bin/bash
# Baut Screentime.app – eine echte macOS-App zum Doppelklicken.
# Benutzt eine virtuelle Umgebung (PEP 668 sicher).
set -e
cd "$(dirname "$0")"

VENV=".venv-build"

echo "==> Virtuelle Umgebung anlegen ..."
python3 -m venv "$VENV"

echo "==> py2app & rumps installieren ..."
"$VENV/bin/pip" install --quiet --upgrade pip setuptools wheel
"$VENV/bin/pip" install --quiet py2app rumps

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

echo "==> App bauen (kann 1–2 Min dauern) ..."
rm -rf build dist
"$VENV/bin/python" setup.py py2app

echo ""
echo "Fertig! Screentime.app liegt in: $(pwd)/dist/Screentime.app"
echo ""
echo "Installieren:"
echo "  mv dist/Screentime.app /Applications/"
echo "  open /Applications/Screentime.app"
