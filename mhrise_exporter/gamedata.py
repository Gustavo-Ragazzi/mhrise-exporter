"""Static game tables (names, armor base stats, qurious tables).

They are extracted once from the user's own game install (re_chunk_000.pak +
patches) and cached as JSON, so no Capcom data is redistributed with this tool.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .msg import LANGUAGES, parse_msg
from .pak import open_game_paks
from .rsz import parse_user

CACHE_VERSION = 1
MSG_SUFFIXES = ["539100710", "17"]
PARTS = ["Head", "Chest", "Arm", "Waist", "Leg"]

# snow.data.DataDef.CustomBuildupCategoryId values used by armor.
CAT_DEF = 13
CAT_RES = 14
CAT_RES_DOWN = 15  # resistance penalty that comes with Augment (Skills+)
CAT_SLOT = 19
CAT_SKILL = 20


def default_cache_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "mhrise-exporter"


def skill_msg_tag(skill_id: int) -> str | None:
    """PlEquipSkillId -> msg tag (mapping from mhrice, src/rsz/skill.rs)."""
    if skill_id == 0:
        return None
    if skill_id <= 0x6F:
        return f"PlayerSkill_{skill_id - 1:03}"
    return f"PlayerSkill_{skill_id - 0x70 + 200:03}"


def _clean(text: str) -> str | None:
    if not text or "#Rejected#" in text:
        return None
    return text


def _msg_map(pak, rel: str) -> dict[str, list[str]]:
    return {e["name"]: e["content"] for e in parse_msg(pak.read_any(rel + ".msg", MSG_SUFFIXES))}


def _names(content: list[str] | None) -> dict[str, str]:
    if not content:
        return {}
    return {lang: t for lang, t in zip(LANGUAGES, content) if _clean(t)}


def build_tables(game_dir: Path, log=print) -> dict:
    pak = open_game_paks(game_dir)
    try:
        log("Reading skill names...")
        base = "data/Define/Player/Skill/PlEquipSkill/PlayerSkill_Name"
        skill_msgs = _msg_map(pak, base)
        skill_msgs_mr = _msg_map(pak, base + "_MR")
        skills = {}
        for sid in range(1, 256):
            tag = skill_msg_tag(sid)
            content = (skill_msgs_mr.get(f"{tag}_Name_MR") or skill_msgs_mr.get(f"{tag}_Name")
                       or skill_msgs.get(f"{tag}_Name"))
            names = _names(content)
            if names:
                skills[str(sid)] = names

        log("Reading armor names and base data...")
        armor_msgs = {}
        for part in PARTS:
            for suffix in ("", "_MR"):
                armor_msgs.update(_msg_map(pak, f"data/Define/Player/Armor/{part}/A_{part}_Name{suffix}"))
        armors = {}
        params = parse_user(pak.read_any("data/Define/Player/Armor/ArmorBaseData.user", ["2"]))[0]["_Param"]
        for p in params:
            aid = p["_Id"]
            kind = (aid >> 20) & 0xF  # 0x0C1xxxxx head ... 0x0C5xxxxx leg
            if not p["_IsValid"] or not 1 <= kind <= 5:
                continue
            tag = f"A_{PARTS[kind - 1]}_{aid & 0xFFFF:03}_Name"
            armors[str(aid)] = {
                "names": _names(armor_msgs.get(tag)),
                "slots": p["_DecorationsNumList"],
                "table": p["_CustomTableNo"],
                "def": p["_DefVal"],
            }

        log("Reading Qurious Crafting tables...")
        buildups = {}
        cb = parse_user(pak.read_any(
            "data/Define/Player/Equip/CustomBuildup/CustomBuildupBaseUserData.user", ["2"]))[0]["_Param"]
        for p in cb:
            key = f"{p['_TableNo']}:{p['_Id']}"
            buildups[key] = {"cat": p["_CategoryId"], "values": p["_ValueTable"]}

        log("Reading decoration levels...")
        decos = {}
        for p in parse_user(pak.read_any(
                "data/Define/Player/Equip/Decorations/DecorationsBaseData.user", ["2"]))[0]["_Param"]:
            decos[str(p["_Id"])] = p["_DecorationLv"]
    finally:
        pak.close()
    return {"version": CACHE_VERSION, "skills": skills, "armors": armors,
            "buildups": buildups, "decos": decos}


def _fingerprint(game_dir: Path) -> str:
    parts = []
    for p in sorted(Path(game_dir).glob("re_chunk_000.pak*")):
        st = p.stat()
        parts.append(f"{p.name}:{st.st_size}:{int(st.st_mtime)}")
    return "|".join(parts)


def load_tables(game_dir: Path | None, cache_dir: Path | None = None, gamedata_file: Path | None = None,
                rebuild: bool = False, log=print) -> dict:
    if gamedata_file:
        return json.loads(Path(gamedata_file).read_text(encoding="utf-8"))
    if game_dir is None:
        raise FileNotFoundError(
            "Monster Hunter Rise install not found; pass --game-dir or --gamedata")
    cache_dir = Path(cache_dir or default_cache_dir())
    cache = cache_dir / "gamedata.json"
    fp = _fingerprint(game_dir)
    if cache.exists() and not rebuild:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("version") == CACHE_VERSION and data.get("fingerprint") == fp:
                return data
        except (OSError, ValueError):
            pass
    data = build_tables(game_dir, log=log)
    data["fingerprint"] = fp
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    log(f"Game data cached in {cache}")
    return data


if __name__ == "__main__":  # pragma: no cover
    print(len(build_tables(Path(sys.argv[1]))["skills"]))
