"""Webex locations: schedules (export, update from CSV, copy, remove past events) and RedSky E911.

Ported from webex/export_location_holidaySchedule.py, update_location_holidayschedule.py, copy_location_schedule.py,
remove_location_scheduleDatesPast.py, locations_e911_status.py and locations_DisableRedSky.py (reference only).
Not tested against a real org.
"""

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

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
