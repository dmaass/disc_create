[Deutsch](#deutsch) | [English](#english)

# disc_create v1.0

## Deutsch

Ordner-zu-Disketten-/CD-Abbild für PCem.

Ein Verzeichnis (alle Dateien und Unterverzeichnisse) in Abbilder
packen, die sich direkt in PCem einbinden lassen: 1,44-MB-FAT12-
Disketten (`.img`) oder ISO-9660-CD-ROMs (`.iso`). Keine
Abhängigkeiten — reine Python-Standardbibliothek.

### Dieses Paket

- `SOURCE/` — die Python-Quellen (`make_floppy.py`, `make_iso.py`,
  `ui.py`), die Test-Suite und `build_exe.bat` zum Neubauen der Exe.
  Das plus die Doku lebt in Git.
- `BINARY/` — `disc_create.exe`: UI per Doppelklick für 64-Bit-Windows,
  kein Python nötig. **Nicht in Git** — Release-Archive enthalten sie,
  und sie wird als GitHub-Release-Asset veröffentlicht.
- `LICENSE`, `CHANGELOG.md`

Veröffentlicht am 28.10.2026. Die Release-Exe ist aus dem `SOURCE/`-
Snapshot in diesem Paket gebaut (PyInstaller-Einzeldatei-Build).

### Schnellstart (ohne Python)

1. `disc_create.exe` aus den GitHub Releases laden — oder aus `BINARY/`
   starten, wenn ein vollständiges Release-Archiv vorliegt. (Windows
   SmartScreen warnt ggf. vor der unsignierten App → „Weitere
   Informationen → Trotzdem ausführen".)
2. Quellordner wählen (oder einen aufs Fenster ziehen), Diskette /
   mehrteilig / ISO wählen, **Abbild erstellen** klicken. **Abbild
   auflisten** inspiziert beliebige `.img`/`.iso` (oder ein Abbild aufs
   Fenster ziehen).

### Schnellstart (Python 3.10+)

```bat
python SOURCE\ui.py                              :: Desktop-UI
python SOURCE\make_floppy.py my_files disk.img   :: 1,44-MB-Diskette
python SOURCE\make_floppy.py my_files disk.img --span   :: auf N Disketten aufteilen
python SOURCE\make_floppy.py big disk.iso --iso  :: CD-Abbild
python SOURCE\make_iso.py big disk.iso           :: dasselbe, direktes Werkzeug
python SOURCE\make_floppy.py disk.img --list     :: inspizieren (erkennt Typ automatisch)
```

Tests ausführen (47 Tests, keine Abhängigkeiten):

```bat
cd SOURCE
python -m unittest discover -s tests -v
```

### Einbinden in PCem

- **Diskette:** das `.img` als Laufwerk A: einbinden (3,5" 1,44M) — es
  erscheint als `A:`. Funktioniert auch in 86Box, DOSBox-X
  (`imgmount a disk.img -t floppy`), QEMU (`-fda disk.img`),
  VirtualBox.
- **CD:** das `.iso` an ein ATAPI-CD-ROM-Laufwerk hängen. Im Gast
  read-only (Dateien per Diskette *aus* dem Gast holen); DOS-Gäste
  brauchen erst einen ATAPI-Treiber + `MSCDEX.EXE`, Windows 95+ geht
  nativ.

### Hinweise & Grenzen

- Diskette: FAT12, max. 224 Wurzeleinträge (große Bäume per `--span`
  aufteilen oder `--iso` für große Inhalte). Lange Namen bleiben via
  LFN erhalten; schlichtes DOS sieht 8.3-Kurznamen. Zeitstempel bleiben
  erhalten.
- ISO: DOS-sicherer 8.3-Namensbaum für MSCDEX + Joliet-Unicode-Baum für
  Windows, teilen sich dieselben Daten. Daten-CD (nicht bootfähig).
  Einzelne Dateien bis 4 GB − 1; Namen bis 64 Zeichen (Joliet).
- Symlinks auf Dateien werden gefolgt; andere Spezialdateien werden mit
  Warnung übersprungen.

### Exe neu bauen

```bat
cd SOURCE
build_exe.bat
```

Braucht Python und einmal `pip install pyinstaller` (das erledigt das
Skript). Ergebnis landet in `SOURCE\dist\disc_create.exe`.

### Credits

Mit KI-Unterstützung entwickelt: Muse Code (powered by Muse Spark).

Homepage: <https://www.good-old-stuff.de/downloads-software/disc_create/>

### Lizenz

MIT — siehe `LICENSE`.

## English

Folder to floppy / CD image for PCem.

Pack a directory (all files and subdirectories) into images that mount
directly in PCem: 1.44MB FAT12 floppies (`.img`) or ISO 9660 CD-ROMs
(`.iso`). No dependencies — pure Python standard library.

### This package

- `SOURCE/` — the Python source (`make_floppy.py`, `make_iso.py`,
  `ui.py`), the test suite, and `build_exe.bat` to rebuild the exe.
  This plus the docs is what lives in git.
- `BINARY/` — `disc_create.exe`: double-click UI for 64-bit Windows,
  no Python needed. **Not tracked in git** — release archives carry
  it, and it is published as a GitHub Release asset.
- `LICENSE`, `CHANGELOG.md`

Released 2026-10-28. The release exe is built from the `SOURCE/`
snapshot in this package (PyInstaller one-file build).

### Quick start (no Python)

1. Download `disc_create.exe` from GitHub Releases — or run it from
   `BINARY/` if you have a full release archive. (Windows SmartScreen
   may warn about the unsigned app → "More info → Run anyway".)
2. Pick a source folder (or drop one onto the window), choose
   floppy / multi-volume / ISO, click **Create image**. **List image**
   inspects any `.img`/`.iso` (or drop an image onto the window).

### Quick start (Python 3.10+)

```bat
python SOURCE\ui.py                              :: desktop UI
python SOURCE\make_floppy.py my_files disk.img   :: 1.44MB floppy
python SOURCE\make_floppy.py my_files disk.img --span   :: split over N floppies
python SOURCE\make_floppy.py big disk.iso --iso  :: CD image
python SOURCE\make_iso.py big disk.iso           :: same, direct tool
python SOURCE\make_floppy.py disk.img --list     :: inspect (auto-detects type)
```

Run the tests (47 tests, no dependencies):

```bat
cd SOURCE
python -m unittest discover -s tests -v
```

### Mounting in PCem

- **Floppy:** attach the `.img` as drive A: (3.5" 1.44M) — it appears
  as `A:`. Also works in 86Box, DOSBox-X
  (`imgmount a disk.img -t floppy`), QEMU (`-fda disk.img`), VirtualBox.
- **CD:** attach the `.iso` to an ATAPI CD-ROM drive. Read-only in the
  guest (use floppies to get files *out* of the guest); DOS guests
  need an ATAPI driver + `MSCDEX.EXE` first, Windows 95+ works natively.

### Notes & limits

- Floppy: FAT12, max 224 root entries (use `--span` to split large
  trees, or `--iso` for big content). Long names preserved via LFN;
  plain DOS sees 8.3 short names. Timestamps preserved.
- ISO: DOS-safe 8.3 name tree for MSCDEX + Joliet Unicode tree for
  Windows, sharing the same data. Data disc (not bootable).
  Single files up to 4GB − 1; names up to 64 chars (Joliet).
- Symlinks pointing to files are followed; other special files
  are skipped with a warning.

### Rebuilding the exe

```bat
cd SOURCE
build_exe.bat
```

Needs Python and one `pip install pyinstaller` (the script does that).
Output lands in `SOURCE\dist\disc_create.exe`.

### Credits

Developed with AI assistance using Muse Code (powered by Muse Spark).

Homepage: <https://www.good-old-stuff.de/downloads-software/disc_create/>

### License

MIT — see `LICENSE`.
