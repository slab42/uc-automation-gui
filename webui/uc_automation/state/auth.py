"""AuthState: sign in, first-run Admin setup, sign out, change own password.

The session token lives in browser LocalStorage so a reload keeps the user signed in, but it is only ever
trusted after `backend/users.session_user` has accepted it (see `auth_guard.py`, which checks it on every event).
Passwords sit in backend (`_`-prefixed) vars and are never sent to the browser or logged.
"""

import reflex as rx

from ..backend import users
from ..backend.applog import OpLog

# Reload the page once the token has reached LocalStorage so the page's own load events run signed in.
_RELOAD = "setTimeout(() => window.location.reload(), 250)"


def log_event(title: str, slug: str, *lines: str) -> None:
    """One short operation log (names only, never passwords)."""
    log = OpLog(title, slug)
    try:
        for line in lines:
            log.info(line)
    finally:
        log.close()


class AuthState(rx.State):
    token: str = rx.LocalStorage("", name="auth_token")
    checked: bool = False  # the session check for this page load has finished
    needs_setup: bool = False  # no Admin account yet
    username: str = ""  # signed-in user's display name ("" = not signed in)
    role: str = ""  # "admin" or "user"
    routes: list[str] = []  # pages an ordinary user may open

    login_name: str = ""
    error: str = ""
    form_key: int = 0  # bumped to clear the uncontrolled password inputs
    _password: str = ""
    _password2: str = ""

    # change my password dialog
    pw_open: bool = False
    pw_error: str = ""
    _pw_current: str = ""
    _pw_new: str = ""
    _pw_new2: str = ""

    # ----- what the pages read -----

    @rx.var
    def signed_in(self) -> bool:
        return bool(self.username)

    @rx.var
    def is_admin(self) -> bool:
        return self.role == "admin"

    @rx.var
    def routes_text(self) -> str:
        """The granted routes as one `|`-led string, for the platform checks (`|/cucm/`)."""
        return "".join("|" + r for r in self.routes)

    @rx.var
    def can_view(self) -> bool:
        """May the signed-in user open the page they are on?"""
        return users.can_open({"role": self.role, "routes": self.routes} if self.username else None,
                              self.router.url.path)

    # ----- helpers for other states -----

    def _user(self) -> dict | None:
        """The verified user behind this browser (re-checked against the session store every call)."""
        return users.session_user(self.token)

    def _apply(self, user: dict | None) -> None:
        self.username = user["username"] if user else ""
        self.role = user["role"] if user else ""
        self.routes = list(user["routes"]) if user else []

    # ----- setters -----

    @rx.event
    def set_login_name(self, value: str):
        self.login_name = value

    @rx.event
    def set_password(self, value: str):
        self._password = value

    @rx.event
    def set_password2(self, value: str):
        self._password2 = value

    @rx.event
    def set_pw_current(self, value: str):
        self._pw_current = value

    @rx.event
    def set_pw_new(self, value: str):
        self._pw_new = value

    @rx.event
    def set_pw_new2(self, value: str):
        self._pw_new2 = value

    # ----- session -----

    @rx.event
    def check_session(self):
        """Run when a page opens: is the stored token still a live session?"""
        self.needs_setup = users.needs_setup()
        self._apply(self._user())
        self.checked = True

    @rx.event
    def sign_in(self, _form: dict | None = None):
        name = self.login_name.strip()
        try:
            if not name or not self._password:
                raise users.AuthError("Enter your user name and password.")
            self.token, user = users.sign_in(name, self._password)
        except users.AuthError as e:
            self.error = str(e)
            self._password = ""
            self.form_key += 1
            log_event("Sign In", "sign-in", f"User: {name or '(blank)'}", f"Failed: {e}")
            return
        self._password = ""
        self.error = ""
        self.form_key += 1
        self._apply(user)
        log_event("Sign In", "sign-in", f"User: {user['username']}", "Signed in")
        return rx.call_script(_RELOAD)

    @rx.event
    def setup_admin(self, _form: dict | None = None):
        try:
            if self._password != self._password2:
                raise users.AuthError("The two passwords do not match.")
            users.create_admin(self._password)
            self.token, user = users.sign_in(users.ADMIN, self._password)
        except users.AuthError as e:
            self.error = str(e)
            self._password = self._password2 = ""
            self.form_key += 1
            return
        self._password = self._password2 = ""
        self.error = ""
        self.form_key += 1
        self.needs_setup = False
        self._apply(user)
        log_event("Set Up Admin Account", "admin-setup", "The Admin account was created")
        return rx.call_script(_RELOAD)

    @rx.event
    def sign_out(self):
        name = self.username
        users.sign_out(self.token)
        self.token = ""
        self._apply(None)
        if name:
            log_event("Sign Out", "sign-out", f"User: {name}")
        return rx.call_script(_RELOAD)

    # ----- change my password -----

    @rx.event
    def open_change_password(self):
        self._pw_current = self._pw_new = self._pw_new2 = ""
        self.pw_error = ""
        self.form_key += 1
        self.pw_open = True

    @rx.event
    def set_pw_open(self, value: bool):
        if value:
            self.open_change_password()
        else:
            self.close_change_password()

    @rx.event
    def close_change_password(self):
        self._pw_current = self._pw_new = self._pw_new2 = ""
        self.pw_open = False

    @rx.event
    def change_password(self, _form: dict | None = None):
        user = self._user()
        if user is None:
            return
        try:
            if self._pw_new != self._pw_new2:
                raise users.AuthError("The two new passwords do not match.")
            users.change_own_password(user["username"], self._pw_current, self._pw_new)
        except users.AuthError as e:
            self.pw_error = str(e)
            self._pw_current = self._pw_new = self._pw_new2 = ""
            self.form_key += 1
            log_event("Change Own Password", "change-password", f"User: {user['username']}", f"Failed: {e}")
            return
        self._pw_current = self._pw_new = self._pw_new2 = ""
        self.pw_open = False
        log_event("Change Own Password", "change-password", f"User: {user['username']}", "Password changed")
        return rx.toast.success("Password changed.")
