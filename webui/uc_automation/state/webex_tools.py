"""State for Webex > Tools: Check Hardware Compatibility."""

import asyncio
from datetime import datetime

import reflex as rx

from ..backend import webex_tools as t
from ..backend.errors import UserError
from .webex_routing import PasteMixin, WebexSession


class HardwareCompatState(WebexSession, PasteMixin):
    form_model: str = ""
    form_mac: str = ""
    model_names: list[str] = []
    checking: bool = False
    checks: list[dict[str, str]] = []
    file_name: str = ""
    paste_hardware: str = ""

    @rx.var
    def valid_count(self) -> int:
        return sum(1 for r in self.checks if r["status"] == "VALID")

    @rx.var
    def warning_count(self) -> int:
        return sum(1 for r in self.checks if r["status"] == "WARNING")

    @rx.var
    def invalid_count(self) -> int:
        return sum(1 for r in self.checks if r["status"] == "INVALID")

    @rx.event
    def set_form(self, field: str, value: str):
        setattr(self, f"form_{field}", value)

    @rx.event
    async def load_page(self):
        """Page load: check the login, then fetch the supported models for the model suggestions."""
        await self._refresh_session()
        if not self.webex_ok:
            return
        log = self._webex_log("List supported devices", "webex-supported-devices")
        try:
            client = await self._connect(log)
            if client is None:
                return
            try:
                devices = await asyncio.to_thread(t.get_supported_devices, client)
            except UserError as e:
                log.error(str(e))
                return
            self.model_names = t.model_names(devices)
            log.info(f"{len(self.model_names)} supported model(s)")
        finally:
            log.close()

    async def _check(self, rows: list[dict[str, str]], log):
        self.checking = True
        self.checks = []
        yield
        client = await self._connect(log)
        if client is None:
            self.checking = False
            yield rx.toast.error(self.webex_message)
            return
        try:
            devices = await asyncio.to_thread(t.get_supported_devices, client)
            self.model_names = t.model_names(devices)
            self.checks = await asyncio.to_thread(t.check_phones, client, rows, devices)
        except UserError as e:
            log.error(str(e))
            yield rx.toast.error(str(e))
        else:
            for r in self.checks:
                {"VALID": log.info, "WARNING": log.warning}.get(r["status"], log.error)(f"Row {r['row']}: {r['reason']}")
            log.info(f"Valid {self.valid_count}, warnings {self.warning_count}, invalid {self.invalid_count}")
        finally:
            self.checking = False

    @rx.event
    async def check_single(self):
        model, mac = self.form_model.strip(), self.form_mac.strip()
        if not model or not mac:
            yield rx.toast.error("Enter the model and the MAC address.")
            return
        log = self._webex_log("Check hardware compatibility", "webex-hardware-check")
        try:
            async for ev in self._check([{"row": "1", "model": model, "mac": mac}], log):
                yield ev
        finally:
            log.close()

    @rx.event
    async def check_csv(self, files: list[rx.UploadFile]):
        async for ev in self._check_csv(files):
            yield ev

    @rx.event
    async def check_text(self):
        async for ev in self._from_paste(self._check_csv, "hardware", columns=("model", "mac"),
                                         markers=("model", "mac")):
            yield ev

    async def _check_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = t.parse_phone_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        self.file_name = files[0].filename or ""
        log = self._webex_log("Check hardware compatibility from CSV", "webex-hardware-check-csv")
        try:
            log.info(f"CSV file: {self.file_name}, {len(rows)} row(s)")
            async for ev in self._check(rows, log):
                yield ev
            yield rx.clear_selected_files("hardware_upload")
        finally:
            log.close()

    @rx.event
    def export_csv(self):
        if not self.checks:
            return rx.toast.error("Nothing to export.")
        return rx.download(data=t.results_csv(self.checks),
                           filename=f"{datetime.now():%Y-%m-%d_%H-%M-%S}-phone_compatibility_results.csv")
