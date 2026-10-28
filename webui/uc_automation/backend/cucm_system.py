"""AXL operations for CUCM System objects: audio codec preference lists, regions, locations, device pools.

Modelled on cucm/audio_codec_preference_list_create.py, regions_remediate.py, locations_remediate.py and
device_pools_remediate.py. Regions, locations and device pools have no AXL "who uses this" call, so their
dependency checks use SQL like the scripts do.
"""

import re

from .cucm_axl import AxlError, list_paged, sql_rows, _call, _non_blank, _service, _text
from .cucm_connections import CucmConnection

CODEC_LIST_FIELDS = ["name", "description", "codecs"]
REGION_FIELDS = ["name", "defaultCodec"]
LOCATION_FIELDS = ["name", "withinAudioBandwidth", "withinVideoBandwidth"]
DEVICE_POOL_FIELDS = ["name", "regionName", "locationName", "callManagerGroupName", "dateTimeSettingName",
                      "srstName"]
CODEC_SEP = ";"

# Built in objects the scripts leave alone (and the pages hide, so they cannot be selected for deletion).
SYSTEM_REGIONS = {"Default"}
SYSTEM_LOCATIONS = {"Phantom", "Shadow", "Hub_None"}


def _clean(row: dict[str, str], fields: list[str]) -> dict[str, str]:
    r = {f: (row.get(f) or "").strip() for f in fields}
    if not r["name"]:
        raise AxlError("name is required")
    return r


# --- Audio codec preference lists ---

def _codecs(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"[;,]", text) if c.strip()]


def list_codec_lists(conn: CucmConnection) -> list[dict[str, str]]:
    """Names and descriptions come from the list call; the ordered codecs need one get per list."""
    rows = list_paged(conn, "listAudioCodecPreferenceList", "audioCodecPreferenceList", {"name": "%"},
                      ["name", "description"])
    svc = _service(conn)
    for r in rows:
        r["codecs"] = ""
        try:
            resp = svc.getAudioCodecPreferenceList(name=r["name"],
                                                   returnedTags={"codecsInList": {"codecNames": ""}})
            names = resp["return"]["audioCodecPreferenceList"].codecsInList.codecNames
            r["codecs"] = CODEC_SEP.join(names if isinstance(names, list) else [names] if names else [])
        except Exception:
            pass  # leave blank; the list itself still loads
    return sorted(rows, key=lambda r: r["name"].lower())


def add_codec_list(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, CODEC_LIST_FIELDS)
    codecs = _codecs(r["codecs"])
    if not codecs:
        raise AxlError("codecs is required (for example G.711 ulaw 64k;G.729)")
    _call(conn, "addAudioCodecPreferenceList", audioCodecPreferenceList={
        "name": r["name"], "description": r["description"] or r["name"], "codecsInList": {"codecNames": codecs}})


def update_codec_list(conn: CucmConnection, row: dict[str, str]) -> None:
    """Blank cells leave a field unchanged. A codecs value replaces the whole ordered list."""
    r = _clean(row, CODEC_LIST_FIELDS)
    body: dict = {}
    if r["description"]:
        body["description"] = r["description"]
    if r["codecs"]:
        body["codecsInList"] = {"codecNames": _codecs(r["codecs"])}
    if not body:
        raise AxlError("nothing to change")
    _call(conn, "updateAudioCodecPreferenceList", name=r["name"], **body)


def remove_codec_list(conn: CucmConnection, name: str) -> None:
    _call(conn, "removeAudioCodecPreferenceList", name=name)


# --- Regions ---

def list_regions(conn: CucmConnection) -> list[dict[str, str]]:
    rows = list_paged(conn, "listRegion", "region", {"name": "%"}, REGION_FIELDS)
    return sorted((r for r in rows if r["name"] not in SYSTEM_REGIONS), key=lambda r: r["name"].lower())


def add_region(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, REGION_FIELDS)
    _call(conn, "addRegion", region=_non_blank(r))


def update_region(conn: CucmConnection, row: dict[str, str]) -> None:
    raise AxlError("Regions cannot be modified here (AXL only updates a region's related regions)")


def remove_region(conn: CucmConnection, name: str) -> None:
    if name in SYSTEM_REGIONS:
        raise AxlError(f"{name} is a system region and cannot be removed")
    _call(conn, "removeRegion", name=name)


# --- Locations ---

def list_locations(conn: CucmConnection) -> list[dict[str, str]]:
    rows = list_paged(conn, "listLocation", "location", {"name": "%"}, LOCATION_FIELDS)
    return sorted((r for r in rows if r["name"] not in SYSTEM_LOCATIONS), key=lambda r: r["name"].lower())


def _bandwidth(value: str, field: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise AxlError(f"{field} must be a whole number (-1 is unlimited)")


def add_location(conn: CucmConnection, row: dict[str, str]) -> None:
    """Same defaults as the CLI add: 512 kbps audio, unlimited video, and a link to Hub_None."""
    r = _clean(row, LOCATION_FIELDS)
    body = {
        "name": r["name"],
        "withinAudioBandwidth": _bandwidth(r["withinAudioBandwidth"] or "512", "withinAudioBandwidth"),
        "withinVideoBandwidth": _bandwidth(r["withinVideoBandwidth"] or "-1", "withinVideoBandwidth"),
        "withinImmersiveKbits": -1,
        "betweenLocations": {"betweenLocation": {"locationName": "Hub_None", "weight": "50", "audioBandwidth": "0",
                                                  "videoBandwidth": "0", "immersiveBandwidth": "0"}},
    }
    _call(conn, "addLocation", location=body)


def update_location(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, LOCATION_FIELDS)
    body = {}
    if r["withinAudioBandwidth"]:
        body["withinAudioBandwidth"] = _bandwidth(r["withinAudioBandwidth"], "withinAudioBandwidth")
    if r["withinVideoBandwidth"]:
        body["withinVideoBandwidth"] = _bandwidth(r["withinVideoBandwidth"], "withinVideoBandwidth")
    if not body:
        raise AxlError("nothing to change")
    _call(conn, "updateLocation", name=r["name"], **body)


def remove_location(conn: CucmConnection, name: str) -> None:
    if name in SYSTEM_LOCATIONS:
        raise AxlError(f"{name} is a system location and cannot be removed")
    _call(conn, "removeLocation", name=name)


# --- Device pools ---

def list_device_pools(conn: CucmConnection) -> list[dict[str, str]]:
    rows = list_paged(conn, "listDevicePool", "devicePool", {"name": "%"}, DEVICE_POOL_FIELDS)
    return sorted(rows, key=lambda r: r["name"].lower())


def add_device_pool(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, DEVICE_POOL_FIELDS)
    body = _non_blank(r)
    body.setdefault("callManagerGroupName", "Default")
    body.setdefault("dateTimeSettingName", "CMLocal")
    body.setdefault("regionName", "Default")
    body.setdefault("srstName", "Disable")
    _call(conn, "addDevicePool", devicePool=body)


def update_device_pool(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, DEVICE_POOL_FIELDS)
    body = _non_blank(r, skip=("name",))
    if not body:
        raise AxlError("nothing to change")
    _call(conn, "updateDevicePool", name=r["name"], **body)


def remove_device_pool(conn: CucmConnection, name: str) -> None:
    _call(conn, "removeDevicePool", name=name)


# --- dependency checks (SQL, as in the remediate scripts) ---

_MISSING = re.compile(r"column|table|syntax|not found|does not exist|unknown", re.I)


def _users_of(conn: CucmConnection, table: str, label: str, ref_table: str, fk_column: str,
              names: set[str]) -> dict[str, list[str]]:
    """{referenced name: ["<label>: <row name>", ...]} for rows of `table` pointing at ref_table by fk_column.

    A table or column that does not exist on this CUCM release is skipped (the scripts do the same);
    any other error (network, credentials) is raised.
    """
    out: dict[str, list[str]] = {}
    try:
        rows = sql_rows(conn, f"""
            SELECT DISTINCT t.name AS name, r.name AS ref
            FROM {table} t
            INNER JOIN {ref_table} r ON t.{fk_column} = r.pkid
            """, 2)
    except AxlError as e:
        if _MISSING.search(str(e)):
            return out
        raise
    for row in rows:
        if row.get("ref") in names:
            out.setdefault(row["ref"], []).append(f"{label}: {row.get('name', '')}")
    return out


def _merge(usage: dict[str, list[str]], found: dict[str, list[str]]) -> None:
    for k, v in found.items():
        usage[k].extend(v)


def find_region_usage(conn: CucmConnection, names: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    usage: dict[str, list[str]] = {n: [] for n in names}
    warnings: list[str] = []
    wanted = set(names)
    for table, label in [("devicepool", "Device pool"), ("device", "Device"), ("deviceprofile", "Device profile"),
                         ("gatewayendpoint", "Trunk"), ("conferencebridge", "Conference bridge"),
                         ("mtp", "Media termination point")]:
        try:
            _merge(usage, _users_of(conn, table, label, "region", "fkregion", wanted))
        except AxlError as e:
            warnings.append(f"{label}s could not be checked: {e}")
    return usage, warnings


def find_location_usage(conn: CucmConnection, names: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    usage: dict[str, list[str]] = {n: [] for n in names}
    warnings: list[str] = []
    wanted = set(names)
    for table, label in [("devicepool", "Device pool"), ("device", "Device"), ("deviceprofile", "Device profile"),
                         ("gatewayendpoint", "Trunk"), ("conferencebridge", "Conference bridge"),
                         ("mtp", "Media termination point"), ("mobilityhub", "Mobility hub")]:
        try:
            _merge(usage, _users_of(conn, table, label, "location", "fklocation", wanted))
        except AxlError as e:
            warnings.append(f"{label}s could not be checked: {e}")
    return usage, warnings


def _route_group_members(conn: CucmConnection) -> dict[str, set[str]]:
    """{route group: member device names} (a device pool is also used by gateways inside route groups)."""
    out: dict[str, set[str]] = {}
    for rg in list_paged(conn, "listRouteGroup", "routeGroup", {"name": "%"}, ["name"]):
        resp = _call(conn, "getRouteGroup", name=rg["name"])
        members = resp["return"]["routeGroup"].members
        items = (members.member if members is not None else None) or []
        if not isinstance(items, list):
            items = [items]
        out[rg["name"]] = {n for n in (_text(m.deviceName) for m in items) if n}
    return out


def find_device_pool_usage(conn: CucmConnection, names: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Devices, device profiles and remote destination profiles in the pool, plus route groups whose
    member devices are in the pool (device_pools_remediate.py)."""
    usage: dict[str, list[str]] = {n: [] for n in names}
    warnings: list[str] = []
    wanted = set(names)
    pool_devices: dict[str, list[str]] = {n: [] for n in names}
    for table, label in [("device", "Device"), ("deviceprofile", "Device profile"),
                         ("remotedestinationprofile", "Remote destination profile")]:
        try:
            found = _users_of(conn, table, label, "devicepool", "fkdevicepool", wanted)
        except AxlError as e:
            warnings.append(f"{label}s could not be checked: {e}")
            continue
        _merge(usage, found)
        if table == "device":
            for pool, refs in found.items():
                pool_devices[pool] = [r.split(": ", 1)[1] for r in refs]
    if any(pool_devices.values()):
        try:
            groups = _route_group_members(conn)
        except AxlError as e:
            warnings.append(f"Route groups could not be checked: {e}")
        else:
            for pool, devices in pool_devices.items():
                for rg, members in groups.items():
                    if members.intersection(devices):
                        usage[pool].append(f"Route group: {rg}")
    return usage, warnings
