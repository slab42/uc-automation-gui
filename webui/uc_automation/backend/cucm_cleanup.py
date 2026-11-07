"""Cutover Cleanup (CUCM): remove the devices and DNs left behind by a Webex cutover, then the objects they leave
unused.

Delete Devices removes phones and then their orphan DNs (modelled on phones_delete.py and ctiRP_delete.py). The
hunt group step finds line groups that hold any of the DNs. The Remediate steps list objects with no references
(the *_remediate.py scripts) so the user can tick the ones to delete. Reuses `cucm_dn`, `cucm_hunt`,
`cucm_devices`, `cucm_routing` and `cucm_system`.
"""

import re
from concurrent.futures import ThreadPoolExecutor

from .cucm_axl import AxlError, list_paged, sql_quote, sql_rows, _call, _text
from .cucm_connections import CucmConnection
from .cucm_cutover import label as dn_label, parse_dn_list
from .cucm_devices import (find_button_template_usage, format_phone_identifier, list_phone_button_templates,
                           remove_common_device_config, remove_phone, remove_phone_button_template,
                           remove_softkey_template)
from .cucm_hunt import _hunt_lists_using_line_group
from .cucm_routing import (find_pickup_group_usage, list_pickup_groups, remove_css, remove_partition,
                           remove_pickup_group)
from .cucm_system import remove_device_pool

_HEADERS = ("name", "device", "devicename", "device name", "mac")


def parse_dns(text: str) -> list[dict[str, str]]:
    """Rows {dn, partition}. A blank partition matches the DN in any partition."""
    return parse_dn_list(text, "")


def parse_devices(text: str) -> list[str]:
    """Device names from pasted text or CSV text: separated by lines, commas, tabs, semicolons or pipes. A MAC
    address becomes SEP<MAC>. A header cell (name, device) is skipped, repeats are kept once."""
    out: list[str] = []
    for i, cell in enumerate(c for c in re.split(r"[\s,;|]+", text) if c):
        if i == 0 and cell.lower() in _HEADERS:
            continue
        name = format_phone_identifier(cell)
        if name not in out:
            out.append(name)
    return out


def matches(rows: list[dict[str, str]], pattern: str, partition: str) -> bool:
    """True when the DN (pattern, partition) is in the list (a list row without a partition matches any)."""
    return any(r["dn"] == pattern and (not r["partition"] or r["partition"] == partition) for r in rows)


# --- 1. devices and orphan DNs ---

def _dn_rows(conn: CucmConnection, pattern: str, partition: str) -> list[dict]:
    """[{pattern, partition, devices}] for the device DNs with this pattern (any partition when blank).
    `devices` are the devices, device profiles and remote destination profiles still using the DN."""
    where = f" AND rp.name = '{sql_quote(partition)}'" if partition else ""
    rows = sql_rows(conn, f"""
        SELECT n.dnorpattern AS pattern, NVL(rp.name, '') AS partition, NVL(d.name, '') AS device
        FROM numplan n
        LEFT JOIN routepartition rp ON rp.pkid = n.fkroutepartition
        LEFT JOIN devicenumplanmap m ON m.fknumplan = n.pkid
        LEFT JOIN device d ON d.pkid = m.fkdevice
        WHERE n.tkpatternusage = 2 AND n.dnorpattern = '{sql_quote(pattern)}'{where}
        """, 3)
    found: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        devices = found.setdefault((r.get("pattern", ""), r.get("partition", "")), [])
        if r.get("device"):
            devices.append(r["device"])
    return [{"pattern": p, "partition": part, "devices": d} for (p, part), d in found.items()]


def _remove_if_orphan(conn: CucmConnection, pattern: str, partition: str) -> list[str]:
    """Remove the DN when no device uses it. Returns notes, one per DN found."""
    notes = []
    for dn in _dn_rows(conn, pattern, partition):
        name = dn_label({"dn": dn["pattern"], "partition": dn["partition"]})
        if dn["devices"]:
            notes.append(f"DN {name} kept: still on {', '.join(dn['devices'][:3])}")
            continue
        ref = {"pattern": dn["pattern"], **({"routePartitionName": dn["partition"]} if dn["partition"] else {})}
        try:
            _call(conn, "removeLine", **ref)
            notes.append(f"DN {name} removed")
        except AxlError as e:
            notes.append(f"DN {name} kept: {e}")
    return notes


def _phone_lines(conn: CucmConnection, name: str) -> list[tuple[str, str]]:
    resp = _call(conn, "getPhone", name=name, returnedTags={
        "lines": {"line": {"dirn": {"pattern": "", "routePartitionName": ""}}}})
    lines = resp["return"]["phone"].lines
    items = (lines.line if lines is not None else None) or []
    if not isinstance(items, list):
        items = [items]
    return [(ln.dirn.pattern, _text(ln.dirn.routePartitionName)) for ln in items
            if getattr(ln, "dirn", None) is not None and ln.dirn.pattern]


def remove_device(conn: CucmConnection, name: str) -> str:
    """Remove the phone, then each of its DNs that no device uses any more."""
    lines = _phone_lines(conn, name)
    remove_phone(conn, name)
    if not lines:
        return "Removed (no directory numbers)"
    notes: list[str] = []
    for pattern, partition in lines:
        try:
            notes.extend(_remove_if_orphan(conn, pattern, partition) or [f"DN {pattern} not found"])
        except AxlError as e:
            notes.append(f"DN {pattern} kept: {e}")
    return "Removed. " + "; ".join(notes)


def remove_listed_dn(conn: CucmConnection, row: dict[str, str]) -> str:
    """A DN from the list: removed when no device uses it (it may already be gone with its device)."""
    notes = _remove_if_orphan(conn, row["dn"], row["partition"])
    return "; ".join(notes) if notes else "Not found (already removed)"


# --- 2. hunt groups ---

def _line_group_members(conn: CucmConnection, name: str) -> list[tuple[str, str]]:
    resp = _call(conn, "getLineGroup", name=name, returnedTags={
        "members": {"member": {"directoryNumber": {"pattern": "", "routePartitionName": ""}}}})
    members = resp["return"]["lineGroup"].members
    items = (members.member if members is not None else None) or []
    if not isinstance(items, list):
        items = [items]
    return [(m.directoryNumber.pattern, _text(m.directoryNumber.routePartitionName)) for m in items
            if getattr(m, "directoryNumber", None) is not None and m.directoryNumber.pattern]


def find_line_groups(conn: CucmConnection, dns: list[dict[str, str]]) -> list[dict[str, str]]:
    """Line groups with any of the DNs as a member: {name, matched, members, hunt_lists}."""
    names = [r["name"] for r in list_paged(conn, "listLineGroup", "lineGroup", {"name": "%"}, ["name"])]

    def look(name: str) -> dict[str, str] | None:
        members = _line_group_members(conn, name)
        hit = [(p, part) for p, part in members if matches(dns, p, part)]
        if not hit:
            return None
        try:
            lists = ", ".join(_hunt_lists_using_line_group(conn, name))
        except AxlError:
            lists = "(not checked)"
        return {"name": name, "matched": "; ".join(dn_label({"dn": p, "partition": part}) for p, part in hit),
                "members": str(len(members)), "hunt_lists": lists or "None"}

    with ThreadPoolExecutor(4) as pool:
        found = [r for r in pool.map(look, names) if r]
    return sorted(found, key=lambda r: r["name"].lower())


def remove_dns_from_line_group(conn: CucmConnection, name: str, dns: list[dict[str, str]]) -> str:
    members = _line_group_members(conn, name)
    hit = [(p, part) for p, part in members if matches(dns, p, part)]
    if not hit:
        return "None of the DNs are members any more"
    if len(hit) == len(members):
        raise AxlError("Every member is in the list, so the line group would be empty. Delete the line group instead.")
    body = [{"directoryNumber": {"pattern": p, **({"routePartitionName": part} if part else {})}} for p, part in hit]
    _call(conn, "updateLineGroup", name=name, removeMembers={"member": body})
    return f"Removed {len(hit)} DN(s): " + "; ".join(dn_label({"dn": p, "partition": part}) for p, part in hit)


def remove_line_group(conn: CucmConnection, name: str) -> str:
    used = _hunt_lists_using_line_group(conn, name)
    if used:
        raise AxlError(f"Still in hunt list {', '.join(used[:3])}. Remove it from the hunt list first.")
    _call(conn, "removeLineGroup", name=name)
    return "Removed"


# --- 3 to 9. unused objects ---

# kind: (title, noun, foreign key column prefix, table) for the kinds found by foreign keys in the database
_FK_KINDS = {
    "cdc": ("Common Device Configurations", "common device configuration", "fkcommondeviceconfig",
            "commondeviceconfig"),
    "softkey": ("Softkey Templates", "softkey template", "fksoftkeytemplate", "softkeytemplate"),
    "partition": ("Partitions", "partition", "fkroutepartition", "routepartition"),
    "devpool": ("Device Pools", "device pool", "fkdevicepool", "devicepool"),
    "css": ("Calling Search Spaces", "calling search space", "fkcallingsearchspace", "callingsearchspace"),
}
TITLES = {"pickup": "Call Pickup Groups", "pbt": "Phone Button Templates",
          **{k: v[0] for k, v in _FK_KINDS.items()}}
NOUNS = {"pickup": "call pickup group", "pbt": "phone button template",
         **{k: v[1] for k, v in _FK_KINDS.items()}}
REMOVERS = {"pickup": remove_pickup_group, "pbt": remove_phone_button_template, "devpool": remove_device_pool,
            "cdc": remove_common_device_config, "softkey": remove_softkey_template, "partition": remove_partition,
            "css": remove_css}
NEEDS_SEARCH = {"devpool"}
HIDE_IN_USE = {"pickup", "pbt"}  # kinds whose list shows only Unused and Unconfirmed rows

_OWN_TABLES = {"softkeyset"}
_DATA_TABLES = ("cdr_", "cmr_")  # CDR and call record tables hold no configuration and are not readable
_IDENT = re.compile(r"^\w+$")
_MISSING = re.compile(r"column|table|syntax|not found|does not exist|unknown", re.I)


def _fk_usage(conn: CucmConnection, table: str, fk_prefix: str, names: dict[str, str]) -> tuple[dict, list[str]]:
    """({object name: ["<table>: <n>", ...]}, warnings) from every table with a column starting `fk_prefix`.
    `names` maps the object pkids to their names."""
    usage: dict[str, list[str]] = {n: [] for n in names.values()}
    warnings: list[str] = []
    cols = sql_rows(conn, f"""
        SELECT TRIM(t.tabname) AS tab, TRIM(c.colname) AS col
        FROM systables t INNER JOIN syscolumns c ON c.tabid = t.tabid
        WHERE t.tabtype = 'T' AND c.colname LIKE '{fk_prefix}%'
        """, 2)
    for c in cols:
        tab, col = c.get("tab", ""), c.get("col", "")
        # the object's own detail tables (a template's softkeyset rows) are not users of it
        if tab.startswith(table) or tab.startswith(_DATA_TABLES) or tab in _OWN_TABLES or not (_IDENT.match(tab) and _IDENT.match(col)):
            continue
        try:
            refs = sql_rows(conn, f"SELECT {col} AS ref, COUNT(*) AS n FROM {tab} WHERE {col} IS NOT NULL "
                                  f"GROUP BY {col}", 2)
        except AxlError as e:
            if not _MISSING.search(str(e)):
                warnings.append(f"{tab}.{col} could not be checked: {e}")
            continue
        for r in refs:
            if r.get("ref") in names:
                usage[names[r["ref"]]].append(f"{tab}: {r.get('n', '')}")
    return usage, warnings


def _status_rows(names: list[str], usage: dict[str, list[str]], warnings: list[str]) -> list[dict[str, str]]:
    rows = []
    for n in names:
        refs = usage.get(n, [])
        if refs:
            shown = "; ".join(refs[:6]) + (f"; and {len(refs) - 6} more" if len(refs) > 6 else "")
            rows.append({"name": n, "status": "In use", "count": str(len(refs)), "detail": shown})
        else:
            rows.append({"name": n, "status": "Unconfirmed" if warnings else "Unused", "count": "0",
                         "detail": "See warnings" if warnings else "No references found"})
    return rows


def scan_unused(conn: CucmConnection, kind: str, search: str) -> tuple[list[dict[str, str]], list[str]]:
    """Objects of `kind` whose name contains `search` (blank = all) with their status: Unused, In use or
    Unconfirmed (a check failed). Returns (rows, warnings)."""
    needle = search.strip().lower()
    if kind == "pickup":
        names = [r["name"] for r in list_pickup_groups(conn)]
        pick = lambda ns: find_pickup_group_usage(conn, ns)
    elif kind == "pbt":
        names = [r["name"] for r in list_phone_button_templates(conn)]
        pick = lambda ns: find_button_template_usage(conn, ns)
    else:
        _title, _noun, prefix, table = _FK_KINDS[kind]
        pairs = sql_rows(conn, f"SELECT pkid, name FROM {table} ORDER BY name", 2)
        by_pkid = {p["pkid"]: p["name"] for p in pairs if p.get("pkid") and p.get("name")}
        names = list(by_pkid.values())
        pick = None
    names = sorted((n for n in names if needle in n.lower()), key=str.lower)
    if not names:
        return [], []
    if pick is not None:
        usage, warnings = pick(names)
    else:
        wanted = {pk: n for pk, n in by_pkid.items() if n in set(names)}
        usage, warnings = _fk_usage(conn, table, prefix, wanted)
    rows = _status_rows(names, usage, warnings)
    if kind in HIDE_IN_USE:
        rows = [r for r in rows if r["status"] != "In use"]
    return rows, warnings


def remove_unused(conn: CucmConnection, kind: str, name: str) -> str:
    REMOVERS[kind](conn, name)
    return "Removed"
