"""States for Webex > Call Routing: Add Numbers and Call Forward."""

import asyncio

from typing import Any

import reflex as rx

from ..backend import organizations as orgs, webex_auth, webex_routing as r
from ..backend.applog import OpLog
from ..backend.errors import UserError
from ..backend.paste import PastedFile, no_at_or_digit
from ..backend.webex_locations import list_locations
from ..backend.webex_api import WebexClient
from .org import OrgState
from .run_mixin import RunMixin

WEBEX_WORKERS = 4  # bulk rows sent to Webex at once (429 responses are retried by WebexClient)


class WebexSession(OrgState):
    """Active Webex org (and the login assigned to it), shown in the Webex menu bar.

    The login status is checked (and the token renewed) on every page load.
    Page states subclass this plus RunMixin, so busy/results stay per page."""

    webex_orgs: list[dict[str, str]] = []
    webex_logins: list[dict[str, str]] = []
    webex_active: str = rx.LocalStorage("")  # name of the saved org in use
    webex_memory: str = rx.LocalStorage("{}")  # JSON: instance last used per customer organization
    memory_field = "webex_memory"
    webex_ok: bool = False
    webex_message: str = ""
    webex_org: str = ""  # org id of the active org
    webex_login: str = ""  # login assigned to the active org

    @rx.var
    def webex_org_names(self) -> list[str]:
        """Saved Webex orgs of the active organization (what the menu bar offers)."""
        return [o["name"] for o in orgs.in_org(self.webex_orgs, self.active_org, self.org_names)]

    @rx.var
    def org_items(self) -> list[dict[str, str]]:
        """Saved Webex orgs of the organization open in the organization window."""
        return orgs.in_org(self.webex_orgs, self.org_view, self.org_names)

    @rx.var
    def saved_groups(self) -> list[dict[str, Any]]:
        """Every saved Webex org, grouped by organization."""
        return orgs.grouped(self.webex_orgs, self.org_names)

    @rx.var
    def webex_login_names(self) -> list[str]:
        return [x["name"] for x in self.webex_logins]

    @rx.var
    def webex_has_orgs(self) -> bool:
        return len(self.webex_orgs) > 0

    def _load_webex(self):
        self._load_orgs()
        self.webex_orgs = webex_auth.list_orgs()
        self.webex_logins = webex_auth.list_logins()
        names = self.webex_org_names
        if names and self.webex_active not in names:
            last = self._recall(self.active_org)
            self.webex_active = last if last in names else names[0]
        if not names:
            self.webex_active = ""
        active = next((o for o in self.webex_orgs if o["name"] == self.webex_active), None)
        self.webex_org = active["org_id"] if active else ""
        self.webex_login = active["login"] if active else ""

    async def _refresh_session(self):
        self._load_webex()
        if not self.webex_active:
            self.webex_ok, self.webex_message = False, "No Webex org yet. Add one on the Credentials page."
            return
        ok, msg = await asyncio.to_thread(webex_auth.check_org, self.webex_active)
        self.webex_ok, self.webex_message = ok, msg

    @rx.event
    async def on_page_load(self):
        await self._refresh_session()

    @rx.event
    def select_org(self, org: str):
        """Switch organization. The page reloads so it lists the data of the Webex org that follows."""
        self.active_org = org
        self._load_webex()
        return rx.call_script("setTimeout(() => window.location.reload(), 200)")

    @rx.event
    def select_webex_org(self, name: str):
        """Switch org. The page reloads so it lists the new org's data."""
        self.webex_active = name
        self._remember(name)
        return rx.call_script("setTimeout(() => window.location.reload(), 200)")

    async def _run_items(self, items, verb: str, log: OpLog, workers: int = WEBEX_WORKERS):
        """Bulk Webex rows run WEBEX_WORKERS at a time (RunMixin does the work)."""
        async for ev in super()._run_items(items, verb, log, workers):
            yield ev

    def _webex_log(self, title: str, slug: str) -> OpLog:
        log = OpLog(title, slug)
        own = "token owner's own org"
        log.info(f"Webex org: {self.webex_active} ({self.webex_org or own}), login: {self.webex_login}")
        return log

    async def _connect(self, log: OpLog):
        """A checked WebexClient, or None after showing why not (the caller then returns)."""
        try:
            return await asyncio.to_thread(WebexClient.connect, self.webex_active)
        except UserError as e:
            log.error(str(e))
            self.webex_ok, self.webex_message = False, str(e)
            return None


class PasteMixin(rx.State, mixin=True):
    """"Paste text" boxes: a state with a paste_<field> var includes this for set_paste and _from_paste.

    Must be a mixin: an event handler on the shared WebexSession parent would run against the parent, which
    has no paste_<field> vars."""

    @rx.event
    def set_paste(self, field: str, value: str):
        """Text of a "Paste text" box; the state holds it in a var named paste_<field>."""
        setattr(self, f"paste_{field}", value)

    async def _from_paste(self, handler, field: str, **options):
        """Run a "files" handler on the pasted text of paste_<field> as if it were an uploaded CSV."""
        text = getattr(self, f"paste_{field}", "")
        if not text.strip():
            yield rx.toast.error("Paste some text first.")
            return
        async for ev in handler([PastedFile(text, **options)]):
            yield ev


def _one(value: str | list[str]) -> str:
    return value if isinstance(value, str) else value[0]


class AddNumbersState(WebexSession, RunMixin):
    form_location: str = ""
    form_number: str = ""
    form_type: str = "DID"
    form_usage: str = "NONE"
    form_state: str = "ACTIVE"
    paste_text: str = ""
    location_names: list[str] = []

    @rx.event
    async def load_page(self):
        """Page load: check the login, then list the locations for the dropdown."""
        await self._refresh_session()
        if not self.webex_ok:
            return
        log = self._webex_log("List locations", "webex-list-locations")
        try:
            client = await self._connect(log)
            if client is None:
                return
            try:
                rows = await asyncio.to_thread(list_locations, client)
            except UserError as e:
                log.error(str(e))
                return
            self.location_names = [r_["name"] for r_ in rows]
            log.info(f"{len(rows)} location(s)")
        finally:
            log.close()

    @rx.event
    def set_paste_text(self, value: str):
        self.paste_text = value

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
        if self.location_names and row["locationId"].lower() not in {n.lower() for n in self.location_names}:
            yield rx.toast.error("Pick the location from the list.")
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

    @rx.event
    async def add_from_text(self):
        try:
            rows = r.parse_add_numbers_text(self.paste_text, self.form_location.strip())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The pasted text has no data rows.")
            return
        log = self._webex_log("Add numbers to locations from pasted text", "webex-add-numbers-text")
        try:
            async for ev in self._add(rows, log):
                yield ev
            if self.result_fail_count == 0 and self.results:
                self.paste_text = ""
        finally:
            log.close()


class CallForwardState(WebexSession, RunMixin, PasteMixin):
    cf_mode: str = "set"
    cf_prefix: str = r.DEFAULT_FORWARD_PREFIX
    cf_number: str = ""
    paste_forward: str = ""

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
        async for ev in self._run_csv(files):
            yield ev

    @rx.event
    async def run_text(self):
        async for ev in self._from_paste(self._run_csv, "forward", columns=("phoneNumber",), flatten=True,
                                         header_if=no_at_or_digit):
            yield ev

    async def _run_csv(self, files: list[rx.UploadFile]):
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
