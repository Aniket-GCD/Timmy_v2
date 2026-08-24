#!/usr/bin/env python3
"""Assemble the timeassist Cowork plugin zip.

The release bundle includes a freshly built Windows executable under
``timeassist/bin/timeassist.exe`` inside the zip. The packager validates that the
binary is Windows-shaped by default and writes it directly into the archive so a
local packaging attempt cannot leave a stale binary in the source plugin tree.
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugin" / "timeassist"


def _is_windows_pe(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(2) == b"MZ"


def _should_skip_plugin_file(rel: Path, binary_name: str) -> bool:
    rel_text = rel.as_posix()
    if rel_text == "bin/.gitignore":  # dev placeholder, not for the bundle
        return True
    if rel_text == f"bin/{binary_name}":  # avoid stale source-tree binaries
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Package the timeassist plugin zip.")
    parser.add_argument("--exe", required=True, help="path to the built timeassist binary")
    parser.add_argument("--out", required=True, help="output zip path")
    parser.add_argument("--binary-name", default="timeassist.exe", help="filename for the bundled binary inside bin/")
    parser.add_argument("--allow-non-windows-binary", action="store_true", help="dev-only escape hatch for packaging a non-PE binary")
    args = parser.parse_args()

    exe = Path(args.exe)
    binary_name = Path(args.binary_name)
    if binary_name.name != args.binary_name or args.binary_name in {"", ".", ".."} or "/" in args.binary_name or "\\" in args.binary_name:
        parser.error("--binary-name must be a plain filename with no path components")
    if args.binary_name != "timeassist.exe":
        parser.error("--binary-name must be timeassist.exe because the plugin manifest launches bin/timeassist.exe")
    if not exe.exists() or not exe.is_file():
        parser.error(f"built binary not found: {exe}")
    if not args.allow_non_windows_binary and not _is_windows_pe(exe):
        parser.error(f"{exe} is not a Windows PE executable (missing MZ header); build on Windows or pass --allow-non-windows-binary for a dev-only package")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Nest under a top-level plugin folder (timeassist/...) inside the zip; the
    # Cowork uploader expects the plugin directory at the archive root, not its
    # contents loose at the root.
    top = PLUGIN_DIR.name
    supabase_config = ROOT / "config" / "supabase.json"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PLUGIN_DIR.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(PLUGIN_DIR)
            if _should_skip_plugin_file(rel, args.binary_name):
                continue
            zf.write(path, f"{top}/{rel.as_posix()}")
        zf.write(exe, f"{top}/bin/{args.binary_name}")
        if supabase_config.is_file():
            zf.write(supabase_config, f"{top}/config/supabase.json")

    print(f"Wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
