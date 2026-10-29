"""Shared CUC REST (vmrest) plumbing for the web UI: errors, schema/version handling.

Written for this app (cuc/cucAPI.py was used as reference only). The REST schema
artifacts live in the webui under schemas/cuc/<version>/.
"""

import re
from xml.etree import ElementTree as ET

import requests
import urllib3
from requests.auth import HTTPBasicAuth

from .errors import UserError
from .paths import CUC_SCHEMA_DIR

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)")


class CucError(UserError):
    pass


def available_schemas() -> list[str]:
    """Numeric schema folders (15.0 ...), ascending."""
    found = [p.name for p in CUC_SCHEMA_DIR.iterdir()
             if p.is_dir() and _VERSION_RE.match(p.name) and (p / "application.wadl").exists()]
    return sorted(found, key=lambda v: tuple(int(x) for x in v.split(".")))


def pick_schema(major: str) -> str:
    """Exact schema folder for the release, else the closest older one, else the oldest."""
    schemas = available_schemas()
    if not schemas:
        raise CucError(f"No CUC schema folders found in {CUC_SCHEMA_DIR}")
    if major in schemas:
        return major
    key = tuple(int(x) for x in major.split("."))
    older = [s for s in schemas if tuple(int(x) for x in s.split(".")) <= key]
    return older[-1] if older else schemas[0]


def detect_version(server: str, username: str, password: str, timeout: int = 15) -> tuple[str, str]:
    """Return (full version string, schema major like '15.0') via GET /vmrest/version."""
    try:
        resp = requests.get(
            f"https://{server}/vmrest/version", timeout=timeout, verify=False,
            auth=HTTPBasicAuth(username, password), headers={"Accept": "application/xml"},
        )
    except requests.exceptions.SSLError as e:
        raise CucError(f"TLS error talking to {server}: {e}")
    except requests.exceptions.ConnectTimeout:
        raise CucError(f"Timed out connecting to {server}")
    except requests.exceptions.ConnectionError as e:
        raise CucError(f"Cannot reach {server} ({e.__class__.__name__})")
    if resp.status_code == 401:
        raise CucError("Authentication failed (401). Check the username and password.")
    if resp.status_code == 403:
        raise CucError("Access denied (403). The account needs an administrator role.")
    if resp.status_code != 200:
        raise CucError(f"Unexpected response from {server} (HTTP {resp.status_code}). Is this a Unity Connection server?")
    try:
        node = ET.fromstring(resp.content).find(".//version")
    except ET.ParseError:
        raise CucError(f"Unexpected response from {server}. Is this a Unity Connection server?")
    full = (node.text or "").strip() if node is not None else ""
    m = _VERSION_RE.match(full)
    if not m:
        raise CucError(f"CUC did not return a recognizable version ({full or 'empty'})")
    return full, f"{m.group(1)}.{m.group(2)}"


# --- REST client ---

DEFAULT_PAGE_SIZE = 2000
DEFAULT_TIMEOUT = 60
_OBJECT_ID_RE = re.compile(r"^[0-9A-Fa-f-]{20,40}$")
_EXTENSION_RE = re.compile(r"^[0-9A-Za-z+*#_.-]{1,40}$")


def element_to_dict(element: ET.Element) -> dict[str, str]:
    """{child.tag: child.text} for the direct children of an element."""
    return {child.tag: (child.text or "").strip() for child in element}


class CucClient:
    """One CUC server: basic auth, XML, GET retries, paging. Every failure raises CucError."""

    def __init__(self, conn, timeout: int = DEFAULT_TIMEOUT, page_size: int = DEFAULT_PAGE_SIZE):
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        self.server = conn.server
        self.timeout = timeout
        self.page_size = page_size
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(conn.username, conn.password)
        self.session.verify = False
        self.session.headers.update({"Accept": "application/xml"})
        retry = Retry(total=4, connect=4, read=4, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset(["GET"]), respect_retry_after_header=True)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        if path.startswith("/vmrest"):
            return f"https://{self.server}{path}"
        return f"https://{self.server}/vmrest/{path.lstrip('/')}"

    def _fail(self, resp) -> CucError:
        if resp.status_code == 401:
            return CucError("Authentication failed (401). Check the username and password.")
        if resp.status_code == 403:
            return CucError("Access denied (403). The account needs an administrator role.")
        if resp.status_code == 404:
            return CucError("Not found (404). It may already have been deleted.")
        return CucError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    def get(self, path: str, params: dict | None = None) -> ET.Element:
        try:
            resp = self.session.get(self._url(path), params=params, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise CucError(f"Cannot reach {self.server} ({e.__class__.__name__})")
        if not resp.ok:
            raise self._fail(resp)
        try:
            return ET.fromstring(resp.content)
        except ET.ParseError:
            raise CucError(f"Unexpected response from {self.server}")

    def delete(self, path: str) -> None:
        try:
            resp = self.session.delete(self._url(path), timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise CucError(f"Cannot reach {self.server} ({e.__class__.__name__})")
        if resp.status_code not in (200, 204):
            raise self._fail(resp)

    def get_paged(self, path: str, tag: str, params: dict | None = None) -> list[dict[str, str]]:
        """Every page of a list resource as dicts, de-duplicated on ObjectId."""
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        page = 1
        total = None
        while True:
            root = self.get(path, {**(params or {}), "rowsPerPage": self.page_size, "pageNumber": page})
            if total is None:
                t = root.get("total")
                total = int(t) if t and t.isdigit() else None
            elements = root.findall(f".//{tag}")
            if not elements:
                break
            new = 0
            for el in elements:
                item = element_to_dict(el)
                oid = item.get("ObjectId", "")
                if oid:
                    if oid in seen:
                        continue
                    seen.add(oid)
                    new += 1
                items.append(item)
            if len(elements) < self.page_size or (total is not None and len(items) >= total):
                break
            if new == 0:
                raise CucError("The server repeated a page; paging is not honored.")
            page += 1
        return items

    # --- users / mailboxes ---

    def find_user(self, extension: str) -> dict[str, str]:
        """The user whose primary extension (DtmfAccessId) is exactly `extension`."""
        extension = extension.strip()
        if not _EXTENSION_RE.match(extension):
            raise CucError(f"'{extension}' is not a valid extension.")
        for user in self.get_paged("users", "User", {"query": f"(DtmfAccessId is {extension})"}):
            if user.get("DtmfAccessId") == extension:
                return user
        raise CucError(f"No user found with extension {extension}")

    def mailbox_usage(self, extension: str) -> dict:
        """User lookup plus mailbox attributes: identity, uri, byteSize, sizeMb and the raw `mailbox` dict."""
        return self.mailbox_for_user(self.find_user(extension))

    def mailbox_for_user(self, user: dict[str, str]) -> dict:
        """Mailbox attributes of a user dict (as returned by find_user or list_users), in mailbox_usage's shape."""
        uri = user.get("URI", "")
        if not uri:
            raise CucError(f"No URI found for user {user.get('Alias', '')}")
        root = self.get(f"{uri}/mailboxattributes")
        if root.tag != "MailboxAttributes":
            root = root.find(".//MailboxAttributes")
            if root is None:
                raise CucError("MailboxAttributes not found in the response")
        mailbox = element_to_dict(root)
        try:
            size = int(mailbox.get("ByteSize") or 0)
        except ValueError:
            size = 0
        return {
            "objectId": user.get("ObjectId", ""), "dtmfAccessId": user.get("DtmfAccessId", ""),
            "alias": user.get("Alias", ""), "displayName": user.get("DisplayName", ""), "uri": uri,
            "byteSize": size, "sizeMb": round(size / (1024 * 1024), 2), "mailbox": mailbox,
        }

    def list_users(self) -> list[dict[str, str]]:
        return self.get_paged("users", "User")

    def delete_user(self, uri: str) -> None:
        """Deletes the whole user account, and with it the mailbox."""
        self.delete(uri)

    # --- call handlers ---

    def list_call_handlers(self) -> list[dict[str, str]]:
        return self.get_paged("handlers/callhandlers", "Callhandler")

    def menu_entries(self, handler_id: str) -> list[dict[str, str]]:
        root = self.get(f"handlers/callhandlers/{handler_id}/menuentries")
        return [element_to_dict(e) for e in root.findall(".//MenuEntry")]

    def delete_call_handler(self, object_id: str) -> None:
        if not _OBJECT_ID_RE.match(object_id):
            raise CucError(f"'{object_id}' is not a valid ObjectId.")
        self.delete(f"handlers/callhandlers/{object_id}")
