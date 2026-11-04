"""CUCM reports: Device Report (registered and unregistered phones and gateways per device pool).

Device pools, device counts and gateway counts come from SQL (one query per kind of device, only for the kinds
selected), the registration state from RisPort70 (SelectCmDevice, port 8443, same credentials) and only when asked for.
"""

import xml.etree.ElementTree as ET

import requests
import urllib3
from requests.auth import HTTPBasicAuth

from .cucm_axl import AxlError, list_paged, sql_rows
from .cucm_connections import CucmConnection

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

RIS_BATCH = 1000   # RisPort70 returns at most 1000 devices per request
RIS_URL = "https://{server}:8443/realtimeservice2/services/RISService70"
KINDS = ["Phones", "Analog Phones", "CTI Devices", "Gateways"]
_DEVICE_SQL = (
    "select dp.name as pool, d.name as name, tm.name as model from device d "
    "join devicepool dp on dp.pkid = d.fkdevicepool join typeclass tc on tc.enum = d.tkclass "
    "join typemodel tm on tm.enum = d.tkmodel where tc.name = 'Phone'"
)
_GATEWAY_SQL = (
    "select dp.name as pool, count(*) as cnt from device d join devicepool dp on dp.pkid = d.fkdevicepool "
    "join typeclass tc on tc.enum = d.tkclass where tc.name = 'Gateway' group by dp.name"
)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def registered_names(conn: CucmConnection, names: list[str], device_class: str = "Phone") -> set[str]:
    """Names (upper case) of the devices in `names` that RisPort70 reports as Registered."""
    found: set[str] = set()
    for i in range(0, len(names), RIS_BATCH):
        items = "".join(f"<soap:item><soap:Item>{_xml_escape(n)}</soap:Item></soap:item>"
                        for n in names[i:i + RIS_BATCH])
        body = (
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:soap="http://schemas.cisco.com/ast/soap"><soapenv:Header/><soapenv:Body>'
            "<soap:selectCmDevice><soap:StateInfo></soap:StateInfo><soap:CmSelectionCriteria>"
            f"<soap:MaxReturnedDevices>{RIS_BATCH}</soap:MaxReturnedDevices><soap:DeviceClass>{device_class}</soap:DeviceClass>"
            "<soap:Model>255</soap:Model><soap:Status>Registered</soap:Status><soap:NodeName></soap:NodeName>"
            f"<soap:SelectBy>Name</soap:SelectBy><soap:SelectItems>{items}</soap:SelectItems>"
            "<soap:Protocol>Any</soap:Protocol><soap:DownloadStatus>Any</soap:DownloadStatus>"
            "</soap:CmSelectionCriteria></soap:selectCmDevice></soapenv:Body></soapenv:Envelope>"
        )
        try:
            resp = requests.post(RIS_URL.format(server=conn.server), data=body.encode(), timeout=60, verify=False,
                                 auth=HTTPBasicAuth(conn.username, conn.password),
                                 headers={"Content-Type": "text/xml", "SOAPAction": '"selectCmDevice"'})
        except requests.exceptions.Timeout:
            raise AxlError(f"Timed out reading registration from {conn.server}:8443")
        except requests.RequestException as e:
            raise AxlError(f"Cannot read registration from {conn.server}:8443 ({e.__class__.__name__})")
        if resp.status_code == 401:
            raise AxlError("Registration lookup failed (401). Check the username and password.")
        if resp.status_code == 403:
            raise AxlError("Registration lookup denied (403). The account needs the Standard RealtimeAndTraceCollection role.")
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            raise AxlError(f"Unexpected RisPort70 response from {conn.server} (HTTP {resp.status_code}).")
        fault = root.find(".//faultstring")
        if fault is not None:
            raise AxlError(f"RisPort70: {fault.text or 'fault'}")
        for el in root.iter():
            if el.tag.split("}")[-1] == "Name" and el.text:
                found.add(el.text.strip().upper())
    return found


def _kind(model: str) -> str:
    m = model.lower()
    return "Analog Phones" if "analog" in m else "CTI Devices" if "cti" in m else "Phones"


def device_report(conn: CucmConnection, pool_filter: str = "", kinds: list[str] | None = None,
                  registration: bool = True) -> list[dict[str, str]]:
    """[{devicePool, registered, unregistered, total, gateways}] for the selected kinds of device.

    `pool_filter` is a case-insensitive "contains" match on the device pool name; blank means every pool.
    `kinds` is a subset of KINDS (default all). Registration is only read when `registration` is true and a
    non-gateway kind is selected; otherwise registered and unregistered are blank."""
    kinds = list(KINDS if kinds is None else kinds)
    q = pool_filter.strip().lower()
    want_dev = [k for k in kinds if k != "Gateways"]
    pools = [p["name"] for p in list_paged(conn, "listDevicePool", "devicePool", {"name": "%"}, ["name"])]
    if q:
        pools = [p for p in pools if q in p.lower()]
    if not pools:
        return []
    wanted = set(pools)
    by_pool: dict[str, list[str]] = {p: [] for p in pools}
    if want_dev:
        for d in sql_rows(conn, _DEVICE_SQL, 3):
            if d.get("pool") in wanted and _kind(d.get("model", "")) in want_dev:
                by_pool[d["pool"]].append(d["name"])
    reg: set[str] = set()
    do_reg = registration and bool(want_dev)
    if do_reg:
        names = [n for v in by_pool.values() for n in v]
        reg = registered_names(conn, names, "Any" if "CTI Devices" in want_dev else "Phone")
    gw_count: dict[str, int] = {}
    if "Gateways" in kinds:
        for r in sql_rows(conn, _GATEWAY_SQL, 2):
            try:
                gw_count[r["pool"]] = int(r["cnt"])
            except (KeyError, ValueError):
                continue
    rows = []
    for p in sorted(pools, key=str.lower):
        names = by_pool[p]
        up = sum(1 for n in names if n.upper() in reg)
        rows.append({"devicePool": p, "registered": str(up) if do_reg else "", "unregistered": str(len(names) - up) if do_reg else "",
                     "total": str(len(names)), "gateways": str(gw_count.get(p, 0))})
    return rows
