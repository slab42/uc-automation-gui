"""Customer organizations: the list, the organization window, and the organization chosen on the platform pages.

Every platform state (CUCM, CUC, CUBE, Webex, RedSky) is a child of OrgState, so the list of organizations and the
active organization are shared. A platform state filters its saved entries to the active organization."""

import re

import reflex as rx

from ..backend import organizations as orgs
from ..backend.applog import OpLog

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")


class OrgState(rx.State):
    org_names: list[str] = []  # saved organizations
    org_options: list[str] = []  # dropdown choices: org_names, plus Unassigned while some entry has no organization
    org_rows: list[dict[str, str]] = []  # name and entry count, for the Organizations tab
    active_org: str = rx.LocalStorage("")  # the choice made on the platform pages

    new_org_open: bool = False
    new_org_name: str = ""
    org_view: str = ""  # organization shown in the organization window ("" = window closed)
    plat_dialog: str = ""  # platform form open on top of the organization window ("" = none)

    def _load_orgs(self):
        self.org_names = orgs.list_names()
        self.org_options = orgs.options()
        self.org_rows = [{"name": n, "count": str(c)} for n, c in orgs.counts().items()]
        if self.active_org not in self.org_options:
            self.active_org = self.org_options[0] if self.org_options else ""

    def _default_org(self) -> str:
        """Organization preselected in an empty form."""
        return self.active_org if self.active_org in self.org_names else ""

    @rx.event
    def load_orgs(self):
        self._load_orgs()

    # --- Organizations tab ---

    @rx.event
    def set_new_org_open(self, value: bool):
        self.new_org_open = value
        if value:
            self.new_org_name = ""

    @rx.event
    def set_new_org_name(self, value: str):
        self.new_org_name = value.strip()

    @rx.event
    def create_org(self):
        name = self.new_org_name
        if not _NAME_RE.match(name):
            return rx.toast.error("Name must use letters, digits, '.', '_' or '-' (max 41 characters).")
        log = OpLog("Add organization", "org-add")
        try:
            log.info(f"Adding organization {name}")
            try:
                orgs.add(name)
            except ValueError as e:
                log.error(str(e))
                return rx.toast.error(str(e))
        finally:
            log.close()
        self._load_orgs()
        self.new_org_open = False
        return rx.toast.success(f"Added organization {name}")

    @rx.event
    def delete_org_by_name(self, name: str):
        log = OpLog("Delete organization", "org-delete")
        try:
            log.info(f"Deleting organization {name}")
            try:
                orgs.delete(name)
            except ValueError as e:
                log.error(str(e))
                return rx.toast.error(str(e))
        finally:
            log.close()
        self._load_orgs()
        self.org_view = ""
        return rx.toast.info(f"Deleted organization {name}")

    # --- organization window and the platform form on top of it ---

    @rx.event
    def open_org(self, name: str):
        self.org_view = name

    @rx.event
    def set_org_view_open(self, value: bool):
        if not value:
            self.org_view = ""
            self.plat_dialog = ""

    @rx.event
    def open_platform(self, platform: str):
        self.plat_dialog = platform

    @rx.event
    def set_plat_open(self, value: bool):
        if not value:
            self.plat_dialog = ""

    @rx.event
    def close_platform(self):
        self.plat_dialog = ""
