"""Build standalone executables (no Python needed by end users).

Usage (from the repository root, with any Python 3.10+):

    python scripts/build.py

Creates an isolated build environment in .build-venv, installs the package and
PyInstaller there, runs the tests, and writes:

    dist/MHRiseExporter.exe        windowed GUI (double-click)
    dist/mhrise-exporter-cli.exe   console version of the same tool
    dist/MHRiseExporter-<version>-windows.zip   both executables + README + LICENSE

On Linux the same command produces ELF binaries without the .exe suffix.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".build-venv"
DIST = ROOT / "dist"
WORK = ROOT / "build"
IS_WIN = os.name == "nt"


def run(*cmd):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def version() -> str:
    text = (ROOT / "mhrise_exporter" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def main():
    if not venv_python().exists():
        venv.EnvBuilder(with_pip=True).create(VENV)
    py = venv_python()
    run(py, "-m", "pip", "install", "--quiet", "--upgrade", "pip")
    run(py, "-m", "pip", "install", "--quiet", "-e", ".[dev]")
    run(py, "-m", "pytest", "-q", "tests")

    shutil.rmtree(WORK, ignore_errors=True)
    common = ["--noconfirm", "--clean", "--onefile", "--log-level", "WARN",
              "--distpath", DIST, "--workpath", WORK, "--specpath", WORK, "--paths", ROOT]
    exe = ".exe" if IS_WIN else ""
    run(py, "-m", "PyInstaller", *common, "--windowed", "--name", "MHRiseExporter",
        ROOT / "scripts" / "gui_entry.py")
    run(py, "-m", "PyInstaller", *common, "--console", "--name", "mhrise-exporter-cli",
        "--exclude-module", "tkinter", ROOT / "scripts" / "entry.py")

    # Smoke test the console build (does not need a save).
    run(DIST / f"mhrise-exporter-cli{exe}", "--version")

    plat = "windows" if IS_WIN else sys.platform
    archive = DIST / f"MHRiseExporter-{version()}-{plat}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name in (f"MHRiseExporter{exe}", f"mhrise-exporter-cli{exe}"):
            z.write(DIST / name, name)
        z.write(ROOT / "README.md", "README.md")
        z.write(ROOT / "LICENSE", "LICENSE")
    print(f"\nDone:\n  {DIST / ('MHRiseExporter' + exe)}\n  {DIST / ('mhrise-exporter-cli' + exe)}\n  {archive}")


if __name__ == "__main__":
    main()
