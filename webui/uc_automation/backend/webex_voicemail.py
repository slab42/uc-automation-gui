"""Webex voicemail report: where each user's voicemail is stored (internal Webex mailbox or external email).

Reads GET /people/{id}/features/voicemail. Not tested against a real org.
"""

from .webex_api import WebexClient, WebexError
from .webex_groups import PAGE, calling_license_ids


def _person_row(p: dict) -> dict[str, str]:
    emails = p.get("emails") or [""]
    return {"id": p.get("id", ""), "name": p.get("displayName", ""), "email": emails[0],
            "locationId": p.get("locationId", "")}


def find_person(c: WebexClient, email: str) -> dict[str, str]:
    """The user with this email who has a Calling license. Raises WebexError otherwise."""
    items = c.call("GET", "/people", {"email": email, "callingData": "true"}).get("items") or []
    licenses = calling_license_ids(c)
    for p in items:
        if licenses is None or licenses & set(p.get("licenses") or []):
            return _person_row(p)
    raise WebexError(f"{email}: user not found or has no Calling license.")


def list_location_people(c: WebexClient, location_id: str) -> list[dict[str, str]]:
    """Every user of a location, sorted by name. The list API returns no licenses, so users without Calling
    are not filtered here; their voicemail read fails and shows as an error row."""
    people: list[dict] = []
    start = 0
    while True:
        page = c.call("GET", "/people", {"locationId": location_id, "callingData": "true", "max": PAGE,
                                         "start": start}).get("items") or []
        people.extend(page)
        if len(page) < PAGE:
            break
        start += PAGE
    return sorted((_person_row(p) for p in people), key=lambda r: r["name"].lower())


def voicemail_info(c: WebexClient, person_id: str) -> dict[str, str]:
    """Mailbox type and settings of one user: storage ('Internal' or 'External'), enabled, details."""
    v = c.call("GET", f"/people/{person_id}/features/voicemail")
    storage = v.get("messageStorage") or {}
    external = (storage.get("storageType") or "").upper() == "EXTERNAL"
    if external:
        details = storage.get("externalEmail") or (v.get("emailCopyOfMessage") or {}).get("emailId") or ""
    else:
        # The Webex voice messaging APIs (message summary) only read the signed-in user's own mailbox, so an
        # admin login cannot get another user's message count.
        details = "Message count not available"
    return {"enabled": "Yes" if v.get("enabled") else "No", "storage": "External" if external else "Internal",
            "details": details, "raw": v}
