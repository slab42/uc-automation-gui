"""CUCM connection management (credentials page) and the active-connection selector."""

import asyncio
import re

import reflex as rx

from ..backend import cucm_axl, cucm_connections
from ..backend.applog import OpLog

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")


class CucmState(rx.State):
    connections: list[dict[str, str]] = []
    active: str = rx.LocalStorage("")

    # Form (password is a backend var so it is never sent to the browser)
    form_name: str = ""
    form_server: str = ""
    form_username: str = ""
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
    def active_info(self) -> dict[str, str]:
        for c in self.connections:
            if c["name"] == self.active:
                return c
        return {}

    @rx.var
    def has_active(self) -> bool:
        return bool(self.active_info)

    @rx.var
    def active_label(self) -> str:
        c = self.active_info
        if not c:
            return ""
        return f"CUCM {c['version']}" if c.get("version") else "version unknown"

    # --- loading / selection ---

    @rx.event
    def load_connections(self):
        self.connections = cucm_connections.list_public()
        names = self.connection_names
        if names and self.active not in names:
            self.active = names[0]
        if not names:
            self.active = ""

    @rx.event
    def select_active(self, name: str):
        self.active = name

    @rx.event
    def edit_connection(self, name: str):
        c = next((c for c in self.connections if c["name"] == name), None)
        if not c:
            return
        self.form_name = c["name"]
        self.form_server = c["server"]
        self.form_username = c["username"]
        self.form_has_password = c["has_password"] == "yes"
        self._password = ""
        self.password_key += 1
        self.test_ok = False
        self.test_message = ""

    @rx.event
    def new_connection(self):
        self.form_name = self.form_server = self.form_username = ""
        self.form_has_password = False
        self._password = ""
        self.password_key += 1
        self.test_ok = False
        self.test_message = ""

    @rx.event
    def set_form(self, field: str, value: str):
        setattr(self, f"form_{field}", value.strip())
        self.test_ok = False
        self.test_message = ""

    @rx.event
    def set_password(self, value: str):
        self._password = value

    # --- actions ---

    def _validate(self) -> str:
        if not _NAME_RE.match(self.form_name):
            return "Name must use letters, digits, '.', '_' or '-' (max 41 characters)."
        if not self.form_server:
            return "IP address or hostname is required."
        if not self.form_username:
            return "Username is required."
        if not self._password and not self.form_has_password:
            return "Password is required."
        return ""

    @rx.event
    def save_connection(self):
        err = self._validate()
        if err:
            return rx.toast.error(err)
        log = OpLog("Save connection", "credentials-save")
        try:
            log.info(f"Saving connection {self.form_name} ({self.form_server}) as {self.form_username}")
            cucm_connections.save(self.form_name, self.form_server, self.form_username, self._password)
            cucm_axl.forget(self.form_server)
        finally:
            log.close()
        self._after_save()
        return rx.toast.success(f"Saved {self.form_name}")

    def _after_save(self):
        self.form_has_password = True
        self._password = ""
        self.password_key += 1
        self.connections = cucm_connections.list_public()
        if not self.active:
            self.active = self.form_name

    @rx.event
    async def test_connection(self):
        err = self._validate()
        if err:
            yield rx.toast.error(err)
            return
        password = self._password
        if not password:
            stored = cucm_connections.load(self.form_name)
            password = stored.password if stored else ""
        if not password:
            yield rx.toast.error("No stored password for this connection. Enter one.")
            return
        self.testing = True
        self.test_ok = False
        self.test_message = ""
        yield
        log = OpLog("Test connection", "credentials-test")
        try:
            log.info(f"Testing connection {self.form_name} ({self.form_server}) as {self.form_username}")
            try:
                full, major = await asyncio.to_thread(
                    cucm_axl.detect_version, self.form_server, self.form_username, password)
                schema = cucm_axl.pick_schema(major)
            except cucm_axl.AxlError as e:
                self.testing = False
                self.test_message = str(e)
                log.error(f"Test failed: {e}")
                return
            except Exception as e:  # unexpected: show it rather than hang the spinner
                self.testing = False
                self.test_message = f"Unexpected error: {e}"
                log.error(f"Test failed unexpectedly: {e!r}")
                return
            cucm_connections.save(self.form_name, self.form_server, self.form_username,
                                  self._password, version=major, schema_version=schema)
            cucm_axl.forget(self.form_server)
            self._after_save()
            self.testing = False
            self.test_ok = True
            note = "" if schema == major else f" (no {major} schema installed, using {schema})"
            self.test_message = f"Connected. CUCM {full}. Schema major release {major}{note}. Saved."
            log.info(self.test_message)
        finally:
            log.close()

    @rx.event
    def delete_connection(self, name: str):
        log = OpLog("Delete connection", "credentials-delete")
        try:
            log.info(f"Deleting connection {name}")
            cucm_connections.delete(name)
        finally:
            log.close()
        self.connections = cucm_connections.list_public()
        if self.active == name:
            self.active = self.connections[0]["name"] if self.connections else ""
        if self.form_name == name:
            self.new_connection()
        return rx.toast.info(f"Deleted {name}")
