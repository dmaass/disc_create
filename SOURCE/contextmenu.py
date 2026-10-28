"""Windows Explorer context-menu verbs (per-user, no admin needed).

Registers "Create floppy image here" / "Create ISO image here" on
directories. Works from the frozen exe as well as from source.
"""

from __future__ import annotations

import os
import sys

VERB_ROOT = r"Software\Classes\Directory\shell"
#: Verb id -> ({"de": ..., "en": ...} labels, context flag).
VERBS = {
    "DiscCreateFloppy": ({"de": "Diskettenabbild hier erstellen",
                          "en": "Create floppy image here"},
                         "--context-floppy"),
    "DiscCreateIso": ({"de": "ISO-Abbild hier erstellen",
                       "en": "Create ISO image here"},
                      "--context-iso"),
}


class ContextMenuError(Exception):
    """Raised for any context-menu problem (incl. non-Windows use)."""


def _winreg():
    """winreg module, or ContextMenuError off Windows (import is lazy)."""
    if sys.platform != "win32":
        raise ContextMenuError("context menu is only supported on Windows")
    import winreg
    return winreg


def _command(flag: str) -> str:
    """Registry command line: exe + flag + "%V" (frozen) or python + script (source)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {flag} "%V"'
    script = os.path.abspath(sys.argv[0])
    return f'"{sys.executable}" "{script}" {flag} "%V"'


def _delete_tree(wr, subkey: str) -> None:
    """Recursively delete a registry key (missing keys are fine)."""
    try:
        with wr.OpenKey(wr.HKEY_CURRENT_USER, subkey, 0,
                        wr.KEY_READ | wr.KEY_WRITE) as key:
            children = []
            i = 0
            while True:
                try:
                    children.append(wr.EnumKey(key, i))
                    i += 1
                except OSError:
                    break
        for child in children:
            _delete_tree(wr, f"{subkey}\\{child}")
        wr.DeleteKey(wr.HKEY_CURRENT_USER, subkey)
    except FileNotFoundError:
        pass


def verb_label(verb: str, lang: str) -> str:
    """Display label for *verb* in language *lang* ("de"/"en")."""
    labels = VERBS[verb][0]
    return labels.get(lang, labels["en"])


def register(root: str = VERB_ROOT, lang: str = "de") -> None:
    """Create both verbs (idempotent; re-run after moving the exe).

    Labels follow *lang*; re-run to switch languages.
    """
    wr = _winreg()
    try:
        for verb, (_, flag) in VERBS.items():
            with wr.CreateKey(wr.HKEY_CURRENT_USER, f"{root}\\{verb}") as key:
                wr.SetValueEx(key, None, 0, wr.REG_SZ,
                              verb_label(verb, lang))
            with wr.CreateKey(wr.HKEY_CURRENT_USER, f"{root}\\{verb}\\command") as key:
                wr.SetValueEx(key, None, 0, wr.REG_SZ, _command(flag))
    except OSError as e:
        raise ContextMenuError(f"cannot write registry: {e}") from e


def unregister(root: str = VERB_ROOT) -> None:
    """Remove both verbs (missing keys are fine)."""
    wr = _winreg()
    try:
        for verb in VERBS:
            _delete_tree(wr, f"{root}\\{verb}")
    except OSError as e:
        raise ContextMenuError(f"cannot write registry: {e}") from e


def is_registered(root: str = VERB_ROOT) -> bool:
    """True only when both verbs with commands are present."""
    wr = _winreg()
    for verb in VERBS:
        try:
            with wr.OpenKey(wr.HKEY_CURRENT_USER, f"{root}\\{verb}\\command") as key:
                value, _ = wr.QueryValueEx(key, None)
        except FileNotFoundError:
            return False
        except OSError as e:
            raise ContextMenuError(f"cannot read registry: {e}") from e
        if not value:
            return False
    return True
