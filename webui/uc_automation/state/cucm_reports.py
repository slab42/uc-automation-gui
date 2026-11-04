"""State for CUCM > Reports > Device Report."""

import asyncio
import csv
import io
from datetime import datetime

import reflex as rx

from ..backend import cucm_reports as r
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from .cucm import CucmState

MODES = ["All Device Pools", "Search"]


class DeviceReportState(CucmState):
    mode: str = MODES[0]
    pool_search: str = ""
    running: bool = False
    report_rows: list[dict[str, str]] = []
    skipped: int = 0
    error: str = ""

    @rx.var
    def modes(self) -> list[str]:
        return MODES

    @rx.var
    def totals(self) -> dict[str, str]:
        keys = ("registered", "unregistered", "total", "gateways")
        return {k: f"{sum(int(x[k]) for x in self.report_rows):,}" for k in keys}

    @rx.event
    def set_mode(self, value: str | list[str]):
        self.mode = value if isinstance(value, str) else value[0]

    @rx.event
    def set_pool_search(self, value: str):
        self.pool_search = value

    @rx.event
    def clear_report(self):
        self.report_rows = []
        self.error = ""

    @rx.event
    async def run_report(self):
        conn = self._conn()
        if conn is None:
            return
        pool_filter = self.pool_search if self.mode == "Search" else ""
        if self.mode == "Search" and not pool_filter.strip():
            self.error = "Enter part of a device pool name to search for."
            return
        self.running = True
        self.error = ""
        yield
        log = OpLog("Device report", "device-report")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Device pools: {pool_filter.strip() or 'all'}")
            try:
                rows, skipped = await asyncio.to_thread(r.device_report, conn, pool_filter)
            except AxlError as e:
                self.error = str(e)
                log.error(f"Report failed: {e}")
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"Report failed unexpectedly: {e!r}")
            else:
                self.report_rows, self.skipped = rows, skipped
                if not rows:
                    self.error = "No device pools match."
                log.info(f"{len(rows)} device pool(s); {skipped} analog/CTI devices skipped")
                for x in rows:
                    log.debug(f"{x['devicePool']}: registered {x['registered']}, unregistered {x['unregistered']}, "
                              f"gateways {x['gateways']}")
        finally:
            log.close()
            self.running = False

    @rx.event
    def export_csv(self):
        if not self.report_rows:
            return rx.toast.error("Nothing to export. Run the report first.")
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["device_pool", "registered", "unregistered", "total_devices", "gateways"])
        for x in self.report_rows:
            w.writerow([x["devicePool"], x["registered"], x["unregistered"], x["total"], x["gateways"]])
        server = (self.active_info or {}).get("server", "cucm")
        stamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
        return rx.download(data=buf.getvalue(), filename=f"device-report-{server}-{stamp}.csv")

    @rx.event
    def switch_connection(self, name: str):
        self.active = name
        self._remember(name)
        self.clear_report()

    @rx.event
    def switch_org(self, org: str):
        self.active_org = org
        self._reconcile()
        self.clear_report()
