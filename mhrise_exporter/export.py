"""Talisman and Qurious-armor export, mirroring TalismanExporter.lua / QuriousExporter.lua.

Inventory: snow.data.DataManager._PlEquipBox._WeaponArmorInventoryList, i.e.
class snow.data.EquipBox -> field _WeaponArmorInventoryList (EquipmentInventoryData[]).
    _IdType == 3                      -> talisman
    _IdType == 2 and _CustomEnable    -> qurious armor
"""

from __future__ import annotations

from .gamedata import CAT_DEF, CAT_RES, CAT_RES_DOWN, CAT_SKILL, CAT_SLOT
from .save import Class, SaveFile

ID_TYPE_ARMOR = 2
ID_TYPE_TALISMAN = 3

# Element order of armorData:getCustomAddReg(0..4): fire, water, thunder, ice, dragon.
# Element-resistance buildup ids come in blocks of 10 in that same order.
RES_BLOCKS = [(89, 98), (99, 108), (109, 118), (119, 128), (129, 138)]


class ExportError(Exception):
    pass


def inventory(save: SaveFile) -> list[Class]:
    boxes = list(save.walk_classes("snow.data.EquipBox"))
    if not boxes:
        raise ExportError("no snow.data.EquipBox found in the save (is this a character slot file?)")
    return boxes[0]["_WeaponArmorInventoryList"]


class Names:
    def __init__(self, tables: dict, lang: str, empty_skill: str = ""):
        self.t = tables
        self.lang = lang
        self.empty_skill = empty_skill
        self.missing: set[str] = set()

    def _pick(self, names: dict, what: str) -> str:
        if self.lang in names:
            return names[self.lang]
        self.missing.add(what)
        return names.get("en") or next(iter(names.values()), what)

    def skill(self, sid: int) -> str:
        if sid == 0:
            return self.empty_skill
        names = self.t["skills"].get(str(sid))
        if not names:
            self.missing.add(f"skill {sid}")
            return f"Skill{sid}"
        return self._pick(names, f"skill {sid}")

    def armor(self, aid: int) -> str:
        a = self.t["armors"].get(str(aid))
        if not a or not a["names"]:
            self.missing.add(f"armor {aid:#x}")
            return f"Armor{aid:#x}"
        return self._pick(a["names"], f"armor {aid:#x}")


def _expand_slots(num_list) -> list[int]:
    """[n_lv1, n_lv2, n_lv3, n_lv4] -> slot levels in descending order."""
    out = []
    for i in range(len(num_list) - 1, -1, -1):
        out += [i + 1] * num_list[i]
    return out


def talisman_lines(save: SaveFile, names: Names) -> list[str]:
    lines = []
    for v in inventory(save):
        if v["_IdType"].s != ID_TYPE_TALISMAN:
            continue
        sk = [x.u for x in v["_TalismanSkillIdList"]]
        lv = [x.u for x in v["_TalismanSkillLvList"]]
        deco = [x.u for x in v["_TalismanDecoSlotNumList"]]  # index = slot level
        slots = []
        for level in (4, 3, 2, 1):
            slots += [level] * (deco[level] if level < len(deco) else 0)
        slots = (slots + [0, 0, 0])[:3]
        lines.append(",".join([names.skill(sk[0]), str(lv[0]), names.skill(sk[1]), str(lv[1]),
                               *map(str, slots)]))
    return lines


def apply_slot_bonus(base: list[int], points: int) -> list[int]:
    """Distribute qurious slot points over the base slots.

    Inferred rule (consistent with every slot-augmented piece checked so far):
    each point adds a new level-1 slot while the piece has fewer than 3 slots;
    otherwise it raises the highest slot that is still below level 4.
    """
    slots = sorted(base, reverse=True)
    for _ in range(points):
        if len(slots) < 3:
            slots.append(1)
        else:
            for i, s in enumerate(slots):
                if s < 4:
                    slots[i] += 1
                    break
        slots.sort(reverse=True)
    return slots


def qurious_effects(v: Class, tables: dict) -> dict:
    aid = v["_IdVal"].u
    armor = tables["armors"].get(str(aid))
    if armor is None:
        raise ExportError(f"unknown armor id {aid:#x} (game data out of date?)")
    table = armor["table"]
    eff = {"def": 0, "res": [0] * 5, "slot_points": 0, "skills": []}
    for b in v["_CustomBuildup"]:
        bid = b["_Id"].u
        if bid == 0:
            continue
        p = tables["buildups"].get(f"{table}:{bid}")
        if p is None:
            raise ExportError(f"unknown qurious bonus {bid} for table {table}")
        value = p["values"][b["_ValueIndex"].u]
        cat = p["cat"]
        if cat == CAT_DEF:
            eff["def"] += value
        elif cat in (CAT_RES, CAT_RES_DOWN):
            for i, (lo, hi) in enumerate(RES_BLOCKS):
                if lo <= bid <= hi:
                    eff["res"][i] += value
                    break
            else:
                raise ExportError(f"resistance bonus {bid} has no known element")
        elif cat == CAT_SLOT:
            eff["slot_points"] += value
        elif cat == CAT_SKILL:
            eff["skills"].append((b["_SkillId"].u, value))
        else:
            raise ExportError(f"unknown qurious category {cat} (bonus {bid})")
    base_slots = _expand_slots(armor["slots"])
    eff["base_slots"] = (base_slots + [0, 0, 0])[:3]
    eff["slots"] = (apply_slot_bonus(base_slots, eff["slot_points"]) + [0, 0, 0])[:3]
    return eff


def _merge_skills(pairs):
    """Sum levels per skill keeping first-seen order; split into ups and downs."""
    totals: dict[int, int] = {}
    for sid, value in pairs:
        totals[sid] = totals.get(sid, 0) + value
    ups = [(s, n) for s, n in totals.items() if n > 0]
    downs = [(s, n) for s, n in totals.items() if n < 0]
    return ups, downs


def qurious_lines(save: SaveFile, tables: dict, names: Names) -> list[str]:
    lines = []
    for v in inventory(save):
        if v["_IdType"].s != ID_TYPE_ARMOR or not v["_CustomEnable"].b:
            continue
        eff = qurious_effects(v, tables)
        ups, downs = _merge_skills(eff["skills"])
        parts = [names.armor(v["_IdVal"].u), str(eff["def"]), *map(str, eff["res"]),
                 *(str(n - o) for n, o in zip(eff["slots"], eff["base_slots"]))]
        skill_str = ""
        count = 0
        for sid, n in ups + downs:
            skill_str += f"{names.skill(sid)},{n},"
            count += 1
        while count < 4:
            skill_str += ",,"
            count += 1
        lines.append((",".join(parts) + "," + skill_str)[:-1])
    return lines
