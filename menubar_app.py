#!/usr/bin/env python3
"""
Screentime Blocker — macOS Menubar App
Kleines Icon oben rechts in der Menüleiste.
Benötigt: rumps (wird beim ersten Start automatisch installiert).
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# --- rumps sicherstellen ---
try:
    import rumps
except ImportError:
    sys.stderr.write(
        "\nFehler: 'rumps' ist nicht installiert.\n"
        "Bitte starte die App über 'Screentime.command' – das legt automatisch\n"
        "eine virtuelle Umgebung an und installiert rumps darin.\n\n"
        "Oder manuell:\n"
        "  python3 -m venv .venv\n"
        "  .venv/bin/pip install rumps\n"
        "  .venv/bin/python menubar_app.py\n"
    )
    sys.exit(1)

# --- Konfiguration ---
APP_NAME = "Screentime"
CONFIG_DIR = Path.home() / ".screentime_blocker"
CONFIG_FILE = CONFIG_DIR / "config.json"
PID_FILE = CONFIG_DIR / "daemon.pid"
LOG_FILE = CONFIG_DIR / "blocker.log"
HOSTS_FILE = "/etc/hosts"
MARKER_START = "# >>> SCREENTIME_BLOCKER START >>>"
MARKER_END = "# <<< SCREENTIME_BLOCKER END <<<"
HELPER_SCRIPT = Path(__file__).parent / "blocker_helper.sh"


# --- Helper ---
def ensure_dir():
    CONFIG_DIR.mkdir(exist_ok=True)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def load_cfg() -> dict:
    if not CONFIG_FILE.exists():
        return {"code_hash": "", "sites": [], "apps": [], "active": False}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_cfg(cfg: dict):
    ensure_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def osa_dialog(prompt: str, default: str = "", hidden: bool = False, title: str = APP_NAME):
    """Zeigt einen nativen macOS-Eingabedialog (mit korrektem Fokus), gibt Text oder None zurück."""
    hidden_arg = " with hidden answer" if hidden else ""
    # System Events aktivieren → Dialog bekommt Fokus, Tastatureingaben funktionieren
    script = (
        'tell application "System Events"\n'
        '  activate\n'
        f'  set theResult to display dialog "{_escape(prompt)}" default answer "{_escape(default)}" '
        f'with title "{_escape(title)}"{hidden_arg}\n'
        '  return text returned of theResult\n'
        'end tell'
    )
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def osa_info(msg: str, title: str = APP_NAME):
    script = (
        'tell application "System Events"\n'
        '  activate\n'
        f'  display dialog "{_escape(msg)}" with title "{_escape(title)}" '
        'buttons {"OK"} default button "OK"\n'
        'end tell'
    )
    subprocess.run(["osascript", "-e", script], capture_output=True)


def osa_confirm(msg: str, title: str = APP_NAME) -> bool:
    script = (
        'tell application "System Events"\n'
        '  activate\n'
        f'  display dialog "{_escape(msg)}" with title "{_escape(title)}" '
        'buttons {"Abbrechen","OK"} default button "OK"\n'
        'end tell'
    )
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return res.returncode == 0 and "OK" in res.stdout


def run_admin(shell_cmd: str) -> bool:
    """Führt Shell-Kommando mit Admin-Rechten via osascript aus (zeigt macOS Passwort-Dialog)."""
    escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    script = f'do shell script "{escaped}" with administrator privileges'
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if res.returncode != 0:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{time.ctime()}] run_admin Fehler: {res.stderr}\n")
    return res.returncode == 0


# Bekannte DNS-over-HTTPS Server, die /etc/hosts umgehen – auch blockieren,
# damit Browser wie Chrome / Firefox / Safari nicht dran vorbei auflösen können.
DOH_SERVERS = [
    "dns.google",
    "cloudflare-dns.com",
    "mozilla.cloudflare-dns.com",
    "chrome.cloudflare-dns.com",
    "one.one.one.one",
    "dns.quad9.net",
    "doh.opendns.com",
    "dns.nextdns.io",
    "dns.adguard.com",
]

# Browser die wir beim Blockieren kurz neustarten, damit DNS-Cache weg ist.
BROWSER_APPS = ["Google Chrome", "Safari", "Firefox", "Arc", "Brave Browser", "Microsoft Edge", "Opera"]


def _hosts_entries_for(domain: str) -> list[str]:
    """Gibt IPv4 + IPv6 Blockeinträge für eine Domain zurück (mit und ohne www.)."""
    d = domain.strip().lower()
    if not d:
        return []
    variants = [d]
    if not d.startswith("www."):
        variants.append(f"www.{d}")
    out = []
    for v in variants:
        out.append(f"127.0.0.1 {v}")
        out.append(f"::1 {v}")
    return out


# --- Hosts / Apps Operationen als Shell-Kommandos (für sudo) ---
def build_block_script(sites: list[str], apps: list[str]) -> str:
    # Hosts-Block aufbauen (mit IPv6 + DoH-Servern)
    lines = [MARKER_START]
    for d in sites:
        lines.extend(_hosts_entries_for(d))
    # DoH-Server blocken – sonst bypasst der Browser /etc/hosts
    if sites:
        lines.append("# --- DoH blockieren (damit Browser nicht /etc/hosts umgehen) ---")
        for doh in DOH_SERVERS:
            lines.extend(_hosts_entries_for(doh))
    lines.append(MARKER_END)
    block_text = "\n".join(lines)

    # Python-Daemon-Kommando
    py = sys.executable
    daemon_script = str(Path(__file__).parent / "blocker_daemon.py")
    apps_arg = ",".join(apps)

    cmd = f"""
/usr/bin/sed -i '' '/{MARKER_START}/,/{MARKER_END}/d' {HOSTS_FILE} 2>/dev/null || true
printf '\\n%s\\n' '{block_text}' >> {HOSTS_FILE}
/usr/bin/dscacheutil -flushcache
/usr/bin/killall -HUP mDNSResponder 2>/dev/null || true
/bin/mkdir -p {CONFIG_DIR}
/bin/chmod 777 {CONFIG_DIR}
nohup {py} {daemon_script} '{apps_arg}' > {LOG_FILE} 2>&1 &
echo $! > {PID_FILE}
"""
    return cmd.strip()


def build_unblock_script() -> str:
    cmd = f"""
/usr/bin/sed -i '' '/{MARKER_START}/,/{MARKER_END}/d' {HOSTS_FILE} 2>/dev/null || true
/usr/bin/dscacheutil -flushcache
/usr/bin/killall -HUP mDNSResponder 2>/dev/null || true
if [ -f {PID_FILE} ]; then
  PID=$(cat {PID_FILE})
  kill "$PID" 2>/dev/null || true
  rm -f {PID_FILE}
fi
pkill -f blocker_daemon.py 2>/dev/null || true
"""
    return cmd.strip()


# --- Die Menubar-App ---
class BlockerApp(rumps.App):
    def __init__(self):
        super().__init__(APP_NAME, title="🛡", quit_button=None)
        ensure_dir()
        self.menu = [
            "Status",
            None,
            "Blockieren",
            "Entsperren",
            None,
            "Websites verwalten",
            "Apps verwalten",
            "Code ändern / einrichten",
            None,
            "Über",
            "Beenden",
        ]
        self.refresh_title()

    def refresh_title(self):
        cfg = load_cfg()
        self.title = "🛑" if cfg.get("active") else "🛡"
        status = "AKTIV" if cfg.get("active") else "inaktiv"
        n_sites = len(cfg.get("sites", []))
        n_apps = len(cfg.get("apps", []))
        self.menu["Status"].title = f"Status: {status}  ({n_sites} Seiten, {n_apps} Apps)"

    # --- Menüpunkte ---
    @rumps.clicked("Blockieren")
    def on_block(self, _):
        cfg = load_cfg()
        if not cfg.get("code_hash"):
            osa_info("Bitte zuerst 'Code ändern / einrichten' wählen und einen Entsperr-Code festlegen.")
            return
        if not cfg.get("sites") and not cfg.get("apps"):
            osa_info("Keine Websites oder Apps zum Blockieren. Bitte zuerst welche hinzufügen.")
            return
        if cfg.get("active"):
            osa_info("Blockierung ist bereits aktiv.")
            return

        script = build_block_script(cfg.get("sites", []), cfg.get("apps", []))
        if run_admin(script):
            # Alle Browser einmal schließen, damit DNS-Cache gelöscht wird.
            # Sonst merken sie die Seite teilweise noch als erreichbar.
            if cfg.get("sites"):
                for b in BROWSER_APPS:
                    subprocess.run(
                        ["osascript", "-e", f'tell application "{b}" to quit'],
                        capture_output=True,
                    )
            cfg["active"] = True
            save_cfg(cfg)
            self.refresh_title()
            osa_info(
                f"Blockierung aktiv.\n\n"
                f"Websites: {', '.join(cfg['sites']) or '—'}\n"
                f"Apps: {', '.join(cfg['apps']) or '—'}\n\n"
                f"Wichtig: Browser wurden geschlossen und DNS-Cache geleert.\n"
                f"Falls eine Seite noch lädt: Browser neu starten."
            )
        else:
            osa_info("Aktivierung abgebrochen oder fehlgeschlagen.")

    @rumps.clicked("Entsperren")
    def on_unblock(self, _):
        cfg = load_cfg()
        if not cfg.get("active"):
            osa_info("Es ist aktuell keine Blockierung aktiv.")
            return
        code = osa_dialog("Entsperr-Code eingeben:", hidden=True)
        if code is None:
            return
        if hash_code(code) != cfg.get("code_hash"):
            osa_info("Falscher Code.")
            return
        if run_admin(build_unblock_script()):
            cfg["active"] = False
            save_cfg(cfg)
            self.refresh_title()
            osa_info("Blockierung aufgehoben. Alles ist wieder verfügbar.")
        else:
            osa_info("Entsperren fehlgeschlagen.")

    @rumps.clicked("Websites verwalten")
    def on_sites(self, _):
        cfg = load_cfg()
        if cfg.get("active"):
            osa_info("Bitte zuerst entsperren, um die Liste zu ändern.")
            return
        current = ", ".join(cfg.get("sites", []))
        value = osa_dialog(
            "Websites zum Blockieren (Komma-getrennt):",
            default=current or "youtube.com, instagram.com, tiktok.com",
        )
        if value is None:
            return
        cfg["sites"] = [s.strip().lower() for s in value.split(",") if s.strip()]
        save_cfg(cfg)
        self.refresh_title()
        osa_info(f"Gespeichert: {', '.join(cfg['sites']) or '(keine)'}")

    @rumps.clicked("Apps verwalten")
    def on_apps(self, _):
        cfg = load_cfg()
        if cfg.get("active"):
            osa_info("Bitte zuerst entsperren, um die Liste zu ändern.")
            return
        current = ", ".join(cfg.get("apps", []))
        value = osa_dialog(
            "Apps zum Blockieren (Name wie im Finder, Komma-getrennt):",
            default=current or "Safari, Google Chrome, Discord",
        )
        if value is None:
            return
        cfg["apps"] = [a.strip() for a in value.split(",") if a.strip()]
        save_cfg(cfg)
        self.refresh_title()
        osa_info(f"Gespeichert: {', '.join(cfg['apps']) or '(keine)'}")

    @rumps.clicked("Code ändern / einrichten")
    def on_code(self, _):
        cfg = load_cfg()
        if cfg.get("code_hash"):
            old = osa_dialog("Aktuellen Code eingeben:", hidden=True)
            if old is None:
                return
            if hash_code(old) != cfg["code_hash"]:
                osa_info("Falscher Code.")
                return
        new1 = osa_dialog("Neuen Entsperr-Code festlegen:", hidden=True)
        if new1 is None or not new1:
            return
        new2 = osa_dialog("Code wiederholen:", hidden=True)
        if new2 is None:
            return
        if new1 != new2:
            osa_info("Codes stimmen nicht überein.")
            return
        cfg["code_hash"] = hash_code(new1)
        save_cfg(cfg)
        osa_info("Code gespeichert.")

    @rumps.clicked("Status")
    def on_status(self, _):
        self.refresh_title()

    @rumps.clicked("Über")
    def on_about(self, _):
        osa_info(
            "Screentime Blocker\n\n"
            "Blockiert Websites (über /etc/hosts) und Apps (via Hintergrund-Daemon).\n"
            "Entsperrt wird nur mit deinem Code.\n\n"
            "Für macOS – Open Source (MIT)."
        )

    @rumps.clicked("Beenden")
    def on_quit(self, _):
        # nur beenden, wenn nichts aktiv ist oder Code bestätigt
        cfg = load_cfg()
        if cfg.get("active"):
            if not osa_confirm(
                "Blockierung ist noch aktiv und läuft im Hintergrund weiter, wenn du die App beendest.\n\nTrotzdem beenden?"
            ):
                return
        rumps.quit_application()


if __name__ == "__main__":
    BlockerApp().run()
