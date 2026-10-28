"""CUCM tools: Extension Mobility bulk login/logout/check, phone counts by device pool, user PIN.

Modelled on cucm/em_bulk_login.py, cucm/phones_count_by_device_pool.py and cucm/User_set_pin.py.
PINs are secrets: they are sent to CUCM and never logged or returned to the browser.
"""

import csv
import io
import re

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .cucm_axl import AxlError, _fault_message, _service, _text, list_paged
from .cucm_connections import CucmConnection

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EM_PORT = 8080
EM_MODES = {"login": "Log in", "logout": "Log out", "check": "Check sessions"}
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?$")

_session = requests.Session()
_adapter = HTTPAdapter(max_retries=Retry(total=3, status_forcelist=[429, 500, 502, 503, 504],
                                         allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]))
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)


def _read_csv(data: bytes, required: list[str], aliases: dict[str, list[str]] | None = None) -> list[dict[str, str]]:
    """Header based CSV read. `aliases` maps a column to other accepted header names."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    lookup = {(h or "").strip().lower(): h for h in reader.fieldnames}
    cols: dict[str, str | None] = {}
    for col in ["device", "user", "pin"]:
        for name in [col] + (aliases or {}).get(col, []):
            if name in lookup:
                cols[col] = lookup[name]
                break
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError("The CSV needs a header row with these columns: " + ", ".join(required))
    rows = []
    for raw in reader:
        row = {c: (raw.get(h) or "").strip() for c, h in cols.items()}
        if any(row.values()):
            rows.append(row)
    return rows


# --- Extension Mobility ---

def parse_em_csv(data: bytes, mode: str) -> list[dict[str, str]]:
    required = {"login": ["device", "user", "pin"], "logout": ["device"], "check": ["device", "user"]}[mode]
    rows = _read_csv(data, required)
    for r in rows:
        for c in required:
            if not r.get(c):
                raise ValueError(f"A row for device '{r.get('device', '')}' has no {c}.")
    return rows


def check_em_server(server: str) -> str:
    server = server.strip()
    if not _HOST_RE.match(server):
        raise AxlError("Enter the Extension Mobility server as a host name or IP address.")
    return server


def em_request(server: str, mode: str, device: str, user: str = "", pin: str = "") -> str:
    """Call the EM application servlet (login / logout). Returns a detail line; raises AxlError on failure."""
    params = {"device": device}
    if mode == "login":
        params.update({"userid": user, "seq": pin})
    else:
        params["doLogout"] = "true"
    try:
        resp = _session.get(f"http://{server}:{EM_PORT}/emapp/EMAppServlet", params=params, timeout=10)
    except requests.exceptions.Timeout:
        raise AxlError("Timed out")
    except requests.exceptions.ConnectionError:
        raise AxlError(f"Cannot reach {server}:{EM_PORT}")
    if resp.status_code != 200:
        raise AxlError(f"HTTP {resp.status_code}")
    return "Logged in (HTTP 200)" if mode == "login" else "Logged out (HTTP 200)"


def em_check(conn: CucmConnection, device: str, user: str) -> str:
    """Compare the user logged in on the phone (AXL loginUserId) with the expected one."""
    from zeep.exceptions import Fault
    try:
        resp = _service(conn).getPhone(name=device, returnedTags={"name": "", "loginUserId": ""})
    except Fault as e:
        raise AxlError(_fault_message(e))
    logged = _text(resp["return"]["phone"].loginUserId)
    if not logged:
        raise AxlError("No user logged in")
    if logged.lower() != user.lower():
        raise AxlError(f"Wrong user logged in ({logged})")
    return f"Logged in as {logged}"


# --- Phone count by device pool ---

_ANALOG_PRODUCTS = ("gatewayendpointanalogaccess", "analogphone", "analogaccessdevice")


def count_phones_by_pool(conn: CucmConnection, include_analog: bool) -> tuple[list[dict[str, str]], int, int]:
    """([{devicePool, phoneCount}], phones counted, analog/CTI devices excluded)."""
    phones = list_paged(conn, "listPhone", "phone", {"name": "%"}, ["name", "product", "devicePoolName"])
    counts: dict[str, int] = {}
    excluded = 0
    for p in phones:
        product = p["product"].lower()
        if not include_analog and ("analog" in product or "cti" in product or product in _ANALOG_PRODUCTS):
            excluded += 1
            continue
        pool = p["devicePoolName"] or "Unknown/Unassigned"
        counts[pool] = counts.get(pool, 0) + 1
    rows = [{"devicePool": k, "phoneCount": str(v)} for k, v in sorted(counts.items(), key=lambda kv: kv[0].lower())]
    return rows, sum(counts.values()), excluded


# --- User PIN ---

def parse_pin_csv(data: bytes) -> list[dict[str, str]]:
    rows = _read_csv(data, ["user", "pin"], {"user": ["userid", "user id", "username"]})
    for r in rows:
        if not r.get("user") or not r.get("pin"):
            raise ValueError(f"A row for user '{r.get('user', '')}' is missing the user or the pin.")
    return rows


def set_user_pin(conn: CucmConnection, user: str, pin: str) -> None:
    from zeep.exceptions import Fault
    if not user or not pin:
        raise AxlError("user and pin are required")
    try:
        _service(conn).updateUser(userid=user, pin=pin)
    except Fault as e:
        raise AxlError(_fault_message(e))
