"""Personal Webex tokens: one bearer token per app user, copied from developer.webex.com (they last about 12 hours).

Used instead of the org's login when a Webex tool gets a 403 and the user switches to their own token.
Stored in `.env/webex_personal.json` (git-ignored, mode 600). The token never leaves the backend: `status` only reports
whether one is stored, when it was saved and whether Webex still accepts it.
Plain Python, no Reflex imports.
"""

import json
import os
import tempfile
import threading
import time

from . import webex_auth
from .errors import UserError
from .paths import WEBEX_PERSONAL_PATH

STALE_AFTER = 6 * 3600  # ask for a fresh token when the stored one was saved longer ago than this

_lock = threading.Lock()


def _key(user: str) -> str:
    return user.strip().lower()


def _read() -> dict:
    try:
        return json.loads(WEBEX_PERSONAL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    WEBEX_PERSONAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(WEBEX_PERSONAL_PATH.parent), prefix="webex_personal", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, WEBEX_PERSONAL_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(user: str, token: str) -> str:
    """Check a pasted token with Webex and store it for `user`. Returns the token owner. Raises UserError."""
    token = token.strip().removeprefix("Bearer ").strip()
    if not token:
        raise UserError("Paste a Webex token first.")
    try:
        owner = webex_auth._whoami(token)
    except webex_auth._Invalid:
        raise UserError("Webex rejected that token. Copy a fresh one.") from None
    with _lock:
        data = _read()
        data[_key(user)] = {"token": token, "saved_at": int(time.time()), "owner": owner}
        _write(data)
    return owner


def remove(user: str) -> None:
    with _lock:
        data = _read()
        if data.pop(_key(user), None) is not None:
            _write(data)


def _record(user: str) -> dict:
    return _read().get(_key(user)) or {}


def get_token(user: str) -> str:
    return _record(user).get("token", "")


def age_text(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    return f"{minutes // 60} h {minutes % 60} min ago"


def status(user: str, verify: bool = True) -> tuple[str, str]:
    """(state, message) of a user's token. state is "missing", "stale" (saved over STALE_AFTER ago), "expired"
    (Webex rejects it) or "ok". `verify=False` skips the Webex call (so "expired" is not detected). Never raises."""
    rec = _record(user)
    if not rec.get("token"):
        return "missing", "No personal Webex token is stored yet. Paste one from developer.webex.com."
    age = time.time() - int(rec.get("saved_at") or 0)
    if verify:
        try:
            webex_auth._whoami(rec["token"])
        except webex_auth._Invalid:
            return "expired", "The stored personal Webex token has expired. Paste a new one."
        except UserError as e:
            return "error", str(e)
    if age > STALE_AFTER:
        return "stale", f"The personal Webex token was saved {age_text(age)}. Paste a fresh one."
    return "ok", f"Stored for {rec.get('owner', '')}, saved {age_text(age)}."
