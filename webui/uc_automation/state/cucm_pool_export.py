"""State for CUCM > Reports > Device Pool Export."""

import asyncio
from datetime import datetime

import reflex as rx

from ..backend import cucm_pool_export as x
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from .cucm import CucmState


class PoolExportState(CucmState):
    pool_search: str = ""
    pools: list[str] = []
    selected: list[str] = []
    registration: bool = False
    searching: bool = False
    running: bool = False
    preview: list[dict[str, str]] = []
    counts: dict[str, str] = {}
    error: str = ""
    warning: str = ""
    progress: str = ""
    _xlsx: bytes = b""

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
    def select_all(self):
        self.selected = list(self.pools)

    @rx.event
    def select_none(self):
        self.selected = []

    @rx.event
    def clear_result(self):
        self.preview = []
        self.counts = {}
        self.error = ""
        self.warning = ""
        self._xlsx = b""

    @rx.event
    async def search_pools(self):
        conn = self._conn()
        if conn is None:
            return
        self.searching = True
        self.error = ""
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
        self.running = True
        self.clear_result()
        self.progress = ""
        yield
        log = OpLog("Device pool export", "device-pool-export")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Device pools: {', '.join(pools)}; registration: {'yes' if registration else 'no'}")
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
                data = await asyncio.to_thread(x.build_workbook, result)
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
    def download_workbook(self):
        if not self._xlsx:
            return rx.toast.error("Nothing to download. Run the export first.")
        server = (self.active_info or {}).get("server", "cucm")
        stamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
        return rx.download(data=self._xlsx, filename=f"device-pool-export-{server}-{stamp}.xlsx")

    @rx.event
    def switch_connection(self, name: str):
        self.active = name
        self._remember(name)
        self.pools = []
        self.selected = []
        self.clear_result()

    @rx.event
    def switch_org(self, org: str):
        self.active_org = org
        self._reconcile()
        self.pools = []
        self.selected = []
        self.clear_result()
