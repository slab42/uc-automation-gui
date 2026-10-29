"""States for CUC > Call Handlers: Map, List, Delete."""

import asyncio
from datetime import datetime

import reflex as rx

from ..backend import cuc_api, cuc_handlers as h
from .cuc import CucRun, CucState
from .cuc_users import AllRows
from .webex_routing import PasteMixin

PREVIEW_LIMIT = 300


def _stamp() -> str:
    return datetime.now().strftime("%Y_%m_%d-%H_%M_%S")


class ListHandlersState(CucState, AllRows):
    """Every call handler (system and subscriber handlers left out), searchable, with Export Selected."""

    menu_busy: bool = False
    menu_errors: list[dict[str, str]] = []
    confirm_open: bool = False

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    async def delete_selected(self):
        """Delete the ticked call handlers, then reload the list."""
        self.confirm_open = False
        conn = self._conn()
        rows = self._selected_rows()
        if conn is None or not rows:
            return
        log = self._tool_log("Delete call handlers", "cuc-delete-handlers", conn)
        try:
            log.info(f"{len(rows)} call handler(s) ticked in the list")
            client = cuc_api.CucClient(conn)
            items = [(r["displayName"] or r["objectId"],
                      lambda r=r: client.delete_call_handler(r["objectId"]) or "Deleted") for r in rows]
            async for ev in self._run_items(items, "Deleting", log):
                yield ev
        finally:
            log.close()
        async for ev in self._load_all():
            yield ev

    def _read_all(self, client):
        handlers, _ = h.list_handlers(client)
        return handlers, []

    def _load_label(self):
        return "List call handlers", "cuc-list-handlers"

    def _search_fields(self):
        return ("displayName", "extension")

    @rx.event
    async def auto_load(self):
        """Page load: read all call handlers, quietly skipping when there is no connection yet."""
        if self._conn() is not None and not self.all_loading:
            async for ev in self._load_all():
                yield ev

    @rx.event
    def export_selected(self):
        rows = self._selected_rows()
        if not rows:
            return rx.toast.error("Tick the call handlers to export first.")
        return rx.download(data=h.to_csv(rows, h.HANDLER_FIELDS),
                           filename=f"callhandlers-{self.all_for}-{_stamp()}.csv")

    @rx.event
    async def export_menu_entries(self):
        """Read the menu entries of the ticked call handlers from CUC and download them as the Map input CSV."""
        conn = self._conn()
        rows = self._selected_rows()
        if conn is None or not rows:
            yield rx.toast.error("Tick the call handlers first.")
            return
        self.menu_busy, self.menu_errors = True, []
        yield
        log = self._tool_log("List menu entries of call handlers", "cuc-list-menu-entries", conn)
        try:
            client = cuc_api.CucClient(conn)
            try:
                _, by_id = await asyncio.to_thread(h.list_handlers, client)
                entries, errors = await asyncio.to_thread(h.collect_menu_entries, client, rows, by_id)
            except cuc_api.CucError as e:
                log.error(f"Menu entries failed: {e}")
                yield rx.toast.error(str(e))
                return
            except Exception as e:
                log.error(f"Menu entries failed unexpectedly: {e!r}")
                yield rx.toast.error(f"Unexpected error: {e}")
                return
            log.info(f"{len(rows)} call handler(s): {len(entries)} menu entrie(s), {len(errors)} handler(s) failed")
            for e in errors:
                log.error(f"Menu entries failed for {e['sourceHandler']}: {e['error']}")
            self.menu_errors = errors
            yield rx.download(data=h.to_csv(entries, h.MENU_FIELDS),
                              filename=f"menuentries-{self.all_for}-{_stamp()}.csv")
        finally:
            log.close()
            self.menu_busy = False

    @rx.event
    def download_errors(self):
        return rx.download(data=h.to_csv(self.menu_errors, h.ERROR_FIELDS),
                           filename=f"menuentries_errors-{self.all_for}-{_stamp()}.csv")


class MapState(CucState):
    """Build the call tree workbook from the active connection or from the two CSV files List produces."""

    source: str = "connection"      # connection | csv
    search: str = ""
    building: bool = False
    error: str = ""
    handlers_file: str = ""
    menu_file: str = ""
    _handlers: list[dict[str, str]] = []
    _menu: list[dict[str, str]] = []
    _xlsx: bytes = b""
    summary: dict[str, str] = {}
    built_from: str = ""

    @rx.var
    def has_workbook(self) -> bool:
        return bool(self.summary)

    @rx.event
    def set_source(self, value: str | list[str]):
        self.source = value if isinstance(value, str) else value[0]

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    async def load_handlers_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose the call handler CSV first.")
            return
        try:
            self._handlers = h.parse_handler_csv(await files[0].read())
        except (ValueError, UnicodeDecodeError) as e:
            yield rx.toast.error(str(e))
            return
        self.handlers_file = files[0].filename or ""
        yield rx.clear_selected_files("map_handlers_upload")

    @rx.event
    async def load_menu_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose the menu entry CSV first.")
            return
        try:
            self._menu = h.parse_menu_csv(await files[0].read())
        except (ValueError, UnicodeDecodeError) as e:
            yield rx.toast.error(str(e))
            return
        self.menu_file = files[0].filename or ""
        yield rx.clear_selected_files("map_menu_upload")

    @rx.event
    async def build(self):
        self.error = ""
        from_conn = self.source == "connection"
        conn = self._conn() if from_conn else None
        if from_conn and conn is None:
            yield rx.toast.error("Add a CUC connection first.")
            return
        if not from_conn and (not self._handlers or not self._menu):
            yield rx.toast.error("Load both CSV files first.")
            return
        self.building = True
        self.summary, self._xlsx = {}, b""
        yield
        log = self._tool_log("Build call trees", "cuc-map", conn)
        try:
            try:
                if from_conn:
                    client = cuc_api.CucClient(conn)
                    handlers, by_id = await asyncio.to_thread(h.list_handlers, client, self.search.strip())
                    menu, errors = await asyncio.to_thread(h.collect_menu_entries, client, handlers, by_id)
                    for e in errors:
                        log.error(f"Menu entries failed for {e['sourceHandler']}: {e['error']}")
                    source = conn.name
                else:
                    handlers, menu, errors, source = self._handlers, self._menu, [], "csv"
                    log.info(f"Input: {self.handlers_file}, {self.menu_file}")
                log.info(f"{len(handlers)} call handler(s), {len(menu)} menu entrie(s)")
                data, counts = await asyncio.to_thread(h.build_call_trees, handlers, menu)
            except cuc_api.CucError as e:
                self.error = str(e)
                log.error(f"Build failed: {e}")
                return
            except ImportError:
                self.error = "openpyxl is not installed. Run: pip install openpyxl"
                log.error("Build failed: openpyxl missing")
                return
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"Build failed unexpectedly: {e!r}")
                return
            self._xlsx = data
            self.built_from = source
            self.summary = {k: str(v) for k, v in counts.items()}
            if errors:
                self.summary["menuErrors"] = str(len(errors))
            log.info(f"Workbook built: {counts}")
        finally:
            log.close()
            self.building = False

    @rx.event
    def download_workbook(self):
        if not self._xlsx:
            return rx.toast.error("Build the workbook first.")
        return rx.download(data=self._xlsx, filename=f"call_trees-{self.built_from}-{_stamp()}.xlsx")


class DeleteHandlersState(CucState, CucRun, PasteMixin):
    """Review the call handlers from a list, then delete them by ObjectId."""

    paste_delete: str = ""
    rows: list[dict[str, str]] = []
    file_name: str = ""
    confirm_open: bool = False

    @rx.var
    def preview(self) -> list[dict[str, str]]:
        return self.rows[:PREVIEW_LIMIT]

    @rx.var
    def preview_hidden(self) -> int:
        return max(0, len(self.rows) - PREVIEW_LIMIT)

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    def clear_list(self):
        self.rows, self.file_name = [], ""

    @rx.event
    async def load_csv(self, files: list[rx.UploadFile]):
        async for ev in self._load(files):
            yield ev

    @rx.event
    async def load_text(self):
        async for ev in self._from_paste(self._load, "delete", columns=("objectId",), flatten=True,
                                         header_if=lambda cells: not any(len(c) >= 20 for c in cells)):
            yield ev

    async def _load(self, files):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = h.parse_delete_csv(await files[0].read())
        except UnicodeDecodeError:
            yield rx.toast.error("The file is not a text CSV.")
            return
        if not rows:
            yield rx.toast.error("No rows with an objectId were found.")
            return
        self.rows, self.file_name, self.results = rows, files[0].filename or "", []
        yield rx.clear_selected_files("delete_handlers_upload")

    @rx.event
    async def run_delete(self):
        self.confirm_open = False
        conn = self._conn()
        rows = list(self.rows)
        if conn is None:
            yield rx.toast.error("Add a CUC connection first.")
            return
        if not rows:
            return
        log = self._tool_log("Delete call handlers", "cuc-delete-handlers", conn)
        try:
            log.info(f"Input: {self.file_name}, {len(rows)} call handler(s)")
            client = cuc_api.CucClient(conn)
            items = [((r["displayName"] or r["objectId"]),
                      lambda r=r: client.delete_call_handler(r["objectId"]) or "Deleted") for r in rows]
            async for ev in self._run_items(items, "Deleting", log):
                yield ev
            self.rows, self.file_name = [], ""
        finally:
            log.close()
