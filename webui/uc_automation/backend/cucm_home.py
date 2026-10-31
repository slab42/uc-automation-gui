"""Home Cluster Locator: ask the UDS service of each CUCM cluster which cluster a user is marked as home on, and move
the home marker (enduser.islocaluser) with AXL SQL.

Ported from the old Home Cluster Manager GUI. UDS needs no login, the update needs an AXL account. No Reflex imports.
"""

from xml.etree.ElementTree import ParseError, fromstring

import requests
import urllib3

from .cucm_axl import AxlError, _call, sql_quote, sql_rows
from .cucm_connections import CucmConnection

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

UDS_PORT = 8443
TIMEOUT = 5


class HomeError(Exception):
    """The cluster could not answer (unreachable) or does not know the user. The message is shown in the table."""


def parse_home_cluster(xml: bytes) -> str:
    """Home cluster name from a `clusterUser` UDS response. Raises HomeError when the answer has none."""
    try:
        root = fromstring(xml)
    except ParseError:
        raise HomeError("Not a UDS answer")
    for el in root.iter():
        if el.tag.lower().endswith("homecluster") and (el.text or "").strip():
            return el.text.strip().lower()
    if len(root) > 1 and (root[1].text or "").strip():  # the old tool read the second child
        return root[1].text.strip().lower()
    raise HomeError("User not found")


def home_cluster(server: str, username: str) -> str:
    """The home cluster reported by `server` for `username`."""
    url = f"https://{server}:{UDS_PORT}/cucm-uds/clusterUser"
    try:
        r = requests.get(url, params={"username": username}, verify=False, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise HomeError(f"Unreachable: {type(e).__name__}")
    if r.status_code == 404:
        raise HomeError("User not found")
    if r.status_code != 200:
        raise HomeError(f"HTTP {r.status_code}")
    return parse_home_cluster(r.content)


def _where(userid: str) -> str:
    return f"lower(userid) = lower('{sql_quote(userid)}')"


def read_home(conn: CucmConnection, userid: str) -> str:
    """'t' or 'f' (the user's islocaluser on this cluster), or '' when the user is not on it."""
    rows = sql_rows(conn, f"select islocaluser from enduser where {_where(userid)}", 1)
    return (rows[0].get("islocaluser", "") if rows else "").strip().lower()


def set_home(conn: CucmConnection, userid: str, local: bool) -> str:
    """Mark (`local`) or unmark the user as home on this cluster, then read it back. Returns a detail line.

    A cluster that does not have the user is left alone and reported. Raises AxlError when the change cannot be made
    or the read back disagrees."""
    want = "t" if local else "f"
    current = read_home(conn, userid)
    if not current:
        if local:
            raise AxlError("User not found on this cluster")
        return "User not on this cluster, nothing to remove"
    if current == want:
        return "Home cluster already enabled" if local else "Home cluster already removed"
    _call(conn, "executeSQLUpdate", sql=f"update enduser set islocaluser = '{want}' where {_where(userid)}")
    if read_home(conn, userid) != want:
        raise AxlError("The update ran but the user still shows the old value")
    return "Home cluster enabled" if local else "Home cluster removed"
