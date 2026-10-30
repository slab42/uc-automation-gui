"""CUBE router credential sets (credentials page)."""

import re

import reflex as rx

from ..backend import cube_credentials
from ..backend.applog import OpLog

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")


class CubeState(rx.State):
    credentials: list[dict[str, str]] = []

    # Form (password is a backend var so it is never sent to the browser)
    form_name: str = ""
    form_username: str = ""
    _password: str = ""
    password_key: int = 0
    form_has_password: bool = False

    @rx.var
    def credential_names(self) -> list[str]:
        return [c["name"] for c in self.credentials]

    @rx.event
    def load_credentials(self):
        self.credentials = cube_credentials.list_public()

    @rx.event
    def edit_credential(self, name: str):
        c = next((c for c in self.credentials if c["name"] == name), None)
        if not c:
            return
        self.form_name = c["name"]
        self.form_username = c["username"]
        self.form_has_password = c["has_password"] == "yes"
        self._password = ""
        self.password_key += 1

    @rx.event
    def new_credential(self):
        self.form_name = self.form_username = ""
        self.form_has_password = False
        self._password = ""
        self.password_key += 1

    @rx.event
    def set_form(self, field: str, value: str):
        setattr(self, f"form_{field}", value.strip())

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
        return ""

    @rx.event
    def save_credential(self):
        err = self._validate()
        if err:
            return rx.toast.error(err)
        log = OpLog("Save CUBE credentials", "cube-credentials-save")
        try:
            log.info(f"Saving credential set {self.form_name} as {self.form_username}")
            cube_credentials.save(self.form_name, self.form_username, self._password)
        finally:
            log.close()
        self.form_has_password = True
        self._password = ""
        self.password_key += 1
        self.credentials = cube_credentials.list_public()
        return rx.toast.success(f"Saved {self.form_name}")

    @rx.event
    def delete_credential(self, name: str):
        log = OpLog("Delete CUBE credentials", "cube-credentials-delete")
        try:
            log.info(f"Deleting credential set {name}")
            cube_credentials.delete(name)
        finally:
            log.close()
        self.credentials = cube_credentials.list_public()
        if self.form_name == name:
            self.new_credential()
        return rx.toast.info(f"Deleted {name}")
