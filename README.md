# Screentime Blocker (macOS)

Kleine **Menubar-App** für den Mac: blockiert **Websites** (z. B. `youtube.com`) und **Apps**. Entsperrt wird nur mit einem selbst festgelegten **Code**. Lebt als kleines Icon 🛡 oben rechts in der Menüleiste (wie BetterDisplay, 1Password etc.).

> Nutzt `/etc/hosts` zum Blockieren von Websites und einen Hintergrund-Daemon, der blockierte Apps beim Start sofort wieder beendet.

## Features
- Websites blockieren (z. B. `youtube.com`, `instagram.com`, `tiktok.com`)
- Apps blockieren (z. B. `Safari`, `Google Chrome`, `Discord`)
- Entsperrung nur mit festgelegtem Code (SHA-256 Hash gespeichert)
- Status-Befehl
- Keine externen Abhängigkeiten – nur Python 3

## Voraussetzungen
- macOS
- Python 3 (ist auf modernen Macs vorinstalliert)
- Administrator-Rechte (`sudo`), da `/etc/hosts` geändert wird

## Schnellstart (einfach)

**Variante A – mit Doppelklick starten:**
1. Ordner öffnen, Doppelklick auf `Screentime.command`
2. (Einmalig: installiert `rumps` automatisch)
3. Oben rechts erscheint das Icon 🛡 → anklicken → alle Optionen im Menü

**Variante B – richtige .app bauen (empfohlen):**
```bash
cd screentime-blocker
bash build_app.sh
open dist/Screentime.app
```
Danach liegt eine eigenständige `Screentime.app` in `dist/`. Einfach nach `/Applications` ziehen.
Um sie automatisch beim Login zu starten: **Systemeinstellungen → Allgemein → Anmeldeobjekte → Screentime hinzufügen**.

## Nutzung über die Menubar

Klick auf das 🛡-Icon → Menü mit:

- **Status** – zeigt ob gerade blockiert wird
- **Blockieren** – aktiviert die Sperre (macOS fragt nach Admin-Passwort)
- **Entsperren** – fragt nach deinem Code und hebt alles auf
- **Websites verwalten** – Liste komma-getrennt eingeben
- **Apps verwalten** – Liste komma-getrennt eingeben
- **Code ändern / einrichten** – neuer Entsperr-Code
- **Beenden**

Alle Dialoge sind native macOS-Fenster – sehr einfach zu bedienen.

## CLI (optional)

Es gibt zusätzlich eine Kommandozeilen-Version `blocker.py` mit `setup`, `block`, `unblock`, `status`.

## Wie funktioniert das?

**Websites:** Beim Blockieren werden Einträge in `/etc/hosts` geschrieben, die die Domain auf `127.0.0.1` umleiten. Dadurch ist die Seite im Browser nicht mehr erreichbar. Beim Entsperren werden diese Einträge wieder entfernt und der DNS-Cache geleert.

**Apps:** Ein kleiner Hintergrund-Daemon läuft und beendet jede Sekunde erneut alle Apps aus deiner Block-Liste. Du kannst sie also nicht mehr länger als ein paar Sekunden offen halten, solange die Blockierung aktiv ist.

## Sicherheit / Grenzen
- Der Code wird als **SHA-256-Hash** gespeichert, nicht im Klartext.
- Wer Root-Zugriff auf den Mac hat, kann die Blockierung theoretisch umgehen (Config-Datei löschen, `/etc/hosts` manuell bearbeiten). Das Tool ist als **Selbstdisziplin-Helfer** gedacht, nicht als Kindersicherung gegen Profis.
- Für strengere Kontrolle: macOS eigene „Bildschirmzeit"-Funktion in den Systemeinstellungen nutzen.

## Deinstallation
```bash
sudo python3 blocker.py unblock   # zuerst entsperren
rm -rf ~/.screentime_blocker
```

## Lizenz
MIT
