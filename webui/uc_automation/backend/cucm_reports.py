"""CUCM reports: Device Report (registered and unregistered phones and gateways per device pool).

Device pools, device counts and gateway counts come from SQL (one query per kind of device, only for the kinds
selected), the registration state from RisPort70 (SelectCmDevice, port 8443, same credentials) and only when asked for.
"""

import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable

import requests
import urllib3
from requests.auth import HTTPBasicAuth

from .cucm_axl import AxlError, list_paged, sql_rows
from .cucm_connections import CucmConnection

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

RIS_BATCH = 1000   # RisPort70 returns at most 1000 devices per request
RIS_URL = "https://{server}:8443/realtimeservice2/services/RISService70"
RIS_MIN_INTERVAL = 4.2   # RisPort70 allows 15 requests per minute per node
RATE_WAIT = 60           # seconds to wait when RisPort70 still reports the rate limit
RATE_RETRIES = 3
_ris_lock = threading.Lock()
_ris_last: dict[str, float] = {}
KINDS = ["Phones", "Analog Phones", "CTI Devices", "Gateways", "SIP Trunks"]
COUNT_ONLY = ("Gateways", "SIP Trunks")   # counted per pool, not part of the device total or registration
_DEVICE_SQL = (
    "select dp.name as pool, d.name as name, tm.name as model from device d "
    "join devicepool dp on dp.pkid = d.fkdevicepool join typeclass tc on tc.enum = d.tkclass "
    "join typemodel tm on tm.enum = d.tkmodel where tc.name = 'Phone'"
)
_COUNT_SQL = (
    "select dp.name as pool, count(*) as cnt from device d join devicepool dp on dp.pkid = d.fkdevicepool "
    "join typeclass tc on tc.enum = d.tkclass where tc.name = '{cls}' group by dp.name"
)
_COUNT_CLASS = {"Gateways": "Gateway", "SIP Trunks": "Trunk"}


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class RateLimited(AxlError):
    """RisPort70 kept refusing requests after every retry."""


def _throttle(server: str) -> None:
    """Block until at least RIS_MIN_INTERVAL seconds have passed since the last RIS call to `server`."""
    with _ris_lock:
        wait = _ris_last.get(server, 0.0) + RIS_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _ris_last[server] = time.monotonic()


def _ris_call(conn: CucmConnection, body: str) -> ET.Element:
    """One selectCmDevice call, paced, retried when RisPort70 reports the rate limit. Returns the parsed response."""
    for attempt in range(RATE_RETRIES + 1):
        _throttle(conn.server)
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
        if fault is None:
            return root
        text = fault.text or "fault"
        if "exceeded allowed rate" not in text.lower():
            raise AxlError(f"RisPort70: {text}")
        if attempt == RATE_RETRIES:
            raise RateLimited(f"RisPort70: {text}")
        time.sleep(RATE_WAIT)
    raise RateLimited("RisPort70: rate limit")  # not reached


def registered_names(conn: CucmConnection, names: list[str], device_class: str = "Phone",
                     progress: Callable[[str], None] | None = None) -> tuple[set[str], bool]:
    """(names in `names` (upper case) that RisPort70 reports as Registered, complete).

    Calls are paced under RisPort70's 15 per minute limit. If the limit still blocks a batch after the retries,
    the names found so far are returned with complete False. `progress` gets a status line per batch."""
    found: set[str] = set()
    total = max(1, -(-len(names) // RIS_BATCH))
    for n_batch, i in enumerate(range(0, len(names), RIS_BATCH), 1):
        if progress:
            minutes = max(1, round((total - n_batch + 1) * RIS_MIN_INTERVAL / 60))
            progress(f"Reading registration, batch {n_batch} of {total} (about {minutes} min left)")
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
            root = _ris_call(conn, body)
        except RateLimited:
            if n_batch == 1:
                raise
            return found, False
        for el in root.iter():
            if el.tag.split("}")[-1] == "Name" and el.text:
                found.add(el.text.strip().upper())
    return found, True


def active_loads(conn: CucmConnection, names: list[str], device_class: str = "Phone") -> dict[str, str]:
    """{device name (upper case): Active Load ID} from RisPort70 for the devices it knows (registered ones)."""
    out: dict[str, str] = {}
    for i in range(0, len(names), RIS_BATCH):
        items = "".join(f"<soap:item><soap:Item>{_xml_escape(n)}</soap:Item></soap:item>"
                        for n in names[i:i + RIS_BATCH])
        body = (
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:soap="http://schemas.cisco.com/ast/soap"><soapenv:Header/><soapenv:Body>'
            "<soap:selectCmDevice><soap:StateInfo></soap:StateInfo><soap:CmSelectionCriteria>"
            f"<soap:MaxReturnedDevices>{RIS_BATCH}</soap:MaxReturnedDevices><soap:DeviceClass>{device_class}</soap:DeviceClass>"
            "<soap:Model>255</soap:Model><soap:Status>Any</soap:Status><soap:NodeName></soap:NodeName>"
            f"<soap:SelectBy>Name</soap:SelectBy><soap:SelectItems>{items}</soap:SelectItems>"
            "<soap:Protocol>Any</soap:Protocol><soap:DownloadStatus>Any</soap:DownloadStatus>"
            "</soap:CmSelectionCriteria></soap:selectCmDevice></soapenv:Body></soapenv:Envelope>"
        )
        root = _ris_call(conn, body)
        for el in root.iter():
            if el.tag.split("}")[-1] != "item":
                continue
            kids = {c.tag.split("}")[-1]: (c.text or "").strip() for c in el}
            if kids.get("Name") and kids.get("ActiveLoadID"):
                out[kids["Name"].upper()] = kids["ActiveLoadID"]
    return out


def _kind(model: str) -> str:
    m = model.lower()
    return "Analog Phones" if "analog" in m else "CTI Devices" if "cti" in m else "Phones"


def device_report(conn: CucmConnection, pool_filter: str = "", kinds: list[str] | None = None,
                  registration: bool = True, progress: Callable[[str], None] | None = None
                  ) -> tuple[list[dict[str, str]], bool]:
    """([{devicePool, registered, unregistered, total, gateways, trunks}], registration complete) for the selected kinds.

    When registration is incomplete (RisPort70 rate limit), registered holds the count found so far and
    unregistered is blank.

    `pool_filter` is a case-insensitive "contains" match on the device pool name; blank means every pool.
    `kinds` is a subset of KINDS (default all). Registration is only read when `registration` is true and a
    non-gateway kind is selected; otherwise registered and unregistered are blank."""
    kinds = list(KINDS if kinds is None else kinds)
    q = pool_filter.strip().lower()
    want_dev = [k for k in kinds if k not in COUNT_ONLY]
    pools = [p["name"] for p in list_paged(conn, "listDevicePool", "devicePool", {"name": "%"}, ["name"])]
    if q:
        pools = [p for p in pools if q in p.lower()]
    if not pools:
        return [], True
    wanted = set(pools)
    by_pool: dict[str, list[str]] = {p: [] for p in pools}
    if want_dev:
        for d in sql_rows(conn, _DEVICE_SQL, 3):
            if d.get("pool") in wanted and _kind(d.get("model", "")) in want_dev:
                by_pool[d["pool"]].append(d["name"])
    reg: set[str] = set()
    complete = True
    do_reg = registration and bool(want_dev)
    if do_reg:
        names = [n for v in by_pool.values() for n in v]
        reg, complete = registered_names(conn, names, "Any" if "CTI Devices" in want_dev else "Phone", progress)
    counts: dict[str, dict[str, int]] = {}
    for kind in COUNT_ONLY:
        counts[kind] = {}
        if kind in kinds:
            for r in sql_rows(conn, _COUNT_SQL.format(cls=_COUNT_CLASS[kind]), 2):
                try:
                    counts[kind][r["pool"]] = int(r["cnt"])
                except (KeyError, ValueError):
                    continue
    rows = []
    for p in sorted(pools, key=str.lower):
        names = by_pool[p]
        up = sum(1 for n in names if n.upper() in reg)
        rows.append({"devicePool": p, "registered": str(up) if do_reg else "", "unregistered": str(len(names) - up) if do_reg and complete else "",
                     "total": str(len(names)),
                     "gateways": str(counts["Gateways"].get(p, 0)) if "Gateways" in kinds else "",
                     "trunks": str(counts["SIP Trunks"].get(p, 0)) if "SIP Trunks" in kinds else ""})
    return rows, complete


def pool_group_key(name: str, mode: str, delimiter: str = "-", parts: int = 2, pattern: str = "") -> str:
    """Consolidation key for a device pool name; a name that does not fit the scheme is its own group.

    "Prefix": the first `parts` delimiter-separated parts plus a trailing delimiter ("AGY-SITE-Phones" -> "AGY-SITE-").
    "Regex": the first capture group (or the whole match) of `pattern`, matched from the start, case-insensitive."""
    if mode == "Prefix" and delimiter and parts > 0:
        bits = name.split(delimiter)
        return delimiter.join(bits[:parts]) + delimiter if len(bits) > parts else name
    if mode == "Regex" and pattern:
        m = re.match(pattern, name, re.IGNORECASE)
        if m:
            return (m.group(1) if m.re.groups else m.group(0)) or name
    return name


def consolidate_rows(rows: list[dict[str, str]], key: Callable[[str], str]) -> list[dict[str, str]]:
    """Merge device report rows whose pool names share a key; counts are summed (blank stays blank)
    and `pools` holds how many device pools were merged."""
    groups: dict[str, list[dict[str, str]]] = {}
    for x in rows:
        groups.setdefault(key(x["devicePool"]), []).append(x)
    out = []
    for k in sorted(groups, key=str.lower):
        g = groups[k]
        row = {"devicePool": k, "pools": str(len(g))}
        for f in ("registered", "unregistered", "total", "gateways", "trunks"):
            row[f] = str(sum(int(x[f]) for x in g)) if g[0][f] != "" else ""
        out.append(row)
    return out
