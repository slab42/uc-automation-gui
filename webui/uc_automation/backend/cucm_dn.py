"""AXL operations for Directory Numbers: move partition, alternate numbers, orphans.

Modelled on cucm/DN_move_partition.py and cucm/DN_EntAltNum-E164AltNum_remove.py. A DN is identified by
pattern + partition, so these pages use composite keys (backend/keys.py).
"""

from .cucm_axl import AxlError, list_paged, sql_rows, _call, _fault_message, _service, _text
from .cucm_connections import CucmConnection
from .keys import split_key

DN_FIELDS = ["pattern", "routePartitionName", "description"]
MOVE_FIELDS = ["pattern", "routePartitionName", "newRoutePartitionName"]
ALT_FIELDS = ["pattern", "routePartitionName", "description", "enterpriseAltNum", "e164AltNum"]
ORPHAN_FIELDS = ["pattern", "routePartitionName", "description"]

_EMPTY_ALT = {"numMask": None, "isUrgent": None, "addLocalRoutePartition": None, "routePartition": None,
              "advertiseGloballyIls": None}


def _line_ref(pattern: str, partition: str) -> dict[str, str]:
    ref = {"pattern": pattern}
    if partition:
        ref["routePartitionName"] = partition
    return ref


def _clean(row: dict[str, str], fields: list[str]) -> dict[str, str]:
    r = {f: (row.get(f) or "").strip() for f in fields}
    if not r["pattern"]:
        raise AxlError("pattern is required")
    return r


# --- Move partition ---

def list_dns(conn: CucmConnection) -> list[dict[str, str]]:
    rows = list_paged(conn, "listLine", "line", {"pattern": "%"}, DN_FIELDS)
    rows = [{**r, "newRoutePartitionName": ""} for r in rows]
    return sorted(rows, key=lambda r: (r["pattern"], r["routePartitionName"]))


def move_dn(conn: CucmConnection, key: str, new_partition: str) -> None:
    pattern, partition = split_key(key)
    if not new_partition:
        raise AxlError("the new partition is required")
    if new_partition == partition:
        raise AxlError("already in that partition")
    _call(conn, "updateLine", **_line_ref(pattern, partition), newRoutePartitionName=new_partition)


def move_dn_row(conn: CucmConnection, row: dict[str, str]) -> None:
    """Import row: pattern, routePartitionName (current), newRoutePartitionName."""
    r = _clean(row, MOVE_FIELDS)
    move_dn(conn, f"{r['pattern']}|{r['routePartitionName']}", r["newRoutePartitionName"])


def not_supported(conn: CucmConnection, *_args) -> None:
    raise AxlError("Not supported on this page")


# --- Alternate numbers ---

def _mask(value) -> str:
    return _text((value or {}).get("numMask")) if isinstance(value, dict) else ""


def list_dns_with_alt_numbers(conn: CucmConnection, page: int = 500) -> list[dict[str, str]]:
    """Only DNs that have an enterprise or E.164 alternate number (the ones worth removing)."""
    from zeep.exceptions import Fault
    from zeep.helpers import serialize_object
    svc = _service(conn)
    out: list[dict[str, str]] = []
    skip = 0
    while True:
        try:
            resp = svc.listLine(searchCriteria={"pattern": "%"}, returnedTags={
                "pattern": "", "routePartitionName": "", "description": "",
                "enterpriseAltNum": {"numMask": ""}, "e164AltNum": {"numMask": ""}}, skip=skip, first=page)
        except Fault as e:
            raise AxlError(_fault_message(e))
        data = serialize_object(resp["return"]) if resp["return"] is not None else {}
        batch = (data or {}).get("line") or []
        for ln in batch:
            ent, e164 = _mask(ln.get("enterpriseAltNum")), _mask(ln.get("e164AltNum"))
            if ent or e164:
                out.append({"pattern": _text(ln.get("pattern")), "routePartitionName": _text(ln.get("routePartitionName")),
                            "description": _text(ln.get("description")), "enterpriseAltNum": ent, "e164AltNum": e164})
        if len(batch) < page:
            break
        skip += page
    return sorted(out, key=lambda r: (r["pattern"], r["routePartitionName"]))


def remove_alt_numbers(conn: CucmConnection, key: str) -> str:
    """Clear the enterprise and E.164 alternate numbers of one DN (DN_EntAltNum-E164AltNum_remove.py)."""
    pattern, partition = split_key(key)
    ref = _line_ref(pattern, partition)
    _call(conn, "updateLine", **ref, enterpriseAltNum=dict(_EMPTY_ALT))
    _call(conn, "updateLine", **ref, e164AltNum=dict(_EMPTY_ALT))
    return "Enterprise and E.164 alternate numbers removed"


def remove_alt_numbers_row(conn: CucmConnection, row: dict[str, str]) -> str:
    r = _clean(row, ALT_FIELDS)
    return remove_alt_numbers(conn, f"{r['pattern']}|{r['routePartitionName']}")


# --- Orphans ---

def list_orphan_dns(conn: CucmConnection) -> list[dict[str, str]]:
    """DNs (pattern usage 2 = Device) that are not assigned to any device, device profile or remote
    destination profile."""
    rows = sql_rows(conn, """
        SELECT n.dnorpattern AS pattern, NVL(rp.name, '') AS partition, NVL(n.description, '') AS description
        FROM numplan n
        LEFT JOIN routepartition rp ON rp.pkid = n.fkroutepartition
        WHERE n.tkpatternusage = 2
          AND NOT EXISTS (SELECT 1 FROM devicenumplanmap m WHERE m.fknumplan = n.pkid)
        ORDER BY n.dnorpattern
        """, 3)
    return [{"pattern": r.get("pattern", ""), "routePartitionName": r.get("partition", ""),
             "description": r.get("description", "")} for r in rows]


def remove_dn(conn: CucmConnection, key: str) -> None:
    pattern, partition = split_key(key)
    _call(conn, "removeLine", **_line_ref(pattern, partition))
