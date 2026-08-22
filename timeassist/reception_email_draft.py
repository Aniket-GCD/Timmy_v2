"""Ready-to-copy Reception email for new QuickBooks clients. Draft only — never send."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


DEFAULT_RECEPTION_EMAIL = "reception@example.com"


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
    office_code = (office or "").strip().upper() or "GCD"
    to_addr = ((to_email or "").strip() or DEFAULT_RECEPTION_EMAIL)
    subject = f"New QuickBooks client request: {spoken}"
    body = (
        f"Hi Reception,\n\n"
        f"Please create a new client in QuickBooks.\n\n"
        f"Client name: {spoken}\n"
        f"Requested by: {staff}\n"
        f"Office: {office_code}\n\n"
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
        "note": "Draft only — Timmy never sends email. Copy or open the mailto link.",
    }
