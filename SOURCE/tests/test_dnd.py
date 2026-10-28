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


if __name__ == "__main__":
    unittest.main()
