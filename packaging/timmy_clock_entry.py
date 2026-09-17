#!/usr/bin/env python3
"""PyInstaller-safe Timmy Clock entrypoint (windowed standalone widget)."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
for path in (str(SCRIPT_DIR), str(ROOT)):
    while path in sys.path:
        sys.path.remove(path)
sys.path.insert(0, str(ROOT))

from timeassist.clock_bootstrap import bootstrap_clock, ensure_stable_clock_install
from timeassist.tray import run_widget


def main() -> int:
    # When frozen, start is the folder containing TimmyClock.exe
    # (plugin root or stable %LOCALAPPDATA%\\Timmy copy).
    start = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    result = bootstrap_clock(start=start)
    if result.error:
        return run_widget(None, setup_error=result.error)
    ensure_stable_clock_install(result.plugin_root)
    return run_widget(result.db_path)


if __name__ == "__main__":
    raise SystemExit(main())
