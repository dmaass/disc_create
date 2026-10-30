"""Tests for dnd.py (drop support; real drops need a window + user)."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dnd


class TestDnd(unittest.TestCase):
    def test_noop_off_windows(self):
        widget = mock.Mock()
        with mock.patch.object(dnd.sys, "platform", "linux"):
            self.assertFalse(dnd.enable(widget, mock.Mock()))
        widget.winfo_toplevel.assert_not_called()


def _make_hdrop(paths):
    """DROPFILES handle (as Explorer builds it) for *paths*."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    class DROPFILES(ctypes.Structure):
        _fields_ = [("pFiles", wintypes.DWORD),
                    ("pt", wintypes.POINT),
                    ("fNC", wintypes.BOOL),
                    ("fWide", wintypes.BOOL)]

    blob = ("\0".join(paths) + "\0\0").encode("utf-16-le")
    header = DROPFILES(ctypes.sizeof(DROPFILES), wintypes.POINT(0, 0),
                       False, True)
    data = bytes(header) + blob
    handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
    dest = kernel32.GlobalLock(handle)
    ctypes.memmove(dest, data, len(data))
    kernel32.GlobalUnlock(handle)
    return handle


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class TestDropMessage(unittest.TestCase):
    def test_drop_reaches_app(self):
        """Synthetic WM_DROPFILES lands in the app (toplevel + child).

        Drops are collected by dnd.poll() from the event loop (never
        via after_idle from the window procedure: real cross-process
        drops arrive with the GIL released, and any Tk call from that
        context kills the process with a PyEval_RestoreThread fatal).
        Same-thread delivery can't reproduce that fatal, so this test
        covers the mechanism, and real drops are user-tested.
        """
        import ctypes
        import tempfile
        from ctypes import wintypes

        try:
            import ui
            app = ui.App()
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            self.assertIn(app.winfo_id(), dnd._active)
            user32 = ctypes.windll.user32
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                            wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = wintypes.LPARAM
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, "src")
                os.makedirs(src)
                with open(os.path.join(src, "a.txt"), "wb") as f:
                    f.write(b"x")
                # Drop a folder onto the toplevel: becomes the source.
                user32.SendMessageW(app.winfo_id(), dnd.WM_DROPFILES,
                                    _make_hdrop([src]), 0)
                app.update()
                app._poll_jobs()  # collect (as the event loop would)
                self.assertEqual(app.source_var.get(), src)
                self.assertTrue(app.output_var.get().endswith(".img"))
                # Unicode names survive the WCHAR round-trip.
                usrc = os.path.join(tmp, "Grüße_🎃")
                os.makedirs(usrc)
                user32.SendMessageW(app.winfo_id(), dnd.WM_DROPFILES,
                                    _make_hdrop([usrc]), 0)
                app.update()
                app._poll_jobs()
                self.assertEqual(app.source_var.get(), usrc)
                # Drop an image onto a child widget: gets listed.
                img = os.path.join(tmp, "disk.img")
                ui.build_image(src, img, "floppy", "", True)
                child = app._btn_list.winfo_id()
                self.assertNotEqual(child, app.winfo_id())
                user32.SendMessageW(child, dnd.WM_DROPFILES,
                                    _make_hdrop([img]), 0)
                app.update()
                app._poll_jobs()
                self.assertIn("a.txt", app.log.get("1.0", "end"))
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
