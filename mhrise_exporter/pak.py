"""Minimal read-only RE Engine PAK (KPKA v4) reader.

Ported from wwylele/mhrice (MIT/Apache-2.0), src/pak.rs. Supports the
encrypted entry table used by MHRise (flag 8, key recovered by statistical
guessing exactly as mhrice does) and per-file encryption type 1.
"""

from __future__ import annotations

import base64
import struct
import zlib
from collections import Counter
from pathlib import Path

from .murmur3 import hash_utf16

_SUB_KEY_MOD = int.from_bytes(base64.b64decode("E9eciYiRSBDXqniu+FnffTxDoNC7Nne18FwCr2XYdwM="), "little")
_SUB_KEY_EXP = int.from_bytes(base64.b64decode("wMJ3H1s0agHH1NeFLkIrOxY6FxMW6oMwMN8/9CWTIAE="), "little")

ENTRY_SIZE = 0x30


class PakError(Exception):
    pass


def _guess_key(buf: bytes) -> bytes:
    P0, P1 = 32, 29

    def index(x, y):
        x, y = max(x, y), min(x, y)
        return x * (x + 1) // 2 + y

    counters = [Counter() for _ in range(P0 * (P0 + 1) // 2)]
    for i, b in enumerate(buf):
        if i % 8 == 0:
            continue
        counters[index(i % P0, i % P1)][(b - i) & 0xFF] += 1
    pads = []
    for c in counters:
        if c:
            v, f = c.most_common(1)[0]
            pads.append((v, f) if f > 100 else None)
        else:
            pads.append(None)
    odd = [(i, pads[index(i, i)][1]) for i in range(P0)
           if pads[index(i, i)] is not None and pads[index(i, i)][0] % 2]
    if not odd:
        raise PakError("cannot guess PAK key (no pivot)")
    pa = max(odd, key=lambda t: t[1])[0]
    rest = [t for t in odd if t[0] != pa and pads[index(t[0], pa)] is not None]
    if not rest:
        raise PakError("cannot guess PAK key (no second pivot)")
    pb = max(rest, key=lambda t: t[1])[0]
    key = [None] * 32
    for a in range(256):
        if (a * a) & 0xFF != pads[index(pa, pa)][0]:
            continue
        for b in range(256):
            if (b * b) & 0xFF == pads[index(pb, pb)][0] and (a * b) & 0xFF == pads[index(pa, pb)][0]:
                key[pa], key[pb] = a, b
                break
        if key[pa] is not None:
            break
    a, b = key[pa], key[pb]
    for i in range(32):
        if key[i] is not None:
            continue
        for c in range(256):
            pai, pbi = pads[index(pa, i)], pads[index(pb, i)]
            if pai and pbi and (a * c) & 0xFF == pai[0] and (b * c) & 0xFF == pbi[0]:
                key[i] = c
                break
    if None in key:
        raise PakError("cannot guess PAK key")
    return bytes(key)


def _decrypt_table(buf: bytes, key: bytes) -> bytes:
    pad = bytes(((key[i % 32] * key[i % 29] + i) & 0xFF) for i in range(len(buf)))
    return (int.from_bytes(buf, "little") ^ int.from_bytes(pad, "little")).to_bytes(len(buf), "little")


class PakReader:
    """Reads several PAKs; later files (patches) override earlier ones."""

    def __init__(self, paths: list[Path]):
        self.files = []
        self.index: dict[int, tuple[int, tuple]] = {}
        for n, p in enumerate(paths):
            f = open(p, "rb")
            head = f.read(16)
            if head[:4] != b"KPKA":
                raise PakError(f"{p}: not a PAK file")
            version, flags, count = struct.unpack_from("<HHI", head, 4)
            if version != 4:
                raise PakError(f"{p}: unsupported PAK version")
            if flags & 1:
                raise PakError(f"{p}: unsupported PAK flag 1")
            table = f.read(count * ENTRY_SIZE)
            if flags & 8:
                table = _decrypt_table(table, _guess_key(table))
            for e in range(count):
                h, off, clen, ulen = struct.unpack_from("<QQQQ", table, e * ENTRY_SIZE)
                fmt, flag, enc = struct.unpack_from("<BBB", table, e * ENTRY_SIZE + 32)
                self.index[h] = (n, (off, clen, ulen, fmt, enc))
            self.files.append(f)

    def close(self):
        for f in self.files:
            f.close()

    @staticmethod
    def path_hash(path: str) -> int:
        return hash_utf16(path.lower()) | (hash_utf16(path.upper()) << 32)

    def has(self, path: str) -> bool:
        return self.path_hash(path) in self.index

    def read(self, path: str) -> bytes:
        h = self.path_hash(path)
        if h not in self.index:
            raise PakError(f"file not found in PAK: {path}")
        n, (off, clen, ulen, fmt, enc) = self.index[h]
        f = self.files[n]
        f.seek(off)
        data = f.read(clen)
        if enc == 1:
            plain_len = struct.unpack_from("<Q", data, 0)[0]
            enc_data = data[8:]
            out = bytearray(((plain_len + 7) // 8) * 8)
            for i in range(len(out) // 8):
                chunk = enc_data[i * 0x80:(i + 1) * 0x80]
                pp = int.from_bytes(chunk[:0x40], "little")
                q = int.from_bytes(chunk[0x40:], "little")
                r = q // pow(pp, _SUB_KEY_EXP, _SUB_KEY_MOD)
                out[i * 8:i * 8 + 8] = r.to_bytes(8, "little")
            data = bytes(out[:plain_len])
        elif enc != 0:
            raise PakError(f"unsupported PAK encryption {enc} for {path}")
        if fmt == 0:
            return data
        if fmt in (1, 0x11):
            return zlib.decompress(data, -15)
        if fmt == 2:
            try:
                from compression import zstd  # Python 3.14+
                return zstd.decompress(data)
            except ImportError:
                import zstandard
                return zstandard.ZstdDecompressor().decompress(data, max_output_size=ulen)
        raise PakError(f"unsupported PAK compression {fmt} for {path}")

    def read_any(self, rel: str, suffixes: list[str]) -> bytes:
        for suf in suffixes:
            for pre in ("natives/STM/", "natives/MSG/"):
                for tail in ("", ".x64", ".STM"):
                    p = f"{pre}{rel}.{suf}{tail}"
                    if self.has(p):
                        return self.read(p)
        raise PakError(f"file not found in PAK: {rel}")


def open_game_paks(game_dir: Path) -> PakReader:
    game_dir = Path(game_dir)
    base = game_dir / "re_chunk_000.pak"
    if not base.exists():
        raise PakError(f"re_chunk_000.pak not found in {game_dir}")
    patches = sorted(game_dir.glob("re_chunk_000.pak.patch_*.pak"))
    return PakReader([base, *patches])
