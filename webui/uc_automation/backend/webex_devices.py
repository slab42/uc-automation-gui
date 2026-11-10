"""Webex devices: move a physical phone from one Webex org to another.

A MAC address can be in one org only, so a move is: find the phone in the source org, check everything the
destination needs, delete the phone from the source org, then add it (by MAC) to an existing workspace of the
destination org. If the add fails the phone is added back to where it was. Not tested against a real org.
"""

import csv
import io
import json
import threading
import time
from datetime import datetime

from .paths import DEVICE_SETTINGS_PATH
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


_store_lock = threading.Lock()


def _load_store() -> dict:
    try:
        return json.loads(DEVICE_SETTINGS_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _store_key(org: str, mac: str) -> str:
    return f"{org}|{mac}"


def read_customizations(c: WebexClient, device: dict, model: str) -> dict:
    """What was customized on the phone in this org: the device level settings (only when the phone has its own,
    customEnabled) and the key layout (only when CUSTOM). Reads that fail are skipped. {} when nothing is customized."""
    saved: dict = {}
    try:
        st = c.call("GET", f"/telephony/config/devices/{device['id']}/settings",
                    {"deviceModel": model} if model else None)
        if st.get("customEnabled") and st.get("customizations"):
            saved["settings"] = {"customEnabled": True, "customizations": st["customizations"]}
    except WebexError:
        pass
    try:
        lay = c.call("GET", f"/telephony/config/devices/{device['id']}/layout")
        if lay.get("layoutMode") == "CUSTOM":
            saved["layout"] = lay
    except WebexError:
        pass
    return saved


def save_customizations(org: str, mac: str, model: str, saved: dict) -> None:
    """Keep the phone's customizations for when it moves back to `org`. Nothing customized removes an old entry."""
    key = _store_key(org, mac)
    with _store_lock:
        store = _load_store()
        if saved:
            store[key] = {"model": model, "saved": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **saved}
        elif key in store:
            del store[key]
        else:
            return
        DEVICE_SETTINGS_PATH.write_text(json.dumps(store, indent=2), "utf-8")


def restore_customizations(c: WebexClient, org: str, mac: str, model: str) -> str:
    """Re-apply what was saved for this MAC when the phone left `org`. Returns a sentence for the result ('' when
    nothing was saved). A failure is reported in the text, the move itself already succeeded."""
    entry = _load_store().get(_store_key(org, mac))
    if not entry:
        return ""
    device = None
    for attempt in range(ADD_ATTEMPTS):
        if attempt:
            time.sleep(ADD_RETRY_SECONDS)
        device = find_device(c, mac)
        if device:
            break
    if device is None:
        return f"Saved settings from {entry.get('saved', '')} were not applied: the phone was not found in {org}."
    done, failed = [], []
    for name, path, body in (("device settings", f"/telephony/config/devices/{device['id']}/settings", entry.get("settings")),
                             ("key layout", f"/telephony/config/devices/{device['id']}/layout", entry.get("layout"))):
        if not body:
            continue
        try:
            c.call("PUT", path, {"deviceModel": model} if name == "device settings" and model else None, body)
            done.append(name)
        except WebexError as e:
            failed.append(f"{name} ({e})")
    text = f"Reapplied saved {' and '.join(done)} from {entry.get('saved', '')}." if done else ""
    if failed:
        text += f" Could not reapply {'; '.join(failed)}."
    return text.strip()


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

    notes = []
    try:
        saved = read_customizations(src, device, src_code)
        save_customizations(src_name, mac, src_code or dst_code, saved)
        if saved:
            notes.append(f"Saved the custom {' and '.join(k for k in ('settings', 'layout') if k in saved)} of the phone "
                         f"for when it returns to {src_name}.")
    except OSError as e:
        notes.append(f"Could not save the phone's customizations ({e}).")

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
    try:
        restored = restore_customizations(dst, dst_name, mac, dst_code)
    except Exception as e:  # the phone is already moved; never fail the run for the extras
        restored = f"Could not reapply saved settings ({e})."
    if restored:
        notes.append(restored)
    return " ".join([f"Moved {product or dst_code} {mac} from {src_name} to {dst_name} (user {row['user']}). "
                     "Factory reset the phone so it registers with the new org."] + notes)
