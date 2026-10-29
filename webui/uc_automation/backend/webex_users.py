"""Webex users: bulk delete and voicemail PIN reset.

Ported from webex/BulkDeleteUsers.py and webex/ResetUserPin.py (reference only). Not tested against a real org.
"""

import csv
import io

from .webex_api import WebexClient, WebexError
from .webex_groups import lookup_calling_user


def parse_email_csv(data: bytes, fallback_column: int = 0) -> list[str]:
    """Emails from a CSV with a header row. Uses the first column whose header contains 'email'
    (the Control Hub export calls it 'User ID/Email (Required)'), else column `fallback_column`."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    if not rows:
        raise ValueError("The CSV file is empty.")
    header = [h.strip().lower() for h in rows[0]]
    col = next((i for i, h in enumerate(header) if "email" in h), fallback_column)
    emails = []
    for r in rows[1:]:
        if len(r) > col and r[col].strip() and r[col].strip() not in emails:
            emails.append(r[col].strip())
    return emails


def delete_user(c: WebexClient, email: str) -> str:
    items = c.call("GET", "/people", {"email": email}).get("items") or []
    if not items:
        raise WebexError("No user found with that email.")
    for u in items:
        c.call("DELETE", f"/people/{u['id']}")
    return "Deleted" if len(items) == 1 else f"Deleted {len(items)} matching users"


def reset_pin(c: WebexClient, email: str) -> str:
    """Reset the voicemail PIN of a user with a Calling license."""
    person_id = lookup_calling_user(c, email)
    c.call("POST", f"/people/{person_id}/features/voicemail/actions/resetPin/invoke")
    return "Voicemail PIN reset"
