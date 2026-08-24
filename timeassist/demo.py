"""Shared deterministic stakeholder walkthrough.

This module owns the canonical demo sequence so both the `demo` CLI command and
the `scripts/run_stakeholder_demo.py` helper run identical logic. Steps are run
through the real CLI dispatch (`cli.run_command`) so the transcript matches what
a stakeholder would see by typing the commands by hand.
"""
from __future__ import annotations

import json
import os
import shutil
import webbrowser
from dataclasses import asdict
from pathlib import Path
from typing import Any

DEFAULT_DEMO_DATE = "2026-05-28"
DEMO_MARKER = ".timeassist-demo-output"
DEMO_README = """# Curated synthetic demo output

This folder contains sample artifacts generated from the synthetic stakeholder demo. They are tracked so reviewers can inspect the current handoff shape without running the demo first.

These files must remain synthetic. Do not place real client data, real QuickBooks exports, copied communications, credentials, or private work context in this folder.

Regenerate with:

```bash
python scripts/run_stakeholder_demo.py
```

or:

```bash
python scripts/timeassist.py demo --output demo/generated
```
"""

TALK_TRACK = [
    "The business problem is not that accountants refuse to track time. The problem is that the current workflow makes short interruptions and task switching easy to lose.",
    "This prototype keeps the user in control. It creates draft entries, not final billing records.",
    "Every mutation writes an event log. That gives the workflow accountability without screen recording or keystroke monitoring.",
    "Only approved entries export to a QuickBooks-ready CSV. Direct QuickBooks writeback is intentionally out of scope for v1.",
    "Before any real pilot, the stakeholder needs to confirm approved data classes, rounding rules, service codes, and the exact QuickBooks handoff route.",
]


def _demo_clients_csv(out: Path) -> Path:
    return out / "demo-clients.csv"


def _write_demo_roster(out: Path) -> Path:
    # A synthetic roster so the demo's clients are on the master list; without it
    # every capture would be needs_info (the #34 approve/export gate) and the
    # scripted approvals would be refused. Synthetic names only.
    clients_csv = _demo_clients_csv(out)
    clients_csv.write_text(
        "display_name,aliases,default_billable,default_job_type\n"
        "Client A,,yes,Bookkeeping\n"
        "Client B,,yes,Tax\n"
    )
    return clients_csv


def _demo_steps(date_value: str, out: Path) -> list[list[str]]:
    clients_csv = _demo_clients_csv(out)
    return [
        ["init", "--at", f"{date_value}T08:55:00"],
        ["import-clients", "--file", str(clients_csv), "--mode", "replace", "--confirm-replace", "--at", f"{date_value}T08:56:00"],
        ["start", "--client", "Client A", "--task", "monthly cleanup", "--billable", "yes", "--at", f"{date_value}T09:00:00"],
        ["switch", "--client", "Client B", "--task", "tax question", "--billable", "yes", "--at", f"{date_value}T09:24:00"],
        ["end", "--at", f"{date_value}T09:42:00"],
        ["add-missing", "--client", "Client A", "--task", "call notes and follow-up", "--start", f"{date_value}T10:00:00", "--end", f"{date_value}T10:18:00", "--billable", "yes"],
        ["review", "--date", date_value, "--format", "html", "--output", str(out / "review-before-approval.html")],
        ["approve", "--entry-id", "1", "--at", f"{date_value}T10:45:00"],
        ["review", "--date", date_value],
        ["approve", "--entry-id", "2", "--at", f"{date_value}T10:46:00"],
        ["review", "--date", date_value],
        ["export", "--date", date_value, "--format", "quickbooks-csv", "--output", str(out / "quickbooks-time-export.csv"), "--at", f"{date_value}T10:50:00"],
        ["review", "--date", date_value, "--format", "html", "--output", str(out / "stakeholder-review.html")],
        ["sanitize-packet", "--date", date_value, "--output", str(out / "sanitized-collaboration-packet.md")],
    ]


def _display_db(db: Path) -> str:
    try:
        return str(db.relative_to(Path.cwd()))
    except ValueError:
        return str(db)


def _run_step(db: Path, args: list[str]) -> dict[str, Any]:
    # Imported lazily to avoid a circular import: cli imports this module.
    from .cli import build_parser, error_result, run_command

    parser = build_parser()
    namespace = parser.parse_args(["--db", str(db), *args])
    try:
        result = run_command(namespace)
    except Exception as exc:  # mirror the CLI's stakeholder-friendly error envelope
        result = error_result(namespace.command, exc)
    return asdict(result)


def _with_review_token(args: list[str], review_token: str | None) -> list[str]:
    if args and args[0] in {"approve", "export"} and "--review-token" not in args:
        if not review_token:
            raise ValueError(f"demo step {args[0]} requires a fresh review token")
        return [*args, "--review-token", review_token]
    return args


def _review_token_from_payload(payload: dict[str, Any]) -> str | None:
    if not payload.get("ok"):
        return None
    details = payload.get("details") or {}
    token = details.get("review_token")
    return str(token) if token else None


def _clear_output(out: Path) -> None:
    marker = out / DEMO_MARKER
    if out.exists():
        children = list(out.iterdir())
        valid_marker = marker.exists() and marker.is_file() and not marker.is_symlink()
        if children and not valid_marker:
            raise ValueError(f"refusing to clear existing output directory without a regular {DEMO_MARKER} ownership marker: {out}")
        for child in children:
            if child == marker:
                continue
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
    out.mkdir(parents=True, exist_ok=True)
    marker.write_text("Owned by TimeAssist demo generator; contents may be regenerated.\n")


def _write_output_readme(out: Path) -> Path:
    readme = out / "README.md"
    readme.write_text(DEMO_README)
    return readme


def _portable_path_payload(value: Any, root: Path) -> Any:
    """Return a transcript-safe copy with local absolute paths made relative.

    Runtime commands intentionally report full paths so plugin users can find
    their exports. The committed demo transcript should stay portable across
    machines, so we redact the repository root prefix while preserving the
    shape of the real command output.
    """
    if isinstance(value, dict):
        return {key: _portable_path_payload(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_path_payload(item, root) for item in value]
    if isinstance(value, str):
        root_text = root.as_posix().rstrip("/") + "/"
        normalized = value.replace("\\", "/")
        if normalized.startswith(root_text):
            return normalized.removeprefix(root_text)
        home_text = Path.home().resolve().as_posix().rstrip("/")
        if normalized == home_text:
            return "~"
        home_prefix = home_text + "/"
        if normalized.startswith(home_prefix):
            return "~/" + normalized.removeprefix(home_prefix)
    return value


def _write_transcript(out: Path, transcript: list[tuple[str, dict[str, Any]]]) -> Path:
    root = Path.cwd().resolve()
    lines = [
        "# TimeAssist Stakeholder Demo Transcript",
        "",
        "This is a synthetic walkthrough. It does not contain real client data, private work context, credentials, exports, or internal URLs.",
        "",
        "## Talk track",
        "",
    ]
    lines.extend(f"{index}. {point}" for index, point in enumerate(TALK_TRACK, start=1))
    lines.extend([
        "",
        "## Demo commands run",
        "",
    ])
    for command, payload in transcript:
        lines.append(f"### `{command}`")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(_portable_path_payload(payload, root), indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    lines.extend([
        "## Generated artifacts",
        "",
        f"- `{(out / 'stakeholder-review.html').as_posix()}` — stakeholder-friendly review screen.",
        f"- `{(out / 'quickbooks-time-export.csv').as_posix()}` — synthetic approved-entry export.",
        f"- `{(out / 'sanitized-collaboration-packet.md').as_posix()}` — anonymized packet for outside design review.",
        "",
    ])
    transcript_path = out / "stakeholder-demo-transcript.md"
    transcript_path.write_text("\n".join(lines))
    return transcript_path


def run_demo(output_dir: str | Path, date_value: str = DEFAULT_DEMO_DATE, open_html: bool = False) -> dict[str, Any]:
    """Run the full deterministic walkthrough and write artifacts into ``output_dir``.

    Returns a stakeholder-friendly summary describing the generated artifacts.
    """
    out = Path(output_dir)
    db = out / "timeassist-demo.sqlite"
    db_display = _display_db(db)

    _clear_output(out)
    _write_output_readme(out)
    _write_demo_roster(out)

    # Synthetic demo still seeds via CSV; production roster is live Supabase only.
    prev_roster = os.environ.get("TIMEASSIST_ALLOW_LOCAL_ROSTER")
    os.environ["TIMEASSIST_ALLOW_LOCAL_ROSTER"] = "1"
    try:
        transcript: list[tuple[str, dict[str, Any]]] = []
        latest_review_token: str | None = None
        for planned_args in _demo_steps(date_value, out):
            args = _with_review_token(planned_args, latest_review_token)
            payload = _run_step(db, args)
            refreshed_token = _review_token_from_payload(payload)
            if refreshed_token:
                latest_review_token = refreshed_token
            command = " ".join(["python scripts/timeassist.py", "--db", db_display, *args])
            transcript.append((command, payload))
    finally:
        if prev_roster is None:
            os.environ.pop("TIMEASSIST_ALLOW_LOCAL_ROSTER", None)
        else:
            os.environ["TIMEASSIST_ALLOW_LOCAL_ROSTER"] = prev_roster

    transcript_path = _write_transcript(out, transcript)

    stakeholder_html = out / "stakeholder-review.html"
    artifacts = {
        "stakeholder_review_html": str(stakeholder_html),
        "review_before_approval_html": str(out / "review-before-approval.html"),
        "quickbooks_csv": str(out / "quickbooks-time-export.csv"),
        "sanitized_packet": str(out / "sanitized-collaboration-packet.md"),
        "transcript": str(transcript_path),
        "database": str(db),
    }

    opened_browser = False
    if open_html and stakeholder_html.exists():
        try:
            opened_browser = webbrowser.open(stakeholder_html.resolve().as_uri())
        except Exception:
            opened_browser = False

    return {
        "date": date_value,
        "output_dir": str(out),
        "commands_run": len(transcript),
        "artifacts": artifacts,
        "opened_browser": opened_browser,
    }
