#!/usr/bin/env python3
"""
Screentime Blocker für macOS
Blockiert Websites (über /etc/hosts) und Apps (durch Beenden beim Start).
Entsperrung nur mit festgelegtem Code.
"""

import argparse
import getpass
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# --- Konfiguration ---
CONFIG_DIR = Path.home() / ".screentime_blocker"
CONFIG_FILE = CONFIG_DIR / "config.json"
PID_FILE = CONFIG_DIR / "daemon.pid"
LOG_FILE = CONFIG_DIR / "blocker.log"
HOSTS_FILE = "/etc/hosts"
MARKER_START = "# >>> SCREENTIME_BLOCKER START >>>"
MARKER_END = "# <<< SCREENTIME_BLOCKER END <<<"


# --- Hilfsfunktionen ---
def ensure_config_dir():
    CONFIG_DIR.mkdir(exist_ok=True)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def load_config():
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(cfg):
    ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def is_root():
    return os.geteuid() == 0


def run_sudo(args):
    """Führt das Skript selbst mit sudo neu aus."""
    print("Administrator-Rechte werden benötigt – bitte Passwort eingeben.")
    os.execvp("sudo", ["sudo", sys.executable, os.path.abspath(__file__)] + args)


# --- /etc/hosts Manipulation ---
def write_hosts_block(domains):
    """Fügt einen Block zum Blockieren der Domains in /etc/hosts ein."""
    with open(HOSTS_FILE) as f:
        content = f.read()

    # Alten Block entfernen, falls vorhanden
    content = remove_hosts_block_content(content)

    block_lines = [MARKER_START]
    for d in domains:
        d = d.strip().lower()
        if not d:
            continue
        # mit und ohne www.
        block_lines.append(f"127.0.0.1 {d}")
        block_lines.append(f"127.0.0.1 www.{d}" if not d.startswith("www.") else f"127.0.0.1 {d[4:]}")
    block_lines.append(MARKER_END)

    new_content = content.rstrip() + "\n\n" + "\n".join(block_lines) + "\n"
    with open(HOSTS_FILE, "w") as f:
        f.write(new_content)

    # DNS Cache leeren
    subprocess.run(["dscacheutil", "-flushcache"], check=False)
    subprocess.run(["killall", "-HUP", "mDNSResponder"], check=False)


def remove_hosts_block_content(content: str) -> str:
    lines = content.splitlines()
    result = []
    skip = False
    for line in lines:
        if MARKER_START in line:
            skip = True
            continue
        if MARKER_END in line:
            skip = False
            continue
        if not skip:
            result.append(line)
    return "\n".join(result).rstrip() + "\n"


def remove_hosts_block():
    with open(HOSTS_FILE) as f:
        content = f.read()
    new_content = remove_hosts_block_content(content)
    with open(HOSTS_FILE, "w") as f:
        f.write(new_content)
    subprocess.run(["dscacheutil", "-flushcache"], check=False)
    subprocess.run(["killall", "-HUP", "mDNSResponder"], check=False)


# --- App-Blockierung ---
def kill_apps(app_names):
    """Beendet laufende Apps mit den angegebenen Namen."""
    for app in app_names:
        app = app.strip()
        if not app:
            continue
        # versuche die App freundlich zu beenden
        subprocess.run(
            ["osascript", "-e", f'tell application "{app}" to quit'],
            capture_output=True,
        )
        # und hart über pkill als Fallback
        subprocess.run(["pkill", "-x", app], capture_output=True)
        subprocess.run(["pkill", "-f", app], capture_output=True)


def daemon_loop(app_names, interval=2):
    """Läuft im Hintergrund und beendet wiederholt blockierte Apps."""
    with open(LOG_FILE, "a") as log:
        log.write(f"[{time.ctime()}] Daemon gestartet, blockiert: {app_names}\n")
        log.flush()
        while True:
            try:
                kill_apps(app_names)
            except Exception as e:
                log.write(f"[{time.ctime()}] Fehler: {e}\n")
                log.flush()
            time.sleep(interval)


def start_daemon(app_names):
    """Startet den App-Killer-Daemon im Hintergrund."""
    if not app_names:
        return
    stop_daemon()  # alten Daemon beenden
    pid = os.fork()
    if pid > 0:
        # Parent: PID speichern
        ensure_config_dir()
        PID_FILE.write_text(str(pid))
        print(f"App-Blocker Daemon gestartet (PID {pid}).")
        return
    # Child: weiter forken für richtiges Daemonisieren
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    # Grandchild: eigentlicher Daemon
    sys.stdin = open(os.devnull, "r")
    sys.stdout = open(LOG_FILE, "a")
    sys.stderr = open(LOG_FILE, "a")
    daemon_loop(app_names)


def stop_daemon():
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, ValueError):
        pass
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


# --- Befehle ---
def cmd_setup():
    """Erstinstallation: Code, Websites und Apps festlegen."""
    print("=== Screentime Blocker Einrichtung ===")
    cfg = load_config() or {}

    if cfg.get("code_hash"):
        old = getpass.getpass("Aktuellen Code eingeben (oder leer lassen für Abbruch): ")
        if hash_code(old) != cfg["code_hash"]:
            print("Falscher Code. Abbruch.")
            return

    code1 = getpass.getpass("Neuen Entsperr-Code festlegen: ")
    code2 = getpass.getpass("Code wiederholen: ")
    if code1 != code2 or not code1:
        print("Codes stimmen nicht überein oder sind leer. Abbruch.")
        return

    print("\nWebsites zum Blockieren eingeben (Komma-getrennt).")
    print("Beispiel: youtube.com, instagram.com, tiktok.com")
    sites = input("Websites: ").strip()
    site_list = [s.strip() for s in sites.split(",") if s.strip()]

    print("\nApps zum Blockieren (Name wie im Finder, Komma-getrennt).")
    print("Beispiel: Safari, Google Chrome, Discord")
    apps = input("Apps: ").strip()
    app_list = [a.strip() for a in apps.split(",") if a.strip()]

    cfg["code_hash"] = hash_code(code1)
    cfg["sites"] = site_list
    cfg["apps"] = app_list
    cfg["active"] = False
    save_config(cfg)

    print("\nKonfiguration gespeichert unter", CONFIG_FILE)
    print("Starte Blockierung mit: sudo python3 blocker.py block")


def cmd_block():
    cfg = load_config()
    if not cfg:
        print("Keine Konfiguration gefunden. Bitte zuerst 'setup' ausführen.")
        return
    if not is_root():
        run_sudo(["block"])
        return

    write_hosts_block(cfg.get("sites", []))
    start_daemon(cfg.get("apps", []))
    kill_apps(cfg.get("apps", []))

    cfg["active"] = True
    save_config(cfg)
    print("Blockierung AKTIV.")
    print(f"  Websites: {', '.join(cfg.get('sites', [])) or '(keine)'}")
    print(f"  Apps:     {', '.join(cfg.get('apps', [])) or '(keine)'}")
    print("Entsperren mit: sudo python3 blocker.py unblock")


def cmd_unblock():
    cfg = load_config()
    if not cfg:
        print("Keine Konfiguration gefunden.")
        return
    if not is_root():
        run_sudo(["unblock"])
        return

    code = getpass.getpass("Entsperr-Code: ")
    if hash_code(code) != cfg.get("code_hash"):
        print("Falscher Code.")
        return

    remove_hosts_block()
    stop_daemon()
    cfg["active"] = False
    save_config(cfg)
    print("Blockierung AUFGEHOBEN. Alle Websites und Apps sind wieder verfügbar.")


def cmd_status():
    cfg = load_config()
    if not cfg:
        print("Keine Konfiguration gefunden.")
        return
    print("Status:", "AKTIV" if cfg.get("active") else "inaktiv")
    print("Websites:", ", ".join(cfg.get("sites", [])) or "(keine)")
    print("Apps:    ", ", ".join(cfg.get("apps", [])) or "(keine)")
    if PID_FILE.exists():
        print("Daemon PID:", PID_FILE.read_text().strip())


def main():
    parser = argparse.ArgumentParser(description="Screentime Blocker für macOS")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("setup", help="Code, Websites und Apps festlegen")
    sub.add_parser("block", help="Blockierung aktivieren (benötigt sudo)")
    sub.add_parser("unblock", help="Blockierung mit Code aufheben (benötigt sudo)")
    sub.add_parser("status", help="Aktuellen Status anzeigen")

    args = parser.parse_args()
    if args.cmd == "setup":
        cmd_setup()
    elif args.cmd == "block":
        cmd_block()
    elif args.cmd == "unblock":
        cmd_unblock()
    elif args.cmd == "status":
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
