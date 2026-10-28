"""Bilingual UI strings (German/English).

Default language is German; the UI offers a dropdown to switch, and the
choice is persisted via :mod:`config`. Use :func:`t` for every
user-visible string so both languages stay complete (tests enforce that
both dicts carry the same keys).
"""

from __future__ import annotations

#: Language codes in display order, mapped to their (untranslated) names.
LANGS = {"de": "Deutsch", "en": "English"}

DEFAULT = "de"

_current = DEFAULT

STRINGS = {
    "de": {
        "status_ready": "Bereit.",
        "status_working": "Arbeite...",
        "lbl_source": "Quellordner:",
        "lbl_output": "Ausgabedatei:",
        "lbl_outdir": "Ausgabeordner:",
        "lbl_format": "Format:",
        "lbl_label": "Name:",
        "lbl_context": "Kontextmenü:",
        "lbl_language": "Sprache:",
        "btn_browse": "Durchsuchen...",
        "btn_clear": "Leeren",
        "btn_install": "Installieren",
        "btn_remove": "Entfernen",
        "btn_create": "Abbild erstellen",
        "btn_list": "Abbild auflisten...",
        "chk_overwrite": "Vorhandene Dateien überschreiben",
        "fmt_floppy": "Diskette 1,44 MB (.img)",
        "fmt_span": "Disketten mehrteilig (.img)",
        "fmt_iso": "CD-Abbild (.iso)",
        "log_frame": "Protokoll",
        "dlg_source_title": "Quellordner wählen",
        "dlg_outdir_title": "Standard-Ausgabeordner wählen",
        "dlg_output_title": "Ausgabedatei wählen",
        "dlg_list_title": "Abbild zum Auflisten wählen",
        "ftype_iso": "ISO-Abbilder",
        "ftype_floppy": "Diskettenabbilder",
        "ftype_images": "Abbilder",
        "ftype_all": "Alle Dateien",
        "err_failed": "Fehlgeschlagen",
        "err_cannot_save": "Einstellung kann nicht gespeichert werden: {detail}",
        "err_bad_outdir": "Ungültiger Ausgabeordner: {detail}",
        "err_missing_input": "Eingabe fehlt",
        "err_choose_source": "Bitte einen Quellordner wählen.",
        "err_not_a_dir": "Quelle ist kein Ordner: {path}",
        "err_output_exists": "Ausgabe existiert bereits: {path}",
        "err_usage": ("Unbekannte Argumente: {args}\n"
                      "Aufruf: ui.py [Quellordner] [--register-context | "
                      "--unregister-context | --context-floppy ORDNER | "
                      "--context-iso ORDNER]"),
        "usage_title": "Aufruf",
        "ctx_windows_only": "Nur Windows",
        "ctx_unavailable": "nicht verfügbar",
        "ctx_installed": "installiert",
        "ctx_not_installed": "nicht installiert",
        "ctx_title": "Kontextmenü",
        "ctx_installed_msg": "Für Ordner installiert:\n{floppy}\n{iso}",
        "ctx_removed_msg": "entfernt",
        "ctx_cli_installed": "Kontextmenü installiert",
        "ctx_cli_removed": "Kontextmenü entfernt",
        "log_creating": "Erstelle {output} aus {source} ...",
        "log_wrote": "{path} geschrieben ({size} Bytes)",
        "log_error": "Fehler: {detail}",
        "log_drop_ignored": "Ignoriert (kein Ordner/Abbild): {path}",
        "done_title": "Fertig",
        "done_created": "Erstellt:\n{paths}",
        "list_dir": "VERZ ",
        "list_file": "DATEI",
        "list_empty": "(leeres Abbild)",
    },
    "en": {
        "status_ready": "Ready.",
        "status_working": "Working...",
        "lbl_source": "Source folder:",
        "lbl_output": "Output file:",
        "lbl_outdir": "Output folder:",
        "lbl_format": "Format:",
        "lbl_label": "Label:",
        "lbl_context": "Context menu:",
        "lbl_language": "Language:",
        "btn_browse": "Browse...",
        "btn_clear": "Clear",
        "btn_install": "Install",
        "btn_remove": "Remove",
        "btn_create": "Create image",
        "btn_list": "List image...",
        "chk_overwrite": "Overwrite existing files",
        "fmt_floppy": "Floppy 1.44MB (.img)",
        "fmt_span": "Floppy multi-volume (.img)",
        "fmt_iso": "CD image (.iso)",
        "log_frame": "Log",
        "dlg_source_title": "Choose source folder",
        "dlg_outdir_title": "Choose default output folder",
        "dlg_output_title": "Choose output file",
        "dlg_list_title": "Choose image to list",
        "ftype_iso": "ISO images",
        "ftype_floppy": "Floppy images",
        "ftype_images": "Images",
        "ftype_all": "All files",
        "err_failed": "Failed",
        "err_cannot_save": "cannot save setting: {detail}",
        "err_bad_outdir": "bad output folder: {detail}",
        "err_missing_input": "Missing input",
        "err_choose_source": "Please choose a source folder.",
        "err_not_a_dir": "source is not a directory: {path}",
        "err_output_exists": "output already exists: {path}",
        "err_usage": ("unrecognized arguments: {args}\n"
                      "usage: ui.py [source_dir] [--register-context | "
                      "--unregister-context | --context-floppy DIR | "
                      "--context-iso DIR]"),
        "usage_title": "Usage",
        "ctx_windows_only": "Windows only",
        "ctx_unavailable": "unavailable",
        "ctx_installed": "installed",
        "ctx_not_installed": "not installed",
        "ctx_title": "Context menu",
        "ctx_installed_msg": "installed for folders:\n{floppy}\n{iso}",
        "ctx_removed_msg": "removed",
        "ctx_cli_installed": "context menu installed",
        "ctx_cli_removed": "context menu removed",
        "log_creating": "Creating {output} from {source} ...",
        "log_wrote": "wrote {path} ({size} bytes)",
        "log_error": "error: {detail}",
        "log_drop_ignored": "Ignored (not a folder/image): {path}",
        "done_title": "Done",
        "done_created": "Created:\n{paths}",
        "list_dir": "DIR ",
        "list_file": "FILE",
        "list_empty": "(empty image)",
    },
}


def set_language(code: str) -> str:
    """Select the UI language; unknown codes fall back to German.

    Returns the effective code.
    """
    global _current
    code = (code or "").strip().lower()
    _current = code if code in STRINGS else DEFAULT
    return _current


def get_language() -> str:
    """Current UI language code ("de" or "en")."""
    return _current


def t(key: str, **kwargs) -> str:
    """Translate *key*, formatting with *kwargs*.

    Falls back to English, then to the key itself, so the UI never
    crashes on a missing entry (tests still enforce key parity).
    """
    text = STRINGS[_current].get(key, STRINGS["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text
