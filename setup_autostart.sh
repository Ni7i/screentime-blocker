#!/bin/bash
# Richtet Screentime Blocker als Autostart-App ein (kein Terminal nötig).
# Einmal ausführen — danach startet die App bei jedem Login automatisch.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
PLIST="$HOME/Library/LaunchAgents/com.screentime.blocker.plist"

echo "==> Virtuelle Umgebung anlegen..."
python3 -m venv "$VENV"

echo "==> rumps installieren..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet rumps

echo "==> Autostart einrichten..."
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.screentime.blocker</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python</string>
    <string>$DIR/menubar_app.py</string>
  </array>
  <key>RunAtLoad</key>  <true/>
  <key>KeepAlive</key>  <true/>
  <key>StandardOutPath</key> <string>$HOME/.screentime_blocker/app.log</string>
  <key>StandardErrorPath</key> <string>$HOME/.screentime_blocker/app.log</string>
</dict>
</plist>
EOF

mkdir -p "$HOME/.screentime_blocker"

# Alten Job stoppen falls vorhanden
launchctl unload "$PLIST" 2>/dev/null || true

# Neuen Job laden → App startet sofort + bei jedem Login
launchctl load -w "$PLIST"

echo ""
echo "✅ Fertig! Screentime Blocker läuft jetzt und startet bei jedem Login automatisch."
echo "   Das 🛡-Icon erscheint oben rechts in der Menüleiste."
echo ""
echo "Zum Deinstallieren:"
echo "  launchctl unload ~/Library/LaunchAgents/com.screentime.blocker.plist"
