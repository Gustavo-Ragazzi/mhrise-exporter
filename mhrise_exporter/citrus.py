"""Read-only port of the Steam "Citrus" save decryption.

Ported from jinghaihan/mhrise-save-converter (MIT), src/crypto/citrus.rs, which
builds on research from kvasszn/ree-save-editor. Only decryption is
implemented: this tool never writes saves.

Layout of the encrypted region (repeated per 0x40000 bytes of plaintext):
    key[16] iv[16]                      outer AES key/iv (plain)
    ecc_keys[0x200]                     AES-encrypted with key/iv; holds 4 EC-ElGamal
                                        ciphertexts encoding the real key/iv halves
    data[0x40000]                       AES-128-CBC with the real key/iv
    sha3_256[0x20]                      over key|iv|ecc_keys(plain)|plain[:0x40000-0x20]
followed by a trailing 0x1000 block that is not needed for decryption.
"""

from __future__ import annotations

import hashlib

from Crypto.Cipher import AES

from .curves import CURVES

KEY_IV_SIZE = 0x20
ENC_KEYS_SIZE = 0x200
ENC_DATA_SIZE = 0x40000
HASH_SIZE = 0x20
BLOCK_SIZE = KEY_IV_SIZE + ENC_KEYS_SIZE + ENC_DATA_SIZE + HASH_SIZE
TRAILER_SIZE = 0x1000


class CitrusError(Exception):
    pass


def _point_add(p1, p2, a, mod):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 != y2 or y1 == 0):
        return None
    if x1 == x2:
        slope = (3 * x1 * x1 + a) * pow(2 * y1, -1, mod) % mod
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, mod) % mod
    x3 = (slope * slope - x1 - x2) % mod
    y3 = (slope * (x1 - x3) - y1) % mod
    return (x3, y3)


def _scalar_mult(k, point, a, mod):
    result = None
    addend = point
    while k > 0:
        if k & 1:
            result = _point_add(result, addend, a, mod)
        if addend is not None:
            addend = _point_add(addend, addend, a, mod)
        k >>= 1
    return result


def _on_curve(pt, curve) -> bool:
    p, a, b, _, _ = curve
    x, y = pt
    return 0 <= x < p and 0 <= y < p and (y * y - (x * x * x + a * x + b)) % p == 0


def _aes_decrypt(buf: bytes, key: bytes, iv: bytes) -> bytes:
    plain = bytearray(AES.new(key, AES.MODE_CBC, iv).decrypt(buf))
    patch = bytes(k ^ v for k, v in zip(key, iv))
    patch_int = int.from_bytes(patch * ((len(plain) - 16) // 16), "little")
    tail = int.from_bytes(plain[16:], "little") ^ patch_int
    plain[16:] = tail.to_bytes(len(plain) - 16, "little")
    return bytes(plain)


class Citrus:
    def __init__(self, steamid64: int, curve_index: int | None = None):
        self.steamid64 = steamid64
        self.d = (~steamid64) & 0xFFFFFFFFFFFFFFFF
        self.curve_index = curve_index

    def _decrypt_segment(self, seg: bytes, curve) -> int | None:
        p, a, _, _, _ = curve
        c1 = (int.from_bytes(seg[0:32], "little"), int.from_bytes(seg[32:64], "little"))
        c2 = (int.from_bytes(seg[64:96], "little"), int.from_bytes(seg[96:128], "little"))
        if not _on_curve(c1, curve) or not _on_curve(c2, curve):
            return None
        s = _scalar_mult(self.d, c1, a, p)
        if s is None:
            return None
        pm = _point_add(c2, (s[0], (-s[1]) % p), a, p)
        if pm is None or not _on_curve(pm, curve):
            return None
        x = pm[0] // 100
        return x if x <= 0xFFFFFFFFFFFFFFFF else None

    def _decrypt_keys(self, ecc_keys: bytes, curve):
        halves = []
        for i in range(4):
            v = self._decrypt_segment(ecc_keys[i * 128:(i + 1) * 128], curve)
            if v is None:
                return None
            halves.append(v.to_bytes(8, "little"))
        return halves[0] + halves[1], halves[2] + halves[3]

    def _decrypt_block(self, block: bytes, curve, plain_len: int) -> bytes | None:
        key, iv = block[0:16], block[16:32]
        ecc_keys = _aes_decrypt(block[32:32 + ENC_KEYS_SIZE], key, iv)
        keys = self._decrypt_keys(ecc_keys, curve)
        if keys is None:
            return None
        real_key, real_iv = keys
        start = 32 + ENC_KEYS_SIZE
        dec = bytearray(_aes_decrypt(block[start:start + ENC_DATA_SIZE], real_key, real_iv))
        dec[plain_len:] = bytes(ENC_DATA_SIZE - plain_len)
        h = hashlib.sha3_256()
        h.update(key)
        h.update(iv)
        h.update(ecc_keys)
        h.update(bytes(dec[:ENC_DATA_SIZE - HASH_SIZE]))
        if h.digest() != block[0x40220:0x40240]:
            return None
        return bytes(dec[:plain_len])

    def decrypt(self, buf: bytes, decrypted_len: int) -> bytes:
        encrypted_len = len(buf) - TRAILER_SIZE
        if encrypted_len <= 0 or encrypted_len % BLOCK_SIZE:
            raise CitrusError("encrypted payload has an unexpected size")
        num_blocks = encrypted_len // BLOCK_SIZE
        if not ((num_blocks - 1) * ENC_DATA_SIZE < decrypted_len <= num_blocks * ENC_DATA_SIZE):
            raise CitrusError("decrypted length does not match the number of blocks")

        def plain_len(i):
            return ENC_DATA_SIZE if i < num_blocks - 1 else decrypted_len - i * ENC_DATA_SIZE

        if self.curve_index is None:
            first = buf[0:BLOCK_SIZE]
            for idx, curve in enumerate(CURVES):
                if self._decrypt_block(first, curve, plain_len(0)) is not None:
                    self.curve_index = idx
                    break
            else:
                raise CitrusError(
                    "could not decrypt the save with this SteamID64 "
                    "(wrong account, or the file belongs to another Steam user)"
                )
        curve = CURVES[self.curve_index]
        out = bytearray()
        for i in range(num_blocks):
            part = self._decrypt_block(buf[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE], curve, plain_len(i))
            if part is None:
                raise CitrusError(f"block {i} failed its SHA3 integrity check (corrupted save?)")
            out += part
        return bytes(out)
