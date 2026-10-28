"""State for the Logs page: list, search, read and export the web app's operation logs."""

import asyncio

import reflex as rx

from ..backend import applog

PARSER_LIMIT = 200  # parser mode: most recent matching log lines shown
DISPLAY_LIMIT = 500  # rows rendered at once; search, select-all and export still cover every match


class LogsState(rx.State):
    items: list[dict[str, str]] = []
    search: str = ""
    selected: list[str] = []
    loading: bool = False

    parser_mode: bool = False
    parser_lines: list[str] = []

    viewing: str = ""        # file name shown in the reader dialog ("" = closed)
    view_text: str = ""
    view_truncated: bool = False

    @rx.var
    def parser_text(self) -> str:
        return "\n".join(self.parser_lines)

    @rx.var
    def shown(self) -> list[dict[str, str]]:
        return self.items[:DISPLAY_LIMIT]

    @rx.var
    def hidden_count(self) -> int:
        return max(0, len(self.items) - DISPLAY_LIMIT)

    @rx.var
    def selected_count(self) -> int:
        return len(self.selected)

    @rx.var
    def all_selected(self) -> bool:
        if not self.items:
            return False
        sel = set(self.selected)
        return all(r["name"] in sel for r in self.items)

    async def _load(self):
        self.loading = True
        yield
        if self.parser_mode:
            self.parser_lines = await asyncio.to_thread(applog.parse_logs, self.search, PARSER_LIMIT)
        else:
            self.items = await asyncio.to_thread(applog.list_logs, self.search)
            present = {r["name"] for r in self.items}
            self.selected = [s for s in self.selected if s in present]
        self.loading = False

    @rx.event
    async def set_parser_mode(self, on: bool):
        self.parser_mode = on
        async for ev in self._load():
            yield ev

    @rx.event
    async def on_page_load(self):
        async for ev in self._load():
            yield ev

    @rx.event
    async def refresh(self):
        async for ev in self._load():
            yield ev

    @rx.event
    async def set_search(self, value: str):
        self.search = value
        async for ev in self._load():
            yield ev

    @rx.event
    def toggle_row(self, name: str, checked: bool):
        sel = [s for s in self.selected if s != name]
        if checked:
            sel.append(name)
        self.selected = sel

    @rx.event
    def toggle_all(self, checked: bool):
        visible = {r["name"] for r in self.items}
        keep = [s for s in self.selected if s not in visible]
        self.selected = keep + sorted(visible) if checked else keep

    @rx.event
    def open_log(self, name: str):
        try:
            self.view_text, self.view_truncated = applog.read_log(name)
        except FileNotFoundError:
            return rx.toast.error("That log no longer exists.")
        self.viewing = name

    @rx.event
    def close_log(self):
        self.viewing = ""
        self.view_text = ""
        self.view_truncated = False

    def _download(self, names: list[str]):
        try:
            filename, data, mime = applog.export_logs(names)
        except FileNotFoundError as e:
            return rx.toast.error(str(e))
        return rx.download(data=data, filename=filename, mime_type=mime)

    @rx.event
    def export_selected(self):
        return self._download(list(self.selected))

    @rx.event
    def export_viewing(self):
        return self._download([self.viewing])
