"""State for CUCM > Reports > Device Report."""

import asyncio
import csv
import io
import re
from datetime import datetime

from typing import ClassVar

import reflex as rx

from ..backend import cucm_reports as r
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from .cucm import CucmState

MODES = ["All Device Pools", "Search"]
GROUPINGS = ["Off", "Prefix", "Regex"]


class DeviceReportState(CucmState):

    output_fields: ClassVar[tuple[str, ...]] = ("raw_rows", "error", "warning", "progress")
    mode: str = MODES[0]
    pool_search: str = ""
    running: bool = False
    raw_rows: list[dict[str, str]] = []
    grouping: str = GROUPINGS[0]
    group_delimiter: str = "-"
    group_parts: str = "2"
    group_regex: str = ""
    kinds: list[str] = list(r.KINDS)
    registration: bool = True
    error: str = ""
    warning: str = ""
    progress: str = ""

    @rx.var
    def modes(self) -> list[str]:
        return MODES

    @rx.var
    def groupings(self) -> list[str]:
        return GROUPINGS

    @rx.var
    def group_error(self) -> str:
        if self.grouping == "Regex" and self.group_regex:
            try:
                re.compile(self.group_regex)
            except re.error as e:
                return f"Invalid regular expression: {e}"
        return ""

    @rx.var
    def report_rows(self) -> list[dict[str, str]]:
        """The report rows, consolidated by the chosen grouping (no re-query when it changes)."""
        if self.grouping == "Off" or not self.raw_rows or self.group_error:
            return [{**x, "pools": "1"} for x in self.raw_rows]
        parts = int(self.group_parts) if self.group_parts.isdigit() else 0
        return r.consolidate_rows(self.raw_rows, lambda n: r.pool_group_key(
            n, self.grouping, self.group_delimiter, parts, self.group_regex))

    @rx.var
    def all_kinds(self) -> list[str]:
        return r.KINDS

    @rx.var
    def totals(self) -> dict[str, str]:
        return {k: f"{sum(int(x[k]) for x in self.report_rows if x[k]):,}" if self.report_rows[0][k] != "" else ""
                for k in ("registered", "unregistered", "total", "gateways")} if self.report_rows else {}

    @rx.var
    def reg_available(self) -> bool:
        """Registration only applies to phones, analog phones and CTI devices."""
        return any(k != "Gateways" for k in self.kinds)

    @rx.var
    def show_reg(self) -> bool:
        return bool(self.report_rows) and self.report_rows[0]["registered"] != ""

    @rx.event
    def toggle_kind(self, kind: str, checked: bool):
        self.kinds = [k for k in r.KINDS if (k in self.kinds and k != kind) or (k == kind and checked)]

    @rx.event
    def set_registration(self, value: bool):
        self.registration = value

    @rx.event
    def set_mode(self, value: str | list[str]):
        self.mode = value if isinstance(value, str) else value[0]

    @rx.event
    def set_grouping(self, value: str | list[str]):
        self.grouping = value if isinstance(value, str) else value[0]

    @rx.event
    def set_group_delimiter(self, value: str):
        self.group_delimiter = value

    @rx.event
    def set_group_parts(self, value: str):
        self.group_parts = value

    @rx.event
    def set_group_regex(self, value: str):
        self.group_regex = value

    @rx.event
    def set_pool_search(self, value: str):
        self.pool_search = value

    @rx.event
    def clear_report(self):
        self.raw_rows = []
        self.error = ""
        self.warning = ""

    @rx.event
    async def run_report(self):
        if self.running:
            return
        conn = self._conn()
        if conn is None:
            return
        pool_filter = self.pool_search if self.mode == "Search" else ""
        if self.mode == "Search" and not pool_filter.strip():
            self.error = "Enter part of a device pool name to search for."
            return
        if not self.kinds:
            self.error = "Select at least one kind of device."
            return
        kinds, registration = list(self.kinds), self.registration and self.reg_available
        self.running = True
        self.error = ""
        self.warning = ""
        self.progress = ""
        yield
        log = OpLog("Device report", "device-report")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Device pools: {pool_filter.strip() or 'all'}")
            log.info(f"Devices: {', '.join(kinds)}; registration: {'yes' if registration else 'no'}")
            latest = {"msg": ""}

            def note(msg: str) -> None:
                latest["msg"] = msg
                log.info(msg)

            try:
                task = asyncio.create_task(asyncio.to_thread(
                    r.device_report, conn, pool_filter, kinds, registration, note))
                while not task.done():
                    await asyncio.wait([task], timeout=1.5)
                    if latest["msg"] != self.progress:
                        self.progress = latest["msg"]
                        yield
                rows, complete = task.result()
            except AxlError as e:
                self.error = str(e)
                log.error(f"Report failed: {e}")
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"Report failed unexpectedly: {e!r}")
            else:
                self.raw_rows = rows
                if not complete:
                    self.warning = ("RisPort70 rate limit reached (15 requests per minute). Registered counts are partial "
                                    "and Unregistered is blank. Try again later, or filter to fewer device pools.")
                    log.warning(self.warning)
                if not rows:
                    self.error = "No device pools match."
                log.info(f"{len(rows)} device pool(s)")
                for x in rows:
                    log.debug(f"{x['devicePool']}: registered {x['registered']}, unregistered {x['unregistered']}, "
                              f"gateways {x['gateways']}")
        finally:
            log.close()
            self.running = False
            self.progress = ""

    @rx.event
    def export_csv(self):
        if not self.report_rows:
            return rx.toast.error("Nothing to export. Run the report first.")
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        grouped = self.grouping != "Off" and not self.group_error
        w.writerow(["device_pool", *(["pools"] if grouped else []), "registered", "unregistered", "total_devices", "gateways"])
        for x in self.report_rows:
            w.writerow([x["devicePool"], *([x["pools"]] if grouped else []), x["registered"], x["unregistered"], x["total"], x["gateways"]])
        server = (self.active_info or {}).get("server", "cucm")
        stamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
        return rx.download(data=buf.getvalue(), filename=f"device-report-{server}-{stamp}.csv")

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
