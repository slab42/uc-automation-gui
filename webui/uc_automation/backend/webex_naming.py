"""Webex naming check: validate configured item names against a regex, and rename the ones that fail.

Item types: locations, call queues, hunt groups, auto attendants, workspaces and virtual lines. Each type has its own
regex. `{location}` in a regex stands for the item's own location name (escaped). Renaming sends only the name.
Request shapes come from the Webex docs; not tested against a real org.
"""

import csv
import io
import re

from .webex_api import WebexClient, WebexError
from .webex_groups import HUNT_GROUPS, QUEUES, VIRTUAL_LINES, _list, location_path
from .webex_locations import list_locations

AUTO_ATTENDANTS = "/telephony/config/autoAttendants"

# key -> label (menu order)
TYPES = {
    "location": "Location",
    "queue": "Call Queue",
    "hunt_group": "Hunt Group",
    "auto_attendant": "Auto Attendant",
    "workspace": "Workspace",
    "virtual_line": "Virtual Line",
}

# Longest name Webex accepts (ServiceInstanceProfileName); types not listed have no check here
MAX_LEN = {"queue": 30, "hunt_group": 30, "auto_attendant": 30}


def fits(typ: str, name: str) -> bool:
    return len(name) <= MAX_LEN.get(typ, 10**6)


# Hints shown on the page: (label, regex)
HINTS = [
    ("Letters, digits, dashes only", r"^[A-Za-z0-9-]+$"),
    ("No spaces", r"^\S+$"),
    ("Starts with the location name", r"^{location}[-_ ]"),
    ("Upper case with dashes (SITE-TYPE-NAME)", r"^[A-Z0-9]+(-[A-Z0-9]+){2,}$"),
    ("Ends with a suffix (-CQ)", r"-CQ$"),
    ("Prefix, then anything (HG-)", r"^HG-.+"),
    ("Length 3 to 30", r"^.{3,30}$"),
]
TOKEN_HELP = ("Webex names are matched with Python regex syntax, case sensitive, against the whole name (use ^ and $ "
              "to anchor). {location} is replaced with the item's location name.")


def compile_pattern(text: str) -> str:
    """Validate a rule and return it trimmed ({location} is expanded per item in `matches`). Raises ValueError."""
    text = text.strip()
    if not text:
        return ""
    try:
        re.compile(text.replace("{location}", "x"))
    except re.error as e:
        raise ValueError(f"Invalid regex '{text}': {e}") from e
    return text


def _expand(pattern: str, location: str) -> re.Pattern:
    return re.compile(pattern.replace("{location}", re.escape(location)))


def matches(pattern: str, name: str, location: str) -> bool:
    return _expand(pattern, location).search(name) is not None


_META = set(".*+?()|{}[]\\^$")


def _literal_prefix(pattern: str, location: str) -> str:
    """The fixed text a rule starting with ^ demands ('^HG-.+' gives 'HG-', '^{location}[-_ ]' gives 'LOC-')."""
    if not pattern.startswith("^"):
        return ""
    s, out = pattern[1:], ""
    while s:
        if s.startswith("{location}"):
            out, s = out + location, s[len("{location}"):]
        elif s[0] == "[":
            end = s.find("]", 2)
            cls = s[1:end] if end > 0 else ""
            if cls and cls[0] != "^" and s[end + 1:end + 2] not in ("*", "+", "?", "{"):
                out += cls[0]
            break
        elif s[0] == "\\" and len(s) > 1 and not s[1].isalnum():
            out, s = out + s[1], s[2:]
        elif s[0] in _META or (len(s) > 1 and s[1] in "*+?{"):
            break
        else:
            out, s = out + s[0], s[1:]
    return out


def _literal_suffix(pattern: str) -> str:
    """The fixed text a rule ending with $ demands ('-CQ$' gives '-CQ')."""
    if not pattern.endswith("$") or pattern.endswith("\\$"):
        return ""
    s, out = pattern[:-1], ""
    while s and (s[-1] not in _META or (len(s) > 1 and s[-2] == "\\")):
        if s[-1] in _META:  # escaped literal such as \-
            s = s[:-1]
        out, s = s[-1] + out, s[:-1]
    return out


def _variants(name: str) -> list[str]:
    """Common clean-ups of a name, simplest first."""
    base = re.sub(r"\s+", " ", name).strip()
    out = [base, base.replace(" ", "-"), base.replace(" ", "_"), base.replace(" ", "")]
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]", "", base)
    out += [cleaned, cleaned.replace(" ", "-"), cleaned.replace(" ", "_"), cleaned.replace(" ", "")]
    out += [re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-"), re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")]
    out += [v.upper() for v in list(out)] + [v.lower() for v in list(out)]
    return list(dict.fromkeys(v for v in out if v))


def suggest(pattern: str, name: str, location: str, find: str, replace: str, typ: str = "") -> str:
    """A new name that passes the rule, or "". Tries the optional find/replace first, then automatic fixes:
    clean-ups (spaces, odd characters, case) with the rule's fixed prefix and suffix added. Never a no-op."""
    candidates: list[str] = []
    if find:
        try:
            candidates.append(re.sub(find.replace("{location}", re.escape(location)), replace, name).strip())
        except (re.error, IndexError):
            pass
    prefix, suffix = _literal_prefix(pattern, location), _literal_suffix(pattern)
    for v in _variants(name):
        for pre, suf in ((prefix, suffix), (prefix, ""), ("", suffix), ("", "")):
            c = (pre if pre and not v.startswith(pre) else "") + v + (suf if suf and not v.endswith(suf) else "")
            candidates.append(c)
    for c in candidates:
        if c and c != name and fits(typ, c) and matches(pattern, c, location):
            return c
    return ""


def check_rows(rows: list[dict[str, str]], patterns: dict[str, str], find: str = "", replace: str = "") -> list[dict[str, str]]:
    """One result per row of a type that has a rule: status PASS or FAIL, plus a suggested name when one fits."""
    out = []
    for r in rows:
        pat = patterns.get(r["type"])
        if not pat:
            continue
        ok = matches(pat, r["name"], r["location"])
        new = "" if ok else suggest(pat, r["name"], r["location"], find, replace, r["type"])
        out.append({**r, "key": f"{r['type']}:{r['id']}", "label": TYPES[r["type"]], "status": "PASS" if ok else "FAIL",
                    "reason": "" if ok else f"Does not match {pat}", "suggestion": new, "valid": "1" if new else "",
                    "limit": f"Max {MAX_LEN[r['type']]} characters" if r["type"] in MAX_LEN else "Type a new name"})
    return out


# --- Lists ---

def _named(i: dict, name: str, typ: str, location: str = "", loc_id: str = "") -> dict[str, str]:
    return {"id": i.get("id", ""), "type": typ, "name": name, "location": location, "locationId": loc_id}


def list_items(c: WebexClient, types: list[str]) -> list[dict[str, str]]:
    """Every item of the chosen types, sorted by type then name."""
    rows: list[dict[str, str]] = []
    if "location" in types:
        rows += [_named({"id": r["id"]}, r["name"], "location", r["name"], r["id"]) for r in list_locations(c)]
    for typ, path, key in (("queue", QUEUES, "queues"), ("hunt_group", HUNT_GROUPS, "huntGroups"),
                           ("auto_attendant", AUTO_ATTENDANTS, "autoAttendants")):
        if typ in types:
            rows += [_named(i, i.get("name", ""), typ, i.get("locationName", ""), i.get("locationId", ""))
                     for i in _list(c, path, key)]
    if "workspace" in types:
        rows += [_named(i, i.get("displayName", ""), "workspace", "", "") for i in _list(c, "/workspaces", "items")]
    if "virtual_line" in types:
        for i in _list(c, VIRTUAL_LINES, "virtualLines"):
            name = i.get("displayName") or f"{i.get('firstName', '')} {i.get('lastName', '')}".strip()
            loc = i.get("location") or {}
            rows.append(_named(i, name, "virtual_line", loc.get("name", ""), loc.get("id", "")))
    return sorted(rows, key=lambda r: (list(TYPES).index(r["type"]), r["name"].lower()))


# --- Rename ---

def rename(c: WebexClient, row: dict[str, str], new_name: str) -> str:
    typ, rid, loc = row["type"], row["id"], row["locationId"]
    if typ == "location":
        c.call("PUT", f"/locations/{rid}", body={"name": new_name})
    elif typ == "workspace":
        c.call("PUT", f"/workspaces/{rid}", body={"displayName": new_name})
    elif typ == "virtual_line":
        c.call("PUT", f"{VIRTUAL_LINES}/{rid}", body={"displayName": new_name})
    elif typ in ("queue", "hunt_group", "auto_attendant"):
        if not loc:
            raise WebexError("The item has no location id, so it cannot be renamed.")
        sub = {"queue": "queues", "hunt_group": "huntGroups", "auto_attendant": "autoAttendants"}[typ]
        c.call("PUT", f"{location_path(loc)}/{sub}/{rid}", body={"name": new_name})
    else:
        raise WebexError(f"Cannot rename a {typ}.")
    return f"Renamed to {new_name}"


def results_csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Type", "Name", "Location", "Status", "Reason", "Suggested name"])
    for r in rows:
        w.writerow([r["label"], r["name"], r["location"], r["status"], r["reason"], r["suggestion"]])
    return buf.getvalue()
