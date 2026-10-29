"""Webex login and token storage, kept in the [WEBEX:default] section of .env/credentials.env.

Webex does not offer a username/password token API, so this uses the OAuth 2.0 authorization code
flow with a Webex Integration (client id + secret from developer.webex.com/my-apps). The user signs
in on Webex's own login page, Webex redirects back to REDIRECT_URI with a code, and the code is
exchanged for an access token (about 14 days) and a refresh token (about 90 days). The refresh
token renews the access token without another login.

Keys: client_id, client_secret, scopes, access_token, refresh_token, expires_at, refresh_expires_at
(epoch seconds), user, org_id (the customer's Webex org id, shared by both modes), auth_mode ("oauth", or "token"
when a bearer token was pasted from developer.webex.com; those have no refresh token and no known expiry). Secrets never leave the backend: `public_status` only reports whether they are set.
"""

import secrets
import threading
import time
from urllib.parse import urlencode

import requests

from . import ini_store
from .errors import UserError
from .paths import CREDENTIALS_PATH

SECTION = "WEBEX:default"
AUTH_URL = "https://webexapis.com/v1/authorize"
TOKEN_URL = "https://webexapis.com/v1/access_token"
ME_URL = "https://webexapis.com/v1/people/me"
REDIRECT_URI = "http://localhost:3000/webex/callback"
DEFAULT_SCOPES = (
    "spark-admin:people_read spark-admin:people_write "
    "spark-admin:telephony_config_read spark-admin:telephony_config_write "
    "spark-admin:workspaces_read spark-admin:workspaces_write "
    "spark-admin:devices_read spark-admin:devices_write spark-admin:licenses_read identity:groups_rw"
)
EXPIRY_MARGIN = 120  # renew when fewer than this many seconds remain
TIMEOUT = 20

_pending_states: dict[str, float] = {}
_state_lock = threading.Lock()
_STATE_TTL = 600


class WebexAuthError(UserError):
    """A problem the user can act on. The message is shown as is."""


def _config() -> dict[str, str]:
    return ini_store.read_section(CREDENTIALS_PATH, SECTION)


def _int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def save_client(client_id: str, client_secret: str | None, scopes: str) -> None:
    """client_secret None/'' keeps the stored one. Changing the client id drops any stored login."""
    old = _config()
    values: dict[str, str | None] = {"client_id": client_id, "scopes": scopes or DEFAULT_SCOPES}
    if client_secret:
        values["client_secret"] = client_secret
    elif not old:
        values["client_secret"] = ""
    if old.get("client_id") and old["client_id"] != client_id:
        values.update(access_token="", refresh_token="", expires_at="", refresh_expires_at="", user="")
    ini_store.upsert_section(CREDENTIALS_PATH, SECTION, values)


def new_state() -> str:
    """A one-time value that ties the login redirect to the callback (CSRF protection)."""
    token = secrets.token_urlsafe(24)
    now = time.time()
    with _state_lock:
        for k in [k for k, t in _pending_states.items() if now - t > _STATE_TTL]:
            del _pending_states[k]
        _pending_states[token] = now
    return token


def _consume_state(token: str) -> bool:
    with _state_lock:
        issued = _pending_states.pop(token, None)
    return issued is not None and time.time() - issued <= _STATE_TTL


def authorize_url(state: str) -> str:
    cfg = _config()
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        raise WebexAuthError("Save the Integration's Client ID and Client Secret first.")
    query = urlencode({
        "client_id": cfg["client_id"],
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": cfg.get("scopes") or DEFAULT_SCOPES,
        "state": state,
    })
    return f"{AUTH_URL}?{query}"


def _token_request(data: dict[str, str]) -> dict:
    cfg = _config()
    body = {"client_id": cfg.get("client_id", ""), "client_secret": cfg.get("client_secret", ""), **data}
    try:
        r = requests.post(TOKEN_URL, data=body, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise WebexAuthError(f"Could not reach Webex: {e}") from e
    if r.status_code != 200:
        try:
            detail = r.json().get("message") or r.json().get("error_description") or r.text
        except ValueError:
            detail = r.text
        raise WebexAuthError(f"Webex rejected the request ({r.status_code}): {detail}")
    return r.json()


def _store_tokens(tok: dict, user: str | None = None) -> None:
    now = int(time.time())
    values: dict[str, str | None] = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", ""),
        "expires_at": str(now + int(tok.get("expires_in", 0))),
        "refresh_expires_at": str(now + int(tok.get("refresh_token_expires_in", 0))),
    }
    if user is not None:
        values["user"] = user
    ini_store.upsert_section(CREDENTIALS_PATH, SECTION, values)


def complete_login(code: str, state: str) -> str:
    """Callback step: verify state, exchange the code, store the tokens. Returns the signed-in user."""
    if not _consume_state(state):
        raise WebexAuthError("Login session not recognised or timed out. Start the login again.")
    tok = _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI})
    user = _whoami(tok["access_token"])
    _store_tokens(tok, user)
    ini_store.upsert_section(CREDENTIALS_PATH, SECTION, {"auth_mode": "oauth"})
    return user


def save_org(org_id: str) -> None:
    ini_store.upsert_section(CREDENTIALS_PATH, SECTION, {"org_id": org_id.strip()})


def get_org_id() -> str:
    """The customer org id to use in API calls. Raises WebexAuthError when none is saved."""
    org = _config().get("org_id", "")
    if not org:
        raise WebexAuthError("No Webex Org ID saved. Use Credentials > Webex.")
    return org


def saved_org_id() -> str:
    """The saved customer org id, or '' when none (calls then go to the token owner's own org)."""
    return _config().get("org_id", "")


def save_pasted_token(token: str) -> str:
    """Store a bearer token copied from developer.webex.com. Returns the token owner."""
    token = token.strip().removeprefix("Bearer ").strip()
    if not token:
        raise WebexAuthError("Paste a bearer token first.")
    try:
        user = _whoami(token)
    except _Invalid:
        raise WebexAuthError("Webex rejected that token. Copy a fresh one.") from None
    ini_store.upsert_section(CREDENTIALS_PATH, SECTION, {
        "auth_mode": "token", "access_token": token, "refresh_token": "", "expires_at": "",
        "refresh_expires_at": "", "user": user,
    })
    return user


def _whoami(token: str) -> str:
    """Display name of the token's owner. Raises WebexAuthError(401) text on an invalid token."""
    try:
        r = requests.get(ME_URL, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise WebexAuthError(f"Could not reach Webex: {e}") from e
    if r.status_code == 401:
        raise _Invalid()
    if r.status_code != 200:
        raise WebexAuthError(f"Webex returned {r.status_code} while checking the token.")
    j = r.json()
    emails = j.get("emails") or [""]
    return f"{j.get('displayName', '')} ({emails[0]})".strip()


class _Invalid(WebexAuthError):
    def __init__(self):
        super().__init__("The stored token is no longer valid.")


def _refresh() -> None:
    cfg = _config()
    rt = cfg.get("refresh_token", "")
    if not rt or _int(cfg.get("refresh_expires_at", "")) <= time.time():
        raise WebexAuthError("Webex session expired. Log in again.")
    tok = _token_request({"grant_type": "refresh_token", "refresh_token": rt})
    _store_tokens(tok)


def ensure_token() -> str:
    """The access token to use for API calls. Checks it on every call and renews it when needed.

    Raises WebexAuthError when there is no login or it can no longer be renewed.
    """
    cfg = _config()
    if not cfg.get("access_token"):
        raise WebexAuthError("Not logged in to Webex. Use Credentials > Webex.")
    pasted = cfg.get("auth_mode") == "token"
    exp = _int(cfg.get("expires_at", ""))
    if pasted or not exp or exp - time.time() > EXPIRY_MARGIN:
        try:
            _whoami(cfg["access_token"])
            return cfg["access_token"]
        except _Invalid:
            if pasted:
                raise WebexAuthError("The pasted token is no longer valid. Paste a new one.") from None
            # revoked or otherwise dead: fall through to a refresh
    _refresh()
    token = _config()["access_token"]
    _whoami(token)
    return token


def check() -> tuple[bool, str]:
    """(logged_in, message) for the Credentials page. Never raises."""
    try:
        ensure_token()
    except WebexAuthError as e:
        return False, str(e)
    return True, "Token is valid."


def logout() -> None:
    ini_store.upsert_section(CREDENTIALS_PATH, SECTION, {
        "access_token": "", "refresh_token": "", "expires_at": "", "refresh_expires_at": "", "user": "",
    })


def delete_client() -> None:
    ini_store.delete_section(CREDENTIALS_PATH, SECTION)


def public_status() -> dict[str, str]:
    """Everything the page may show. No secrets, no token text."""
    c = _config()
    return {
        "client_id": c.get("client_id", ""),
        "scopes": c.get("scopes") or DEFAULT_SCOPES,
        "has_secret": "yes" if c.get("client_secret") else "no",
        "has_token": "yes" if c.get("access_token") else "no",
        "user": c.get("user", ""),
        "org_id": c.get("org_id", ""),
        "auth_mode": c.get("auth_mode", "oauth"),
        "expires_at": c.get("expires_at", ""),
        "refresh_expires_at": c.get("refresh_expires_at", ""),
    }
