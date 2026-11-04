"""CUCM reports: Device Report (registered and unregistered phones and gateways per device pool).

Phones and device pools come from AXL, the registration state from RisPort70 (SelectCmDevice, port 8443, same
credentials), gateway counts from one SQL query. Analog and CTI devices are skipped.
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
_SKIP = ("analog", "cti")
_GATEWAY_SQL = (
    "select dp.name as pool, count(*) as cnt from device d join devicepool dp on dp.pkid = d.fkdevicepool "
    "join typeclass tc on tc.enum = d.tkclass where tc.name = 'Gateway' group by dp.name"
)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def registered_names(conn: CucmConnection, names: list[str]) -> set[str]:
    """Names (upper case) of the phones in `names` that RisPort70 reports as Registered."""
    found: set[str] = set()
    for i in range(0, len(names), RIS_BATCH):
        items = "".join(f"<soap:item><soap:Item>{_xml_escape(n)}</soap:Item></soap:item>"
                        for n in names[i:i + RIS_BATCH])
        body = (
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:soap="http://schemas.cisco.com/ast/soap"><soapenv:Header/><soapenv:Body>'
            "<soap:selectCmDevice><soap:StateInfo></soap:StateInfo><soap:CmSelectionCriteria>"
            f"<soap:MaxReturnedDevices>{RIS_BATCH}</soap:MaxReturnedDevices><soap:DeviceClass>Phone</soap:DeviceClass>"
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


def device_report(conn: CucmConnection, pool_filter: str = "") -> tuple[list[dict[str, str]], int]:
    """([{devicePool, registered, unregistered, total, gateways}], analog/CTI devices skipped).

    `pool_filter` is a case-insensitive "contains" match on the device pool name; blank means every pool."""
    pools = [p["name"] for p in list_paged(conn, "listDevicePool", "devicePool", {"name": "%"}, ["name"])]
    q = pool_filter.strip().lower()
    if q:
        pools = [p for p in pools if q in p.lower()]
    if not pools:
        return [], 0
    wanted = set(pools)
    phones = list_paged(conn, "listPhone", "phone", {"name": "%"}, ["name", "product", "devicePoolName"])
    by_pool: dict[str, list[str]] = {p: [] for p in pools}
    skipped = 0
    for ph in phones:
        if ph["devicePoolName"] not in wanted:
            continue
        product = ph["product"].lower()
        if any(s in product for s in _SKIP):
            skipped += 1
            continue
        by_pool[ph["devicePoolName"]].append(ph["name"])
    reg = registered_names(conn, [n for names in by_pool.values() for n in names])
    gw_count: dict[str, int] = {}
    for r in sql_rows(conn, _GATEWAY_SQL, 2):
        try:
            gw_count[r["pool"]] = int(r["cnt"])
        except (KeyError, ValueError):
            continue
    rows = []
    for p in sorted(pools, key=str.lower):
        names = by_pool[p]
        up = sum(1 for n in names if n.upper() in reg)
        rows.append({"devicePool": p, "registered": str(up), "unregistered": str(len(names) - up),
                     "total": str(len(names)), "gateways": str(gw_count.get(p, 0))})
    return rows, skipped
