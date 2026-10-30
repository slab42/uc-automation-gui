"""RedSky Tracking: BSSID, LLDP, Private IP and Public IP. Each entry ties a network clue to a Location."""

from .redsky_api import RedskyClient, RedskyError
from .redsky_common import LOCATION_HELP, AddSpec, Field, location_choices, location_map, parse_bool, resolve_location


def _location_lookup(client: RedskyClient) -> dict[str, list[str]]:
    return {"locations": location_choices(client)}


def _locations(client: RedskyClient) -> dict[str, str | None]:
    return location_map(client)


_LOC = Field("location", "Location", LOCATION_HELP, required=True, options="locations")


def _add_bssid(client: RedskyClient, locations, row: dict[str, str]) -> str:
    location_id = resolve_location(locations, row["location"])
    return client.add_bssid(row["bssid"], location_id, row["description"], parse_bool(row["masking"]))[1]


BSSID = AddSpec(
    slug="bssid", title="BSSID", noun="BSSID",
    blurb="Add wireless access point BSSIDs and tie each to a Location. A client that sees the BSSID is placed "
          "at that Location.",
    fields=(
        Field("bssid", "BSSID", "Access point MAC address, e.g. 00:1A:2B:3C:4D:5E.", required=True),
        _LOC,
        Field("description", "Description"),
        Field("masking", "BSSID masking", "Leave Not Set to not send it.", yesno=True, default="Not Set"),
    ),
    add=_add_bssid, prepare=_locations, lookups=_location_lookup,
    csv_note="description and masking are optional. masking accepts yes/no/true/false/1/0; blank leaves it unset.",
    example="bssid,location,description,masking\n00:1A:2B:3C:4D:5E,HQ Building / Room 101,AP-101,yes\n",
)


def _prepare_lldp(client: RedskyClient) -> dict:
    return {"locations": location_map(client), "switches": _switch_ids(client)}


def _switch_ids(client: RedskyClient) -> dict[str, str]:
    return {sw.get("chassisId", "").strip().lower(): sw["id"] for sw in client.list_network_switches()}


def _add_lldp(client: RedskyClient, ctx: dict, row: dict[str, str]) -> str:
    """A blank portId adds the chassis; otherwise the port, creating its chassis first when it is not in RedSky."""
    location_id = resolve_location(ctx["locations"], row["location"])
    chassis, port, key = row["chassisId"], row["portId"], row["chassisId"].lower()
    switches = ctx["switches"]
    if not port:
        new_id, detail = client.add_network_switch(chassis, location_id, row["description"])
        if new_id:
            switches[key] = new_id
        return detail
    note = ""
    if key not in switches:
        new_id, _ = client.add_network_switch(chassis)
        if new_id:
            switches[key] = new_id
        else:
            switches.update(_switch_ids(client))
        if key not in switches:
            raise RedskyError(f"{chassis}: unable to determine the new chassis id")
        note = f" (chassis {chassis} was not in RedSky and was created first)"
    return client.add_network_switch_port(port, switches[key], location_id, row["description"])[1] + note


LLDP = AddSpec(
    slug="lldp", title="LLDP", noun="LLDP entry",
    blurb="Add LLDP switches (chassis) and switch ports. A client whose LLDP data matches a chassis (and port) is "
          "placed at the Location tied to it.",
    fields=(
        Field("chassisId", "Chassis ID", "The switch LLDP chassis ID (usually its base MAC address).", required=True),
        Field("portId", "Port ID", "Blank adds the chassis itself; a port (e.g. Gi1/0/1) adds that port."),
        _LOC,
        Field("description", "Description"),
    ),
    add=_add_lldp, prepare=_prepare_lldp, lookups=_location_lookup, label_keys=("chassisId", "portId"),
    csv_note="A row with a blank portId adds the chassis. A row with a portId adds that port; if the chassis is not "
             "in RedSky yet it is created first with no Location of its own. Put chassis rows before their port rows.",
    example="chassisId,portId,location,description\n"
            "00:1A:2B:3C:4D:5E,,HQ Building / IDF 1,Floor 1 switch\n"
            "00:1A:2B:3C:4D:5E,Gi1/0/1,HQ Building / Room 101,Desk jack 101-A\n",
)


def _add_private_ip(client: RedskyClient, locations, row: dict[str, str]) -> str:
    location_id = resolve_location(locations, row["location"])
    return client.add_ip_range(row["ipAddressLow"], row["ipAddressHigh"], location_id, row["description"])[1]


PRIVATE_IP = AddSpec(
    slug="private-ip", title="Private IP", noun="private IP range",
    blurb="Add private IP ranges and tie each to a Location. A client whose address falls in the range is placed "
          "at that Location.",
    fields=(
        Field("ipAddressLow", "IP address low", "First address in the range.", required=True),
        Field("ipAddressHigh", "IP address high", "Last address (same as low for one address).", required=True),
        _LOC,
        Field("description", "Description"),
    ),
    add=_add_private_ip, prepare=_locations, lookups=_location_lookup, label_keys=("ipAddressLow", "ipAddressHigh"),
    csv_note="description is optional.",
    example="ipAddressLow,ipAddressHigh,location,description\n"
            "10.10.1.0,10.10.1.255,HQ Building / Room 101,Floor 1 data VLAN\n",
)


def _add_public_ip(client: RedskyClient, _ctx, row: dict[str, str]) -> str:
    return client.add_public_ip_range(row["ipAddressLow"], row["ipAddressHigh"], row["description"])[1]


PUBLIC_IP = AddSpec(
    slug="public-ip", title="Public IP", noun="public IP range",
    blurb="Add public (trusted) IP ranges, such as the customer's internet egress addresses.",
    fields=(
        Field("ipAddressLow", "IP address low", "First address in the range.", required=True),
        Field("ipAddressHigh", "IP address high", "Last address (same as low for one address).", required=True),
        Field("description", "Description"),
    ),
    add=_add_public_ip, label_keys=("ipAddressLow", "ipAddressHigh"),
    csv_note="description is optional.",
    example="ipAddressLow,ipAddressHigh,description\n203.0.113.0,203.0.113.255,HQ internet egress\n",
)
