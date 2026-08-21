#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from timeassist.demo import DEFAULT_DEMO_DATE, run_demo


if __name__ == "__main__":
    output = Path("demo") / "generated"
    summary = run_demo(output, DEFAULT_DEMO_DATE, open_html=False)
    print(f"Stakeholder demo generated in {summary['output_dir']}")
