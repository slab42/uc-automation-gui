"""Cutover Cleanup (CUCM): remove the devices and DNs left behind by a Webex cutover, then the objects they leave
unused.

The hunt group step runs first, while the DNs still exist: it finds the hunt pilots, hunt lists and line groups that
use any of the DNs. Delete Devices removes phones and then their orphan DNs (modelled on phones_delete.py and
ctiRP_delete.py). The Remediate steps list objects with no references
(the *_remediate.py scripts) so the user can tick the ones to delete. Reuses `cucm_dn`, `cucm_hunt`,
`cucm_devices`, `cucm_routing` and `cucm_system`.
"""

import re
from concurrent.futures import ThreadPoolExecutor

from .cucm_axl import AxlError, list_paged, sql_quote, sql_rows, _call, _text
from .cucm_connections import CucmConnection
from .cucm_cutover import dn_key, label as dn_label, parse_dn_list
from .cucm_devices import (find_button_template_usage, format_phone_identifier, list_phone_button_templates,
                           remove_common_device_config, remove_phone, remove_phone_button_template,
                           remove_softkey_template)
from .cucm_hunt import (_hunt_list_line_groups, _hunt_lists_using_line_group, _pilots_on_hunt_list,
                        list_hunt_pilots)
from .keys import split_key
from .cucm_routing import (find_pickup_group_usage, list_pickup_groups, remove_css, remove_partition,
                           remove_pickup_group)
from .cucm_system import remove_device_pool

_HEADERS = ("name", "device", "devicename", "device name", "mac")


def parse_dns(text: str, prefix: str = "", length: str = "") -> list[dict[str, str]]:
    """Rows {dn, partition}. A blank partition matches the DN in any partition. `length` and `prefix` work as in
    Webex Cutover (keep that many characters from the right, then put the prefix in front)."""
    return parse_dn_list(text, "", prefix, length)


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
    return any(dn_key(r["dn"]) == pattern and (not r["partition"] or r["partition"] == partition) for r in rows)


# --- 2. devices and orphan DNs ---

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
    """A DN from the list (a + DN is looked up as \\+...): removed when no device uses it (it may already be gone with its device)."""
    notes = _remove_if_orphan(conn, dn_key(row["dn"]), row["partition"])
    return "; ".join(notes) if notes else "Not found (already removed)"


# --- 1. hunt groups (searched first, while the DNs still exist) ---

def _line_group_members(conn: CucmConnection, name: str) -> list[tuple[str, str]]:
    resp = _call(conn, "getLineGroup", name=name, returnedTags={
        "members": {"member": {"directoryNumber": {"pattern": "", "routePartitionName": ""}}}})
    members = resp["return"]["lineGroup"].members
    items = (members.member if members is not None else None) or []
    if not isinstance(items, list):
        items = [items]
    return [(m.directoryNumber.pattern, _text(m.directoryNumber.routePartitionName)) for m in items
            if getattr(m, "directoryNumber", None) is not None and m.directoryNumber.pattern]


def _split_members(members: list[tuple[str, str]], dns: list[dict[str, str]]):
    hit = [m for m in members if matches(dns, *m)]
    return hit, [m for m in members if not matches(dns, *m)]


def _labels(members: list[tuple[str, str]]) -> str:
    return "; ".join(dn_label({"dn": p, "partition": part}) for p, part in members)


def _pilot_ref(pattern: str, partition: str) -> dict[str, str]:
    return {"pattern": pattern, **({"routePartitionName": partition} if partition else {})}


def _hunt_list_blockers(conn: CucmConnection, name: str, dns: list[dict[str, str]]) -> list[str]:
    """Why a hunt list must not be deleted: pilots that are not in the list, line groups holding other numbers."""
    why = []
    listed = {dn_key(r["dn"]) for r in dns}
    other_pilots = [p for p in _pilots_on_hunt_list(conn, name) if p and p not in listed]
    if other_pilots:
        why.append(f"used by pilot {', '.join(other_pilots[:3])}")
    for lg in _hunt_list_line_groups(conn, name):
        _, others = _split_members(_line_group_members(conn, lg), dns)
        if others:
            why.append(f"line group {lg} holds other numbers")
    return why


def find_hunt_objects(conn: CucmConnection, dns: list[dict[str, str]]) -> list[dict[str, str]]:
    """Hunt pilots, hunt lists and line groups that use any of the DNs, found before the DNs are deleted.

    Rows {key, kind, name, matched, others, related, deletable ("1"/"0"), reason}. A line group that also holds
    numbers outside the list, and a hunt list that depends on one (or on a pilot outside the list), is not deletable.
    """
    kind_order = {"Hunt Pilot": 0, "Hunt List": 1, "Line Group": 2}
    rows: list[dict[str, str]] = []
    hunt_lists: set[str] = set()

    for p in list_hunt_pilots(conn):
        if matches(dns, p["pattern"], p["routePartitionName"]):
            label = dn_label({"dn": p["pattern"].lstrip("\\"), "partition": p["routePartitionName"]})
            rows.append({"key": f"Hunt Pilot:{p['pattern']}|{p['routePartitionName']}", "kind": "Hunt Pilot",
                         "name": label, "matched": label, "others": "", "related": p["huntListName"] or "None",
                         "deletable": "1", "reason": ""})
            if p["huntListName"]:
                hunt_lists.add(p["huntListName"])

    names = [r["name"] for r in list_paged(conn, "listLineGroup", "lineGroup", {"name": "%"}, ["name"])]

    def look(name: str) -> dict[str, str] | None:
        hit, others = _split_members(_line_group_members(conn, name), dns)
        if not hit:
            return None
        try:
            lists = _hunt_lists_using_line_group(conn, name)
        except AxlError:
            lists = []
        return {"key": f"Line Group:{name}", "kind": "Line Group", "name": name, "matched": _labels(hit),
                "others": _labels(others), "related": ", ".join(lists) or "None",
                "deletable": "0" if others else "1",
                "reason": "Also holds numbers that are not in the list" if others else "", "_lists": lists}

    with ThreadPoolExecutor(4) as pool:
        groups = [r for r in pool.map(look, names) if r]
    for g in groups:
        hunt_lists.update(g.pop("_lists"))
    rows.extend(groups)

    for hl in sorted(hunt_lists):
        try:
            why = _hunt_list_blockers(conn, hl, dns)
            pilots = ", ".join(_pilots_on_hunt_list(conn, hl)) or "None"
        except AxlError as e:
            why, pilots = [f"could not be checked: {e}"], "(not checked)"
        rows.append({"key": f"Hunt List:{hl}", "kind": "Hunt List", "name": hl, "matched": "", "others": "",
                     "related": f"Pilots: {pilots}", "deletable": "0" if why else "1", "reason": "; ".join(why)})
    return sorted(rows, key=lambda r: (kind_order[r["kind"]], r["name"].lower()))


def remove_dns_from_line_group(conn: CucmConnection, name: str, dns: list[dict[str, str]]) -> str:
    hit, others = _split_members(_line_group_members(conn, name), dns)
    if not hit:
        return "None of the DNs are members any more"
    if not others:
        raise AxlError("Every member is in the list, so the line group would be empty. Delete the line group instead.")
    body = [{"directoryNumber": {"pattern": p, **({"routePartitionName": part} if part else {})}} for p, part in hit]
    _call(conn, "updateLineGroup", name=name, removeMembers={"member": body})
    return f"Removed {len(hit)} DN(s): " + _labels(hit)


def remove_hunt_object(conn: CucmConnection, key: str, dns: list[dict[str, str]]) -> str:
    """Delete one row from find_hunt_objects. The checks are repeated now, so nothing outside the list is lost."""
    kind, _, ref = key.partition(":")
    if kind == "Hunt Pilot":
        pattern, partition = split_key(ref)
        if not matches(dns, pattern, partition):
            raise AxlError("Not one of the DNs in the list")
        _call(conn, "removeHuntPilot", **_pilot_ref(pattern, partition))
        return "Removed"
    if kind == "Hunt List":
        why = _hunt_list_blockers(conn, ref, dns)
        if why:
            raise AxlError("Not deleted: " + "; ".join(why))
        _call(conn, "removeHuntList", name=ref)
        return "Removed"
    if kind == "Line Group":
        _, others = _split_members(_line_group_members(conn, ref), dns)
        if others:
            raise AxlError(f"Not deleted: it also holds {_labels(others)}")
        used = _hunt_lists_using_line_group(conn, ref)
        if used:
            raise AxlError(f"Still in hunt list {', '.join(used[:3])}. Delete the hunt list first.")
        _call(conn, "removeLineGroup", name=ref)
        return "Removed"
    raise AxlError(f"Unknown hunt object: {key}")


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
