"""App users, passwords, access lists and sign-in sessions. Plain Python, no Reflex imports.

Users live in `webui/users.json` (per machine, git-ignored): one `admin` account with full access plus any
number of ordinary users, each with the list of page routes they may open. Passwords are stored as salted
scrypt hashes and never leave this module. Sessions are random tokens kept in memory only (a restart signs
everyone out).
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time

from .errors import UserError
from .paths import WEBUI_ROOT

USERS_PATH = WEBUI_ROOT / "users.json"
ADMIN = "admin"
MIN_PASSWORD = 8
SESSION_IDLE_SECONDS = 12 * 3600  # a session unused this long is dropped
MAX_FAILURES = 5  # wrong passwords in LOCK_WINDOW seconds lock the account for LOCK_SECONDS
LOCK_WINDOW = 600
LOCK_SECONDS = 300
_NAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}

_lock = threading.RLock()
_sessions: dict[str, dict] = {}  # token -> {"user": key, "seen": float}
_failures: dict[str, list[float]] = {}  # user key -> times of recent wrong passwords
_cache: dict = {"mtime": None, "data": {"users": {}}}


class AuthError(UserError):
    """A sign-in or account problem with a message that is safe to show."""


def _key(name: str) -> str:
    return name.strip().lower()


def _read() -> dict:
    """The users file as a dict, re-read only when it changed on disk."""
    try:
        mtime = USERS_PATH.stat().st_mtime_ns
    except OSError:
        _cache.update(mtime=None, data={"users": {}})
        return _cache["data"]
    if mtime != _cache["mtime"]:
        try:
            data = json.loads(USERS_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("users"), dict):
                raise ValueError
        except (OSError, ValueError):
            data = {"users": {}}
        _cache.update(mtime=mtime, data=data)
    return _cache["data"]


def _write(data: dict) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=USERS_PATH.parent, prefix=".users.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, USERS_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _cache["mtime"] = None  # force a re-read next time


def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), **_SCRYPT)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"The password must be at least {MIN_PASSWORD} characters.")


def _public(key: str, rec: dict) -> dict:
    return {
        "username": rec.get("username", key),
        "role": "admin" if key == ADMIN else "user",
        "enabled": bool(rec.get("enabled", True)),
        "routes": list(rec.get("routes", [])),
    }


def needs_setup() -> bool:
    """True until the admin account exists (first run)."""
    with _lock:
        return ADMIN not in _read()["users"]


def create_admin(password: str) -> None:
    """First run only: create the Admin account with the chosen password."""
    with _lock:
        if not needs_setup():
            raise AuthError("The Admin account already exists.")
        _check_new_password(password)
        data = json.loads(json.dumps(_read()))
        data["users"][ADMIN] = {"username": "Admin", "enabled": True, "routes": [], "password": _hash(password)}
        _write(data)


def list_users() -> list[dict]:
    with _lock:
        users = _read()["users"]
        rows = [_public(k, v) for k, v in users.items()]
    rows.sort(key=lambda r: (r["role"] != "admin", r["username"].lower()))
    return rows


def get_user(name: str) -> dict | None:
    with _lock:
        rec = _read()["users"].get(_key(name))
        return _public(_key(name), rec) if rec else None


def add_user(username: str, password: str, routes: list[str]) -> None:
    username = username.strip()
    if not _NAME_RE.match(username):
        raise AuthError("A user name is 1 to 64 letters, digits or . _ @ - (no spaces).")
    key = _key(username)
    if key == ADMIN:
        raise AuthError("That name is reserved.")
    _check_new_password(password)
    with _lock:
        data = json.loads(json.dumps(_read()))
        if key in data["users"]:
            raise AuthError(f"User {username} already exists.")
        data["users"][key] = {"username": username, "enabled": True, "routes": sorted(set(routes)),
                              "password": _hash(password)}
        _write(data)


def update_user(username: str, routes: list[str], enabled: bool) -> None:
    """Change a user's access list and whether the account is enabled. The Admin account cannot be changed."""
    key = _key(username)
    if key == ADMIN:
        raise AuthError("The Admin account always has full access.")
    with _lock:
        data = json.loads(json.dumps(_read()))
        rec = data["users"].get(key)
        if rec is None:
            raise AuthError(f"User {username} does not exist.")
        rec["routes"] = sorted(set(routes))
        rec["enabled"] = bool(enabled)
        _write(data)
        if not enabled:
            drop_sessions(key)


def set_password(username: str, password: str) -> None:
    """Set a new password (Admin resetting a user, or a user after the current one was checked)."""
    key = _key(username)
    _check_new_password(password)
    with _lock:
        data = json.loads(json.dumps(_read()))
        rec = data["users"].get(key)
        if rec is None:
            raise AuthError(f"User {username} does not exist.")
        rec["password"] = _hash(password)
        _write(data)
        _failures.pop(key, None)


def change_own_password(username: str, current: str, new: str) -> None:
    key = _key(username)
    with _lock:
        rec = _read()["users"].get(key)
        if rec is None or not _verify(current, rec.get("password", "")):
            raise AuthError("The current password is not correct.")
        set_password(username, new)


def delete_user(username: str) -> None:
    key = _key(username)
    if key == ADMIN:
        raise AuthError("The Admin account cannot be deleted.")
    with _lock:
        data = json.loads(json.dumps(_read()))
        if key not in data["users"]:
            raise AuthError(f"User {username} does not exist.")
        del data["users"][key]
        _write(data)
        drop_sessions(key)


# ----- sign in and sessions -----

def sign_in(username: str, password: str) -> tuple[str, dict]:
    """Check the password and open a session. Returns (token, user). Wrong name and wrong password look alike."""
    key = _key(username)
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(key, []) if now - t < LOCK_WINDOW]
        if len(recent) >= MAX_FAILURES and now - recent[-1] < LOCK_SECONDS:
            raise AuthError("Too many wrong passwords. Try again in a few minutes.")
        rec = _read()["users"].get(key)
        # Always run one hash so a missing user takes as long as a wrong password.
        ok = _verify(password, rec.get("password", "") if rec else _hash("x"))
        if not rec or not ok or not rec.get("enabled", True):
            recent.append(now)
            _failures[key] = recent
            raise AuthError("Wrong user name or password.")
        _failures.pop(key, None)
        token = secrets.token_urlsafe(32)
        _sessions[token] = {"user": key, "seen": now}
        return token, _public(key, rec)


def session_user(token: str) -> dict | None:
    """The user for a session token (and renews it), or None when the token is unknown, expired or the user is gone/disabled."""
    if not token:
        return None
    now = time.time()
    with _lock:
        sess = _sessions.get(token)
        if sess is None:
            return None
        rec = _read()["users"].get(sess["user"])
        if rec is None or not rec.get("enabled", True) or now - sess["seen"] > SESSION_IDLE_SECONDS:
            _sessions.pop(token, None)
            return None
        sess["seen"] = now
        return _public(sess["user"], rec)


def sign_out(token: str) -> None:
    with _lock:
        _sessions.pop(token, None)


def drop_sessions(username: str) -> None:
    key = _key(username)
    with _lock:
        for token in [t for t, s in _sessions.items() if s["user"] == key]:
            del _sessions[token]


# ----- page access -----

ALWAYS_OPEN = {"/", "/webex/callback"}  # every signed-in user (the callback is where the Webex login returns)


def can_open(user: dict | None, path: str) -> bool:
    """May this user open this page? Admin: everything. Others: the routes granted, a platform home page
    (`/cucm`) when anything below it is granted, never `/users`."""
    if user is None:
        return False
    if user["role"] == "admin":
        return True
    path = path.split("?")[0].rstrip("/") or "/"
    if path == "/index":  # Reflex names the home page route "index"
        path = "/"
    if path in ALWAYS_OPEN:
        return True
    if path == "/users":
        return False
    routes = user["routes"]
    if path in routes:
        return True
    return path.count("/") == 1 and any(r.startswith(path + "/") for r in routes)
