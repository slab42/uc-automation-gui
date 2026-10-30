"""CUBE router credential sets (credentials page)."""

import re

import reflex as rx

from ..backend import cube_credentials, organizations as orgs
from ..backend.applog import OpLog
from .org import OrgState

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")


class CubeState(OrgState):
    credentials: list[dict[str, str]] = []

    # Form (password is a backend var so it is never sent to the browser)
    form_name: str = ""
    form_username: str = ""
    form_org: str = ""
    _password: str = ""
    password_key: int = 0
    form_has_password: bool = False

    @rx.var
    def credential_names(self) -> list[str]:
        return [c["name"] for c in self.credentials]

    @rx.var
    def org_items(self) -> list[dict[str, str]]:
        """Saved credential sets of the organization open in the organization window."""
        return orgs.in_org(self.credentials, self.org_view, self.org_names)

    @rx.var
    def saved_rows(self) -> list[dict[str, str]]:
        """Every saved credential set, grouped by organization (heading rows have kind org)."""
        return orgs.grouped(self.credentials, self.org_names)

    @rx.event
    def load_credentials(self):
        self.credentials = cube_credentials.list_public()
        self._load_orgs()

    @rx.event
    def edit_credential(self, name: str):
        c = next((c for c in self.credentials if c["name"] == name), None)
        if not c:
            return
        self.form_name = c["name"]
        self.form_username = c["username"]
        self.form_org = c.get("org", "")
        self.form_has_password = c["has_password"] == "yes"
        self._password = ""
        self.password_key += 1

    @rx.event
    def new_credential(self):
        self.form_name = self.form_username = ""
        self.form_org = self._default_org()
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
        if self.form_org not in self.org_names:
            return "Choose an organization. Create one on the Credentials > Organizations tab first."
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
            log.info(f"Saving credential set {self.form_name} as {self.form_username} in organization {self.form_org}")
            cube_credentials.save(self.form_name, self.form_username, self._password, org=self.form_org)
        finally:
            log.close()
        self.form_has_password = True
        self._password = ""
        self.password_key += 1
        self.credentials = cube_credentials.list_public()
        self._load_orgs()
        self.plat_dialog = ""  # closes the form when it was opened from an organization window
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
        self._load_orgs()
        if self.form_name == name:
            self.new_credential()
        return rx.toast.info(f"Deleted {name}")
