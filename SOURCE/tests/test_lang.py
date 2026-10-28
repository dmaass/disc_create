"""Tests for lang.py (bilingual UI strings)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lang


class TestLang(unittest.TestCase):
    def tearDown(self):
        lang.set_language("de")

    def test_default_is_german(self):
        lang.set_language("de")
        self.assertEqual(lang.get_language(), "de")
        self.assertEqual(lang.t("btn_create"), "Abbild erstellen")

    def test_switch_to_english(self):
        lang.set_language("en")
        self.assertEqual(lang.t("btn_create"), "Create image")
        lang.set_language("de")
        self.assertEqual(lang.t("btn_create"), "Abbild erstellen")

    def test_unknown_code_falls_back_to_german(self):
        self.assertEqual(lang.set_language("fr"), "de")
        self.assertEqual(lang.set_language(""), "de")
        self.assertEqual(lang.get_language(), "de")

    def test_key_parity(self):
        self.assertEqual(set(lang.STRINGS["de"]), set(lang.STRINGS["en"]))

    def test_format_and_missing_key(self):
        lang.set_language("en")
        self.assertIn("/tmp/x", lang.t("err_not_a_dir", path="/tmp/x"))
        self.assertEqual(lang.t("no_such_key"), "no_such_key")


if __name__ == "__main__":
    unittest.main()
