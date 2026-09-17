"""Ready-to-copy Reception email for new QuickBooks clients. Draft only — never send."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


DEFAULT_RECEPTION_EMAIL = "reception@gcd.cpa"


def draft_reception_email(
    *,
    spoken_client_name: str,
    staff_name: str,
    office: str,
    to_email: str | None = None,
) -> dict[str, Any]:
    spoken = (spoken_client_name or "").strip()
    if not spoken:
        raise ValueError("spoken_client_name is required")
    staff = (staff_name or "").strip() or "Staff"
    # office kept for callers / future templates; body is firm-wide Reception wording.
    _ = (office or "").strip().upper() or "GCD"
    to_addr = ((to_email or "").strip() or DEFAULT_RECEPTION_EMAIL)
    subject = f"New Client Setup Request: {spoken}"
    body = (
        f"Hi Reception Team,\n\n"
        f"Will you please set up this new client in QuickBooks and Practice. "
        f"Source documents are attached.\n\n"
        f"Client name: {spoken}\n\n"
        f"Thank you,\n"
        f"{staff}\n"
    )
    mailto = f"mailto:{quote(to_addr, safe='@.+')}?subject={quote(subject)}&body={quote(body)}"
    return {
        "to": to_addr,
        "subject": subject,
        "body": body,
        "mailto": mailto,
        "sent": False,
        "note": (
            "Draft only — Timmy never sends or attaches. "
            "Operator: attach source documents (name, DOB, SSN, etc.) before sending."
        ),
    }
