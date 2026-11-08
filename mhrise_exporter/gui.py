"""Small Tkinter front-end. Everything is auto-detected; every field can be overridden."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from . import __version__
from .citrus import CitrusError
from .core import (UserError, load_slot, read_hunters, run_export, steamid_from_save_dir,
                   to_steamid64, write_outputs)
from .gamedata import default_cache_dir
from .steam import find_accounts, find_game_dir

WIKI_DB_URL = "https://mhrise.wiki-db.com/sim/?hl=en"

LANG_CHOICES = [
    ("English", "en"), ("日本語", "ja"), ("Português (Brasil)", "pt-br"), ("Español (Latinoamérica)", "es-419"),
    ("Español", "es"), ("Français", "fr"), ("Deutsch", "de"), ("Italiano", "it"), ("Polski", "pl"),
    ("Русский", "ru"), ("한국어", "ko"), ("简体中文", "zh-cn"), ("繁體中文", "zh-tw"), ("العربية", "ar"),
]
CUSTOM_ACCOUNT = "Other folder…"


def _default_out_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "MHRise Exporter"


def _settings_path() -> Path:
    return default_cache_dir() / "gui-settings.json"


def _load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict):
    try:
        p = _settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _open_folder(path: Path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=12)
        self.root = root
        self.settings = _load_settings()
        self.jobs: queue.Queue = queue.Queue()
        self.busy = False
        self.accounts = []
        self.hunters = []
        self.curve = None
        self.result = None

        root.title(f"MH Rise Talisman & Qurious Exporter {__version__}")
        root.minsize(640, 520)
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self.account_var = tk.StringVar()
        self.save_dir_var = tk.StringVar()
        self.steamid_var = tk.StringVar()
        self.game_dir_var = tk.StringVar()
        self.hunter_var = tk.StringVar()
        self.lang_var = tk.StringVar()
        self.out_var = tk.StringVar(value=self.settings.get("out_dir") or str(_default_out_dir()))

        r = 0
        ttk.Label(self, text="Steam account").grid(row=r, column=0, sticky="w", pady=3)
        self.account_cb = ttk.Combobox(self, textvariable=self.account_var, state="readonly")
        self.account_cb.grid(row=r, column=1, columnspan=2, sticky="ew", pady=3)
        self.account_cb.bind("<<ComboboxSelected>>", lambda e: self.on_account())

        r += 1
        ttk.Label(self, text="Save folder").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(self, textvariable=self.save_dir_var).grid(row=r, column=1, sticky="ew", pady=3)
        ttk.Button(self, text="Browse…", command=self.browse_save).grid(row=r, column=2, padx=(6, 0))

        r += 1
        ttk.Label(self, text="SteamID64").grid(row=r, column=0, sticky="w", pady=3)
        sid_row = ttk.Frame(self)
        sid_row.grid(row=r, column=1, columnspan=2, sticky="ew")
        ttk.Entry(sid_row, textvariable=self.steamid_var, width=22).pack(side="left")
        ttk.Label(sid_row, text="  filled in automatically; the save is encrypted with it",
                  foreground="gray").pack(side="left")

        r += 1
        ttk.Label(self, text="Game folder").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(self, textvariable=self.game_dir_var).grid(row=r, column=1, sticky="ew", pady=3)
        ttk.Button(self, text="Browse…", command=self.browse_game).grid(row=r, column=2, padx=(6, 0))

        r += 1
        ttk.Label(self, text="Character").grid(row=r, column=0, sticky="w", pady=3)
        self.hunter_cb = ttk.Combobox(self, textvariable=self.hunter_var, state="readonly")
        self.hunter_cb.grid(row=r, column=1, sticky="ew", pady=3)
        ttk.Button(self, text="Reload", command=self.load_hunters).grid(row=r, column=2, padx=(6, 0))

        r += 1
        ttk.Label(self, text="Name language").grid(row=r, column=0, sticky="w", pady=3)
        self.lang_cb = ttk.Combobox(self, textvariable=self.lang_var, state="readonly",
                                    values=[n for n, _ in LANG_CHOICES])
        self.lang_cb.grid(row=r, column=1, sticky="w", pady=3)
        code = self.settings.get("lang", "en")
        self.lang_var.set(next((n for n, c in LANG_CHOICES if c == code), "English"))

        r += 1
        ttk.Label(self, text="Output folder").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(self, textvariable=self.out_var).grid(row=r, column=1, sticky="ew", pady=3)
        ttk.Button(self, text="Browse…", command=self.browse_out).grid(row=r, column=2, padx=(6, 0))

        r += 1
        buttons = ttk.Frame(self)
        buttons.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        self.export_btn = ttk.Button(buttons, text="Export", command=self.export)
        self.export_btn.pack(side="left")
        self.copy_tal_btn = ttk.Button(buttons, text="Copy talismans", state="disabled",
                                       command=lambda: self.copy("talismans"))
        self.copy_tal_btn.pack(side="left", padx=(8, 0))
        self.copy_qur_btn = ttk.Button(buttons, text="Copy qurious armors", state="disabled",
                                       command=lambda: self.copy("qurious"))
        self.copy_qur_btn.pack(side="left", padx=(8, 0))
        self.open_btn = ttk.Button(buttons, text="Open output folder", state="disabled",
                                   command=lambda: _open_folder(Path(self.out_var.get())))
        self.open_btn.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Open wiki-db", command=lambda: webbrowser.open(WIKI_DB_URL)).pack(side="right")

        r += 1
        self.progress = ttk.Progressbar(self, mode="determinate", value=0)
        self.progress.grid(row=r, column=0, columnspan=3, sticky="ew")

        r += 1
        self.log_box = tk.Text(self, height=12, wrap="word", state="disabled", font="TkDefaultFont",
                               relief="flat", padx=6, pady=4)
        self.log_box.grid(row=r, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        self.rowconfigure(r, weight=1)

        self.log("Read-only: save files are copied to a temporary folder; the originals are never modified.")
        self.after(100, self.poll)
        self.detect()

    # --- helpers -----------------------------------------------------------
    def log(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def threadsafe_log(self, msg: str):
        self.jobs.put(("log", msg))

    def run_bg(self, work, done):
        if self.busy:
            return
        self.busy = True
        self.export_btn.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def target():
            try:
                self.jobs.put(("done", done, work(), None))
            except Exception as e:  # noqa: BLE001 - shown to the user
                self.jobs.put(("done", done, None, e))

        threading.Thread(target=target, daemon=True).start()

    def poll(self):
        try:
            while True:
                job = self.jobs.get_nowait()
                if job[0] == "log":
                    self.log(job[1])
                else:
                    _, done, value, err = job
                    self.busy = False
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.export_btn.configure(state="normal")
                    if err is not None:
                        self.show_error(err)
                    else:
                        done(value)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def show_error(self, err: Exception):
        if isinstance(err, CitrusError):
            text = (f"Could not decrypt the save.\n\n{err}\n\nCheck that the SteamID64 belongs to the "
                    "Steam account that owns this save folder.")
        elif isinstance(err, (UserError, FileNotFoundError, ValueError)):
            text = str(err)
        else:
            text = f"{type(err).__name__}: {err}"
            self.log("".join(traceback.format_exception(err)))
        self.log("Error: " + text.splitlines()[0])
        messagebox.showerror("MH Rise Exporter", text)

    # --- detection ---------------------------------------------------------
    def detect(self):
        self.accounts = find_accounts()
        labels = [f"{a.persona or 'Steam user'}  ({a.steamid64})" for a in self.accounts] + [CUSTOM_ACCOUNT]
        self.account_cb.configure(values=labels)
        last = self.settings.get("steamid")
        idx = next((i for i, a in enumerate(self.accounts) if str(a.steamid64) == str(last)), 0)
        if self.accounts:
            self.account_cb.current(idx)
        else:
            self.account_cb.set(CUSTOM_ACCOUNT)
            self.save_dir_var.set(self.settings.get("save_dir", ""))
            self.steamid_var.set(self.settings.get("custom_steamid", ""))
            self.log("No Monster Hunter Rise save folder found in Steam. Pick the win64_save folder with Browse….")

        game = self.settings.get("game_dir")
        if not game or not (Path(game) / "re_chunk_000.pak").exists():
            found = find_game_dir()
            game = str(found) if found else ""
        self.game_dir_var.set(game)
        if not game:
            self.log("Game install not found. Pick the MonsterHunterRise folder (it contains re_chunk_000.pak).")
        self.on_account()

    def on_account(self):
        label = self.account_var.get()
        for a, text in zip(self.accounts, self.account_cb.cget("values")):
            if text == label:
                self.save_dir_var.set(str(a.save_dir))
                self.steamid_var.set(str(a.steamid64))
                break
        self.load_hunters()

    def current_account(self) -> tuple[Path, int]:
        save_dir = Path(self.save_dir_var.get().strip())
        if not save_dir.is_dir():
            raise UserError("Pick the save folder (…\\userdata\\<id>\\1446780\\remote\\win64_save).")
        sid_text = self.steamid_var.get().strip()
        sid = to_steamid64(sid_text) if sid_text.isdigit() else steamid_from_save_dir(save_dir)
        if sid is None:
            raise UserError("Enter the SteamID64 of the account that owns this save.")
        self.steamid_var.set(str(sid))
        return save_dir, sid

    def load_hunters(self):
        if not self.save_dir_var.get().strip():
            return
        try:
            save_dir, sid = self.current_account()
        except UserError as e:
            self.log(str(e))
            return
        self.log(f"Reading characters from {save_dir} …")
        self.run_bg(lambda: read_hunters(save_dir, sid), self.hunters_loaded)

    def hunters_loaded(self, value):
        self.hunters, self.curve = value
        used = [h for h in self.hunters if h.used]
        self.hunter_cb.configure(values=[h.label() for h in used])
        if used:
            last = self.settings.get("slot")
            self.hunter_cb.current(next((i for i, h in enumerate(used) if h.slot == last), 0))
            self.log(f"Found {len(used)} character(s).")
        else:
            self.hunter_cb.set("")
            self.log("No characters in this save.")

    # --- browse ------------------------------------------------------------
    def browse_save(self):
        d = filedialog.askdirectory(title="Select the win64_save folder")
        if d:
            self.account_cb.set(CUSTOM_ACCOUNT)
            self.save_dir_var.set(d)
            sid = steamid_from_save_dir(Path(d))
            self.steamid_var.set(str(sid) if sid else "")
            self.load_hunters()

    def browse_game(self):
        d = filedialog.askdirectory(title="Select the MonsterHunterRise game folder")
        if d:
            if not (Path(d) / "re_chunk_000.pak").exists():
                messagebox.showwarning("MH Rise Exporter", "That folder does not contain re_chunk_000.pak.")
            self.game_dir_var.set(d)

    def browse_out(self):
        d = filedialog.askdirectory(title="Select the output folder")
        if d:
            self.out_var.set(d)

    # --- export ------------------------------------------------------------
    def export(self):
        try:
            save_dir, sid = self.current_account()
            used = [h for h in self.hunters if h.used]
            idx = self.hunter_cb.current()
            if idx < 0 or idx >= len(used):
                raise UserError("Pick a character first (click Reload if the list is empty).")
            slot = used[idx].slot
            game_dir = Path(self.game_dir_var.get().strip()) if self.game_dir_var.get().strip() else None
            if game_dir is None or not (game_dir / "re_chunk_000.pak").exists():
                raise UserError("Pick the Monster Hunter Rise game folder (it contains re_chunk_000.pak). "
                                "It is needed for skill and armor names.")
            lang = dict(LANG_CHOICES).get(self.lang_var.get(), "en")
            out_dir = Path(self.out_var.get().strip() or _default_out_dir())
        except UserError as e:
            self.show_error(e)
            return
        curve = self.curve
        self.settings.update({"steamid": sid, "save_dir": str(save_dir), "custom_steamid": str(sid),
                              "game_dir": str(game_dir), "slot": slot, "lang": lang, "out_dir": str(out_dir)})
        _save_settings(self.settings)
        self.log(f"Exporting slot {slot} …")

        def work():
            save = load_slot(save_dir, sid, slot, curve)
            result = run_export(save, game_dir, lang, log=self.threadsafe_log)
            write_outputs(result, out_dir)
            return result

        self.run_bg(work, self.exported)

    def exported(self, result):
        self.result = result
        self.log(f"Wrote {len(result.talismans)} talismans → {result.files[0]}")
        self.log(f"Wrote {len(result.qurious)} qurious armors → {result.files[1]}")
        if result.missing_names:
            self.log(f"{len(result.missing_names)} names are not translated in this language; English was used.")
        self.log("In wiki-db: open the Charms or Qurious Crafting tab → Import/Export → paste → Import↑.")
        for b in (self.copy_tal_btn, self.copy_qur_btn, self.open_btn):
            b.configure(state="normal")

    def copy(self, which: str):
        if not self.result:
            return
        lines = self.result.talismans if which == "talismans" else self.result.qurious
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines) + "\n")
        self.log(f"Copied {len(lines)} {which} lines to the clipboard.")


def main():
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
