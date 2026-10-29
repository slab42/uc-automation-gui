"""Webex REST plumbing: one client per operation, with the token checked once and the org id attached.

Features (`webex_routing.py` and later modules) take a `WebexClient` and never touch tokens themselves.
Plain Python, no Reflex imports.
"""

import time

import requests

from . import webex_auth
from .errors import UserError

BASE = "https://webexapis.com/v1"
TIMEOUT = 30
MAX_RETRIES = 3  # for HTTP 429 (rate limited)


class WebexError(UserError):
    """A Webex API problem. The message is shown as is."""


class WebexClient:
    def __init__(self, token: str, org_id: str = ""):
        self._token = token
        self.org_id = org_id
        self.cache: dict = {}  # per-run lookups (license ids and the like)

    @classmethod
    def connect(cls) -> "WebexClient":
        """Check the stored login (renewing it if needed) and build a client. Raises WebexAuthError."""
        return cls(webex_auth.ensure_token(), webex_auth.saved_org_id())

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None,
             files: dict | None = None) -> dict:
        """Run one request. Returns the JSON body ({} for 204). Raises WebexError on any failure.

        `files` makes it a multipart upload ({"file": (name, bytes, content_type)}); `body` is then ignored."""
        params = dict(params or {})
        if self.org_id:
            params["orgId"] = self.org_id
        headers = {"Authorization": f"Bearer {self._token}"}
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = requests.request(method, BASE + path, headers=headers, params=params,
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
            raise WebexError(_error_text(r))
        try:
            return r.json() if r.content else {}
        except ValueError:
            return {}


def _error_text(r: requests.Response) -> str:
    try:
        j = r.json()
        msg = j.get("message") or j.get("errors", [{}])[0].get("description") or r.text
    except (ValueError, AttributeError, IndexError):
        msg = r.text
    return f"Webex returned {r.status_code}: {msg.strip()[:300]}"
