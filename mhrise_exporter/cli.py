"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .citrus import CitrusError
from .core import (UserError, inventory_tree, load_slot, read_hunters, run_export,
                   steamid_from_save_dir, to_steamid64, write_outputs)
from .export import ExportError
from .msg import LANGUAGES
from .pak import PakError
from .rsz import RszError
from .save import SaveError
from .steam import find_accounts, find_game_dir


def _log(msg: str):
    print(msg, file=sys.stderr)


def _pick_account(args) -> tuple[Path, int]:
    if args.save_dir:
        save_dir = Path(args.save_dir)
        sid = to_steamid64(args.steamid) if args.steamid else steamid_from_save_dir(save_dir)
        if sid is None:
            raise UserError("cannot infer the SteamID from --save-dir; pass --steamid")
        return save_dir, sid
    accounts = find_accounts()
    if args.steamid:
        sid = to_steamid64(args.steamid)
        for a in accounts:
            if a.steamid64 == sid:
                return a.save_dir, sid
        raise UserError(f"no MHRise save folder for SteamID {sid}; pass --save-dir")
    if not accounts:
        raise UserError("no MHRise Steam save folder found; pass --save-dir and --steamid")
    if len(accounts) > 1:
        lines = "\n".join(f"  {a.steamid64}  ({a.persona or 'unknown'})  {a.save_dir}" for a in accounts)
        raise UserError(f"several Steam accounts have MHRise saves; pick one with --steamid:\n{lines}")
    return accounts[0].save_dir, accounts[0].steamid64


def cmd_list(args):
    for a in find_accounts():
        print(f"SteamID64 {a.steamid64}  ({a.persona or 'unknown'})  {a.save_dir}")
    print(f"Game install: {find_game_dir() or 'not found'}")


def cmd_export(args):
    save_dir, sid = _pick_account(args)
    hunters, curve = read_hunters(save_dir, sid)
    for h in hunters:
        _log("  " + h.label())
    slot = args.slot
    if slot is None:
        used = [h.slot for h in hunters if h.used]
        if len(used) != 1:
            raise UserError("pick a character with --slot 1|2|3")
        slot = used[0]
    save = load_slot(save_dir, sid, slot, curve)

    if args.dump:
        items = inventory_tree(save, args.dump_all)
        Path(args.dump).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        _log(f"Inventory dump written to {args.dump} ({len(items)} items)")
        if args.dump_only:
            return

    game_dir = Path(args.game_dir) if args.game_dir else find_game_dir()
    result = run_export(save, game_dir, args.lang, args.empty_skill, args.gamedata,
                        args.rebuild_gamedata, log=_log)
    for p, lines in zip(write_outputs(result, Path(args.out)), (result.talismans, result.qurious)):
        _log(f"{p}: {len(lines)} entries")
    if result.missing_names:
        _log(f"warning: no '{args.lang}' name for {len(result.missing_names)} entries, used English instead")


def cmd_validate(args):
    """Compare our output with the REFramework Lua exports (as multisets of lines)."""
    for mine, ref in ((args.mine_talismans, args.ref_talismans), (args.mine_qurious, args.ref_qurious)):
        if not ref:
            continue
        a = Path(mine).read_text(encoding="utf-8").splitlines()
        b = Path(ref).read_text(encoding="utf-8-sig").splitlines()
        ca, cb = Counter(a), Counter(b)
        only_a, only_b = ca - cb, cb - ca
        print(f"{Path(ref).name}: reference {len(b)} lines, ours {len(a)} lines, "
              f"{'IDENTICAL as a multiset' if not only_a and not only_b else 'DIFFERENT'}")
        for line, n in only_b.items():
            print(f"  only in reference (x{n}): {line}")
        for line, n in only_a.items():
            print(f"  only in ours      (x{n}): {line}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mhrise-exporter",
                                 description="Offline talisman / Qurious armor exporter for MH Rise: Sunbreak (Steam).")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="show detected Steam accounts and game install").set_defaults(func=cmd_list)
    sub.add_parser("gui", help="open the graphical interface").set_defaults(func=lambda a: _gui())

    ex = sub.add_parser("export", help="write ExportedTalismans.txt and ExportedQuriousArmors.txt")
    ex.add_argument("--slot", type=int, choices=[1, 2, 3], help="character slot (default: the only used one)")
    ex.add_argument("--steamid", help="SteamID64 or the userdata folder number (steamid3)")
    ex.add_argument("--save-dir", help="folder containing data00-1.bin / data00NSlot.bin")
    ex.add_argument("--game-dir", help="MonsterHunterRise install folder (for names and armor data)")
    ex.add_argument("--gamedata", help="use a previously extracted gamedata.json instead of the game install")
    ex.add_argument("--rebuild-gamedata", action="store_true", help="re-extract game tables even if cached")
    ex.add_argument("--lang", default="en", choices=LANGUAGES, help="language for names (default: en)")
    ex.add_argument("--empty-skill", default="", help="text for the missing 2nd talisman skill (default: empty)")
    ex.add_argument("--out", default=".", help="output folder (default: current folder)")
    ex.add_argument("--dump", metavar="FILE.json", help="also dump talisman/armor inventory records as JSON")
    ex.add_argument("--dump-all", action="store_true", help="with --dump: include every inventory record")
    ex.add_argument("--dump-only", action="store_true", help="with --dump: do not export")
    ex.set_defaults(func=cmd_export)

    va = sub.add_parser("validate", help="compare outputs against the Lua exporters' files")
    va.add_argument("--mine-talismans", default="ExportedTalismans.txt")
    va.add_argument("--mine-qurious", default="ExportedQuriousArmors.txt")
    va.add_argument("--ref-talismans")
    va.add_argument("--ref-qurious")
    va.set_defaults(func=cmd_validate)
    return ap


def _gui():
    from .gui import main as gui_main
    gui_main()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    try:
        args.func(args)
    except CitrusError as e:
        raise SystemExit(f"error: decryption failed: {e}")
    except (UserError, SaveError, ExportError, PakError, RszError, FileNotFoundError) as e:
        raise SystemExit(f"error: {e}")
    return 0
