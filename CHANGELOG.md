[Deutsch](#deutsch) | [English](#english)

# Changelog

## Deutsch

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
