"""State for Webex > Devices > Bulk ATA/VG."""

import asyncio

import reflex as rx

from ..backend import webex_workspaces as w
from ..backend.errors import UserError
from ..backend.webex_locations import list_locations
from ..backend.webex_tools import get_supported_devices, model_import_rows
from .run_mixin import RunMixin
from .webex_routing import PasteMixin, WebexSession


class BulkAtaState(WebexSession, RunMixin, PasteMixin):
    form_location: str = ""
    form_model: str = ""
    form_mac: str = ""
    form_ports: str = ""
    location_names: list[str] = []
    model_rows: list[dict[str, str]] = []
    paste_ata: str = ""

    @rx.event
    def set_form(self, field: str, value: str):
        setattr(self, f"form_{field}", value)

    @rx.event
    async def load_page(self):
        """Page load: check the login, then list the locations and supported models for the dropdowns."""
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
            self.location_names = [r["name"] for r in rows]
            log.info(f"{len(rows)} location(s)")
            try:
                devices = await asyncio.to_thread(get_supported_devices, client)
                self.model_rows = model_import_rows(devices)
                log.info(f"{len(self.model_rows)} supported model(s)")
            except UserError as e:
                log.warning(f"Supported models not loaded: {e}")
        finally:
            log.close()

    async def _add(self, devices: list[dict], log):
        client = await self._connect(log)
        if client is None:
            yield rx.toast.error(self.webex_message)
            return
        cache: dict[str, str] = {}
        items = [(d["mac"], lambda d=d: w.add_ata(client, d, cache)) for d in devices]
        async for ev in self._run_items(items, "Adding", log):
            yield ev

    @rx.event
    async def add_single(self):
        location = self.form_location.strip()
        rows = w.port_rows_from_text(self.form_ports, self.form_mac.strip(), self.form_model.strip(), location)
        if not (location and self.form_model.strip() and self.form_mac.strip() and rows):
            yield rx.toast.error("Enter the location, the model, the MAC address and at least one port.")
            return
        if self.location_names and location.lower() not in {n.lower() for n in self.location_names}:
            yield rx.toast.error("Pick the location from the list.")
            return
        log = self._webex_log("Add ATA/VG", "webex-add-ata")
        try:
            async for ev in self._add(w.group_ata_rows(rows), log):
                yield ev
            if self.result_fail_count == 0 and self.results:
                self.form_mac = ""
                self.form_ports = ""
        finally:
            log.close()

    @rx.event
    async def add_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._add_from_csv(files):
            yield ev

    @rx.event
    async def add_from_text(self):
        async for ev in self._from_paste(self._add_from_csv, "ata", columns=w.ATA_COLUMNS,
                                         markers=("mac", "workspace")):
            yield ev

    async def _add_from_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = w.parse_ata_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        log = self._webex_log("Add ATA/VG from CSV", "webex-add-ata-csv")
        try:
            log.info(f"CSV file: {files[0].filename}")
            async for ev in self._add(w.group_ata_rows(rows), log):
                yield ev
            yield rx.clear_selected_files("ata_upload")
        finally:
            log.close()
