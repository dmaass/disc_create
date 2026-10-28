"""Tests for ui.py logic (no display needed; widgets are not tested)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import ui
except ImportError as e:
    raise unittest.SkipTest(f"tkinter unavailable: {e}")


class TestUiLogic(unittest.TestCase):
    def test_suggest_output(self):
        src = os.path.join("some", "dir", "my_files")
        self.assertTrue(ui.suggest_output(src, "floppy").endswith(
            os.path.join("my_files.img")))
        self.assertTrue(ui.suggest_output(src, "span").endswith(
            os.path.join("my_files.img")))
        self.assertTrue(ui.suggest_output(src, "iso").endswith(
            os.path.join("my_files.iso")))

    def test_build_floppy_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "a.txt"), "wb") as f:
                f.write(b"ui floppy")
            out = os.path.join(tmp, "disk.img")
            paths = ui.build_image(src, out, "floppy", "UILABEL", False)
            self.assertEqual(paths, [out])
            text = ui.list_image_text(out)
            self.assertIn("a.txt", text)
            # Refuses to overwrite without force.
            with self.assertRaises(FileExistsError):
                ui.build_image(src, out, "floppy", "", False)
            self.assertEqual(
                ui.build_image(src, out, "floppy", "", True), [out])

    def test_build_span(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            for name in ("p1.bin", "p2.bin"):
                with open(os.path.join(src, name), "wb") as f:
                    f.write(b"x" * (800 * 1024))
            out = os.path.join(tmp, "disk.img")
            paths = ui.build_image(src, out, "span", "", True)
            self.assertEqual(len(paths), 2)
            for p in paths:
                self.assertIn("p", ui.list_image_text(p))

    def test_build_iso(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "Long Name Here.txt"), "wb") as f:
                f.write(b"ui iso")
            out = os.path.join(tmp, "disk.iso")
            self.assertEqual(ui.build_image(src, out, "iso", "UICD", False),
                             [out])
            self.assertIn("Long Name Here.txt", ui.list_image_text(out))

    def test_list_clears_old_content(self):
        try:
            app = ui.App()
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, "src")
                os.makedirs(src)
                with open(os.path.join(src, "a.txt"), "wb") as f:
                    f.write(b"x")
                out = os.path.join(tmp, "disk.img")
                ui.build_image(src, out, "floppy", "", True)
                app._log("STALE LISTING MARKER")
                app._show_listing(out)
                content = app.log.get("1.0", "end")
                self.assertNotIn("STALE LISTING MARKER", content)
                self.assertIn("a.txt", content)
        finally:
            app.destroy()

    def test_parse_startup_args(self):
        self.assertEqual(ui.parse_startup_args([]), ("gui", None))
        self.assertEqual(ui.parse_startup_args(["--register-context"]),
                         ("register", None))
        self.assertEqual(ui.parse_startup_args(["--unregister-context"]),
                         ("unregister", None))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ui.parse_startup_args([tmp]), ("gui", tmp))
            self.assertEqual(ui.parse_startup_args(["--context-floppy", tmp]),
                             ("context", ("floppy", tmp)))
            self.assertEqual(ui.parse_startup_args(["--context-iso", tmp]),
                             ("context", ("iso", tmp)))
            with self.assertRaises(ValueError):
                ui.parse_startup_args([os.path.join(tmp, "nope")])
        with self.assertRaises(ValueError):
            ui.parse_startup_args(["--bogus"])
        with self.assertRaises(ValueError):
            ui.parse_startup_args(["--context-floppy"])
        with self.assertRaises(ValueError):
            ui.parse_startup_args(["a", "b"])

    def test_effective_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "my_files")
            os.makedirs(src)
            outdir = os.path.join(tmp, "images")
            self.assertEqual(
                ui.effective_output(src, os.path.join(tmp, "y.img"),
                                    "floppy", outdir),
                os.path.join(tmp, "y.img"))
            self.assertEqual(
                ui.effective_output(src, "", "floppy", outdir),
                os.path.join(outdir, "my_files.img"))
            self.assertEqual(
                ui.effective_output(src, "  ", "iso", ""),
                os.path.join(tmp, "my_files.iso"))
            self.assertEqual(
                ui.suggest_output(src, "iso", outdir),
                os.path.join(outdir, "my_files.iso"))

    def test_run_context_action(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "a.txt"), "wb") as f:
                f.write(b"ctx")
            outdir = os.path.join(tmp, "out")
            with mock.patch.dict(os.environ, {"APPDATA": tmp}), \
                    mock.patch.object(ui.config.sys, "platform", "win32"):
                ui.config.save_output_dir(outdir)
                paths = ui.run_context_action("floppy", src)
                self.assertEqual(len(paths), 1)
                self.assertTrue(paths[0].startswith(outdir))
                self.assertEqual(os.path.getsize(paths[0]), 1474560)
                with self.assertRaises(FileExistsError):
                    ui.run_context_action("floppy", src)

    def test_app_preselect(self):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, "src")
                os.makedirs(src)
                app = ui.App(preselect=src)
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            self.assertEqual(app.source_var.get(), src)
            self.assertTrue(app.output_var.get().endswith("src.img"))
        finally:
            app.destroy()

    def test_app_loads_outdir(self):
        from unittest import mock
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch.dict(os.environ, {"APPDATA": tmp}), \
                        mock.patch.object(ui.config.sys, "platform", "win32"):
                    ui.config.save_output_dir(os.path.join(tmp, "cfg-out"))
                    app = ui.App()
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            self.assertEqual(app.outdir_var.get(),
                             os.path.join(tmp, "cfg-out"))
        finally:
            app.destroy()

    def test_apply_language_retranslates(self):
        try:
            app = ui.App()
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            self.assertEqual(app._homepage.cget("text"), ui.HOMEPAGE)
            ui.lang.set_language("en")
            app._apply_language()
            self.assertEqual(app.create_btn.cget("text"), "Create image")
            self.assertEqual(app.status_var.get(), "Ready.")
            ui.lang.set_language("de")
            app._apply_language()
            self.assertEqual(app.create_btn.cget("text"),
                             "Abbild erstellen")
            self.assertEqual(app.status_var.get(), "Bereit.")
        finally:
            ui.lang.set_language("de")
            app.destroy()

    def test_route_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            img = os.path.join(tmp, "disk.img")
            with open(img, "wb") as f:
                f.write(b"x")
            txt = os.path.join(tmp, "note.txt")
            with open(txt, "wb") as f:
                f.write(b"x")
            source, image, ignored = ui.route_dropped(
                [txt, src, img, os.path.join(tmp, "missing")])
            self.assertEqual(source, src)
            self.assertEqual(image, img)
            self.assertEqual(ignored, [txt, os.path.join(tmp, "missing")])
            self.assertEqual(ui.route_dropped([]), (None, None, []))

    def test_progress_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "a.txt"), "wb") as f:
                f.write(b"0123456789")
            calls = []
            out = os.path.join(tmp, "disk.iso")
            ui.build_image(src, out, "iso", "", True,
                           progress=lambda d, t: calls.append((d, t)))
            self.assertTrue(calls)
            self.assertEqual(calls[-1], (10, 10))
            for (d, t) in calls:
                self.assertLessEqual(d, t)
            calls.clear()
            out2 = os.path.join(tmp, "disk.img")
            ui.build_image(src, out2, "floppy", "", True,
                           progress=lambda d, t: calls.append((d, t)))
            self.assertEqual(calls, [(1, 1)])

    def test_on_drop_sets_source_and_lists(self):
        try:
            app = ui.App()
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            with tempfile.TemporaryDirectory() as tmp:
                src = os.path.join(tmp, "src")
                os.makedirs(src)
                with open(os.path.join(src, "a.txt"), "wb") as f:
                    f.write(b"x")
                img = os.path.join(tmp, "disk.img")
                ui.build_image(src, img, "floppy", "", True)
                app._on_drop([src])
                self.assertEqual(app.source_var.get(), src)
                self.assertTrue(app.output_var.get().endswith(".img"))
                app._on_drop([img])
                self.assertIn("a.txt", app.log.get("1.0", "end"))
                app._on_drop([os.path.join(src, "a.txt")])
                self.assertIn(os.path.join(src, "a.txt"),
                              app.log.get("1.0", "end"))
        finally:
            app.destroy()

    def test_build_bad_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                ui.build_image(os.path.join(tmp, "missing"),
                               os.path.join(tmp, "o.img"), "floppy", "", True)


if __name__ == "__main__":
    unittest.main()
