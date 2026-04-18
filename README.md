# Screentime Blocker (macOS)

Ein einfaches Python-Programm, mit dem du **Websites** (z. B. `youtube.com`) und **Apps** auf deinem Mac blockieren kannst. Entsperrt wird nur mit einem selbst festgelegten **Code**.

> Für macOS. Nutzt `/etc/hosts` zum Blockieren von Websites und einen Hintergrund-Daemon, der blockierte Apps beim Start sofort wieder beendet.

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

## Installation
```bash
git clone <repo-url>
cd screentime-blocker
chmod +x blocker.py
```

## Nutzung

### 1. Einrichten (Code, Websites, Apps festlegen)
```bash
python3 blocker.py setup
```
Du wirst nach einem Code sowie der Liste an Websites und Apps gefragt.

### 2. Blockierung aktivieren
```bash
sudo python3 blocker.py block
```

### 3. Blockierung aufheben (mit Code)
```bash
sudo python3 blocker.py unblock
```

### 4. Status anzeigen
```bash
python3 blocker.py status
```

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
