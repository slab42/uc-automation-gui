"""Webex call queues and hunt groups: create from CSV, replace agents, migrate a hunt group to a call queue.

Ported from webex/CreateCallQueue.py, UpdateCallQueueAgents.py, CreateHuntGroup.py, UpdateHuntGroupAgents.py
and migrate_huntgroup_callqueue.py (reference only). Request shapes are not tested against a real org.

Differences from the scripts: JSON booleans and numbers are real booleans and numbers (the create scripts sent
the strings "true" and "10"); the queue create no longer sends the org-specific announcement file id the script
hardcoded, so every greeting is DEFAULT; Update Agents refuses to save an empty agent list.
"""

import csv
import io
import json
from collections.abc import Callable

from .webex_api import WebexClient, WebexError

CALLING_LICENSE = "Webex Calling - Professional"
POLICIES = ("CIRCULAR", "REGULAR", "SIMULTANEOUS", "UNIFORM", "WEIGHTED")
PAGE = 100

QUEUES = "/telephony/config/queues"
HUNT_GROUPS = "/telephony/config/huntGroups"
VIRTUAL_LINES = "/telephony/config/virtualLines"


def location_path(location_id: str) -> str:
    return f"/telephony/config/locations/{location_id}"


# --- Lists (for the pickers) ---

def _list(c: WebexClient, path: str, key: str) -> list[dict]:
    items: list[dict] = []
    start = 0
    while True:
        page = c.call("GET", path, {"max": PAGE, "start": start}).get(key) or []
        items.extend(page)
        if len(page) < PAGE:
            return items
        start += PAGE


def _row(i: dict) -> dict[str, str]:
    number = i.get("phoneNumber") or i.get("extension") or ""
    if not number and isinstance(i.get("number"), dict):  # virtual lines
        number = i["number"].get("external") or i["number"].get("extension") or ""
    name = i.get("name") or i.get("displayName") or f"{i.get('firstName', '')} {i.get('lastName', '')}".strip()
    loc = i.get("locationName") or (i.get("location") or {}).get("name", "")
    loc_id = i.get("locationId") or (i.get("location") or {}).get("id", "")
    return {"id": i.get("id", ""), "name": name, "location": loc, "locationId": loc_id, "number": number,
            "extension": i.get("extension") or (i.get("number") or {}).get("extension", "")}


def list_queues(c: WebexClient) -> list[dict[str, str]]:
    return sorted((_row(i) for i in _list(c, QUEUES, "queues")), key=lambda r: r["name"].lower())


def list_hunt_groups(c: WebexClient) -> list[dict[str, str]]:
    return sorted((_row(i) for i in _list(c, HUNT_GROUPS, "huntGroups")), key=lambda r: r["name"].lower())


def list_virtual_lines(c: WebexClient) -> list[dict[str, str]]:
    return sorted((_row(i) for i in _list(c, VIRTUAL_LINES, "virtualLines")), key=lambda r: r["name"].lower())


# --- Agents ---

def calling_license_ids(c: WebexClient) -> set[str] | None:
    """Ids of the Calling license. None when the lookup is not allowed (no licenses scope): the check is then skipped."""
    if "licenses" not in c.cache:
        try:
            items = c.call("GET", "/licenses").get("items") or []
            c.cache["licenses"] = {i["id"] for i in items if i.get("name") == CALLING_LICENSE}
        except WebexError:
            c.cache["licenses"] = None
    return c.cache["licenses"]


def lookup_calling_user(c: WebexClient, email: str) -> str:
    """Person id of the user with this email who has a Calling license. Raises WebexError otherwise."""
    items = c.call("GET", "/people", {"email": email}).get("items") or []
    licenses = calling_license_ids(c)
    for u in items:
        if licenses is None or licenses & set(u.get("licenses") or []):
            return u["id"]
    raise WebexError(f"{email}: user not found or has no Calling license.")


def _lookup_virtual_line(c: WebexClient, number: str) -> str:
    lines = c.call("GET", VIRTUAL_LINES, {"phoneNumber": number}).get("virtualLines") or []
    if not lines:
        raise WebexError(f"{number}: no virtual line has this number.")
    return lines[0]["id"]


def _lookup_extension(c: WebexClient, extension: str) -> str:
    found = c.call("GET", "/telephony/config/numbers", {"extension": extension}).get("phoneNumbers") or []
    owner = (found[0].get("owner") or {}).get("id") if found else None
    if not owner:
        raise WebexError(f"{extension}: extension not found or has no owner.")
    return owner


def resolve_agent(c: WebexClient, entry: str, numeric: str | None) -> str:
    """Agent id from an email, or (when `numeric` is "virtual_line" or "extension") from a number."""
    if entry.isnumeric():
        if numeric == "virtual_line":
            return _lookup_virtual_line(c, entry)
        if numeric == "extension":
            return _lookup_extension(c, entry)
        raise WebexError(f"{entry}: the agent must be an email address.")
    return lookup_calling_user(c, entry)


def resolve_agents(c: WebexClient, entries: list[str], numeric: str | None) -> tuple[list[dict], list[str]]:
    """([{"id": ...}], skipped messages). Entries that cannot be resolved are skipped, not fatal."""
    agents, skipped = [], []
    for e in entries:
        try:
            agents.append({"id": resolve_agent(c, e, numeric)})
        except WebexError as err:
            skipped.append(str(err))
    return agents, skipped


def parse_agent_list_csv(data: bytes) -> list[str]:
    """Header row required. The first column holds the agents (email, or number where allowed)."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    if not rows:
        raise ValueError("The CSV file is empty.")
    return [r[0].strip() for r in rows[1:] if r and r[0].strip()]


def replace_agents(c: WebexClient, kind: str, group: dict[str, str], entries: list[str], add: bool = False) -> str:
    """Replace the whole agent list of a queue or hunt group ("queue" / "hunt"), or with add=True keep the
    current agents and add the new ones."""
    numeric = "virtual_line" if kind == "hunt" else None
    agents, skipped = resolve_agents(c, entries, numeric)
    if not agents:
        raise WebexError("None of the agents could be resolved, so nothing was changed. " + "; ".join(skipped))
    path = f"{location_path(group['locationId'])}/{'huntGroups' if kind == 'hunt' else 'queues'}/{group['id']}"
    note = f" Skipped: {'; '.join(skipped)}" if skipped else ""
    if add:
        current = [a["id"] for a in c.call("GET", path).get("agents") or []]
        new = [a for a in dict.fromkeys(a["id"] for a in agents) if a not in current]
        if new:
            c.call("PUT", path, body={"agents": [{"id": i} for i in current + new]})
        already = len(set(a["id"] for a in agents)) - len(new)
        return f"{len(new)} agent(s) added, {already} already in the list ({len(current) + len(new)} total).{note}"
    c.call("PUT", path, body={"agents": agents})
    return f"Agents replaced ({len(agents)} set).{note}"


# --- Create ---

CREATE_COLUMNS = ("name", "location", "firstName", "lastName", "phoneNumber", "extension", "policy", "destination")


def parse_group_csv(data: bytes) -> list[dict]:
    """Header row required: name, location (a location name), policy, destination are required;
    firstName, lastName, phoneNumber, extension optional; agent columns are every header starting with 'agent'."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    lookup = {(h or "").strip().lower(): h for h in reader.fieldnames}
    loc_col = next((lookup[k] for k in ("location", "locationid", "locationname") if k in lookup), None)
    if "name" not in lookup or loc_col is None:
        raise ValueError("The CSV needs a header row with at least the columns name and location.")
    agent_cols = [h for k, h in lookup.items() if k.startswith("agent")]
    rows = []
    for raw in reader:
        row = {"name": (raw.get(lookup["name"]) or "").strip(), "location": (raw.get(loc_col) or "").strip()}
        for f in ("firstName", "lastName", "phoneNumber", "extension", "policy", "destination"):
            row[f] = (raw.get(lookup[f.lower()]) or "").strip() if f.lower() in lookup else ""
        row["agents"] = [(raw.get(h) or "").strip() for h in agent_cols if (raw.get(h) or "").strip()]
        if row["name"] or row["location"] or row["agents"]:
            rows.append(row)
    return rows


def _greeting(**extra) -> dict:
    return {"enabled": True, "greeting": "DEFAULT", **extra}


def queue_body(row: dict, agents: list[dict]) -> dict:
    dest = row["destination"]
    return {
        "name": row["name"], "phoneNumber": row["phoneNumber"], "extension": row["extension"],
        "firstName": row["firstName"], "lastName": row["lastName"],
        "callPolicies": {
            "policy": row["policy"], "routingType": "SKILL_BASED", "waitingEnabled": False,
            "noAnswer": {"nextAgentEnabled": True, "nextAgentRings": 3, "forwardEnabled": True,
                         "numberOfRings": 15, "destination": dest, "destinationVoicemailEnabled": False},
            "businessContinuity": {"enabled": True, "destination": dest, "destinationVoicemailEnabled": False},
        },
        "queueSettings": {
            "queueSize": 10, "callOfferToneEnabled": True, "resetCallStatisticsEnabled": True,
            "overflow": {"action": "PERFORM_BUSY_TREATMENT", "overflowAfterWaitEnabled": False,
                         "overflowAfterWaitTime": 30, "playOverflowGreetingEnabled": False, "greeting": "DEFAULT"},
            "welcomeMessage": _greeting(alwaysEnabled=False),
            "waitMessage": {"enabled": True, "waitMode": "POSITION", "handlingTime": 100,
                            "defaultHandlingTime": 100, "queuePosition": 100, "highVolumeMessageEnabled": False,
                            "estimatedWaitingTime": 600, "playUpdatedEstimatedWaitMessage": True},
            "comfortMessage": _greeting(timeBetweenMessages=10),
            "mohMessage": {"normalSource": _greeting(), "alternateSource": _greeting()},
            "comfortMessageBypass": {"enabled": False, "callWaitingAgeThreshold": 30, "greeting": "DEFAULT"},
            "whisperMessage": _greeting(),
        },
        "agents": agents, "enabled": True, "phoneNumberForOutgoingCallsEnabled": True,
        "allowAgentJoinEnabled": True,
    }


def hunt_group_body(row: dict, agents: list[dict]) -> dict:
    dest = row["destination"]
    return {
        "name": row["name"], "phoneNumber": row["phoneNumber"], "extension": row["extension"],
        "firstName": row["firstName"], "lastName": row["lastName"],
        "callPolicies": {
            "policy": row["policy"], "waitingEnabled": False,
            "noAnswer": {"nextAgentEnabled": True, "nextAgentRings": 5, "forwardEnabled": True,
                         "numberOfRings": 15, "destination": dest, "destinationVoicemailEnabled": False},
            "businessContinuity": {"enabled": True, "destination": dest, "destinationVoicemailEnabled": False},
        },
        "agents": agents, "enabled": True,
    }


def _location_id(c: WebexClient, name: str, cache: dict[str, str]) -> str:
    from .webex_routing import find_location_id
    return find_location_id(c, name, cache)


def create_group(c: WebexClient, kind: str, row: dict, cache: dict[str, str]) -> str:
    """Create one queue or hunt group ("queue" / "hunt") from a parsed CSV row."""
    for f in ("name", "location", "policy", "destination"):
        if not row.get(f):
            raise WebexError(f"{f} is required.")
    row = {**row, "policy": row["policy"].upper()}
    if row["policy"] not in POLICIES:
        raise WebexError(f"policy must be one of {', '.join(POLICIES)}.")
    if not row["agents"]:
        raise WebexError("At least one agent is required.")
    location_id = _location_id(c, row["location"], cache)
    agents, skipped = resolve_agents(c, row["agents"], "virtual_line" if kind == "queue" else "extension")
    if not agents:
        raise WebexError("None of the agents could be resolved. " + "; ".join(skipped))
    body = queue_body(row, agents) if kind == "queue" else hunt_group_body(row, agents)
    body = {k: v for k, v in body.items() if v != ""}  # blank phone/extension/name fields are left out
    result = c.call("POST", f"{location_path(location_id)}/{'queues' if kind == 'queue' else 'huntGroups'}", body=body)
    note = f" Skipped agents: {'; '.join(skipped)}" if skipped else ""
    return f"Created in {row['location']} with {len(agents)} agent(s) ({result.get('id', '')[-12:]}).{note}"


# --- Migrate hunt group to call queue ---

SECONDS_PER_RING = 6  # Webex rings for about 6 seconds


def overflow_from_no_answer(na: dict) -> dict:
    """Queue overflow that approximates a hunt group no-answer forward: after rings x 6 s waiting, transfer."""
    overflow = {"action": "PERFORM_BUSY_TREATMENT"}
    if na.get("forwardEnabled") and na.get("destination"):
        overflow = {"action": "TRANSFER_TO_PHONE_NUMBER", "transferNumber": na["destination"],
                    "overflowAfterWaitEnabled": True,
                    "overflowAfterWaitTime": max(1, int(na.get("numberOfRings") or 15)) * SECONDS_PER_RING}
    return overflow


# Hunt group settings with no Call Queue create equivalent
def unmapped_notes(hg: dict) -> list[str]:
    policies = hg.get("callPolicies") or {}
    na = policies.get("noAnswer") or {}
    notes = []
    for key, label in (("busyRedirect", "Busy redirect"), ("businessContinuityRedirect", "Business continuity")):
        if (policies.get(key) or {}).get("enabled"):
            notes.append(f"{label}: {json.dumps(policies[key])}")
    if (hg.get("alternateNumberSettings") or {}).get("alternateNumbers"):
        notes.append(f"Alternate numbers: {json.dumps(hg['alternateNumberSettings'])}")
    return notes


def queue_body_from_hunt_group(hg: dict) -> dict:
    policies = hg.get("callPolicies") or {}
    na = policies.get("noAnswer") or {}
    call_policies = {
        "routingType": "PRIORITY_BASED", "policy": policies.get("policy", "CIRCULAR"),
        "callBounce": {"callBounceEnabled": bool(na.get("nextAgentEnabled", False)),
                       "callBounceMaxRings": na.get("nextAgentRings", 3)},
    }
    if hg.get("distinctiveRing"):
        call_policies["distinctiveRing"] = hg["distinctiveRing"]
    body = {
        "name": hg["name"], "callPolicies": call_policies,
        "queueSettings": {"queueSize": 10, "overflow": overflow_from_no_answer(na)},
        "allowAgentJoinEnabled": True, "phoneNumberForOutgoingCallsEnabled": True,
        "agents": [{"id": a["id"]} for a in hg.get("agents") or []],
    }
    for key in ("phoneNumber", "extension", "firstName", "lastName", "languageCode", "timeZone", "enabled"):
        if hg.get(key) not in (None, ""):
            body[key] = hg[key]
    return body


# --- Migrate call queue to hunt group ---

HG_MIN_RINGS, HG_MAX_RINGS = 2, 20


def queue_unmapped_notes(q: dict) -> list[str]:
    """Queue settings a hunt group cannot hold."""
    notes = []
    settings = q.get("queueSettings") or {}
    overflow = settings.get("overflow") or {}
    if overflow.get("action") and overflow["action"] != "PERFORM_BUSY_TREATMENT" and not _overflow_transfer(q):
        notes.append(f"Overflow action {overflow['action']}")
    wait = _overflow_transfer(q)
    if wait:
        rings = round(wait[1] / SECONDS_PER_RING)
        if not HG_MIN_RINGS <= rings <= HG_MAX_RINGS:
            notes.append(f"Overflow wait of {wait[1]} s is about {rings} rings; hunt groups allow "
                         f"{HG_MIN_RINGS} to {HG_MAX_RINGS}, so it is set to {_clamp_rings(rings)}")
    if settings.get("queueSize"):
        notes.append(f"Queue size {settings['queueSize']} (a hunt group has no waiting queue)")
    for key, label in (("welcomeMessage", "Welcome message"), ("waitMessage", "Wait message"),
                       ("comfortMessage", "Comfort message"), ("mohMessage", "Music on hold"),
                       ("whisperMessage", "Whisper message"), ("comfortMessageBypass", "Comfort message bypass")):
        if (settings.get(key) or {}).get("enabled") or (settings.get(key) or {}).get("normalSource", {}).get("enabled"):
            notes.append(label)
    if (q.get("callPolicies") or {}).get("routingType") == "SKILL_BASED":
        notes.append("Skill based routing and agent skill levels")
    if any(a.get("skillLevel", 1) != 1 for a in q.get("agents") or []):
        notes.append("Agent skill levels")
    if (q.get("alternateNumberSettings") or {}).get("alternateNumbers"):
        notes.append(f"Alternate numbers: {json.dumps(q['alternateNumberSettings'])}")
    return notes


def _overflow_transfer(q: dict) -> tuple[str, int] | None:
    """(number, wait seconds) when the queue transfers to a number after waiting, else None."""
    ov = (q.get("queueSettings") or {}).get("overflow") or {}
    if ov.get("action") == "TRANSFER_TO_PHONE_NUMBER" and ov.get("transferNumber") and ov.get("overflowAfterWaitEnabled"):
        return ov["transferNumber"], int(ov.get("overflowAfterWaitTime") or 0)
    return None


def _clamp_rings(rings: int) -> int:
    return max(HG_MIN_RINGS, min(HG_MAX_RINGS, rings))


def hunt_group_body_from_queue(q: dict) -> dict:
    policies = q.get("callPolicies") or {}
    bounce = policies.get("callBounce") or {}
    no_answer = {"nextAgentEnabled": bool(bounce.get("callBounceEnabled", False)),
                 "nextAgentRings": _clamp_rings(int(bounce.get("callBounceMaxRings") or 3)),
                 "forwardEnabled": False}
    transfer = _overflow_transfer(q)
    if transfer:
        no_answer.update(forwardEnabled=True, destination=transfer[0],
                         numberOfRings=_clamp_rings(round(transfer[1] / SECONDS_PER_RING)),
                         destinationVoicemailEnabled=False)
    call_policies = {"policy": policies.get("policy", "CIRCULAR"), "waitingEnabled": False, "noAnswer": no_answer}
    body = {"name": q["name"], "callPolicies": call_policies,
            "agents": [{"id": a["id"]} for a in q.get("agents") or []]}
    for key in ("phoneNumber", "extension", "firstName", "lastName", "languageCode", "timeZone", "enabled"):
        if q.get(key) not in (None, ""):
            body[key] = q[key]
    return body


def read_queue(c: WebexClient, group: dict[str, str]) -> dict:
    q = c.call("GET", f"{location_path(group['locationId'])}/queues/{group['id']}")
    q.setdefault("name", group["name"])
    return q


def migrate_queue(c: WebexClient, group: dict[str, str], q: dict, backup_path: str,
                  note: Callable[[str], None]) -> str:
    """Delete the call queue (frees its number and extension), then create the hunt group with the same agents.

    The caller writes the backup JSON first. If the hunt group create fails the queue is already gone.
    """
    loc = location_path(group["locationId"])
    c.call("DELETE", f"{loc}/queues/{group['id']}")
    note(f"Call queue deleted: {q['name']}")
    try:
        result = c.call("POST", f"{loc}/huntGroups", body=hunt_group_body_from_queue(q))
    except WebexError as e:
        raise WebexError(f"Hunt group creation failed ({e}). The call queue is already deleted; "
                         f"the settings are in the backup {backup_path}") from e
    note(f"Hunt group created: {q['name']} ({result.get('id', '')})")
    return f"Call queue replaced by a hunt group with {len(q.get('agents') or [])} agent(s)."


# Read-only keys in a hunt group GET that the create call does not accept
_HG_READ_ONLY = {"id", "location", "locationId", "locationName", "toPhoneNumber"}


def backup_document(group: dict[str, str], hg: dict) -> dict:
    """Hunt group settings plus where it lived, so the JSON can be restored on its own."""
    return {**hg, "location": group["location"], "locationId": group["locationId"]}


def hunt_group_body_from_backup(doc: dict) -> dict:
    body = {k: v for k, v in doc.items() if k not in _HG_READ_ONLY and v not in (None, "")}
    body["agents"] = [{"id": a["id"]} for a in doc.get("agents") or [] if a.get("id")]
    return body


def restore_hunt_group(c: WebexClient, doc: dict, cache: dict[str, str]) -> str:
    """Re-create a hunt group from a JSON backup written by the migration."""
    if not isinstance(doc, dict) or not doc.get("name"):
        raise WebexError("This is not a hunt group backup (no name).")
    if "queueSettings" in doc:
        raise WebexError("This is a call queue backup. Restore it on the Call Queues page.")
    location_id = doc.get("locationId") or (
        _location_id(c, doc["location"], cache) if doc.get("location") else "")
    if not location_id:
        raise WebexError("The backup has no location.")
    result = c.call("POST", f"{location_path(location_id)}/huntGroups", body=hunt_group_body_from_backup(doc))
    return f"Restored in {doc.get('location', location_id)} with {len(doc.get('agents') or [])} agent(s) " \
           f"({result.get('id', '')[-12:]})."


def queue_body_from_backup(doc: dict) -> dict:
    body = {k: v for k, v in doc.items() if k not in _HG_READ_ONLY and v not in (None, "")}
    body["agents"] = [{k: a[k] for k in ("id", "skillLevel", "joinEnabled") if k in a}
                      for a in doc.get("agents") or [] if a.get("id")]
    return body


def restore_queue(c: WebexClient, doc: dict, cache: dict[str, str]) -> str:
    """Re-create a call queue from a JSON backup written by the migration to a hunt group."""
    if not isinstance(doc, dict) or not doc.get("name"):
        raise WebexError("This is not a call queue backup (no name).")
    if "queueSettings" not in doc:
        raise WebexError("This is not a call queue backup (no queue settings). Hunt group backups are restored "
                         "on the Hunt Groups page.")
    location_id = doc.get("locationId") or (
        _location_id(c, doc["location"], cache) if doc.get("location") else "")
    if not location_id:
        raise WebexError("The backup has no location.")
    result = c.call("POST", f"{location_path(location_id)}/queues", body=queue_body_from_backup(doc))
    return (f"Restored in {doc.get('location', location_id)} with {len(doc.get('agents') or [])} agent(s) "
            f"({result.get('id', '')[-12:]}).")


def read_hunt_group(c: WebexClient, group: dict[str, str]) -> dict:
    hg = c.call("GET", f"{location_path(group['locationId'])}/huntGroups/{group['id']}")
    hg.setdefault("name", group["name"])
    return hg


def migrate_hunt_group(c: WebexClient, group: dict[str, str], hg: dict, backup_path: str,
                       note: Callable[[str], None]) -> str:
    """Delete the hunt group (frees its number and extension), create the queue, join the agents.

    The caller writes the backup JSON first. If the queue create fails the hunt group is already gone, and the
    error says where the backup is.
    """
    loc = location_path(group["locationId"])
    c.call("DELETE", f"{loc}/huntGroups/{group['id']}")
    note(f"Hunt group deleted: {hg['name']}")
    try:
        result = c.call("POST", f"{loc}/queues", body=queue_body_from_hunt_group(hg))
    except WebexError as e:
        raise WebexError(f"Call queue creation failed ({e}). The hunt group is already deleted; "
                         f"re-create it from the backup {backup_path}") from e
    queue_id = result.get("id", "")
    note(f"Call queue created: {hg['name']} ({queue_id})")
    msg = "Hunt group replaced by a call queue."
    if hg.get("agents") and queue_id:
        try:
            queue = c.call("GET", f"{loc}/queues/{queue_id}")
            agents = queue.get("agents") or []
            if agents and not all(a.get("joinEnabled") for a in agents):
                c.call("PUT", f"{loc}/queues/{queue_id}",
                       body={"agents": [{"id": a["id"], "joinEnabled": True} for a in agents]})
            msg += f" {len(agents)} agent(s) joined."
        except WebexError as e:
            msg += f" Could not confirm agents are joined ({e}). Check the queue in Control Hub."
    return msg
