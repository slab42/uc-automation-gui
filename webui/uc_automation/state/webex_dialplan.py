"""State for Webex > Call Routing > Gateway Dial Plan: create a dial plan, add dial patterns to one."""

import asyncio

from typing import ClassVar

import reflex as rx

from ..backend import webex_dialplan as D
from ..backend.applog import OpLog
from ..backend.errors import UserError
from .run_mixin import RunMixin
from .webex_groups import PickerMixin
from .webex_routing import PasteMixin, WebexSession

PATTERN_DISPLAY_LIMIT = 300
_PASTE = dict(columns=("pattern",), flatten=True, item_split=r"[\s,;|]+", markers=("pattern", "dialpattern"))


class GatewayDialPlanState(WebexSession, RunMixin, PickerMixin, PasteMixin):

    output_fields: ClassVar[tuple[str, ...]] = ("patterns", "chosen")
    routes: list[dict[str, str]] = []
    route_label: str = ""
    new_name: str = ""
    paste_create: str = ""
    paste_add: str = ""
    patterns: list[str] = []
    detail_loading: bool = False
    pattern_search: str = ""
    chosen: list[str] = []         # patterns ticked for deletion
    confirm_open: bool = False

    def _fetch_rows(self, client):
        return D.list_dial_plans(client)

    def _noun(self) -> str:
        return "dial plans"

    @rx.var
    def route_labels(self) -> list[str]:
        return [r["label"] for r in self.routes]

    @rx.var
    def filtered_patterns(self) -> list[str]:
        q = self.pattern_search.strip().lower()
        return [p for p in self.patterns if q in p.lower()] if q else self.patterns

    @rx.var
    def shown_patterns(self) -> list[str]:
        return self.filtered_patterns[:PATTERN_DISPLAY_LIMIT]

    @rx.event
    def set_pattern_search(self, value: str):
        self.pattern_search = value

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    def toggle_pattern(self, pattern: str, checked: bool):
        if checked and pattern not in self.chosen:
            self.chosen = [*self.chosen, pattern]
        elif not checked:
            self.chosen = [p for p in self.chosen if p != pattern]

    @rx.event
    def choose_matching(self):
        """Tick every pattern the search matches (not only the ones listed)."""
        self.chosen = list(dict.fromkeys([*self.chosen, *self.filtered_patterns]))

    @rx.event
    def choose_none(self):
        self.chosen = []

    @rx.event
    def set_route_label(self, value: str):
        self.route_label = value

    @rx.event
    def set_new_name(self, value: str):
        self.new_name = value

    async def _reload_all(self):
        self.patterns, self.chosen = [], []
        async for ev in self._load_rows():
            yield ev
        if not self.webex_ok:
            return
        log = self._webex_log("List trunks and route groups", "webex-list-routes")
        try:
            client = await self._connect(log)
            if client is None:
                return
            try:
                self.routes = await asyncio.to_thread(D.list_routes, client)
                if self.route_label not in self.route_labels:
                    self.route_label = ""
                log.info(f"{len(self.routes)} trunk(s) and route group(s) found")
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
        finally:
            log.close()

    @rx.event
    async def load_page(self):
        await self._refresh_session()
        if self.webex_ok:
            async for ev in self._reload_all():
                yield ev

    @rx.event
    async def reload(self):
        async for ev in self._reload_all():
            yield ev

    @rx.event
    async def select_row(self, row_id: str):
        self.selected_id = row_id
        self.patterns, self.results, self.chosen, self.pattern_search = [], [], [], ""
        if not self.has_selection:
            return
        self.detail_loading = True
        yield
        log = self._webex_log("Read dial patterns", "webex-read-dial-patterns")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                self.patterns = await asyncio.to_thread(D.list_patterns, client, row_id)
                log.info(f"{self.selected_row['name']}: {len(self.patterns)} dial pattern(s)")
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
        finally:
            log.close()
            self.detail_loading = False

    # --- Create ---

    @rx.event
    async def create_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._create(files):
            yield ev

    @rx.event
    async def create_from_text(self):
        async for ev in self._from_paste(self._create, "create", **_PASTE):
            yield ev

    async def _create(self, files: list[rx.UploadFile]):
        if self.busy:
            return
        route = next((r for r in self.routes if r["label"] == self.route_label), None)
        if not self.new_name.strip() or route is None:
            yield rx.toast.error("Enter a dial plan name and choose a trunk or route group.")
            return
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            patterns = D.parse_patterns_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        name = self.new_name.strip()
        log = self._webex_log("Create gateway dial plan", "webex-create-dial-plan")
        try:
            log.info(f"{name}: {len(patterns)} pattern(s) -> {route['label']}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            yield self._start_run([(name, lambda: D.create_dial_plan(client, name, route, patterns))],
                                  "Creating", log, then="_after_create")
        finally:
            log.close()

    def _after_create(self, log: OpLog):
        events = [rx.clear_selected_files("dp_create_upload")]
        if self.result_fail_count == 0 and self.results:
            self.paste_create, self.new_name = "", ""
            events.append(type(self).reload())
        return events

    # --- Add patterns to the selected plan ---

    @rx.event
    async def add_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._add(files):
            yield ev

    @rx.event
    async def add_from_text(self):
        async for ev in self._from_paste(self._add, "add", **_PASTE):
            yield ev

    async def _add(self, files: list[rx.UploadFile]):
        if self.busy:
            return
        plan = self.selected_row
        if not plan:
            yield rx.toast.error("Select a dial plan first.")
            return
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            patterns = D.parse_patterns_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        log = self._webex_log("Add dial patterns to gateway dial plan", "webex-add-dial-patterns")
        try:
            log.info(f"{plan['name']}: {len(patterns)} pattern(s)")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            yield self._start_run([(plan["name"], lambda: D.add_patterns(client, plan["id"], patterns))],
                                  "Adding", log, then="_after_add")
        finally:
            log.close()

    def _after_add(self, log: OpLog):
        events = [rx.clear_selected_files("dp_add_upload")]
        if self.result_fail_count == 0 and self.results:
            self.paste_add = ""
        # keep the result row: reread the patterns without clearing it
        return events + [type(self).refresh_patterns()]

    @rx.event
    async def refresh_patterns(self):
        if not self.has_selection:
            return
        log = self._webex_log("Read dial patterns", "webex-read-dial-patterns")
        try:
            client = await self._connect(log)
            if client is None:
                return
            try:
                self.patterns = await asyncio.to_thread(D.list_patterns, client, self.selected_id)
                self.chosen = [p for p in self.chosen if p in self.patterns]
            except UserError as e:
                log.error(str(e))
        finally:
            log.close()

    # --- Delete patterns from the selected plan ---

    @rx.event
    async def run_delete(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        plan = self.selected_row
        patterns = [p for p in self.patterns if p in self.chosen]
        if not plan or not patterns:
            yield rx.toast.error("Tick the dial patterns to delete first.")
            return
        log = self._webex_log("Delete dial patterns from gateway dial plan", "webex-delete-dial-patterns")
        try:
            log.info(f"{plan['name']}: {len(patterns)} pattern(s): {', '.join(patterns)}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            yield self._start_run([(plan["name"], lambda: D.delete_patterns(client, plan["id"], patterns))],
                                  "Deleting", log, then="_after_delete")
        finally:
            log.close()

    def _after_delete(self, log: OpLog):
        return [type(self).refresh_patterns()]
