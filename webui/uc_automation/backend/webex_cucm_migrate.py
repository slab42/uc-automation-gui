"""Move a physical phone between CUCM and Webex Calling (either direction).

CUCM to Webex: the phone is read from CUCM (it must exist there), then added by MAC to a user of the Webex org.
The CUCM phone is kept. Webex to CUCM: the phone configuration must already exist in CUCM; the phone is deleted
from the Webex org so it can be provisioned by CUCM. Not tested against a real CUCM or Webex org.
"""

from .cucm_axl import AxlError, _call, _text
from .cucm_connections import CucmConnection
from .cucm_devices import format_phone_identifier
from .webex_api import WebexClient, WebexError
from .webex_devices import destination_model, find_device, find_person
from .webex_workspaces import normalize_mac

COLUMNS = ("mac", "user")
# Converts a multiplatform (Webex) phone to Enterprise firmware so CUCM can manage it.
M2E_PROFILE_RULE = "https://cloudupgrader.webex.com/Cisco/M2E/$SWVER/$PN/$MA.cfg"
M2E_STEPS = (f"Then on the phone open http://<phone IP>/admin/advanced, go to Voice > Provisioning, set the Profile "
             f"Rule to {M2E_PROFILE_RULE} and save. The phone reboots and upgrades several times and ends on the "
             "Enterprise firmware.")


def cucm_phone(conn: CucmConnection, mac: str) -> dict[str, str]:
    """name, model, product and owner of the CUCM phone with this MAC. Raises WebexError when it is not there."""
    name = format_phone_identifier(mac)
    try:
        resp = _call(conn, "getPhone", name=name)
    except AxlError as e:
        raise WebexError(f"CUCM phone {name} was not found on {conn.name}: {e}") from e
    from zeep.helpers import serialize_object
    phone = serialize_object(resp["return"]["phone"]) if resp and resp["return"] else None
    if not phone:
        raise WebexError(f"CUCM phone {name} was not found on {conn.name}.")
    return {"name": name, "model": _text(phone.get("model")), "product": _text(phone.get("product")),
            "owner": _text(phone.get("ownerUserName"))}


def _check_cucm_owner(phone: dict[str, str], user: str, conn_name: str) -> None:
    if user and phone["owner"].lower() != user.strip().lower():
        raise WebexError(f"CUCM phone {phone['name']} is owned by '{phone['owner'] or 'nobody'}' on {conn_name}, "
                         f"not {user}.")


def cucm_to_webex(conn: CucmConnection, dst: WebexClient, row: dict[str, str], supported: dict[str, dict],
                  dst_name: str) -> str:
    """row: mac, user (the Webex user, email or display name), from_user (optional CUCM owner to check)."""
    if not (row.get("mac") and row.get("user")):
        raise WebexError("The MAC address and the Webex user are both required.")
    mac = normalize_mac(row["mac"])
    phone = cucm_phone(conn, mac)
    _check_cucm_owner(phone, row.get("from_user", ""), conn.name)
    model = destination_model(supported, phone["model"], phone["product"])
    if find_device(dst, mac) is not None:
        raise WebexError(f"A phone with MAC {mac} is already in {dst_name}.")
    person = find_person(dst, row["user"])
    dst.call("POST", "/devices", body={"mac": mac, "model": model, "personId": person["id"]})
    return (f"Added {phone['product'] or model} {mac} to {row['user']} in {dst_name}. The CUCM phone {phone['name']} "
            f"was kept on {conn.name}. Factory reset the phone so it registers with Webex.")


def webex_to_cucm(conn: CucmConnection, src: WebexClient, row: dict[str, str], src_name: str) -> str:
    """row: mac, user (the CUCM owner to check, optional), from_user (optional Webex owner to check)."""
    if not row.get("mac"):
        raise WebexError("The MAC address is required.")
    mac = normalize_mac(row["mac"])
    phone = cucm_phone(conn, mac)
    _check_cucm_owner(phone, row.get("user", ""), conn.name)
    device = find_device(src, mac)
    if device is None:
        raise WebexError(f"No phone with MAC {mac} was found in {src_name}.")
    if row.get("from_user"):
        owner = find_person(src, row["from_user"])
        if device.get("personId") != owner["id"]:
            raise WebexError(f"The phone {mac} does not belong to {row['from_user']} in {src_name}.")
    src.call("DELETE", f"/devices/{device['id']}")
    return (f"Deleted {device.get('product') or 'phone'} {mac} from {src_name}. Its configuration {phone['name']} "
            f"already exists on {conn.name}. {M2E_STEPS}")
