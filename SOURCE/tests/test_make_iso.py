"""Tests for make_iso.py - ISO 9660 (+Joliet) round-trip and structure."""

import io
import os
import re
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_floppy
import make_iso
from make_iso import SECTOR, create_iso_image


def make_sample_tree(root):
    files = {}
    files["hello.txt"] = b"Hello, PCem CD!\n"
    files["empty.dat"] = b""
    files["My Long Document Name.txt"] = b"long filename contents"
    files["Gr\xfc\xdfe_\u65e5\u672c.txt"] = "unicode name contents".encode()
    files[os.path.join("docs", "readme.md")] = b"# docs\n"
    files[os.path.join("docs", "nested", "deep.bin")] = bytes(range(256)) * 4
    # Bigger than a whole floppy: proves the ISO path has room.
    files["big.bin"] = os.urandom(5 * 1024 * 1024)
    for rel, data in files.items():
        full = os.path.join(root, rel)
        parent = os.path.dirname(full)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
    os.makedirs(os.path.join(root, "empty_dir"), exist_ok=True)
    return files


def read_sector(path, lba):
    with open(path, "rb") as f:
        f.seek(lba * SECTOR)
        return f.read(SECTOR)


class TestIso(unittest.TestCase):
    def test_roundtrip_joliet(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            files = make_sample_tree(src)
            img = os.path.join(tmp, "disk.iso")
            create_iso_image(src, img, label="TESTCD")

            size = os.path.getsize(img)
            self.assertEqual(size % SECTOR, 0)
            self.assertGreater(size, 5 * 1024 * 1024)

            pvd = read_sector(img, 16)
            self.assertEqual(pvd[0], 1)
            self.assertEqual(pvd[1:6], b"CD001")
            self.assertEqual(pvd[40:72], b"TESTCD" + b" " * 26)
            svd = read_sector(img, 17)
            self.assertEqual(svd[0], 2)
            self.assertEqual(svd[1:6], b"CD001")
            self.assertEqual(svd[88:91], b"%/E")
            self.assertEqual(svd[40:72], "TESTCD".encode("utf-16-be")
                             + b"\x00 " * 10)
            term = read_sector(img, 18)
            self.assertEqual(term[0], 255)
            self.assertEqual(term[1:6], b"CD001")

            listed = {p: (s, d) for p, s, d in
                      make_iso.list_iso_contents(img)}
            for rel, data in files.items():
                arc = rel.replace(os.sep, "/")
                self.assertIn(arc, listed, f"missing {arc}")
                self.assertEqual(listed[arc][0], len(data))
                self.assertFalse(listed[arc][1])
                back = make_iso.read_file_from_iso(img, arc)
                self.assertEqual(back, data, f"content mismatch {arc}")
            for d in ("docs", "docs/nested", "empty_dir"):
                self.assertIn(d, listed)
                self.assertTrue(listed[d][1])

    def test_9660_tree_dos_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            files = make_sample_tree(src)
            img = os.path.join(tmp, "disk.iso")
            create_iso_image(src, img)

            listed = make_iso.list_iso_contents(img, joliet=False)
            # Same file count as the Joliet tree (names differ).
            jol = make_iso.list_iso_contents(img, joliet=True)
            self.assertEqual(len(listed), len(jol))

            # Raw check: 9660 file idents are 8.3 uppercase with ;1 versions.
            pvd = read_sector(img, 16)
            root_ext = struct.unpack_from("<I", pvd, 156 + 2)[0]
            root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
            with open(img, "rb") as f:
                f.seek(root_ext * SECTOR)
                blob = f.read(root_size)
            seen_files = 0
            pos = 0
            pat = re.compile(rb"^[A-Z0-9_]{1,8}(\.[A-Z0-9_]{1,3})?;1$")
            while pos < len(blob):
                if SECTOR - (pos % SECTOR) < 33:
                    pos += SECTOR - (pos % SECTOR)
                    continue
                rec_len = blob[pos]
                if rec_len == 0:
                    pos += SECTOR - (pos % SECTOR)
                    continue
                rec = blob[pos:pos + rec_len]
                fi_len = rec[32]
                ident = bytes(rec[33:33 + fi_len])
                flags = rec[25]
                if ident not in (b"\x00", b"\x01") and not (flags & 0x02):
                    self.assertRegex(ident, pat, f"bad 9660 name {ident!r}")
                    seen_files += 1
                pos += rec_len
            n_root_files = sum(1 for r in files if os.sep not in r)
            self.assertEqual(seen_files, n_root_files)

    def test_both_endian_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            make_sample_tree(src)
            img = os.path.join(tmp, "disk.iso")
            create_iso_image(src, img)
            total = os.path.getsize(img) // SECTOR
            for lba in (16, 17):
                vd = read_sector(img, lba)
                le, be = struct.unpack_from("<I", vd, 80)[0], \
                    struct.unpack_from(">I", vd, 84)[0]
                self.assertEqual(le, be)
                self.assertEqual(le, total)
                self.assertEqual(struct.unpack_from("<H", vd, 128)[0], SECTOR)
                self.assertEqual(struct.unpack_from(">H", vd, 130)[0], SECTOR)
                # Root record extent/size LE == BE.
                self.assertEqual(struct.unpack_from("<I", vd, 158)[0],
                                 struct.unpack_from(">I", vd, 162)[0])
                self.assertEqual(struct.unpack_from("<I", vd, 166)[0],
                                 struct.unpack_from(">I", vd, 170)[0])

    def test_path_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            files = make_sample_tree(src)
            img = os.path.join(tmp, "disk.iso")
            create_iso_image(src, img)
            # Distinct dirs incl. root ("empty_dir" has no files
            # below it, so it must be counted explicitly).
            want_dirs = {"", "docs", "docs/nested", "empty_dir"}

            pvd = read_sector(img, 16)
            pt_size = struct.unpack_from("<I", pvd, 132)[0]
            pt_le = struct.unpack_from("<I", pvd, 140)[0]
            pt_be = struct.unpack_from(">I", pvd, 148)[0]
            with open(img, "rb") as f:
                f.seek(pt_le * SECTOR)
                le_blob = f.read(pt_size)
                f.seek(pt_be * SECTOR)
                be_blob = f.read(pt_size)

            def parse(blob, big_endian):
                recs = []
                pos = 0
                while pos < len(blob):
                    ln = blob[pos]
                    fmt = ">IH" if big_endian else "<IH"
                    extent, parent = struct.unpack_from(fmt, blob, pos + 2)
                    ident = bytes(blob[pos + 8:pos + 8 + ln])
                    recs.append((ident, extent, parent))
                    pos += 8 + ln + (ln % 2)
                return recs

            le_recs = parse(le_blob, False)
            be_recs = parse(be_blob, True)
            self.assertEqual(len(le_recs), len(want_dirs))
            # LE and BE tables mirror each other.
            self.assertEqual(
                [(i, e, p) for i, e, p in le_recs],
                [(i, e, p) for i, e, p in be_recs])
            # Root first, parent numbers sane.
            self.assertEqual(le_recs[0][0], b"\x00")
            self.assertEqual(le_recs[0][2], 1)
            for _ident, _ext, parent in le_recs[1:]:
                self.assertGreaterEqual(parent, 1)
                self.assertLessEqual(parent, len(le_recs))

    def test_name_collision_mangling(self):
        # Direct unit tests: two names differing only by case cannot
        # coexist on case-insensitive filesystems, so exercise the
        # manglers without touching disk.
        existing_jol: set[str] = set()
        a = make_iso.joliet_name("MixCase.dat", existing_jol)
        b = make_iso.joliet_name("MIXCASE.dat", existing_jol)
        self.assertEqual(a, "MixCase.dat")
        self.assertNotEqual(a.casefold(), b.casefold())
        self.assertTrue(b.endswith(".dat"))
        # Long-name truncation collisions also mangle.
        existing_iso: set[tuple[str, str]] = set()
        x = make_iso.iso_short_name("verylongfilename1.txt", existing_iso)
        y = make_iso.iso_short_name("verylongfilename2.txt", existing_iso)
        self.assertNotEqual(x, y)
        self.assertRegex(x.encode(), rb"^[A-Z0-9_]{1,8}(\.[A-Z0-9_]{1,3})?$")
        self.assertRegex(y.encode(), rb"^[A-Z0-9_]{1,8}(\.[A-Z0-9_]{1,3})?$")

    def test_layout_audit(self):
        # From-scratch structural audit, independent of the reader:
        # no record crosses a sector boundary, no extents overlap,
        # everything lies inside the volume, and both trees reference
        # identical file data.
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            make_sample_tree(src)
            img = os.path.join(tmp, "disk.iso")
            create_iso_image(src, img, label="AUDIT")
            with open(img, "rb") as f:
                image = f.read()
            total = len(image) // SECTOR

            def records_in(extent, size):
                recs = []
                for base in range(size // SECTOR):
                    sec = image[(extent + base) * SECTOR:
                                (extent + base + 1) * SECTOR]
                    pos = 0
                    while pos < SECTOR:
                        ln = sec[pos]
                        if ln == 0:
                            break  # padding to end of sector
                        self.assertGreaterEqual(ln, 33)
                        self.assertLessEqual(pos + ln, SECTOR,
                                             "record crosses sector boundary")
                        recs.append(bytes(sec[pos:pos + ln]))
                        pos += ln
                return recs

            intervals = [(0, 16), (16, 1), (17, 1), (18, 1)]  # sys + VDs
            tree_files = []
            for lba in (16, 17):
                vd = image[lba * SECTOR:(lba + 1) * SECTOR]
                pt_size = struct.unpack_from("<I", vd, 132)[0]
                pt_le = struct.unpack_from("<I", vd, 140)[0]
                pt_be = struct.unpack_from(">I", vd, 148)[0]
                pt_sectors = (pt_size + SECTOR - 1) // SECTOR
                intervals += [(pt_le, pt_sectors), (pt_be, pt_sectors)]
                root_ext = struct.unpack_from("<I", vd, 158)[0]
                root_size = struct.unpack_from("<I", vd, 166)[0]
                file_spans = []
                queue = [(root_ext, root_size)]
                seen_dirs = set()
                while queue:
                    ext, size = queue.pop()
                    self.assertNotIn(ext, seen_dirs)
                    seen_dirs.add(ext)
                    self.assertEqual(size % SECTOR, 0)
                    intervals.append((ext, size // SECTOR))
                    for rec in records_in(ext, size):
                        c_ext = struct.unpack_from("<I", rec, 2)[0]
                        c_size = struct.unpack_from("<I", rec, 10)[0]
                        is_dir = bool(rec[25] & 0x02)
                        ident = bytes(rec[33:33 + rec[32]])
                        if ident in (b"\x00", b"\x01"):
                            continue
                        if is_dir:
                            queue.append((c_ext, c_size))
                        else:
                            nsec = max(
                                1, (c_size + SECTOR - 1) // SECTOR)
                            intervals.append((c_ext, nsec))
                            file_spans.append((c_ext, c_size))
                tree_files.append(sorted(file_spans))

            # Both trees point at the same file data.
            self.assertEqual(tree_files[0], tree_files[1])
            self.assertGreater(len(tree_files[0]), 0)

            # All intervals inside the volume, none overlapping
            # (exact duplicates = empty files sharing one zero sector).
            for ext, nsec in intervals:
                self.assertGreaterEqual(ext, 0)
                self.assertLessEqual(ext + nsec, total)
            uniq = sorted(set(intervals))
            for (e1, n1), (e2, _n2) in zip(uniq, uniq[1:]):
                self.assertLessEqual(
                    e1 + n1, e2, f"extents overlap: {(e1, n1)} vs {(e2, _n2)}")

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            img = os.path.join(tmp, "disk.iso")
            create_iso_image(src, img)
            self.assertEqual(make_iso.list_iso_contents(img), [])
            self.assertEqual(read_sector(img, 16)[1:6], b"CD001")
            self.assertEqual(read_sector(img, 18)[0], 255)

    def test_floppy_cli_iso_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "a.txt"), "wb") as f:
                f.write(b"iso via floppy cli")
            img = os.path.join(tmp, "disk.iso")
            import contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    make_floppy.main([src, img, "--iso", "--force"]), 0)
            self.assertTrue(make_iso.is_iso_image(img))
            self.assertEqual(
                make_iso.read_file_from_iso(img, "a.txt"),
                b"iso via floppy cli")
            # --list auto-detects the ISO.
            buf = io.StringIO()
            with redirect_stderr(io.StringIO()):
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(make_floppy.main([img, "--list"]), 0)
            self.assertIn("a.txt", buf.getvalue())
            # --span and --iso are mutually exclusive.
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    make_floppy.main([src, img, "--span", "--iso"])
            self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
