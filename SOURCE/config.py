"""Per-user configuration (default output directory).

Stored as INI: %APPDATA%\\disc_create\\config.ini on Windows,
~/Library/Application Support/disc_create on macOS,
~/.config/disc_create (XDG_CONFIG_HOME) elsewhere.
"""

from __future__ import annotations

import configparser
import os
import sys

SECTION = "general"
KEY_OUTPUT_DIR = "output_dir"
KEY_LANGUAGE = "language"

DEFAULT_LANGUAGE = "de"
LANGUAGES = ("de", "en")


def config_dir() -> str:
    """Platform config dir for disc_create (not created as a side effect)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "disc_create")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", "disc_create")
    base = os.environ.get("XDG_CONFIG_HOME") \
        or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "disc_create")


def config_path() -> str:
    """Full path of config.ini (may not exist yet)."""
    return os.path.join(config_dir(), "config.ini")


def _read_section() -> configparser.SectionProxy:
    """Current [general] settings (empty when missing/unreadable)."""
    cp = configparser.ConfigParser()
    try:
        cp.read(config_path(), encoding="utf-8")
    except (OSError, configparser.Error):
        pass
    if SECTION not in cp:
        cp[SECTION] = {}
    return cp[SECTION]


def load_output_dir() -> str:
    """Configured default output dir, or "" when unset/unreadable."""
    try:
        return _read_section().get(KEY_OUTPUT_DIR, fallback="").strip()
    except configparser.Error:
        return ""


def _save(settings: dict[str, str]) -> None:
    """Persist *settings* into [general], keeping existing keys.

    May raise OSError.
    """
    cp = configparser.ConfigParser()
    try:
        cp.read(config_path(), encoding="utf-8")
    except (OSError, configparser.Error):
        cp = configparser.ConfigParser()
    if SECTION not in cp:
        cp[SECTION] = {}
    for key, value in settings.items():
        cp[SECTION][key] = value
    os.makedirs(config_dir(), exist_ok=True)
    with open(config_path(), "w", encoding="utf-8") as f:
        cp.write(f)


def save_output_dir(path: str) -> None:
    """Persist the default output dir ("" clears it). May raise OSError."""
    _save({KEY_OUTPUT_DIR: path.strip()})


def load_language() -> str:
    """Configured UI language ("de"/"en"), German when unset/invalid."""
    code = _read_section().get(KEY_LANGUAGE, fallback="").strip().lower()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def save_language(code: str) -> None:
    """Persist the UI language (invalid codes become German).

    May raise OSError.
    """
    code = (code or "").strip().lower()
    _save({KEY_LANGUAGE: code if code in LANGUAGES else DEFAULT_LANGUAGE})
