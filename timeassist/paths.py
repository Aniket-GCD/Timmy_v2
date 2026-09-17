"""Default data and artifact locations.

Plugin / MCP installs use a per-Windows-user Timmy data directory
(``%LOCALAPPDATA%\\Timmy``). Explicit ``--db`` still overrides for tests and
CLI demos. Official exports/review files resolve next to the selected database;
tool results report full paths so the operator can find them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def is_unexpanded_plugin_var(value: str | Path | None) -> bool:
    """True when Claude left a ${CLAUDE_PLUGIN_*} placeholder unexpanded."""
    if value is None:
        return False
    return "${" in str(value)


def _environ_map(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def timmy_data_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Per-user Timmy data directory (canonical durable home for SQLite)."""
    env = _environ_map(environ)
    if os.name == "nt":
        raw = (env.get("LOCALAPPDATA") or "").strip()
        if raw and not is_unexpanded_plugin_var(raw):
            return Path(raw).expanduser() / "Timmy"
        home = Path.home()
        return home / "AppData" / "Local" / "Timmy"
    # Non-Windows (tests / future): XDG-style under the home directory.
    return Path.home() / ".timmy"


def canonical_db_path(environ: Mapping[str, str] | None = None) -> Path:
    return timmy_data_dir(environ=environ) / "timeassist.sqlite"


def default_db_path() -> str:
    return str(canonical_db_path())


def valid_claude_plugin_data(value: str | None) -> Path | None:
    """Return expanded CLAUDE_PLUGIN_DATA path, or None if missing/unusable."""
    raw = (value or "").strip()
    if not raw or is_unexpanded_plugin_var(raw):
        return None
    return Path(raw).expanduser()


def maybe_migrate_legacy_db(
    dest_db: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Copy legacy Claude plugin-data DB into the Timmy data dir once.

    Returns the source path if a migration ran, else None. Never treats a
    literal ``${CLAUDE_PLUGIN_DATA}`` string as a filesystem path.
    """
    dest = Path(dest_db).expanduser()
    if dest.is_file():
        return None
    env = _environ_map(environ)
    legacy_root = valid_claude_plugin_data(env.get("CLAUDE_PLUGIN_DATA"))
    if legacy_root is None:
        return None
    src = legacy_root / "timeassist.sqlite"
    if not src.is_file():
        return None
    try:
        if dest.exists() and src.resolve() == dest.resolve():
            return None
    except OSError:
        pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    from . import db as tdb

    tdb.backup(src, dest)
    return src


def prepare_db_path(
    db_path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    migrate_if_canonical: bool = True,
) -> str:
    """Validate --db, optionally migrate into the canonical Timmy location."""
    text = str(db_path)
    if is_unexpanded_plugin_var(text):
        raise ValueError(
            "database path still contains an unexpanded Claude plugin variable "
            f"({text!r}). Timmy owns its data under the Timmy AppData folder — "
            "reinstall/update the plugin so .mcp.json no longer passes "
            "${CLAUDE_PLUGIN_DATA}, or omit --db to use the default."
        )
    path = Path(text).expanduser()
    if migrate_if_canonical:
        canonical = canonical_db_path(environ=environ)
        same = False
        try:
            same = path.resolve() == canonical.resolve()
        except OSError:
            same = path == canonical or str(path) == str(canonical)
        if same:
            maybe_migrate_legacy_db(path, environ=environ)
    return str(path)


def default_export_path(date_value: str, end_date: str | None = None, operator_code: str | None = None) -> str:
    code = f"{operator_code}-" if operator_code else ""
    span = date_value if not end_date or end_date == date_value else f"{date_value}_to_{end_date}"
    return f"quickbooks-time-{code}{span}.csv"


def default_packet_path(date_value: str) -> str:
    return f"sanitized-collaboration-packet-{date_value}.md"


def default_review_html_path(date_value: str) -> str:
    return f"review-{date_value}.html"


def data_dir_for_db(db_path: str | Path) -> Path:
    return Path(db_path).expanduser().resolve().parent


def _inside(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def resolve_within_data_dir(value: str | Path, db_path: str | Path) -> Path:
    """Resolve a model/user supplied path under the DB's data directory.

    MCP/plugin mode must not let tool arguments write/read arbitrary local files.
    Relative paths are interpreted inside the TimeAssist data directory; absolute
    paths are accepted only if they already point inside that directory. Symlink
    and ``..`` escapes are rejected after realpath resolution. The data directory
    itself is not a valid file argument.
    """
    base = data_dir_for_db(db_path).resolve()
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else base / raw
    resolved = candidate.resolve()
    if resolved == base:
        raise ValueError(f"path must be a file path under TimeAssist data directory, not the data directory itself: {value}")
    if not _inside(resolved, base):
        raise ValueError(f"path is outside TimeAssist data directory: {value}")
    return resolved


def resolve_artifact_path(
    output: str | Path,
    db_path: str | Path | None = None,
    *,
    restrict_to_data_dir: bool = False,
    artifact_subdir: str | None = None,
) -> Path:
    if restrict_to_data_dir:
        if db_path is None:
            raise ValueError("db_path is required when restricting artifact paths")
        if not artifact_subdir:
            raise ValueError("artifact_subdir is required when restricting artifact paths")
        base = data_dir_for_db(db_path).resolve()
        artifact_base = base / artifact_subdir
        if artifact_base.is_symlink():
            raise ValueError(f"TimeAssist {artifact_subdir} artifact directory must not be a symlink: {artifact_base}")
        if artifact_base.exists() and not artifact_base.is_dir():
            raise ValueError(f"TimeAssist {artifact_subdir} artifact path must be a directory: {artifact_base}")
        artifact_base_resolved = artifact_base.resolve()
        raw = Path(output).expanduser()
        if raw.is_absolute():
            candidate = raw
        elif raw.parent == Path("."):
            # Bare filenames are routed to the expected artifact directory, so a
            # model cannot overwrite TimeAssist's DB, WAL/SHM, backups, or roster
            # files by choosing a top-level filename inside the plugin data dir.
            candidate = artifact_base / raw.name
        else:
            candidate = base / raw
        path = candidate.resolve()
        if path == artifact_base_resolved:
            raise ValueError(f"path must be a file path under TimeAssist {artifact_subdir} directory, not the directory itself: {output}")
        if not _inside(path, artifact_base_resolved):
            raise ValueError(f"artifact path must be under TimeAssist {artifact_subdir} directory: {output}")
        if path.exists() and path.is_dir():
            raise ValueError(f"path must be a file path, not an existing directory: {output}")
        return path

    path = Path(output).expanduser()
    if not path.is_absolute():
        # Bare filenames are TimeAssist's default artifact names; keep them next
        # to the selected database. Relative paths with a directory component are
        # explicit caller paths (e.g. demo/generated/file.csv), so honor the
        # caller's working directory instead of prefixing the DB directory.
        if path.parent == Path("."):
            base = data_dir_for_db(db_path) if db_path is not None else Path.cwd()
            path = base / path
        else:
            path = Path.cwd() / path
    return path.resolve()


def resolve_input_path(input_path: str | Path, db_path: str | Path, *, restrict_to_data_dir: bool = False) -> Path:
    if restrict_to_data_dir:
        return resolve_within_data_dir(input_path, db_path)
    return Path(input_path).expanduser().resolve()


def default_user_export_dir() -> Path:
    """Return the built-in operator-visible export folder.

    Cowork/plugin users should not need a CLI setup step just to find a CSV.
    This path is deterministic and engine-chosen (not model-supplied), so it can
    sit outside plugin data without weakening per-call artifact path hardening.
    """
    return (_documents_dir() / "TimeAssist Exports").resolve()


def _is_windows() -> bool:
    return os.name == "nt"


def _documents_dir() -> Path:
    if _is_windows():
        known_documents = _windows_known_documents_dir()
        if known_documents is not None:
            return known_documents
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    base = Path(home).expanduser() if home else Path.home()
    return base / "Documents"


def _windows_known_documents_dir() -> Path | None:
    if not _is_windows():
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        folderid_documents = GUID(
            0xFDD39AD0,
            0x238F,
            0x46AF,
            (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
        )
        path_ptr = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None

        result = shell32.SHGetKnownFolderPath(ctypes.byref(folderid_documents), 0, None, ctypes.byref(path_ptr))
        try:
            if result != 0 or not path_ptr.value:
                return None
            return Path(path_ptr.value)
        finally:
            if path_ptr.value:
                ole32.CoTaskMemFree(ctypes.cast(path_ptr, ctypes.c_void_p))
    except Exception:
        return None


def resolve_user_export_dir(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise ValueError(f"user_export_dir is not a directory: {value}")
    return path


def copy_export_to_user_dir(official_output: str | Path, user_export_dir: str | Path) -> Path:
    source = Path(official_output).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise ValueError(f"official export must be an existing file: {official_output}")
    destination_dir = resolve_user_export_dir(user_export_dir)
    if destination_dir.exists() and not destination_dir.is_dir():
        raise ValueError(f"user_export_dir is not a directory: {user_export_dir}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists() and destination.is_dir():
        raise ValueError(f"user-visible export destination is a directory: {destination}")
    tmp_path = destination.with_name(f".{destination.name}.tmp")
    tmp_path.write_bytes(source.read_bytes())
    tmp_path.replace(destination)
    return destination.resolve()


def default_backups_dir(db_path: str | Path) -> str:
    return str(data_dir_for_db(db_path) / "backups")
