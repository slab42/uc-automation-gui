"""Webex logins and orgs, stored in .env/credentials.env.

Logins and orgs are saved separately and paired freely:
- a login is a named [WEBEX:<name>] section (Integration, tokens or a pasted bearer token);
- an org is a named [WEBEXORG:<name>] section with `org_id` and `login` (the name of the login to use for it).
Any login can serve any number of orgs and an org can be switched to another login at any time.
`resolve(org)` gives the (login, org id) pair that API code needs. Functions that take `name` mean a login name.

Keys of a login: client_id, client_secret, scopes, access_token, refresh_token, expires_at, refresh_expires_at
(epoch seconds), user, auth_mode ("oauth", or "token"
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

_pending_states: dict[str, tuple[float, str]] = {}
_state_lock = threading.Lock()
_STATE_TTL = 600


class WebexAuthError(UserError):
    """A problem the user can act on. The message is shown as is."""


def _section(name: str) -> str:
    return f"WEBEX:{name}"


def _config(name: str) -> dict[str, str]:
    return ini_store.read_section(CREDENTIALS_PATH, _section(name))


def list_logins() -> list[dict[str, str]]:
    """Saved logins without secrets, safe for the browser."""
    out = []
    for sec in ini_store.read_sections(CREDENTIALS_PATH):
        if sec["service"] != "WEBEX":
            continue
        f = sec["fields"]
        out.append({
            "name": sec["identifier"],
            "user": f.get("user", ""),
            "auth_mode": f.get("auth_mode", "oauth"),
            "has_token": "yes" if sec["secrets"].get("access_token") else "no",
        })
    return out


def delete_login(name: str) -> bool:
    """Remove a login. Orgs that used it keep existing but have no login until another is chosen."""
    for o in list_orgs():
        if o["login"] == name:
            ini_store.upsert_section(CREDENTIALS_PATH, _org_section(o["name"]), {"login": ""})
    return ini_store.delete_section(CREDENTIALS_PATH, _section(name))


def rename_login(old: str, new: str) -> None:
    """Rename a login (secrets move with it) and repoint the orgs that use it."""
    if old == new:
        return
    if _config(new):
        raise WebexAuthError(f"Credentials named {new} already exist.")
    values = _config(old)
    if not values:
        raise WebexAuthError(f"Credentials {old} are not saved.")
    ini_store.upsert_section(CREDENTIALS_PATH, _section(new), values)
    for o in list_orgs():
        if o["login"] == old:
            ini_store.upsert_section(CREDENTIALS_PATH, _org_section(o["name"]), {"login": new})
    ini_store.delete_section(CREDENTIALS_PATH, _section(old))


def rename_org(old: str, new: str) -> None:
    if old == new:
        return
    if ini_store.read_section(CREDENTIALS_PATH, _org_section(new)):
        raise WebexAuthError(f"An organization named {new} already exists.")
    values = ini_store.read_section(CREDENTIALS_PATH, _org_section(old))
    if not values:
        raise WebexAuthError(f"Organization {old} is not saved.")
    ini_store.upsert_section(CREDENTIALS_PATH, _org_section(new), values)
    ini_store.delete_section(CREDENTIALS_PATH, _org_section(old))


def _org_section(name: str) -> str:
    return f"WEBEXORG:{name}"


def _migrate_legacy_orgs() -> None:
    """Older versions stored `org_id` inside the login section. Turn each into an org of the same name."""
    for sec in ini_store.read_sections(CREDENTIALS_PATH):
        if sec["service"] == "WEBEX" and sec["fields"].get("org_id"):
            name = sec["identifier"]
            if not ini_store.read_section(CREDENTIALS_PATH, _org_section(name)):
                ini_store.upsert_section(CREDENTIALS_PATH, _org_section(name),
                                         {"org_id": sec["fields"]["org_id"], "login": name})
            ini_store.upsert_section(CREDENTIALS_PATH, _section(name), {"org_id": ""})


def list_orgs() -> list[dict[str, str]]:
    _migrate_legacy_orgs()
    return [
        {"name": sec["identifier"], "org_id": sec["fields"].get("org_id", ""), "login": sec["fields"].get("login", ""),
         "org": sec["fields"].get("org", "")}
        for sec in ini_store.read_sections(CREDENTIALS_PATH) if sec["service"] == "WEBEXORG"
    ]


def save_org(name: str, org_id: str, login: str | None = None, org: str | None = None) -> None:
    """Create or update an org. `login` None keeps the stored choice."""
    values: dict[str, str | None] = {"org_id": org_id.strip()}
    if org is not None:
        values["org"] = org
    if login is not None:
        values["login"] = login
    elif not ini_store.read_section(CREDENTIALS_PATH, _org_section(name)):
        values["login"] = ""
    ini_store.upsert_section(CREDENTIALS_PATH, _org_section(name), values)


def set_org_login(name: str, login: str) -> None:
    ini_store.upsert_section(CREDENTIALS_PATH, _org_section(name), {"login": login})


def delete_org(name: str) -> bool:
    return ini_store.delete_section(CREDENTIALS_PATH, _org_section(name))


def resolve(org: str) -> tuple[str, str]:
    """(login name, org id) for a saved org. Raises WebexAuthError when the org or its login is missing."""
    if not org:
        raise WebexAuthError("No Webex org selected. Add one on Credentials > Webex.")
    kv = ini_store.read_section(CREDENTIALS_PATH, _org_section(org))
    if not kv:
        raise WebexAuthError(f"Webex org {org} is not saved.")
    login = kv.get("login", "")
    if not login or not _config(login):
        raise WebexAuthError(f"Webex org {org} has no login assigned. Choose one on Credentials > Webex.")
    return login, kv.get("org_id", "")


def _int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def save_client(name: str, client_id: str, client_secret: str | None, scopes: str) -> None:
    """client_secret None/'' keeps the stored one. Changing the client id drops any stored login."""
    old = _config(name)
    values: dict[str, str | None] = {"client_id": client_id, "scopes": scopes or DEFAULT_SCOPES}
    if client_secret:
        values["client_secret"] = client_secret
    elif not old:
        values["client_secret"] = ""
    if old.get("client_id") and old["client_id"] != client_id:
        values.update(access_token="", refresh_token="", expires_at="", refresh_expires_at="", user="")
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), values)


def new_state(name: str) -> str:
    """A one-time value that ties the login redirect to the callback (CSRF protection)."""
    token = secrets.token_urlsafe(24)
    now = time.time()
    with _state_lock:
        for k in [k for k, (t, _n) in _pending_states.items() if now - t > _STATE_TTL]:
            del _pending_states[k]
        _pending_states[token] = (now, name)
    return token


def _consume_state(token: str) -> str | None:
    """The connection name the login was started for, or None when the state is unknown or too old."""
    with _state_lock:
        issued = _pending_states.pop(token, None)
    if issued is None or time.time() - issued[0] > _STATE_TTL:
        return None
    return issued[1]


def authorize_url(name: str, state: str) -> str:
    cfg = _config(name)
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


def _token_request(name: str, data: dict[str, str]) -> dict:
    cfg = _config(name)
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


def _store_tokens(name: str, tok: dict, user: str | None = None) -> None:
    now = int(time.time())
    values: dict[str, str | None] = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", ""),
        "expires_at": str(now + int(tok.get("expires_in", 0))),
        "refresh_expires_at": str(now + int(tok.get("refresh_token_expires_in", 0))),
    }
    if user is not None:
        values["user"] = user
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), values)


def complete_login(code: str, state: str) -> tuple[str, str]:
    """Callback step: verify state, exchange the code, store the tokens. Returns (connection name, user)."""
    name = _consume_state(state)
    if name is None:
        raise WebexAuthError("Login session not recognised or timed out. Start the login again.")
    tok = _token_request(name, {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI})
    user = _whoami(tok["access_token"])
    _store_tokens(name, tok, user)
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), {"auth_mode": "oauth"})
    return name, user


def save_pasted_token(name: str, token: str) -> str:
    """Store a bearer token copied from developer.webex.com. Returns the token owner."""
    token = token.strip().removeprefix("Bearer ").strip()
    if not token:
        raise WebexAuthError("Paste a bearer token first.")
    try:
        user = _whoami(token)
    except _Invalid:
        raise WebexAuthError("Webex rejected that token. Copy a fresh one.") from None
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), {
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


def _refresh(name: str) -> None:
    cfg = _config(name)
    rt = cfg.get("refresh_token", "")
    if not rt or _int(cfg.get("refresh_expires_at", "")) <= time.time():
        raise WebexAuthError("Webex session expired. Log in again.")
    tok = _token_request(name, {"grant_type": "refresh_token", "refresh_token": rt})
    _store_tokens(name, tok)


def ensure_token(name: str) -> str:
    """The access token to use for API calls. Checks it on every call and renews it when needed.

    Raises WebexAuthError when there is no login or it can no longer be renewed.
    """
    if not name:
        raise WebexAuthError("No Webex connection selected. Add one on Credentials > Webex.")
    cfg = _config(name)
    if not cfg.get("access_token"):
        raise WebexAuthError(f"Not logged in to Webex connection {name}. Use Credentials > Webex.")
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
    _refresh(name)
    token = _config(name)["access_token"]
    _whoami(token)
    return token


def check_org(org: str) -> tuple[bool, str]:
    """check() for the login assigned to a saved org. Never raises."""
    try:
        login, _ = resolve(org)
    except WebexAuthError as e:
        return False, str(e)
    return check(login)


def check(name: str) -> tuple[bool, str]:
    """(logged_in, message) for the Credentials page. Never raises."""
    try:
        ensure_token(name)
    except WebexAuthError as e:
        return False, str(e)
    return True, "Token is valid."


def logout(name: str) -> None:
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), {
        "access_token": "", "refresh_token": "", "expires_at": "", "refresh_expires_at": "", "user": "",
    })


def public_status(name: str) -> dict[str, str]:
    """Everything the page may show about one connection. No secrets, no token text."""
    c = _config(name)
    return {
        "client_id": c.get("client_id", ""),
        "scopes": c.get("scopes") or DEFAULT_SCOPES,
        "has_secret": "yes" if c.get("client_secret") else "no",
        "has_token": "yes" if c.get("access_token") else "no",
        "user": c.get("user", ""),
        "auth_mode": c.get("auth_mode", "oauth"),
        "expires_at": c.get("expires_at", ""),
        "refresh_expires_at": c.get("refresh_expires_at", ""),
    }
