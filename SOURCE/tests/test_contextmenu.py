"""Tests for contextmenu.py.

Registry logic runs against an in-memory fake (all platforms); a real
HKCU roundtrip runs on Windows when writes are allowed, else skips.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

import contextmenu
from fakewinreg import FakeWinreg

TEST_ROOT = r"Software\DiscCreateMenuTest"


class TestCommand(unittest.TestCase):
    def test_source_mode(self):
        with mock.patch.object(sys, "argv", ["ui.py"]):
            if hasattr(sys, "frozen"):
                self.skipTest("frozen interpreter")
            cmd = contextmenu._command("--context-floppy")
        self.assertIn("--context-floppy", cmd)
        self.assertIn('"%V"', cmd)
        self.assertIn("ui.py", cmd)

    def test_frozen_mode(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable",
                                  r"C:\app\disc_create.exe"):
            cmd = contextmenu._command("--context-iso")
        self.assertEqual(cmd, r'"C:\app\disc_create.exe" --context-iso "%V"')


class FakeRegistryTestCase(unittest.TestCase):
    def setUp(self):
        self._platform_patcher = mock.patch.object(
            contextmenu.sys, "platform", "win32")
        self._platform_patcher.start()
        self.addCleanup(self._platform_patcher.stop)
        self.fake = FakeWinreg()
        self._modules_patcher = mock.patch.dict(
            sys.modules, {"winreg": self.fake})
        self._modules_patcher.start()
        self.addCleanup(self._modules_patcher.stop)


class TestRegistryFake(FakeRegistryTestCase):
    def test_roundtrip(self):
        contextmenu.unregister(TEST_ROOT)
        self.assertFalse(contextmenu.is_registered(TEST_ROOT))
        contextmenu.register(TEST_ROOT)
        self.assertTrue(contextmenu.is_registered(TEST_ROOT))

        with self.fake.OpenKey(self.fake.HKEY_CURRENT_USER,
                               TEST_ROOT + "\\DiscCreateFloppy") as key:
            label, _ = self.fake.QueryValueEx(key, None)
        self.assertEqual(label, "Diskettenabbild hier erstellen")
        with self.fake.OpenKey(self.fake.HKEY_CURRENT_USER,
                               TEST_ROOT + "\\DiscCreateIso\\command") as key:
            cmd, _ = self.fake.QueryValueEx(key, None)
        self.assertIn("--context-iso", cmd)
        self.assertIn('"%V"', cmd)

        contextmenu.register(TEST_ROOT)  # idempotent
        self.assertTrue(contextmenu.is_registered(TEST_ROOT))
        contextmenu.unregister(TEST_ROOT)
        self.assertFalse(contextmenu.is_registered(TEST_ROOT))
        contextmenu.unregister(TEST_ROOT)  # missing is fine
        self.assertFalse(contextmenu.is_registered(TEST_ROOT))

    def test_english_labels(self):
        contextmenu.unregister(TEST_ROOT)
        contextmenu.register(TEST_ROOT, lang="en")
        self.assertTrue(contextmenu.is_registered(TEST_ROOT))
        with self.fake.OpenKey(self.fake.HKEY_CURRENT_USER,
                               TEST_ROOT + "\\DiscCreateFloppy") as key:
            label, _ = self.fake.QueryValueEx(key, None)
        self.assertEqual(label, "Create floppy image here")
        with self.fake.OpenKey(self.fake.HKEY_CURRENT_USER,
                               TEST_ROOT + "\\DiscCreateIso") as key:
            label, _ = self.fake.QueryValueEx(key, None)
        self.assertEqual(label, "Create ISO image here")
        contextmenu.unregister(TEST_ROOT)

    def test_partial_counts_as_missing(self):
        contextmenu.unregister(TEST_ROOT)
        contextmenu.register(TEST_ROOT)
        contextmenu._delete_tree(
            self.fake, TEST_ROOT + "\\DiscCreateIso\\command")
        self.assertFalse(contextmenu.is_registered(TEST_ROOT))

    def test_os_errors_wrapped(self):
        def denied(*a, **k):
            raise PermissionError("denied")
        with mock.patch.object(self.fake, "CreateKey", denied):
            with self.assertRaises(contextmenu.ContextMenuError):
                contextmenu.register(TEST_ROOT)
        with mock.patch.object(self.fake, "OpenKey", denied):
            with self.assertRaises(contextmenu.ContextMenuError):
                contextmenu.is_registered(TEST_ROOT)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class TestRegistryReal(unittest.TestCase):
    def test_roundtrip(self):
        try:
            contextmenu.unregister(TEST_ROOT)
            contextmenu.register(TEST_ROOT)
            self.assertTrue(contextmenu.is_registered(TEST_ROOT))
        except (PermissionError, contextmenu.ContextMenuError) as e:
            raise unittest.SkipTest(f"registry writes blocked: {e}")
        finally:
            try:
                contextmenu.unregister(TEST_ROOT)
            except OSError:
                pass
        self.assertFalse(contextmenu.is_registered(TEST_ROOT))


if __name__ == "__main__":
    unittest.main()
