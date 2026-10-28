"""AXL operations for Route Partitions and Calling Search Spaces."""

from .cucm_axl import AxlError, _fault_message, _service, _text, list_paged
from .cucm_connections import CucmConnection
from .keys import split_key

PATTERN_TYPES = ["+E.164 Number", "Enterprise Number"]
PSTN_RULES = ["No PSTN", "Use pattern", "Specify"]
PATTERN_FIELDS = ["description", "pattern", "patternType", "hostedRoutePSTNRule",
                  "pstnFailStrip", "pstnFailPrepend"]
PARTITION_FIELDS = ["name", "description"]
CSS_FIELDS = ["name", "description", "members"]
PICKUP_GROUP_FIELDS = ["name", "pattern", "description", "routePartitionName", "pickupNotification"]
PICKUP_NOTIFICATIONS = ["No Alert", "Audio Alert", "Visual Alert", "Audio and Visual Alert"]
MEMBER_SEP = ";"


def _clean(row: dict[str, str], fields: list[str]) -> dict[str, str]:
    r = {f: (row.get(f) or "").strip() for f in fields}
    if not r["name"]:
        raise AxlError("name is required")
    return r


def _members(text: str) -> list[str]:
    return [m.strip() for m in text.split(MEMBER_SEP) if m.strip()]


def _member_list(names: list[str]) -> dict:
    return {"member": [{"routePartitionName": n, "index": i} for i, n in enumerate(names, 1)]}


# --- Route Partitions ---

def list_partitions(conn: CucmConnection) -> list[dict[str, str]]:
    rows = list_paged(conn, "listRoutePartition", "routePartition", {"name": "%"}, PARTITION_FIELDS)
    return sorted(rows, key=lambda r: r["name"].lower())


def add_partition(conn: CucmConnection, row: dict[str, str]) -> None:
    from zeep.exceptions import Fault
    r = _clean(row, PARTITION_FIELDS)
    body = {"name": r["name"]}
    if r["description"]:
        body["description"] = r["description"]
    try:
        _service(conn).addRoutePartition(routePartition=body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def update_partition(conn: CucmConnection, row: dict[str, str]) -> None:
    from zeep.exceptions import Fault
    r = _clean(row, PARTITION_FIELDS)
    if not r["description"]:
        raise AxlError("nothing to change")
    try:
        _service(conn).updateRoutePartition(name=r["name"], description=r["description"])
    except Fault as e:
        raise AxlError(_fault_message(e))


def remove_partition(conn: CucmConnection, name: str) -> None:
    from zeep.exceptions import Fault
    try:
        _service(conn).removeRoutePartition(name=name)
    except Fault as e:
        raise AxlError(_fault_message(e))


# --- Calling Search Spaces ---

def list_css(conn: CucmConnection) -> list[dict[str, str]]:
    """members come from the read-only 'clause' (partition names joined by ':')."""
    rows = list_paged(conn, "listCss", "css", {"name": "%"}, ["name", "description", "clause"])
    out = []
    for r in rows:
        parts = [p for p in r["clause"].split(":") if p]
        out.append({"name": r["name"], "description": r["description"], "members": MEMBER_SEP.join(parts)})
    return sorted(out, key=lambda r: r["name"].lower())


def add_css(conn: CucmConnection, row: dict[str, str]) -> None:
    from zeep.exceptions import Fault
    r = _clean(row, CSS_FIELDS)
    body: dict = {"name": r["name"]}
    if r["description"]:
        body["description"] = r["description"]
    members = _members(r["members"])
    if members:
        body["members"] = _member_list(members)
    try:
        _service(conn).addCss(css=body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def update_css(conn: CucmConnection, row: dict[str, str]) -> None:
    """Blank cells leave a field unchanged; a members value replaces the whole ordered list."""
    from zeep.exceptions import Fault
    r = _clean(row, CSS_FIELDS)
    body: dict = {"name": r["name"]}
    if r["description"]:
        body["description"] = r["description"]
    members = _members(r["members"])
    if members:
        body["members"] = _member_list(members)
    if len(body) == 1:
        raise AxlError("nothing to change")
    try:
        _service(conn).updateCss(**body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def remove_css(conn: CucmConnection, name: str) -> None:
    from zeep.exceptions import Fault
    try:
        _service(conn).removeCss(name=name)
    except Fault as e:
        raise AxlError(_fault_message(e))


# --- Call Pickup Groups ---

def list_pickup_groups(conn: CucmConnection) -> list[dict[str, str]]:
    rows = list_paged(conn, "listCallPickupGroup", "callPickupGroup", {"pattern": "%"}, PICKUP_GROUP_FIELDS)
    return sorted(rows, key=lambda r: r["name"].lower())


def _clean_pickup_group(row: dict[str, str]) -> dict[str, str]:
    r = _clean(row, PICKUP_GROUP_FIELDS)
    if r["pickupNotification"] and r["pickupNotification"] not in PICKUP_NOTIFICATIONS:
        raise AxlError(f"pickupNotification must be one of: {', '.join(PICKUP_NOTIFICATIONS)}")
    return r


def add_pickup_group(conn: CucmConnection, row: dict[str, str]) -> None:
    from zeep.exceptions import Fault
    r = _clean_pickup_group(row)
    if not r["pattern"]:
        raise AxlError("pattern is required")
    body = {k: v for k, v in r.items() if v}
    try:
        _service(conn).addCallPickupGroup(callPickupGroup=body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def update_pickup_group(conn: CucmConnection, row: dict[str, str]) -> None:
    """Blank CSV cells leave that field unchanged. The pattern and partition are not changed here."""
    from zeep.exceptions import Fault
    r = _clean_pickup_group(row)
    body = {k: r[k] for k in ("description", "pickupNotification") if r[k]}
    if not body:
        raise AxlError("nothing to change")
    try:
        _service(conn).updateCallPickupGroup(name=r["name"], **body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def remove_pickup_group(conn: CucmConnection, name: str) -> None:
    from zeep.exceptions import Fault
    try:
        _service(conn).removeCallPickupGroup(name=name)
    except Fault as e:
        raise AxlError(_fault_message(e))


def find_pickup_group_usage(conn: CucmConnection, names: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Return ({group: ["Directory Number: 1001 (PT)", ...]}, warnings) for the given groups.

    Same checks as cucm/call_pickup_group_remediate.py: lines and hunt pilots whose Call Pickup Group is
    the group (AXL does not list those on the group itself), and other groups nested in the group.
    A source that cannot be read is a warning, and that group's result should be treated as unconfirmed.
    """
    from zeep.exceptions import Fault
    from zeep.helpers import serialize_object
    wanted = set(names)
    usage: dict[str, list[str]] = {n: [] for n in names}
    warnings: list[str] = []
    sources = [
        ("Directory Number", "listLine", "line"),
        ("Hunt Pilot", "listHuntPilot", "huntPilot"),
    ]
    for label, op, result_key in sources:
        try:
            rows = list_paged(conn, op, result_key, {"pattern": "%"},
                              ["pattern", "routePartitionName", "callPickupGroupName"])
        except AxlError as e:
            warnings.append(f"{label}s could not be checked: {e}")
            continue
        for r in rows:
            if r["callPickupGroupName"] in wanted:
                usage[r["callPickupGroupName"]].append(
                    f"{label}: {r['pattern']} ({r['routePartitionName'] or 'None'})")
    svc = _service(conn)
    for name in names:
        try:
            resp = svc.getCallPickupGroup(name=name, returnedTags={
                "name": "", "members": {"member": {"priority": "", "pickupGroupName": ""}}})
        except Fault as e:
            warnings.append(f"Nested groups of {name} could not be checked: {_fault_message(e)}")
            continue
        group = serialize_object(resp["return"]["callPickupGroup"]) or {}
        members = (group.get("members") or {}).get("member") or []
        if not isinstance(members, list):
            members = [members]
        for m in members:
            nested = _text((m or {}).get("pickupGroupName"))
            if nested and nested != name:  # a group's first member is always itself
                usage[name].append(f"Nested Call Pickup Group: {nested}")
    return usage, warnings


# --- Route Patterns ---

ROUTE_PATTERN_FIELDS = ["pattern", "routePartitionName", "description", "routeListName", "gatewayName"]
NETWORK_LOCATIONS = ["OnNet", "OffNet"]


def list_route_patterns(conn: CucmConnection) -> list[dict[str, str]]:
    # AXL does not return the destination when listing, so those two columns stay blank here.
    rows = list_paged(conn, "listRoutePattern", "routePattern", {"pattern": "%"},
                      ["pattern", "routePartitionName", "description"])
    rows = [{**r, "routeListName": "", "gatewayName": ""} for r in rows]
    return sorted(rows, key=lambda r: (r["pattern"], r["routePartitionName"]))


def _clean_route_pattern(row: dict[str, str]) -> dict[str, str]:
    r = {f: (row.get(f) or "").strip() for f in ROUTE_PATTERN_FIELDS}
    if not r["pattern"]:
        raise AxlError("pattern is required")
    return r


def add_route_pattern(conn: CucmConnection, row: dict[str, str]) -> None:
    from zeep.exceptions import Fault
    r = _clean_route_pattern(row)
    if not r["routePartitionName"]:
        raise AxlError("routePartitionName is required")
    if bool(r["routeListName"]) == bool(r["gatewayName"]):
        raise AxlError("give either routeListName or gatewayName (not both)")
    body = {"pattern": r["pattern"], "routePartitionName": r["routePartitionName"],
            "blockEnable": False, "useCallingPartyPhoneMask": "Default", "networkLocation": "OnNet",
            "destination": {"routeListName": r["routeListName"]} if r["routeListName"]
            else {"gatewayName": r["gatewayName"]}}
    if r["description"]:
        body["description"] = r["description"]
    try:
        _service(conn).addRoutePattern(routePattern=body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def update_route_pattern(conn: CucmConnection, row: dict[str, str]) -> None:
    """Blank cells leave a field unchanged. Only the description and destination can change here."""
    from zeep.exceptions import Fault
    r = _clean_route_pattern(row)
    if r["routeListName"] and r["gatewayName"]:
        raise AxlError("give either routeListName or gatewayName (not both)")
    body: dict = {}
    if r["description"]:
        body["description"] = r["description"]
    if r["routeListName"]:
        body["destination"] = {"routeListName": r["routeListName"]}
    if r["gatewayName"]:
        body["destination"] = {"gatewayName": r["gatewayName"]}
    if not body:
        raise AxlError("nothing to change")
    try:
        _service(conn).updateRoutePattern(pattern=r["pattern"], routePartitionName=r["routePartitionName"], **body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def remove_route_pattern(conn: CucmConnection, key: str) -> None:
    from zeep.exceptions import Fault
    pattern, partition = split_key(key)
    try:
        _service(conn).removeRoutePattern(pattern=pattern, routePartitionName=partition)
    except Fault as e:
        raise AxlError(_fault_message(e))


def find_duplicatish_route_patterns(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Pairs of '.+' and '+' patterns that share the same last 11 characters (RP-duplicatish_remediate.py).

    Returns [{dot_plus_id, dot_plus, plus, partition, plus_partition, last_11}] sorted by the shared suffix.
    The '.+' pattern is the one proposed for deletion. CUCM stores a literal plus as '\\+'; backslashes are
    ignored when classifying.
    """
    dot_plus: dict[str, dict[str, str]] = {}
    plus: dict[str, dict[str, str]] = {}
    for r in rows:
        p = r["pattern"]
        bare = p.replace("\\", "")
        last = p[-11:]
        if bare.startswith("+.") or bare.startswith(".+"):
            dot_plus[last] = r
        elif bare.startswith("+"):
            plus[last] = r
    out = []
    for last, d in dot_plus.items():
        if last in plus:
            out.append({"dot_plus_id": d["id"], "dot_plus": d["pattern"], "partition": d["routePartitionName"],
                        "plus": plus[last]["pattern"], "plus_partition": plus[last]["routePartitionName"],
                        "last_11": last})
    return sorted(out, key=lambda x: x["last_11"])


# --- Translation Patterns ---

TRANS_PATTERN_FIELDS = ["pattern", "routePartitionName", "description", "callingSearchSpaceName",
                        "calledPartyTransformationMask", "callingPartyTransformationMask"]


def list_translation_patterns(conn: CucmConnection) -> list[dict[str, str]]:
    rows = list_paged(conn, "listTransPattern", "transPattern", {"pattern": "%"}, TRANS_PATTERN_FIELDS)
    return sorted(rows, key=lambda r: (r["pattern"], r["routePartitionName"]))


def _clean_trans_pattern(row: dict[str, str]) -> dict[str, str]:
    r = {f: (row.get(f) or "").strip() for f in TRANS_PATTERN_FIELDS}
    if not r["pattern"]:
        raise AxlError("pattern is required")
    return r


def add_translation_pattern(conn: CucmConnection, row: dict[str, str]) -> None:
    from zeep.exceptions import Fault
    r = _clean_trans_pattern(row)
    if not r["routePartitionName"]:
        raise AxlError("routePartitionName is required")
    body = {k: v for k, v in r.items() if v}
    body["usage"] = "Translation"
    try:
        _service(conn).addTransPattern(transPattern=body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def update_translation_pattern(conn: CucmConnection, row: dict[str, str]) -> None:
    """Blank cells leave a field unchanged. The pattern and partition identify the row."""
    from zeep.exceptions import Fault
    r = _clean_trans_pattern(row)
    body = {k: r[k] for k in ("description", "callingSearchSpaceName", "calledPartyTransformationMask",
                              "callingPartyTransformationMask") if r[k]}
    if not body:
        raise AxlError("nothing to change")
    try:
        _service(conn).updateTransPattern(pattern=r["pattern"], routePartitionName=r["routePartitionName"], **body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def remove_translation_pattern(conn: CucmConnection, key: str) -> None:
    from zeep.exceptions import Fault
    pattern, partition = split_key(key)
    try:
        _service(conn).removeTransPattern(pattern=pattern, routePartitionName=partition or None)
    except Fault as e:
        raise AxlError(_fault_message(e))


# --- Advertised Patterns ---

def list_advertised_patterns(conn: CucmConnection) -> list[dict[str, str]]:
    rows = list_paged(conn, "listAdvertisedPatterns", "advertisedPatterns",
                      {"pattern": "%"}, PATTERN_FIELDS)
    return sorted(rows, key=lambda r: r["pattern"])


def _clean_pattern(row: dict[str, str]) -> dict[str, str]:
    r = {f: (row.get(f) or "").strip() for f in PATTERN_FIELDS}
    if not r["pattern"]:
        raise AxlError("pattern is required")
    if r["patternType"] and r["patternType"] not in PATTERN_TYPES:
        raise AxlError(f"patternType must be one of: {', '.join(PATTERN_TYPES)}")
    if r["hostedRoutePSTNRule"] and r["hostedRoutePSTNRule"] not in PSTN_RULES:
        raise AxlError(f"hostedRoutePSTNRule must be one of: {', '.join(PSTN_RULES)}")
    if r["pstnFailStrip"] and not r["pstnFailStrip"].isdigit():
        raise AxlError("pstnFailStrip must be a number")
    return r


def add_advertised_pattern(conn: CucmConnection, row: dict[str, str]) -> None:
    from zeep.exceptions import Fault
    r = _clean_pattern(row)
    body = {"pattern": r["pattern"]}
    if r["description"]:
        body["description"] = r["description"]
    body["patternType"] = r["patternType"] or "Enterprise Number"
    body["hostedRoutePSTNRule"] = r["hostedRoutePSTNRule"] or "No PSTN"
    body["pstnFailStrip"] = r["pstnFailStrip"] or "0"
    if r["pstnFailPrepend"]:
        body["pstnFailPrepend"] = r["pstnFailPrepend"]
    try:
        _service(conn).addAdvertisedPatterns(advertisedPatterns=body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def update_advertised_pattern(conn: CucmConnection, row: dict[str, str]) -> None:
    """Update an existing pattern. Blank CSV cells leave that field unchanged."""
    from zeep.exceptions import Fault
    r = _clean_pattern(row)
    body = {"pattern": r["pattern"]}
    for f in ["description", "patternType", "hostedRoutePSTNRule", "pstnFailStrip", "pstnFailPrepend"]:
        if r[f]:
            body[f] = r[f]
    if len(body) == 1:
        raise AxlError("nothing to change")
    try:
        _service(conn).updateAdvertisedPatterns(**body)
    except Fault as e:
        raise AxlError(_fault_message(e))


def remove_advertised_pattern(conn: CucmConnection, pattern: str) -> None:
    """Remove a pattern; retries with a '+' prefix if the bare pattern is not found."""
    from zeep.exceptions import Fault
    svc = _service(conn)
    try:
        svc.removeAdvertisedPatterns(pattern=pattern)
        return
    except Fault as e:
        first = _fault_message(e)
    if not pattern.startswith("+"):
        try:
            svc.removeAdvertisedPatterns(pattern="+" + pattern)
            return
        except Fault:
            pass
    raise AxlError(first)
