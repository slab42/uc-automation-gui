"""Webex REST plumbing: one client per operation, with the token checked once and the org id attached.

Features (`webex_routing.py` and later modules) take a `WebexClient` and never touch tokens themselves.
Plain Python, no Reflex imports.
"""

import base64
import re
import time

import requests
from requests.adapters import HTTPAdapter

from . import webex_auth
from .errors import UserError

BASE = "https://webexapis.com/v1"
TIMEOUT = 30
MAX_RETRIES = 3  # for HTTP 429 (rate limited)
POOL_SIZE = 16   # keep-alive connections, enough for the parallel bulk runs


class WebexError(UserError):
    """A Webex API problem. The message is shown as is."""


# Core (non-calling) APIs: they want the base64 org id, the telephony APIs accept the bare UUID.
CORE_PATHS = ("/people", "/workspaces", "/devices", "/locations")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _core_org_id(org_id: str) -> str:
    """The core APIs (/people, /workspaces, /devices) reject a bare UUID org id; it wants the base64 form (assumes the US cluster)."""
    if _UUID.match(org_id):
        return base64.b64encode(f"ciscospark://us/ORGANIZATION/{org_id}".encode()).decode().rstrip("=")
    return org_id


class WebexClient:
    def __init__(self, token: str, org_id: str = ""):
        self._token = token
        self.org_id = org_id
        self.log = None  # optional OpLog: every request and every failure is written to it
        self.cache: dict = {}  # per-run lookups (license ids and the like)
        # One session per client: reuses the TLS connection across calls (and across the worker threads of a bulk run).
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=1, pool_maxsize=POOL_SIZE)
        self._session.mount("https://", adapter)

    @classmethod
    def connect(cls, org: str, log=None) -> "WebexClient":
        """Check the login assigned to a saved org (renewing it if needed) and build a client for that org.
        With `log`, writes the login's scopes and the token owner's roles first, then every request.
        Raises WebexAuthError."""
        login, org_id = webex_auth.resolve(org)
        client = cls(webex_auth.ensure_token(login), org_id)
        if log is not None:
            client.log = log
            for line in webex_auth.describe_login(login, client._token):
                log.info(line)
        return client

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None,
             files: dict | None = None) -> dict:
        """Run one request. Returns the JSON body ({} for 204). Raises WebexError on any failure.

        `files` makes it a multipart upload ({"file": (name, bytes, content_type)}); `body` is then ignored."""
        return _json(self._send(method, BASE + path, self._params(path, params), body, files))

    def list_all(self, path: str, key: str, params: dict | None = None) -> list[dict]:
        """Every item of a list API that pages with the Link header (rel="next"), such as /people."""
        r = self._send("GET", BASE + path, self._params(path, params))
        items = list(_json(r).get(key) or [])
        while r.links.get("next", {}).get("url"):
            r = self._send("GET", r.links["next"]["url"], None)  # the next link carries every query parameter
            items.extend(_json(r).get(key) or [])
        return items

    def _params(self, path: str, params: dict | None) -> dict:
        params = dict(params or {})
        if self.org_id:
            params["orgId"] = _core_org_id(self.org_id) if path.startswith(CORE_PATHS) else self.org_id
        return params

    def _send(self, method: str, url: str, params: dict | None, body: dict | None = None,
              files: dict | None = None) -> requests.Response:
        headers = {"Authorization": f"Bearer {self._token}"}
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self._session.request(method, url, headers=headers, params=params,
                                          json=None if files else body, files=files, timeout=TIMEOUT)
            except requests.RequestException as e:
                raise WebexError(f"Could not reach Webex: {e}") from e
            if r.status_code == 429 and attempt < MAX_RETRIES:
                time.sleep(min(int(r.headers.get("Retry-After", "2") or 2), 60))
                continue
            break
        self._log_response(method, url, params, r)
        if r.status_code == 401:
            raise WebexError("Webex rejected the token (401). Log in again on the Credentials page.")
        if r.status_code >= 300:
            text = _error_text(r)
            if r.status_code in (400, 403):
                text += f" ({method} {url.removeprefix(BASE).split('?')[0]})"
            if r.status_code == 403 and r.headers.get("TrackingID"):
                text += f" [TrackingID {r.headers['TrackingID']}]"
            raise WebexError(text)
        return r


    def _log_response(self, method: str, url: str, params: dict | None, r: requests.Response) -> None:
        if self.log is None:
            return
        path = url.removeprefix(BASE).split("?")[0]
        query = " ".join(f"{k}={v}" for k, v in (params or {}).items())
        line = f"{method} {path}{' ?' + query if query else ''} -> {r.status_code} (TrackingID {r.headers.get('TrackingID', '-')})"
        if r.status_code < 300:
            self.log.info(line)
            return
        self.log.error(line)
        self.log.error(f"  response body: {r.text.strip()[:2000]}")
        for h in ("WWW-Authenticate", "Retry-After"):
            if r.headers.get(h):
                self.log.error(f"  {h}: {r.headers[h]}")


def _json(r: requests.Response) -> dict:
    try:
        return r.json() if r.content else {}
    except ValueError:
        return {}


def _error_text(r: requests.Response) -> str:
    try:
        j = r.json()
        msg = j.get("message") or j.get("errors", [{}])[0].get("description") or r.text
        details = [str(e.get("description") or e.get("message") or "") for e in j.get("errors") or [] if isinstance(e, dict)]
        details = [d for d in details if d and d not in msg]
        if details:
            msg += ": " + "; ".join(details)
    except (ValueError, AttributeError, IndexError):
        msg = r.text
    return f"Webex returned {r.status_code}: {msg.strip()[:300]}"
