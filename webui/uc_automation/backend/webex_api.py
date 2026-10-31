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
CORE_PATHS = ("/people", "/workspaces", "/devices")
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
        self.cache: dict = {}  # per-run lookups (license ids and the like)
        # One session per client: reuses the TLS connection across calls (and across the worker threads of a bulk run).
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=1, pool_maxsize=POOL_SIZE)
        self._session.mount("https://", adapter)

    @classmethod
    def connect(cls, org: str) -> "WebexClient":
        """Check the login assigned to a saved org (renewing it if needed) and build a client for that org.
        Raises WebexAuthError."""
        login, org_id = webex_auth.resolve(org)
        return cls(webex_auth.ensure_token(login), org_id)

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None,
             files: dict | None = None) -> dict:
        """Run one request. Returns the JSON body ({} for 204). Raises WebexError on any failure.

        `files` makes it a multipart upload ({"file": (name, bytes, content_type)}); `body` is then ignored."""
        params = dict(params or {})
        if self.org_id:
            params["orgId"] = _core_org_id(self.org_id) if path.startswith(CORE_PATHS) else self.org_id
        headers = {"Authorization": f"Bearer {self._token}"}
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self._session.request(method, BASE + path, headers=headers, params=params,
                                          json=None if files else body, files=files, timeout=TIMEOUT)
            except requests.RequestException as e:
                raise WebexError(f"Could not reach Webex: {e}") from e
            if r.status_code == 429 and attempt < MAX_RETRIES:
                time.sleep(min(int(r.headers.get("Retry-After", "2") or 2), 60))
                continue
            break
        if r.status_code == 401:
            raise WebexError("Webex rejected the token (401). Log in again on the Credentials page.")
        if r.status_code >= 300:
            text = _error_text(r)
            if r.status_code == 400:
                text += f" ({method} {path})"
            raise WebexError(text)
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
