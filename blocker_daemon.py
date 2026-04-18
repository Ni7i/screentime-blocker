#!/usr/bin/env python3
"""
Hintergrund-Daemon: beendet alle paar Sekunden die blockierten Apps.
Wird von der Menubar-App als root gestartet (damit er nicht einfach gekillt wird).
Aufruf: blocker_daemon.py "App1,App2,App3"
"""
import subprocess
import sys
import time


def kill_apps(apps):
    for app in apps:
        app = app.strip()
        if not app:
            continue
        # Freundliches Quit per AppleScript
        subprocess.run(
            ["osascript", "-e", f'tell application "{app}" to quit'],
            capture_output=True,
        )
        # Hart
        subprocess.run(["pkill", "-x", app], capture_output=True)
        subprocess.run(["pkill", "-f", app], capture_output=True)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    apps = [a.strip() for a in arg.split(",") if a.strip()]
    if not apps:
        return
    while True:
        try:
            kill_apps(apps)
        except Exception:
            pass
        time.sleep(2)


if __name__ == "__main__":
    main()
