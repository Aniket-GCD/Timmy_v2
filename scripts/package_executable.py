#!/usr/bin/env python3
"""Build a platform-native TimeAssist executable with PyInstaller.

This intentionally builds for the current platform only. A Linux machine creates a
Linux binary; Windows .exe artifacts should be built on Windows or in CI.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".packaging-venv"
BUILD_DIR = ROOT / "build" / "pyinstaller"
DIST_DIR = ROOT / "dist"
ENTRYPOINT = ROOT / "packaging" / "timeassist_entry.py"
EXECUTABLE_NAME = "timeassist.exe" if os.name == "nt" else "timeassist"


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


def build() -> Path:
    python = ensure_packaging_venv()
    DIST_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    # Remove the old platform artifact so smoke tests cannot accidentally use it.
    artifact = DIST_DIR / EXECUTABLE_NAME
    if artifact.exists():
        artifact.unlink()

    run([
        python,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        "timeassist",
        "--distpath",
        DIST_DIR,
        "--workpath",
        BUILD_DIR,
        "--specpath",
        BUILD_DIR,
        "--paths",
        ROOT,
        "--collect-submodules",
        "timeassist",
        ENTRYPOINT,
    ])

    if not artifact.exists():
        raise FileNotFoundError(f"Expected executable was not created: {artifact}")
    if os.name != "nt":
        artifact.chmod(0o755)
    return artifact


def main() -> int:
    artifact = build()
    print("\nBuilt TimeAssist executable:")
    print(f"  {artifact}")
    print("\nTry it:")
    print(f"  {artifact} --help")
    print(f"  {artifact} demo --output demo/generated-exe")
    print("\nNote: this artifact is platform-native. Build on Windows for a .exe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
