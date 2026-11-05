[Deutsch](#deutsch) | [English](#english)

# Changelog

## Deutsch

### v1.2 — 05.11.2026

- Neu: „Abbild bereitstellen" bindet ISOs direkt bzw.
  Diskettenabbilder (360/720 KB, 1,2/1,44/2,88 MB) über einen
  temporären
  VHD-Wrapper als Laufwerk ein und öffnet es im Explorer (nur
  Windows, Admin-Bestätigung erforderlich); getrennt wird per
  Auswerfen im Explorer.
- Der Programmstart räumt eigene alte Temp-Dateien (VHD-Wrapper)
  weg.
- Bereitstellen: Laufwerk wird nötigenfalls online geschaltet und
  bekommt zuverlässig einen Buchstaben (eindeutige Disk-Signatur
  je Wrapper, echte Wiederholung der Abfrage).
- Test-Suite: 69 Tests.

### v1.1 — 30.10.2026

- Behoben: Absturz beim Droppen aufs Fenster (Drops werden jetzt per
  Polling abgeholt statt per UI-Callback aus der Fensternachricht).
- Behoben: Bei jeder neuen Quellwahl wird der Ausgabe-Vorschlag jetzt
  aktualisiert (zuvor nur bei leerem Ausgabefeld).
- Neu: Visual-Studio-Projekt (`disc_create.sln` / `disc_create.pyproj`)
  zum Öffnen, Debuggen und Testen.
- Robuster: Drag-&-Drop ignoriert unerwartete Systemantworten
  (statt abzustürzen) und prüft Drop-Handles vorab; die Drop-Kette
  wird per simulierter WM_DROPFILES-Nachricht getestet.
- Test-Suite: 49 Tests.

### v1.0 — 28.10.2026

Erste Veröffentlichung.

- `make_floppy.py`: Verzeichnis → 1,44-MB-FAT12-`.img` (lange
  LFN-Namen, Zeitstempel bleiben erhalten); `--span` verteilt zu großen
  Inhalt auf nummerierte Disketten; `--iso` schreibt stattdessen ein
  CD-Abbild; `--list` inspiziert Abbilder (erkennt Diskette vs. ISO
  automatisch).
- `make_iso.py`: Verzeichnis → ISO-9660-+Joliet-`.iso` (DOS-sicherer
  8.3-Baum plus Unicode-Langnamenbaum, gemeinsame Dateidaten).
- `ui.py`: tkinter-Desktop-UI über allem (erstellen + auflisten),
  zweisprachig (Deutsch/Englisch), mit Drag & Drop,
  Fortschrittsbalken, Standard-Ausgabeordner und
  Ein-Klick-Explorer-Kontextmenü.
- `BINARY/disc_create.exe`: PyInstaller-Einzeldatei-Windows-Build
  der UI.
- unittest-Suite mit 47 Tests: Roundtrips, Spanning, ISO-Struktur und
  Pfadtabellen, Namens-Mangling, UI-Logik, Config, Kontextmenü, i18n.

## English

### v1.2 — 2026-11-05

- New: "Mount image" mounts ISOs directly, or floppy images
  (360K/720K/1.2M/1.44M/2.88M) via a temporary VHD wrapper, as
  a drive
  and opens it in Explorer (Windows only, admin approval required);
  unmount by ejecting the drive in Explorer.
- Startup cleans up our old temp files (VHD wrappers).
- Mounting: the drive is brought online if needed and reliably gets
  a letter (unique disk signature per wrapper, real query retries).
- Test suite: 69 tests.

### v1.1 — 2026-10-30

- Fixed: crash when dropping onto the window (drops are now collected
  by polling instead of a UI callback from the window procedure).
- Fixed: picking a new source now always refreshes the suggested output
  (previously only when the output field was empty).
- New: Visual Studio project (`disc_create.sln` / `disc_create.pyproj`)
  for opening, debugging, and testing.
- Hardened: drag & drop ignores unexpected system responses instead
  of crashing, and validates drop handles up front; the drop chain is
  tested with a synthetic WM_DROPFILES message.
- Test suite: 49 tests.

### v1.0 — 2026-10-28

First release.

- `make_floppy.py`: directory → 1.44MB FAT12 `.img` (LFN long names,
  timestamps preserved); `--span` splits oversized content across
  numbered floppies; `--iso` writes a CD image instead; `--list`
  inspects images (auto-detects floppy vs. ISO).
- `make_iso.py`: directory → ISO 9660 + Joliet `.iso` (DOS-safe 8.3
  tree plus Unicode long-name tree, shared file data).
- `ui.py`: tkinter desktop UI over all of the above (create + list),
  bilingual (German/English), with drag & drop, a progress bar, a
  default output folder, and one-click Explorer context-menu setup.
- `BINARY/disc_create.exe`: PyInstaller one-file Windows build of the UI.
- 47-test unittest suite: round-trips, spanning, ISO structure and
  path tables, name mangling, UI logic, config, context menu, i18n.
