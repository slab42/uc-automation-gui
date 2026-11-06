"""Move a CUCM analog gateway (VG2xx and similar) to Webex Calling.

The gateway and its analog ports are read from CUCM. In Webex, every chosen port gets a Webex Calling workspace
(port 1 is always created). The device is then either added right away (to the port 1 workspace, the other
workspaces are assigned to their ports) or left for later: only the workspaces are created and the device is added
afterwards with Add Device. Nothing is changed in CUCM. Not tested against a real CUCM or Webex org.
"""

import re

from .cucm_axl import AxlError, _call, _service, _text, list_paged, sql_quote, sql_rows
from .cucm_connections import CucmConnection
from .webex_api import WebexClient, WebexError
from .webex_routing import find_location_id
from .webex_workspaces import MAX_PORTS, add_location_number, build_workspace_body, create_workspace_adding_number, find_workspace_id, normalize_mac, workspace_exists

_MAC_DOMAIN = re.compile(r"^[A-Za-z]{2,3}([0-9A-Fa-f]{12})$")


def list_gateways(conn: CucmConnection) -> list[dict[str, str]]:
    """Gateways whose product looks analog (VG2xx, VG3xx, ATA...), as {domainName, product, description}."""
    rows = list_paged(conn, "listGateway", "gateway", {"domainName": "%"}, ["domainName", "product", "description"])
    return [r for r in rows if re.search(r"VG\d|ATA|ANALOG", r["product"], re.I)]


def mac_from_domain(domain: str) -> str:
    """SCCP gateway domain names are 'AN' plus the MAC address; '' when it does not look like one."""
    m = _MAC_DOMAIN.match(domain.strip())
    return m.group(1).upper() if m else ""


def _core(domain: str) -> str:
    """The hex part of a gateway name (SKIGWDB98F0FE80 and ANDB98F0FE80 both give DB98F0FE80)."""
    m = re.match(r"^[A-Za-z]*?([0-9A-Fa-f]+)$", domain)
    return m.group(1) if m else domain


def _endpoint_lines(conn: CucmConnection, domain: str) -> dict[str, tuple[str, str]]:
    """{endpoint device name: (DN, partition)} for the devices that contain the gateway's hex name.

    SCCP analog ports are named AN<hex name><unit><subunit><port>, which is not the gateway's own name (a VG350 is
    SKIGW<hex> but its ports are AN<hex>nnn), so the gateway is matched by its hex part and each endpoint is then
    checked against the gateway with AXL. The ones with no DN are included with an empty DN."""
    q = sql_quote(_core(domain))
    # nvl: a NULL column is dropped from the AXL row, which would shift the columns of the rows after it
    rows = sql_rows(conn, "select d.name as name, nvl(n.dnorpattern, '-') as dn, nvl(p.name, '-') as part "
                          "from device d "
                          "left join devicenumplanmap m on m.fkdevice = d.pkid and m.numplanindex = 1 "
                          "left join numplan n on n.pkid = m.fknumplan "
                          "left join routepartition p on p.pkid = n.fkroutepartition "
                          f"where d.name like '%{q}%' or d.name like '%@{sql_quote(domain)}' order by d.name", 3)
    out: dict[str, tuple[str, str]] = {}
    for r in rows:
        if r.get("name"):
            out[r["name"]] = tuple("" if r.get(k, "-") == "-" else r[k] for k in ("dn", "part"))
    return out


def read_ports(conn: CucmConnection, domain: str) -> list[dict[str, str]]:
    """The analog ports of a gateway as {port, endpoint, description, dn, partition}, in port order.

    The port number is the endpoint index plus 1 (CUCM counts from 0)."""
    from zeep.exceptions import Fault
    from zeep.helpers import serialize_object
    domain = domain.strip()
    if not domain:
        raise AxlError("Enter the gateway name.")
    svc = _service(conn)
    ports: list[dict[str, str]] = []
    for name, (dn, partition) in _endpoint_lines(conn, domain).items():
        try:
            resp = svc.getGatewayEndpointAnalogAccess(name=name)  # no returnedTags: only then is domainName returned
        except Fault:
            continue  # not an analog endpoint
        e = serialize_object(resp["return"]["gatewayEndpointAnalogAccess"])
        if (e.get("domainName") or "").lower() != domain.lower():
            continue  # an endpoint of another gateway with a similar name
        ep = e.get("endpoint") or {}
        index = ep.get("index")
        ports.append({"port": str(int(index) + 1) if index is not None else "", "endpoint": name,
                      "description": _text(ep.get("description")), "dn": dn, "partition": partition,
                      "unit": _text(e.get("unit")), "subunit": _text(e.get("subunit"))})
    if not ports:
        raise AxlError(f"No analog ports were found for gateway {domain}. Check the name.")
    ports.sort(key=lambda p: int(p["port"]) if p["port"].isdigit() else 999)
    return ports


def suggest_rows(domain: str, ports: list[dict[str, str]]) -> list[dict[str, str]]:
    """Editable Webex rows from CUCM ports: include (port 1 and every port with a DN), port, workspace, line."""
    rows = []
    for p in ports:
        n = p["port"] or str(len(rows) + 1)
        rows.append({"include": "1" if n == "1" or p["dn"] else "", "port": n,
                     "workspace": p["description"] or f"{domain} Port {n}", "line": p["dn"]})
    return rows


def _line(raw: str) -> dict[str, str]:
    """'+15551234567' or a long number is a phone number, anything else is an extension."""
    text = raw.strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") or len(digits) >= 10:
        return {"number": text, "extension": ""}
    return {"number": "", "extension": text}


def _members(ids: dict[int, str]) -> dict:
    """PUT members body: workspace of port n on port n, port 1 is the device owner."""
    return {"members": [{"port": n, "id": wid, "primaryOwner": n == 1, "lineType": "PRIMARY", "lineWeight": 1,
                         "hotlineEnabled": False, "hotlineDestination": "", "allowCallDeclineEnabled": True,
                         "t38FaxCompressionEnabled": False}
                        for n, wid in sorted(ids.items())]}


def migrate_gateway(c: WebexClient, gateway: dict, cache: dict[str, str], log=None) -> str:
    """gateway: name, location, add_device (bool), model, mac, use_existing (bool), rows (port, workspace, line, include).

    With use_existing, a workspace that already has the name is not created: it is assigned to the port as it is
    (its calling settings are not changed).

    Everything is checked before the first Webex call. A failure part way leaves what was already created.
    `log` is an optional callable taking one line: each change is logged on its own."""
    say = log or (lambda _msg: None)
    location = gateway.get("location", "").strip()
    if not location:
        raise WebexError("The Webex location is required.")
    chosen = [r for r in gateway["rows"] if r.get("include")]
    ports: dict[int, dict] = {}
    for r in chosen:
        if not r["port"].strip().isdigit() or int(r["port"]) < 1:
            raise WebexError(f"Port '{r['port']}' must be a number from 1.")
        n = int(r["port"])
        if n > MAX_PORTS:
            raise WebexError(f"Port {n} is above the {MAX_PORTS} ports allowed.")
        if n in ports:
            raise WebexError(f"Port {n} is listed more than once.")
        ports[n] = r
    if 1 not in ports:
        raise WebexError("Port 1 must be included: the device is owned by the port 1 workspace.")
    add_device = gateway.get("add_device", False)
    model, mac = gateway.get("model", "").strip(), ""
    if add_device:
        if not (model and gateway.get("mac", "").strip()):
            raise WebexError("The model and the MAC address are required to add the device now.")
        mac = normalize_mac(gateway["mac"])
    location_id = find_location_id(c, location, cache)
    names: set[str] = set()
    bodies: dict[int, dict] = {}
    existing: dict[int, str] = {}
    use_existing = gateway.get("use_existing", False)
    for n in sorted(ports):
        r = ports[n]
        name = r["workspace"].strip()
        if not (name and r["line"].strip()):
            raise WebexError(f"Port {n} needs a workspace name and an extension or a number.")
        if name.lower() in names:
            raise WebexError(f"Workspace {name} is listed more than once.")
        names.add(name.lower())
        if workspace_exists(c, {"workspace": name, "location": location}, cache):
            if not use_existing:
                raise WebexError(f"Workspace {name} already exists in {location}. Tick 'Use an existing workspace' "
                                 "to assign it to port " + f"{n} instead.")
            existing[n] = find_workspace_id(c, name, location_id)
            continue
        bodies[n] = build_workspace_body({"workspace": name, **_line(r["line"])}, location_id)
    added: list[str] = []
    ids: dict[int, str] = {}
    for n in sorted(ports):
        name, line = ports[n]["workspace"].strip(), ports[n]["line"].strip()
        what = f"Port {n} workspace {name} ({line}) in {location}"
        if n in existing:
            ids[n] = existing[n]
            say(f"{what}: assigned existing workspace, nothing changed on it")
            continue
        try:
            ids[n] = create_workspace_adding_number(c, bodies[n], location_id, added, say)
        except WebexError as e:
            say(f"{what}: create failed - {e}")
            raise
        say(f"Port {n} configured with new workspace {name} ({line}) in {location}")
    note = f" Added number(s) to {location}: {', '.join(added)}." if added else ""
    summary = ", ".join(f"port {n} {ports[n]['workspace'].strip()}" + (" (existing)" if n in existing else "")
                        for n in sorted(ports))
    if not add_device:
        say("Device not added (Add Device Later)")
        return (f"Created {len(bodies)} workspace(s), {len(existing)} existing: {summary}.{note} The device was not added. Add it later to the port 1 "
                f"workspace {ports[1]['workspace'].strip()} with Add Device"
                + (", then assign the other ports in Control Hub." if len(ids) > 1 else "."))
    made = c.call("POST", "/devices", body={"mac": mac, "model": model, "workspaceId": ids[1]})
    say(f"Device {model} {mac} added to port 1 workspace {ports[1]['workspace'].strip()}")
    device_id = made.get("id")
    if not device_id:
        raise WebexError(f"The device {mac} was added but Webex did not return its id, so the other ports were "
                         "not assigned.")
    if len(ids) > 1:
        c.call("PUT", f"/telephony/config/devices/{device_id}/members", body=_members(ids))
        for n in sorted(ids):
            say(f"Port {n} of {mac} assigned to workspace {ports[n]['workspace'].strip()}")
    return f"Added {model} {mac} with {len(ids)} port(s): {summary}.{note}"
