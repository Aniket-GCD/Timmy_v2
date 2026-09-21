"""Bootstrap TimmyClock when dropped into the Timmy plugin folder.

Resolves plugin root (exe/script directory), injects SUPABASE_* from sibling
.mcp.json when unset, and finds timeassist.sqlite for the local staff identity.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MISSING_DB_HINT = (
    "Could not find Timmy's database.\n\n"
    "1. Open Claude and use Timmy once\n"
    "2. Then open Timmy Clock again"
)

MISSING_PLUGIN_HINT = (
    "Put TimmyClock.exe in your Timmy plugin folder\n"
    "(same folder as .mcp.json), then double-click it."
)

MISSING_CREDS_HINT = (
    "Timmy Clock needs Supabase credentials from the Timmy folder.\n"
    "Keep TimmyClock.exe next to .mcp.json and try again."
)


@dataclass(frozen=True)
class ClockBootstrap:
    plugin_root: Path
    db_path: Path | None
    env_loaded: bool
    error: str | None = None


def _frozen_or_script_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # packaging/timmy_clock_entry.py -> repo root; tray CLI uses --db explicitly.
    here = Path(__file__).resolve().parent
    # timeassist/ -> prefer cwd when developing; entrypoint overrides via start=.
    return here.parent


def looks_like_plugin_root(path: Path) -> bool:
    root = path.resolve()
    if (root / ".mcp.json").is_file():
        return True
    if (root / "config" / "supabase.json").is_file():
        return True
    for sub in ("bin", "engine"):
        if (root / sub / "timeassist.exe").is_file():
            return True
        if (root / sub / "timeassist").is_file():
            return True
    return False


def resolve_plugin_root(start: Path | None = None) -> Path:
    """Folder that should contain .mcp.json (plugin root)."""
    base = (start or _frozen_or_script_dir()).resolve()
    candidates = [base, base.parent]
    for cand in candidates:
        if looks_like_plugin_root(cand):
            return cand
    return base


def load_mcp_env_from_plugin(
    plugin_root: Path,
    *,
    environ: dict[str, str] | None = None,
    inject: bool = True,
) -> dict[str, str]:
    """Read mcpServers.timeassist.env from .mcp.json; optionally set os.environ."""
    env = os.environ if environ is None else environ
    path = plugin_root / ".mcp.json"
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return loaded
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        return loaded
    # Prefer "timeassist"; otherwise first server with env SUPABASE_URL.
    blocks: list[Any] = []
    if "timeassist" in servers:
        blocks.append(servers["timeassist"])
    blocks.extend(v for k, v in servers.items() if k != "timeassist")
    for block in blocks:
        if not isinstance(block, dict):
            continue
        raw_env = block.get("env")
        if not isinstance(raw_env, dict):
            continue
        for key, value in raw_env.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            text = value.strip()
            if not text:
                continue
            loaded[key] = text
            if inject and not (env.get(key) or "").strip():
                env[key] = text
        if loaded:
            break
    return loaded


def _claude_plugin_data_db(environ: dict[str, str]) -> Path | None:
    from .paths import is_unexpanded_plugin_var, valid_claude_plugin_data

    raw = (environ.get("CLAUDE_PLUGIN_DATA") or "").strip()
    if not raw or is_unexpanded_plugin_var(raw):
        return None
    root = valid_claude_plugin_data(raw)
    if root is None:
        return None
    candidate = root / "timeassist.sqlite"
    return candidate if candidate.is_file() else None


def _claude_store_package_db(environ: dict[str, str]) -> Path | None:
    """Timmy DB under the Claude Microsoft Store package for this user.

    ``%LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Local\\Timmy\\timeassist.sqlite``
    — targeted glob only (no full AppData walk).
    """
    raw = (environ.get("LOCALAPPDATA") or "").strip()
    if not raw:
        return None
    packages = Path(raw) / "Packages"
    if not packages.is_dir():
        return None
    newest: Path | None = None
    newest_mtime = -1.0
    try:
        matches = list(packages.glob("Claude_*"))
    except OSError:
        return None
    for pkg in matches:
        candidate = pkg / "LocalCache" / "Local" / "Timmy" / "timeassist.sqlite"
        if not candidate.is_file():
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest = candidate
    return newest


def _search_appdata_sqlite(environ: dict[str, str]) -> Path | None:
    roots: list[Path] = []
    for key in ("LOCALAPPDATA", "APPDATA"):
        # Use only the provided mapping — do not fall back to process env when
        # tests pass a fake environ (avoids scanning the developer's machine).
        raw = (environ.get(key) or "").strip()
        if raw:
            roots.append(Path(raw))
    newest: Path | None = None
    newest_mtime = -1.0
    for root in roots:
        if not root.is_dir():
            continue
        # os.walk so one permission error does not abort the whole search.
        try:
            for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
                if "timeassist.sqlite" not in filenames:
                    continue
                hit = Path(dirpath) / "timeassist.sqlite"
                try:
                    mtime = hit.stat().st_mtime
                except OSError:
                    continue
                if mtime > newest_mtime:
                    newest_mtime = mtime
                    newest = hit
        except OSError:
            continue
    return newest


def resolve_db_path(
    plugin_root: Path,
    *,
    environ: dict[str, str] | None = None,
    explicit: str | Path | None = None,
) -> Path | None:
    from .paths import canonical_db_path, is_unexpanded_plugin_var, maybe_migrate_legacy_db

    if explicit is not None:
        if is_unexpanded_plugin_var(explicit):
            return None
        path = Path(explicit).expanduser()
        return path.resolve() if path.is_file() else None
    env = os.environ if environ is None else environ
    canonical = canonical_db_path(environ=env)
    maybe_migrate_legacy_db(canonical, environ=env)
    if canonical.is_file():
        return canonical.resolve()
    from_claude = _claude_plugin_data_db(env)
    if from_claude is not None:
        return from_claude.resolve()
    beside = plugin_root / "timeassist.sqlite"
    if beside.is_file():
        return beside.resolve()
    store_db = _claude_store_package_db(env)
    if store_db is not None:
        return store_db.resolve()
    found = _search_appdata_sqlite(env)
    return found.resolve() if found is not None else None


def find_org_timeassist_plugin(environ: dict[str, str] | None = None) -> Path | None:
    """Locate org/desktop Timmy plugin root (folder with .mcp.json) under Claude sessions."""
    env = os.environ if environ is None else environ
    raw = (env.get("APPDATA") or "").strip()
    if not raw:
        return None
    sessions = Path(raw) / "Claude" / "local-agent-mode-sessions"
    if not sessions.is_dir():
        return None
    newest: Path | None = None
    newest_mtime = -1.0
    # Shallow walk only: <acct>/<org>/rpm/plugin_* — avoid deep globs into skills/node_modules.
    try:
        for acct in sessions.iterdir():
            if not acct.is_dir():
                continue
            try:
                children = list(acct.iterdir())
            except OSError:
                continue
            for org in children:
                if not org.is_dir():
                    continue
                rpm = org / "rpm"
                if not rpm.is_dir():
                    continue
                try:
                    plugin_dirs = list(rpm.glob("plugin_*"))
                except OSError:
                    continue
                for root in plugin_dirs:
                    plugin_json = root / ".claude-plugin" / "plugin.json"
                    mcp = root / ".mcp.json"
                    if not plugin_json.is_file() or not mcp.is_file():
                        continue
                    try:
                        payload = json.loads(plugin_json.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    if not isinstance(payload, dict) or payload.get("name") != "timeassist":
                        continue
                    try:
                        mtime = mcp.stat().st_mtime
                    except OSError:
                        continue
                    if mtime > newest_mtime:
                        newest_mtime = mtime
                        newest = root
    except OSError:
        return None
    return newest


def stable_clock_dir(environ: dict[str, str] | None = None) -> Path:
    from .paths import timmy_data_dir

    return timmy_data_dir(environ=environ)


def ensure_stable_clock_install(
    plugin_root: Path,
    *,
    environ: dict[str, str] | None = None,
) -> Path | None:
    """Copy TimmyClock into %LOCALAPPDATA%\\Timmy and refresh Desktop/Start Menu shortcuts.

    Returns the stable exe path when install ran (frozen builds), else None.
    """
    env = os.environ if environ is None else environ
    if not getattr(sys, "frozen", False):
        return None
    src = Path(sys.executable).resolve()
    if not src.is_file():
        return None
    dest_dir = stable_clock_dir(environ=env)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    dest = dest_dir / "TimmyClock.exe"
    try:
        if src.resolve() != dest.resolve():
            import shutil

            shutil.copy2(src, dest)
    except OSError:
        # Still try shortcuts pointing at the running exe.
        dest = src
    _write_timmy_clock_shortcuts(dest, environ=env)
    # Refresh sibling .mcp.json next to stable copy when we know the plugin root.
    if looks_like_plugin_root(plugin_root):
        mcp_src = plugin_root / ".mcp.json"
        if mcp_src.is_file():
            try:
                import shutil

                shutil.copy2(mcp_src, dest_dir / ".mcp.json")
            except OSError:
                pass
    return dest


def _write_timmy_clock_shortcuts(target: Path, *, environ: dict[str, str]) -> None:
    """Create/refresh Desktop + Start Menu + Startup shortcuts (Windows). Idempotent."""
    if os.name != "nt":
        return
    desktop = (environ.get("USERPROFILE") or "").strip()
    desktop_dir = Path(desktop) / "Desktop" if desktop else None
    appdata = (environ.get("APPDATA") or "").strip()
    start_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" if appdata else None
    startup_dir = (
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        if appdata
        else None
    )
    links: list[Path] = []
    if desktop_dir is not None:
        links.append(desktop_dir / "Timmy Clock.lnk")
    if start_dir is not None:
        links.append(start_dir / "Timmy Clock.lnk")
    if startup_dir is not None:
        links.append(startup_dir / "Timmy Clock.lnk")
    target_s = str(target)
    work_s = str(target.parent)
    for link in links:
        try:
            link.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        # PowerShell COM shortcut — no extra deps.
        ps = (
            f"$w=New-Object -ComObject WScript.Shell; "
            f"$s=$w.CreateShortcut('{str(link).replace(chr(39), chr(39)+chr(39))}'); "
            f"$s.TargetPath='{target_s.replace(chr(39), chr(39)+chr(39))}'; "
            f"$s.WorkingDirectory='{work_s.replace(chr(39), chr(39)+chr(39))}'; "
            f"$s.Description='Timmy Clock'; "
            f"$s.Save()"
        )
        try:
            import subprocess

            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                check=False,
                capture_output=True,
                timeout=20,
            )
        except OSError:
            continue
        except Exception:
            # TimeoutExpired and COM failures — skip this link.
            continue


def has_supabase_credentials(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    url = (env.get("SUPABASE_URL") or "").strip()
    key = (
        (env.get("SUPABASE_KEY") or "").strip()
        or (env.get("SUPABASE_ANON_KEY") or "").strip()
        or (env.get("SUPABASE_SECRET") or "").strip()
    )
    return bool(url and key)


def bootstrap_clock(
    *,
    start: Path | None = None,
    db: str | Path | None = None,
    environ: dict[str, str] | None = None,
    inject_env: bool = True,
) -> ClockBootstrap:
    """Resolve plugin root, inject MCP env, find DB. Soft errors via .error."""
    env = os.environ if environ is None else environ
    plugin_root = resolve_plugin_root(start)
    loaded = load_mcp_env_from_plugin(plugin_root, environ=env, inject=inject_env)
    org = find_org_timeassist_plugin(environ=env)
    if not has_supabase_credentials(env) and org is not None:
        plugin_root = org
        loaded = load_mcp_env_from_plugin(org, environ=env, inject=inject_env) or loaded
    db_path = resolve_db_path(plugin_root, environ=env, explicit=db)

    if (
        db is None
        and db_path is None
        and not looks_like_plugin_root(plugin_root)
        and org is None
    ):
        return ClockBootstrap(
            plugin_root=plugin_root,
            db_path=None,
            env_loaded=bool(loaded),
            error=MISSING_PLUGIN_HINT,
        )
    if db_path is None:
        return ClockBootstrap(
            plugin_root=plugin_root,
            db_path=None,
            env_loaded=bool(loaded),
            error=MISSING_DB_HINT,
        )
    if not has_supabase_credentials(env):
        return ClockBootstrap(
            plugin_root=plugin_root,
            db_path=db_path,
            env_loaded=bool(loaded),
            error=MISSING_CREDS_HINT,
        )
    return ClockBootstrap(
        plugin_root=plugin_root,
        db_path=db_path,
        env_loaded=bool(loaded),
        error=None,
    )
