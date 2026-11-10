"""State for Webex > Reports > SME Pattern Check."""

import asyncio
from datetime import datetime
from typing import ClassVar

import reflex as rx

from ..backend import cucm_connections, cucm_sme_patterns as sme, organizations as orgs, webex_sme_check as R
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from ..backend.cucm_sme_patterns import require_sme
from ..backend.errors import UserError
from .run_mixin import RunMixin
from .sme_settings import SmeSettingsMixin
from .webex_routing import WebexSession


class SmeCheckState(WebexSession, RunMixin, SmeSettingsMixin):

    output_fields: ClassVar[tuple[str, ...]] = ("rows", "selected", "result_partition", "_result_org")
    rows: list[dict[str, str]] = []
    search: str = ""
    status_filter: str = "All"
    selected: list[str] = []
    confirm_open: bool = False
    use_regex: bool = False
    regex_source: str = "Location"
    result_partition: str = ""
    loading: bool = False
    load_error: str = ""
    cucm_saved: list[dict[str, str]] = []
    _result_org: str = ""

    @rx.var
    def sme_names(self) -> list[str]:
        """SME clusters among the organization's saved CUCM connections."""
        return [c["name"] for c in orgs.in_org(self.cucm_saved, self.active_org, self.org_names)
                if c.get("sme") == "yes"]

    @rx.var
    def sme_selected(self) -> str:
        names = self.sme_names
        return names[0] if names else ""

    @rx.var
    def status_options(self) -> list[str]:
        return ["All", R.ANY_MISSING] + R.STATUSES

    @rx.var
    def shown(self) -> list[dict[str, str]]:
        q = self.search.strip().lower()
        return [r for r in self.rows
                if (self.status_filter == "All" or r["status"] == self.status_filter
                     or (self.status_filter == R.ANY_MISSING and r["status"] != R.STATUS_ALL))
                and (not q or q in r["number"].lower() or q in r["location"].lower() or q in r["owner"].lower())]

    @rx.var
    def used_var_rows(self) -> list[dict[str, str]]:
        """The variables the descriptions use (the ones this page asks a value for)."""
        used = sme.used_vars([self.adv_desc, self.rp_desc], self.var_names)
        return [r for i, r in enumerate(self.var_rows) if i in used]

    @rx.var
    def sources(self) -> list[str]:
        return R.SOURCES

    @rx.var
    def selectable(self) -> list[str]:
        """Shown numbers that miss an Advertised Pattern or a Route Pattern."""
        return [r["number"] for r in self.shown if r["status"] != R.STATUS_ALL]

    @rx.var
    def selected_count(self) -> int:
        """Selected numbers that still miss something."""
        missing = {r["number"] for r in self.rows if r["status"] != R.STATUS_ALL}
        return sum(1 for n in self.selected if n in missing)

    @rx.var
    def all_selected(self) -> bool:
        return bool(self.selectable) and all(n in self.selected for n in self.selectable)

    @rx.var
    def counts(self) -> dict[str, int]:
        return {s: sum(1 for r in self.rows if r["status"] == s) for s in R.STATUSES}

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    def set_status_filter(self, value: str):
        self.status_filter = value

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    def set_use_regex(self, value: bool):
        self.use_regex = value

    @rx.event
    def set_regex_source(self, value: str):
        self.regex_source = value

    @rx.event
    def select_row(self, number: str, checked: bool):
        rest = [n for n in self.selected if n != number]
        self.selected = rest + [number] if checked else rest

    @rx.event
    def select_all(self, checked: bool):
        """Select (or clear) every shown number that is missing a pattern."""
        shown = set(self.selectable)
        rest = [n for n in self.selected if n not in shown]
        self.selected = rest + self.selectable if checked else rest

    def _org_key(self) -> str:
        return f"{self.active_org}|{self.webex_active}"

    @rx.event
    async def load_page(self):
        await self._refresh_session()
        self.cucm_saved = cucm_connections.list_public()
        self._load_orgs()
        if self._result_org != self._org_key():
            self.rows, self.selected, self.search, self.load_error = [], [], "", ""

    @rx.event
    async def run_report(self):
        if self.loading:
            return
        await self._refresh_session()
        if not self.webex_ok:
            self.load_error = self.webex_message
            return
        try:
            sme = require_sme(cucm_connections.load(self.sme_selected) if self.sme_selected else None)
        except AxlError as e:
            self.load_error = str(e)
            return
        partition = self.rp_partition.strip()
        if not partition:
            self.load_error = "Set the Route Pattern partition in the Webex Cutover settings first."
            return
        self.loading, self.load_error, self.rows, self.selected = True, "", [], []
        yield
        log = self._webex_log("SME pattern check", "webex-sme-pattern-check")
        try:
            log.info(f"SME cluster: {sme.name} ({sme.server}) as {sme.username}, Route Pattern partition: {partition}")
            client = await self._connect(log)
            if client is None:
                self.load_error = self.webex_message
                return
            try:
                numbers = await asyncio.to_thread(R.list_webex_numbers, client, log.info)
                log.info(f"{len(numbers)} Webex number(s)")
                rows = await asyncio.to_thread(R.check_numbers, sme, partition, numbers, log.info)
            except (UserError, AxlError) as e:
                self.load_error = str(e)
                log.error(str(e))
                return
            self._result_org = self._org_key()
            self.result_partition = partition
            self.rows = rows
            log.info(", ".join(f"{s}: {self.counts[s]}" for s in R.STATUSES))
        finally:
            log.close()
            self.loading = False

    @rx.event
    def export_csv(self):
        if not self.rows:
            return rx.toast.error("Nothing to export.")
        return rx.download(data=R.report_csv(self.rows, self.result_partition),
                           filename=f"webex_sme_pattern_check_{datetime.now():%Y-%m-%d_%H-%M-%S}.csv")

    @rx.event
    def ask_update(self):
        if self.busy or self.selected_count == 0:
            return rx.toast.error("Select at least one number that is missing a pattern.")
        self.confirm_open = True

    @rx.event
    def run_update(self):
        """Create the missing Advertised Patterns and Route Patterns of the selected numbers on the SME cluster."""
        self.confirm_open = False
        if self.busy:
            return
        try:
            conn = sme.require_sme(cucm_connections.load(self.sme_selected) if self.sme_selected else None)
        except AxlError as e:
            return rx.toast.error(str(e))
        if err := self.settings_error:
            return rx.toast.error(err)
        settings, names = {k: getattr(self, k) for k in sme.DEFAULTS}, self.var_names
        values = [self.form_values.get(sme.var_key(i), "").strip() for i in range(len(names))]
        for i in sorted(sme.used_vars([settings["adv_desc"], settings["rp_desc"]], names)):
            if not values[i]:
                return rx.toast.error(f"Enter a value for {sme.var_display(i, names)}.")
        use_regex, source = self.use_regex, self.regex_source
        if use_regex:
            if err := R.check_value_regexes(values):
                return rx.toast.error(err)
        elif err := sme.check_values(values, names, self.var_regexes):
            return rx.toast.error(err)
        picked = set(self.selected)
        todo = [r for r in self.rows if r["number"] in picked and r["status"] != R.STATUS_ALL]
        if not todo:
            return rx.toast.error("Select at least one number that is missing a pattern.")
        log = OpLog("SME pattern check add missing patterns", "webex-sme-pattern-check-add")
        try:
            log.info(f"SME cluster: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"{len(todo)} number(s) selected")
            for k, v in settings.items():
                log.info(f"Setting {k}: {v}")
            if use_regex:
                log.info(f"Variable values are regexes on the {source}: {values}")
            items = [(r["number"], lambda r=r: self._add_row(conn, settings, names, values, r, use_regex, source))
                     for r in todo]
            return self._start_run(items, "Adding", log, then="_after_update")
        finally:
            log.close()

    def _add_row(self, conn, settings, names, values, row, use_regex, source) -> str:
        """Runs in a thread: with regex values, resolve them from this row first (a failed validation regex or a
        non-matching regex fails only this row)."""
        if use_regex:
            values = R.values_from_row(values, row, source)
            if err := sme.check_values(values, names, self.var_regexes, row["number"]):
                raise UserError(err)
        return sme.add_missing_patterns(conn, settings, names, row["number"], values,
                                        row["adv_found"] == "No", row["rp_found"] == "No")

    def _after_update(self, log: OpLog):
        """Mark the numbers that were fixed. A number that failed part way keeps its old status: run the report again."""
        done = {r["key"] for r in self.results if r["status"] == "OK"}
        self.rows = [{**r, "adv_found": "Yes", "rp_found": "Yes", "status": R.STATUS_ALL} if r["number"] in done else r
                     for r in self.rows]
        self.selected = [n for n in self.selected if n not in done]
