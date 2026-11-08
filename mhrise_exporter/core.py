"""High-level, UI-independent operations shared by the CLI and the GUI."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .export import Names, inventory, qurious_lines, talisman_lines
from .gamedata import load_tables
from .save import Class, Scalar, load_save
from .steam import STEAMID64_BASE

TALISMAN_FILE = "ExportedTalismans.txt"
QURIOUS_FILE = "ExportedQuriousArmors.txt"


class UserError(Exception):
    """A problem the user can fix (wrong folder, missing slot, ...)."""


def to_steamid64(value) -> int:
    n = int(str(value).strip())
    return n if n >= STEAMID64_BASE else n + STEAMID64_BASE


def steamid_from_save_dir(save_dir: Path) -> int | None:
    """.../userdata/<steamid3>/1446780/remote/win64_save -> SteamID64."""
    try:
        name = Path(save_dir).resolve().parents[2].name
        return to_steamid64(name) if name.isdigit() else None
    except (IndexError, OSError):
        return None


@dataclass
class Hunter:
    slot: int
    name: str
    hr: int
    mr: int

    @property
    def used(self) -> bool:
        return self.hr >= 0

    def label(self) -> str:
        if not self.used:
            return f"Slot {self.slot}: (empty)"
        return f"Slot {self.slot}: {self.name}  (HR {self.hr} / MR {self.mr})"


@dataclass
class ExportResult:
    talismans: list[str]
    qurious: list[str]
    files: list[Path] = field(default_factory=list)
    missing_names: set[str] = field(default_factory=set)


def _copy(src: Path, tmp: Path) -> Path:
    if not src.exists():
        raise UserError(f"{src} does not exist")
    dst = tmp / src.name
    shutil.copy2(src, dst)  # never parse the live save in place
    return dst


def read_hunters(save_dir: Path, steamid64: int) -> tuple[list[Hunter], int | None]:
    """Character summaries from data00-1.bin, plus the Citrus curve index for reuse."""
    sysfile = Path(save_dir) / "data00-1.bin"
    if not sysfile.exists():
        slots = [Hunter(i, "?", 0, 0) for i in (1, 2, 3)
                 if (Path(save_dir) / f"data{i:03}Slot.bin").exists()]
        return slots, None
    with tempfile.TemporaryDirectory(prefix="mhrise-exporter-") as t:
        s = load_save(_copy(sysfile, Path(t)), steamid64)
    for _, entry in s.entries:
        arr = entry.get("_HunterArray")
        if isinstance(arr, list):
            return [Hunter(i + 1, h.get("_HunterName") or "", h["_HunterRank"].s, h["_MasterRank"].s)
                    for i, h in enumerate(arr)], s.curve_index
    return [], s.curve_index


def load_slot(save_dir: Path, steamid64: int, slot: int, curve_index: int | None = None):
    slot_file = Path(save_dir) / f"data{slot:03}Slot.bin"
    if not slot_file.exists():
        raise UserError(f"character slot {slot} has no save file ({slot_file.name})")
    with tempfile.TemporaryDirectory(prefix="mhrise-exporter-") as t:
        return load_save(_copy(slot_file, Path(t)), steamid64, curve_index=curve_index)


def run_export(save, game_dir: Path | None, lang: str = "en", empty_skill: str = "",
               gamedata_file: Path | None = None, rebuild: bool = False, log=print) -> ExportResult:
    tables = load_tables(game_dir, gamedata_file=gamedata_file, rebuild=rebuild, log=log)
    names = Names(tables, lang, empty_skill=empty_skill)
    return ExportResult(talisman_lines(save, names), qurious_lines(save, tables, names),
                        missing_names=names.missing)


def write_outputs(result: ExportResult, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for fname, lines in ((TALISMAN_FILE, result.talismans), (QURIOUS_FILE, result.qurious)):
        p = out_dir / fname
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(line + "\n" for line in lines))
        files.append(p)
    result.files = files
    return files


# --- debug dump -------------------------------------------------------------

INVENTORY_FIELDS = [
    "_IdType", "_IdVal", "_IsSetGuildCard", "_BowgunCustomizeType", "_PairInsectInventoryIndex",
    "_HyakuryuSkillIdList", "_PrevHyakuryuSkillId", "_HyakuryuModelId", "_HyakuryuColorData",
    "_BuildupPoint", "_IsLock", "_TalismanDecoSlotNumList", "_TalismanSkillIdList",
    "_TalismanSkillLvList", "_CustomEnable", "_CustomCount", "_CustomOpenIdArray", "_CustomBuildup",
    "_CustomBuildupType", "_DecoIdList", "_HyakuryuDecoId", "_Id", "_ValueIndex", "_SkillId",
]


def inventory_tree(save, include_all: bool = False) -> list:
    from .murmur3 import hash_utf8
    names = {hash_utf8(n): n for n in INVENTORY_FIELDS}

    def tree(v):
        if isinstance(v, Scalar):
            return v.u
        if isinstance(v, list):
            return [tree(x) for x in v]
        if isinstance(v, Class):
            return {names.get(h, f"0x{h:08x}"): tree(x) for h, _, x in v.fields}
        return v

    items = [tree(v) for v in inventory(save)]
    return items if include_all else [x for x in items if x.get("_IdType") in (2, 3)]
