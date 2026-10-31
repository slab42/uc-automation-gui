"""Webex devices: move a physical phone from one Webex org to another.

A MAC address can be in one org only, so a move is: find the phone in the source org, check everything the
destination needs, delete the phone from the source org, then add it (by MAC) to an existing workspace of the
destination org. If the add fails the phone is added back to where it was. Not tested against a real org.
"""

import csv
import io
import time

from .webex_api import WebexClient, WebexError
from .webex_tools import get_supported_devices
from .webex_workspaces import normalize_mac

MIGRATE_COLUMNS = ("mac", "user")
ADD_ATTEMPTS = 3
ADD_RETRY_SECONDS = 4  # the MAC can take a moment to be released by the source org


def parse_migrate_csv(data: bytes) -> list[dict[str, str]]:
    """Header row required: mac and user (the destination user: an email or a display name)."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    lookup = {(h or "").strip().lower(): h for h in reader.fieldnames}
    if "mac" not in lookup or "user" not in lookup:
        raise ValueError("The CSV needs a header row with the columns mac and user.")
    rows = []
    for raw in reader:
        row = {f: (raw.get(lookup[f]) or "").strip() if f in lookup else "" for f in MIGRATE_COLUMNS}
        if any(row.values()):
            rows.append(row)
    return rows


def find_person(c: WebexClient, text: str) -> dict:
    """A user by email, or by exact display name."""
    text = text.strip()
    params = {"email": text} if "@" in text else {"displayName": text}
    items = c.call("GET", "/people", params).get("items") or []
    if "@" not in text:
        items = [p for p in items if (p.get("displayName") or "").strip().lower() == text.lower()]
    if len(items) > 1:
        raise WebexError(f"More than one user matches '{text}'. Use the email address.")
    if not items:
        raise WebexError(f"User '{text}' was not found.")
    return items[0]


def find_device(c: WebexClient, mac: str) -> dict | None:
    items = c.call("GET", "/devices", {"mac": mac}).get("items") or []
    return next((d for d in items if normalize_mac(d.get("mac") or "") == mac), None)


def source_model(c: WebexClient, device: dict) -> str:
    """The model code Webex Calling uses for the phone (for example 'DMS Cisco 8845'); '' when it cannot be read."""
    try:
        return c.call("GET", f"/telephony/config/devices/{device['id']}").get("model") or ""
    except WebexError:
        return ""


def destination_model(supported: dict[str, dict], model: str, product: str) -> str:
    for key in (model, product):
        entry = supported.get(key.strip().lower()) if key else None
        if entry:
            return entry["model"]
    raise WebexError(f"The destination org does not support this phone model ({model or product or 'unknown'}).")


def _owner_body(device: dict) -> dict:
    """Body part that puts a phone back on its owner: a workspace, else a person."""
    if device.get("workspaceId"):
        return {"workspaceId": device["workspaceId"]}
    if device.get("personId"):
        return {"personId": device["personId"]}
    raise WebexError("The phone has no workspace or person in the source org.")


def migrate_phone(src: WebexClient, dst: WebexClient, row: dict[str, str], supported: dict[str, dict],
                  src_name: str, dst_name: str) -> str:
    """Move one phone to a user of the destination org. Everything is checked before the phone is deleted from the
    source org. row: mac, user (destination), from_user (optional: the phone must belong to this user now)."""
    if not (row.get("mac") and row.get("user")):
        raise WebexError("The MAC address and the destination user are both required.")
    mac = normalize_mac(row["mac"])
    device = find_device(src, mac)
    if device is None:
        raise WebexError(f"No phone with MAC {mac} was found in {src_name}.")
    if row.get("from_user"):
        owner = find_person(src, row["from_user"])
        if device.get("personId") != owner["id"]:
            raise WebexError(f"The phone {mac} does not belong to {row['from_user']} in {src_name}.")
    product = device.get("product") or ""
    src_code = source_model(src, device)
    dst_code = destination_model(supported, src_code, product)
    back = _owner_body(device)
    if find_device(dst, mac) is not None:
        raise WebexError(f"A phone with MAC {mac} is already in {dst_name}.")
    person = find_person(dst, row["user"])

    src.call("DELETE", f"/devices/{device['id']}")
    last: WebexError | None = None
    for attempt in range(ADD_ATTEMPTS):
        if attempt:
            time.sleep(ADD_RETRY_SECONDS)
        try:
            dst.call("POST", "/devices", body={"mac": mac, "model": dst_code, "personId": person["id"]})
            break
        except WebexError as e:
            last = e
    else:
        try:
            src.call("POST", "/devices", body={"mac": mac, "model": src_code or dst_code, **back})
        except WebexError as e:
            raise WebexError(f"Could not add {mac} to {dst_name}: {last} Adding it back to {src_name} also "
                             f"failed ({e}). The phone is in neither org.") from e
        raise WebexError(f"Could not add {mac} to {dst_name}: {last} The phone was added back to {src_name}.")
    return (f"Moved {product or dst_code} {mac} from {src_name} to {dst_name} (user {row['user']}). "
            "Factory reset the phone so it registers with the new org.")
