"""Tests for config.py (per-user settings, env-redirected)."""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


class TestConfig(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"APPDATA": tmp}), \
                    mock.patch.object(config.sys, "platform", "win32"):
                self.assertEqual(config.load_output_dir(), "")
                want = os.path.join(tmp, "out here")
                config.save_output_dir(want)
                self.assertEqual(config.load_output_dir(), want)
                config.save_output_dir("   ")
                self.assertEqual(config.load_output_dir(), "")

    def test_missing_and_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"APPDATA": tmp}), \
                    mock.patch.object(config.sys, "platform", "win32"):
                self.assertEqual(config.load_output_dir(), "")
                os.makedirs(os.path.dirname(config.config_path()),
                            exist_ok=True)
                with open(config.config_path(), "w") as f:
                    f.write("[[[ not ini\n")
                self.assertEqual(config.load_output_dir(), "")

    def test_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"APPDATA": tmp}), \
                    mock.patch.object(config.sys, "platform", "win32"):
                self.assertEqual(config.load_language(), "de")
                config.save_language("en")
                self.assertEqual(config.load_language(), "en")
                config.save_language("xx")
                self.assertEqual(config.load_language(), "de")

    def test_keys_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"APPDATA": tmp}), \
                    mock.patch.object(config.sys, "platform", "win32"):
                config.save_output_dir(os.path.join(tmp, "out"))
                config.save_language("en")
                self.assertEqual(config.load_output_dir(),
                                 os.path.join(tmp, "out"))
                self.assertEqual(config.load_language(), "en")
                config.save_output_dir(os.path.join(tmp, "out2"))
                self.assertEqual(config.load_language(), "en")

    def test_xdg_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}), \
                    mock.patch.object(config.sys, "platform", "linux"):
                self.assertEqual(
                    config.config_dir(), os.path.join(tmp, "disc_create"))
