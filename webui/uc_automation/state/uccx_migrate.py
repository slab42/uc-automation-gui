"""UCCX > Migrate: download everything from one UCCX server into the stored download, upload it to another.

The stored download (backend/uccx_store.py) lives a short time. Opening the page checks for one and asks whether to
continue with it, export it as a zip or delete it."""

import asyncio
from functools import partial

import reflex as rx
from reflex_base.config import get_config

from ..backend import uccx_api, uccx_backup, uccx_connections, uccx_restore as restore, uccx_store as store
from ..backend.applog import OpLog
from ..backend.errors import UserError
from .run_mixin import RunMixin
from .uccx import UccxState

STEPS = [{"key": k, "label": label} for k, label, _fn in restore.STEPS]
DEFAULT_STEPS = [s["key"] for s in STEPS if s["key"] != "delete_triggers"]


class UccxMigrateState(UccxState, RunMixin):
    origin: str = ""
    dest: str = ""
    stored: dict[str, str] = {}
    existing_open: bool = False  # the "previous download found" prompt
    replace_open: bool = False
    confirm_open: bool = False
    last_op: str = ""
    steps: list[dict[str, str]] = STEPS
    selected_steps: list[str] = DEFAULT_STEPS
    opt_original_ids: bool = False
    opt_in_place: bool = False
    opt_lan: bool = False

    @rx.var
    def has_stored(self) -> bool:
        return bool(self.stored)

    @rx.var
    def origin_sel(self) -> str:
        names = self.connection_names
        return self.origin if self.origin in names else (names[0] if names else "")

    @rx.var
    def dest_sel(self) -> str:
        names = self.connection_names
        if self.dest in names and self.dest != self.origin_sel:
            return self.dest
        others = [n for n in names if n != self.origin_sel]
        return others[0] if others else ""

    @rx.var
    def dest_names(self) -> list[str]:
        return [n for n in self.connection_names if n != self.origin_sel]

    @rx.var
    def ccgs_selected(self) -> bool:
        return "ccgs" in self.selected_steps

    @rx.var
    def selected_count(self) -> int:
        return len(self.selected_steps)

    @rx.event
    def load_page(self):
        self.stored = store.current() or {}
        self.existing_open = bool(self.stored)

    def _refresh(self):
        self.stored = store.current() or {}

    @rx.event
    def set_origin(self, name: str):
        self.origin = name

    @rx.event
    def set_dest(self, name: str):
        self.dest = name

    @rx.event
    def set_existing_open(self, value: bool):
        self.existing_open = value

    @rx.event
    def set_replace_open(self, value: bool):
        self.replace_open = value

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    def toggle_step(self, key: str, on: bool):
        keep = [s for s in self.selected_steps if s != key]
        self.selected_steps = keep + [key] if on else keep

    @rx.event
    def set_opt(self, name: str, on: bool):
        setattr(self, f"opt_{name}", on)

    @rx.event
    def keep_existing(self):
        self.existing_open = False

    @rx.event
    def delete_stored(self):
        if self.busy:
            return
        log = OpLog("Delete stored UCCX download", "uccx-download-delete")
        try:
            log.info(f"Deleting the stored download from {self.stored.get('source', '?')} ({self.stored.get('created', '?')})")
            store.delete()
        finally:
            log.close()
        self._refresh()
        self.existing_open = False
        self.results = []
        return rx.toast.info("Deleted the stored download")

    @rx.event
    async def export_stored(self):
        """Zip the stored download and hand it to the browser (served once by /uccx-export/<token>)."""
        if self.busy:
            return
        self.busy = True
        self.progress = "Building the zip"
        yield
        log = OpLog("Export UCCX download", "uccx-download-export")
        job = None
        registered = False
        try:
            job = store.new_export_dir()
            name = await asyncio.to_thread(store.export_zip, job)
            log.info(f"Wrote {name}, {(job / name).stat().st_size:,} bytes")
            token = store.register(job, name)
            registered = True
            yield rx.download(url=rx.Var.create(get_config().api_url.rstrip("/") + f"/uccx-export/{token}"), filename=name)
        except (UserError, FileNotFoundError, OSError) as e:
            log.error(str(e))
            yield rx.toast.error(f"Export failed: {e}")
        finally:
            if job is not None and not registered:
                store.remove_export_dir(job)
            self.busy = False
            self.progress = ""
            log.close()

    # --- download from the origin ---

    @rx.event
    async def download_all(self):
        # Run from the replace dialog when a download is stored, straight from the button otherwise.
        if self.busy or (self.stored and not self.replace_open):
            return
        self.replace_open = False
        name = self.origin_sel
        conn = uccx_connections.load(name) if name else None
        if conn is None:
            yield rx.toast.error("Choose the origin connection.")
            return
        self.busy = True
        self.progress = "Connecting"
        self.results = []
        self.last_op = "Download"
        started = False
        log = None
        try:
            yield
            log = self._tool_log("Download from UCCX", "uccx-download", conn)
            client = uccx_api.UccxClient(conn)
            try:
                await asyncio.to_thread(client.check)
            except UserError as e:
                log.error(f"Connection check failed: {e}")
                yield rx.toast.error(str(e))
                return
            try:
                dest = store.start(conn.name, conn.server)
            except OSError as e:
                log.error(f"Could not prepare the stored download folder: {e}")
                yield rx.toast.error(f"Could not prepare the stored download folder: {e}")
                return
            log.info(f"Stored download folder emptied and ready: {dest}")
            items = [(label, partial(fn, client, dest, log)) for _key, label, fn in uccx_backup.AREAS]
            started = True
            yield self._start_run(items, "Downloading", log, then="_after_download")
        finally:
            if not started:
                self.busy = False
                self.progress = ""
                self._refresh()
            if log is not None:
                log.close()

    def _after_download(self, log: OpLog):
        try:
            store.finish(self.results)
        except OSError as e:
            log.error(f"Could not record the download result: {e}")
        self._refresh()

    # --- upload to the destination ---

    @rx.event
    async def upload_selected(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        name = self.dest_sel
        conn = uccx_connections.load(name) if name else None
        if conn is None or not self.stored:
            yield rx.toast.error("Choose the destination connection. A stored download is needed.")
            return
        order = [(k, label, fn) for k, label, fn in restore.STEPS if k in self.selected_steps]
        if not order:
            yield rx.toast.error("Tick at least one step.")
            return
        if self.stored.get("server") == conn.server:
            yield rx.toast.error("The destination is the server this was downloaded from.")
            return
        self.busy = True
        self.progress = "Connecting"
        self.results = []
        self.last_op = "Upload"
        started = False
        log = None
        try:
            yield
            log = self._tool_log("Upload to UCCX", "uccx-upload", conn)
            log.info(f"Stored download from {self.stored.get('source')} ({self.stored.get('server')}), "
                     f"made {self.stored.get('created')}")
            ctx = restore.Ctx(uccx_api.UccxClient(conn), conn, store.DIR,
                              log, restore.Options(self.opt_original_ids, self.opt_in_place, self.opt_lan))
            try:
                await asyncio.to_thread(ctx.client.check)
            except UserError as e:
                log.error(f"Connection check failed: {e}")
                yield rx.toast.error(str(e))
                return
            log.info("Steps: " + ", ".join(label for _k, label, _fn in order))
            items = [(label, partial(fn, ctx)) for _k, label, fn in order]
            started = True
            yield self._start_run(items, "Uploading", log)
        finally:
            if not started:
                self.busy = False
                self.progress = ""
            if log is not None:
                log.close()
