"""States for CUC > Users: Status Check, Usage Check, Remove Empty."""

import asyncio
from datetime import datetime

from typing import ClassVar

import reflex as rx

from ..backend import cuc_api, cuc_users as u
from ..backend.applog import OpLog
from ..backend.paste import no_at_or_digit
from .cuc import CucRun, CucState
from .webex_routing import PasteMixin

PREVIEW_LIMIT = 500
_PASTE = {"columns": ("extension",), "flatten": True, "header_if": no_at_or_digit}

# What a background run collects for its after-step, keyed by RunMixin._job_key(). Kept out of state: the workers
# fill it while the run is going.
_COLLECTED: dict[tuple[str, str], dict] = {}


def _stamp() -> str:
    return datetime.now().strftime("%Y_%m_%d-%H_%M_%S")


class _Lookup(CucRun, PasteMixin, mixin=True):
    """Look up the mailbox of each extension in a pasted list or CSV and keep one row per found user."""

    output_fields: ClassVar[tuple[str, ...]] = ("rows",)

    paste_ext: str = ""
    rows: list[dict[str, str]] = []

    @rx.var
    def shown_rows(self) -> list[dict[str, str]]:
        return self.rows[:PREVIEW_LIMIT]

    @rx.var
    def rows_hidden(self) -> int:
        return max(0, len(self.rows) - PREVIEW_LIMIT)

    async def _lookup(self, files, make_row, title: str, slug: str, upload_id: str):
        if self.busy:  # a second run would replace this one's collected rows
            return
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUC connection first.")
            return
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            extensions = u.parse_extensions(await files[0].read())
        except UnicodeDecodeError:
            yield rx.toast.error("The file is not a text CSV.")
            return
        if not extensions:
            yield rx.toast.error("No extensions were found.")
            return
        log = self._tool_log(title, slug, conn)
        try:
            log.info(f"Input: {files[0].filename}, {len(extensions)} extension(s)")
            client = cuc_api.CucClient(conn)
            found: list[dict[str, str]] = []

            def one(ext: str) -> str:
                usage = client.mailbox_usage(ext)
                found.append(make_row(usage))
                return f"{usage['alias']}, {usage['sizeMb']} MB"

            self.rows = []
            items = [(ext, lambda ext=ext: one(ext)) for ext in extensions]
            _COLLECTED[self._job_key()] = {"found": found, "upload_id": upload_id}
            yield self._start_run(items, "Checking", log, then="_after_lookup")
        finally:
            log.close()

    def _after_lookup(self, log: OpLog):
        out = _COLLECTED.pop(self._job_key(), {})
        self.rows = out.get("found", [])
        return [rx.clear_selected_files(out["upload_id"])] if "upload_id" in out else None


class AllRows(CucRun, mixin=True):
    """The "All" tab of a CUC page: every row read once, then searched, ticked and exported or acted on.

    Rows need an objectId. Users are the default; override _read_all, _load_label and _search_fields for other lists."""

    output_fields: ClassVar[tuple[str, ...]] = ("all_rows", "all_error", "all_failed", "all_for")

    all_rows: list[dict[str, str]] = []
    all_loading: bool = False
    all_error: str = ""
    all_failed: int = 0
    all_for: str = ""
    search: str = ""
    search_mode: str = "Contains"
    selected: list[str] = []

    def _read_all(self, client) -> tuple[list[dict[str, str]], list[str]]:
        """(rows, failure messages). Runs in a thread, so it must not touch state."""
        return u.all_status(client)

    def _load_label(self) -> tuple[str, str]:
        """(log title, log slug) of the load."""
        return "Read all users and mailboxes", "cuc-users-all"

    def _search_fields(self) -> tuple[str, ...]:
        return ("dtmfAccessId", "alias", "displayName")

    def _base_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        """The rows the tab lists before searching. Override to show only some users."""
        return rows

    @rx.var
    def filtered(self) -> list[dict[str, str]]:
        return u.filter_rows(self._base_rows(self.all_rows), self.search, self.search_mode == "Begins With",
                             self._search_fields())

    @rx.var
    def filtered_shown(self) -> list[dict[str, str]]:
        return self.filtered[:PREVIEW_LIMIT]

    @rx.var
    def filtered_hidden(self) -> int:
        return max(0, len(self.filtered) - PREVIEW_LIMIT)

    @rx.var
    def selected_count(self) -> int:
        return len(self.selected)

    @rx.var
    def all_selected(self) -> bool:
        keys = {r["objectId"] for r in self.filtered}
        return bool(keys) and keys <= set(self.selected)

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    def set_search_mode(self, value: str):
        self.search_mode = value

    @rx.event
    def toggle_row(self, key: str, checked: bool):
        if checked and key not in self.selected:
            self.selected = self.selected + [key]
        elif not checked:
            self.selected = [k for k in self.selected if k != key]

    @rx.event
    def toggle_all(self, checked: bool):
        """Select all / none of the rows the search currently shows (rows selected earlier stay selected)."""
        keys = [r["objectId"] for r in self.filtered]
        if checked:
            self.selected = self.selected + [k for k in keys if k not in set(self.selected)]
        else:
            drop = set(keys)
            self.selected = [k for k in self.selected if k not in drop]

    @rx.event
    async def load_all(self):
        async for ev in self._load_all():
            yield ev

    @rx.event
    async def auto_load(self):
        """Page load: read all users, quietly skipping when there is no connection yet."""
        # Not guarded by all_loading: a load cancelled mid-way (page left, socket drop) can leave the flag stuck on.
        if self._conn() is not None:
            async for ev in self._load_all():
                yield ev

    async def _load_all(self):
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUC connection first.")
            return
        self.all_loading, self.all_error = True, ""
        yield
        log = self._tool_log(*self._load_label(), conn)
        try:
            client = cuc_api.CucClient(conn)
            try:
                rows, errors = await asyncio.to_thread(self._read_all, client)
            except cuc_api.CucError as e:
                self.all_error = str(e)
                log.error(f"Load failed: {e}")
                return
            except Exception as e:
                self.all_error = f"Unexpected error: {e}"
                log.error(f"Load failed unexpectedly: {e!r}")
                return
            self.all_rows, self.all_failed, self.all_for = rows, len(errors), conn.name
            self.selected = []
            log.info(f"{len(rows)} row(s) read, {len(errors)} failed")
            for e in errors:
                log.error(e)
        finally:
            log.close()
            self.all_loading = False

    def _selected_rows(self) -> list[dict[str, str]]:
        keys = set(self.selected)
        return [r for r in self.all_rows if r["objectId"] in keys]


class StatusCheckState(CucState, _Lookup, AllRows):
    @rx.event
    def export_selected(self):
        rows = self._selected_rows()
        if not rows:
            return rx.toast.error("Tick the users to export first.")
        return rx.download(data=u.status_csv(rows), filename=f"mailbox-status-{self.all_for}-{_stamp()}.csv")

    async def _csv(self, files):
        async for ev in self._lookup(files, u.status_row, "Mailbox status check", "cuc-status-check",
                                     "status_upload"):
            yield ev

    @rx.event
    async def load_csv(self, files: list[rx.UploadFile]):
        async for ev in self._csv(files):
            yield ev

    @rx.event
    async def load_text(self):
        async for ev in self._from_paste(self._csv, "ext", **_PASTE):
            yield ev

    @rx.event
    def export_csv(self):
        if not self.rows:
            return rx.toast.error("Nothing to export. Run the check first.")
        return rx.download(data=u.status_csv(self.rows), filename=f"mailbox-status-{_stamp()}.csv")


class UsageCheckState(CucState, _Lookup, AllRows):
    @rx.event
    def export_selected(self):
        rows = self._selected_rows()
        if not rows:
            return rx.toast.error("Tick the users to export first.")
        out = [{"dtmfAccessID": r["dtmfAccessId"], "alias": r["alias"], "mailboxSize": r["sizeMb"]} for r in rows]
        return rx.download(data=u.usage_csv(out), filename=f"mailbox-usage-{self.all_for}-{_stamp()}.csv")

    async def _csv(self, files):
        async for ev in self._lookup(files, u.usage_row, "Mailbox usage check", "cuc-usage-check", "usage_upload"):
            yield ev

    @rx.event
    async def load_csv(self, files: list[rx.UploadFile]):
        async for ev in self._csv(files):
            yield ev

    @rx.event
    async def load_text(self):
        async for ev in self._from_paste(self._csv, "ext", **_PASTE):
            yield ev

    @rx.event
    def export_csv(self):
        if not self.rows:
            return rx.toast.error("Nothing to export. Run the check first.")
        return rx.download(data=u.usage_csv(self.rows), filename=f"mailbox-usage-{_stamp()}.csv")


class RemoveEmptyState(CucState, PasteMixin, AllRows):
    """Two steps: scan the extensions (read only), then delete the user accounts whose mailbox is empty."""

    output_fields: ClassVar[tuple[str, ...]] = ("empty", "keep", "scanned", "_uris")

    paste_ext: str = ""
    empty: list[dict[str, str]] = []      # extension, alias, mailboxSize
    keep: list[dict[str, str]] = []       # mailboxes with data (the CLI's "remaining" CSV)
    scanned: int = 0
    scan_conn: str = ""
    _uris: dict[str, str] = {}            # extension -> user URI, backend only
    confirm_open: bool = False
    confirm_all_open: bool = False

    def _base_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        """All users tab: only mailboxes with no data."""
        return [r for r in rows if r["byteSize"] == "0"]

    @rx.var
    def with_data_count(self) -> int:
        return len(self.all_rows) - len(self._base_rows(self.all_rows))

    @rx.event
    def set_confirm_all_open(self, value: bool):
        self.confirm_all_open = value

    @rx.event
    async def delete_selected(self):
        """All users tab: delete the user accounts ticked in the list, then reload it."""
        if not self.confirm_all_open or self.busy:
            return
        self.confirm_all_open = False
        conn = self._conn()
        if conn is None:
            return
        keys = set(self.selected)
        rows = [r for r in self._base_rows(self.all_rows) if r["objectId"] in keys]  # only empty mailboxes, whatever was ticked
        if not rows:
            return
        log = self._tool_log("Delete empty mailbox users", "cuc-remove-empty-delete", conn)
        try:
            log.info(f"{len(rows)} user account(s) ticked in the list")
            client = cuc_api.CucClient(conn)
            items = [(r["dtmfAccessId"] or r["alias"], lambda r=r: u.delete_empty(client, r["uri"])) for r in rows]
            yield self._start_run(items, "Deleting", log, then="_after_delete_selected")
        finally:
            log.close()

    def _after_delete_selected(self, log: OpLog):
        return [type(self).load_all]

    @rx.var
    def shown_empty(self) -> list[dict[str, str]]:
        return self.empty[:PREVIEW_LIMIT]

    @rx.var
    def empty_hidden(self) -> int:
        return max(0, len(self.empty) - PREVIEW_LIMIT)

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    def _reset_plan(self):
        self.empty, self.keep, self.scanned, self._uris = [], [], 0, {}
        self.results = []

    @rx.event
    def clear_plan(self):
        self._reset_plan()

    @rx.event
    async def load_csv(self, files: list[rx.UploadFile]):
        async for ev in self._scan(files):
            yield ev

    @rx.event
    async def load_text(self):
        async for ev in self._from_paste(self._scan, "ext", **_PASTE):
            yield ev

    async def _scan(self, files):
        if self.busy:  # a second run would replace this one's collected rows
            return
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUC connection first.")
            return
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            extensions = u.parse_extensions(await files[0].read())
        except UnicodeDecodeError:
            yield rx.toast.error("The file is not a text CSV.")
            return
        if not extensions:
            yield rx.toast.error("No extensions were found.")
            return
        log = self._tool_log("Scan for empty mailboxes", "cuc-remove-empty-scan", conn)
        try:
            log.info(f"Input: {files[0].filename}, {len(extensions)} extension(s)")
            client = cuc_api.CucClient(conn)
            empty, keep, uris = [], [], {}

            def one(ext: str) -> str:
                usage = client.mailbox_usage(ext)
                row = u.usage_row(usage)
                if usage["byteSize"] == 0:
                    empty.append(row)
                    uris[usage["dtmfAccessId"]] = usage["uri"]
                    return "Empty"
                keep.append(row)
                return f"{usage['sizeMb']} MB, keep"

            self._reset_plan()
            items = [(ext, lambda ext=ext: one(ext)) for ext in extensions]
            _COLLECTED[self._job_key()] = {"empty": empty, "keep": keep, "uris": uris,
                                           "scanned": len(extensions), "conn": conn.name}
            yield self._start_run(items, "Checking", log, then="_after_scan")
        finally:
            log.close()

    def _after_scan(self, log: OpLog):
        out = _COLLECTED.pop(self._job_key(), None)
        if out is None:
            return None
        self.empty, self.keep, self._uris = out["empty"], out["keep"], out["uris"]
        self.scanned, self.scan_conn = out["scanned"], out["conn"]
        unchecked = self.scanned - len(self.empty) - len(self.keep)  # failed or not run (cancelled)
        log.info(f"{len(self.empty)} empty, {len(self.keep)} with data, {unchecked} not checked")
        return [rx.clear_selected_files("empty_upload")]

    @rx.event
    async def run_delete(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        conn = self._conn()
        if conn is None or not self.empty:
            return
        if conn.name != self.scan_conn:
            yield rx.toast.error("The connection changed since the scan. Scan again.")
            return
        log = self._tool_log("Delete empty mailbox users", "cuc-remove-empty-delete", conn)
        try:
            client = cuc_api.CucClient(conn)
            uris = dict(self._uris)
            items = [(r["dtmfAccessID"], lambda r=r: u.delete_empty(client, uris[r["dtmfAccessID"]]))
                     for r in self.empty]
            yield self._start_run(items, "Deleting", log, then="_after_run_delete")
        finally:
            log.close()

    def _after_run_delete(self, log: OpLog):
        # Keep the rows not deleted (failed, or not run after Cancel) so the review still lists them.
        done = {r["key"] for r in self.results if r["status"] == "OK"}
        self.empty = [r for r in self.empty if r["dtmfAccessID"] not in done]
        self._uris = {k: v for k, v in self._uris.items() if k not in done}

    @rx.event
    def export_keep(self):
        if not self.keep:
            return rx.toast.error("No mailboxes with data to export.")
        return rx.download(data=u.usage_csv(self.keep), filename=f"mailbox-usage-remaining-{_stamp()}.csv")
