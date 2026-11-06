"""Webex workspaces: create workspaces, add devices to workspaces, move users to another location by phone number.

Ported from webex/AddDevicesWorkspaces.py (an unfinished draft: the CSV is workspace, model, MAC here) and
webex/migration_userWorkspace_location.py (reference only). Not tested against a real org.
"""

import csv
import io
import json
import re
import time

from .webex_api import WebexClient, WebexError
from .webex_groups import _list
from .webex_routing import find_location_id

JOB_TIMEOUT_SECONDS = 180
JOB_POLL_SECONDS = 5
MOVE_PATH = "/telephony/config/jobs/person/moveLocation"


# --- Create workspaces ---

WORKSPACE_COLUMNS = ("workspace", "location", "type", "capacity", "number", "extension", "model", "mac", "license")
WORKSPACE_TYPES = ("notSet", "focus", "huddle", "meetingRoom", "open", "desk", "other")


def parse_workspace_csv(data: bytes) -> list[dict[str, str]]:
    """Header row required: workspace (display name). Everything else is optional; model and mac together add a device."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    lookup = {(h or "").strip().lower(): h for h in reader.fieldnames}
    if "workspace" not in lookup:
        raise ValueError("The CSV needs a header row with a workspace column "
                         "(location, type, capacity, number, extension, model, mac and license are optional).")
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
    model, mac = row.get("model", "").strip(), row.get("mac", "").strip()
    if bool(model) != bool(mac):
        raise WebexError("model and mac must both be given to add a device (or both left empty).")
    mac = normalize_mac(mac) if mac else ""
    location_id = find_location_id(c, row["location"], cache) if row.get("location") else ""
    body = build_workspace_body(row, location_id)
    kind = normalize_license(row.get("license", ""))
    if kind:
        if "calling" not in body:
            raise WebexError("A phone number or extension (and a location) is needed to set a calling license.")
        body["calling"]["webexCalling"]["licenses"] = workspace_license_ids(c, kind)
    created = c.call("POST", "/workspaces", body=body)
    message = f"Created workspace {body['displayName']}" + (f" with the {kind} license" if kind else "")
    if not mac:
        return message
    try:
        c.call("POST", "/devices", body={"mac": mac, "model": model, "workspaceId": created["id"]})
    except WebexError as e:
        raise WebexError(f"{message}, but adding {model} {mac} failed: {e}") from e
    return f"{message} with {model} {mac}"


def create_workspace_adding_number(c: WebexClient, body: dict, location_id: str, added: list[str], log=None) -> str:
    """POST the workspace. When that fails and it has a phone number, add the number to the location and try once
    more (the number is probably not in the location yet); `added` collects the numbers that were added.
    `log` is an optional callable taking one line."""
    try:
        return c.call("POST", "/workspaces", body=body)["id"]
    except WebexError as first:
        number = (((body.get("calling") or {}).get("webexCalling")) or {}).get("phoneNumber")
        if not number:
            raise
        try:
            add_location_number(c, number, location_id)
        except WebexError as e:
            raise WebexError(f"{first} Adding {number} to the location also failed: {e}") from e
        added.append(number)
        if log:
            log(f"Number {number} added to the location (the workspace create failed without it)")
        return c.call("POST", "/workspaces", body=body)["id"]


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


# --- Upgrade the Calling license ---

LICENSE_PROFESSIONAL = "Professional Workspace"
LICENSE_COMMON = "Common Area Workspace"
LICENSE_CHOICES = (LICENSE_PROFESSIONAL, LICENSE_COMMON)
LICENSE_COLUMNS = ("workspace", "location")


def license_kind(name: str) -> str:
    """Which workspace Calling license a /licenses name is: Professional Workspace, Common Area Workspace or ''.
    A professional workspace uses the same license as a user, "Webex Calling - Professional" (confirmed). The
    common area one is matched loosely ("common", or "workspace" in the name) because its exact name is not known."""
    n = name.lower()
    if "common" in n or "workspace" in n:
        return LICENSE_COMMON
    if n.strip() == "webex calling - professional":
        return LICENSE_PROFESSIONAL
    return ""


def normalize_license(text: str) -> str:
    """The license kind a row's license cell names ('' for none, which leaves the choice to Webex). Accepts
    'professional' or 'common area' in any case, with or without 'workspace'. Raises WebexError otherwise."""
    t = text.strip().lower()
    if not t or t in ("default", "none"):
        return ""
    if t.startswith("pro"):
        return LICENSE_PROFESSIONAL
    if t.startswith("common"):
        return LICENSE_COMMON
    raise WebexError(f"License '{text}' must be Professional Workspace or Common Area Workspace.")


def workspace_license_ids(c: WebexClient, kind: str) -> list[str]:
    """Ids of the org's licenses of this kind (cached per run). Raises WebexError when there is none."""
    if "workspace_licenses" not in c.cache:
        found: dict[str, list[str]] = {k: [] for k in LICENSE_CHOICES}
        items = c.call("GET", "/licenses").get("items") or []
        c.cache["license_names"] = sorted({i.get("name") or "" for i in items})
        for item in items:
            k = license_kind(item.get("name") or "")
            if k:
                found[k].append(item["id"])
        c.cache["workspace_licenses"] = found
    ids = c.cache["workspace_licenses"][kind]
    if not ids:
        names = "; ".join(c.cache.get("license_names") or []) or "none"
        raise WebexError(f"No {kind} license was found in this org. Licenses in the org: {names}")
    return ids


def upgrade_license(c: WebexClient, row: dict[str, str], cache: dict[str, str]) -> str:
    """Upgrade a Webex Calling workspace from the Common Area Workspace to the Professional Workspace license
    (one way only, there is no downgrade). The update
    is a full PUT (type, capacity and notes are dropped when omitted), so the current values are sent back with
    the new license and the workspace's own location, number and extension."""
    location_id = find_location_id(c, row["location"], cache) if row.get("location") else ""
    ws = c.call("GET", f"/workspaces/{find_workspace_id(c, row['workspace'], location_id)}")
    calling = ws.get("calling") or {}
    if calling.get("type") != "webexCalling":
        raise WebexError(f"{ws.get('displayName', row['workspace'])} does not have Webex Calling.")
    wc = calling.get("webexCalling") or {}
    kind = LICENSE_PROFESSIONAL
    ids = workspace_license_ids(c, kind)
    if set(wc.get("licenses") or []) & set(ids):
        return f"Already has the {kind} license"
    calling_body = {"locationId": wc.get("locationId") or ws.get("locationId") or "", "licenses": ids}
    for f in ("phoneNumber", "extension"):
        if wc.get(f):
            calling_body[f] = wc[f]
    body = {"displayName": ws["displayName"], "calling": {"type": "webexCalling", "webexCalling": calling_body}}
    for f in ("capacity", "type", "notes", "hotdeskingStatus"):
        if ws.get(f) not in (None, ""):
            body[f] = ws[f]
    c.call("PUT", f"/workspaces/{ws['id']}", body=body)
    return f"Upgraded to the {kind} license"


# --- Get a workspace ---

# Read-only extras shown by Get Workspace (not copied to a new workspace), under /telephony/config/workspaces/{id}
EXTRA_SETTINGS = (
    ("Numbers", "/numbers"),
    ("Emergency callback number", "/emergencyCallbackNumber"),
    ("Devices", "/devices"),
    ("Monitoring", "/monitoring"),
)


def _pretty(body) -> str:
    return json.dumps(body, indent=2, ensure_ascii=False)


def get_workspace_details(c: WebexClient, name: str, location: str, cache: dict[str, str],
                          locations: list[dict[str, str]]) -> dict:
    """Everything known about one workspace: a summary (location, calling type, license names, number...) as
    label/value rows, and each calling setting as label/JSON text. 'unread' lists settings that could not be read."""
    location_id = find_location_id(c, location, cache) if location else ""
    ws = c.call("GET", f"/workspaces/{find_workspace_id(c, name, location_id)}")
    calling = ws.get("calling") or {}
    wc = calling.get("webexCalling") or {}
    loc_names = {l["id"]: l["name"] for l in locations}
    loc_id = ws.get("locationId") or wc.get("locationId") or ""
    try:
        by_id = {i["id"]: i.get("name") or i["id"] for i in c.call("GET", "/licenses").get("items") or []}
    except WebexError:
        by_id = {}
    license_ids = wc.get("licenses") or []
    summary = [
        ("Name", ws.get("displayName", "")),
        ("Workspace ID", ws.get("id", "")),
        ("Location", loc_names.get(loc_id, loc_id)),
        ("Calling type", calling.get("type", "")),
        ("Calling location", loc_names.get(wc.get("locationId", ""), wc.get("locationId", ""))),
        ("Calling license", ", ".join(by_id.get(i, i) for i in license_ids)
         or ("" if calling.get("type") == "webexCalling" else "None")),
        ("Phone number", wc.get("phoneNumber", "")),
        ("Extension", wc.get("extension", "")),
        ("Type", ws.get("type", "")),
        ("Capacity", str(ws.get("capacity") or "")),
        ("Hot desking", ws.get("hotdeskingStatus", "")),
        ("Supported devices", ws.get("supportedDevices", "")),
        ("Notes", ws.get("notes", "")),
    ]
    settings: list[dict[str, str]] = []
    unread: list[str] = []
    if calling.get("type") == "webexCalling":
        for label, path in CALLING_SETTINGS + EXTRA_SETTINGS:
            try:
                body = c.call("GET", _settings_url(ws["id"], path))
            except WebexError:
                unread.append(label)
                continue
            settings.append({"label": label, "text": _pretty({k: v for k, v in body.items() if k not in READ_ONLY_KEYS})})
    return {"summary": [{"label": k, "value": v} for k, v in summary if v],
            "settings": settings, "unread": unread, "raw": _pretty(ws),
            "licenses": sorted(set(by_id.values())), "license_ids": license_ids, "calling": _pretty(calling)}


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
                         "hotlineEnabled": False, "hotlineDestination": "", "allowCallDeclineEnabled": True,
                         "t38FaxCompressionEnabled": False}
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


# --- Update an existing ATA / VG: show its ports, fill the open ones ---

ATA_PRODUCT = re.compile(r"\bATA\b|\bVG|\bDMS\b", re.I)
MEMBER_KEYS = ("port", "id", "primaryOwner", "lineType", "lineWeight", "allowCallDeclineEnabled",
               "hotlineDestination", "hotlineEnabled", "t38FaxCompressionEnabled", "lineLabel")


def list_ata_devices(c: WebexClient, location_names: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Webex devices whose product looks like an ATA or VG, as {label, name, id, mac, model, workspaceId}, by label.

    name is 'device (MAC)'; label is the name with ' - <location>' added when location_names (id to name) knows it."""
    rows = []
    for i in _list(c, "/devices", "items"):
        product = i.get("product") or i.get("model") or ""
        if not ATA_PRODUCT.search(product):
            continue
        mac = (i.get("mac") or "").upper()
        name = i.get("displayName") or product
        short = f"{name} ({mac or i.get('serial', '')})"
        where = (location_names or {}).get(i.get("locationId") or "", "")
        rows.append({"label": f"{short} - {where}" if where else short, "name": short, "id": i.get("id", ""),
                     "telId": i.get("callingDeviceId") or i.get("id", ""), "mac": mac,
                     "model": product, "workspaceId": i.get("workspaceId") or i.get("placeId") or ""})
    return sorted(rows, key=lambda r: r["label"].lower())


def read_ata_ports(c: WebexClient, device_id: str) -> tuple[list[dict], int]:
    """(members, maxLineCount) of the device. A member is the raw API record: port, id, names, numbers."""
    data = c.call("GET", f"/telephony/config/devices/{device_id}/members")
    members = sorted(data.get("members") or [], key=lambda m: m.get("port") or 0)
    return members, int(data.get("maxLineCount") or 0)


def port_table(members: list[dict], max_ports: int) -> list[dict[str, str]]:
    """One row per port 1..max: port, configured ('1' or ''), workspace, number, extension, plus the blank input
    fields for an open port (kind is 'Existing' or 'New')."""
    by_port = {int(m.get("port") or 0): m for m in members}
    rows = []
    for n in range(1, max(max_ports, max(by_port, default=0)) + 1):
        m = by_port.get(n)
        name = f"{(m or {}).get('firstName', '')} {(m or {}).get('lastName', '')}".strip() if m else ""
        rows.append({"port": str(n), "configured": "1" if m else "", "current": name or (m or {}).get("id", ""),
                     "wid": (m or {}).get("id") or "", "line": (m or {}).get("phoneNumber") or "", "ext": (m or {}).get("extension") or "",
                     "kind": "Existing", "workspace": "", "extension": "", "number": ""})
    return rows


def search_ports(c: WebexClient, text: str, location_names: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Workspaces matching a name, phone number or extension, as {id, name, line, location}.

    A name is searched in the workspace list. Digits (with + - ( ) and spaces) are also searched as an extension
    and, from 10 digits, as a phone number among the numbers owned by workspaces."""
    text = text.strip()
    if not text:
        raise WebexError("Enter a workspace name, phone number or extension.")
    locations = location_names or {}
    found: dict[str, dict[str, str]] = {}

    def add(wid: str, name: str, line: str, location_id: str) -> None:
        if wid:
            found.setdefault(wid, {"id": wid, "name": name, "line": line, "location": locations.get(location_id, "")})

    digits = re.sub(r"\D", "", text)
    if digits and re.fullmatch(r"[\d\s+\-().]+", text):
        queries = [{"extension": digits}] + ([{"phoneNumber": normalize_e164(text)}] if len(digits) >= 10 else [])
        for q in queries:
            for r in c.call("GET", "/telephony/config/numbers", {**q, "ownerType": "PLACE", "max": 100}).get("phoneNumbers") or []:
                owner = r.get("owner") or {}
                line = " ".join(x for x in (r.get("phoneNumber"), f"x{r['extension']}" if r.get("extension") else "") if x)
                add(owner.get("id", ""), owner_name(owner), line, (r.get("location") or {}).get("id", ""))
    for i in c.call("GET", "/workspaces", {"displayName": text, "max": 100}).get("items") or []:
        add(i.get("id", ""), i.get("displayName", ""), _workspace_line(i), i.get("locationId") or _calling(i).get("locationId", ""))
    for r in found.values():  # the list often leaves the numbers out: read the workspace itself
        if not r["line"]:
            try:
                r["line"] = _workspace_line(c.call("GET", f"/workspaces/{r['id']}"))
            except WebexError:
                pass
    return sorted(found.values(), key=lambda r: r["name"].lower())


def _calling(workspace: dict) -> dict:
    return (workspace.get("calling") or {}).get("webexCalling") or {}


def _workspace_line(workspace: dict) -> str:
    """'+15551234567 x1001' from a workspace record's calling section, '' when it has neither."""
    calling = _calling(workspace)
    return " ".join(x for x in (calling.get("phoneNumber"), f"x{calling['extension']}" if calling.get("extension") else "") if x)


def find_ata_for_workspace(c: WebexClient, workspace_id: str, devices: list[dict[str, str]]) -> dict[str, str] | None:
    """The ATA/VG (one of `devices`, from list_ata_devices) the workspace is on a port of, or None.

    The workspace's device list is tried first (matched by MAC); when it does not show a gateway, every gateway's
    members are read."""
    try:
        listed = c.call("GET", f"/telephony/config/workspaces/{workspace_id}/devices").get("devices") or []
    except WebexError:
        listed = []
    macs = {re.sub(r"[^0-9A-Fa-f]", "", d.get("mac") or "").upper() for d in listed}
    for d in devices:
        if d["mac"] and d["mac"] in macs:
            return d
    for d in devices:
        if any(m.get("id") == workspace_id for m in read_ata_ports(c, d["telId"])[0]):
            return d
    return None


def append_port_note(c: WebexClient, workspace_id: str, device_label: str, port: int) -> None:
    """Add 'ATA/VG <device> port <n>' as a new line of the workspace's notes (unless it is already there)."""
    ws = c.call("GET", f"/workspaces/{workspace_id}")
    line = f"ATA/VG {device_label} port {port}"
    notes = (ws.get("notes") or "").strip()
    if line in notes.splitlines():
        return
    c.call("PUT", f"/workspaces/{workspace_id}",
           body={"displayName": ws.get("displayName", ""), "notes": f"{notes}\n{line}" if notes else line})


def update_ata(c: WebexClient, device_id: str, device_workspace_id: str, rows: list[dict[str, str]],
               cache: dict[str, str], device_label: str = "") -> str:
    """Fill open ports. rows are the open ports to fill: port, kind ('Existing' or 'New'), workspace, extension,
    number. Everything is checked before the first change. The members PUT replaces the list, so the current
    members are sent back as they are. Once the ports are assigned, 'ATA/VG <device_label> port <n>' is appended to
    each assigned workspace's notes (a notes failure is reported, not raised). A failure after workspaces were
    created leaves them."""
    rows = [{**r, "kind": r["kind"].lower()} for r in rows]
    members, max_ports = read_ata_ports(c, device_id)
    taken = {int(m.get("port") or 0) for m in members}
    location_id = ""
    if any(r["kind"] == "new" for r in rows):
        location_id = c.call("GET", f"/workspaces/{device_workspace_id}").get("locationId") or ""
        if not location_id:
            raise WebexError("The location of the device's workspace could not be read.")
    steps: list[tuple[int, str, dict | str]] = []  # (port, "new" body or "existing" id)
    seen: set[str] = set()
    for r in rows:
        port, name = int(r["port"]), r["workspace"].strip()
        if port in taken or port > max_ports:
            raise WebexError(f"Port {port} is not open.")
        if not name:
            raise WebexError(f"Port {port} needs a workspace name.")
        if name.lower() in seen:
            raise WebexError(f"Workspace {name} is listed more than once.")
        seen.add(name.lower())
        if r["kind"] == "new":
            if not (r["extension"].strip() or r["number"].strip()):
                raise WebexError(f"Port {port} needs an extension or a number for the new workspace.")
            if workspace_exists(c, {"workspace": name}, cache):
                raise WebexError(f"Workspace {name} already exists. Choose Existing for port {port}.")
            steps.append((port, "new", build_workspace_body(
                {"workspace": name, "extension": r["extension"], "number": r["number"]}, location_id)))
        else:
            steps.append((port, "existing", find_workspace_id(c, name)))
    if not steps:
        raise WebexError("No open port has a workspace to assign.")
    keep = [{k: m[k] for k in MEMBER_KEYS if k in m} for m in members]
    assigned: list[tuple[int, str]] = []
    added: list[str] = []  # numbers that did not exist and were added to the location
    for port, kind, what in steps:
        wid = what if kind == "existing" else create_workspace_adding_number(c, what, location_id, added)
        assigned.append((port, wid))
        keep.append({"port": port, "id": wid, "primaryOwner": port == 1 and not members, "lineType": "PRIMARY",
                     "lineWeight": 1, "hotlineEnabled": False, "hotlineDestination": "",
                     "allowCallDeclineEnabled": True, "t38FaxCompressionEnabled": False})
    c.call("PUT", f"/telephony/config/devices/{device_id}/members",
           body={"members": sorted(keep, key=lambda m: m["port"])})
    detail = f"Assigned {len(steps)} port(s): " + ", ".join(
        f"{p}{' (new workspace)' if k == 'new' else ''}" for p, k, _ in steps)
    if added:
        detail += f". Added number(s) to the location: {', '.join(added)}"
    unnoted = []
    for port, wid in assigned:
        try:
            append_port_note(c, wid, device_label, port)
        except WebexError as e:
            unnoted.append(f"port {port} ({e})")
    return detail + (f". Notes not updated: {'; '.join(unnoted)}" if unnoted else ". Notes updated")


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
