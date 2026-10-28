"""Tests for make_floppy.py - round-trip a directory through a FAT12 image."""

import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_floppy
from make_floppy import TOTAL_SIZE, FloppyFullError, create_floppy_image


def make_sample_tree(root):
    files = {}
    files["hello.txt"] = b"Hello, PCem!\n"
    files["empty.dat"] = b""
    files["My Long Document Name.txt"] = b"long filename contents"
    files[os.path.join("docs", "readme.md")] = b"# docs\n"
    files[os.path.join("docs", "nested", "deep.bin")] = bytes(range(256)) * 4
    files[os.path.join("UPPER", "lower.TXT")] = b"case"
    # ~100KB binary to exercise multi-cluster chains
    files["big.bin"] = os.urandom(100 * 1024)
    for rel, data in files.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full) or root, exist_ok=True)
        if os.path.dirname(full):
            os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
    os.makedirs(os.path.join(root, "empty_dir"), exist_ok=True)
    return files


class TestFloppy(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            files = make_sample_tree(src)
            img = os.path.join(tmp, "disk.img")
            create_floppy_image(src, img, label="TESTDISK")

            # Raw geometry checks.
            self.assertEqual(os.path.getsize(img), TOTAL_SIZE)
            with open(img, "rb") as f:
                raw = f.read()
            self.assertEqual(raw[510:512], b"\x55\xaa")
            self.assertEqual(struct.unpack_from("<H", raw, 11)[0], 512)
            self.assertEqual(struct.unpack_from("<H", raw, 17)[0], 224)
            self.assertEqual(struct.unpack_from("<H", raw, 19)[0], 2880)
            self.assertEqual(raw[21], 0xF0)
            self.assertEqual(raw[52:60], b"FAT12   ")
            # Both FAT copies identical.
            fat1 = raw[512:512 + 9 * 512]
            fat2 = raw[512 + 9 * 512:512 + 18 * 512]
            self.assertEqual(fat1, fat2)
            self.assertEqual(fat1[0:3], bytes([0xF0, 0xFF, 0xFF]))

            # Every source file lists and extracts byte-identical.
            listed = {p: (s, d) for p, s, d in make_floppy.list_image_contents(img)}
            for rel, data in files.items():
                arc = rel.replace(os.sep, "/")
                self.assertIn(arc, listed, f"missing {arc}")
                self.assertEqual(listed[arc][0], len(data))
                self.assertFalse(listed[arc][1])
                back = make_floppy.read_file_from_image(img, arc)
                self.assertEqual(back, data, f"content mismatch {arc}")
            # Directories present.
            for d in ("docs", "docs/nested", "UPPER", "empty_dir"):
                self.assertIn(d, listed)
                self.assertTrue(listed[d][1])

    def test_short_name_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            # These all truncate to the same 8.3 base -> need ~1, ~2 mangling.
            names = ["verylongfilename1.txt", "verylongfilename2.txt",
                     "verylongfilename3.txt"]
            for n in names:
                with open(os.path.join(src, n), "wb") as f:
                    f.write(n.encode())
            img = os.path.join(tmp, "disk.img")
            create_floppy_image(src, img)
            for n in names:
                self.assertEqual(make_floppy.read_file_from_image(img, n),
                                 n.encode())

    def test_too_big_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "huge.bin"), "wb") as f:
                f.write(b"x" * (2 * 1024 * 1024))
            img = os.path.join(tmp, "disk.img")
            with self.assertRaises(FloppyFullError):
                create_floppy_image(src, img)

    def test_span_splits_across_volumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            files = {}
            # ~2.1MB over several files -> must span at least 2 floppies.
            for i in range(3):
                files[f"part{i}.bin"] = os.urandom(700 * 1024)
            files[os.path.join("docs", "note.txt")] = b"spanned nested file"
            for rel, data in files.items():
                full = os.path.join(src, rel)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as f:
                    f.write(data)
            img = os.path.join(tmp, "disk.img")
            paths = make_floppy.create_floppy_images(src, img, label="SPAN",
                                                     span=True)
            self.assertGreaterEqual(len(paths), 2)
            self.assertEqual(paths[0], os.path.join(tmp, "disk_1.img"))
            self.assertEqual(paths[1], os.path.join(tmp, "disk_2.img"))
            # Every volume is a valid 1.44MB image ...
            for p in paths:
                self.assertEqual(os.path.getsize(p), TOTAL_SIZE)
                with open(p, "rb") as f:
                    self.assertEqual(f.read()[510:512], b"\x55\xaa")
            # ... and together they hold every file byte-identical.
            remaining = dict(files)
            for p in paths:
                for arc, _size, is_dir in make_floppy.list_image_contents(p):
                    if is_dir:
                        continue
                    rel = arc.replace("/", os.sep)
                    self.assertIn(rel, remaining)
                    back = make_floppy.read_file_from_image(p, arc)
                    self.assertEqual(back, remaining.pop(rel))
            self.assertEqual(remaining, {})

    def test_span_single_volume_keeps_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "small.txt"), "wb") as f:
                f.write(b"tiny")
            img = os.path.join(tmp, "disk.img")
            paths = make_floppy.create_floppy_images(src, img, span=True)
            self.assertEqual(paths, [img])
            self.assertEqual(
                make_floppy.read_file_from_image(img, "small.txt"), b"tiny")

    def test_span_single_file_too_big_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "huge.bin"), "wb") as f:
                f.write(b"x" * (2 * 1024 * 1024))
            img = os.path.join(tmp, "disk.img")
            with self.assertRaises(FloppyFullError):
                make_floppy.create_floppy_images(src, img, span=True)


if __name__ == "__main__":
    unittest.main()
