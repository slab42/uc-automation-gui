"""Webex call routing: add numbers to a location, set or remove call forward all.

Ported from webex/AddNumbersToLocation.py, CallFowardAll.py and CallFowardAll-Remove.py (reference only).
Request shapes follow the Webex Calling API docs and have not been run against a real org.
"""

import csv
import io
import re

from .webex_api import WebexClient, WebexError

NUMBER_TYPES = ("DID", "TOLLFREE")
USAGE_TYPES = ("NONE", "SERVICE")
NUMBER_STATES = ("ACTIVE", "INACTIVE")
DEFAULT_FORWARD_PREFIX = "88888888"
COUNTRY = "US"  # 10 digit numbers get a leading 1


def _read_csv(data: bytes) -> tuple[csv.DictReader, dict[str, str]]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    return reader, {(h or "").strip().lower(): h for h in reader.fieldnames}


# --- Add numbers ---

def parse_add_numbers_csv(data: bytes) -> list[dict[str, str]]:
    """Header row required. locationId and phoneNumber are required; the other columns are optional."""
    reader, lookup = _read_csv(data)
    fields = ["locationId", "phoneNumber", "numberType", "numberUsageType", "state"]
    if "locationid" not in lookup or "phonenumber" not in lookup:
        raise ValueError("The CSV needs a header row with the columns locationId and phoneNumber.")
    rows = []
    for raw in reader:
        row = {f: (raw.get(lookup[f.lower()]) or "").strip() if f.lower() in lookup else "" for f in fields}
        if any(row.values()):
            rows.append(row)
    return rows


def normalize_number(number: str) -> str:
    """Digits only, 10 digit US numbers get a 1. Returns E.164 with the leading +."""
    digits = re.sub(r"\D", "", number)
    if COUNTRY == "US" and len(digits) == 10:
        digits = "1" + digits
    if COUNTRY == "US" and len(digits) < 10:
        raise WebexError(f"Phone number {number} is shorter than 10 digits.")
    return "+" + digits


def find_location_id(c: WebexClient, name: str, cache: dict[str, str]) -> str:
    """Location id from a location name (exact match, case insensitive). A value that already looks like an id passes through."""
    key = name.strip()
    if key in cache:
        return cache[key]
    data = c.call("GET", "/telephony/config/locations", {"name": key, "max": 200})
    items = data.get("locations") or data.get("items") or []
    exact = [i for i in items if (i.get("name") or "").strip().lower() == key.lower()]
    if len(exact) == 1:
        cache[key] = exact[0]["id"]
    elif len(exact) > 1:
        raise WebexError(f"More than one location is named '{key}'.")
    elif key.startswith("Y2lzY29"):  # base64 of "ciscospark://", an id was supplied
        cache[key] = key
    else:
        raise WebexError(f"Location '{key}' was not found.")
    return cache[key]


def add_number(c: WebexClient, row: dict[str, str], cache: dict[str, str]) -> str:
    number_type = (row.get("numberType") or "DID").upper()
    usage = (row.get("numberUsageType") or "NONE").upper()
    state = (row.get("state") or "ACTIVE").upper()
    if number_type not in NUMBER_TYPES:
        raise WebexError(f"numberType must be one of {', '.join(NUMBER_TYPES)}.")
    if usage not in USAGE_TYPES:
        raise WebexError(f"numberUsageType must be one of {', '.join(USAGE_TYPES)}.")
    if state not in NUMBER_STATES:
        raise WebexError(f"state must be one of {', '.join(NUMBER_STATES)}.")
    if not row.get("locationId") or not row.get("phoneNumber"):
        raise WebexError("locationId and phoneNumber are both required.")
    number = normalize_number(row["phoneNumber"])
    location_id = find_location_id(c, row["locationId"], cache)
    c.call("POST", f"/telephony/config/locations/{location_id}/numbers", body={
        "phoneNumbers": [number], "numberType": number_type, "numberUsageType": usage, "state": state,
    })
    return f"Added {number} to {row['locationId']} ({number_type}, {usage}, {state})"


# --- Call forward all ---

def parse_number_list_csv(data: bytes) -> list[str]:
    """Header row required. Uses the column whose header contains 'phone' or 'pattern', else the first column."""
    reader, lookup = _read_csv(data)
    col = next((h for k, h in lookup.items() if "phone" in k or "pattern" in k), reader.fieldnames[0])
    numbers = [(raw.get(col) or "").strip() for raw in reader]
    return [n for n in numbers if n]


def lookup_number(c: WebexClient, number: str) -> tuple[str, str, str]:
    """(location id, owner type, owner id) for a phone number or extension."""
    data = c.call("GET", "/telephony/config/numbers", {"phoneNumber": number})
    found = data.get("phoneNumbers") or []
    if not found:
        raise WebexError(f"Phone number {number} was not found.")
    n = found[0]
    owner = n.get("owner") or {}
    if not owner.get("id"):
        raise WebexError(f"Phone number {number} has no owner assigned, so it has no call forward.")
    return (n.get("location") or {}).get("id", ""), owner.get("type", ""), owner["id"]


def _forward_path(owner_type: str, location_id: str, owner_id: str) -> str:
    if owner_type == "PEOPLE":
        return f"/people/{owner_id}/features/callForwarding"
    if owner_type == "PLACE":
        return f"/workspaces/{owner_id}/features/callForwarding"
    if owner_type == "VIRTUAL_LINE":
        return f"/telephony/config/virtualLines/{owner_id}/callForwarding"
    loc = f"/telephony/config/locations/{location_id}"
    paths = {"HUNT_GROUP": "huntGroups", "CALL_QUEUE": "queues", "AUTO_ATTENDANT": "autoAttendants"}
    if owner_type in paths:
        return f"{loc}/{paths[owner_type]}/{owner_id}/callForwarding"
    raise WebexError(f"Owner type {owner_type} is not supported for call forward.")


def set_call_forward_all(c: WebexClient, number: str, enabled: bool, prefix: str = "") -> str:
    """Forward all calls of the number's owner to prefix+number (enabled) or switch forward all off."""
    location_id, owner_type, owner_id = lookup_number(c, number)
    path = _forward_path(owner_type, location_id, owner_id)
    destination = f"{prefix}{number}" if enabled else ""
    body: dict = {"callForwarding": {"always": {"enabled": enabled, "destination": destination}}}
    if owner_type == "VIRTUAL_LINE":  # virtual lines also need business continuity set
        body["businessContinuity"] = {"enabled": enabled, "destination": destination}
    c.call("PUT", path, body=body)
    return f"Forward all set to {destination} ({owner_type})" if enabled else f"Forward all removed ({owner_type})"
