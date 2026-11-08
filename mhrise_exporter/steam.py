"""Locate Steam, the MHRise save folders and the game install."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

APP_ID = "1446780"
STEAMID64_BASE = 76561197960265728


@dataclass
class Account:
    steamid3: int
    save_dir: Path
    persona: str | None = None

    @property
    def steamid64(self) -> int:
        return STEAMID64_BASE + self.steamid3


def steam_roots() -> list[Path]:
    roots = []
    if os.name == "nt":
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots.append(Path(r"C:\Program Files (x86)\Steam"))
    else:
        home = Path.home()
        roots += [home / ".steam/steam", home / ".local/share/Steam",
                  home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    seen, out = set(), []
    for r in roots:
        try:
            key = r.resolve()
        except OSError:
            continue
        if key not in seen and (r / "steamapps").is_dir():
            seen.add(key)
            out.append(r)
    return out


def _personas(root: Path) -> dict[int, str]:
    f = root / "config" / "loginusers.vdf"
    out = {}
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for sid, body in re.findall(r'"(\d{17})"\s*\{(.*?)\}', text, re.S):
        m = re.search(r'"PersonaName"\s*"([^"]*)"', body)
        if m:
            out[int(sid) - STEAMID64_BASE] = m.group(1)
    return out


def find_accounts() -> list[Account]:
    accounts = []
    for root in steam_roots():
        personas = _personas(root)
        ud = root / "userdata"
        if not ud.is_dir():
            continue
        for d in ud.iterdir():
            save = d / APP_ID / "remote" / "win64_save"
            if d.name.isdigit() and save.is_dir():
                accounts.append(Account(int(d.name), save, personas.get(int(d.name))))
    return accounts


def find_game_dir() -> Path | None:
    for root in steam_roots():
        libs = [root]
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            for p in re.findall(r'"path"\s*"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
                libs.append(Path(p.replace("\\\\", "\\")))
        except OSError:
            pass
        for lib in libs:
            g = lib / "steamapps" / "common" / "MonsterHunterRise"
            if (g / "re_chunk_000.pak").exists():
                return g
    return None
