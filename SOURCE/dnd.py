"""Drag & drop files/folders onto the window (Windows only, stdlib only).

tkinter has no built-in drop support, so this uses the classic
WM_DROPFILES message via ctypes. The message goes to the window under
the cursor, hence the toplevel *and all its descendants* are registered
with DragAcceptFiles and subclassed with one shared window procedure.
Dropped paths reach the app through ``after_idle``, i.e. on the UI
thread. enable() is a no-op returning False off Windows.
"""

from __future__ import annotations

import sys

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4


def _lresult():
    """LRESULT type (LONG_PTR); wintypes has none to offer."""
    import ctypes

    return ctypes.c_ssize_t

#: toplevel hwnd -> state dict (keeps ctypes callbacks alive, old
#: window procedures for restore on destroy).
_active: dict[int, dict] = {}


def _query_paths(shell32, hdrop) -> list[str]:
    """File paths from a WM_DROPFILES handle (then DragFinish it)."""
    import ctypes
    from ctypes import wintypes

    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, ctypes.c_uint,
                                      wintypes.LPWSTR, ctypes.c_uint]
    shell32.DragQueryFileW.restype = ctypes.c_uint
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

    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                        ctypes.c_void_p]
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                      wintypes.UINT, wintypes.WPARAM,
                                      wintypes.LPARAM]
    user32.CallWindowProcW.restype = _lresult()
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

    wins: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_child(h, _lp):
        wins.append(h)
        return True

    user32.EnumChildWindows(hwnd, _enum_child, 0)
    wins.append(hwnd)

    olds: dict[int, int] = {}
    pending: list[str] = []
    scheduled = False

    def _drain():
        nonlocal scheduled
        paths, pending[:] = pending[:], []
        scheduled = False
        if paths:
            callback(paths)

    @ctypes.WINFUNCTYPE(_lresult(), wintypes.HWND, wintypes.UINT,
                        wintypes.WPARAM, wintypes.LPARAM)
    def _wndproc(h, msg, wp, lp):
        nonlocal scheduled
        if msg == WM_DROPFILES:
            paths = _query_paths(shell32, wp)
            if paths:
                pending.extend(paths)
                if not scheduled:
                    scheduled = True
                    top.after_idle(_drain)
            return 0
        return user32.CallWindowProcW(olds.get(h), h, msg, wp, lp)

    for h in wins:
        olds[h] = user32.GetWindowLongPtrW(h, GWLP_WNDPROC)
        user32.SetWindowLongPtrW(h, GWLP_WNDPROC,
                                 ctypes.cast(_wndproc, ctypes.c_void_p))
        shell32.DragAcceptFiles(h, True)

    def _cleanup(event=None):
        if event is not None and event.widget is not top:
            return  # Destroy fires for children too
        state = _active.pop(hwnd, None)
        if state is None:
            return
        for h, old in state["olds"].items():
            try:
                user32.SetWindowLongPtrW(h, GWLP_WNDPROC, old)
                shell32.DragAcceptFiles(h, False)
            except Exception:
                pass  # window already gone

    top.bind("<Destroy>", _cleanup, add="+")
    _active[hwnd] = {"olds": olds, "proc": _wndproc, "enum": _enum_child}
    return True
