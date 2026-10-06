from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeassist import actions
from timeassist import clock_bootstrap as cb
from timeassist import paths


class ClockBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "timeassist"
        self.root.mkdir()
        self.local = Path(self.tmp.name) / "empty-local"
        self.roaming = Path(self.tmp.name) / "empty-roaming"
        self.local.mkdir()
        self.roaming.mkdir()

    def _appdata_env(self, **extra: str) -> dict[str, str]:
        env = {
            "LOCALAPPDATA": str(self.local),
            "APPDATA": str(self.roaming),
        }
        env.update(extra)
        return env

    def _write_mcp(self, env: dict[str, str] | None = None) -> None:
        payload = {
            "mcpServers": {
                "timeassist": {
                    "command": "engine/timeassist.exe",
                    "env": env
                    or {
                        "SUPABASE_URL": "https://example.supabase.co",
                        "SUPABASE_KEY": "anon-test-key",
                    },
                }
            }
        }
        (self.root / ".mcp.json").write_text(json.dumps(payload), encoding="utf-8")

    def _seed_sqlite(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        actions.init_state(path, "2026-05-28T08:00:00")

    def test_looks_like_plugin_root_with_mcp(self) -> None:
        self._write_mcp()
        self.assertTrue(cb.looks_like_plugin_root(self.root))

    def test_load_mcp_env_injects_when_unset(self) -> None:
        self._write_mcp()
        environ: dict[str, str] = {}
        loaded = cb.load_mcp_env_from_plugin(self.root, environ=environ, inject=True)
        self.assertEqual(loaded["SUPABASE_URL"], "https://example.supabase.co")
        self.assertEqual(environ["SUPABASE_URL"], "https://example.supabase.co")
        self.assertEqual(environ["SUPABASE_KEY"], "anon-test-key")

    def test_load_mcp_env_does_not_override_existing(self) -> None:
        self._write_mcp()
        environ = {"SUPABASE_URL": "https://already.set", "SUPABASE_KEY": "keep"}
        cb.load_mcp_env_from_plugin(self.root, environ=environ, inject=True)
        self.assertEqual(environ["SUPABASE_URL"], "https://already.set")
        self.assertEqual(environ["SUPABASE_KEY"], "keep")

    def test_resolve_db_migrates_claude_plugin_data_into_timmy(self) -> None:
        self._write_mcp()
        data = Path(self.tmp.name) / "plugin-data"
        data.mkdir()
        legacy = data / "timeassist.sqlite"
        self._seed_sqlite(legacy)
        environ = self._appdata_env(CLAUDE_PLUGIN_DATA=str(data))
        found = cb.resolve_db_path(self.root, environ=environ)
        canonical = paths.canonical_db_path(environ=environ)
        self.assertEqual(found, canonical.resolve())
        self.assertTrue(canonical.is_file())

    def test_resolve_db_ignores_unexpanded_claude_plugin_data(self) -> None:
        self._write_mcp()
        environ = self._appdata_env(CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}")
        found = cb.resolve_db_path(self.root, environ=environ)
        self.assertIsNone(found)

    def test_resolve_db_beside_plugin(self) -> None:
        self._write_mcp()
        db = self.root / "timeassist.sqlite"
        self._seed_sqlite(db)
        found = cb.resolve_db_path(self.root, environ=self._appdata_env())
        self.assertEqual(found, db.resolve())

    def test_resolve_db_claude_store_package(self) -> None:
        """Store Claude packages Timmy path when canonical is missing."""
        self._write_mcp()
        store_db = (
            self.local
            / "Packages"
            / "Claude_pzs8sxrjxfjjc"
            / "LocalCache"
            / "Local"
            / "Timmy"
            / "timeassist.sqlite"
        )
        self._seed_sqlite(store_db)
        found = cb.resolve_db_path(self.root, environ=self._appdata_env())
        self.assertEqual(found, store_db.resolve())

    def test_resolve_db_uses_store_when_only_that_file_has_staff_name(self) -> None:
        self._write_mcp()
        canonical = paths.canonical_db_path(environ=self._appdata_env())
        self._seed_sqlite(canonical)
        store_db = (
            self.local
            / "Packages"
            / "Claude_pzs8sxrjxfjjc"
            / "LocalCache"
            / "Local"
            / "Timmy"
            / "timeassist.sqlite"
        )
        self._seed_sqlite(store_db)
        actions.set_setting(store_db, "staff_name", "Jamie")
        found = cb.resolve_db_path(self.root, environ=self._appdata_env())
        self.assertEqual(found, store_db.resolve())

    def test_find_org_timeassist_plugin(self) -> None:
        rpm = (
            self.roaming
            / "Claude"
            / "local-agent-mode-sessions"
            / "acct"
            / "org"
            / "rpm"
            / "plugin_abc"
        )
        (rpm / ".claude-plugin").mkdir(parents=True)
        (rpm / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "timeassist", "version": "0.1.24"}),
            encoding="utf-8",
        )
        self._write_mcp()
        # Copy mcp into org plugin root
        (rpm / ".mcp.json").write_text((self.root / ".mcp.json").read_text(encoding="utf-8"), encoding="utf-8")
        found = cb.find_org_timeassist_plugin(environ=self._appdata_env())
        self.assertIsNotNone(found)
        self.assertTrue(found.samefile(rpm))

    def test_bootstrap_loads_org_mcp_when_start_has_no_mcp(self) -> None:
        """Stable %LOCALAPPDATA%\\Timmy launch: creds from org plugin scan."""
        orphan = Path(self.tmp.name) / "TimmyStable"
        orphan.mkdir()
        store_db = (
            self.local
            / "Packages"
            / "Claude_test"
            / "LocalCache"
            / "Local"
            / "Timmy"
            / "timeassist.sqlite"
        )
        self._seed_sqlite(store_db)
        rpm = (
            self.roaming
            / "Claude"
            / "local-agent-mode-sessions"
            / "a"
            / "b"
            / "rpm"
            / "plugin_org"
        )
        (rpm / ".claude-plugin").mkdir(parents=True)
        (rpm / ".claude-plugin" / "plugin.json").write_text(
            '{"name":"timeassist"}',
            encoding="utf-8",
        )
        (rpm / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "timeassist": {
                            "env": {
                                "SUPABASE_URL": "https://example.supabase.co",
                                "SUPABASE_KEY": "anon-test-key",
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        environ = self._appdata_env()
        result = cb.bootstrap_clock(start=orphan, environ=environ, inject_env=True)
        self.assertIsNone(result.error, result.error)
        self.assertEqual(result.db_path, store_db.resolve())
        self.assertTrue(cb.has_supabase_credentials(environ))

    def test_bootstrap_ok(self) -> None:
        self._write_mcp()
        db = self.root / "timeassist.sqlite"
        self._seed_sqlite(db)
        environ = self._appdata_env()
        result = cb.bootstrap_clock(start=self.root, environ=environ, inject_env=True)
        self.assertIsNone(result.error)
        self.assertEqual(result.db_path, db.resolve())
        self.assertTrue(result.env_loaded)
        self.assertTrue(cb.has_supabase_credentials(environ))

    def test_bootstrap_missing_db(self) -> None:
        self._write_mcp()
        environ = self._appdata_env()
        result = cb.bootstrap_clock(start=self.root, environ=environ, inject_env=True)
        self.assertIsNone(result.db_path)
        self.assertIn("database", (result.error or "").lower())

    def test_bootstrap_missing_creds(self) -> None:
        (self.root / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"timeassist": {"env": {}}}}),
            encoding="utf-8",
        )
        db = self.root / "timeassist.sqlite"
        self._seed_sqlite(db)
        environ = self._appdata_env()
        result = cb.bootstrap_clock(start=self.root, environ=environ, inject_env=True)
        self.assertEqual(result.db_path, db.resolve())
        self.assertIn("credentials", (result.error or "").lower())

    def test_bootstrap_wrong_folder(self) -> None:
        orphan = Path(self.tmp.name) / "desktop"
        orphan.mkdir()
        environ = self._appdata_env()
        result = cb.bootstrap_clock(start=orphan, environ=environ, inject_env=True)
        self.assertIsNotNone(result.error)
        self.assertIn(".mcp.json", result.error or "")


class TimmyDataPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name) / "Local"
        self.local.mkdir()

    def test_canonical_under_timmy(self) -> None:
        environ = {"LOCALAPPDATA": str(self.local)}
        self.assertEqual(
            paths.canonical_db_path(environ=environ),
            self.local / "Timmy" / "timeassist.sqlite",
        )

    def test_reject_unexpanded_db_path(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            paths.prepare_db_path("${CLAUDE_PLUGIN_DATA}/timeassist.sqlite")
        self.assertIn("unexpanded", str(ctx.exception).lower())

    def test_migrate_once_from_legacy(self) -> None:
        legacy_root = Path(self.tmp.name) / "old-plugin-data"
        legacy_root.mkdir()
        legacy_db = legacy_root / "timeassist.sqlite"
        actions.init_state(legacy_db, "2026-05-28T09:00:00")
        environ = {
            "LOCALAPPDATA": str(self.local),
            "CLAUDE_PLUGIN_DATA": str(legacy_root),
        }
        dest = paths.canonical_db_path(environ=environ)
        self.assertFalse(dest.is_file())
        migrated = paths.maybe_migrate_legacy_db(dest, environ=environ)
        self.assertEqual(migrated, legacy_db)
        self.assertTrue(dest.is_file())
        # Second call is a no-op when dest exists.
        self.assertIsNone(paths.maybe_migrate_legacy_db(dest, environ=environ))

    def test_no_migrate_when_dest_exists(self) -> None:
        legacy_root = Path(self.tmp.name) / "old-plugin-data"
        legacy_root.mkdir()
        legacy_db = legacy_root / "timeassist.sqlite"
        actions.init_state(legacy_db, "2026-05-28T09:00:00")
        environ = {
            "LOCALAPPDATA": str(self.local),
            "CLAUDE_PLUGIN_DATA": str(legacy_root),
        }
        dest = paths.canonical_db_path(environ=environ)
        actions.init_state(dest, "2026-05-28T10:00:00")
        self.assertIsNone(paths.maybe_migrate_legacy_db(dest, environ=environ))

    def test_no_migrate_from_unexpanded_legacy(self) -> None:
        environ = {
            "LOCALAPPDATA": str(self.local),
            "CLAUDE_PLUGIN_DATA": "${CLAUDE_PLUGIN_DATA}",
        }
        dest = paths.canonical_db_path(environ=environ)
        self.assertIsNone(paths.maybe_migrate_legacy_db(dest, environ=environ))

    def test_explicit_db_skips_migrate_gate(self) -> None:
        other = Path(self.tmp.name) / "other.sqlite"
        # prepare with migrate_if_canonical still true, but path is not canonical
        out = paths.prepare_db_path(other, environ={"LOCALAPPDATA": str(self.local)})
        self.assertEqual(out, str(other))
        self.assertFalse(paths.canonical_db_path(environ={"LOCALAPPDATA": str(self.local)}).is_file())


class ClockSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name) / "Local"
        self.roaming = Path(self.tmp.name) / "Roaming"
        self.plugin = Path(self.tmp.name) / "plugin"
        self.local.mkdir()
        self.roaming.mkdir()
        self.plugin.mkdir()
        (self.plugin / ".mcp.json").write_text("{}", encoding="utf-8")
        self.env = {
            "LOCALAPPDATA": str(self.local),
            "APPDATA": str(self.roaming),
            "CLAUDE_PLUGIN_ROOT": str(self.plugin),
        }
        self.shortcut_patch = patch.object(cb, "_write_timmy_clock_shortcuts")
        self.shortcut_patch.start()
        self.addCleanup(self.shortcut_patch.stop)

    def _write_clock(self, path: Path, payload: bytes, mtime: float | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_finds_clock_via_claude_plugin_root(self) -> None:
        src = self._write_clock(self.plugin / "TimmyClock.exe", b"NEW")
        found = cb.find_plugin_clock_exe(environ=self.env)
        self.assertEqual(found, src.resolve())

    def test_finds_clock_beside_engine(self) -> None:
        env = {"LOCALAPPDATA": str(self.local), "APPDATA": str(self.roaming)}
        engine = self.plugin / "engine" / "timeassist.exe"
        engine.parent.mkdir(parents=True)
        engine.write_bytes(b"eng")
        src = self._write_clock(self.plugin / "TimmyClock.exe", b"NEW")
        found = cb.find_plugin_clock_exe(environ=env, executable=engine)
        self.assertEqual(found, src.resolve())

    def test_missing_plugin_clock_is_noop(self) -> None:
        self.assertIsNone(cb.find_plugin_clock_exe(environ=self.env))
        self.assertIsNone(cb.sync_stable_clock_from_plugin(environ=self.env))
        dest = self.local / "Timmy" / "TimmyClock.exe"
        self.assertFalse(dest.is_file())

    def test_newer_plugin_clock_is_copied(self) -> None:
        src = self._write_clock(self.plugin / "TimmyClock.exe", b"NEW-CLOCK", mtime=2_000)
        dest = self._write_clock(self.local / "Timmy" / "TimmyClock.exe", b"OLD", mtime=1_000)
        with patch.object(cb, "_is_clock_running", return_value=False):
            out = cb.sync_stable_clock_from_plugin(environ=self.env)
        self.assertIsNotNone(out)
        self.assertEqual(Path(out).name, "TimmyClock.exe")
        self.assertEqual(dest.read_bytes(), b"NEW-CLOCK")

    def test_same_mtime_size_is_noop(self) -> None:
        payload = b"SAME-BYTES"
        src = self._write_clock(self.plugin / "TimmyClock.exe", payload, mtime=1_500)
        dest = self._write_clock(self.local / "Timmy" / "TimmyClock.exe", payload, mtime=1_500)
        with patch.object(cb, "_is_clock_running", return_value=False):
            with patch.object(cb, "_stop_running_clock") as stop:
                cb.sync_stable_clock_from_plugin(environ=self.env)
        stop.assert_not_called()
        self.assertEqual(dest.read_bytes(), payload)

    def test_running_dest_is_stopped_then_replaced(self) -> None:
        src = self._write_clock(self.plugin / "TimmyClock.exe", b"NEWER", mtime=3_000)
        dest = self._write_clock(self.local / "Timmy" / "TimmyClock.exe", b"OLDER", mtime=1_000)
        started: list[Path] = []
        with patch.object(cb, "_is_clock_running", return_value=True):
            with patch.object(cb, "_stop_running_clock") as stop:
                with patch.object(cb, "_launch_clock", side_effect=lambda p: started.append(p)):
                    out = cb.sync_stable_clock_from_plugin(environ=self.env)
        stop.assert_called_once()
        self.assertIsNotNone(out)
        self.assertEqual(Path(out).name, "TimmyClock.exe")
        self.assertEqual(dest.read_bytes(), b"NEWER")
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].name, "TimmyClock.exe")

    def test_rejects_timeassist_exe_as_source(self) -> None:
        engine = self.plugin / "engine" / "timeassist.exe"
        engine.parent.mkdir(parents=True)
        engine.write_bytes(b"not-clock")
        self.assertIsNone(cb.install_stable_clock(engine, self.plugin, environ=self.env))
        self.assertFalse((self.local / "Timmy" / "TimmyClock.exe").is_file())

    def test_mcp_starts_if_sync_raises(self) -> None:
        from timeassist import cli

        db = Path(self.tmp.name) / "mcp.sqlite"
        actions.init_state(db, "2026-05-28T09:00:00")
        with patch("timeassist.clock_bootstrap.sync_stable_clock_from_plugin", side_effect=RuntimeError("boom")):
            with patch("timeassist.mcp_server.serve") as serve:
                rc = cli.main(["--db", str(db), "mcp"])
        self.assertEqual(rc, 0)
        serve.assert_called_once()


if __name__ == "__main__":
    unittest.main()
