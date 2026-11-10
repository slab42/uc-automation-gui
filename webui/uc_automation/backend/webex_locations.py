"""Webex locations: schedules (export, update from CSV, copy, remove past events), RedSky E911 and PSTN migration.

Ported from webex/export_location_holidaySchedule.py, update_location_holidayschedule.py, copy_location_schedule.py,
remove_location_scheduleDatesPast.py, locations_e911_status.py and locations_DisableRedSky.py (reference only).
Not tested against a real org.
"""

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .countries import COUNTRIES
from .webex_api import WebexClient, WebexError
from .webex_groups import _list, location_path

HOLIDAYS = "holidays"
CSV_HEADER = ["Name", "Event action", "Event name", "Event start date", "Event end date"]
E911_WORKERS = 5


def list_locations(c: WebexClient) -> list[dict[str, str]]:
    """Locations as picker rows (the Calling API list, not the core /v1/locations)."""
    rows = [{"id": i["id"], "name": i.get("name", ""), "location": "", "locationId": i["id"], "number": ""}
            for i in _list(c, "/telephony/config/locations", "locations")]
    return sorted(rows, key=lambda r: r["name"].lower())


# --- Schedules ---

def list_schedules(c: WebexClient, location_id: str) -> list[dict[str, str]]:
    items = c.call("GET", f"{location_path(location_id)}/schedules").get("schedules") or []
    return [{"id": s["id"], "name": s.get("name", ""), "type": s.get("type", ""),
             "label": f"{s.get('name', '')} ({s.get('type', '')})"} for s in items]


def get_schedule(c: WebexClient, location_id: str, sched_type: str, sched_id: str) -> dict:
    return c.call("GET", f"{location_path(location_id)}/schedules/{sched_type}/{sched_id}")


def format_date(value: str) -> str:
    """YYYY-MM-DD to M/D/YY (the CSV template format)."""
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
        return f"{d.month}/{d.day}/{d.strftime('%y')}"
    except (TypeError, ValueError):
        return value or ""


def parse_date(value: str) -> str | None:
    """M/D/YY, M/D/YYYY or YYYY-MM-DD to YYYY-MM-DD; None when invalid."""
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((value or "").strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def export_schedule_csv(schedule_name: str, events: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_HEADER)
    for e in events:
        start = e.get("startDate", "")
        w.writerow([schedule_name, "ADD", e.get("name", ""), format_date(start), format_date(e.get("endDate") or start)])
    return buf.getvalue()


def parse_holiday_csv(data: bytes) -> tuple[dict[str, list[dict]], list[str]]:
    """({schedule name: [rows]}, warnings for skipped rows). Columns: Name, Event action (ADD/REMOVE), Event name,
    Event start date, Event end date. Blank rows are ignored."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    lookup = {(h or "").strip().lower(): h for h in reader.fieldnames}
    need = ["name", "event action", "event name", "event start date"]
    if any(n not in lookup for n in need):
        raise ValueError("The CSV needs the header row: " + ", ".join(CSV_HEADER))
    get = lambda raw, k: (raw.get(lookup[k]) or "").strip() if k in lookup else ""  # noqa: E731
    schedules: dict[str, list[dict]] = {}
    warnings: list[str] = []
    for line, raw in enumerate(reader, 2):
        name, action, event = get(raw, "name"), get(raw, "event action").upper(), get(raw, "event name")
        if not (name or action or event):
            continue
        start = parse_date(get(raw, "event start date"))
        end = parse_date(get(raw, "event end date")) or start
        if not name or not event or action not in ("ADD", "REMOVE") or not start:
            warnings.append(f"Line {line} skipped: invalid row")
            continue
        schedules.setdefault(name, []).append({"action": action, "name": event, "start": start, "end": end})
    return schedules, warnings


def _event_body(r: dict) -> dict:
    return {"name": r["name"], "startDate": r["start"], "endDate": r["end"], "allDayEnabled": True}


def build_update_plan(c: WebexClient, location_id: str, schedules: dict[str, list[dict]]) -> list[dict]:
    """Per CSV schedule: what would be created, added or removed. Holiday schedules only."""
    existing = {s["name"].lower(): s for s in list_schedules(c, location_id) if s["type"] == HOLIDAYS}
    plan = []
    for name, rows in schedules.items():
        sched = existing.get(name.lower())
        events = get_schedule(c, location_id, HOLIDAYS, sched["id"]).get("events", []) if sched else []
        current = {(e.get("name") or "").lower(): e for e in events}
        adds, removes, notes = [], [], []
        for r in rows:
            key = r["name"].lower()
            if r["action"] == "ADD":
                if key in current:
                    notes.append(f'"{r["name"]}" already exists')
                else:
                    adds.append(r)
                    current[key] = {}
            elif not sched:
                notes.append(f'REMOVE "{r["name"]}" skipped: schedule does not exist')
            elif current.get(key, {}).get("id"):
                removes.append(current[key])
            else:
                notes.append(f'REMOVE "{r["name"]}" skipped: event not found')
        plan.append({"name": name, "schedule": sched, "adds": adds, "removes": removes, "notes": notes})
    return plan


def apply_update_plan(c: WebexClient, location_id: str, plan: list[dict]) -> list[tuple[str, str]]:
    """Returns (label, detail) per schedule; raises WebexError for a schedule when any step failed."""
    base = f"{location_path(location_id)}/schedules"
    out = []
    for item in plan:
        sched, adds = item["schedule"], item["adds"]
        done = 0
        try:
            if not sched:
                if adds:
                    c.call("POST", base, body={"type": HOLIDAYS, "name": item["name"],
                                               "events": [_event_body(r) for r in adds]})
                    done = len(adds)
                out.append((item["name"], f"Created with {done} event(s)"))
                continue
            for r in adds:
                c.call("POST", f"{base}/{HOLIDAYS}/{sched['id']}/events", body=_event_body(r))
                done += 1
            for e in item["removes"]:
                c.call("DELETE", f"{base}/{HOLIDAYS}/{sched['id']}/events/{e['id']}")
                done += 1
            out.append((item["name"], f"{len(adds)} added, {len(item['removes'])} removed"))
        except WebexError as e:
            raise WebexError(f"{item['name']}: {e} ({done} change(s) done before the error)") from e
    return out


def copy_schedule_to(c: WebexClient, source_body: dict, sched_type: str, sched_name: str, target_id: str) -> str:
    """Copy a schedule to one location: create it, or add missing events and update ones that differ."""
    base = f"{location_path(target_id)}/schedules"
    match = next((s for s in list_schedules(c, target_id)
                  if s["type"] == sched_type and s["name"].lower() == sched_name.lower()), None)
    if match is None:
        c.call("POST", base, body=source_body)
        return f'Created "{sched_name}"'
    current = {(e.get("name") or "").lower(): e
               for e in get_schedule(c, target_id, sched_type, match["id"]).get("events", [])}
    changes = 0
    for event in source_body["events"]:
        cur = current.get((event.get("name") or "").lower())
        if cur is None:
            c.call("POST", f"{base}/{sched_type}/{match['id']}/events", body=event)
        elif {k: v for k, v in cur.items() if k != "id"} != event:
            c.call("PUT", f"{base}/{sched_type}/{match['id']}/events/{cur['id']}", body=event)
        else:
            continue
        changes += 1
    return f"Updated {changes} event(s)" if changes else "Already up to date"


def copy_body(schedule: dict, detail: dict) -> dict:
    """Create body from the source schedule, dropping server-assigned event ids."""
    return {"type": schedule["type"], "name": schedule["name"],
            "events": [{k: v for k, v in e.items() if k != "id"} for e in detail.get("events", [])]}


def find_past_events(c: WebexClient, location: dict[str, str], today: str) -> list[dict[str, str]]:
    """One-time holiday events that ended before `today` (YYYY-MM-DD). Recurring events and business hours are ignored."""
    found = []
    for s in list_schedules(c, location["id"]):
        if s["type"] != HOLIDAYS:
            continue
        for e in get_schedule(c, location["id"], HOLIDAYS, s["id"]).get("events", []):
            if e.get("recurrence"):
                continue
            start = e.get("startDate") or ""
            end = e.get("endDate") or start
            if end and end < today:
                dates = format_date(start) if start == end else f"{format_date(start)} - {format_date(end)}"
                found.append({"key": f"{location['id']}|{s['id']}|{e['id']}", "location": location["name"],
                              "locationId": location["id"], "schedule": s["name"], "scheduleId": s["id"],
                              "event": e.get("name", ""), "eventId": e["id"], "dates": dates})
    return found


def delete_event(c: WebexClient, item: dict[str, str]) -> str:
    c.call("DELETE", f"{location_path(item['locationId'])}/schedules/{HOLIDAYS}/{item['scheduleId']}/events/{item['eventId']}")
    return "Deleted"


# --- Voice Portal (VM Portal) numbers ---

def voice_portal_numbers(c: WebexClient, locations: list[dict[str, str]]) -> list[dict[str, str]]:
    """Phone number and extension of each location's voice portal (one call each, a few at a time).
    A location whose portal cannot be read gets an Error text."""
    def one(loc: dict[str, str]) -> dict[str, str]:
        try:
            vp = c.call("GET", f"{location_path(loc['id'])}/voicePortal")
        except WebexError as e:
            return {"id": loc["id"], "name": loc["name"], "portal": "", "number": "", "extension": "",
                    "error": str(e)}
        return {"id": loc["id"], "name": loc["name"], "portal": str(vp.get("name") or ""),
                "number": str(vp.get("phoneNumber") or ""),
                "extension": str(vp.get("extension") or ""), "error": ""}
    with ThreadPoolExecutor(max_workers=E911_WORKERS) as pool:
        return list(pool.map(one, locations))


def set_voice_portal(c: WebexClient, location_id: str, extension: str, name: str) -> str:
    """Change the voice portal extension and/or name of a location. The PUT needs the portal's other mandatory
    settings (name, languageCode), so read them first and send them back unchanged except the new values."""
    path = f"{location_path(location_id)}/voicePortal"
    cur = c.call("GET", path)
    body = {k: cur[k] for k in ("name", "languageCode", "phoneNumber", "extension", "directLineCallerIdName", "dialByName")
            if cur.get(k) not in (None, "")}
    if "directLineCallerIdName" not in body:  # deprecated fields, only when the new caller ID object is absent
        body.update({k: cur[k] for k in ("firstName", "lastName") if cur.get(k)})
    done = []
    if extension:
        body["extension"] = extension
        done.append(f"Extension set to {extension}")
    if name:
        body["name"] = name
        done.append(f"Name set to {name}")
    c.call("PUT", path, body=body)
    return ", ".join(done)


def voice_portal_csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Location", "Voice Portal Name", "VM Portal Phone Number", "VM Portal Extension"])
    for r in rows:
        w.writerow([r["name"], r["portal"], r["number"], r["extension"]])
    return buf.getvalue()


# --- RedSky E911 ---

def e911_status(c: WebexClient, locations: list[dict[str, str]]) -> list[dict[str, str]]:
    """Compliance status, integration and routing flags per location (two calls each, a few at a time)."""
    def one(loc: dict[str, str]) -> dict[str, str]:
        def get(path: str) -> dict | None:
            try:
                return c.call("GET", f"{location_path(loc['id'])}/redSky{path}")
            except WebexError:
                return None
        st, params = get("/status"), get("")
        return {"id": loc["id"], "name": loc["name"],
                "status": (st or {}).get("complianceStatus", "ERROR") if st is not None else "ERROR",
                "integration": str((params or {}).get("integrationEnabled", "")) if params is not None else "ERROR",
                "routing": str((params or {}).get("routingEnabled", "")) if params is not None else "ERROR"}
    with ThreadPoolExecutor(max_workers=E911_WORKERS) as pool:
        return list(pool.map(one, locations))


def e911_csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Location", "Compliance Status", "Integration Enabled", "Routing Enabled"])
    for r in rows:
        w.writerow([r["name"], r["status"], r["integration"], r["routing"]])
    return buf.getvalue()


def opt_out_redsky(c: WebexClient, location_id: str) -> str:
    c.call("PUT", f"{location_path(location_id)}/redSky/status", body={"complianceStatus": "OPTED_OUT"})
    return "Opted out"


def parse_location_names_csv(data: bytes) -> list[str]:
    """First column after a header row."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    if not rows:
        raise ValueError("The CSV file is empty.")
    return [r[0].strip() for r in rows[1:] if r and r[0].strip()]


# --- PSTN connection ---

def get_connection(c: WebexClient, location_id: str) -> dict[str, str]:
    """The location's current PSTN connection as display text."""
    cur = c.call("GET", f"/telephony/pstn/locations/{location_id}/connection")
    if c.log is not None:
        c.log.info(f"Connection response keys: {sorted(cur)}")
    return {"type": cur.get("pstnConnectionType", ""), "name": cur.get("displayName", ""), "id": cur.get("id", ""),
            "routeType": cur.get("routeType", ""), "routeId": cur.get("routeId", "")}


def org_cloud_connections(c: WebexClient, locations: list[dict[str, str]]) -> list[dict[str, str]]:
    """Cloud (non-integrated CCP) connections already in use by any location, as targets with kind CONNECTION.

    The options endpoint is answered per location and can leave out a provider another location uses (for
    example one tied to the location's country), so these ids are offered too. Webex decides on the PUT
    whether the location may use one."""
    def one(loc: dict[str, str]) -> dict | None:
        try:
            return c.call("GET", f"/telephony/pstn/locations/{loc['id']}/connection")
        except WebexError:
            return None
    with ThreadPoolExecutor(max_workers=E911_WORKERS) as pool:
        conns = list(pool.map(one, locations))
    found = {x["id"]: {"label": f"Cloud: {x.get('displayName', '')}", "kind": "CONNECTION", "id": x["id"]}
             for x in conns if x and x.get("pstnConnectionType") == "NON_INTEGRATED_CCP" and x.get("id")}
    return list(found.values())


def pstn_targets(c: WebexClient, location_id: str, extra: list[dict[str, str]] = (),
                 current: dict[str, str] | None = None) -> list[dict[str, str]]:
    """What a location can be moved to: premises trunks and route groups, plus the cloud connection options
    (and `extra`, cloud connections other locations use).

    Each row is {"label", "kind", "id"}; kind is TRUNK, ROUTE_GROUP or CONNECTION (a cloud option id).
    The premises-based option is skipped, a trunk or route group stands for it. Integrated CCP and Cisco PSTN
    cannot be set through the API and are not offered."""
    out = [{"label": f"Trunk: {t.get('name', '')}", "kind": "TRUNK", "id": t["id"]}
           for t in _list(c, "/telephony/config/premisePstn/trunks", "trunks")]
    out += [{"label": f"Route Group: {g.get('name', '')}", "kind": "ROUTE_GROUP", "id": g["id"]}
            for g in _list(c, "/telephony/config/premisePstn/routeGroups", "routeGroups")]
    opts = c.call("GET", f"/telephony/pstn/locations/{location_id}/connectionOptions").get("items") or []
    out += [{"label": f"Cloud: {o.get('displayName', '')}", "kind": "CONNECTION", "id": o["id"]}
            for o in opts if "premises" not in (o.get("displayName") or "").lower()]
    if current and current.get("type") == "NON_INTEGRATED_CCP" and current.get("id"):
        # The options endpoint can leave out the provider the location already uses.
        extra = [*extra, {"label": f"Cloud: {current['name']}", "kind": "CONNECTION", "id": current["id"]}]
    have = {t["id"] for t in out}
    for t in extra:
        if t["id"] not in have:
            out.append(t)
            have.add(t["id"])
    return sorted(out, key=lambda t: t["label"].lower())


def set_connection(c: WebexClient, location_id: str, target: dict[str, str]) -> str:
    """Point the location's PSTN connection at a trunk, route group or cloud connection."""
    if target["kind"] == "CONNECTION":
        body = {"id": target["id"]}
    else:
        body = {"premiseRouteType": target["kind"], "premiseRouteId": target["id"]}
    c.call("PUT", f"/telephony/pstn/locations/{location_id}/connection", body=body)
    return f"Now uses {target['label']}"


# --- Copy location ---

# Webex Calling location settings copied to the new location. Left out on purpose: the main number and charge number
# (numbers are never copied), the routing prefix and the PSTN connection (set those with Migrate PSTN).
_CALLING_KEYS = ("externalCallerIdName", "outsideDialDigit", "enforceOutsideDialDigit", "pAccessNetworkInfo",
                 "useChargeNumberForPChargeInfo")
_ADDRESS_KEYS = ("address1", "address2", "city", "state", "postalCode", "country")


def _probe_core_locations(c: WebexClient, location_id: str) -> None:
    """After a 403 on the core locations API, log which related calls the same token can make (each is logged by the
    client), so the log shows whether the token lacks the core locations API as a whole or only this location."""
    if c.log is None:
        return
    c.log.warning("403 on the core locations API. Probing related calls to narrow it down:")
    for label, path, params in (("core list, this org", "/locations", {"max": 1}),
                                ("telephony details of this location", location_path(location_id), None),
                                ("core people list, this org", "/people", {"max": 1})):
        try:
            c.call("GET", path, params=params)
            c.log.info(f"  probe OK: {label}")
        except WebexError as e:
            c.log.warning(f"  probe failed: {label}: {e}")


def get_location_template(c: WebexClient, location_id: str) -> dict:
    """What a copy starts from: core location fields (`GET /locations/{id}`) plus the calling language."""
    try:
        loc = c.call("GET", f"/locations/{location_id}")
    except WebexError as e:
        if "403" in str(e):
            _probe_core_locations(c, location_id)
        raise
    addr = loc.get("address") or {}
    out = {"timeZone": loc.get("timeZone", ""), "preferredLanguage": loc.get("preferredLanguage", ""),
           "announcementLanguage": loc.get("announcementLanguage", ""),
           "address": {k: addr.get(k, "") for k in _ADDRESS_KEYS}}
    for k in ("latitude", "longitude", "notes"):
        if loc.get(k):
            out[k] = str(loc[k])
    if not out["announcementLanguage"]:
        out["announcementLanguage"] = c.call("GET", location_path(location_id)).get("announcementLanguage", "")
    return out


def _step(label: str, fn, *args, **kw):
    """Run one API step; a WebexError names the step that failed."""
    try:
        return fn(*args, **kw)
    except WebexError as e:
        raise WebexError(f"{label}: {e}") from e


def copy_location(c: WebexClient, source: dict[str, str], name: str, address: dict[str, str] | None = None,
                  calling_settings: bool = True, schedules: bool = True) -> str:
    """Create `name` from the `source` location row and enable it for Webex Calling.

    Steps: read the source, create the location (`POST /locations`, `address` replaces the source address when
    given), enable Webex Calling (`POST /telephony/config/locations`), then optionally copy the calling settings
    and the schedules. A failure in the optional steps is listed in the result and does not fail the copy; a failure
    before the location exists raises WebexError."""
    name = name.strip()
    if not name:
        raise WebexError("Enter the name of the new location.")
    if len(name) > 80:
        raise WebexError("A location enabled for Webex Calling can have at most 80 characters in its name.")
    country = (address or {}).get("country", "").strip().upper()
    if country and country not in COUNTRIES:
        raise WebexError(f'"{country}" is not a 2-letter ISO country code. Pick one from the Country list.')
    if any(r["name"].lower() == name.lower() for r in _step("Listing locations", list_locations, c)):
        raise WebexError(f'A location named "{name}" already exists.')
    tpl = _step("Reading the source location (GET /locations)", get_location_template, c, source["id"])
    if address:
        tpl["address"] = {**tpl["address"], **{k: v.strip() for k, v in {**address, 'country': country}.items() if k in _ADDRESS_KEYS and v.strip()}}
    missing = [k for k in ("address1", "city", "state", "postalCode", "country") if not tpl["address"].get(k)]
    if missing or not (tpl["timeZone"] and tpl["preferredLanguage"] and tpl["announcementLanguage"]):
        raise WebexError("The source location is missing required fields (" + ", ".join(
            missing + [k for k in ("timeZone", "preferredLanguage", "announcementLanguage") if not tpl[k]])
            + "). Fill in the address here or fix the source location.")
    tpl["address"] = {k: v for k, v in tpl["address"].items() if v}
    created = _step("Creating the location (POST /locations)", c.call, "POST", "/locations",
                    body={"name": name, **tpl})
    new_id = created.get("id")
    if not new_id:
        raise WebexError("Webex did not return an id for the new location.")
    calling = {k: tpl[k] for k in ("timeZone", "preferredLanguage", "announcementLanguage", "address")}
    try:
        c.call("POST", "/telephony/config/locations", body={"id": new_id, "name": name, **calling})
    except WebexError as e:
        raise WebexError(f"The location was created but could not be enabled for Webex Calling ({e}). "
                         "Enable it in Control Hub or delete it before trying again.") from e
    notes = ["Created and enabled for Webex Calling"]
    if calling_settings:
        try:
            src = c.call("GET", location_path(source["id"]))
            body = {k: src[k] for k in _CALLING_KEYS if k in src}
            if body:
                c.call("PUT", location_path(new_id), body=body)
            notes.append(f"{len(body)} calling setting(s) copied")
        except WebexError as e:
            notes.append(f"Calling settings not copied: {e}")
    if schedules:
        try:
            copied = 0
            for s in list_schedules(c, source["id"]):
                detail = get_schedule(c, source["id"], s["type"], s["id"])
                copy_schedule_to(c, copy_body(s, detail), s["type"], s["name"], new_id)
                copied += 1
            notes.append(f"{copied} schedule(s) copied")
        except WebexError as e:
            notes.append(f"Schedules not copied: {e}")
    return "; ".join(notes)


def connection_text(conn: dict | None) -> str:
    """Display text for a PSTN connection: "Name (TYPE)", or "Unknown" when it could not be read."""
    if conn is None:
        return "Unknown"
    name, kind = conn.get("displayName", ""), conn.get("pstnConnectionType", "")
    return f"{name} ({kind})" if name and kind else name or kind or "None"


def list_locations_with_pstn(c: WebexClient) -> list[dict[str, str]]:
    """Locations as picker rows with a "pstn" column (one connection read per location, a few at a time)."""
    rows = list_locations(c)

    def one(loc: dict[str, str]) -> str:
        try:
            return connection_text(c.call("GET", f"/telephony/pstn/locations/{loc['id']}/connection"))
        except WebexError:
            return connection_text(None)
    with ThreadPoolExecutor(max_workers=E911_WORKERS) as pool:
        for loc, text in zip(rows, pool.map(one, rows)):
            loc["pstn"] = text
    return rows
