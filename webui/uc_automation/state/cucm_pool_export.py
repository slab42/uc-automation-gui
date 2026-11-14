"""State for CUCM > Devices > Device Export for Webex."""

import asyncio
from datetime import datetime

from typing import ClassVar

import reflex as rx

from ..backend import cucm_pool_export as x
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from ..backend.webex_tools import get_supported_devices
from .cucm import CucmState
from .webex_routing import WebexSession


DEFAULT_LOCATION_REGEX = r"^(\w+)[_-](\w+)[_-]?.*"
DEFAULT_LOCATION_REPLACE = r"\1 \2"


class PoolExportState(CucmState):

    output_fields: ClassVar[tuple[str, ...]] = ("pools", "selected", "preview", "counts", "error", "warning", "progress", "_xlsx", "_result", "email_check")
    pool_search: str = ""
    pools: list[str] = []
    selected: list[str] = []
    registration: bool = True
    settings_open: bool = False
    location_field: str = rx.LocalStorage("Device Pool", name="pool_export_location_field")
    location_regex: str = rx.LocalStorage(DEFAULT_LOCATION_REGEX, name="pool_export_location_regex")
    location_replace_on: str = rx.LocalStorage("1", name="pool_export_location_replace_on")
    location_replace: str = rx.LocalStorage(DEFAULT_LOCATION_REPLACE, name="pool_export_location_replace")
    location_field_names: list[str] = list(x.LOCATION_FIELDS)
    excel_option_names: list[str] = list(x.EXCEL_OPTIONS)
    # Excel Output Options: comma separated names of the enabled options (browser LocalStorage, all off by default)
    excel_opts: str = rx.LocalStorage("", name="pool_export_excel_opts")
    searching: bool = False
    running: bool = False
    preview: list[dict[str, str]] = []
    counts: dict[str, str] = {}
    error: str = ""
    warning: str = ""
    progress: str = ""
    _xlsx: bytes = b""
    _result: dict = {}
    _build: tuple = ()
    email_check: str = ""
    validating: bool = False

    @rx.var
    def excel_on(self) -> list[str]:
        return [o for o in self.excel_opts.split(",") if o]

    @rx.event
    def set_settings_open(self, value: bool):
        self.settings_open = value

    @rx.event
    def toggle_excel_opt(self, name: str, checked: bool):
        on = [o for o in x.EXCEL_OPTIONS if (o in self.excel_on and o != name) or (o == name and checked)]
        self.excel_opts = ",".join(on)

    @rx.event
    def reset_excel_opts(self):
        self.excel_opts = ""
        self.location_field = "Device Pool"
        self.location_regex = DEFAULT_LOCATION_REGEX
        self.location_replace_on = "1"
        self.location_replace = DEFAULT_LOCATION_REPLACE

    @rx.event
    def set_location_replace_on(self, value: bool):
        self.location_replace_on = "1" if value else "0"

    @rx.event
    def set_location_replace(self, value: str):
        self.location_replace = value

    @rx.event
    def set_location_field(self, value: str):
        self.location_field = value

    @rx.event
    def set_location_regex(self, value: str):
        self.location_regex = value

    @rx.var
    def location_regex_error(self) -> str:
        return x.check_location_regex(self.location_regex, self.location_replace if self.location_replace_on == "1" else None)

    @rx.var
    def has_result(self) -> bool:
        return len(self.preview) > 0

    @rx.event
    def set_pool_search(self, value: str):
        self.pool_search = value

    @rx.event
    def set_registration(self, value: bool):
        self.registration = value

    @rx.event
    def toggle_pool(self, name: str, checked: bool):
        self.selected = [p for p in self.pools if (p in self.selected and p != name) or (p == name and checked)]

    @rx.event
    def toggle_all(self, checked: bool):
        self.selected = list(self.pools) if checked else []

    @rx.event
    def clear_result(self):
        self.preview = []
        self.counts = {}
        self.error = ""
        self.warning = ""
        self._xlsx = b""
        self._result = {}
        self.email_check = ""

    @rx.event
    async def search_pools(self):
        if self.searching or self.running:
            return
        conn = self._conn()
        if conn is None:
            return
        self.searching = True
        self.clear_result()
        yield
        try:
            found = await asyncio.to_thread(x.list_pools, conn, self.pool_search)
        except AxlError as e:
            self.error = str(e)
        except Exception as e:
            self.error = f"Unexpected error: {e}"
        else:
            self.pools = found
            self.selected = [p for p in self.selected if p in found]
            if not found:
                self.error = "No device pools match."
        finally:
            self.searching = False

    @rx.event
    async def run_export(self):
        conn = self._conn()
        if conn is None:
            return
        if not self.selected:
            self.error = "Select at least one device pool."
            return
        pools, registration = list(self.selected), self.registration
        options = set(self.excel_on)
        if self.location_regex_error:
            self.error = f"Webex Location settings: {self.location_regex_error}"
            return
        loc_field, loc_regex = self.location_field, self.location_regex
        loc_replace = self.location_replace if self.location_replace_on == "1" else None
        self.running = True
        self.clear_result()
        self.progress = ""
        yield
        log = OpLog("Device export for Webex", "device-export-webex")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Device pools: {', '.join(pools)}; registration: {'yes' if registration else 'no'}")
            log.info(f"Webex Location: {loc_field}" + (f" with regex {loc_regex}" if loc_regex else "")
                     + (f" replaced by {loc_replace!r}" if loc_replace is not None else ""))
            log.info(f"Excel output options: {', '.join(sorted(options)) or 'none'}")
            latest = {"msg": ""}

            def note(msg: str) -> None:
                latest["msg"] = msg
                log.info(msg)

            try:
                task = asyncio.create_task(asyncio.to_thread(x.pool_export, conn, pools, registration, note))
                while not task.done():
                    await asyncio.wait([task], timeout=1.5)
                    if latest["msg"] != self.progress:
                        self.progress = latest["msg"]
                        yield
                result = task.result()
                data = await asyncio.to_thread(x.build_workbook, result, None, options, registration, loc_field, loc_regex, loc_replace)
            except AxlError as e:
                self.error = str(e)
                log.error(f"Export failed: {e}")
            except ImportError:
                self.error = "openpyxl is not installed. Run python3 main.py --update."
                log.error("openpyxl is not installed")
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"Export failed unexpectedly: {e!r}")
            else:
                phones = result["phones"]
                self._xlsx = data
                self._result = result
                self._build = (options, registration, loc_field, loc_regex, loc_replace)
                self.preview = [{
                    "type": p["Type"], "name": p["Device Name"], "model": p["Device Type"], "pool": p["Device Pool"],
                    "user": p["User ID"], "email": p["Email"], "source": p["Owner Source"],
                    "lines": ", ".join(ln["DN"] for ln in p["lines"][:4]) + (" ..." if len(p["lines"]) > 4 else ""),
                } for p in phones]
                users = sum(1 for p in phones if p["Type"] == "User")
                self.counts = {"phones": str(len(phones)), "users": str(users), "workspaces": str(len(phones) - users),
                               "blfs": str(len(result["blfs"])), "errors": str(len(result["errors"]))}
                if result["errors"]:
                    self.warning = f"{len(result['errors'])} item(s) could not be read. See the Errors sheet."
                    log.warning(self.warning)
                if not result["reg_complete"]:
                    self.warning += " RisPort70 rate limit reached: registration is partial."
                    log.warning("Registration incomplete (rate limit)")
                if not phones:
                    self.error = "No phones found in the selected device pools."
                log.info(f"{len(phones)} phone(s), {users} user(s), {len(phones) - users} workspace(s)")
        finally:
            log.close()
            self.running = False
            self.progress = ""

    @rx.event
    async def validate_emails(self):
        if not self._result or self.validating or self.running:
            return
        emails = [p["Email"] for p in self._result["phones"] if p["Email"].strip()]
        ws = await self.get_state(WebexSession)
        await ws._refresh_session()
        if not ws.webex_active:
            self.error = f"No Webex org is saved for the organization {self.active_org or '(none)'}. Add one on the Credentials page."
            return
        if not ws.webex_ok:
            self.error = f"Webex org {ws.webex_active}: {ws.webex_message}"
            return
        self.validating = True
        self.error = ""
        self.email_check = ""
        yield
        log = ws._webex_log("Validate emails in Webex", "device-export-webex-validate")
        try:
            client = await ws._connect(log)
            if client is None:
                self.error = ws.webex_message or "Could not connect to Webex."
                return
            log.info(f"{len(emails)} phone email(s) to check")
            supported = set(await asyncio.to_thread(get_supported_devices, client))
            log.info(f"{len(supported)} supported Webex device name(s) loaded")
            latest = {"msg": ""}

            def note(msg: str) -> None:
                latest["msg"] = msg
                log.info(msg)

            task = asyncio.create_task(asyncio.to_thread(x.missing_in_webex, client, emails, note))
            while not task.done():
                await asyncio.wait([task], timeout=1.5)
                if latest["msg"] != self.progress:
                    self.progress = latest["msg"]
                    yield
            missing, failed = task.result()
            no_email = sum(1 for p in self._result["phones"] if p["User ID"].strip() and not p["Email"].strip())
            self._xlsx = await asyncio.to_thread(x.build_workbook, self._result, None, *self._build, missing, supported)
            distinct = len({e.strip().lower() for e in emails})
            self.email_check = f"{len(missing)} of {distinct} email addresses not found in Webex (highlighted Bad in the Email column)."
            if no_email:
                self.email_check += f" {no_email} phone(s) have a User ID but no email (also highlighted)."
            bad_models = sorted({p["Device Type"] for p in self._result["phones"]
                                 if p["Device Type"].strip().lower() not in supported})
            if bad_models:
                self.email_check += (f" {len(bad_models)} device type(s) are not supported by Webex "
                                     f"(highlighted Bad in the Device Type column): {', '.join(bad_models)}.")
                log.warning(f"Unsupported device types: {', '.join(bad_models)}")
            for m in sorted(missing):
                log.warning(f"Not in Webex: {m}")
            if failed:
                self.warning = f"{len(failed)} email(s) could not be checked: {failed[0]}"
                for f in failed:
                    log.error(f)
        except Exception as e:
            self.error = f"Email validation failed: {e}"
            log.error(f"Email validation failed: {e!r}")
        finally:
            log.close()
            self.validating = False
            self.progress = ""

    @rx.event
    def download_workbook(self):
        if not self._xlsx:
            return rx.toast.error("Nothing to download. Run the export first.")
        server = (self.active_info or {}).get("server", "cucm")
        stamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
        return rx.download(data=self._xlsx, filename=f"device-export-webex-{server}-{stamp}.xlsx")

    @rx.event
    async def switch_connection(self, name: str):
        self.active = name
        self._remember(name)
        await self._clear_outputs(whole_org=False)

    @rx.event
    async def switch_org(self, org: str):
        self.active_org = org
        self._reconcile()
        await self._clear_outputs(whole_org=True)
