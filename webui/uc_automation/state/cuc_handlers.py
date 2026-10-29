"""States for CUC > Call Handlers: Map, List, Delete."""

import asyncio
from datetime import datetime

import reflex as rx

from ..backend import cuc_api, cuc_handlers as h
from .cuc import CucRun, CucState
from .webex_routing import PasteMixin

PREVIEW_LIMIT = 300


def _stamp() -> str:
    return datetime.now().strftime("%Y_%m_%d-%H_%M_%S")


class ListHandlersState(CucState):
    """List non-subscriber call handlers, optionally with every menu entry."""

    mode: str = "handlers"          # handlers | menu
    search: str = ""
    loading: bool = False
    error: str = ""
    handlers: list[dict[str, str]] = []
    menu_rows: list[dict[str, str]] = []
    menu_errors: list[dict[str, str]] = []
    listed_menu: bool = False
    listed_for: str = ""

    @rx.var
    def shown_handlers(self) -> list[dict[str, str]]:
        return self.handlers[:PREVIEW_LIMIT]

    @rx.var
    def handlers_hidden(self) -> int:
        return max(0, len(self.handlers) - PREVIEW_LIMIT)

    @rx.var
    def shown_menu(self) -> list[dict[str, str]]:
        return self.menu_rows[:PREVIEW_LIMIT]

    @rx.var
    def menu_hidden(self) -> int:
        return max(0, len(self.menu_rows) - PREVIEW_LIMIT)

    @rx.event
    def set_mode(self, value: str | list[str]):
        self.mode = value if isinstance(value, str) else value[0]

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    async def run_list(self):
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUC connection first.")
            return
        menu = self.mode == "menu"
        search = self.search.strip()
        self.loading, self.error = True, ""
        yield
        log = self._tool_log("List non-subscriber call handlers" if menu else "List call handlers",
                             "cuc-list-handlers-menu" if menu else "cuc-list-handlers", conn)
        try:
            client = cuc_api.CucClient(conn)
            try:
                handlers, by_id = await asyncio.to_thread(h.list_handlers, client, search if menu else "")
                log.info(f"{len(handlers)} call handler(s)" + (f" matching '{search}'" if menu and search else ""))
                rows, errors = [], []
                if menu:
                    rows, errors = await asyncio.to_thread(h.collect_menu_entries, client, handlers, by_id)
                    log.info(f"{len(rows)} menu entrie(s), {len(errors)} handler(s) failed")
                    for e in errors:
                        log.error(f"Menu entries failed for {e['sourceHandler']}: {e['error']}")
            except cuc_api.CucError as e:
                self.error = str(e)
                log.error(f"List failed: {e}")
                return
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"List failed unexpectedly: {e!r}")
                return
            self.handlers, self.menu_rows, self.menu_errors = handlers, rows, errors
            self.listed_menu, self.listed_for = menu, conn.name
        finally:
            log.close()
            self.loading = False

    @rx.event
    def download_handlers(self):
        if not self.handlers:
            return rx.toast.error("Nothing to export.")
        fields = h.HANDLER_FIELDS if self.listed_menu else ["displayName", "extension", "objectId"]
        name = "non_subscriber_callhandlers" if self.listed_menu else "callhandlers"
        return rx.download(data=h.to_csv(self.handlers, fields), filename=f"{name}-{self.listed_for}-{_stamp()}.csv")

    @rx.event
    def download_menu(self):
        if not self.menu_rows:
            return rx.toast.error("No menu entries to export.")
        return rx.download(data=h.to_csv(self.menu_rows, h.MENU_FIELDS),
                           filename=f"menuentries-{self.listed_for}-{_stamp()}.csv")

    @rx.event
    def download_errors(self):
        return rx.download(data=h.to_csv(self.menu_errors, h.ERROR_FIELDS),
                           filename=f"menuentries_errors-{self.listed_for}-{_stamp()}.csv")


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
