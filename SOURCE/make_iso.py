#!/usr/bin/env python3
"""Create an ISO 9660 (+Joliet) CD-ROM image from a directory.

The output is a plain data disc image (.iso) that mounts as a CD-ROM
in PCem (and most other emulators / VMs / OSes).

Pure standard library, works on Windows / Linux / macOS::

    python make_iso.py <source_dir> <output.iso> [--label LABEL]

Layout: ISO 9660 tree with DOS-safe 8.3 uppercase names (readable
with MSCDEX on DOS) plus a Joliet tree with full Unicode long names
(for Windows 95 and later). Both trees share the same file data.
No practical size limit (files up to 4GB - 1).
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time

SECTOR = 2048
SYSTEM_SECTORS = 16  # sectors 0-15: system area (zeros)

VD_PRIMARY = 1
VD_SUPPLEMENTARY = 2
VD_TERMINATOR = 255

JOLIET_ESCAPE = b"%/E"  # UCS-2 level 3
MAX_JOLIET_CHARS = 64  # original spec limit, version suffix included


class IsoError(Exception):
    """Base error for ISO creation problems."""


# ---------------------------------------------------------------------------
# Low-level encodings
# ---------------------------------------------------------------------------

def _both16(n: int) -> bytes:
    """16-bit both-endian field (LE16 followed by BE16)."""
    return struct.pack("<H", n) + struct.pack(">H", n)


def _both32(n: int) -> bytes:
    """32-bit both-endian field (LE32 followed by BE32)."""
    return struct.pack("<I", n) + struct.pack(">I", n)


def _dir_datetime(ts: float | None = None) -> bytes:
    """7-byte directory-record timestamp (UTC, offset 0)."""
    if ts is None:
        ts = time.time()
    t = time.gmtime(ts)
    year = max(0, min(t.tm_year - 1900, 255))
    return bytes([year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, 0])


def _vd_datetime(ts: float | None = None) -> bytes:
    """17-byte volume-descriptor timestamp (UTC, offset 0)."""
    if ts is None:
        ts = time.time()
    t = time.gmtime(ts)
    s = (f"{t.tm_year:04d}{t.tm_mon:02d}{t.tm_mday:02d}"
         f"{t.tm_hour:02d}{t.tm_min:02d}{t.tm_sec:02d}00")
    return s.encode("ascii") + b"\x00"


_VD_DATETIME_UNSPECIFIED = b"0000000000000000\x00"

_ISO_DCHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_JOLIET_RESERVED = set("*\\/:;?\"<>|")


def iso_short_name(long_name: str, existing: set[tuple[str, str]],
                   is_dir: bool = False) -> str:
    """DOS-safe 8.3 stem (e.g. 'FOO.BAR'); per-directory *existing* set.

    Uses only ISO 9660 d-characters (A-Z 0-9 _); collisions get _1, _2...
    """
    stripped = long_name.strip(" .") or "FILE"

    def clean(text: str) -> str:
        return "".join(c if c in _ISO_DCHARS else "_" for c in text.upper())

    if is_dir:
        base = clean(stripped.replace(".", "")) or "_"
        ext = ""
    else:
        if "." in stripped:
            base_raw, ext_raw = stripped.rsplit(".", 1)
        else:
            base_raw, ext_raw = stripped, ""
        base = clean(base_raw.replace(".", "")) or "_"
        ext = clean(ext_raw.replace(".", ""))

    if len(base) <= 8 and len(ext) <= 3 and (base, ext) not in existing:
        existing.add((base, ext))
        return base + ("." + ext if ext else "")
    for n in range(1, 10000):
        suffix = f"_{n}"
        cand_base = base[:8 - len(suffix)] + suffix
        cand_ext = ext[:3]
        if (cand_base, cand_ext) not in existing:
            existing.add((cand_base, cand_ext))
            return cand_base + ("." + cand_ext if cand_ext else "")
    raise IsoError(f"cannot generate ISO name for {long_name!r}")


def joliet_name(long_name: str, existing: set[str], is_dir: bool = False) -> str:
    """Joliet name (case preserved); *existing* holds casefolded names."""
    s = "".join("_" if (c in _JOLIET_RESERVED or ord(c) < 0x20) else c
                for c in long_name).strip().rstrip(".") or "FILE"
    if is_dir:
        stem, suffix = s, ""
    elif "." in s:
        stem, ext = s.rsplit(".", 1)
        suffix = "." + ext
    else:
        stem, suffix = s, ""
    # Room for the ";1" version on files (dirs have none).
    ver_len = 0 if is_dir else 2
    if len(s) + ver_len > MAX_JOLIET_CHARS:
        raise IsoError(
            f"name too long for Joliet (>{MAX_JOLIET_CHARS - ver_len} chars): "
            f"{long_name!r}")

    def claim(name: str) -> str | None:
        if name.casefold() not in existing:
            existing.add(name.casefold())
            return name
        return None

    first = stem + suffix
    got = claim(first)
    if got is not None:
        return got
    for n in range(2, 10000):
        num = f"_{n}"
        cand = stem[:MAX_JOLIET_CHARS - ver_len - len(num) - len(suffix)] \
            + num + suffix
        got = claim(cand)
        if got is not None:
            return got
    raise IsoError(f"cannot generate Joliet name for {long_name!r}")


def _dir_record(extent: int, size: int, mtime: float | None,
                is_dir: bool, ident: bytes) -> bytes:
    """Build one directory record (extent/size both-endian, 7-byte date).

    Length is 33 + identifier, padded to even. Identifiers: "."/".." are
    single 0x00/0x01 bytes; 9660 files carry a ";1" version, as do Joliet
    files (UCS-2BE); directories never do.
    """
    rec_len = 33 + len(ident) + (0 if len(ident) % 2 else 1)
    rec = bytearray(rec_len)
    rec[0] = rec_len
    rec[1] = 0
    rec[2:10] = _both32(extent)
    rec[10:18] = _both32(size)
    rec[18:25] = _dir_datetime(mtime)
    rec[25] = 0x02 if is_dir else 0x00
    rec[26] = 0
    rec[27] = 0
    rec[28:32] = _both16(1)
    rec[32] = len(ident)
    rec[33:33 + len(ident)] = ident
    return bytes(rec)


def _pack_dir(records: list[bytes]) -> bytes:
    """Pack directory records into sectors (records never split)."""
    out = bytearray()
    used = 0
    for r in records:
        if used + len(r) > SECTOR:
            out += bytes(SECTOR - used)
            used = 0
        out += r
        used += len(r)
    if used:
        out += bytes(SECTOR - used)
    return bytes(out)


def _path_record(ident: bytes, extent: int, parent_no: int,
                 big_endian: bool) -> bytes:
    """Build one path-table record (lengths in bytes, pad byte when odd).

    Root's identifier is a single 0x00 byte in both the 9660 and the
    Joliet table; directory numbering starts at 1 (root) in BFS order.
    """
    rec = bytearray()
    rec.append(len(ident))
    rec.append(0)
    rec += struct.pack(">I" if big_endian else "<I", extent)
    rec += struct.pack(">H" if big_endian else "<H", parent_no)
    rec += ident
    if len(ident) % 2:
        rec.append(0)
    return bytes(rec)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class _Node:
    __slots__ = ("rel", "full", "is_dir", "mtime", "size", "children",
                 "iso_ident", "jol_ident", "dir_no", "extent", "data_len")

    def __init__(self, rel: str, full: str, is_dir: bool,
                 mtime: float | None, size: int = 0):
        self.rel = rel            # '/'-separated archive path ('' = root)
        self.full = full          # source path
        self.is_dir = is_dir
        self.mtime = mtime
        self.size = size
        self.children: list[_Node] = []
        self.iso_ident = b""      # identifier bytes in 9660 tree
        self.jol_ident = b""      # identifier bytes in Joliet tree
        self.dir_no = 0           # path-table directory number
        self.extent = 0           # data/dir extent LBA
        self.data_len = 0         # data length recorded in dir record


class IsoBuilder:
    """ISO 9660 + Joliet image builder (single build() call, no size limit).

    Two directory trees (9660 with DOS-safe 8.3 names, Joliet with long
    Unicode names) share the same file-data extents. Layout order:
    system area, PVD, Joliet SVD, terminator, path tables (9660 LE/BE,
    Joliet LE/BE), 9660 dirs, Joliet dirs, file data. Empty files share
    one zero sector.
    """

    def __init__(self, label: str | None = None):
        self.label = (label or "CDROM").strip() or "CDROM"
        self.now = time.time()

    # -- source walk ----------------------------------------------------
    @staticmethod
    def _collect(src_dir: str) -> _Node:
        """Walk *src_dir* into a tree of _Nodes (files get sizes, dirs get kids)."""
        def mtime_of(path: str) -> float | None:
            try:
                return os.path.getmtime(path)
            except OSError:
                return None

        root = _Node("", src_dir, True, mtime_of(src_dir))
        stack = [(root, src_dir)]
        while stack:
            node, path = stack.pop()
            try:
                children = sorted(os.listdir(path))
            except OSError as e:
                raise IsoError(f"cannot list {path}: {e}")
            for child in children:
                full = os.path.join(path, child)
                rel = f"{node.rel}/{child}" if node.rel else child
                if os.path.isdir(full) and not os.path.islink(full):
                    sub = _Node(rel, full, True, mtime_of(full))
                    node.children.append(sub)
                    stack.append((sub, full))
                elif os.path.isfile(full):
                    try:
                        size = os.path.getsize(full)
                    except OSError as e:
                        raise IsoError(f"cannot stat {full}: {e}")
                    if size > 0xFFFFFFFF:
                        raise IsoError(f"file too large for ISO 9660: {rel}")
                    node.children.append(
                        _Node(rel, full, False, mtime_of(full), size))
                elif os.path.islink(full) and os.path.isfile(full):
                    # Symlink to a file: follow it.
                    try:
                        size = os.path.getsize(full)
                    except OSError as e:
                        raise IsoError(f"cannot stat {full}: {e}")
                    node.children.append(
                        _Node(rel, full, False, mtime_of(full), size))
                else:
                    print(f"warning: skipping {full} (not a regular file)",
                          file=sys.stderr)
        return root

    # -- identifiers -----------------------------------------------------
    @staticmethod
    def _assign_idents(root: _Node) -> list[_Node]:
        """Assign 9660 + Joliet identifiers; return dirs in BFS order."""
        ordered: list[_Node] = []
        queue = [root]
        while queue:
            node = queue.pop(0)
            ordered.append(node)
            existing_iso: set[tuple[str, str]] = set()
            existing_jol: set[str] = set()
            node.children.sort(key=lambda n: n.rel.rsplit("/", 1)[-1])
            for child in node.children:
                arc = child.rel.rsplit("/", 1)[-1]
                stem = iso_short_name(arc, existing_iso, child.is_dir)
                if child.is_dir:
                    child.iso_ident = stem.encode("ascii")
                    child.jol_ident = joliet_name(
                        arc, existing_jol, True).encode("utf-16-be")
                else:
                    child.iso_ident = (stem + ";1").encode("ascii")
                    child.jol_ident = (joliet_name(arc, existing_jol, False)
                                       + ";1").encode("utf-16-be")
                if child.is_dir:
                    queue.append(child)
        for i, node in enumerate(ordered, 1):
            node.dir_no = i
        return ordered

    # -- layout -----------------------------------------------------------
    def build(self, src_dir: str, progress=None) -> bytes:
        """Build the full image: identifiers, extents, tables, dirs, data, VDs.

        Extents are assigned before any bytes are written: identifier and
        record sizes are known up front, so path-table sizes fix the table
        addresses, then dir sizes (via placeholder packing) fix the dir
        addresses, then file data follows. Records within a directory are
        sorted by identifier bytes, as readers expect.

        *progress*, when given, is called as progress(done_bytes,
        total_bytes) while file data is copied, plus one final call.
        """
        report = progress or (lambda _d, _t: None)
        if not os.path.isdir(src_dir):
            raise IsoError(f"source is not a directory: {src_dir}")
        root = self._collect(src_dir)
        dirs = self._assign_idents(root)
        by_no = {d.dir_no: d for d in dirs}

        files: list[_Node] = []
        stack = [root]
        while stack:
            node = stack.pop()
            for child in node.children:
                if child.is_dir:
                    stack.append(child)
                else:
                    files.append(child)
        files.sort(key=lambda n: n.rel)

        # Path-table idents. Root is a single 00 byte in both tables;
        # 9660 idents reuse the assigned stems (no version on dirs anyway).
        iso_pt_idents: dict[int, bytes] = {}
        for node in dirs:
            if node.dir_no == 1:
                iso_pt_idents[node.dir_no] = b"\x00"
            else:
                iso_pt_idents[node.dir_no] = node.iso_ident
        jol_pt_idents: dict[int, bytes] = {}
        for node in dirs:
            if node.dir_no == 1:
                jol_pt_idents[node.dir_no] = b"\x00"
            else:
                # Dir idents carry no version suffix, usable as-is.
                jol_pt_idents[node.dir_no] = node.jol_ident

        def table_size(idents: dict[int, bytes]) -> int:
            return sum(8 + len(b) + (len(b) % 2) for b in idents.values())

        def sectors(nbytes: int) -> int:
            return (nbytes + SECTOR - 1) // SECTOR

        # Fixed header: 16 system + PVD + SVD + terminator.
        lba = SYSTEM_SECTORS + 3
        pt_iso_le = lba
        lba += sectors(table_size(iso_pt_idents))
        pt_iso_be = lba
        lba += sectors(table_size(iso_pt_idents))
        pt_jol_le = lba
        lba += sectors(table_size(jol_pt_idents))
        pt_jol_be = lba
        lba += sectors(table_size(jol_pt_idents))

        # Directory extents (record sizes known; contents need extents).
        dir_sectors: dict[tuple[int, str], int] = {}
        for node in dirs:
            for tree, attr in (("iso", "iso_ident"), ("jol", "jol_ident")):
                n = 2 + len(node.children)  # . and .. plus children
                # Upper bound: records never split, so count worst case
                # by packing with placeholder extents (same lengths).
                recs = [b"\x00" * 34, b"\x00" * 34]
                for child in sorted(node.children,
                                    key=lambda c: getattr(c, attr)):
                    ident = getattr(child, attr)
                    recs.append(b"\x00" * (33 + len(ident)
                                           + (0 if len(ident) % 2 else 1)))
                size = len(_pack_dir(recs))
                dir_sectors[(node.dir_no, tree)] = size // SECTOR

        dir_extent: dict[tuple[int, str], int] = {}
        for node in dirs:
            dir_extent[(node.dir_no, "iso")] = lba
            lba += dir_sectors[(node.dir_no, "iso")]
        for node in dirs:
            dir_extent[(node.dir_no, "jol")] = lba
            lba += dir_sectors[(node.dir_no, "jol")]

        # File data extents; empty files share one zero sector.
        empty_extent = 0
        if any(f.size == 0 for f in files):
            empty_extent = lba
            lba += 1
        for f in files:
            if f.size == 0:
                f.extent = empty_extent
            else:
                f.extent = lba
                lba += sectors(f.size)
            f.data_len = f.size

        total_sectors = lba
        image = bytearray(total_sectors * SECTOR)

        # -- path tables -------------------------------------------------
        def write_table(lba_at: int, idents: dict[int, bytes],
                        tree: str, big_endian: bool) -> None:
            blob = bytearray()
            for node in dirs:
                parent_no = 1 if node.dir_no == 1 else self._parent_no(
                    node, by_no)
                blob += _path_record(idents[node.dir_no],
                                     dir_extent[(node.dir_no, tree)],
                                     parent_no, big_endian)
            off = lba_at * SECTOR
            image[off:off + len(blob)] = blob

        write_table(pt_iso_le, iso_pt_idents, "iso", False)
        write_table(pt_iso_be, iso_pt_idents, "iso", True)
        write_table(pt_jol_le, jol_pt_idents, "jol", False)
        write_table(pt_jol_be, jol_pt_idents, "jol", True)

        # -- directories ---------------------------------------------------
        for node in dirs:
            for tree, attr in (("iso", "iso_ident"), ("jol", "jol_ident")):
                recs = []
                own_extent = dir_extent[(node.dir_no, tree)]
                own_size = dir_sectors[(node.dir_no, tree)] * SECTOR
                recs.append(_dir_record(own_extent, own_size, node.mtime,
                                        True, b"\x00"))
                if node.dir_no == 1:
                    recs.append(_dir_record(own_extent, own_size, node.mtime,
                                            True, b"\x01"))
                else:
                    pno = self._parent_no(node, by_no)
                    recs.append(_dir_record(
                        dir_extent[(pno, tree)],
                        dir_sectors[(pno, tree)] * SECTOR,
                        by_no[pno].mtime, True, b"\x01"))
                for child in sorted(node.children,
                                    key=lambda c: getattr(c, attr)):
                    if child.is_dir:
                        c_ext = dir_extent[(child.dir_no, tree)]
                        c_len = dir_sectors[(child.dir_no, tree)] * SECTOR
                    else:
                        c_ext, c_len = child.extent, child.data_len
                    recs.append(_dir_record(c_ext, c_len, child.mtime,
                                            child.is_dir,
                                            getattr(child, attr)))
                blob = _pack_dir(recs)
                assert len(blob) == dir_sectors[(node.dir_no, tree)] * SECTOR
                off = own_extent * SECTOR
                image[off:off + len(blob)] = blob
                if tree == "iso":
                    node.extent = own_extent
                    node.data_len = own_size

        # -- file data ------------------------------------------------------
        total = sum(f.size for f in files)
        done = 0
        for f in files:
            if f.size == 0:
                continue
            with open(f.full, "rb") as fh:
                data = fh.read()
            if len(data) != f.size:
                raise IsoError(f"file changed during build: {f.rel}")
            off = f.extent * SECTOR
            image[off:off + len(data)] = data
            done += len(data)
            report(done, total)
        report(total, total)

        # -- descriptors -----------------------------------------------------
        root_iso = _dir_record(dir_extent[(1, "iso")],
                               dir_sectors[(1, "iso")] * SECTOR,
                               root.mtime, True, b"\x00")
        root_jol = _dir_record(dir_extent[(1, "jol")],
                               dir_sectors[(1, "jol")] * SECTOR,
                               root.mtime, True, b"\x00")
        assert len(root_iso) == 34 and len(root_jol) == 34
        image[16 * SECTOR:17 * SECTOR] = self._volume_descriptor(
            VD_PRIMARY, self._volume_id_9660(), root_iso,
            table_size(iso_pt_idents), pt_iso_le, pt_iso_be,
            total_sectors, joliet=False)
        image[17 * SECTOR:18 * SECTOR] = self._volume_descriptor(
            VD_SUPPLEMENTARY, self._volume_id_joliet(), root_jol,
            table_size(jol_pt_idents), pt_jol_le, pt_jol_be,
            total_sectors, joliet=True)
        term = bytearray(SECTOR)
        term[0] = VD_TERMINATOR
        term[1:6] = b"CD001"
        term[6] = 1
        image[18 * SECTOR:19 * SECTOR] = term

        return bytes(image)

    @staticmethod
    def _parent_no(node: _Node, by_no: dict[int, _Node]) -> int:
        """Path-table parent directory number (root is its own parent: 1)."""
        if node.dir_no == 1:
            return 1
        parent_rel = node.rel.rsplit("/", 1)[0] if "/" in node.rel else ""
        for n in by_no.values():
            if n.rel == parent_rel:
                return n.dir_no
        raise IsoError(f"parent not found for {node.rel!r}")

    def _volume_id_9660(self) -> bytes:
        """32-byte space-padded uppercase volume id (d-chars and spaces)."""
        clean = "".join(c if c in _ISO_DCHARS or c == " " else "_"
                        for c in self.label.upper())
        return clean[:32].ljust(32).encode("ascii")

    def _volume_id_joliet(self) -> bytes:
        """32-byte Joliet volume id: up to 16 UCS-2BE chars, space-padded."""
        return self._joliet_pad(self.label[:16], 32)

    def _volume_descriptor(self, vd_type: int, vol_id: bytes, root_rec: bytes,
                           pt_size: int, pt_le: int, pt_be: int,
                           total_sectors: int, joliet: bool) -> bytes:
        """Build one 2048-byte volume descriptor (PVD or Joliet SVD).

        Field layout: type(0) "CD001"(1) version(6), system id(8),
        volume id(40), space size(80), escape(88, SVD: "%/E"), set
        size/seq(120/124), block size(128), path table size/locs
        (132/140/148), root record(156), set/publisher/preparer/app
        ids(190/318/446/574), timestamps(813/830/847/864), struct
        version(881).
        """
        vd = bytearray(SECTOR)
        vd[0] = vd_type
        vd[1:6] = b"CD001"
        vd[6] = 1
        vd[7] = 0
        if joliet:
            vd[8:40] = self._joliet_pad(" ", 32)  # system identifier
        else:
            vd[8:40] = b" " * 32  # system identifier
        vd[40:72] = vol_id
        # 72-79 unused (zeros)
        vd[80:88] = _both32(total_sectors)
        if joliet:
            vd[88:91] = JOLIET_ESCAPE
        # 120-123 volume set size, 124-127 volume sequence number
        vd[120:124] = _both16(1)
        vd[124:128] = _both16(1)
        vd[128:132] = _both16(SECTOR)
        vd[132:140] = _both32(pt_size)
        struct.pack_into("<I", vd, 140, pt_le)
        struct.pack_into(">I", vd, 148, pt_be)
        # 144/152 optional tables stay 0
        vd[156:190] = root_rec
        if joliet:
            vd[190:318] = self._joliet_pad(self.label, 128)
            vd[318:446] = self._joliet_pad("", 128)
            vd[446:574] = self._joliet_pad("", 128)
            vd[574:702] = self._joliet_pad("MAKE_ISO", 128)
        else:
            vd[190:318] = b" " * 128  # volume set identifier
            vd[574:702] = b"MAKE_ISO" + b" " * (128 - 8)  # application id
        vd[813:830] = _vd_datetime(self.now)
        vd[830:847] = _vd_datetime(self.now)
        vd[847:864] = _VD_DATETIME_UNSPECIFIED
        vd[864:881] = _VD_DATETIME_UNSPECIFIED
        vd[881] = 1
        return bytes(vd)

    @staticmethod
    def _joliet_pad(text: str, size: int) -> bytes:
        """UCS-2BE string truncated to *size* bytes, padded with U+0020."""
        raw = text.encode("utf-16-be")[:size]
        if len(raw) % 2:
            raw = raw[:-1]
        # Pad with UCS-2 spaces (trailing, like real mastering tools).
        return raw + b"\x00 " * ((size - len(raw)) // 2)


def create_iso_image(src_dir: str, out_path: str,
                     label: str | None = None, progress=None) -> None:
    """Build an ISO 9660 (+Joliet) image from *src_dir*.

    *progress* is passed through to IsoBuilder.build (done, total bytes).
    """
    image = IsoBuilder(label=label).build(src_dir, progress=progress)
    with open(out_path, "wb") as f:
        f.write(image)


# ---------------------------------------------------------------------------
# Reader (for --list and tests)
# ---------------------------------------------------------------------------

def _find_descriptors(image: bytes) -> tuple[dict, dict | None]:
    """Return (primary, joliet-or-None) descriptor info dicts."""
    primary: dict | None = None
    joliet: dict | None = None
    for sector in range(SYSTEM_SECTORS, SYSTEM_SECTORS + 64):
        off = sector * SECTOR
        vd = image[off:off + SECTOR]
        if len(vd) < SECTOR or vd[1:6] != b"CD001":
            break
        vd_type = vd[0]
        if vd_type == VD_TERMINATOR:
            break
        if vd_type not in (VD_PRIMARY, VD_SUPPLEMENTARY):
            continue
        info = {
            "sector": sector,
            "type": vd_type,
            "escape": bytes(vd[88:91]),
            "block_size": struct.unpack_from("<H", vd, 128)[0],
            "root_extent": struct.unpack_from("<I", vd, 156 + 2)[0],
            "root_size": struct.unpack_from("<I", vd, 156 + 10)[0],
        }
        if vd_type == VD_PRIMARY and primary is None:
            primary = info
        elif vd_type == VD_SUPPLEMENTARY and vd[88:91] in (
                b"%/E", b"%/C", b"%/@") and joliet is None:
            joliet = info
    if primary is None:
        raise IsoError("no primary volume descriptor found")
    return primary, joliet


def _iter_dir(image: bytes, extent: int, size: int):
    """Yield raw directory records (with byte offset) from an extent."""
    blob = image[extent * SECTOR:extent * SECTOR + size]
    pos = 0
    while pos < len(blob):
        # Records never cross sector boundaries; skip padding.
        sector_off = pos % SECTOR
        if SECTOR - sector_off < 33:
            pos += SECTOR - sector_off
            continue
        rec_len = blob[pos]
        if rec_len == 0:
            pos += SECTOR - sector_off
            continue
        if rec_len < 33 or pos + rec_len > len(blob):
            raise IsoError("corrupt directory record")
        yield bytes(blob[pos:pos + rec_len])
        pos += rec_len


def _decode_record(rec: bytes, joliet: bool):
    """Decode a record to (name, extent, size, is_dir); None for ./...

    Versions (";1") are stripped from file names in both trees.
    """
    extent = struct.unpack_from("<I", rec, 2)[0]
    size = struct.unpack_from("<I", rec, 10)[0]
    flags = rec[25]
    fi_len = rec[32]
    ident = bytes(rec[33:33 + fi_len])
    if ident in (b"\x00", b"\x01"):
        return None  # . / ..
    if joliet:
        name = ident.decode("utf-16-be")
    else:
        name = ident.decode("ascii")
    if ";" in name and not (flags & 0x02):
        name = name.split(";")[0]
    return name, extent, size, bool(flags & 0x02)


def _walk_iso(image: bytes, desc: dict, joliet: bool):
    """Walk one tree from its root extent; return [(path, size, is_dir, extent)]."""
    out: list[tuple[str, int, bool, int]] = []  # path,size,is_dir,extent

    def visit(extent: int, size: int, prefix: str):
        for rec in _iter_dir(image, extent, size):
            decoded = _decode_record(rec, joliet)
            if decoded is None:
                continue
            name, c_ext, c_size, is_dir = decoded
            path = f"{prefix}{name}"
            out.append((path, c_size, is_dir, c_ext))
            if is_dir:
                visit(c_ext, c_size, path + "/")

    visit(desc["root_extent"], desc["root_size"], "")
    return out


def is_iso_image(path: str) -> bool:
    """True if *path* looks like an ISO 9660 image (PVD magic)."""
    try:
        with open(path, "rb") as f:
            f.seek(SYSTEM_SECTORS * SECTOR + 1)
            return f.read(5) == b"CD001"
    except OSError:
        return False


def list_iso_contents(image_path: str, joliet: bool = True,
                      ) -> list[tuple[str, int, bool]]:
    """Return [(path, size, is_dir)] for an ISO image.

    Uses the Joliet tree (long names) when present unless *joliet* is False.
    """
    with open(image_path, "rb") as f:
        image = f.read()
    primary, jol = _find_descriptors(image)
    desc = jol if (joliet and jol is not None) else primary
    use_jol = desc is jol
    return [(p, s, d) for p, s, d, _ in _walk_iso(image, desc, use_jol)]


def read_file_from_iso(image_path: str, arc_path: str) -> bytes:
    """Extract one file (unix-style path) from an ISO image."""
    with open(image_path, "rb") as f:
        image = f.read()
    primary, jol = _find_descriptors(image)
    desc = jol if jol is not None else primary
    use_jol = desc is jol
    parts = [p for p in arc_path.replace("\\", "/").split("/")
             if p not in ("", ".")]
    if not parts:
        raise IsoError("empty path")
    extent, size, is_dir = desc["root_extent"], desc["root_size"], True
    for depth, part in enumerate(parts):
        found = None
        for rec in _iter_dir(image, extent, size):
            decoded = _decode_record(rec, use_jol)
            if decoded is None:
                continue
            name, c_ext, c_size, c_dir = decoded
            if name == part or (not use_jol and name.upper() == part.upper()):
                found = (c_ext, c_size, c_dir)
                break
        if found is None:
            raise IsoError(f"not found in image: {arc_path}")
        extent, size, is_dir = found
        if depth == len(parts) - 1:
            if is_dir:
                raise IsoError(f"not a file: {arc_path}")
            return bytes(image[extent * SECTOR:extent * SECTOR + size])
        if not is_dir:
            raise IsoError(f"not a directory: {part}")
    raise IsoError(f"not found in image: {arc_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit codes: 0 ok, 1 error, 2 usage."""
    ap = argparse.ArgumentParser(
        description="Convert a directory to an ISO 9660 (+Joliet) CD image.")
    ap.add_argument("source", nargs="?", help="source directory")
    ap.add_argument("output", nargs="?", help="output image, e.g. disk.iso")
    ap.add_argument("--label", default=None,
                    help="volume label (default: CDROM)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite output file if it exists")
    ap.add_argument("--list", dest="list_only", action="store_true",
                    help="list contents of an existing image instead of creating")
    args = ap.parse_args(argv)

    try:
        if args.list_only:
            if not args.source:
                ap.error("--list needs an image path")
            for path, size, is_dir in list_iso_contents(args.source):
                print(f"{'DIR ' if is_dir else 'FILE'} {size:>8}  {path}")
            return 0
        if not args.source or not args.output:
            ap.error("source and output are required")
        if os.path.exists(args.output) and not args.force:
            print(f"error: output already exists: {args.output} "
                  "(use --force to overwrite)", file=sys.stderr)
            return 1
        create_iso_image(args.source, args.output, args.label)
        print(f"wrote {args.output} ({os.path.getsize(args.output)} bytes)")
        return 0
    except IsoError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
