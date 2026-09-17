#!/usr/bin/env python3
"""Build platform-native TimeAssist + TimmyClock executables with PyInstaller.

This intentionally builds for the current platform only. A Linux machine creates
Linux binaries; Windows .exe artifacts should be built on Windows or in CI.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".packaging-venv"
BUILD_DIR = ROOT / "build" / "pyinstaller"
DIST_DIR = ROOT / "dist"
TIMEASSIST_ENTRY = ROOT / "packaging" / "timeassist_entry.py"
CLOCK_ENTRY = ROOT / "packaging" / "timmy_clock_entry.py"
TIMEASSIST_NAME = "timeassist"
CLOCK_NAME = "TimmyClock"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(command: list[str | Path]) -> None:
    printable = " ".join(str(part) for part in command)
    print(f"$ {printable}")
    subprocess.run([str(part) for part in command], cwd=ROOT, check=True)


def ensure_packaging_venv() -> Path:
    python = venv_python()
    if not python.exists():
        print(f"Creating packaging venv: {VENV_DIR}")
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)
    run([python, "-m", "pip", "install", "--upgrade", "pip", "wheel", "pyinstaller"])
    return python


def _artifact_name(base: str) -> str:
    return f"{base}.exe" if os.name == "nt" else base


def _build_one(
    python: Path,
    *,
    name: str,
    entry: Path,
    windowed: bool,
) -> Path:
    artifact = DIST_DIR / _artifact_name(name)
    if artifact.exists():
        artifact.unlink()

    cmd: list[str | Path] = [
        python,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        name,
        "--distpath",
        DIST_DIR,
        "--workpath",
        BUILD_DIR / name,
        "--specpath",
        BUILD_DIR / name,
        "--paths",
        ROOT,
        "--collect-submodules",
        "timeassist",
    ]
    if windowed and os.name == "nt":
        cmd.append("--windowed")
    cmd.append(entry)
    run(cmd)

    if not artifact.exists():
        raise FileNotFoundError(f"Expected executable was not created: {artifact}")
    if os.name != "nt":
        artifact.chmod(0o755)
    return artifact


def build() -> tuple[Path, Path]:
    python = ensure_packaging_venv()
    DIST_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    timeassist = _build_one(
        python, name=TIMEASSIST_NAME, entry=TIMEASSIST_ENTRY, windowed=False
    )
    clock = _build_one(python, name=CLOCK_NAME, entry=CLOCK_ENTRY, windowed=True)
    return timeassist, clock


def main() -> int:
    timeassist, clock = build()
    print("\nBuilt executables:")
    print(f"  {timeassist}")
    print(f"  {clock}")
    print("\nTimmy Clock: copy TimmyClock.exe into the Timmy plugin folder")
    print("(same folder as .mcp.json), then double-click.")
    print(f"\nCLI help: {timeassist} --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
