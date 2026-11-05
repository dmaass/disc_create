"""Minimal fixed-VHD wrapper so Windows can mount raw floppy images.

Layout: MBR with one FAT12 partition (the raw image starts at sector
63, like on a USB stick), then a 512-byte VHD footer (the "conectix"
cookie, sizes, geometry, checksum, ...). Windows rejects partitionless
images ("not initialized"), hence the MBR. Standard sizes 360K, 720K,
1.2M, 1.44M and 2.88M are supported.
"""

from __future__ import annotations

import os
import random
import time
import uuid

FLOPPY_SIZE = 1474560
FOOTER_SIZE = 512
SECTOR = 512
PARTITION_START = 63  # classic MBR offset, in sectors
#: Raw floppy sizes we can wrap: size -> (cylinders, heads, sectors).
FLOPPY_GEOMETRIES = {
    368640: (40, 2, 9),
    737280: (80, 2, 9),
    1228800: (80, 2, 15),
    1474560: (80, 2, 18),
    2949120: (80, 2, 36),
}
_COOKIE = b"conectix"


def lba_to_chs(lba: int, heads: int = 2, spt: int = 18,
               ) -> tuple[int, int, int]:
    """LBA sector number -> clamped (cylinder, head, sector) tuple."""
    cyl, rem = divmod(lba, heads * spt)
    head, sec = divmod(rem, spt)
    return min(cyl, 1023), min(head, 255), min(sec + 1, 63)


def build_mbr(part_start: int = PARTITION_START,
              part_sectors: int = FLOPPY_SIZE // SECTOR,
              heads: int = 2, spt: int = 18) -> bytes:
    """512-byte MBR with a single bootable FAT12 partition.

    The disk signature (0x1B8) is random so concurrently mounted
    wrappers never collide (Windows takes duplicate-signature disks
    offline).
    """
    mbr = bytearray(SECTOR)
    mbr[0x1B8:0x1BC] = random.randbytes(4)
    entry = bytearray(16)
    entry[0] = 0x80
    c, h, s = lba_to_chs(part_start, heads, spt)
    entry[1:4] = bytes((h, s | ((c >> 8) << 6), c & 0xFF))
    entry[4] = 0x01  # FAT12
    c, h, s = lba_to_chs(part_start + part_sectors - 1, heads, spt)
    entry[5:8] = bytes((h, s | ((c >> 8) << 6), c & 0xFF))
    entry[8:12] = part_start.to_bytes(4, "little")
    entry[12:16] = part_sectors.to_bytes(4, "little")
    mbr[446:462] = entry
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


def build_footer(disk_size: int = FLOPPY_SIZE,
                 cylinders: int = 80, heads: int = 2,
                 sectors: int = 18) -> bytes:
    """Build a 512-byte fixed-VHD footer for a raw disk of *disk_size*."""
    footer = bytearray(FOOTER_SIZE)
    footer[0:8] = _COOKIE
    footer[8:12] = (2).to_bytes(4, "big")  # features
    footer[12:16] = (0x00010000).to_bytes(4, "big")  # file format version
    footer[16:24] = (0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")  # data offset
    footer[24:28] = int(time.time() - 946684800).to_bytes(4, "big")
    footer[28:32] = b"dcsc"  # creator application
    footer[32:36] = (0x00010000).to_bytes(4, "big")  # creator version
    footer[36:40] = b"Wi2k"  # creator OS (Windows)
    footer[40:48] = disk_size.to_bytes(8, "big")  # original size
    footer[48:56] = disk_size.to_bytes(8, "big")  # current size
    footer[56:58] = cylinders.to_bytes(2, "big")
    footer[58] = heads
    footer[59] = sectors
    footer[60:64] = (2).to_bytes(4, "big")  # disk type: fixed
    # checksum at 64:68 stays zero while summing
    footer[68:84] = uuid.uuid4().bytes
    footer[84] = 0  # saved state
    total = sum(footer)
    footer[64:68] = (~total & 0xFFFFFFFF).to_bytes(4, "big")
    return bytes(footer)


def verify_footer(footer: bytes) -> bool:
    """True when *footer* is a consistent 512-byte VHD footer."""
    if len(footer) != FOOTER_SIZE or footer[0:8] != _COOKIE:
        return False
    stored = int.from_bytes(footer[64:68], "big")
    return stored == (~sum(footer[:64] + footer[68:]) & 0xFFFFFFFF)


def wrap_raw_floppy(img_path: str, vhd_path: str) -> None:
    """Embed a raw floppy image (at sector 63) in a fixed VHD.

    Writes MBR + padding + image (with the BPB hidden-sectors field
    patched to the partition offset) + padding + VHD footer. The disk
    is padded to exact CHS geometry. Raises ValueError when the image
    is not a standard floppy size (360K/720K/1.2M/1.44M/2.88M),
    OSError on I/O errors.
    """
    with open(img_path, "rb") as f:
        image = bytearray(f.read())
    geo = FLOPPY_GEOMETRIES.get(len(image))
    if geo is None:
        raise ValueError(
            f"unsupported floppy size {len(image)} bytes "
            f"(want 360K/720K/1.2M/1.44M/2.88M): {img_path}")
    _, heads, spt = geo
    image[0x1C:0x20] = PARTITION_START.to_bytes(4, "little")
    data_sectors = PARTITION_START + len(image) // SECTOR
    per_cyl = heads * spt
    total = -(-data_sectors // per_cyl) * per_cyl
    with open(vhd_path, "wb") as dst:
        dst.write(build_mbr(part_sectors=len(image) // SECTOR,
                            heads=heads, spt=spt))
        dst.write(b"\0" * (PARTITION_START * SECTOR - SECTOR))
        dst.write(image)
        dst.write(b"\0" * (total - data_sectors) * SECTOR)
        dst.write(build_footer(disk_size=total * SECTOR,
                               cylinders=total // per_cyl,
                               heads=heads, sectors=spt))
