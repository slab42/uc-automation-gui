"""State for Webex > Reports > Locations Report."""

import asyncio
from datetime import datetime

import reflex as rx

from ..backend import webex_reports as R
from ..backend.errors import UserError
from .webex_routing import WebexSession


class LocationsReportState(WebexSession):
    rows: list[dict[str, str]] = []
    search: str = ""
    want_users: bool = True
    want_workspaces: bool = True
    result_users: bool = True  # what the rows on screen cover
    result_workspaces: bool = True
    loading: bool = False
    load_error: str = ""
    _result_org: str = ""  # org and instance the rows were read from

    @rx.var
    def shown(self) -> list[dict[str, str]]:
        q = self.search.strip().lower()
        return [r for r in self.rows if q in r["name"].lower()] if q else self.rows

    @rx.var
    def total_users(self) -> int:
        return sum(int(r["users"]) for r in self.rows)

    @rx.var
    def total_workspaces(self) -> int:
        return sum(int(r["workspaces"]) for r in self.rows)

    @rx.var
    def total_all(self) -> int:
        return self.total_users + self.total_workspaces

    @rx.var
    def both(self) -> bool:
        return self.result_users and self.result_workspaces

    @rx.event
    def set_want_users(self, value: bool):
        self.want_users = value

    @rx.event
    def set_want_workspaces(self, value: bool):
        self.want_workspaces = value

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    async def load_page(self):
        """Page load (also after an Org or Instance change, which reloads the page): drop results of another org."""
        await self._refresh_session()
        if self._result_org != self._org_key():
            self.rows, self.search, self.load_error = [], "", ""

    def _org_key(self) -> str:
        return f"{self.active_org}|{self.webex_active}"

    @rx.event
    async def run_report(self):
        if self.loading:
            return
        if not (self.want_users or self.want_workspaces):
            yield rx.toast.error("Select Users, Workspaces or both.")
            return
        await self._refresh_session()
        if not self.webex_ok:
            self.load_error = self.webex_message
            return
        users, workspaces = self.want_users, self.want_workspaces
        self.loading, self.load_error, self.rows = True, "", []
        yield
        log = self._webex_log("Locations report", "webex-locations-report")
        try:
            client = await self._connect(log)
            if client is None:
                self.load_error = self.webex_message
                return
            try:
                rows = await asyncio.to_thread(R.locations_report, client, users, workspaces, log.info)
            except UserError as e:
                self.load_error = str(e)
                log.error(str(e))
                return
            self._result_org = self._org_key()
            self.result_users, self.result_workspaces = users, workspaces
            self.rows = [{k: str(v) for k, v in r.items()} for r in rows]
            log.info(f"{len(rows)} row(s): {self.total_users} Calling user(s), "
                     f"{self.total_workspaces} Calling workspace(s)")
        finally:
            log.close()
            self.loading = False

    @rx.event
    def export_csv(self):
        if not self.rows:
            return rx.toast.error("Nothing to export.")
        rows = [{**r, "users": int(r["users"]), "workspaces": int(r["workspaces"]), "total": int(r["total"])}
                for r in self.rows]
        return rx.download(data=R.report_csv(rows, self.result_users, self.result_workspaces), filename=f"webex_locations_report_{datetime.now():%Y-%m-%d_%H-%M-%S}.csv")
