"""DSSS container + self-describing class stream of MHRise save files (read-only).

Container layout (Steam): "DSSS" u32 version(=2) u32 flags | pad to 0x10 |
Citrus payload | u64 decrypted_len | u32 murmur3(seed 0xFFFFFFFF) of everything before.

The class stream format follows jinghaihan/mhrise-save-converter (MIT),
src/payload.rs: a sequence of (u32 native_hash, Class) where
    Class  = u32 field_count, u32 class_hash, Field*
    Field  = u32 name_hash, i32 type, value
    type -1 -> Array, 0x11 -> Class, 0x0f -> String(utf16), else Scalar(u32 size, bytes)
Field and class hashes are murmur3_32(utf8 name, 0xFFFFFFFF).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from .citrus import Citrus
from .murmur3 import hash_utf8, murmur3_32

FLAG_CITRUS = 0x04
FLAG_DEFLATE = 0x08

T_ARRAY = -1
T_STRING = 0x0F
T_CLASS = 0x11
ARRAY_MARKER = 0xFFEEFFEE


class SaveError(Exception):
    pass


@dataclass
class Class:
    hash: int
    fields: list = field(default_factory=list)  # list[(name_hash, type, value)]

    def get(self, name: str, default=None):
        h = hash_utf8(name)
        for fh, _, v in self.fields:
            if fh == h:
                return v
        return default

    def __getitem__(self, name: str):
        h = hash_utf8(name)
        for fh, _, v in self.fields:
            if fh == h:
                return v
        raise KeyError(name)


@dataclass
class Scalar:
    type: int
    raw: bytes

    @property
    def u(self) -> int:
        return int.from_bytes(self.raw, "little")

    @property
    def s(self) -> int:
        return int.from_bytes(self.raw, "little", signed=True)

    @property
    def b(self) -> bool:
        return self.raw != b"\x00" * len(self.raw)


class _Reader:
    __slots__ = ("d", "o", "base")

    def __init__(self, data: bytes, base: int):
        self.d = data
        self.o = 0
        self.base = base

    def align(self, n: int):
        a = self.base + self.o
        self.o = ((a + n - 1) & ~(n - 1)) - self.base

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.o)[0]
        self.o += 4
        return v

    def take(self, n: int) -> bytes:
        v = self.d[self.o:self.o + n]
        if len(v) != n:
            raise SaveError("unexpected end of payload")
        self.o += n
        return v


def _read_class(r: _Reader) -> Class:
    count = r.u32()
    h = r.u32()
    if count > (len(r.d) - r.o) // 8:
        raise SaveError(f"class {h:08x} has an impossible field count")
    c = Class(h)
    for _ in range(count):
        fh = r.u32()
        ft = r.i32()
        if ft == T_ARRAY:
            v = _read_array(r)
        elif ft == T_CLASS:
            v = _read_class(r)
        elif ft == T_STRING:
            v = _read_string(r)
        else:
            r.align(4)
            size = r.u32()
            v = Scalar(ft, _read_sized(r, size))
        r.align(4)
        c.fields.append((fh, ft, v))
    return c


def _read_sized(r: _Reader, size: int) -> bytes:
    if size == 0:
        raise SaveError("zero-sized scalar")
    if size != 1:
        # Same bit trick as the reference implementation (also for non-power-of-two sizes).
        a = r.base + r.o
        r.o = ((a + size - 1) & ~(size - 1)) - r.base
    return r.take(size)


def _read_string(r: _Reader) -> str:
    r.align(4)
    n = r.u32()
    return r.take(n * 2).decode("utf-16-le", errors="replace").rstrip("\x00")


def _read_array(r: _Reader) -> list:
    r.align(4)
    member_type = r.i32()
    member_size = r.u32()
    n = r.u32()
    array_type = r.i32()
    if array_type not in (0, 1):
        raise SaveError(f"unsupported array type {array_type}")
    if array_type == 1 and struct.unpack_from("<I", r.d, r.o)[0] == ARRAY_MARKER:
        r.u32()
        r.take(4 * n)
    out = []
    for _ in range(n):
        if array_type == 1:
            out.append(_read_class(r))
        elif member_type == T_ARRAY:
            out.append(_read_array(r))
        elif member_type == T_STRING:
            out.append(_read_string(r))
        else:
            out.append(Scalar(member_type, _read_sized(r, member_size)))
    r.align(4)
    return out


def parse_class_stream(data: bytes, base: int) -> list[tuple[int, Class]]:
    r = _Reader(data, base)
    entries = []
    while r.o < len(data):
        rest = data[r.o:]
        if len(rest) < 12 and not any(rest):
            break
        nh = r.u32()
        entries.append((nh, _read_class(r)))
    return entries


@dataclass
class SaveFile:
    path: Path
    payload: bytes
    entries: list
    curve_index: int | None

    def walk_classes(self, class_name: str):
        """Yield every Class instance whose class hash matches class_name."""
        target = hash_utf8(class_name)
        stack = [c for _, c in reversed(self.entries)]
        while stack:
            c = stack.pop()
            if c.hash == target:
                yield c
            for _, _, v in reversed(c.fields):
                if isinstance(v, Class):
                    stack.append(v)
                elif isinstance(v, list):
                    stack.extend(x for x in reversed(v) if isinstance(x, Class))


def load_save(path: Path, steamid64: int, curve_index: int | None = None,
              verify_checksum: bool = True) -> SaveFile:
    data = Path(path).read_bytes()
    if len(data) < 16 or data[:4] != b"DSSS":
        raise SaveError(f"{path.name}: not a MHRise DSSS save file")
    version, flags = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise SaveError(f"{path.name}: unsupported DSSS version {version}")
    if verify_checksum:
        stored = struct.unpack_from("<I", data, len(data) - 4)[0]
        if murmur3_32(data[:-4]) != stored:
            raise SaveError(f"{path.name}: outer checksum mismatch (file corrupted or truncated)")
    if flags & FLAG_CITRUS:
        decrypted_len = struct.unpack_from("<Q", data, len(data) - 12)[0]
        citrus = Citrus(steamid64, curve_index)
        payload = citrus.decrypt(data[16:len(data) - 12], decrypted_len)
        base = 16
        curve_index = citrus.curve_index
    elif flags & FLAG_DEFLATE:
        import zlib
        comp_size = struct.unpack_from("<I", data, 16 + 12)[0]
        payload = zlib.decompress(data[16 + 24:16 + 24 + comp_size], -15)
        base = 12
    else:
        raise SaveError(f"{path.name}: unsupported save flags {flags:#x}")
    return SaveFile(Path(path), payload, parse_class_stream(payload, base), curve_index)
