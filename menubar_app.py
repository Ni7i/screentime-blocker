#!/usr/bin/env python3
"""
Screentime Blocker — macOS Menubar App
Kleines Icon oben rechts in der Menüleiste.
Benötigt: rumps (wird beim ersten Start automatisch installiert).
"""

import datetime
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
RESTORE_PLIST_LABEL = "com.screentime.blocker.restore"
RESTORE_PLIST_PATH  = "/Library/LaunchDaemons/com.screentime.blocker.restore.plist"
RESTORE_SCRIPT_PATH = "/tmp/screentime_restore.sh"


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


def build_hosts_block_text(sites: list[str]) -> str:
    """Erzeugt den kompletten /etc/hosts-Block für eine Liste an Domains."""
    lines = [MARKER_START]
    for d in sites:
        lines.extend(_hosts_entries_for(d))
    if sites:
        lines.append("# --- DoH blockieren (damit Browser nicht /etc/hosts umgehen) ---")
        for doh in DOH_SERVERS:
            lines.extend(_hosts_entries_for(doh))
    lines.append(MARKER_END)
    return "\n".join(lines)


# --- Hosts / Apps Operationen als Shell-Kommandos (für sudo) ---
def build_block_script(sites: list[str], apps: list[str]) -> str:
    block_text = build_hosts_block_text(sites)

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
/bin/launchctl unload {RESTORE_PLIST_PATH} 2>/dev/null || true
/bin/rm -f {RESTORE_PLIST_PATH} {RESTORE_SCRIPT_PATH} 2>/dev/null || true
if [ -f {PID_FILE} ]; then
  PID=$(cat {PID_FILE})
  kill "$PID" 2>/dev/null || true
  rm -f {PID_FILE}
fi
pkill -f blocker_daemon.py 2>/dev/null || true
"""
    return cmd.strip()


def build_exception_script(cfg: dict, minutes: int) -> str:
    """Entfernt youtube.com aus dem Block und registriert einen launchd-Job,
    der nach genau `minutes` Minuten automatisch wieder vollständig sperrt.
    launchd ist zuverlässiger als nohup – überlebt auch App-Neustarts.
    """
    sites = cfg.get("sites", [])
    sites_without_yt = [
        s for s in sites
        if s.strip().lower() not in ("youtube.com", "www.youtube.com")
    ]
    exception_block = build_hosts_block_text(sites_without_yt)
    full_block      = build_hosts_block_text(sites)

    # Restore-Skript (wird von launchd als root ausgeführt)
    restore_content = f"""#!/bin/sh
/usr/bin/sed -i '' '/{MARKER_START}/,/{MARKER_END}/d' {HOSTS_FILE} 2>/dev/null
printf '\\n%s\\n' '{full_block}' >> {HOSTS_FILE}
/usr/bin/dscacheutil -flushcache
/usr/bin/killall -HUP mDNSResponder 2>/dev/null || true
/bin/launchctl unload {RESTORE_PLIST_PATH} 2>/dev/null || true
/bin/rm -f {RESTORE_PLIST_PATH} "$0"
"""
    with open(RESTORE_SCRIPT_PATH, "w") as f:
        f.write(restore_content)
    os.chmod(RESTORE_SCRIPT_PATH, 0o755)

    # launchd-Plist: feuert einmalig zur berechneten Uhrzeit
    fire = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    plist_tmp = "/tmp/screentime_restore_job.plist"
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>{RESTORE_PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>{RESTORE_SCRIPT_PATH}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>   <integer>{fire.hour}</integer>
    <key>Minute</key> <integer>{fire.minute}</integer>
  </dict>
  <key>RunAtLoad</key> <false/>
</dict>
</plist>
"""
    with open(plist_tmp, "w") as f:
        f.write(plist_content)

    cmd = f"""
/usr/bin/sed -i '' '/{MARKER_START}/,/{MARKER_END}/d' {HOSTS_FILE} 2>/dev/null || true
printf '\\n%s\\n' '{exception_block}' >> {HOSTS_FILE}
/usr/bin/dscacheutil -flushcache
/usr/bin/killall -HUP mDNSResponder 2>/dev/null || true
/bin/launchctl unload {RESTORE_PLIST_PATH} 2>/dev/null || true
/bin/rm -f {RESTORE_PLIST_PATH}
/bin/cp {plist_tmp} {RESTORE_PLIST_PATH}
/bin/chmod 644 {RESTORE_PLIST_PATH}
/usr/sbin/chown root:wheel {RESTORE_PLIST_PATH}
/bin/launchctl load {RESTORE_PLIST_PATH}
/bin/rm -f {plist_tmp}
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
            "Ausnahme: Andalusi öffnen (30 Min)",
            "Ausnahme-Link setzen",
            None,
            "Website sperren...",
            "Website freigeben... (Code)",
            "Apps verwalten (Code)",
            "Code ändern / einrichten",
            None,
            "Über",
            "Beenden",
        ]
        self.refresh_title()

    def refresh_title(self):
        cfg = load_cfg()
        # Prüfen ob /etc/hosts tatsächlich unseren Block hat - State konsistent halten
        hosts_has_block = False
        try:
            with open(HOSTS_FILE) as f:
                hosts_has_block = MARKER_START in f.read()
        except Exception:
            pass
        if cfg.get("active") and not hosts_has_block:
            cfg["active"] = False
            save_cfg(cfg)
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

    @rumps.clicked("Ausnahme: Andalusi öffnen (30 Min)")
    def on_exception(self, _):
        cfg = load_cfg()
        if not cfg.get("active"):
            osa_info("Blockierung ist nicht aktiv. Erst 'Blockieren' klicken.")
            return
        yt_blocked = any(
            s.strip().lower() in ("youtube.com", "www.youtube.com")
            for s in cfg.get("sites", [])
        )
        if not yt_blocked:
            osa_info("youtube.com ist nicht in deiner Blockliste — keine Ausnahme nötig.")
            return

        url = cfg.get("whitelist_url", "").strip()
        if not url:
            url = osa_dialog(
                "Channel-Link von Muhammad Andalusi eingeben (wird gespeichert):",
                default="https://www.youtube.com/@",
            )
            if not url:
                return
            cfg["whitelist_url"] = url.strip()
            save_cfg(cfg)

        code = osa_dialog("Code eingeben für 30-Min-Ausnahme:", hidden=True)
        if code is None:
            return
        if hash_code(code) != cfg.get("code_hash"):
            osa_info("Falscher Code.")
            return

        script = build_exception_script(cfg, 30)
        if run_admin(script):
            subprocess.run(["open", cfg["whitelist_url"]])
            osa_info(
                "YouTube für 30 Minuten freigeschaltet.\n\n"
                f"Kanal wird geöffnet: {cfg['whitelist_url']}\n\n"
                "Nach 30 Minuten wird YouTube automatisch wieder gesperrt."
            )
        else:
            osa_info("Ausnahme konnte nicht aktiviert werden.")

    @rumps.clicked("Ausnahme-Link setzen")
    def on_set_exception_url(self, _):
        cfg = load_cfg()
        current = cfg.get("whitelist_url", "")
        url = osa_dialog(
            "Channel-Link (z. B. https://www.youtube.com/@MuhammadAndalusi):",
            default=current or "https://www.youtube.com/@",
        )
        if url is None:
            return
        cfg["whitelist_url"] = url.strip()
        save_cfg(cfg)
        osa_info(f"Ausnahme-Link gespeichert:\n{cfg['whitelist_url'] or '(leer)'}")

    @rumps.clicked("Website sperren...")
    def on_site_add(self, _):
        """Neue Website sperren — kein Code nötig, nur hinzufügen."""
        cfg = load_cfg()
        value = osa_dialog(
            "Website(s) sperren (Komma-getrennt):\nz. B.  facebook.com, reddit.com",
            default="",
        )
        if value is None or not value.strip():
            return
        new_sites = [s.strip().lower() for s in value.split(",") if s.strip()]
        existing = cfg.get("sites", [])
        added = [s for s in new_sites if s not in existing]
        if not added:
            osa_info("Diese Seiten sind bereits gesperrt.")
            return
        cfg["sites"] = existing + added
        save_cfg(cfg)
        # Sofort in /etc/hosts anwenden
        if cfg.get("active"):
            script = build_block_script(cfg["sites"], cfg.get("apps", []))
            if run_admin(script):
                for b in BROWSER_APPS:
                    subprocess.run(
                        ["osascript", "-e", f'tell application "{b}" to quit'],
                        capture_output=True,
                    )
                self.refresh_title()
                osa_info(f"Gesperrt: {', '.join(added)}\n\nAlle gesperrten Seiten:\n{', '.join(cfg['sites'])}")
            else:
                # Admin abgebrochen → aus config wieder entfernen
                cfg["sites"] = existing
                save_cfg(cfg)
                osa_info("Abgebrochen. Keine Änderung.")
        else:
            self.refresh_title()
            osa_info(f"Gespeichert: {', '.join(added)}\nWird beim nächsten 'Blockieren' aktiv.")

    @rumps.clicked("Website freigeben... (Code)")
    def on_site_remove(self, _):
        """Website aus der Sperrliste entfernen — nur mit Entsperr-Code."""
        cfg = load_cfg()
        if not cfg.get("sites"):
            osa_info("Keine Websites gesperrt.")
            return
        code = osa_dialog("Entsperr-Code eingeben:", hidden=True)
        if code is None:
            return
        if hash_code(code) != cfg.get("code_hash"):
            osa_info("Falscher Code.")
            return
        current_list = "\n".join(f"• {s}" for s in cfg["sites"])
        value = osa_dialog(
            f"Aktuell gesperrt:\n{current_list}\n\nWelche Website(s) freigeben? (Komma-getrennt)",
            default="",
        )
        if value is None or not value.strip():
            return
        to_remove = [s.strip().lower() for s in value.split(",") if s.strip()]
        new_sites = [s for s in cfg["sites"] if s not in to_remove]
        if len(new_sites) == len(cfg["sites"]):
            osa_info("Keine der angegebenen Seiten war in der Liste.")
            return
        cfg["sites"] = new_sites
        save_cfg(cfg)
        if cfg.get("active"):
            script = build_block_script(cfg["sites"], cfg.get("apps", []))
            run_admin(script)
        self.refresh_title()
        osa_info(f"Freigegeben: {', '.join(to_remove)}")

    @rumps.clicked("Apps verwalten (Code)")
    def on_apps(self, _):
        cfg = load_cfg()
        code = osa_dialog("Entsperr-Code eingeben:", hidden=True)
        if code is None:
            return
        if hash_code(code) != cfg.get("code_hash"):
            osa_info("Falscher Code.")
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
