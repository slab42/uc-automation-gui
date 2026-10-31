"""Webex workspaces: create workspaces, add devices to workspaces, move users to another location by phone number.

Ported from webex/AddDevicesWorkspaces.py (an unfinished draft: the CSV is workspace, model, MAC here) and
webex/migration_userWorkspace_location.py (reference only). Not tested against a real org.
"""

import csv
import io
import re
import time

from .webex_api import WebexClient, WebexError
from .webex_groups import _list
from .webex_routing import find_location_id

JOB_TIMEOUT_SECONDS = 180
JOB_POLL_SECONDS = 5
MOVE_PATH = "/telephony/config/jobs/person/moveLocation"


# --- Create workspaces ---

WORKSPACE_COLUMNS = ("workspace", "location", "type", "capacity", "number", "extension")
WORKSPACE_TYPES = ("notSet", "focus", "huddle", "meetingRoom", "open", "desk", "other")


def parse_workspace_csv(data: bytes) -> list[dict[str, str]]:
    """Header row required: workspace (display name). location, type, capacity, number and extension are optional."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    lookup = {(h or "").strip().lower(): h for h in reader.fieldnames}
    if "workspace" not in lookup:
        raise ValueError("The CSV needs a header row with a workspace column "
                         "(location, type, capacity, number and extension are optional).")
    rows = []
    for raw in reader:
        row = {f: (raw.get(lookup[f]) or "").strip() if f in lookup else "" for f in WORKSPACE_COLUMNS}
        if any(row.values()):
            rows.append(row)
    return rows


def build_workspace_body(row: dict[str, str], location_id: str) -> dict:
    name = row.get("workspace", "").strip()
    if not name:
        raise WebexError("The workspace name is required.")
    body: dict = {"displayName": name}
    wtype = row.get("type", "").strip()
    if wtype:
        match = next((t for t in WORKSPACE_TYPES if t.lower() == wtype.replace(" ", "").lower()), None)
        if not match:
            raise WebexError(f"Type '{wtype}' must be one of: {', '.join(WORKSPACE_TYPES)}.")
        body["type"] = match
    capacity = row.get("capacity", "").strip()
    if capacity:
        if not capacity.isdigit():
            raise WebexError(f"Capacity '{capacity}' must be a whole number.")
        body["capacity"] = int(capacity)
    number = normalize_e164(row.get("number", ""))
    extension = row.get("extension", "").strip()
    if number or extension:
        if not location_id:
            raise WebexError("A location is required to give the workspace a number or extension.")
        calling = {"locationId": location_id}
        if number:
            calling["phoneNumber"] = number
        if extension:
            calling["extension"] = extension
        body["calling"] = {"type": "webexCalling", "webexCalling": calling}
        body["supportedDevices"] = "phones"
    if location_id:
        body["locationId"] = location_id
    return body


def workspace_exists(c: WebexClient, row: dict[str, str], cache: dict[str, str]) -> bool:
    """True when a workspace with this name (ignoring case) exists, in the row's location when it has one."""
    name = row.get("workspace", "").strip()
    if not name:
        return False
    params = {"displayName": name}
    location_id = ""
    if row.get("location"):
        try:
            location_id = find_location_id(c, row["location"], cache)
        except WebexError:
            location_id = ""  # an unknown location fails on its own when the workspace is created
    if location_id:
        params["locationId"] = location_id
    items = c.call("GET", "/workspaces", params).get("items") or []
    return any((i.get("displayName") or "").strip().lower() == name.lower() for i in items)


def review_row_number(c: WebexClient, row: dict[str, str], cache: dict[str, str]) -> tuple[str, str]:
    """Where the row's phone number stands against its location: (status, detail).

    status is 'none' (nothing to check), 'ok' (already in the location), 'missing' (not configured anywhere) or
    'other' (configured in a different location, detail is that location's name plus what it is in use on)
    or 'inuse' (in the location but already assigned, detail is what it is in use on)."""
    if not (row.get("number") and row.get("location")):
        return "none", ""
    try:
        location_id = find_location_id(c, row["location"], cache)
    except WebexError:
        return "none", ""  # an unknown location fails on its own when the workspace is created
    n = normalize_e164(row["number"])
    found = c.call("GET", "/telephony/config/numbers", {"phoneNumber": n}).get("phoneNumbers") or []
    record = next((i for i in found if i.get("phoneNumber") == n), None)
    if not record:
        return "missing", ""
    loc = record.get("location") or {}
    owner = record.get("owner") or {}
    used = describe_owner(owner) if owner.get("id") else ""
    if loc.get("id") == location_id:
        return ("inuse", used) if used else ("ok", "")
    where = loc.get("name") or loc.get("id") or "another location"
    return "other", f"{where} (in use on {used})" if used else where


def add_location_number(c: WebexClient, number: str, location_id: str) -> None:
    """Add a DID, active and unused, to the location (the Add Numbers defaults)."""
    c.call("POST", f"/telephony/config/locations/{location_id}/numbers", body={
        "phoneNumbers": [normalize_e164(number)], "numberType": "DID", "numberUsageType": "NONE", "state": "ACTIVE",
    })


def create_workspace(c: WebexClient, row: dict[str, str], cache: dict[str, str]) -> str:
    location_id = find_location_id(c, row["location"], cache) if row.get("location") else ""
    body = build_workspace_body(row, location_id)
    c.call("POST", "/workspaces", body=body)
    return f"Created workspace {body['displayName']}"


# --- Copy a workspace ---

COPY_COLUMNS = ("workspace", "location", "number", "extension")


def list_workspace_names(c: WebexClient) -> list[str]:
    """Display names of every workspace, sorted and without repeats, for the search list."""
    names = {(i.get("displayName") or "").strip() for i in _list(c, "/workspaces", "items")}
    return sorted(names - {""}, key=str.lower)


def workspace_location_map(c: WebexClient, locations: list[dict[str, str]]) -> dict[str, str]:
    """Workspace display name to its location name. Blank when two workspaces share the name in different locations."""
    by_id = {l["id"]: l["name"] for l in locations}
    found: dict[str, set[str]] = {}
    for i in _list(c, "/workspaces", "items"):
        name = (i.get("displayName") or "").strip()
        if name:
            found.setdefault(name, set()).add(by_id.get(i.get("locationId", ""), ""))
    return {n: (next(iter(locs)) if len(locs) == 1 else "") for n, locs in found.items()}


# Per-workspace Webex Calling settings that are copied: (label, path under the workspace id). A "/features/..."
# path is under /workspaces/{id}, the others under /telephony/config/workspaces/{id}. Not copied: numbers,
# emergency callback number, devices, monitoring members, billing plan and audio greetings (they are specific to
# the source), and the criteria lists of the selective and ring features.
CALLING_SETTINGS = (
    ("Call forwarding", "/features/callForwarding"),
    ("Call waiting", "/features/callWaiting"),
    ("Caller ID", "/features/callerId"),
    ("Incoming permission", "/features/incomingPermission"),
    ("Outgoing permission", "/features/outgoingPermission"),
    ("Call intercept", "/features/intercept"),
    ("Call recording", "/features/callRecordings"),
    ("Voicemail", "/voicemail"),
    ("Anonymous call reject", "/anonymousCallReject"),
    ("Barge in", "/bargeIn"),
    ("Do not disturb", "/doNotDisturb"),
    ("Push to talk", "/pushToTalk"),
    ("Privacy", "/privacy"),
    ("Call policies", "/callPolicies"),
    ("Music on hold", "/musicOnHold"),
    ("Simultaneous ring", "/simultaneousRing"),
    ("Sequential ring", "/sequentialRing"),
    ("Selective reject", "/selectiveReject"),
    ("Selective accept", "/selectiveAccept"),
    ("Selective forward", "/selectiveForward"),
    ("Priority alert", "/priorityAlert"),
)
READ_ONLY_KEYS = ("id", "orgId")


def _settings_url(workspace_id: str, path: str) -> str:
    return f"/workspaces/{workspace_id}{path}" if path.startswith("/features/") \
        else f"/telephony/config/workspaces/{workspace_id}{path}"


def read_calling_settings(c: WebexClient, source: dict) -> tuple[list[tuple[str, str, dict]], list[str]]:
    """The source workspace's calling settings as (label, path, body), plus the labels that could not be read.
    Empty when the source has no Webex Calling."""
    if (source.get("calling") or {}).get("type") != "webexCalling":
        return [], []
    found: list[tuple[str, str, dict]] = []
    unread: list[str] = []
    for label, path in CALLING_SETTINGS:
        try:
            body = c.call("GET", _settings_url(source["id"], path))
        except WebexError:
            unread.append(label)
            continue
        found.append((label, path, {k: v for k, v in body.items() if k not in READ_ONLY_KEYS}))
    return found, unread


def apply_calling_settings(c: WebexClient, workspace_id: str, settings: list[tuple[str, str, dict]]) -> list[str]:
    """PUT each setting to the new workspace. Returns 'label (error)' for the ones that failed."""
    failed: list[str] = []
    for label, path, body in settings:
        try:
            c.call("PUT", _settings_url(workspace_id, path), body=body)
        except WebexError as e:
            failed.append(f"{label} ({e})")
    return failed


def get_workspace(c: WebexClient, name: str, location: str, cache: dict[str, str]) -> dict:
    """The full record of the workspace to copy, found by display name (and location when two share a name)."""
    location_id = find_location_id(c, location, cache) if location else ""
    return c.call("GET", f"/workspaces/{find_workspace_id(c, name, location_id)}")


def copy_workspace(c: WebexClient, source: dict, row: dict[str, str], cache: dict[str, str],
                   settings: list[tuple[str, str, dict]] | None = None, unread: list[str] | None = None) -> str:
    """Create row['workspace'] with the source's type, capacity and notes. A number or extension must be given
    for the copy, they are never taken from the source. Without a location the copy stays in the source's
    location (and floor); a different location drops the floor. The legacy workspaceLocationId is only sent
    when the source has no locationId, because Webex rejects the two together."""
    new_location = find_location_id(c, row["location"], cache) if row.get("location") else ""
    calling_location = ((source.get("calling") or {}).get("webexCalling") or {}).get("locationId", "")
    location_id = new_location or source.get("locationId") or ""
    if not location_id and (row.get("number") or row.get("extension")):
        location_id = calling_location
    base = {**row, "type": row.get("type") or source.get("type") or "",
            "capacity": row.get("capacity") or str(source.get("capacity") or "")}
    body = build_workspace_body(base, location_id)
    for f in ("notes", "hotdeskingStatus"):
        if source.get(f):
            body[f] = source[f]
    if not new_location and location_id and source.get("floorId"):
        body["floorId"] = source["floorId"]
    if not location_id and source.get("workspaceLocationId"):
        body["workspaceLocationId"] = source["workspaceLocationId"]
    created = c.call("POST", "/workspaces", body=body)
    detail = f"Created workspace {body['displayName']} as a copy of {source.get('displayName', '')}"
    if settings and "calling" in body and created.get("id"):
        failed = apply_calling_settings(c, created["id"], settings)
        detail += f". Copied {len(settings) - len(failed)} of {len(settings)} calling setting(s)"
        failed += [f"{u} (could not be read from the source)" for u in unread or []]
        if failed:
            detail += f"; not copied: {'; '.join(failed)}"
    return detail


# --- Add devices to workspaces ---

DEVICE_COLUMNS = ("workspace", "model", "mac", "location")


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


# --- Bulk ATA / VG: one device, one workspace per port ---

ATA_COLUMNS = ("mac", "model", "location", "workspace", "extension", "number")
MAX_PORTS = 48


def parse_ata_csv(data: bytes) -> list[dict[str, str]]:
    """One row per port. Header row required: mac, workspace and extension; model, location and number are optional.

    Rows with the same MAC are the ports of one device, in file order (the first row is port 1)."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    lookup = {(h or "").strip().lower(): h for h in reader.fieldnames}
    missing = [f for f in ("mac", "workspace", "extension") if f not in lookup]
    if missing:
        raise ValueError("The CSV needs a header row with the columns mac, workspace and extension "
                         "(model, location and number are optional).")
    rows = []
    for raw in reader:
        row = {f: (raw.get(lookup[f]) or "").strip() if f in lookup else "" for f in ATA_COLUMNS}
        if any(row.values()):
            rows.append(row)
    return rows


def port_rows_from_text(text: str, mac: str, model: str, location: str) -> list[dict[str, str]]:
    """Lines of 'workspace, extension, number' (number optional) to port rows for one device."""
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in re.split(r"[\t|;,]", line)]
        parts += [""] * (3 - len(parts))
        rows.append({"mac": mac, "model": model, "location": location,
                     "workspace": parts[0], "extension": parts[1], "number": parts[2]})
    return rows


def group_ata_rows(rows: list[dict[str, str]]) -> list[dict]:
    """Port rows to devices: {mac, model, location, ports: [{workspace, extension, number}]}, in first-seen order."""
    devices: dict[str, dict] = {}
    for r in rows:
        key = re.sub(r"[^0-9A-Fa-f]", "", r.get("mac", "")).upper() or r.get("mac", "")
        d = devices.setdefault(key, {"mac": r.get("mac", ""), "model": "", "location": "", "ports": []})
        for f in ("model", "location"):
            if r.get(f) and not d[f]:
                d[f] = r[f]
        d["ports"].append({f: r.get(f, "") for f in ("workspace", "extension", "number")})
    return list(devices.values())


def member_body(workspace_ids: list[str]) -> dict:
    """PUT members body: workspace n is on port n, port 1 is the device owner."""
    return {"members": [{"port": n, "id": wid, "primaryOwner": n == 1, "lineType": "PRIMARY", "lineWeight": 1,
                         "hotlineEnabled": False, "hotlineDestination": "", "allowCallDeclineEnabled": True}
                        for n, wid in enumerate(workspace_ids, 1)]}


def add_ata(c: WebexClient, device: dict, cache: dict[str, str]) -> str:
    """Create a workspace per port, add the device to the first one, then give every port its workspace.

    Everything is checked before the first call. A failure part way leaves what was already created."""
    model, location = device.get("model", "").strip(), device.get("location", "").strip()
    ports = device["ports"]
    if not (device.get("mac") and model and location):
        raise WebexError("mac, model and location are required.")
    if not ports:
        raise WebexError("At least one port is required.")
    if len(ports) > MAX_PORTS:
        raise WebexError(f"{len(ports)} ports is more than the {MAX_PORTS} allowed.")
    mac = normalize_mac(device["mac"])
    location_id = find_location_id(c, location, cache)
    names: set[str] = set()
    bodies = []
    for n, p in enumerate(ports, 1):
        name = p["workspace"].strip()
        if not (name and (p["extension"].strip() or p["number"].strip())):
            raise WebexError(f"Port {n} needs a workspace name and an extension or a number.")
        if name.lower() in names:
            raise WebexError(f"Workspace {name} is listed more than once.")
        names.add(name.lower())
        if workspace_exists(c, {"workspace": name, "location": location}, cache):
            raise WebexError(f"Workspace {name} already exists in {location}.")
        bodies.append(build_workspace_body({"workspace": name, "number": p["number"], "extension": p["extension"]},
                                           location_id))
    ids = [c.call("POST", "/workspaces", body=b)["id"] for b in bodies]
    made = c.call("POST", "/devices", body={"mac": mac, "model": model, "workspaceId": ids[0]})
    device_id = made.get("id")
    if not device_id:
        raise WebexError(f"The device {mac} was added but Webex did not return its id, so ports 2 to {len(ids)} "
                         "were not assigned.")
    if len(ids) > 1:
        c.call("PUT", f"/telephony/config/devices/{device_id}/members", body=member_body(ids))
    return f"Added {model} {mac} with {len(ids)} port(s): " + ", ".join(p["workspace"] for p in ports)


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
    return (f"{owner.get('firstName', '')} {owner.get('lastName', '')}".strip() or owner.get("name")
            or owner.get("id", ""))


def describe_owner(owner: dict) -> str:
    """What a number is in use on, e.g. 'Jane Doe (PEOPLE)' or 'Lobby (PLACE)'."""
    kind = owner.get("type") or "unknown owner type"
    return f"{owner_name(owner)} ({kind})"


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
