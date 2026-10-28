#!/usr/bin/env python3
"""Create a 1.44MB FAT12 floppy image from a directory.

The output is a raw 1474560-byte image (.img) that mounts directly
as a floppy disk in PCem (and most other emulators / VMs).

Pure standard library, works on Windows / Linux / macOS::

    python make_floppy.py <source_dir> <output.img> [--label LABEL] [--span]
    python make_floppy.py <source_dir> <output.iso> --iso

Features:
  - FAT12 formatting with valid BPB (80 tracks, 2 heads, 18 spt)
  - Recursive files + subdirectories
  - 8.3 short names with automatic ~1 mangling
  - VFAT long filename (LFN) entries so long names survive
  - File timestamps preserved from source files
"""

from __future__ import annotations

import argparse
import datetime
import os
import random
import struct
import sys

import contextmenu
import make_iso

# ---------------------------------------------------------------------------
# Floppy geometry (standard 1.44MB 3.5" HD floppy)
# ---------------------------------------------------------------------------
BYTES_PER_SECTOR = 512
SECTORS_PER_CLUSTER = 1
RESERVED_SECTORS = 1
NUM_FATS = 2
ROOT_ENTRIES = 224
TOTAL_SECTORS = 2880
MEDIA_DESCRIPTOR = 0xF0
SECTORS_PER_FAT = 9
SECTORS_PER_TRACK = 18
HEADS = 2

TOTAL_SIZE = TOTAL_SECTORS * BYTES_PER_SECTOR  # 1474560
FAT_OFFSET = RESERVED_SECTORS * BYTES_PER_SECTOR
ROOT_OFFSET = (RESERVED_SECTORS + NUM_FATS * SECTORS_PER_FAT) * BYTES_PER_SECTOR
DATA_OFFSET = ROOT_OFFSET + ROOT_ENTRIES * 32
DATA_CLUSTERS = (TOTAL_SECTORS - (RESERVED_SECTORS + NUM_FATS * SECTORS_PER_FAT
                                  + ROOT_ENTRIES * 32 // BYTES_PER_SECTOR))
# Clusters are numbered starting at 2.
FIRST_CLUSTER = 2
LAST_CLUSTER = FIRST_CLUSTER + DATA_CLUSTERS - 1  # 2848
FAT_ENTRY_COUNT = SECTORS_PER_FAT * BYTES_PER_SECTOR * 2 // 3  # 3072

FAT_FREE = 0x000
FAT_EOC = 0xFFF  # end-of-chain marker we write

ENTRIES_PER_CLUSTER = BYTES_PER_SECTOR * SECTORS_PER_CLUSTER // 32  # 16

ATTR_READONLY = 0x01
ATTR_HIDDEN = 0x02
ATTR_SYSTEM = 0x04
ATTR_VOLUME = 0x08
ATTR_DIR = 0x10
ATTR_ARCHIVE = 0x20
ATTR_LFN = 0x0F


class FloppyError(Exception):
    """Base error for floppy creation problems."""


class FloppyFullError(FloppyError):
    """Raised when content does not fit on the 1.44MB image."""


# ---------------------------------------------------------------------------
# Helpers: DOS date/time, short names, LFN
# ---------------------------------------------------------------------------

def dos_date_time(timestamp: float | None = None) -> tuple[int, int]:
    """Return (dos_date, dos_time) for a POSIX timestamp (local time)."""
    if timestamp is None:
        dt = datetime.datetime.now()
    else:
        dt = datetime.datetime.fromtimestamp(timestamp)
    year = max(1980, min(dt.year, 2107)) - 1980
    date = ((year & 0x7F) << 9) | ((dt.month & 0x0F) << 5) | (dt.day & 0x1F)
    time = ((dt.hour & 0x1F) << 11) | ((dt.minute & 0x3F) << 5) | ((dt.second // 2) & 0x1F)
    return date, time


_VALID_SHORT_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789$%'-_@~`!(){}^#&")
_RESERVED_BASES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _sanitize_component(text: str) -> str:
    """Uppercase and replace characters illegal in 8.3 names with '_'."""
    out = []
    for ch in text.upper():
        if ch in _VALID_SHORT_CHARS:
            out.append(ch)
        # Dots inside a component are dropped (they only separate base/ext).
        elif ch == ".":
            continue
        else:
            out.append("_")
    return "".join(out)


def generate_short_name(long_name: str, existing: set[tuple[str, str]]) -> tuple[bytes, str, bool]:
    """Generate an 8.3 short name for *long_name*.

    *existing* holds (base, ext) tuples already used in this directory
    (uppercased, unpadded). Returns (short_11_bytes, dotted_name, need_lfn).
    """
    # Strip leading/trailing spaces and dots like Windows does.
    stripped = long_name.strip(" .")
    if not stripped:
        stripped = "FILE"
    if "." in stripped:
        base_raw, ext_raw = stripped.rsplit(".", 1)
    else:
        base_raw, ext_raw = stripped, ""
    if not base_raw:
        base_raw = "FILE"

    base = _sanitize_component(base_raw)
    ext = _sanitize_component(ext_raw)
    if not base:
        base = "_"

    def dotted(b: str, e: str) -> str:
        return f"{b}.{e}" if e else b

    def key(b: str, e: str) -> tuple[str, str]:
        return (b, e)

    need_tilde = (
        len(base) > 8
        or len(ext) > 3
        or base in _RESERVED_BASES
    )

    if not need_tilde:
        cand = key(base, ext)
        if cand not in existing:
            existing.add(cand)
            short_11 = (base.ljust(8) + ext.ljust(3)).encode("ascii")
            need_lfn = dotted(base, ext) != long_name
            return short_11, dotted(base, ext), need_lfn
        need_tilde = True

    # Tilde mangling: BASE~1, BASE~2, ... shrinking base as needed.
    base_trunc = base
    ext_trunc = ext[:3]
    for n in range(1, 1000000):
        suffix = f"~{n}"
        keep = 8 - len(suffix)
        cand_base = base_trunc[:keep] + suffix
        cand = key(cand_base, ext_trunc)
        if cand not in existing:
            existing.add(cand)
            short_11 = (cand_base.ljust(8) + ext_trunc.ljust(3)).encode("ascii")
            return short_11, dotted(cand_base, ext_trunc), True
    raise FloppyError(f"cannot generate short name for {long_name!r}: directory full")


def lfn_checksum(short_11: bytes) -> int:
    """VFAT checksum of an 11-byte short name."""
    s = 0
    for b in short_11:
        s = (((s & 1) << 7) + (s >> 1) + b) & 0xFF
    return s


def create_lfn_entries(long_name: str, checksum: int) -> list[bytes]:
    """Build VFAT long-name directory entries (in on-disk order)."""
    raw = long_name.encode("utf-16-le")
    units = [raw[i:i + 2] for i in range(0, len(raw), 2)]
    n_entries = (len(units) + 12) // 13
    if n_entries == 0:
        n_entries = 1
    if n_entries > 20:  # 20 * 13 = 260 chars max
        raise FloppyError(f"file name too long for FAT LFN: {long_name!r}")

    entries: list[bytes] = []
    for i in range(n_entries):
        seq = n_entries - i  # disk order: highest sequence first
        chunk = units[(seq - 1) * 13:seq * 13]
        slots: list[bytes]
        if len(chunk) < 13:
            slots = list(chunk) + [b"\x00\x00"] + [b"\xff\xff"] * (13 - len(chunk) - 1)
        else:
            slots = list(chunk)
        ent = bytearray(32)
        ent[0] = seq | (0x40 if i == 0 else 0x00)
        # chars 1-5
        for j in range(5):
            ent[1 + j * 2:1 + j * 2 + 2] = slots[j]
        ent[11] = ATTR_LFN
        ent[12] = 0x00
        ent[13] = checksum
        # chars 6-11
        for j in range(6):
            ent[14 + j * 2:14 + j * 2 + 2] = slots[5 + j]
        ent[26:28] = b"\x00\x00"
        # chars 12-13
        for j in range(2):
            ent[28 + j * 2:28 + j * 2 + 2] = slots[11 + j]
        entries.append(bytes(ent))
    return entries


def make_short_entry(short_11: bytes, attr: int, cluster: int, size: int,
                     timestamp: float | None) -> bytes:
    """Build a 32-byte directory entry (11-byte name + attrs + DOS stamps)."""
    ent = bytearray(32)
    ent[0:11] = short_11
    ent[11] = attr
    ent[12] = 0x00
    ent[13] = 0x00
    d, t = dos_date_time(timestamp)
    ent[14:16] = struct.pack("<H", t)
    ent[16:18] = struct.pack("<H", d)
    ent[18:20] = struct.pack("<H", d)  # last access date
    ent[20:22] = struct.pack("<H", 0)  # high cluster (FAT12: always 0)
    ent[22:24] = struct.pack("<H", t)
    ent[24:26] = struct.pack("<H", d)
    ent[26:28] = struct.pack("<H", cluster)
    ent[28:32] = struct.pack("<I", size)
    return bytes(ent)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class _DirState:
    """In-progress directory: entries, used short names, first cluster."""
    __slots__ = ("first_cluster", "entries", "existing")

    def __init__(self, first_cluster: int):
        self.first_cluster = first_cluster  # 0 for root (no chain)
        self.entries: list[bytes] = []
        self.existing: set[tuple[str, str]] = set()


class FloppyBuilder:
    """Incremental FAT12 image builder.

    Files/dirs are added one at a time (add_file/_ensure_dir) with
    clusters allocated on demand; finalize() writes directories, FATs
    and the boot sector. Directory entries are buffered per directory
    and flushed at finalize, except capacity (root limit, subdir chain
    length) which is enforced at add time so spanning can spill over.
    """

    def __init__(self, label: str | None = None):
        self.image = bytearray(TOTAL_SIZE)
        self.fat = [FAT_FREE] * FAT_ENTRY_COUNT
        self.fat[0] = 0xFF0  # media descriptor + reserved
        self.fat[1] = FAT_EOC
        self._hint = FIRST_CLUSTER
        self.dirs: dict[str, _DirState] = {"": _DirState(0)}
        self.label: bytes | None = None
        if label:
            self.set_label(label)

    @staticmethod
    def _format_label(label: str) -> bytes:
        clean = "".join(c if c.isprintable() else "_" for c in label.strip().upper())
        if not clean:
            clean = "FLOPPY"
        return clean[:11].ljust(11).encode("ascii", errors="replace")

    def set_label(self, label: str) -> None:
        """Set the volume label (reserves the root volume entry)."""
        if self.label is not None:
            raise FloppyError("volume label already set")
        self.label = self._format_label(label)
        root = self.dirs[""]
        root.entries.insert(0, make_short_entry(
            self.label, ATTR_VOLUME, 0, 0, None))
        if len(root.entries) > ROOT_ENTRIES:
            del root.entries[0]
            self.label = None
            raise FloppyFullError("root directory full: no room for volume label")

    def rename_label(self, label: str) -> None:
        """Replace the volume label (entry count unchanged)."""
        if self.label is None:
            raise FloppyError("no volume label to rename")
        entries = self.dirs[""].entries
        if not entries or bytes(entries[0][0:11]) != self.label \
                or entries[0][11] != ATTR_VOLUME:
            raise FloppyError("volume entry not where expected")
        self.label = self._format_label(label)
        entries[0] = make_short_entry(self.label, ATTR_VOLUME, 0, 0, None)

    # -- cluster management ---------------------------------------------
    def _find_free(self) -> int:
        for i in range(self._hint, LAST_CLUSTER + 1):
            if self.fat[i] == FAT_FREE:
                self._hint = i + 1
                return i
        for i in range(FIRST_CLUSTER, self._hint):
            if self.fat[i] == FAT_FREE:
                self._hint = i + 1
                return i
        raise FloppyFullError(
            "disk full: content exceeds 1.44MB floppy capacity")

    def alloc_cluster(self) -> int:
        """Allocate one zeroed cluster, marked end-of-chain. Raises FloppyFullError."""
        c = self._find_free()
        self.fat[c] = FAT_EOC
        off = DATA_OFFSET + (c - FIRST_CLUSTER) * BYTES_PER_SECTOR
        self.image[off:off + BYTES_PER_SECTOR] = bytes(BYTES_PER_SECTOR)
        return c

    def alloc_chain(self, count: int) -> int:
        """Allocate a linked chain of *count* clusters; return first (0 if none)."""
        if count <= 0:
            return 0
        first = self.alloc_cluster()
        prev = first
        for _ in range(count - 1):
            nxt = self.alloc_cluster()
            self.fat[prev] = nxt
            prev = nxt
        return first

    def _chain_end(self, first: int) -> int:
        c = first
        while self.fat[c] != FAT_EOC:
            nxt = self.fat[c]
            if nxt < FIRST_CLUSTER or nxt > LAST_CLUSTER:
                raise FloppyError(f"broken FAT chain at cluster {c}")
            c = nxt
        return c

    def _chain_len(self, first: int) -> int:
        n = 0
        c = first
        while True:
            n += 1
            if self.fat[c] == FAT_EOC:
                return n
            c = self.fat[c]

    def extend_chain(self, first: int, needed: int) -> None:
        """Grow the chain at *first* to *needed* clusters (for growing dirs)."""
        have = self._chain_len(first)
        if needed <= have:
            return
        end = self._chain_end(first)
        for _ in range(needed - have):
            nxt = self.alloc_cluster()
            self.fat[end] = nxt
            end = nxt

    def write_chain(self, first: int, data: bytes) -> None:
        """Write *data* across the chain starting at *first* (must be long enough)."""
        c = first
        pos = 0
        while pos < len(data):
            if c < FIRST_CLUSTER or c > LAST_CLUSTER:
                raise FloppyError("FAT chain too short for data")
            off = DATA_OFFSET + (c - FIRST_CLUSTER) * BYTES_PER_SECTOR
            chunk = data[pos:pos + BYTES_PER_SECTOR]
            self.image[off:off + len(chunk)] = chunk
            pos += BYTES_PER_SECTOR
            if pos < len(data):
                nxt = self.fat[c]
                if nxt == FAT_EOC:
                    raise FloppyError("FAT chain too short for data")
                c = nxt

    # -- files / directories ---------------------------------------------
    def add_file_data(self, data: bytes) -> int:
        """Store file bytes, returning the first cluster (0 for empty files)."""
        if not data:
            return 0
        n = (len(data) + BYTES_PER_SECTOR - 1) // BYTES_PER_SECTOR
        first = self.alloc_chain(n)
        self.write_chain(first, data)
        return first

    # -- files / directories (incremental, transactional) -------------------
    def _snapshot(self):
        """Capture full mutable state for rollback (add_file is atomic)."""
        return (
            list(self.fat),
            self._hint,
            {k: (list(v.entries), set(v.existing), v.first_cluster)
             for k, v in self.dirs.items()},
            bytearray(self.image),
        )

    def _restore(self, snap) -> None:
        """Restore state captured by _snapshot (failed adds leave no trace)."""
        fat, hint, dirs, image = snap
        self.fat = fat
        self._hint = hint
        self.dirs = {}
        for k, (entries, existing, first) in dirs.items():
            st = _DirState(first)
            st.entries = entries
            st.existing = existing
            self.dirs[k] = st
        self.image = image

    def _check_parent_capacity(self, rel: str, state: _DirState) -> None:
        """Enforce dir capacity now: root limit, or grow the subdir chain."""
        if rel == "":
            if len(state.entries) > ROOT_ENTRIES:
                raise FloppyFullError(
                    f"root directory full ({ROOT_ENTRIES} entries max); "
                    "move files into subdirectories")
        else:
            needed = max(1, (len(state.entries) + ENTRIES_PER_CLUSTER - 1)
                         // ENTRIES_PER_CLUSTER)
            self.extend_chain(state.first_cluster, needed)

    def _ensure_dir(self, rel_dir: str, src_path: str | None = None) -> _DirState:
        """Return state for *rel_dir* ('/'-separated, '' is root), creating it."""
        st = self.dirs.get(rel_dir)
        if st is not None:
            return st
        if "/" in rel_dir:
            parent_rel, arc_name = rel_dir.rsplit("/", 1)
        else:
            parent_rel, arc_name = "", rel_dir
        parent_src = os.path.dirname(src_path) if src_path else None
        parent = self._ensure_dir(parent_rel, parent_src)
        try:
            mtime = os.path.getmtime(src_path) if src_path else None
        except OSError:
            mtime = None
        first = self.alloc_cluster()
        short_11, _, need_lfn = generate_short_name(arc_name, parent.existing)
        if need_lfn:
            parent.entries.extend(
                create_lfn_entries(arc_name, lfn_checksum(short_11)))
        parent.entries.append(make_short_entry(
            short_11, ATTR_DIR, first, 0, mtime))
        self._check_parent_capacity(parent_rel, parent)
        st = _DirState(first)
        st.entries.append(make_short_entry(
            b".          ", ATTR_DIR, first, 0, mtime))
        st.entries.append(make_short_entry(
            b"..         ", ATTR_DIR, parent.first_cluster, 0, mtime))
        self.dirs[rel_dir] = st
        return st

    def add_file(self, rel_path: str, src_path: str) -> None:
        """Add one file; on FloppyError the builder is left unchanged."""
        snap = self._snapshot()
        try:
            self._add_file_inner(rel_path, src_path)
        except FloppyError:
            self._restore(snap)
            raise

    def _add_file_inner(self, rel_path: str, src_path: str) -> None:
        """Add one file; caller (add_file) rolls back on FloppyError."""
        if "/" in rel_path:
            parent_rel, arc_name = rel_path.rsplit("/", 1)
        else:
            parent_rel, arc_name = "", rel_path
        parent = self._ensure_dir(parent_rel, os.path.dirname(src_path))
        with open(src_path, "rb") as f:
            data = f.read()
        try:
            mtime = os.path.getmtime(src_path)
        except OSError:
            mtime = None
        first = self.add_file_data(data)
        short_11, _, need_lfn = generate_short_name(arc_name, parent.existing)
        if need_lfn:
            parent.entries.extend(
                create_lfn_entries(arc_name, lfn_checksum(short_11)))
        parent.entries.append(make_short_entry(
            short_11, ATTR_ARCHIVE, first, len(data), mtime))
        self._check_parent_capacity(parent_rel, parent)

    def build_from_dir(self, src_dir: str) -> None:
        """Add a whole directory tree (single-volume mode)."""
        self._build_recursive(src_dir, "")

    def _build_recursive(self, src_path: str, rel_dir: str) -> None:
        """Depth-first add in sorted order (single-volume layout)."""
        for child in sorted(os.listdir(src_path)):
            full = os.path.join(src_path, child)
            rel = f"{rel_dir}/{child}" if rel_dir else child
            if os.path.isdir(full) and not os.path.islink(full):
                self._ensure_dir(rel, full)
                self._build_recursive(full, rel)
            elif os.path.isfile(full) or (os.path.islink(full)
                                          and os.path.exists(full)
                                          and not os.path.isdir(full)):
                if os.path.islink(full) and not os.path.isfile(full):
                    print(f"warning: skipping {full} (unsupported link)",
                          file=sys.stderr)
                    continue
                self.add_file(rel, full)
            else:
                print(f"warning: skipping {full} (not a regular file)",
                      file=sys.stderr)

    def finalize(self) -> None:
        """Write directories, FATs and boot sector into the image."""
        root = self.dirs[""].entries
        if len(root) > ROOT_ENTRIES:
            raise FloppyFullError(
                f"root directory full: {len(root)} entries "
                f"(max {ROOT_ENTRIES})")
        blob = b"".join(root)
        blob += bytes(ROOT_ENTRIES * 32 - len(blob))
        self.image[ROOT_OFFSET:ROOT_OFFSET + len(blob)] = blob

        for rel, st in self.dirs.items():
            if rel == "":
                continue
            n = max(1, (len(st.entries) + ENTRIES_PER_CLUSTER - 1)
                    // ENTRIES_PER_CLUSTER)
            blob = b"".join(st.entries)
            blob += bytes(n * BYTES_PER_SECTOR - len(blob))
            self.write_chain(st.first_cluster, blob)

        self._write_fats()
        self._write_boot_sector()

    # -- on-disk structures -----------------------------------------------
    def _write_fats(self) -> None:
        """Pack 12-bit FAT entries (2 entries per 3 bytes) into both FAT copies."""
        packed = bytearray(SECTORS_PER_FAT * BYTES_PER_SECTOR)
        # Even entry: low byte + low nibble; odd entry: high nibble + full byte.
        for i in range(0, FAT_ENTRY_COUNT, 2):
            a = self.fat[i] & 0xFFF
            b = self.fat[i + 1] & 0xFFF if i + 1 < FAT_ENTRY_COUNT else 0
            packed[i * 3 // 2] = a & 0xFF
            packed[i * 3 // 2 + 1] = ((a >> 8) & 0x0F) | ((b & 0x0F) << 4)
            packed[i * 3 // 2 + 2] = (b >> 4) & 0xFF
        for n in range(NUM_FATS):
            off = FAT_OFFSET + n * SECTORS_PER_FAT * BYTES_PER_SECTOR
            self.image[off:off + len(packed)] = packed

    def _write_boot_sector(self) -> None:
        """Write jump + BPB + volume fields + 0x55AA signature (data disk)."""
        boot = bytearray(BYTES_PER_SECTOR)
        boot[0:3] = bytes([0xEB, 0x3C, 0x90])  # jmp + nop
        boot[3:11] = b"MSDOS5.0"
        struct.pack_into("<H", boot, 11, BYTES_PER_SECTOR)
        boot[13] = SECTORS_PER_CLUSTER
        struct.pack_into("<H", boot, 14, RESERVED_SECTORS)
        boot[16] = NUM_FATS
        struct.pack_into("<H", boot, 17, ROOT_ENTRIES)
        struct.pack_into("<H", boot, 19, TOTAL_SECTORS)
        boot[21] = MEDIA_DESCRIPTOR
        struct.pack_into("<H", boot, 22, SECTORS_PER_FAT)
        struct.pack_into("<H", boot, 24, SECTORS_PER_TRACK)
        struct.pack_into("<H", boot, 26, HEADS)
        struct.pack_into("<I", boot, 28, 0)  # hidden sectors
        struct.pack_into("<I", boot, 32, 0)  # total sectors (32-bit, unused)
        boot[34] = 0x00  # drive number
        boot[35] = 0x00  # reserved
        boot[36] = 0x29  # extended boot signature
        struct.pack_into("<I", boot, 37, random.getrandbits(32))
        boot[41:52] = self.label if self.label is not None else b"NO NAME    "
        boot[52:60] = b"FAT12   "
        # boot code left as zeros (data disk); signature:
        boot[510] = 0x55
        boot[511] = 0xAA
        self.image[0:BYTES_PER_SECTOR] = boot


def create_floppy_image(src_dir: str, out_path: str, label: str | None = None) -> None:
    """Build a 1.44MB floppy image from *src_dir* and write it to *out_path*."""
    if not os.path.isdir(src_dir):
        raise FloppyError(f"source is not a directory: {src_dir}")
    builder = FloppyBuilder(label=label)
    builder.build_from_dir(src_dir)
    builder.finalize()
    with open(out_path, "wb") as f:
        f.write(builder.image)


def _collect_source(src_dir: str) -> tuple[list[tuple[str, str]],
                                           list[tuple[str, str]]]:
    """Walk *src_dir*; return ([(rel, full)] files, [(rel, full)] dirs).

    rel paths use '/' separators. Non-regular files are skipped with
    a warning, mirroring single-volume mode.
    """
    files: list[tuple[str, str]] = []
    dirs: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames.sort()
        kept = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            if os.path.islink(full):
                print(f"warning: skipping {full} (unsupported link)",
                      file=sys.stderr)
                continue
            kept.append(d)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            dirs.append((rel, full))
        dirnames[:] = kept
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            if os.path.islink(full) and not os.path.isfile(full):
                print(f"warning: skipping {full} (unsupported link)",
                      file=sys.stderr)
                continue
            if not os.path.isfile(full):
                print(f"warning: skipping {full} (not a regular file)",
                      file=sys.stderr)
                continue
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            files.append((rel, full))
    files.sort(key=lambda t: t[0])
    dirs.sort(key=lambda t: t[0])
    return files, dirs


def _volume_paths(out_path: str, count: int) -> list[str]:
    """Output name(s): as given for one volume, <stem>_<n><ext> for several."""
    if count <= 1:
        return [out_path]
    stem, ext = os.path.splitext(out_path)
    return [f"{stem}_{i}{ext}" for i in range(1, count + 1)]


def build_floppy_images(src_dir: str, label: str | None = None,
                        span: bool = False) -> list[FloppyBuilder]:
    """Build one (or, with *span*, several) finalized floppy images.

    Span mode packs files greedily in sorted order: each file goes on
    the current volume, spilling to a fresh one on FloppyFullError (the
    failed add rolls back, leaving the volume untouched). Empty dirs
    land on the earliest volume with room; a file that fits nowhere
    fails. Multiple volumes get numbered labels (LABEL_1, ...).
    """
    if not os.path.isdir(src_dir):
        raise FloppyError(f"source is not a directory: {src_dir}")
    if not span:
        builder = FloppyBuilder(label=label)
        builder.build_from_dir(src_dir)
        builder.finalize()
        return [builder]

    files, dirs = _collect_source(src_dir)
    builders = [FloppyBuilder(label=label)]
    for rel, full in files:
        try:
            builders[-1].add_file(rel, full)
            continue
        except FloppyFullError:
            pass  # current volume full (unchanged) -> spill to a new one
        fresh = FloppyBuilder(label=label)
        try:
            fresh.add_file(rel, full)
        except FloppyFullError:
            try:
                size = os.path.getsize(full)
            except OSError:
                size = -1
            raise FloppyFullError(
                f"file does not fit on a single 1.44MB floppy "
                f"({size} bytes): {rel}")
        builders.append(fresh)

    # Truly empty dirs (no files anywhere below them) go on the
    # earliest volume with room.
    with_files = {""}
    for rel, _ in files:
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            with_files.add("/".join(parts[:i]))
    for rel, full in dirs:
        if rel in with_files:
            continue
        for b in builders:
            snap = b._snapshot()
            try:
                b._ensure_dir(rel, full)
            except FloppyError:
                b._restore(snap)
            else:
                break
        else:
            fresh = FloppyBuilder(label=label)
            fresh._ensure_dir(rel, full)
            builders.append(fresh)

    if len(builders) > 1 and label:
        for i, b in enumerate(builders, 1):
            suffix = f"_{i}"
            base = label if len(label) + len(suffix) <= 11 \
                else label[:11 - len(suffix)]
            b.rename_label(base + suffix)

    for b in builders:
        b.finalize()
    return builders


def create_floppy_images(src_dir: str, out_path: str,
                         label: str | None = None,
                         span: bool = False) -> list[str]:
    """Build floppy image(s) from *src_dir*, write them, return paths.

    Single volume -> exactly *out_path*. Multiple volumes ->
    ``<stem>_1<ext>``, ``<stem>_2<ext>``, ...
    """
    builders = build_floppy_images(src_dir, label=label, span=span)
    paths = _volume_paths(out_path, len(builders))
    for b, p in zip(builders, paths):
        with open(p, "wb") as f:
            f.write(b.image)
    return paths


# ---------------------------------------------------------------------------
# Reader (for --list and tests)
# ---------------------------------------------------------------------------

def _unpack_fat(image: bytes) -> list[int]:
    """Unpack FAT #1 from 12-bit packed form into entry values."""
    raw = image[FAT_OFFSET:FAT_OFFSET + SECTORS_PER_FAT * BYTES_PER_SECTOR]
    fat = []
    for i in range(0, len(raw), 3):
        b0, b1, b2 = raw[i], raw[i + 1], raw[i + 2]
        fat.append(b0 | ((b1 & 0x0F) << 8))
        fat.append(((b1 >> 4) & 0x0F) | (b2 << 4))
    return fat


def _read_chain(image: bytes, fat: list[int], first: int, size: int) -> bytes:
    """Follow a FAT chain from *first*, returning exactly *size* bytes."""
    if first == 0:
        return b""
    out = bytearray()
    c = first
    while True:
        off = DATA_OFFSET + (c - FIRST_CLUSTER) * BYTES_PER_SECTOR
        out.extend(image[off:off + BYTES_PER_SECTOR])
        nxt = fat[c]
        if nxt >= 0xFF8:
            break
        if nxt < FIRST_CLUSTER or nxt > LAST_CLUSTER:
            raise FloppyError(f"broken FAT chain at cluster {c}")
        c = nxt
    return bytes(out[:size])


def _parse_lfn(entry: bytes) -> tuple[int, bytes]:
    """Split an LFN entry into (sequence number, 26 payload bytes)."""
    seq = entry[0] & 0x1F
    payload = entry[1:11] + entry[14:26] + entry[28:32]
    return seq, payload


def _walk(image: bytes, fat: list[int], entries_blob: bytes, prefix: str,
          out: list[tuple[str, int, bool]]) -> None:
    """Walk a directory blob recursively, reassembling LFN names.

    LFN entries preceding a short entry are joined in sequence order
    (disk order is reversed) and accepted only when their checksum
    matches the short name; otherwise the 8.3 name is used.
    """
    pending: dict[int, bytes] = {}
    pending_sum: int | None = None
    has_last = False
    for i in range(0, len(entries_blob), 32):
        ent = entries_blob[i:i + 32]
        if ent[0] == 0x00:
            break  # end of directory
        if ent[0] == 0xE5:
            pending.clear()
            continue  # deleted
        attr = ent[11]
        if attr == ATTR_LFN:
            seq, payload = _parse_lfn(ent)
            if ent[0] & 0x40:
                pending.clear()
                has_last = True
                pending_sum = ent[13]
            pending[seq] = payload
            continue
        is_dir = bool(attr & ATTR_DIR)
        is_volume = bool(attr & ATTR_VOLUME)
        short_raw = bytes(ent[0:11])
        cluster = struct.unpack_from("<H", ent, 26)[0]
        size = struct.unpack_from("<I", ent, 28)[0]
        name_short = (short_raw[0:8].decode("ascii").rstrip()
                      + ("." + short_raw[8:11].decode("ascii").rstrip()
                         if short_raw[8:11].strip() else ""))
        if name_short in (".", ".."):
            pending.clear()
            continue
        if is_volume:
            pending.clear()
            continue
        # Reconstruct long name if LFN entries match.
        name = name_short
        if pending and has_last and pending_sum == lfn_checksum(short_raw):
            try:
                seqs = sorted(pending)
                if seqs == list(range(1, max(seqs) + 1)):
                    blob = b"".join(pending[s] for s in seqs)
                    text = blob.decode("utf-16-le")
                    nul = text.find("\x00")
                    if nul != -1:
                        text = text[:nul]
                    text = text.rstrip("\uffff")
                    if text:
                        name = text
            except (UnicodeDecodeError, KeyError):
                pass
        pending.clear()
        has_last = False
        pending_sum = None
        path = f"{prefix}{name}"
        out.append((path, size, is_dir))
        if is_dir and cluster != 0:
            # Directories: read full chain (size field is 0 for dirs).
            chunks = []
            c = cluster
            while True:
                off = DATA_OFFSET + (c - FIRST_CLUSTER) * BYTES_PER_SECTOR
                chunks.append(bytes(image[off:off + BYTES_PER_SECTOR]))
                nxt = fat[c]
                if nxt >= 0xFF8:
                    break
                c = nxt
            _walk(image, fat, b"".join(chunks), path + "/", out)


def list_image_contents(image_path: str) -> list[tuple[str, int, bool]]:
    """Return [(path, size, is_dir)] for a floppy image."""
    with open(image_path, "rb") as f:
        image = f.read()
    if len(image) != TOTAL_SIZE:
        raise FloppyError(f"not a 1.44MB image: {image_path} ({len(image)} bytes)")
    fat = _unpack_fat(image)
    root = image[ROOT_OFFSET:ROOT_OFFSET + ROOT_ENTRIES * 32]
    out: list[tuple[str, int, bool]] = []
    _walk(image, fat, root, "", out)
    return out


def read_file_from_image(image_path: str, arc_path: str) -> bytes:
    """Extract one file (unix-style path) from a floppy image."""
    with open(image_path, "rb") as f:
        image = f.read()
    fat = _unpack_fat(image)

    parts = [p for p in arc_path.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts:
        raise FloppyError("empty path")

    def entries_of(blob: bytes):
        pending: dict[int, bytes] = {}
        pending_sum: int | None = None
        has_last = False
        result = []
        for i in range(0, len(blob), 32):
            ent = blob[i:i + 32]
            if ent[0] == 0x00:
                break
            if ent[0] == 0xE5:
                pending.clear()
                continue
            if ent[11] == ATTR_LFN:
                seq, payload = _parse_lfn(ent)
                if ent[0] & 0x40:
                    pending.clear()
                    has_last = True
                    pending_sum = ent[13]
                pending[seq] = payload
                continue
            short_raw = bytes(ent[0:11])
            name_short = (short_raw[0:8].decode("ascii").rstrip()
                          + ("." + short_raw[8:11].decode("ascii").rstrip()
                             if short_raw[8:11].strip() else ""))
            if name_short in (".", "..") or ent[11] & ATTR_VOLUME:
                pending.clear()
                continue
            name = name_short
            if pending and has_last and pending_sum == lfn_checksum(short_raw):
                try:
                    seqs = sorted(pending)
                    if seqs == list(range(1, max(seqs) + 1)):
                        blob_lfn = b"".join(pending[s] for s in seqs)
                        text = blob_lfn.decode("utf-16-le")
                        nul = text.find("\x00")
                        if nul != -1:
                            text = text[:nul]
                        text = text.rstrip("\uffff")
                        if text:
                            name = text
                except (UnicodeDecodeError, KeyError):
                    pass
            pending.clear()
            has_last = False
            pending_sum = None
            result.append((name, name_short, bytes(ent)))
        return result

    def dir_blob_for(cluster: int) -> bytes:
        chunks = []
        c = cluster
        while True:
            off = DATA_OFFSET + (c - FIRST_CLUSTER) * BYTES_PER_SECTOR
            chunks.append(bytes(image[off:off + BYTES_PER_SECTOR]))
            nxt = fat[c]
            if nxt >= 0xFF8:
                break
            c = nxt
        return b"".join(chunks)

    blob = bytes(image[ROOT_OFFSET:ROOT_OFFSET + ROOT_ENTRIES * 32])
    for depth, part in enumerate(parts):
        found = None
        for name, name_short, ent in entries_of(blob):
            if part == name or part.upper() == name_short.upper():
                found = ent
                break
        if found is None:
            raise FloppyError(f"not found in image: {arc_path}")
        cluster = struct.unpack_from("<H", found, 26)[0]
        size = struct.unpack_from("<I", found, 28)[0]
        is_dir = bool(found[11] & ATTR_DIR)
        if depth == len(parts) - 1:
            if is_dir:
                raise FloppyError(f"not a file: {arc_path}")
            return _read_chain(image, fat, cluster, size)
        if not is_dir:
            raise FloppyError(f"not a directory: {part}")
        blob = dir_blob_for(cluster)
    raise FloppyError(f"not found in image: {arc_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit codes: 0 ok, 1 error, 2 usage/disk-full."""
    ap = argparse.ArgumentParser(
        description="Convert a directory to a 1.44MB floppy image (.img) "
                    "for PCem, or to an ISO 9660 CD image with --iso.")
    ap.add_argument("source", nargs="?", help="source directory")
    ap.add_argument("output", nargs="?", help="output image, e.g. disk.img")
    ap.add_argument("--label", default=None,
                    help="volume label, up to 11 chars (default: NO NAME)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite output file if it exists")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--span", action="store_true",
                       help="spread content over multiple numbered images "
                            "(disk_1.img, disk_2.img, ...) when it exceeds "
                            "one floppy instead of failing")
    group.add_argument("--iso", action="store_true",
                       help="write an ISO 9660 (+Joliet) CD image instead "
                            "of a floppy image (no size limit)")
    ap.add_argument("--list", dest="list_only", action="store_true",
                    help="list contents of an existing image (floppy or ISO, "
                         "auto-detected) instead of creating")
    ap.add_argument("--register-context", dest="register_context",
                    action="store_true",
                    help="install Explorer context-menu verbs and exit "
                         "(Windows, per-user)")
    ap.add_argument("--unregister-context", dest="unregister_context",
                    action="store_true",
                    help="remove Explorer context-menu verbs and exit")
    args = ap.parse_args(argv)

    try:
        if args.list_only:
            if not args.source:
                ap.error("--list needs an image path")
            entries = make_iso.list_iso_contents(args.source) \
                if make_iso.is_iso_image(args.source) \
                else list_image_contents(args.source)
            for path, size, is_dir in entries:
                print(f"{'DIR ' if is_dir else 'FILE'} {size:>8}  {path}")
            return 0

        if args.register_context:
            try:
                contextmenu.register()
            except contextmenu.ContextMenuError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print("context menu installed")
            return 0
        if args.unregister_context:
            try:
                contextmenu.unregister()
            except contextmenu.ContextMenuError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print("context menu removed")
            return 0

        if not args.source or not args.output:
            ap.error("source and output are required")
        if args.iso:
            if os.path.exists(args.output) and not args.force:
                print(f"error: output already exists: {args.output} "
                      "(use --force to overwrite)", file=sys.stderr)
                return 1
            make_iso.create_iso_image(args.source, args.output, args.label)
            print(f"wrote {args.output} "
                  f"({os.path.getsize(args.output)} bytes)")
            return 0
        builders = build_floppy_images(args.source, args.label,
                                       span=args.span)
        paths = _volume_paths(args.output, len(builders))
        if not args.force:
            existing = [p for p in paths if os.path.exists(p)]
            if existing:
                print(f"error: output already exists: {', '.join(existing)} "
                      "(use --force to overwrite)", file=sys.stderr)
                return 1
        for p, b in zip(paths, builders):
            with open(p, "wb") as f:
                f.write(b.image)
            print(f"wrote {p} ({TOTAL_SIZE} bytes)")
        return 0
    except FloppyFullError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (FloppyError, make_iso.IsoError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
