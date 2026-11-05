"""Tests for vhd.py (floppy -> fixed-VHD wrapper)."""

import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vhd


class TestVhd(unittest.TestCase):
    def test_footer_shape(self):
        footer = vhd.build_footer()
        self.assertEqual(len(footer), 512)
        self.assertEqual(footer[0:8], b"conectix")
        self.assertEqual(footer[48:56], (1474560).to_bytes(8, "big"))
        self.assertEqual(struct.unpack(">HBB", footer[56:60]), (80, 2, 18))
        self.assertEqual(int.from_bytes(footer[60:64], "big"), 2)

    def test_footer_checksum_roundtrip(self):
        self.assertTrue(vhd.verify_footer(vhd.build_footer()))
        bad = bytearray(vhd.build_footer())
        bad[100] ^= 0xFF
        self.assertFalse(vhd.verify_footer(bytes(bad)))
        self.assertFalse(vhd.verify_footer(b"short"))

    def test_lba_to_chs(self):
        self.assertEqual(vhd.lba_to_chs(63), (1, 1, 10))
        self.assertEqual(vhd.lba_to_chs(0), (0, 0, 1))
        c, h, s = vhd.lba_to_chs(63 + 2880 - 1)
        self.assertEqual((c, h, s), (81, 1, 9))

    def test_mbr_shape(self):
        mbr = vhd.build_mbr()
        self.assertEqual(len(mbr), 512)
        self.assertEqual(mbr[510:512], b"\x55\xaa")
        entry = mbr[446:462]
        self.assertEqual(entry[0], 0x80)
        self.assertEqual(entry[4], 0x01)
        self.assertEqual(int.from_bytes(entry[8:12], "little"), 63)
        self.assertEqual(int.from_bytes(entry[12:16], "little"), 2880)
        self.assertEqual(bytes(mbr[462:510]), b"\0" * 48)

    def test_mbr_signature_random(self):
        first = vhd.build_mbr()[0x1B8:0x1BC]
        second = vhd.build_mbr()[0x1B8:0x1BC]
        self.assertEqual(len(first), 4)
        self.assertNotEqual(first, second)

    def test_wrap_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = os.path.join(tmp, "d.img")
            with open(img, "wb") as f:
                f.write(b"F" * vhd.FLOPPY_SIZE)
            out = os.path.join(tmp, "d.vhd")
            vhd.wrap_raw_floppy(img, out)
            off = vhd.PARTITION_START * vhd.SECTOR
            disk = 2952 * vhd.SECTOR
            self.assertEqual(os.path.getsize(out), disk + vhd.FOOTER_SIZE)
            with open(out, "rb") as f:
                blob = f.read()
            self.assertEqual(blob[510:512], b"\x55\xaa")
            self.assertEqual(blob[512:off], b"\0" * (off - 512))
            body = blob[off:off + vhd.FLOPPY_SIZE]
            self.assertEqual(body[:0x1C], b"F" * 0x1C)
            self.assertEqual(body[0x1C:0x20], (63).to_bytes(4, "little"))
            self.assertEqual(body[0x20:], b"F" * (vhd.FLOPPY_SIZE
                                                  - 0x20))
            self.assertEqual(blob[off + vhd.FLOPPY_SIZE:disk],
                             b"\0" * (disk - off - vhd.FLOPPY_SIZE))
            footer = blob[disk:]
            self.assertTrue(vhd.verify_footer(footer))
            self.assertEqual(int.from_bytes(footer[48:56], "big"), disk)
            self.assertEqual(
                struct.unpack(">HBB", footer[56:60]), (82, 2, 18))
            self.assertEqual(82 * 2 * 18 * vhd.SECTOR, disk)

    def test_wrap_other_sizes(self):
        cases = {  # size -> (disk sectors, (cyl, heads, spt))
            368640: (792, (44, 2, 9)),    # 63 + 720 padded to 44x2x9
            737280: (1512, (84, 2, 9)),   # 63 + 1440 padded to 84x2x9
        }
        with tempfile.TemporaryDirectory() as tmp:
            for size, (disk, geo) in cases.items():
                img = os.path.join(tmp, "d.img")
                with open(img, "wb") as f:
                    f.write(b"\0" * size)
                out = os.path.join(tmp, "d.vhd")
                vhd.wrap_raw_floppy(img, out)
                with open(out, "rb") as f:
                    blob = f.read()
                self.assertEqual(len(blob),
                                 disk * vhd.SECTOR + vhd.FOOTER_SIZE)
                self.assertEqual(blob[510:512], b"\x55\xaa")
                self.assertEqual(
                    int.from_bytes(blob[446 + 12:446 + 16], "little"),
                    size // vhd.SECTOR)
                footer = blob[disk * vhd.SECTOR:]
                self.assertTrue(vhd.verify_footer(footer))
                self.assertEqual(struct.unpack(">HBB", footer[56:60]),
                                 geo)

    def test_wrap_rejects_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = os.path.join(tmp, "d.img")
            with open(img, "wb") as f:
                f.write(b"small")
            with self.assertRaises(ValueError):
                vhd.wrap_raw_floppy(img, os.path.join(tmp, "d.vhd"))


if __name__ == "__main__":
    unittest.main()
