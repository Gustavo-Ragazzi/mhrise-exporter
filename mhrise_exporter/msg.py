"""RE Engine GMSG (.msg) reader. Ported from wwylele/mhrice (MIT/Apache-2.0), src/msg.rs."""

from __future__ import annotations

import struct

from .murmur3 import hash_utf16

_KEY = bytes([0xCF, 0xCE, 0xFB, 0xF8, 0xEC, 0x0A, 0x33, 0x66, 0x93, 0xA9, 0x1D, 0x93, 0x50, 0x39, 0x5F, 0x09])

# Language index order inside the msg file.
LANGUAGES = ["ja", "en", "fr", "it", "de", "es", "ru", "pl", "nl", "pt", "pt-br", "ko",
             "zh-tw", "zh-cn", "fi", "sv", "da", "no", "cs", "hu", "sk", "ar", "tr", "bg",
             "el", "ro", "th", "uk", "vi", "id", "fc", "hi", "es-419"]


class MsgError(Exception):
    pass


def _u16str(data: bytes, off: int) -> str:
    end = off
    while data[end:end + 2] != b"\x00\x00":
        end += 2
    return data[off:end].decode("utf-16-le")


def parse_msg(raw: bytes) -> list[dict]:
    """Returns entries in file order: {"name": str, "content": [str per language]}."""
    version, magic, sixteen = struct.unpack_from("<I4sQ", raw, 0)
    if magic != b"GMSG" or sixteen != 0x10 or version not in (17, 539100710):
        raise MsgError("not a supported GMSG file")
    entry_count, attr_count, lang_count = struct.unpack_from("<III", raw, 16)
    off = (28 + 7) & ~7
    data_off, _p_off, _lang_off, _attr_types_off, _attr_names_off = struct.unpack_from("<QQQQQ", raw, off)
    off += 40
    entry_offsets = struct.unpack_from(f"<{entry_count}Q", raw, off)

    enc = raw[data_off:]
    dec = bytearray(len(enc))
    prev = 0
    for i, cur in enumerate(enc):
        dec[i] = cur ^ prev ^ _KEY[i & 0xF]
        prev = cur
    dec = bytes(dec)

    entries = []
    for eo in entry_offsets:
        h = struct.unpack_from("<I", raw, eo + 20)[0]
        name_off, _attrs = struct.unpack_from("<QQ", raw, eo + 24)
        content_offs = struct.unpack_from(f"<{lang_count}Q", raw, eo + 40)
        name = _u16str(dec, name_off - data_off)
        if hash_utf16(name) != h:
            raise MsgError(f"msg entry hash mismatch for {name!r}")
        entries.append({
            "name": name,
            "content": [_u16str(dec, c - data_off) for c in content_offs],
        })
    return entries
