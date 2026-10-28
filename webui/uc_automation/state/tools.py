"""States for CUCM > Tools: EM bulk login, phone count by device pool, set user PIN."""

import asyncio
import csv
import io
from datetime import datetime

import reflex as rx

from ..backend import cucm_tools as t
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from ..backend.cucm_connections import CucmConnection
from .cucm import CucmState


class _RunMixin(rx.State, mixin=True):
    """busy / progress / per-row results shared by the tools that run a list of items."""

    busy: bool = False
    progress: str = ""
    results: list[dict[str, str]] = []

    @rx.var
    def result_ok_count(self) -> int:
        return sum(1 for r in self.results if r["status"] == "OK")

    @rx.var
    def result_fail_count(self) -> int:
        return sum(1 for r in self.results if r["status"] != "OK")

    async def _run_items(self, items: list[tuple[str, object]], verb: str, log: OpLog):
        """items: (label, zero-argument callable returning a detail string or None). Runs each in a thread."""
        self.busy = True
        self.results = []
        log.info(f"{verb}: {len(items)} item(s)")
        for i, (label, fn) in enumerate(items, 1):
            self.progress = f"{verb} {i} of {len(items)}"
            yield
            try:
                detail = await asyncio.to_thread(fn)
                self.results.append({"key": label, "status": "OK", "detail": detail or "Done"})
                log.info(f"{label}: OK - {detail or 'Done'}")
            except AxlError as e:
                self.results.append({"key": label, "status": "Failed", "detail": str(e)})
                log.error(f"{label}: Failed - {e}")
            except Exception as e:
                self.results.append({"key": label, "status": "Failed", "detail": f"Unexpected error: {e}"})
                log.error(f"{label}: Failed unexpectedly - {e!r}")
        log.info(f"{verb} finished: {self.result_ok_count} OK, {self.result_fail_count} failed")
        self.progress = ""
        self.busy = False

    def _tool_log(self, title: str, slug: str, conn: CucmConnection | None) -> OpLog:
        log = OpLog(title, slug)
        if conn is not None:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
        return log


class EmBulkState(CucmState, _RunMixin):
    em_mode: str = "login"
    em_server: str = ""

    @rx.var
    def em_mode_help(self) -> str:
        return {
            "login": "Logs each user in on their device. Needs the device, user and pin columns.",
            "logout": "Logs out whoever is on each device. Needs the device column.",
            "check": "Checks that each user is logged in on their device (read from CUCM). Needs device and user.",
        }[self.em_mode]

    @rx.var
    def em_template(self) -> str:
        return {
            "login": "device,user,pin\nSEPDC0539FB8FA2,jsmith,159357\n",
            "logout": "device\nSEPDC0539FB8FA2\n",
            "check": "device,user\nSEPDC0539FB8FA2,jsmith\n",
        }[self.em_mode]

    @rx.var
    def uses_em_server(self) -> bool:
        return self.em_mode != "check"

    @rx.event
    def set_em_mode(self, value: str):
        self.em_mode = value
        self.results = []

    @rx.event
    def set_em_server(self, value: str):
        self.em_server = value.strip()

    @rx.event
    async def run_em(self, files: list[rx.UploadFile]):
        conn = self._conn()
        mode = self.em_mode
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = t.parse_em_csv(await files[0].read(), mode)
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        if mode == "check" and conn is None:
            yield rx.toast.error("Add a CUCM connection first (Check reads the phones from CUCM).")
            return
        try:
            server = t.check_em_server(self.em_server or (conn.server if conn else ""))
        except AxlError as e:
            if mode != "check":
                yield rx.toast.error(str(e) if self.em_server or conn else "Enter the Extension Mobility server.")
                return
            server = ""
        log = self._tool_log(f"EM bulk {mode}", f"em-bulk-{mode}", conn)
        try:
            log.info(f"CSV file: {files[0].filename}" + (f", EM server: {server}" if mode != "check" else ""))
            if mode == "check":
                items = [(f"{r['device']} / {r['user']}", lambda r=r: t.em_check(conn, r["device"], r["user"]))
                         for r in rows]
            elif mode == "login":
                items = [(f"{r['device']} / {r['user']}",
                          lambda r=r: t.em_request(server, "login", r["device"], r["user"], r["pin"])) for r in rows]
            else:
                items = [(r["device"], lambda r=r: t.em_request(server, "logout", r["device"])) for r in rows]
            async for ev in self._run_items(items, {"login": "Logging in", "logout": "Logging out",
                                                    "check": "Checking"}[mode], log):
                yield ev
            yield rx.clear_selected_files("em_upload")
        finally:
            log.close()


class PhoneCountState(CucmState):
    include_analog: bool = False
    counting: bool = False
    counted_for: str = ""
    pool_rows: list[dict[str, str]] = []
    total_phones: int = 0
    excluded_count: int = 0
    search: str = ""
    error: str = ""

    @rx.var
    def filtered_rows(self) -> list[dict[str, str]]:
        q = self.search.strip().lower()
        return [r for r in self.pool_rows if q in r["devicePool"].lower()] if q else self.pool_rows

    @rx.var
    def total_label(self) -> str:
        return f"{self.total_phones:,}"

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    async def set_include_analog(self, value: bool):
        self.include_analog = value
        async for ev in self._count():
            yield ev

    @rx.event
    async def on_page_load(self):
        """Count as soon as the page opens (rows from an earlier visit stay on screen until the new count lands)."""
        self.load_connections()
        if self.active != self.counted_for:
            self.pool_rows = []
            self.total_phones = 0
        async for ev in self._count():
            yield ev

    @rx.event
    async def run_count(self):
        async for ev in self._count():
            yield ev

    async def _count(self):
        conn = self._conn()
        if conn is None:
            return
        self.counting = True
        self.error = ""
        yield
        log = OpLog("Phone count by device pool", "phone-count-by-dp")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Include analog and CTI devices: {self.include_analog}")
            try:
                rows, total, excluded = await asyncio.to_thread(t.count_phones_by_pool, conn, self.include_analog)
            except AxlError as e:
                self.error = str(e)
                log.error(f"Count failed: {e}")
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"Count failed unexpectedly: {e!r}")
            else:
                self.pool_rows, self.total_phones, self.excluded_count = rows, total, excluded
                self.counted_for = self.active
                log.info(f"{total} phone(s) in {len(rows)} device pool(s); {excluded} analog/CTI excluded")
                for r in rows:
                    log.debug(f"{r['devicePool']}: {r['phoneCount']}")
        finally:
            log.close()
            self.counting = False

    @rx.event
    def export_csv(self):
        if not self.pool_rows:
            return rx.toast.error("Nothing to export. Run the count first.")
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["device_pool", "phone_count"])
        for r in self.pool_rows:
            w.writerow([r["devicePool"], r["phoneCount"]])
        server = (self.active_info or {}).get("server", "cucm")
        stamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
        return rx.download(data=buf.getvalue(), filename=f"phone-count-{server}-{stamp}.csv")

    @rx.event
    async def switch_connection(self, name: str):
        self.active = name
        self.pool_rows = []
        self.total_phones = 0
        self.error = ""
        async for ev in self._count():
            yield ev


class SetPinState(CucmState, _RunMixin):
    pin_user: str = ""
    _pin: str = ""          # backend var: never sent to the browser
    pin_key: int = 0

    @rx.event
    def set_pin_user(self, value: str):
        self.pin_user = value.strip()

    @rx.event
    def set_pin_value(self, value: str):
        self._pin = value

    @rx.event
    async def set_single(self):
        conn = self._conn()
        user, pin = self.pin_user, self._pin
        if conn is None:
            return
        if not user or not pin:
            yield rx.toast.error("Enter the user ID and the PIN.")
            return
        log = self._tool_log("Set user PIN", "set-user-pin", conn)
        try:
            async for ev in self._run_items([(user, lambda: t.set_user_pin(conn, user, pin))], "Setting PIN", log):
                yield ev
            if self.result_fail_count == 0:
                self._pin = ""
                self.pin_user = ""
                self.pin_key += 1
        finally:
            log.close()

    @rx.event
    async def set_from_csv(self, files: list[rx.UploadFile]):
        conn = self._conn()
        if conn is None:
            return
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = t.parse_pin_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        log = self._tool_log("Set user PIN from CSV", "set-user-pin-csv", conn)
        try:
            log.info(f"CSV file: {files[0].filename}")
            items = [(r["user"], lambda r=r: t.set_user_pin(conn, r["user"], r["pin"])) for r in rows]
            async for ev in self._run_items(items, "Setting PIN", log):
                yield ev
            yield rx.clear_selected_files("pin_upload")
        finally:
            log.close()
