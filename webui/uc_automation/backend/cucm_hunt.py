"""AXL operations for Hunt Groups: hunt pilots and the hunt lists / line groups behind them.

Modelled on cucm/huntgroups_remediate.py. A hunt pilot points at a hunt list, which holds line groups,
which hold directory numbers. Deleting a pilot also cleans up the hunt list and line groups that nothing
else uses any more (the script deletes line groups -> hunt lists -> hunt pilots).
"""

from .cucm_axl import AxlError, list_paged, sql_quote, sql_rows, _call, _text
from .cucm_connections import CucmConnection
from .keys import split_key

HUNT_PILOT_FIELDS = ["pattern", "routePartitionName", "description", "huntListName"]


def _pilot_ref(pattern: str, partition: str) -> dict[str, str]:
    ref = {"pattern": pattern}
    if partition:
        ref["routePartitionName"] = partition
    return ref


def list_hunt_pilots(conn: CucmConnection) -> list[dict[str, str]]:
    rows = list_paged(conn, "listHuntPilot", "huntPilot", {"pattern": "%"}, HUNT_PILOT_FIELDS)
    return sorted(rows, key=lambda r: (r["pattern"], r["routePartitionName"]))


def _clean(row: dict[str, str]) -> dict[str, str]:
    r = {f: (row.get(f) or "").strip() for f in HUNT_PILOT_FIELDS}
    if not r["pattern"]:
        raise AxlError("pattern is required")
    return r


def add_hunt_pilot(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row)
    if not r["huntListName"]:
        raise AxlError("huntListName is required")
    body = {k: v for k, v in r.items() if v}
    body["blockEnable"] = False
    body["useCallingPartyPhoneMask"] = "Default"
    _call(conn, "addHuntPilot", huntPilot=body)


def update_hunt_pilot(conn: CucmConnection, row: dict[str, str]) -> None:
    """Blank cells leave a field unchanged. The pattern and partition identify the pilot."""
    r = _clean(row)
    body = {k: r[k] for k in ("description", "huntListName") if r[k]}
    if not body:
        raise AxlError("nothing to change")
    _call(conn, "updateHuntPilot", **_pilot_ref(r["pattern"], r["routePartitionName"]), **body)


# --- reading the chain: pilot -> hunt list -> line groups ---

def _pilot_hunt_list(conn: CucmConnection, pattern: str, partition: str) -> str:
    resp = _call(conn, "getHuntPilot", **_pilot_ref(pattern, partition), returnedTags={"huntListName": ""})
    return _text(resp["return"]["huntPilot"].huntListName)


def _hunt_list_line_groups(conn: CucmConnection, hunt_list: str) -> list[str]:
    resp = _call(conn, "getHuntList", name=hunt_list,
                 returnedTags={"members": {"member": {"lineGroupName": "", "selectionOrder": ""}}})
    members = resp["return"]["huntList"].members
    items = (members.member if members is not None else None) or []
    if not isinstance(items, list):
        items = [items]
    return [n for n in (_text(m.lineGroupName) for m in items) if n]


def _line_group_member_count(conn: CucmConnection, name: str) -> int:
    resp = _call(conn, "getLineGroup", name=name,
                 returnedTags={"name": "", "members": {"member": {"lineSelectionOrder": ""}}})
    members = resp["return"]["lineGroup"].members
    items = (members.member if members is not None else None) or []
    return len(items) if isinstance(items, list) else 1


def _pilots_on_hunt_list(conn: CucmConnection, hunt_list: str) -> list[str]:
    rows = sql_rows(conn, f"""
        SELECT DISTINCT np.pkid AS pkid, np.dnorpattern AS name
        FROM numplan np
        JOIN devicenumplanmap dnpm ON dnpm.fknumplan = np.pkid
        JOIN device d ON dnpm.fkdevice = d.pkid
        WHERE d.name = '{sql_quote(hunt_list)}' AND np.tkpatternusage = 7
        """, 2)
    return [r.get("name", "") for r in rows]


def _hunt_lists_using_line_group(conn: CucmConnection, line_group: str) -> list[str]:
    rows = sql_rows(conn, f"""
        SELECT DISTINCT rl.pkid AS pkid, d.name AS name
        FROM routelist rl
        JOIN device d ON rl.fkdevice = d.pkid
        JOIN linegroup lg ON rl.fklinegroup = lg.pkid
        WHERE lg.name = '{sql_quote(line_group)}'
        """, 2)
    return [r.get("name", "") for r in rows]


def find_hunt_pilot_usage(conn: CucmConnection, keys: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Return ({pilot key: ["Line group: LG-Sales (3 members)", ...]}, warnings).

    Only line groups that still have members count as references. A pilot whose hunt list is missing or
    holds only empty line groups comes back with no references (the script's "unused" case).
    """
    usage: dict[str, list[str]] = {k: [] for k in keys}
    warnings: list[str] = []
    for key in keys:
        pattern, partition = split_key(key)
        try:
            hunt_list = _pilot_hunt_list(conn, pattern, partition)
            if not hunt_list:
                continue
            for lg in _hunt_list_line_groups(conn, hunt_list):
                count = _line_group_member_count(conn, lg)
                if count:
                    usage[key].append(f"Line group: {lg} ({count} member{'s' if count != 1 else ''})")
        except AxlError as e:
            warnings.append(f"{pattern}: could not be checked: {e}")
    return usage, warnings


def remove_hunt_pilot(conn: CucmConnection, key: str) -> str:
    """Remove the pilot, then its hunt list and line groups if nothing else uses them. Returns a detail."""
    pattern, partition = split_key(key)
    hunt_list = _pilot_hunt_list(conn, pattern, partition)
    line_groups: list[str] = []
    if hunt_list:
        try:
            line_groups = _hunt_list_line_groups(conn, hunt_list)
        except AxlError:
            line_groups = []
    _call(conn, "removeHuntPilot", **_pilot_ref(pattern, partition))
    if not hunt_list:
        return "Removed (no hunt list)"
    notes = ["Removed"]
    try:
        others = [p for p in _pilots_on_hunt_list(conn, hunt_list) if p]
    except AxlError as e:
        return f"Removed. Hunt list {hunt_list} kept: could not check its other pilots ({e})"
    if others:
        return f"Removed. Hunt list {hunt_list} kept: still used by {', '.join(others[:3])}"
    try:
        _call(conn, "removeHuntList", name=hunt_list)
        notes.append(f"hunt list {hunt_list} removed")
    except AxlError as e:
        return f"Removed. Hunt list {hunt_list} kept: {e}"
    for lg in line_groups:
        try:
            if _hunt_lists_using_line_group(conn, lg):
                notes.append(f"line group {lg} kept (used by another hunt list)")
                continue
            _call(conn, "removeLineGroup", name=lg)
            notes.append(f"line group {lg} removed")
        except AxlError as e:
            notes.append(f"line group {lg} kept: {e}")
    return ". ".join(notes[:1]) + (". " + ", ".join(notes[1:]) if len(notes) > 1 else "")
