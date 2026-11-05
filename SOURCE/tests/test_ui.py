"""Tests for ui.py logic (no display needed; widgets are not tested)."""

import contextlib
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

    def test_browse_source_resets_output(self):
        from unittest import mock
        try:
            app = ui.App()
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            with tempfile.TemporaryDirectory() as tmp:
                src1 = os.path.join(tmp, "one")
                src2 = os.path.join(tmp, "two")
                os.makedirs(src1)
                os.makedirs(src2)
                with mock.patch.object(ui.filedialog, "askdirectory",
                                       return_value=src1):
                    app._browse_source()
                self.assertEqual(app.source_var.get(), src1)
                self.assertTrue(app.output_var.get().endswith("one.img"))
                app.output_var.set(os.path.join(tmp, "custom.img"))
                with mock.patch.object(ui.filedialog, "askdirectory",
                                       return_value=src2):
                    app._browse_source()
                self.assertEqual(app.source_var.get(), src2)
                self.assertTrue(app.output_var.get().endswith("two.img"))
        finally:
            app.destroy()

    def test_mount_target(self):
        self.assertEqual(ui.mount_target("d.iso"), "iso")
        self.assertEqual(ui.mount_target("D.ISO"), "iso")
        self.assertEqual(ui.mount_target("d.img"), "floppy")
        self.assertEqual(ui.mount_target("d.txt"), "error")
        self.assertEqual(ui.mount_target("noext"), "error")

    def test_mount_iso_mocked(self):
        from unittest import mock
        runs = [mock.Mock(stdout="True\n"), mock.Mock(stdout="E\n")]
        with mock.patch.object(ui.os, "startfile", create=True) as sf, \
                mock.patch.object(ui.subprocess, "run",
                                  side_effect=runs):
            self.assertEqual(ui.mount_iso("x.iso"), "E:")
            sf.assert_called_once_with("x.iso")
        with mock.patch.object(ui.os, "startfile", create=True), \
                mock.patch.object(ui.subprocess, "run",
                                  return_value=mock.Mock(stdout="\n")), \
                mock.patch.object(ui.time, "sleep"):
            with self.assertRaises(OSError):
                ui.mount_iso("x.iso")
            self.assertIsNone(ui._mounted_letter("x.iso", tries=2,
                                                 delay=0))

    def test_elevated_args_quoting(self):
        args = ui._elevated_args("Do-Thing -Path 'a b''c'",
                                 "C:\\t\\r e s.txt")
        self.assertIn("-ExecutionPolicy Bypass", args)
        self.assertIn("Do-Thing -Path 'a b''c'", args)
        self.assertIn("Out-File -FilePath 'C:\\t\\r e s.txt'", args)
        # Only the outer -Command "..." pair: inner double quotes
        # would break parsing and hang waiting for the result file.
        self.assertEqual(args.count('"'), 2)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_elevated_args_execute_probe(self):
        import shutil
        import subprocess
        if shutil.which("powershell") is None:
            raise unittest.SkipTest("no powershell")
        with tempfile.TemporaryDirectory() as tmp:
            res = os.path.join(tmp, "res.txt")
            open(res, "w").close()
            args = ui._elevated_args("'OK:' + 'probe-42'", res)
            subprocess.run("powershell.exe " + args, timeout=60)
            with open(res, encoding="utf-8-sig") as f:
                self.assertEqual(ui._parse_elevated_result(f.read()),
                                 (True, "probe-42"))
            # ...while inner double quotes really do break the call.
            res2 = os.path.join(tmp, "res2.txt")
            open(res2, "w").close()
            bad = ('-NoProfile -ExecutionPolicy Bypass -Command '
                   '"try { \'OK:\' + "x" } catch { } | Out-File '
                   f"-FilePath '{res2}' -Encoding utf8 -NoNewline\"")
            subprocess.run("powershell.exe " + bad, timeout=60)
            with open(res2, encoding="utf-8-sig") as f:
                self.assertNotEqual(
                    ui._parse_elevated_result(f.read()), (True, "x"))

    def test_parse_elevated_result(self):
        self.assertEqual(ui._parse_elevated_result("OK:E"), (True, "E"))
        self.assertEqual(ui._parse_elevated_result("OK:\n"), (True, ""))
        self.assertEqual(ui._parse_elevated_result("ERR:denied"),
                         (False, "denied"))
        self.assertEqual(ui._parse_elevated_result("garbage")[0], False)
        self.assertEqual(ui._parse_elevated_result("")[0], False)
        # Cmdlet chatter above the marker must not confuse the parser.
        blob = ("Attached : True\nBlockSize : 0\nSize : 1511424\nOK:F\n")
        self.assertEqual(ui._parse_elevated_result(blob), (True, "F"))
        blob = "OK:F\nSome-Object : 1\nERR:late failure\n"
        self.assertEqual(ui._parse_elevated_result(blob),
                         (False, "late failure"))

    def test_mount_floppy_mocked(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            img = os.path.join(tmp, "d.img")
            with open(img, "wb") as f:
                f.write(b"\0" * 1474560)
            with mock.patch.object(ui, "_run_elevated",
                                   return_value=(True, "F")) as run:
                vhd_path, letter = ui.mount_floppy(img)
            try:
                self.assertEqual(letter, "F:")
                self.assertTrue(vhd_path.endswith(".vhd"))
                self.assertEqual(os.path.getsize(vhd_path),
                                 82 * 2 * 18 * 512 + 512)
            finally:
                os.unlink(vhd_path)
            self.assertIn("Mount-DiskImage", run.call_args[0][0])
            with mock.patch.object(ui, "_run_elevated",
                                   return_value=(False, "denied")):
                with self.assertRaises(OSError):
                    ui.mount_floppy(img)

    def test_mount_floppy_bad_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = os.path.join(tmp, "d.img")
            with open(img, "wb") as f:
                f.write(b"small")
            with self.assertRaises(ValueError):
                ui.mount_floppy(img)

    def test_mount_thread_posts_result(self):
        from unittest import mock
        try:
            app = ui.App()
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            with mock.patch.object(ui, "mount_iso", return_value="E:"):
                app._mount_thread("iso", "x.iso")
            self.assertEqual(app.jobs.get_nowait(),
                             ("mounted", "iso", "x.iso", None, "E:"))
            with mock.patch.object(ui, "mount_iso",
                                   side_effect=OSError("nope")):
                app._mount_thread("iso", "x.iso")
            kind, err = app.jobs.get_nowait()
            self.assertEqual(kind, "mount_error")
            self.assertIsInstance(err, OSError)
            app._finish_job(("mounted", "iso", "x.iso", None, "E:"))
            content = app.log.get("1.0", "end")
            self.assertIn("E:", content)
            self.assertIn("x.iso", content)
            with mock.patch.object(ui.messagebox,
                                   "showerror") as errbox:
                app._finish_job(("mount_error", OSError("plain-msg")))
            text = errbox.call_args[0][1]
            self.assertIn("plain-msg", text)
            self.assertNotIn("OSError", text)
            with mock.patch.object(ui.os, "startfile",
                                   create=True) as sf:
                app._finish_job(("mounted", "iso", "y.iso", None, "G:"))
                sf.assert_called_once_with("G:\\")
                app._finish_job(("mounted", "iso", "z.iso", None, None))
                sf.assert_called_once()  # no letter: no Explorer
        finally:
            app.destroy()

    def test_mount_floppy_letter_script(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            img = os.path.join(tmp, "d.img")
            with open(img, "wb") as f:
                f.write(b"\0" * 1474560)
            with mock.patch.object(ui.vhd, "wrap_raw_floppy") as wrap, \
                    mock.patch.object(ui, "_run_elevated",
                                      return_value=(True, "E")) as elev:
                vhd_path, letter = ui.mount_floppy(img)
            try:
                self.assertEqual(letter, "E:")
                wrap.assert_called_once_with(img, vhd_path)
                cmd = elev.call_args[0][0]
                self.assertIn("Mount-DiskImage", cmd)
                self.assertIn("Set-Disk", cmd)
                self.assertIn("NewDriveLetter", cmd)
                self.assertIn("Get-Partition", cmd)
                self.assertNotIn('"', cmd)  # breaks elevated wrapping
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(vhd_path)

    def test_cleanup_temp_files(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            names = ["other.txt", "disc_create_abc.vhd",
                     "disc_create_el_xyz", "disc_create_notes.txt"]
            for name in names:
                with open(os.path.join(tmp, name), "w") as f:
                    f.write("x")
            with mock.patch.object(ui.tempfile, "gettempdir",
                                   return_value=tmp):
                removed = ui.cleanup_temp_files()
            self.assertEqual(removed, 2)
            left = sorted(os.listdir(tmp))
            self.assertEqual(left, ["disc_create_notes.txt", "other.txt"])
            # Locked files (still attached) are silently skipped.
            with open(os.path.join(tmp, "disc_create_abc.vhd"),
                      "w") as f:
                f.write("x")
            with mock.patch.object(ui.tempfile, "gettempdir",
                                   return_value=tmp), \
                    mock.patch.object(ui.os, "unlink",
                                      side_effect=OSError("locked")):
                self.assertEqual(ui.cleanup_temp_files(), 0)

    def test_on_mount_floppy(self):
        from unittest import mock

        class SyncThread:
            def __init__(self, target, args=(), daemon=None):
                self._target = target
                self._args = args

            def start(self):
                self._target(*self._args)

            def is_alive(self):
                return False

        try:
            app = ui.App()
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            with tempfile.TemporaryDirectory() as tmp:
                img = os.path.join(tmp, "d.img")
                with open(img, "wb") as f:
                    f.write(b"x")
                fake_vhd = os.path.join(tmp, "d.vhd")
                with mock.patch.object(ui.filedialog, "askopenfilename",
                                       return_value=img), \
                        mock.patch.object(ui, "mount_floppy",
                                          return_value=(fake_vhd, "E:")), \
                        mock.patch.object(ui.threading, "Thread",
                                          SyncThread):
                    app._on_mount()
                app._poll_jobs()
                content = app.log.get("1.0", "end")
                self.assertIn(img, content)
                self.assertIn("E:", content)
        finally:
            app.destroy()

    def test_on_mount_needs_windows(self):
        from unittest import mock
        try:
            app = ui.App()
        except Exception as e:
            raise unittest.SkipTest(f"no display: {e}")
        try:
            app.withdraw()
            with mock.patch.object(ui.sys, "platform", "linux"), \
                    mock.patch.object(ui.messagebox, "showinfo") as info, \
                    mock.patch.object(ui.filedialog,
                                      "askopenfilename") as dlg:
                app._on_mount()
            info.assert_called_once()
            dlg.assert_not_called()
        finally:
            app.destroy()

    def test_build_bad_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                ui.build_image(os.path.join(tmp, "missing"),
                               os.path.join(tmp, "o.img"), "floppy", "", True)


if __name__ == "__main__":
    unittest.main()
