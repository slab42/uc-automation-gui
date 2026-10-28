"""Shared AXL plumbing for the web UI: errors, schema/version handling, the cached zeep client, paged lists,
SQL rows and small call helpers. Resource operations live in the cucm_<area>.py modules.

Written for this app (the CLI scripts in cucm/ were used as reference only). The
WSDL files live in the webui under schemas/cucm/<version>/.
"""

import re
import threading
from xml.etree import ElementTree as ET

import requests
import urllib3
from requests.auth import HTTPBasicAuth

from .cucm_connections import CucmConnection
from .paths import CUCM_SCHEMA_DIR

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)")


class AxlError(Exception):
    pass


def available_schemas() -> list[str]:
    """Numeric schema folders (8.5 ... 15.0), ascending. 'current' is excluded."""
    found = [p.name for p in CUCM_SCHEMA_DIR.iterdir()
             if p.is_dir() and _VERSION_RE.match(p.name) and (p / "AXLAPI.wsdl").exists()]
    return sorted(found, key=lambda v: tuple(int(x) for x in v.split(".")))


def pick_schema(major: str) -> str:
    """Exact schema folder for the release, else the closest older one, else the oldest."""
    schemas = available_schemas()
    if not schemas:
        raise AxlError(f"No AXL schema folders found in {CUCM_SCHEMA_DIR}")
    if major in schemas:
        return major
    key = tuple(int(x) for x in major.split("."))
    older = [s for s in schemas if tuple(int(x) for x in s.split(".")) <= key]
    return older[-1] if older else schemas[0]


def _soap(server: str, username: str, password: str, body: str, ns_version: str, timeout: int = 15) -> ET.Element:
    envelope = (
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:ns="http://www.cisco.com/AXL/API/{ns_version}"><soapenv:Header/>'
        f"<soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>"
    )
    try:
        resp = requests.post(
            f"https://{server}:8443/axl/", data=envelope.encode(), timeout=timeout, verify=False,
            auth=HTTPBasicAuth(username, password),
            headers={"Content-Type": "text/xml", "SOAPAction": f'"CUCM:DB ver={ns_version}"'},
        )
    except requests.exceptions.SSLError as e:
        raise AxlError(f"TLS error talking to {server}: {e}")
    except requests.exceptions.ConnectTimeout:
        raise AxlError(f"Timed out connecting to {server}:8443")
    except requests.exceptions.ConnectionError as e:
        raise AxlError(f"Cannot reach {server}:8443 ({e.__class__.__name__})")
    if resp.status_code == 401:
        raise AxlError("Authentication failed (401). Check the username and password.")
    if resp.status_code == 403:
        raise AxlError("Access denied (403). The account needs the Standard AXL API Access role.")
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        raise AxlError(f"Unexpected response from {server} (HTTP {resp.status_code}). Is AXL enabled?")
    fault = root.find(".//faultstring")
    if fault is not None:
        raise AxlError(fault.text or "AXL fault")
    return root


def detect_version(server: str, username: str, password: str) -> tuple[str, str]:
    """Return (full version string, schema major like '15.0') via getCCMVersion.

    The AXL namespace 1.0 means "whatever release the server runs"; fall back to
    trying known releases newest first if the server refuses it.
    """
    body = "<ns:getCCMVersion/>"
    last: AxlError | None = None
    for ns in ["1.0"] + list(reversed(available_schemas())):
        try:
            root = _soap(server, username, password, body, ns)
        except AxlError as e:
            msg = str(e).lower()
            if "authentication" in msg or "denied" in msg or "reach" in msg or "timed out" in msg or "tls" in msg:
                raise
            last = e
            continue
        node = root.find(".//version")
        full = (node.text or "").strip() if node is not None else ""
        m = _VERSION_RE.match(full)
        if not m:
            raise AxlError(f"CUCM did not return a recognizable version ({full or 'empty'})")
        return full, f"{m.group(1)}.{m.group(2)}"
    raise last or AxlError("Could not determine CUCM version")


# --- zeep client (built lazily and cached: parsing a CUCM WSDL takes seconds) ---

_clients: dict[tuple, object] = {}
_lock = threading.Lock()


def _service(conn: CucmConnection):
    from zeep import Client, Settings
    from zeep.transports import Transport
    from requests import Session

    schema = conn.schema_version or pick_schema(conn.version or available_schemas()[-1])
    key = (conn.server, conn.username, schema)
    with _lock:
        svc = _clients.get(key)
        if svc is None:
            session = Session()
            session.verify = False
            session.auth = HTTPBasicAuth(conn.username, conn.password)
            client = Client(
                wsdl=(CUCM_SCHEMA_DIR / schema / "AXLAPI.wsdl").as_uri(),
                transport=Transport(session=session, timeout=30),
                settings=Settings(strict=False, xml_huge_tree=True),
            )
            svc = client.create_service(
                "{http://www.cisco.com/AXLAPIService/}AXLAPIBinding", f"https://{conn.server}:8443/axl/")
            _clients[key] = svc
    return svc


def forget(server: str) -> None:
    """Drop cached clients for a server (after credentials change)."""
    with _lock:
        for k in [k for k in _clients if k[0] == server]:
            del _clients[k]


def _fault_message(e: Exception) -> str:
    return getattr(e, "message", None) or str(e)


def _text(value) -> str:
    """AXL returns reference fields (device pool, CSS, ...) as {'_value_1': name, 'uuid': ...}."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return _text(value.get("_value_1"))
    if hasattr(value, "_value_1"):  # zeep object (not yet serialized)
        return _text(value._value_1)
    return str(value)


def _call(conn: CucmConnection, op: str, **kwargs):
    """Call one AXL operation by name, turning a zeep Fault into AxlError."""
    from zeep.exceptions import Fault
    try:
        return getattr(_service(conn), op)(**kwargs)
    except Fault as e:
        raise AxlError(_fault_message(e))


def _non_blank(r: dict[str, str], skip: tuple[str, ...] = ()) -> dict[str, str]:
    """The entries of a form row that have a value (blank cells mean "leave unchanged / use default")."""
    return {k: v for k, v in r.items() if v and k not in skip}


def list_paged(conn: CucmConnection, op: str, result_key: str, search: dict, tags: list[str],
               page: int = 500) -> list[dict[str, str]]:
    """Run an AXL list call page by page (AXL refuses unpaged lists over 1000 rows)."""
    from zeep.exceptions import Fault
    from zeep.helpers import serialize_object
    svc = _service(conn)
    rows: list[dict] = []
    skip = 0
    while True:
        try:
            resp = getattr(svc, op)(searchCriteria=search, returnedTags={t: "" for t in tags},
                                    skip=skip, first=page)
        except Fault as e:
            raise AxlError(_fault_message(e))
        data = serialize_object(resp["return"]) if resp["return"] is not None else {}
        batch = (data or {}).get(result_key) or []
        rows.extend(batch)
        if len(batch) < page:
            break
        skip += page
    return [{t: _text(r.get(t)) for t in tags} for r in rows]


def sql_rows(conn: CucmConnection, query: str, columns: int) -> list[dict[str, str]]:
    """Run executeSQLQuery. Use only where AXL has no list/get call (dependency checks).

    AXL returns each column as its own element; `columns` is how many the query selects, so the flat
    sequence can be cut back into rows. Values are text, NULL becomes "".
    """
    from zeep.exceptions import Fault
    try:
        resp = _service(conn).executeSQLQuery(sql=query)
    except Fault as e:
        raise AxlError(_fault_message(e))
    ret = resp["return"]
    raw = None if ret is None else ret["row"]
    if raw is None:
        return []
    cells: list[tuple[str, str]] = []

    def collect(item):
        if isinstance(item, (list, tuple)):
            for x in item:
                collect(x)
        elif isinstance(item, dict):
            cells.extend((k.split("}")[-1], "" if v is None else str(v)) for k, v in item.items())
        elif hasattr(item, "tag"):
            kids = list(item)
            if kids and columns > 1 and len(kids) >= columns:   # a whole <row> element
                for k in kids:
                    cells.append((k.tag.split("}")[-1], k.text or ""))
            else:
                cells.append((item.tag.split("}")[-1], item.text or ""))

    collect(raw)
    return [dict(cells[i:i + columns]) for i in range(0, len(cells) - columns + 1, columns)]


def sql_quote(value: str) -> str:
    return value.replace("'", "''")
