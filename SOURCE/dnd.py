"""Drag & drop files/folders onto the window (Windows only, stdlib only).

tkinter has no built-in drop support, so this uses the classic
WM_DROPFILES message via ctypes. The message goes to the window under
the cursor, hence the toplevel *and all its descendants* are registered
with DragAcceptFiles and subclassed with one shared window procedure.
Dropped paths are stashed and collected by poll() from the normal event
loop. enable() is a no-op returning False off Windows.
"""

from __future__ import annotations

import sys

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4


def _lresult():
    """LRESULT type (LONG_PTR); wintypes has none to offer."""
    import ctypes

    return ctypes.c_ssize_t

#: toplevel hwnd -> state dict (callback, pending drops, old window
#: procedures, ctypes objects kept alive, subclassed windows).
_active: dict[int, dict] = {}

#: every subclassed window (toplevel + descendants) -> its toplevel.
_owners: dict[int, int] = {}


def poll() -> None:
    """Deliver pending drops to their callbacks. Call from the UI thread.

    The window procedure must not touch tkinter (see note there), so
    drops wait here until the event loop collects them.
    """
    for state in list(_active.values()):
        paths, state["pending"][:] = state["pending"][:], []
        if paths:
            state["callback"](paths)


def _query_paths(shell32, hdrop) -> list[str]:
    """File paths from a WM_DROPFILES handle (then DragFinish it).

    Invalid handles are ignored (never passed to DragQueryFile).
    """
    import ctypes
    from ctypes import wintypes

    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, ctypes.c_uint,
                                      wintypes.LPWSTR, ctypes.c_uint]
    shell32.DragQueryFileW.restype = ctypes.c_uint
    shell32.DragFinish.argtypes = [wintypes.HANDLE]
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalFlags.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFlags.restype = wintypes.UINT
    if kernel32.GlobalFlags(hdrop) & 0x8000:  # GMEM_INVALID_HANDLE
        return []
    paths = []
    count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
    for i in range(count):
        size = shell32.DragQueryFileW(hdrop, i, None, 0)
        buf = ctypes.create_unicode_buffer(size + 1)
        shell32.DragQueryFileW(hdrop, i, buf, size + 1)
        paths.append(buf.value)
    shell32.DragFinish(hdrop)
    return paths


def enable(widget, callback) -> bool:
    """Accept drops onto the widget's toplevel.

    Calls ``callback(paths: list[str])`` on the UI thread for every
    drop. Returns True when installed, False when unsupported
    (non-Windows). Idempotent per toplevel.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    top = widget.winfo_toplevel()
    hwnd = top.winfo_id()
    if hwnd in _active:
        return True

    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                        ctypes.c_void_p]
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                      wintypes.UINT, wintypes.WPARAM,
                                      wintypes.LPARAM]
    user32.CallWindowProcW.restype = _lresult()
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = _lresult()
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

    wins: list[int] = []

    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                 wintypes.LPARAM)
    user32.EnumChildWindows.argtypes = [wintypes.HWND, ENUMPROC,
                                       wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL

    @ENUMPROC
    def _enum_child(h, _lp):
        wins.append(h)
        return True

    user32.EnumChildWindows(hwnd, _enum_child, 0)
    wins.append(hwnd)

    olds: dict[int, int] = {}
    pending: list[str] = []

    @ctypes.WINFUNCTYPE(_lresult(), wintypes.HWND, wintypes.UINT,
                        wintypes.WPARAM, wintypes.LPARAM)
    def _wndproc(h, msg, wp, lp):
        # Never let anything escape: a dead drop beats a dead app.
        # NOTE: no tkinter calls here (no after_idle/event_generate)!
        # Real drops arrive via cross-process SendMessage while tkinter
        # runs with the GIL released; any Tk C call from this context
        # corrupts the GIL state and kills the process with a
        # PyEval_RestoreThread fatal error. Drops are stashed and
        # collected by poll() from the normal event loop instead.
        # (Same-thread tests can't reproduce that fatal.)
        try:
            if msg == WM_DROPFILES:
                try:
                    paths = _query_paths(shell32, wp)
                except Exception:
                    return 0
                try:
                    state = _active.get(_owners.get(h, -1))
                    if paths and state is not None:
                        state["pending"].extend(paths)
                except Exception:
                    pass
                return 0
        except Exception:
            pass
        old = olds.get(h)
        if old:
            return user32.CallWindowProcW(old, h, msg, wp, lp)
        return user32.DefWindowProcW(h, msg, wp, lp)

    for h in wins:
        olds[h] = user32.GetWindowLongPtrW(h, GWLP_WNDPROC)
        user32.SetWindowLongPtrW(h, GWLP_WNDPROC,
                                 ctypes.cast(_wndproc, ctypes.c_void_p))
        shell32.DragAcceptFiles(h, True)
        _owners[h] = hwnd

    def _cleanup(event=None):
        if event is not None and event.widget is not top:
            return  # Destroy fires for children too
        state = _active.pop(hwnd, None)
        if state is None:
            return
        for h in state["wins"]:
            _owners.pop(h, None)
        for h, old in state["olds"].items():
            try:
                user32.SetWindowLongPtrW(h, GWLP_WNDPROC, old)
                shell32.DragAcceptFiles(h, False)
            except Exception:
                pass  # window already gone

    top.bind("<Destroy>", _cleanup, add="+")
    _active[hwnd] = {"callback": callback, "pending": pending,
                     "olds": olds, "wins": wins,
                     "proc": _wndproc, "enum": _enum_child}
    return True
