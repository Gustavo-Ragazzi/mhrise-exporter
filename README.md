# mhrise-exporter

Offline exporter for **Monster Hunter Rise: Sunbreak (PC/Steam)**. It reads your save straight from
disk (no game running, no REFramework) and writes the two files the
[wiki-db set builder](https://mhrise.wiki-db.com/sim/?hl=en) imports:

| File | Contents | Line format |
|---|---|---|
| `ExportedTalismans.txt` | every talisman | `Skill1,Lv1,Skill2,Lv2,Slot1,Slot2,Slot3` |
| `ExportedQuriousArmors.txt` | every armor piece with Qurious Crafting | `Name,Def,Fire,Water,Thunder,Ice,Dragon,dSlot1,dSlot2,dSlot3,Skill1,Lv1,...,Skill4,Lv4` |

The output follows the `TalismanExporter.lua` and `QuriousExporter.lua` REFramework scripts it replaces.

**Read-only.** Save files are copied to a temporary folder before parsing. Nothing is ever written to
`win64_save`, and there is no encryption or re-signing code in this project.

## Quick start (no Python needed)

1. Download `MHRiseExporter-<version>-windows.zip` from the releases page, or build it yourself (see below), then unzip it.
2. Double-click **`MHRiseExporter.exe`**. The game does not need to be running.
3. The app fills everything in automatically:
   - every Steam account on the PC that has MHRise saves (pick yours from the list)
   - the save folder and SteamID64
   - the game install, found through all your Steam libraries
   - your characters, with name, HR and MR
4. Choose the name language and click **Export**.
5. Click **Copy talismans** or **Copy qurious armors**, then paste in wiki-db:
   - Charms tab, or Qurious Crafting tab
   - Import/Export
   - Import↑

For a save backup or a folder outside Steam, choose **Other folder…**, browse to the folder that contains
`data00-1.bin`, and type the SteamID64 of the account that created it. The save is encrypted with that ID. The
`userdata` folder number (steamid3) also works.

Settings are remembered in `%LOCALAPPDATA%\mhrise-exporter\`. Windows SmartScreen may warn about an unsigned exe;
choose "More info → Run anyway".

## Command line

`mhrise-exporter-cli.exe` (or `MHRiseExporter.exe` with arguments) offers the same functions for scripts:

```bash
mhrise-exporter list
```

```bash
mhrise-exporter export --slot 1 --out .
```

Options for `export`:

| Option | Meaning |
|---|---|
| `--slot 1\|2\|3` | character slot. If omitted, the only used slot is picked. Hunter name, HR and MR of each slot are printed. |
| `--steamid N` | SteamID64, or the `userdata` folder number (steamid3). Required when several accounts have MHRise saves. |
| `--save-dir DIR` | folder holding `data00-1.bin` / `data00NSlot.bin`, e.g. a backup copy |
| `--game-dir DIR` | game install, used for names and armor data (found automatically from Steam libraries) |
| `--gamedata FILE` | use a previously extracted `gamedata.json` instead of the game install |
| `--lang CODE` | name language: `en` (default), `ja`, `pt-br`, `fr`, `de`, `ko`, `zh-cn`, ... |
| `--empty-skill TEXT` | text written for a talisman's missing 2nd skill (default: empty) |
| `--dump FILE.json` | also dump the raw talisman/armor inventory records (`--dump-all` for every record, `--dump-only` to skip exporting) |

Compare against the Lua scripts' files (as multisets of lines; order doesn't matter):

```bash
mhrise-exporter validate --ref-talismans Save001_ExportedTalismans.txt --ref-qurious Save001_ExportedQuriousArmors.txt
```

### Importing into wiki-db

1. Talismans: open the talisman tab, then Import/Export, paste the contents of `ExportedTalismans.txt`, and click Import.
2. Qurious: open the "Qurious Crafting" tab, then Import/Export, paste `ExportedQuriousArmors.txt`, and click Import.

## How it works

1. **Container**: `DSSS` v2 header, flag `0x04` (Citrus), payload at `0x10`, `u64` plaintext length, then a MurmurHash3
   checksum (seed `0xFFFFFFFF`).
2. **Citrus decryption** ([citrus.py](mhrise_exporter/citrus.py)): the key comes from the SteamID64 (`d = ~steamid64`),
   with EC-ElGamal over one of 128 curves (the curve is found automatically). Each `0x40000` block is AES-128-CBC
   and is verified with SHA3-256.
3. **Class stream** ([save.py](mhrise_exporter/save.py)): self-describing RE Engine serialization. Fields are
   identified by `murmur3(utf8 name)`.
4. **Inventory**: `snow.data.EquipBox._WeaponArmorInventoryList` (`EquipmentInventoryData[]`).
5. **Game tables** ([gamedata.py](mhrise_exporter/gamedata.py)): extracted once from your own `re_chunk_000.pak`
   (plus patches) and cached in `%LOCALAPPDATA%\mhrise-exporter\gamedata.json`, so no Capcom data ships with this
   tool. The cache rebuilds itself when the game updates.

### Fields used

| Item | Raw save fields | Derived with game tables |
|---|---|---|
| Talisman (`_IdType == 3`) | `_TalismanSkillIdList[2]`, `_TalismanSkillLvList[2]`, `_TalismanDecoSlotNumList[5]` (index = slot level) | skill names from `PlayerSkill_Name(_MR).msg` |
| Qurious armor (`_IdType == 2 && _CustomEnable`) | `_IdVal` (PlArmorId), `_CustomBuildup[7]` = (`_Id`, `_ValueIndex`, `_SkillId`) | `ArmorBaseData.user` (`_DecorationsNumList`, `_CustomTableNo`), `CustomBuildupBaseUserData.user` keyed by (`_CustomTableNo`, `_Id`), giving `_CategoryId` + `_ValueTable[_ValueIndex]`; names from `A_<Part>_Name(_MR).msg` |

How the Lua getters are reproduced:

- `get_CustomAddDef` is the sum of category 13 values.
- `getCustomAddReg(i)` is the sum of category 14 and 15 values. Bonus ids 89–98 are fire, 99–108 water,
  109–118 thunder, 119–128 ice and 129–138 dragon.
- Slots: the category 19 values give slot points. Each point adds a new Lv1 slot while the piece has fewer than
  3 slots; otherwise it raises the highest slot below Lv4. This rule was inferred from mounted decorations and confirmed against
  the Lua exporters' output. The delta against the original sorted slots is what gets exported.
- `getCustomSkillUpList` / `getCustomSkillDownList`: category 20 values summed per `_SkillId`. Increases come first,
  then decreases, each in buildup order.

## Building the executables

Only the person building needs Python (3.10+). The result runs on any Windows 10/11 PC without Python.

```bash
python scripts/build.py
```

The script creates an isolated `.build-venv`, installs the package with PyInstaller, runs the tests, and writes:

| File | Purpose |
|---|---|
| `dist/MHRiseExporter.exe` | windowed GUI; with arguments it behaves like the CLI |
| `dist/mhrise-exporter-cli.exe` | console version |
| `dist/MHRiseExporter-<version>-windows.zip` | both executables plus README and LICENSE, ready to share |

Pushing a `v*` tag to GitHub runs [.github/workflows/build.yml](.github/workflows/build.yml), which builds on
`windows-latest` and attaches the zip to the release.

Development setup:

```bash
python -m venv .venv
```

```bash
.venv\Scripts\pip install -e .[dev]
```

```bash
.venv\Scripts\python -m mhrise_exporter gui
```

Linux works the same way, and `scripts/build.py` produces native binaries there. Saves are found under
`~/.steam/steam/userdata/...` (Proton), and the game install under `steamapps/common/MonsterHunterRise`.

## Limitations

- **Steam only.** The Switch DEFLATE container is parsed, but it is untested.
- **Validated against the REFramework Lua exporters** on a real save (2026-11-08): 94 talismans and 29 qurious
  armors are identical line by line, in the same order. This confirms:
  - the slot distribution rule (it was inferred, not read from game code)
  - the element order (fire, water, thunder, ice, dragon)
  - the skill ordering and level deltas

  The only difference is line endings: the Lua scripts write CRLF, this tool writes LF.
- The talisman and RSZ layouts match game v16.0.x. If a future layout changes, the reader stops with a clear error
  instead of emitting wrong data.

## Credits and licenses

This project is MIT-licensed. It ports code and research from:

| Project | License | Used for |
|---|---|---|
| [jinghaihan/mhrise-save-converter](https://github.com/jinghaihan/mhrise-save-converter) | MIT | Citrus decryption, curve table (`curves.py`), DSSS container, class-stream parser |
| [wwylele/mhrice](https://github.com/wwylele/mhrice) | MIT / Apache-2.0 | PAK reader + entry-table key guessing, GMSG decoding, USER/RSZ layout, id-to-message-tag mapping, qurious category ids |
| [ChevalGrand/mhrise-save-editor](https://github.com/ChevalGrand/mhrise-save-editor) | MIT | field/class hash constants (`EquipBox`, `_WeaponArmorInventoryList`) used in tests |
| [kvasszn/ree-save-editor](https://github.com/kvasszn/ree-save-editor) | GPL-3.0 | original save-format research; its RSZ schema dump was consulted during development only (no code or data copied) |

Monster Hunter Rise is © CAPCOM. Game data is read from your own installation at run time and is not distributed.
