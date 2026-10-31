"""UCCX plumbing: errors and one client for the admin API (/adminapi) and the Finesse API (:8445/finesse/api).

Port of ccx_general.py from the old uccxTools scripts (reference only). One client per operation. Reads retry on
a reset connection or HTTP 429/5xx; writes never retry (a repeated create would duplicate or fail).
"""

import re

import requests
import urllib3
from lxml import etree
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

from .errors import UserError
from .uccx_connections import UccxConnection

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

XML_HEADERS = {"Content-Type": "application/xml"}


class UccxError(UserError):
    pass


def _error_text(resp: requests.Response) -> str:
    """The server's error message when the body has one, else the HTTP status."""
    try:
        root = etree.fromstring(resp.content)
        msgs = [e.text.strip() for e in root.iter("errorMessage") if e.text]
        if msgs:
            return f"HTTP {resp.status_code}: " + "; ".join(msgs)
    except etree.XMLSyntaxError:
        pass
    return f"HTTP {resp.status_code}"


def self_href(element) -> str:
    """The URL in a <self> child, whether it is an href attribute or the element text."""
    node = element.find("self")
    if node is None:
        return ""
    return node.attrib.get("href") or (node.text or "")


def admin_path(href: str) -> str:
    """The part of an admin API URL after /adminapi/ ('' when it is not one)."""
    return href.split("/adminapi/", 1)[1] if "/adminapi/" in href else ""


def local_name(text: str) -> str:
    """A name made safe to use inside a file name."""
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", text or "").strip(" .") or "unnamed"


class UccxClient:
    def __init__(self, conn: UccxConnection, timeout: int = 60):
        self.server = conn.server
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(conn.username, conn.password)
        self.session.verify = False
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET", "HEAD", "OPTIONS"])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def admin_url(self, path: str) -> str:
        return f"https://{self.server}/adminapi/{path}"

    def finesse_url(self, path: str) -> str:
        return f"https://{self.server}:8445/finesse/api/{path}"

    def request(self, method: str, url: str, ok=(200,), **kwargs) -> requests.Response:
        """One call. Network problems and a status outside `ok` raise UccxError."""
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.exceptions.SSLError as e:
            raise UccxError(f"TLS error talking to {self.server}: {e}")
        except requests.exceptions.ConnectTimeout:
            raise UccxError(f"Timed out connecting to {self.server}")
        except requests.exceptions.ConnectionError as e:
            raise UccxError(f"Cannot reach {self.server} ({e.__class__.__name__})")
        except requests.exceptions.RequestException as e:
            raise UccxError(f"Request to {self.server} failed: {e.__class__.__name__}")
        if resp.status_code == 401:
            raise UccxError("Authentication failed (401). Check the username and password.")
        if resp.status_code not in ok:
            raise UccxError(f"{method} {url.split(self.server, 1)[-1]} failed. {_error_text(resp)}")
        return resp

    def get_xml(self, url: str):
        """GET and parse the XML body (root element)."""
        resp = self.request("GET", url, ok=(200, 201, 202, 206))
        try:
            return etree.fromstring(resp.content)
        except etree.XMLSyntaxError:
            raise UccxError(f"GET {url.split(self.server, 1)[-1]} did not return XML.")

    def admin_xml(self, path: str):
        return self.get_xml(self.admin_url(path))

    def finesse_xml(self, path: str):
        return self.get_xml(self.finesse_url(path))

    def send_xml(self, method: str, url: str, payload, ok) -> requests.Response:
        """POST or PUT an lxml element (or a string) as XML."""
        if not isinstance(payload, (str, bytes)):
            payload = etree.tostring(payload, encoding="unicode", pretty_print=True)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return self.request(method, url, ok=ok, data=payload, headers=XML_HEADERS)

    def check(self) -> int:
        """Prove the login: list the skills. Returns how many there are."""
        root = self.admin_xml("skill")
        return len(root.findall(".//skillName"))
