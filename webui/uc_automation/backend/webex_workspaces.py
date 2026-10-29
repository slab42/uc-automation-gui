"""Webex workspaces: add devices to workspaces, move users to another location by phone number.

Ported from webex/AddDevicesWorkspaces.py (an unfinished draft: the CSV is workspace, model, MAC here) and
webex/migration_userWorkspace_location.py (reference only). Not tested against a real org.
"""

import csv
import io
import re
import time

from .webex_api import WebexClient, WebexError
from .webex_routing import find_location_id

JOB_TIMEOUT_SECONDS = 180
JOB_POLL_SECONDS = 5
MOVE_PATH = "/telephony/config/jobs/person/moveLocation"


# --- Add devices to workspaces ---

def parse_device_csv(data: bytes) -> list[dict[str, str]]:
    """Header row required: workspace (display name), model, mac; location is optional and narrows the workspace search."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    lookup = {(h or "").strip().lower(): h for h in reader.fieldnames}
    missing = [f for f in ("workspace", "model", "mac") if f not in lookup]
    if missing:
        raise ValueError("The CSV needs a header row with the columns workspace, model and mac "
                         "(location is optional).")
    rows = []
    for raw in reader:
        row = {f: (raw.get(lookup[f]) or "").strip() if f in lookup else "" for f in ("workspace", "model", "mac", "location")}
        if any(row.values()):
            rows.append(row)
    return rows


def normalize_mac(mac: str) -> str:
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
    if len(cleaned) != 12:
        raise WebexError(f"MAC address {mac} must have 12 hex digits.")
    return cleaned


def find_workspace_id(c: WebexClient, name: str, location_id: str = "") -> str:
    params = {"displayName": name}
    if location_id:
        params["locationId"] = location_id
    items = c.call("GET", "/workspaces", params).get("items") or []
    exact = [w for w in items if (w.get("displayName") or "").strip().lower() == name.lower()]
    if len(exact) > 1:
        raise WebexError(f"More than one workspace is named '{name}'. Add the location column to tell them apart.")
    if not exact:
        raise WebexError(f"Workspace '{name}' was not found.")
    return exact[0]["id"]


def add_device(c: WebexClient, row: dict[str, str], cache: dict[str, str]) -> str:
    if not (row.get("workspace") and row.get("model") and row.get("mac")):
        raise WebexError("workspace, model and mac are all required.")
    mac = normalize_mac(row["mac"])
    location_id = find_location_id(c, row["location"], cache) if row.get("location") else ""
    workspace_id = find_workspace_id(c, row["workspace"], location_id)
    c.call("POST", "/devices", body={"mac": mac, "model": row["model"], "workspaceId": workspace_id})
    return f"Added {row['model']} {mac} to {row['workspace']}"


# --- Move users to another location (by phone number) ---

def normalize_e164(raw: str) -> str:
    """E.164 with a leading +; 10 and 11 digit input is taken as US/Canada."""
    raw = (raw or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return f"+{digits}"
    return f"+1{digits}" if len(digits) == 10 else f"+{digits}"


def parse_numbers_text(text: str) -> list[str]:
    out: list[str] = []
    for line in re.split(r"[\n,;]+", text):
        n = normalize_e164(line)
        if n and n not in out:
            out.append(n)
    return out


def parse_numbers_csv(data: bytes) -> list[str]:
    """Header row required. Uses the 'number' column, else the first column."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    if not rows:
        raise ValueError("The CSV file is empty.")
    col = next((i for i, h in enumerate(rows[0]) if h.strip().lower() == "number"), 0)
    out: list[str] = []
    for r in rows[1:]:
        n = normalize_e164(r[col]) if len(r) > col else ""
        if n and n not in out:
            out.append(n)
    return out


def owner_name(owner: dict) -> str:
    return f"{owner.get('firstName', '')} {owner.get('lastName', '')}".strip() or owner.get("id", "")


def classify(record: dict | None, location_id: str) -> tuple[str, str]:
    """(action, reason): action is 'move' or 'skip'."""
    if not record:
        return "skip", "number not found"
    owner = record.get("owner") or {}
    if not owner.get("id"):
        return "skip", f"number is {record.get('state', 'unassigned')} with no owner"
    if owner.get("type") not in ("PEOPLE", "PLACE"):
        return "skip", f"owner type is {owner.get('type')}"
    if record.get("phoneNumberType") != "PRIMARY":
        return "skip", f"not the primary number ({record.get('phoneNumberType')})"
    if (record.get("location") or {}).get("id") == location_id:
        return "skip", "owner is already at the target location"
    if owner["type"] == "PLACE":
        return "skip", "workspaces cannot be moved by the API; use Control Hub"
    return "move", ""


def review_numbers(c: WebexClient, numbers: list[str], location_id: str) -> list[dict[str, str]]:
    """One row per number: number, owner, ownerId, action (move/skip), reason."""
    rows = []
    for n in numbers:
        record = None
        try:
            found = c.call("GET", "/telephony/config/numbers", {"phoneNumber": n}).get("phoneNumbers") or []
            record = next((i for i in found if i.get("phoneNumber") == n), None)
            action, reason = classify(record, location_id)
        except WebexError as e:
            action, reason = "skip", str(e)
        owner = (record or {}).get("owner") or {}
        rows.append({"number": n, "owner": owner_name(owner) if owner else "", "ownerId": owner.get("id", ""),
                     "action": action, "reason": reason})
    return rows


def _move_body(user_id: str, location_id: str, validate: bool) -> dict:
    return {"usersList": [{"locationId": location_id, "validate": validate, "users": [{"userId": user_id}]}]}


def _errors(result: dict) -> list[str]:
    users = (result.get("response") or result).get("usersList") or []
    return [f"{e.get('code')}: {e.get('message')}" for u in users for e in (u.get("errors") or [])]


def move_user(c: WebexClient, user_id: str, location_id: str, note) -> str:
    """Validate, run the Move Users job and wait for it. `note` logs impacts and progress."""
    result = c.call("POST", MOVE_PATH, body=_move_body(user_id, location_id, True))
    for u in (result.get("response") or result).get("usersList") or []:
        for i in u.get("impacts") or []:
            note(f"Impact {i.get('code')}: {i.get('message')}")
    errs = _errors(result)
    if errs:
        raise WebexError("Validation failed: " + "; ".join(errs))
    result = c.call("POST", MOVE_PATH, body=_move_body(user_id, location_id, False))
    errs = _errors(result)
    if errs:
        raise WebexError("; ".join(errs))
    job_id = ((result.get("response") or result).get("jobDetails") or {}).get("id")
    if not job_id:
        raise WebexError("The move job id was not returned.")
    deadline = time.time() + JOB_TIMEOUT_SECONDS
    status = ""
    while time.time() < deadline:
        job = c.call("GET", f"{MOVE_PATH}/{job_id}")
        status = job.get("latestExecutionStatus", "")
        if status in ("COMPLETED", "FAILED"):
            counts = job.get("counts") or {}
            note(f"Move job {job_id} {status} {counts}")
            if status == "COMPLETED" and not counts.get("usersFailed"):
                return "Moved"
            raise WebexError(f"Move job {status.lower()} {counts}")
        time.sleep(JOB_POLL_SECONDS)
    raise WebexError(f"Move job still {status or 'pending'} after {JOB_TIMEOUT_SECONDS}s. Check Control Hub.")
