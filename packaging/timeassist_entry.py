#!/usr/bin/env python3
"""PyInstaller-safe TimeAssist entrypoint."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
for path in (str(SCRIPT_DIR), str(ROOT)):
    while path in sys.path:
        sys.path.remove(path)
sys.path.insert(0, str(ROOT))

from timeassist.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
