"""States for Webex > Call Routing: Add Numbers and Call Forward."""

import asyncio

import reflex as rx

from ..backend import webex_auth, webex_routing as r
from ..backend.applog import OpLog
from ..backend.errors import UserError
from ..backend.webex_api import WebexClient
from .run_mixin import RunMixin


class WebexSession(rx.State):
    """Login status shown in the Webex menu bar, checked (and the token renewed) on every page load.

    Page states subclass this plus RunMixin, so busy/results stay per page."""

    webex_ok: bool = False
    webex_message: str = ""
    webex_org: str = ""

    async def _refresh_session(self):
        self.webex_org = webex_auth.saved_org_id()
        ok, msg = await asyncio.to_thread(webex_auth.check)
        self.webex_ok, self.webex_message = ok, msg

    @rx.event
    async def on_page_load(self):
        await self._refresh_session()

    def _webex_log(self, title: str, slug: str) -> OpLog:
        log = OpLog(title, slug)
        log.info("Webex org: " + (self.webex_org or "(token owner's own org)"))
        return log

    async def _connect(self, log: OpLog):
        """A checked WebexClient, or None after showing why not (the caller then returns)."""
        try:
            return await asyncio.to_thread(WebexClient.connect)
        except UserError as e:
            log.error(str(e))
            self.webex_ok, self.webex_message = False, str(e)
            return None


def _one(value: str | list[str]) -> str:
    return value if isinstance(value, str) else value[0]


class AddNumbersState(WebexSession, RunMixin):
    form_location: str = ""
    form_number: str = ""
    form_type: str = "DID"
    form_usage: str = "NONE"
    form_state: str = "ACTIVE"

    @rx.event
    def set_form_location(self, value: str):
        self.form_location = value

    @rx.event
    def set_form_number(self, value: str):
        self.form_number = value

    @rx.event
    def set_form_type(self, value: str):
        self.form_type = value

    @rx.event
    def set_form_usage(self, value: str):
        self.form_usage = value

    @rx.event
    def set_form_state(self, value: str):
        self.form_state = value

    async def _add(self, rows: list[dict[str, str]], log: OpLog):
        client = await self._connect(log)
        if client is None:
            yield rx.toast.error(self.webex_message)
            return
        cache: dict[str, str] = {}
        items = [(r_["phoneNumber"], lambda r_=r_: r.add_number(client, r_, cache)) for r_ in rows]
        async for ev in self._run_items(items, "Adding", log):
            yield ev

    @rx.event
    async def add_single(self):
        row = {"locationId": self.form_location.strip(), "phoneNumber": self.form_number.strip(),
               "numberType": self.form_type, "numberUsageType": self.form_usage, "state": self.form_state}
        if not row["locationId"] or not row["phoneNumber"]:
            yield rx.toast.error("Enter the location and the phone number.")
            return
        log = self._webex_log("Add number to location", "webex-add-number")
        try:
            async for ev in self._add([row], log):
                yield ev
            if self.result_fail_count == 0 and self.results:
                self.form_number = ""
        finally:
            log.close()

    @rx.event
    async def add_from_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = r.parse_add_numbers_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        log = self._webex_log("Add numbers to locations from CSV", "webex-add-numbers-csv")
        try:
            log.info(f"CSV file: {files[0].filename}")
            async for ev in self._add(rows, log):
                yield ev
            yield rx.clear_selected_files("numbers_upload")
        finally:
            log.close()


class CallForwardState(WebexSession, RunMixin):
    cf_mode: str = "set"
    cf_prefix: str = r.DEFAULT_FORWARD_PREFIX
    cf_number: str = ""

    @rx.event
    def set_cf_mode(self, value: str | list[str]):
        self.cf_mode = _one(value)
        self.results = []

    @rx.event
    def set_cf_prefix(self, value: str):
        self.cf_prefix = value.strip()

    @rx.event
    def set_cf_number(self, value: str):
        self.cf_number = value

    async def _forward(self, numbers: list[str], log: OpLog):
        enable = self.cf_mode == "set"
        prefix = self.cf_prefix
        if enable and not prefix:
            yield rx.toast.error("Enter the forward prefix.")
            return
        client = await self._connect(log)
        if client is None:
            yield rx.toast.error(self.webex_message)
            return
        log.info(f"Forward all: {'set with prefix ' + prefix if enable else 'remove'}")
        items = [(n, lambda n=n: r.set_call_forward_all(client, n, enable, prefix)) for n in numbers]
        async for ev in self._run_items(items, "Setting forward" if enable else "Removing forward", log):
            yield ev

    def _log(self) -> OpLog:
        if self.cf_mode == "set":
            return self._webex_log("Call forward all set", "webex-call-forward-set")
        return self._webex_log("Call forward all remove", "webex-call-forward-remove")

    @rx.event
    async def run_single(self):
        number = self.cf_number.strip()
        if not number:
            yield rx.toast.error("Enter a phone number.")
            return
        log = self._log()
        try:
            async for ev in self._forward([number], log):
                yield ev
            if self.result_fail_count == 0 and self.results:
                self.cf_number = ""
        finally:
            log.close()

    @rx.event
    async def run_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            numbers = r.parse_number_list_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not numbers:
            yield rx.toast.error("The CSV has no data rows.")
            return
        log = self._log()
        try:
            log.info(f"CSV file: {files[0].filename}")
            async for ev in self._forward(numbers, log):
                yield ev
            yield rx.clear_selected_files("forward_upload")
        finally:
            log.close()
