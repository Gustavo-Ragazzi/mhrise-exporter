"""Read-only RE Engine USER / RSZ reader for the handful of game tables we need.

Container layout ported from wwylele/mhrice (MIT/Apache-2.0), src/user.rs and
src/rsz/mod.rs. RSZ instance data is not self-describing, so each type we read
has a hand-written field spec below (layouts match game v16.0.x; the CRC check
catches future layout changes).
"""

from __future__ import annotations

import struct

from .murmur3 import hash_utf8


class RszError(Exception):
    pass


# kind: (struct fmt, size)
_SCALARS = {
    "bool": ("<?", 1), "u8": ("<B", 1), "s8": ("<b", 1),
    "u16": ("<H", 2), "s16": ("<h", 2),
    "u32": ("<I", 4), "s32": ("<i", 4),
}

# type name -> (expected crc or None, [(field, kind, is_array)])
SPECS = {
    "snow.data.ArmorBaseUserData": (0x2B3920A5, [("_Param", "obj", True)]),
    "snow.data.ArmorBaseUserData.Param": (None, [
        ("_Id", "u32", False), ("_IsValid", "bool", False), ("_Series", "s32", False),
        ("_SortId", "u32", False), ("_ModelId", "u32", False), ("_Rare", "u8", False),
        ("_Value", "u32", False), ("_BuyValue", "u32", False), ("_SexualEquipable", "s32", False),
        ("_SymbolColor1", "bool", False), ("_SymbolColor2", "bool", False),
        ("_DefVal", "s32", False), ("_FireRegVal", "s32", False), ("_WaterRegVal", "s32", False),
        ("_IceRegVal", "s32", False), ("_ThunderRegVal", "s32", False), ("_DragonRegVal", "s32", False),
        ("_BuildupTable", "s32", False), ("_BuffFormula", "s32", False),
        ("_DecorationsNumList", "u32", True), ("_SkillList", "u8", True), ("_SkillLvList", "s32", True),
        ("_IdAfterExChange", "u32", False), ("_CustomTableNo", "u32", False), ("_CustomCost", "u32", False),
    ]),
    "snow.data.CustomBuildupBaseUserData": (0x2783EA03, [("_Param", "obj", True)]),
    "snow.data.CustomBuildupBaseUserData.Param": (None, [
        ("_TableNo", "u32", False), ("_Id", "u16", False), ("_CategoryId", "u16", False),
        ("_Lv", "s32", False), ("_IconColor", "s32", False), ("_Cost", "s32", False),
        ("_ValueTable", "s32", True), ("_LotTable", "u32", True),
    ]),
    "snow.data.DecorationsBaseUserData": (None, [("_Param", "obj", True)]),
    "snow.data.DecorationsBaseUserData.Param": (None, [
        ("_Id", "u32", False), ("_SortId", "u32", False), ("_Rare", "u8", False),
        ("_IconColor", "s32", False), ("_BasePrice", "u32", False), ("_DecorationLv", "s32", False),
        ("_SkillIdList", "u8", True), ("_SkillLvList", "s32", True),
    ]),
}
_BY_HASH = {hash_utf8(name): name for name in SPECS}


def _read_user_rsz(raw: bytes) -> tuple[bytes, int]:
    if raw[:4] != b"USR\0":
        raise RszError("not a USER file")
    rsz_off = struct.unpack_from("<Q", raw, 32)[0]
    return raw, rsz_off


def parse_user(raw: bytes) -> list[dict]:
    """Deserialize a .user file and return its root objects as nested dicts."""
    raw, base = _read_user_rsz(raw)
    if raw[base:base + 4] != b"RSZ\0":
        raise RszError("missing RSZ block")
    version, root_count, type_count, extern_count, _pad = struct.unpack_from("<IIIII", raw, base + 4)
    if version != 0x10:
        raise RszError(f"unexpected RSZ version {version}")
    type_off, data_off, _str_off = struct.unpack_from("<QQQ", raw, base + 24)
    roots = struct.unpack_from(f"<{root_count}I", raw, base + 48)
    types = [struct.unpack_from("<II", raw, base + type_off + 8 * i) for i in range(type_count)]
    if extern_count:
        raise RszError("external user references are not supported")

    data_base = base + data_off
    pos = data_base
    nodes: list = [None]

    def align(n):
        nonlocal pos
        rel = pos - data_base
        pos = data_base + ((rel + n - 1) & ~(n - 1))

    def scalar(kind):
        nonlocal pos
        fmt, size = _SCALARS[kind]
        align(size)
        v = struct.unpack_from(fmt, raw, pos)[0]
        pos += size
        return v

    for th, crc in types[1:]:
        name = _BY_HASH.get(th)
        if name is None:
            raise RszError(f"unsupported RSZ type {th:08x}")
        want_crc, fields = SPECS[name]
        if want_crc is not None and want_crc != crc:
            raise RszError(f"{name}: layout CRC {crc:08x} differs from the supported one")
        obj = {"__type": name}
        for fname, kind, is_array in fields:
            if is_array:
                align(4)
                n = struct.unpack_from("<I", raw, pos)[0]
                pos += 4
                if kind == "obj":
                    vals = []
                    for _ in range(n):
                        align(4)
                        vals.append(nodes[struct.unpack_from("<I", raw, pos)[0]])
                        pos += 4
                else:
                    vals = [scalar(kind) for _ in range(n)]
                obj[fname] = vals
            elif kind == "obj":
                align(4)
                obj[fname] = nodes[struct.unpack_from("<I", raw, pos)[0]]
                pos += 4
            else:
                obj[fname] = scalar(kind)
        nodes.append(obj)

    if pos != len(raw):
        raise RszError(f"RSZ parse ended at {pos:#x}, file size {len(raw):#x} (layout mismatch)")
    return [nodes[r] for r in roots]
