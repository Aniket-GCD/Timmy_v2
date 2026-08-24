from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "package_plugin.py"
PLUGIN_BINARY = ROOT / "plugin" / "timeassist" / "bin" / "timeassist.exe"


class PackagePluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workdir = Path(self.tmp.name)
        if PLUGIN_BINARY.exists():
            original = PLUGIN_BINARY.read_bytes()
            self.addCleanup(lambda: PLUGIN_BINARY.write_bytes(original))
        else:
            self.addCleanup(lambda: PLUGIN_BINARY.unlink() if PLUGIN_BINARY.exists() else None)

    def run_packager(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_rejects_non_windows_binary_for_default_exe_name(self) -> None:
        fake = self.workdir / "timeassist"
        fake.write_bytes(b"\x7fELFnot-a-windows-exe")
        out = self.workdir / "timeassist-plugin.zip"

        result = self.run_packager("--exe", str(fake), "--out", str(out))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Windows PE", result.stdout + result.stderr)
        self.assertFalse(out.exists())

    def test_rejects_binary_name_with_path_components(self) -> None:
        fake = self.workdir / "timeassist.exe"
        fake.write_bytes(b"MZfake-pe")
        out = self.workdir / "timeassist-plugin.zip"

        result = self.run_packager("--exe", str(fake), "--out", str(out), "--binary-name", "../evil.exe")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("plain filename", result.stdout + result.stderr)
        self.assertFalse(out.exists())

    def test_rejects_binary_name_with_windows_path_separator(self) -> None:
        fake = self.workdir / "timeassist.exe"
        fake.write_bytes(b"MZfake-pe")
        out = self.workdir / "timeassist-plugin.zip"

        result = self.run_packager("--exe", str(fake), "--out", str(out), "--binary-name", r"..\evil.exe")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("plain filename", result.stdout + result.stderr)
        self.assertFalse(out.exists())

    def test_rejects_non_manifest_binary_name(self) -> None:
        fake = self.workdir / "timeassist.exe"
        fake.write_bytes(b"MZfake-pe")
        out = self.workdir / "timeassist-plugin.zip"

        result = self.run_packager("--exe", str(fake), "--out", str(out), "--binary-name", "timeassist")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timeassist.exe", result.stdout + result.stderr)
        self.assertFalse(out.exists())

    def test_packages_pe_binary_without_mutating_source_plugin_directory(self) -> None:
        fake = self.workdir / "timeassist.exe"
        fake.write_bytes(b"MZfake-pe-for-package-test")
        out = self.workdir / "timeassist-plugin.zip"

        result = self.run_packager("--exe", str(fake), "--out", str(out))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(PLUGIN_BINARY.exists(), "packager should not leave a binary in the source plugin directory")
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(zf.read("timeassist/bin/timeassist.exe"), fake.read_bytes())
            names = zf.namelist()
            self.assertIn("timeassist/.claude-plugin/plugin.json", names)
            self.assertIn("timeassist/config/supabase.json", names)


if __name__ == "__main__":
    unittest.main()
