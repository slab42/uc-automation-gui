"""Webex gateway dial plans: create a dial plan, add dial patterns to an existing one.

Dial plans route calls to premises destinations through a trunk or route group (Calling API
/telephony/config/premisePstn/dialPlans). Request shapes follow webui/reference/webex-cloud-calling.json
and have not been run against a real org.
"""

import csv
import io

from .webex_api import WebexClient, WebexError
from .webex_groups import _list

PLANS = "/telephony/config/premisePstn/dialPlans"
PATTERN_BATCH = 50  # patterns per PUT
ROUTE_LABELS = {"TRUNK": "Trunk", "ROUTE_GROUP": "Route Group"}


def route_text(route_type: str, name: str) -> str:
    return f"{ROUTE_LABELS.get(route_type, route_type)}: {name}" if name else ""


def list_dial_plans(c: WebexClient) -> list[dict[str, str]]:
    """Rows for the picker: id, name and the route as text (key "location", which the picker shows)."""
    rows = [{"id": p["id"], "name": p.get("name", ""),
             "location": route_text(p.get("routeType", ""), p.get("routeName", ""))}
            for p in _list(c, PLANS, "dialPlans")]
    return sorted(rows, key=lambda r: r["name"].lower())


def list_routes(c: WebexClient) -> list[dict[str, str]]:
    """Trunks and route groups a dial plan can use: {"label", "kind", "id"}, kind TRUNK or ROUTE_GROUP."""
    out = [{"label": route_text("TRUNK", t.get("name", "")), "kind": "TRUNK", "id": t["id"]}
           for t in _list(c, "/telephony/config/premisePstn/trunks", "trunks")]
    out += [{"label": route_text("ROUTE_GROUP", g.get("name", "")), "kind": "ROUTE_GROUP", "id": g["id"]}
            for g in _list(c, "/telephony/config/premisePstn/routeGroups", "routeGroups")]
    return sorted(out, key=lambda t: t["label"].lower())


def parse_patterns_csv(data: bytes) -> list[str]:
    """First column after a header row, de-duplicated in order."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    if not rows:
        raise ValueError("The CSV file is empty.")
    patterns = list(dict.fromkeys(r[0].strip() for r in rows[1:] if r and r[0].strip()))
    if not patterns:
        raise ValueError("No dial patterns found. Put one pattern per row under a header row.")
    return patterns


def list_patterns(c: WebexClient, plan_id: str) -> list[str]:
    return sorted(_list(c, f"{PLANS}/{plan_id}/dialPatterns", "dialPatterns"))


def create_dial_plan(c: WebexClient, name: str, route: dict[str, str], patterns: list[str]) -> str:
    if not name.strip():
        raise WebexError("Enter a dial plan name.")
    c.call("POST", PLANS, body={"name": name.strip(), "routeId": route["id"], "routeType": route["kind"],
                                "dialPatterns": patterns})
    return f"Created with {len(patterns)} dial pattern(s) on {route['label']}"


def add_patterns(c: WebexClient, plan_id: str, patterns: list[str]) -> str:
    """Add patterns the plan does not have yet (Webex rejects duplicates)."""
    have = set(list_patterns(c, plan_id))
    new = [p for p in patterns if p not in have]
    for i in range(0, len(new), PATTERN_BATCH):
        body = {"dialPatterns": [{"dialPattern": p, "action": "ADD"} for p in new[i:i + PATTERN_BATCH]]}
        c.call("PUT", f"{PLANS}/{plan_id}/dialPatterns", body=body)
    skipped = len(patterns) - len(new)
    return f"Added {len(new)} dial pattern(s)" + (f", {skipped} already on the plan" if skipped else "")


def delete_patterns(c: WebexClient, plan_id: str, patterns: list[str]) -> str:
    """Remove the given dial patterns from the plan."""
    for i in range(0, len(patterns), PATTERN_BATCH):
        body = {"dialPatterns": [{"dialPattern": p, "action": "DELETE"} for p in patterns[i:i + PATTERN_BATCH]]}
        c.call("PUT", f"{PLANS}/{plan_id}/dialPatterns", body=body)
    return f"Deleted {len(patterns)} dial pattern(s)"
