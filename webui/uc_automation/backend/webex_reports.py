"""Webex reports: Locations Report (Webex Calling users and workspaces per location).

Users come from GET /people?callingData=true (a person with a Calling location id is Calling enabled), workspaces
from GET /workspaces?calling=webexCalling. Not tested against a real org.
"""

import base64
import csv
import io

from .webex_api import WebexClient
from .webex_locations import list_locations

PEOPLE_PAGE = 100
WORKSPACE_PAGE = 100
UNKNOWN = "(No Location Match)"


def _key(location_id: str) -> str:
    """Location id in a comparable form: the Calling and core APIs can encode the same location differently, so
    compare the last segment of the decoded id."""
    try:
        padded = location_id + "=" * (-len(location_id) % 4)
        return base64.urlsafe_b64decode(padded).decode().rsplit("/", 1)[-1].lower()
    except ValueError:
        return location_id.lower()


def _calling_people(c: WebexClient) -> list[dict]:
    people = c.list_all("/people", "items", {"callingData": "true", "max": PEOPLE_PAGE, "excludeStatus": "true"})
    return [p for p in people if p.get("locationId")]


def _calling_workspaces(c: WebexClient) -> list[dict]:
    items: list[dict] = []
    start = 0
    while True:
        page = c.call("GET", "/workspaces", {"calling": "webexCalling", "max": WORKSPACE_PAGE,
                                              "start": start}).get("items") or []
        items.extend(page)
        if len(page) < WORKSPACE_PAGE:
            return items
        start += WORKSPACE_PAGE


def locations_report(c: WebexClient, users: bool = True, workspaces: bool = True,
                     progress=lambda text: None) -> list[dict]:
    """One row per location: Calling users, Calling workspaces and their total. Locations with nothing are kept.
    People and workspaces that match no location are counted in a final row."""
    locations = list_locations(c)
    people, spaces = [], []
    if users:
        progress("Reading users")
        people = _calling_people(c)
    if workspaces:
        progress("Reading workspaces")
        spaces = _calling_workspaces(c)
    rows = {_key(l["id"]): {"name": l["name"], "users": 0, "workspaces": 0} for l in locations}
    other = {"name": UNKNOWN, "users": 0, "workspaces": 0}
    for items, field in ((people, "users"), (spaces, "workspaces")):
        for i in items:
            rows.get(_key(i.get("locationId") or i.get("workspaceLocationId") or ""), other)[field] += 1
    out = sorted(rows.values(), key=lambda r: r["name"].lower())
    if other["users"] or other["workspaces"]:
        out.append(other)
    return [{**r, "total": r["users"] + r["workspaces"]} for r in out]


def report_csv(rows: list[dict], users: bool = True, workspaces: bool = True) -> str:
    """Columns follow what the report covered; Total is shown only when both were."""
    cols = ([("Calling Users", "users")] if users else []) + ([("Calling Workspaces", "workspaces")] if workspaces else [])
    if users and workspaces:
        cols.append(("Total", "total"))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Location"] + [h for h, _ in cols])
    for r in rows:
        w.writerow([r["name"]] + [r[k] for _, k in cols])
    w.writerow(["Total"] + [sum(r[k] for r in rows) for _, k in cols])
    return buf.getvalue()
