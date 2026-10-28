"""AXL operations for Devices: phones, softkey templates, common device configs,
phone button templates, and the MPP firmware workflows."""

import re

from .cucm_axl import AxlError, list_paged, sql_quote, sql_rows, _call, _non_blank, _text
from .cucm_connections import CucmConnection

PHONE_FIELDS = ["name", "description", "product", "protocol", "devicePoolName", "callingSearchSpaceName",
                "phoneTemplateName", "securityProfileName", "sipProfileName", "commonPhoneConfigName",
                "locationName"]
SOFTKEY_FIELDS = ["name", "description", "baseSoftkeyTemplateName"]
CDC_FIELDS = ["name", "softkeyTemplateName", "userLocale"]
BUTTON_TEMPLATE_FIELDS = ["name", "basePhoneTemplateName"]
CTIRP_FIELDS = ["name", "description", "devicePoolName", "callingSearchSpaceName", "locationName"]
MPP_FIELDS = ["name", "description", "model", "devicePoolName", "loadInformation"]

MPP_LOAD_SERVER = "cloudupgrader.webex.com"


def _clean(row: dict[str, str], fields: list[str], key: str = "name") -> dict[str, str]:
    r = {f: (row.get(f) or "").strip() for f in fields}
    if not r[key]:
        raise AxlError(f"{key} is required")
    return r


# --- Phones ---

def list_phones(conn: CucmConnection) -> list[dict[str, str]]:
    return sorted(list_paged(conn, "listPhone", "phone", {"name": "%"}, PHONE_FIELDS),
                  key=lambda r: r["name"])


def add_phone(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, PHONE_FIELDS)
    if not r["product"]:
        raise AxlError("product is required (for example: Cisco 8845)")
    if not r["devicePoolName"]:
        raise AxlError("devicePoolName is required")
    body = _non_blank(r)
    body.setdefault("protocol", "SIP")
    body.setdefault("commonPhoneConfigName", "Standard Common Phone Profile")
    body.setdefault("locationName", "Hub_None")
    body["class"] = "Phone"
    body["protocolSide"] = "User"
    body["useTrustedRelayPoint"] = "Default"
    _call(conn, "addPhone", phone=body)


def update_phone(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, PHONE_FIELDS)
    body = _non_blank(r, skip=("name", "product", "protocol"))
    if not body:
        raise AxlError("nothing to change")
    _call(conn, "updatePhone", name=r["name"], **body)


def remove_phone(conn: CucmConnection, name: str) -> None:
    _call(conn, "removePhone", name=name)


# --- Softkey templates ---

def list_softkey_templates(conn: CucmConnection) -> list[dict[str, str]]:
    return sorted(list_paged(conn, "listSoftKeyTemplate", "softKeyTemplate", {"name": "%"}, SOFTKEY_FIELDS),
                  key=lambda r: r["name"].lower())


def add_softkey_template(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, SOFTKEY_FIELDS)
    body = {"name": r["name"], "description": r["description"] or r["name"],
            "baseSoftkeyTemplateName": r["baseSoftkeyTemplateName"] or "Standard User"}
    _call(conn, "addSoftKeyTemplate", softKeyTemplate=body)


def update_softkey_template(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, SOFTKEY_FIELDS)
    if not r["description"]:
        raise AxlError("nothing to change")
    _call(conn, "updateSoftKeyTemplate", name=r["name"], description=r["description"])


def remove_softkey_template(conn: CucmConnection, name: str) -> None:
    _call(conn, "removeSoftKeyTemplate", name=name)


# --- Common device configs ---

def list_common_device_configs(conn: CucmConnection) -> list[dict[str, str]]:
    return sorted(list_paged(conn, "listCommonDeviceConfig", "commonDeviceConfig", {"name": "%"}, CDC_FIELDS),
                  key=lambda r: r["name"].lower())


def add_common_device_config(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, CDC_FIELDS)
    _call(conn, "addCommonDeviceConfig", commonDeviceConfig=_non_blank(r))


def update_common_device_config(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, CDC_FIELDS)
    body = _non_blank(r, skip=("name",))
    if not body:
        raise AxlError("nothing to change")
    _call(conn, "updateCommonDeviceConfig", name=r["name"], **body)


def remove_common_device_config(conn: CucmConnection, name: str) -> None:
    _call(conn, "removeCommonDeviceConfig", name=name)


# --- Phone button templates ---

def list_phone_button_templates(conn: CucmConnection) -> list[dict[str, str]]:
    """User-modifiable templates only: CUCM's built-in templates cannot be changed or deleted.

    The list call cannot return the base template, so only the name is available.
    """
    rows = list_paged(conn, "listPhoneButtonTemplate", "phoneButtonTemplate", {"name": "%"},
                      ["name", "isUserModifiable"])
    modifiable = [r for r in rows if r["isUserModifiable"] and r["isUserModifiable"].lower() != "false"]
    return sorted([{"name": r["name"], "basePhoneTemplateName": ""} for r in modifiable],
                  key=lambda r: r["name"].lower())


def add_phone_button_template(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, BUTTON_TEMPLATE_FIELDS)
    if not r["basePhoneTemplateName"]:
        raise AxlError("basePhoneTemplateName is required (for example: Cisco 8845 SIP)")
    _call(conn, "addPhoneButtonTemplate", phoneButtonTemplate=r)


def find_button_template_usage(conn: CucmConnection, names: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Return ({template: ["Phone: SEP...", ...]}, warnings) for the given templates.

    Checks phones, device profiles and universal device templates (the three places CUCM
    refuses to delete a template from). A source that cannot be read is reported as a warning
    and that template's result should then be treated as unconfirmed.
    """
    wanted = set(names)
    usage: dict[str, list[str]] = {n: [] for n in names}
    warnings: list[str] = []
    sources = [
        ("Phone", "listPhone", "phone", "phoneTemplateName"),
        ("Device profile", "listDeviceProfile", "deviceProfile", "phoneTemplateName"),
        ("Universal device template", "listUniversalDeviceTemplate", "universalDeviceTemplate",
         "phoneButtonTemplate"),
    ]
    for label, op, result_key, tag in sources:
        try:
            rows = list_paged(conn, op, result_key, {"name": "%"}, ["name", tag])
        except AxlError as e:
            warnings.append(f"{label}s could not be checked: {e}")
            continue
        for r in rows:
            if r[tag] in wanted:
                usage[r[tag]].append(f"{label}: {r['name']}")
    return usage, warnings


def update_phone_button_template(conn: CucmConnection, row: dict[str, str]) -> None:
    raise AxlError("Phone button templates cannot be modified here")


def remove_phone_button_template(conn: CucmConnection, name: str) -> None:
    _call(conn, "removePhoneButtonTemplate", name=name)


# --- CTI route points ---

def list_cti_route_points(conn: CucmConnection) -> list[dict[str, str]]:
    return sorted(list_paged(conn, "listCtiRoutePoint", "ctiRoutePoint", {"name": "%"}, CTIRP_FIELDS),
                  key=lambda r: r["name"].lower())


def add_cti_route_point(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, CTIRP_FIELDS)
    if not r["devicePoolName"]:
        raise AxlError("devicePoolName is required")
    body = _non_blank(r)
    body.setdefault("locationName", "Hub_None")
    body["product"] = "CTI Route Point"
    body["class"] = "CTI Route Point"
    body["protocol"] = "SCCP"
    body["protocolSide"] = "User"
    body["useTrustedRelayPoint"] = "Default"
    _call(conn, "addCtiRoutePoint", ctiRoutePoint=body)


def update_cti_route_point(conn: CucmConnection, row: dict[str, str]) -> None:
    r = _clean(row, CTIRP_FIELDS)
    body = _non_blank(r, skip=("name",))
    if not body:
        raise AxlError("nothing to change")
    _call(conn, "updateCtiRoutePoint", name=r["name"], **body)


def _cti_route_point_lines(conn: CucmConnection, name: str) -> list[tuple[str, str]]:
    resp = _call(conn, "getCtiRoutePoint", name=name, returnedTags={
        "lines": {"line": {"dirn": {"pattern": "", "routePartitionName": ""}}}})
    lines = resp["return"]["ctiRoutePoint"].lines
    items = (lines.line if lines is not None else None) or []
    if not isinstance(items, list):
        items = [items]
    out = []
    for ln in items:
        dirn = getattr(ln, "dirn", None)
        if dirn is not None and dirn.pattern:
            out.append((dirn.pattern, _text(dirn.routePartitionName)))
    return out


def _line_devices(conn: CucmConnection, pattern: str, partition: str) -> list[str]:
    """Devices, device profiles and remote destination profiles that still use a directory number."""
    where = (f"rp.name = '{sql_quote(partition)}'" if partition else "n.fkroutepartition IS NULL")
    rows = sql_rows(conn, f"""
        SELECT d.name AS name
        FROM numplan n
        LEFT JOIN routepartition rp ON rp.pkid = n.fkroutepartition
        INNER JOIN devicenumplanmap m ON m.fknumplan = n.pkid
        INNER JOIN device d ON d.pkid = m.fkdevice
        WHERE n.dnorpattern = '{sql_quote(pattern)}' AND {where}
        """, 1)
    return [r["name"] for r in rows if r.get("name")]


def remove_cti_route_point(conn: CucmConnection, name: str) -> str:
    """Remove the route point, then delete its directory numbers that no device uses any more
    (ctiRP_delete.py). Returns a detail line; a DN that cannot be removed does not fail the removal."""
    lines = _cti_route_point_lines(conn, name)
    _call(conn, "removeCtiRoutePoint", name=name)
    if not lines:
        return "Removed (no directory numbers)"
    notes = []
    for pattern, partition in lines:
        label = f"{pattern} ({partition or 'no partition'})"
        try:
            devices = _line_devices(conn, pattern, partition)
            if devices:
                notes.append(f"DN {label} kept: still on {', '.join(devices[:3])}")
                continue
            kwargs = {"pattern": pattern}
            if partition:
                kwargs["routePartitionName"] = partition
            _call(conn, "removeLine", **kwargs)
            notes.append(f"DN {label} removed")
        except AxlError as e:
            notes.append(f"DN {label} kept: {e}")
    return "Removed. " + "; ".join(notes)


# --- Physical phones: MPP firmware workflows ---

def format_phone_identifier(identifier: str) -> str:
    """Device name for a device name or MAC address (a 12-digit MAC gets the SEP prefix)."""
    identifier = identifier.strip()
    stripped = re.sub(r"[:.\-]", "", identifier)
    if re.fullmatch(r"[0-9A-Fa-f]{12}", stripped):
        return "SEP" + stripped.upper()
    return identifier


_LOADS = {
    "migrate": {"7832": "sip7832.12-0-7MPP0501-123", "8832": "sip8832.12-0-7MPP0501-123",
                "8845_65": "sip8845_65.12-0-7MPP0201-66", "88": "sip88xx.12-0-7MPP0501-123",
                "78": "sip78xx.12-0-7MPP0501-123"},
    "prep": {"7832": "sip7832.14-4-1-0001-36", "8832": "sip8832.14-4-1-0001-36",
             "8845_65": "sip8845_65.14-4-1-0001-36", "88": "sip88xx.14-4-1-0001-36",
             "78": "sip78xx.14-4-1-0001-36"},
}
MPP_ACTIONS = {"migrate": "Migrate to MPP load", "prep": "Prep for Webex Calling"}


def mpp_load_for_model(model: str, action: str = "migrate") -> str | None:
    loads = _LOADS[action]
    if not model:
        return None
    if "7832" in model:
        return loads["7832"]
    if "8832" in model:
        return loads["8832"]
    if "8845" in model or "8865" in model:
        return loads["8845_65"]
    if "88" in model:
        return loads["88"]
    if "78" in model:
        return loads["78"]
    return None


def list_mpp_phones(conn: CucmConnection) -> list[dict[str, str]]:
    """Physical 78xx/88xx phones (the models with an MPP load mapping)."""
    rows = list_paged(conn, "listPhone", "phone", {"name": "SEP%"}, MPP_FIELDS)
    return sorted([r for r in rows if mpp_load_for_model(r["model"])], key=lambda r: r["name"])


def run_mpp_action(conn: CucmConnection, identifier: str, action: str) -> str:
    """Set the load (and for 'prep' the load server and peer firmware sharing), then reset. Returns detail."""
    from lxml import etree
    name = format_phone_identifier(identifier)
    resp = _call(conn, "getPhone", name=name)
    model = (resp["return"]["phone"].get("model") or "") if resp["return"] else ""
    load = mpp_load_for_model(model, action)
    if not load:
        raise AxlError(f"No phone load mapping for model '{model}'")
    kwargs = {"loadInformation": load}
    if action == "prep":
        vendor = etree.Element("vendorConfig")
        etree.SubElement(vendor, "loadServer").text = MPP_LOAD_SERVER
        etree.SubElement(vendor, "peerFirmwareSharing").text = "0"
        kwargs["vendorConfig"] = vendor
    _call(conn, "updatePhone", name=name, **kwargs)
    try:
        _call(conn, "resetPhone", name=name)
    except AxlError as e:
        raise AxlError(f"Updated but reset failed: {e}")
    return f"{model}: load {load}, reset"


def not_supported(*_args):
    raise AxlError("Not supported on this page")
