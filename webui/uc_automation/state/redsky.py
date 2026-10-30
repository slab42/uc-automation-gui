"""RedSky connection management (credentials page)."""

import asyncio
import re

import reflex as rx

from ..backend import redsky_api, redsky_connections
from ..backend.applog import OpLog
from ..backend.redsky_connections import RedskyConnection

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")


class RedskyState(rx.State):
    connections: list[dict[str, str]] = []
    active: str = rx.LocalStorage("")

    # Form (password is a backend var so it is never sent to the browser)
    form_name: str = ""
    form_username: str = ""
    form_org_id: str = ""
    _password: str = ""
    password_key: int = 0
    form_has_password: bool = False

    testing: bool = False
    test_ok: bool = False
    test_message: str = ""

    @rx.var
    def connection_names(self) -> list[str]:
        return [c["name"] for c in self.connections]

    @rx.var
    def has_active(self) -> bool:
        return self.active in self.connection_names

    def _conn(self) -> RedskyConnection | None:
        """The active connection with its stored credentials (backend only), or None."""
        return redsky_connections.load(self.active) if self.active else None

    def _tool_log(self, title: str, slug: str, conn: RedskyConnection | None) -> OpLog:
        """An operation log with the connection line (never the password)."""
        log = OpLog(title, slug)
        if conn is not None:
            log.info(f"Connection: {conn.name} as {conn.username}, org {conn.org_id}")
        return log

    @rx.event
    def load_connections(self):
        self.connections = redsky_connections.list_public()
        names = self.connection_names
        if names and self.active not in names:
            self.active = names[0]
        if not names:
            self.active = ""

    @rx.event
    def select_active(self, name: str):
        self.active = name

    def _reset_test(self):
        self.test_ok = False
        self.test_message = ""

    @rx.event
    def edit_connection(self, name: str):
        c = next((c for c in self.connections if c["name"] == name), None)
        if not c:
            return
        self.form_name = c["name"]
        self.form_username = c["username"]
        self.form_org_id = c["org_id"]
        self.form_has_password = c["has_password"] == "yes"
        self._password = ""
        self.password_key += 1
        self._reset_test()

    @rx.event
    def new_connection(self):
        self.form_name = self.form_username = self.form_org_id = ""
        self.form_has_password = False
        self._password = ""
        self.password_key += 1
        self._reset_test()

    @rx.event
    def set_form(self, field: str, value: str):
        setattr(self, f"form_{field}", value.strip())
        self._reset_test()

    @rx.event
    def set_password(self, value: str):
        self._password = value

    def _validate(self) -> str:
        if not _NAME_RE.match(self.form_name):
            return "Name must use letters, digits, '.', '_' or '-' (max 41 characters)."
        if not self.form_username:
            return "Username is required."
        if not self._password and not self.form_has_password:
            return "Password is required."
        if not self.form_org_id:
            return "Organization ID is required."
        return ""

    def _after_save(self):
        self.form_has_password = True
        self._password = ""
        self.password_key += 1
        self.connections = redsky_connections.list_public()
        if not self.active:
            self.active = self.form_name

    @rx.event
    def save_connection(self):
        err = self._validate()
        if err:
            return rx.toast.error(err)
        log = OpLog("Save RedSky connection", "redsky-credentials-save")
        try:
            log.info(f"Saving connection {self.form_name} as {self.form_username}, org {self.form_org_id}")
            redsky_connections.save(self.form_name, self.form_username, self._password, self.form_org_id)
        finally:
            log.close()
        self._after_save()
        return rx.toast.success(f"Saved {self.form_name}")

    @rx.event
    async def test_connection(self):
        err = self._validate()
        if err:
            yield rx.toast.error(err)
            return
        password = self._password
        if not password:
            stored = redsky_connections.load(self.form_name)
            password = stored.password if stored else ""
        if not password:
            yield rx.toast.error("No stored password for this connection. Enter one.")
            return
        self.testing = True
        self._reset_test()
        yield
        log = OpLog("Test RedSky connection", "redsky-credentials-test")
        try:
            log.info(f"Testing connection {self.form_name} as {self.form_username}, org {self.form_org_id}")
            try:
                count = await asyncio.to_thread(
                    redsky_api.check_login, self.form_username, password, self.form_org_id)
            except redsky_api.RedskyError as e:
                self.testing = False
                self.test_message = str(e)
                log.error(f"Test failed: {e}")
                return
            except Exception as e:  # unexpected: show it rather than hang the spinner
                self.testing = False
                self.test_message = f"Unexpected error: {e}"
                log.error(f"Test failed unexpectedly: {e!r}")
                return
            redsky_connections.save(self.form_name, self.form_username, self._password, self.form_org_id)
            self._after_save()
            self.testing = False
            self.test_ok = True
            self.test_message = f"Connected. Organization has {count} building(s). Saved."
            log.info(self.test_message)
        finally:
            log.close()

    @rx.event
    def delete_connection(self, name: str):
        log = OpLog("Delete RedSky connection", "redsky-credentials-delete")
        try:
            log.info(f"Deleting connection {name}")
            redsky_connections.delete(name)
        finally:
            log.close()
        self.connections = redsky_connections.list_public()
        if self.active == name:
            self.active = self.connections[0]["name"] if self.connections else ""
        if self.form_name == name:
            self.new_connection()
        return rx.toast.info(f"Deleted {name}")
