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
    locations = list_locations(c)
    by_id = {r["id"]: r["name"] for r in locations}  # the Calling locations: names for items that only carry an id
    if "location" in types:
        rows += [_named({"id": r["id"]}, r["name"], "location", r["name"], r["id"]) for r in locations]
    for typ, path, key in (("queue", QUEUES, "queues"), ("hunt_group", HUNT_GROUPS, "huntGroups"),
                           ("auto_attendant", AUTO_ATTENDANTS, "autoAttendants")):
        if typ in types:
            rows += [_named(i, i.get("name", ""), typ, i.get("locationName") or by_id.get(i.get("locationId", ""), ""),
                            i.get("locationId", "")) for i in _list(c, path, key)]
    if "workspace" in types:
        for i in _list(c, "/workspaces", "items"):
            calling = (i.get("calling") or {}).get("webexCalling") or {}
            loc_id = i.get("locationId") or calling.get("locationId", "")
            rows.append(_named(i, i.get("displayName", ""), "workspace", by_id.get(loc_id, ""), loc_id))
    if "virtual_line" in types:
        for i in _list(c, VIRTUAL_LINES, "virtualLines"):
            name = i.get("displayName") or f"{i.get('firstName', '')} {i.get('lastName', '')}".strip()
            loc = i.get("location") or {}
            loc_id = loc.get("id") or i.get("locationId", "")
            rows.append(_named(i, name, "virtual_line", loc.get("name") or by_id.get(loc_id, ""), loc_id))
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


# --- Describe a rule in words, get a regex ---

_LITERAL_META = set(".^$*+?{}[]\\|()")
_SEPARATORS = {"dash": "-", "hyphen": "-", "underscore": "_", "space": " "}
_STOP = r"(?=,|;|\.|\band\b|\bthen\b|\bfollowed\b|$)"


def _esc(text: str) -> str:
    return "".join("\\" + ch if ch in _LITERAL_META else ch for ch in text)


def _literal(text: str) -> str:
    text = text.strip().strip("'\"")
    if re.fullmatch(r"(?:the\s+)?(?:item'?s?\s+)?location(?:\s+name)?", text, re.I):
        return "{location}"
    return _esc(text)


_CHARS = {"space": " ", "dash": "-", "hyphen": "-", "underscore": "_", "period": ".", "dot": ".", "slash": "/",
          "comma": ","}
_SEQ_BLOCK = re.compile(r"\b(?:only|no|without|max(?:imum)?|min(?:imum)?|at most|at least|between|starts?|begins?|"
                        r"ends?|contains?|long|length)\b", re.I)


def _sequence_piece(piece: str) -> tuple[str, str] | None:
    """One step of a sequence ('a space', '5 letters', 'the location name', '"HG"') as (regex, note), or None."""
    piece = piece.strip(" .;")
    if not piece:
        return ("", "")
    if re.fullmatch(r"(?:the\s+)?(?:item'?s?\s+)?location(?:\s+name)?", piece, re.I):
        return "{location}", "The location name"
    m = re.fullmatch(r"(?:(\d+)|an?|one)?\s*(" + "|".join(_CHARS) + r")s?", piece, re.I)
    if m:
        name = m.group(2).lower()
        ch, n = _esc(_CHARS[name]), m.group(1)
        return (f"{ch}{{{n}}}" if n and n != "1" else ch), f"{n or 'One'} {name}" + ("s" if n and n != "1" else "")
    m = re.fullmatch(r"['\"](.+)['\"]", piece)
    if m:
        return _esc(m.group(1)), f"Text {m.group(1)}"
    m = re.fullmatch(r"(?:(?:(\d+)\s*(?:to|-)\s*(\d+))|(?:at least (\d+))|(?:(?:up to|max(?:imum)?(?: of)?) (\d+))|(\d+)|"
                     r"(an?|one)|(?:any(?: number of)?|some))?\s*(upper\s?case |lower\s?case |capital )?"
                     r"(letters?|digits?|numbers?|numerals?|alphanumerics?|characters?|chars?|text)", piece, re.I)
    if not m:
        return None
    a, b, atleast, upto, exact, single, case, kind = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6), m.group(7), m.group(8)
    kind, case = kind.lower(), (case or "").lower()
    k = kind.rstrip("s")
    cls = {"letter": "A-Za-z", "digit": "0-9", "number": "0-9", "numeral": "0-9", "alphanumeric": "A-Za-z0-9"}.get(k)
    if cls and case:
        cls = "A-Z" if "upper" in case or "capital" in case else "a-z"
    base = f"[{cls}]" if cls else "."
    if a and b:
        q, words = f"{{{a},{b}}}", f"{a} to {b}"
    elif atleast:
        q, words = f"{{{atleast},}}", f"at least {atleast}"
    elif upto:
        q, words = f"{{0,{upto}}}", f"up to {upto}"
    elif exact:
        q, words = f"{{{exact}}}", exact
    elif single:
        q, words = "", "one"
    else:
        q, words = "+", "one or more"
    label = case.strip() + " " + kind
    return base + q, f"{words} {label.strip()}" + (f" [{cls}]" if cls else "")


def _sequence_regex(text: str) -> tuple[str, list[str]] | None:
    """Ordered description ('location name, then a space, then 5 letters') to a fully anchored regex, or None
    when a step is not understood or the text states rules instead of a sequence."""
    low = text.strip()
    if not low or _SEQ_BLOCK.search(low):
        return None
    low = re.sub(r"\b(letters?)\s+(?:and|or)\s+(?:numbers?|digits?)\b|\b(?:numbers?|digits?)\s+(?:and|or)\s+letters?\b",
                 "alphanumerics", low, flags=re.I)
    steps = re.split(r"\s*(?:,|;|\.\s|\bfollowed by\b|\band then\b|\bthen\b|\band\b|\bplus\b)\s*", low, flags=re.I)
    regex, notes = "", []
    for step in steps:
        step = re.sub(r"^(?:and|finally|next|with|by)\s+", "", step.strip(), flags=re.I)
        got = _sequence_piece(step)
        if got is None:
            return None
        regex += got[0]
        if got[1]:
            notes.append(got[1][0].upper() + got[1][1:])
    return ("^" + regex + "$", notes) if regex else None


def describe_to_regex(text: str) -> tuple[str, list[str]]:
    """Turn a plain-English description of a naming rule into (regex, notes). Understands common phrases only:
    starts/ends with, contains, no spaces, letters/numbers/dashes/underscores only, upper/lower case and length.
    `notes` says how each part was read (and what was not understood), so the result can be checked."""
    seq = _sequence_regex(text)
    if seq:
        return seq
    t = " " + text.strip() + " "
    low = t.lower()
    notes: list[str] = []
    prefix = suffix = ""
    lookaheads: list[str] = []

    m = re.search(r"\b(?:starts?|begins?)\s+with\s+(.+?)" + _STOP, t, re.I)
    if m:
        prefix = _literal(m.group(1))
        sep = re.search(r"followed by (?:a |an )?(dash|hyphen|underscore|space)", low)
        if sep:
            prefix += _esc(_SEPARATORS[sep.group(1)])
        notes.append(f"Starts with {prefix}")
    m = re.search(r"\bends?\s+with\s+(.+?)" + _STOP, t, re.I)
    if m:
        suffix = _literal(m.group(1))
        notes.append(f"Ends with {suffix}")
    for m in re.finditer(r"\bcontains?\s+(.+?)" + _STOP, t, re.I):
        lookaheads.append(f"(?=.*{_literal(m.group(1))})")
        notes.append(f"Contains {_literal(m.group(1))}")

    # judge allowed characters on the text left after the starts/ends/contains clauses are taken out
    low = re.sub(r"\b(?:starts?|begins?|ends?)\s+with\s+.+?" + _STOP, " ", low)
    low = re.sub(r"\bcontains?\s+.+?" + _STOP, " ", low)
    low = re.sub(r"followed by (?:a |an )?\w+", " ", low)
    allowed = ""
    letters = re.search(r"\bletters?\b|\balphabet", low)
    upper = re.search(r"\bupper\s?case|\bcapital", low)
    lower = re.search(r"\blower\s?case", low)
    if letters or upper or lower:
        allowed += "A-Z" if upper and not lower else "a-z" if lower and not upper else "A-Za-z"
    if re.search(r"\b(?:numbers?|digits?|numeric)\b", low):
        allowed += "0-9"
    if re.search(r"\bdash(?:es)?\b|\bhyphens?\b", low) and not re.search(r"no (?:dash|hyphen)", low):
        allowed += "\\-"
    if re.search(r"\bunderscores?\b", low) and not re.search(r"no underscore", low):
        allowed += "_"
    if re.search(r"\bspaces?\b", low) and not re.search(r"no spaces?|without spaces?|not.*spaces?", low):
        allowed += " "
    no_space = bool(re.search(r"no spaces?|without spaces?|not (?:contain|have|allow) spaces?", low))
    if no_space:
        notes.append("No spaces")
    if re.search(r"no special characters?|alphanumeric", low) and not allowed:
        allowed = "A-Za-z0-9"
    if allowed:
        notes.append(f"Allowed characters: [{allowed}]")

    lo, hi = None, None
    m = re.search(r"(?:between\s+)?(\d+)\s*(?:to|-|and)\s*(\d+)\s*(?:characters?|chars?|long|letters?)?", low)
    if m and re.search(r"characters?|chars?|long|length|between", low):
        lo, hi = int(m.group(1)), int(m.group(2))
    else:
        for pat, which in ((r"(?:max(?:imum)?|at most|up to|no more than|under|less than)\D{0,12}(\d+)", "hi"),
                           (r"(?:min(?:imum)?|at least|no fewer than|more than)\D{0,12}(\d+)", "lo"),
                           (r"exactly\s+(\d+)", "both")):
            m = re.search(pat, low)
            if m:
                n = int(m.group(1))
                lo, hi = (n, n) if which == "both" else (lo, n) if which == "hi" else (n, hi)
    if lo is not None or hi is not None:
        lookaheads.append(f"(?=.{{{lo if lo is not None else 0},{hi if hi is not None else ''}}}$)")
        notes.append(f"Length {lo if lo is not None else 0} to {hi if hi is not None else 'any'}")

    body = f"[{allowed}]" if allowed else r"\S" if no_space else "."
    body += "*" if prefix or suffix else "+"
    if not (prefix or suffix or lookaheads or allowed or no_space):
        return "", ["Nothing recognized. Try phrases like: starts with HG-, ends with -CQ, contains Sales, "
                    "letters and numbers only, no spaces, max 30 characters."]
    if no_space and allowed:
        notes.append("Allowed characters already exclude spaces")
    return "^" + "".join(lookaheads) + prefix + body + suffix + "$", notes
