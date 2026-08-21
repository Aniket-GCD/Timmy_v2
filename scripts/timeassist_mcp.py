#!/usr/bin/env python3
"""MCP stdio server entrypoint for TimeAssist.

Launched by Claude Code / Cowork as a local stdio MCP server. Anchors the
working directory to the repo root so relative state/ and exports/ paths
resolve the same way the CLI assumes, regardless of where it is launched.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(prog="timeassist-mcp", description="TimeAssist MCP stdio server.")
    parser.add_argument(
        "--db",
        default=os.environ.get("TIMEASSIST_DB", "state/timeassist.sqlite"),
        help="path to the local SQLite database (default: state/timeassist.sqlite under repo root)",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    from timeassist.mcp_server import serve

    serve(args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
