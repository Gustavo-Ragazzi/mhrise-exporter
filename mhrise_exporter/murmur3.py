"""MurmurHash3 (x86, 32-bit). RE Engine uses seed 0xFFFFFFFF everywhere."""

import struct

_C1 = 0xCC9E2D51
_C2 = 0x1B873593
_M = 0xFFFFFFFF


def murmur3_32(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    length = len(data)
    h1 = seed
    rounded = length & ~3
    for (k1,) in struct.iter_unpack("<I", memoryview(data)[:rounded]):
        k1 = (k1 * _C1) & _M
        k1 = ((k1 << 15) | (k1 >> 17)) & _M
        k1 = (k1 * _C2) & _M
        h1 ^= k1
        h1 = ((h1 << 13) | (h1 >> 19)) & _M
        h1 = (h1 * 5 + 0xE6546B64) & _M
    tail = data[rounded:]
    k1 = 0
    if len(tail) >= 3:
        k1 ^= tail[2] << 16
    if len(tail) >= 2:
        k1 ^= tail[1] << 8
    if len(tail) >= 1:
        k1 ^= tail[0]
        k1 = (k1 * _C1) & _M
        k1 = ((k1 << 15) | (k1 >> 17)) & _M
        k1 = (k1 * _C2) & _M
        h1 ^= k1
    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & _M
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & _M
    h1 ^= h1 >> 16
    return h1


def hash_utf8(name: str) -> int:
    """Field/class hash used by the save payload."""
    return murmur3_32(name.encode("utf-8"))


def hash_utf16(name: str) -> int:
    """Hash used by PAK paths and MSG entry names."""
    return murmur3_32(name.encode("utf-16-le"))
