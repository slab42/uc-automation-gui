"""UCCX > Script Report: read UCCX scripts (.aef) from the stored download or from an upload and build HTML reports."""

import asyncio
import io
import re
import zipfile

import reflex as rx

from ..backend import uccx_aef, uccx_store as store
from ..backend.applog import OpLog
from ..backend.errors import UserError
from .run_mixin import RunMixin
from .uccx import UccxState

DISPLAY_LIMIT = 500

# Reports being built by a background run, keyed by RunMixin._job_key(). Kept out of state: worker threads fill it.
_BUILT: dict[tuple[str, str], dict[str, str]] = {}


def _report_name(script: str) -> str:
    base = script.rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", base.rsplit(".", 1)[0]) + "-report.html"


class UccxScriptState(UccxState, RunMixin):
    stored_scripts: list[str] = []
    search: str = ""
    picked: list[str] = []
    reports: list[str] = []  # names of the reports built (the last run)
    preview_name: str = ""
    preview_html: str = ""
    _html: dict[str, str] = {}  # report name -> HTML (backend only)

    @rx.var
    def visible_scripts(self) -> list[str]:
        terms = self.search.lower().split()
        return [s for s in self.stored_scripts if all(t in s.lower() for t in terms)][:DISPLAY_LIMIT]

    @rx.var
    def picked_count(self) -> int:
        return len(self.picked)

    @rx.var
    def stored_note(self) -> str:
        n = len(self.stored_scripts)
        return f"{n} script(s) in the stored download." if n else "There is no stored download with scripts. Download from a UCCX server on the Migrate page."

    @rx.event
    def load_page(self):
        self.stored_scripts = store.script_files()
        self.picked = [p for p in self.picked if p in self.stored_scripts]

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    def toggle_pick(self, name: str, on: bool):
        keep = [p for p in self.picked if p != name]
        self.picked = keep + [name] if on else keep

    @rx.event
    def pick_shown(self):
        self.picked = list(dict.fromkeys(self.picked + self.visible_scripts))

    @rx.event
    def clear_picked(self):
        self.picked = []

    def _make_reports(self, sources: list[tuple[str, object]], log: OpLog, then: str):
        """sources: (script name, zero-argument callable returning its bytes). Returns the event that builds a
        report for each in the background."""
        built: dict[str, str] = {}
        _BUILT[self._job_key()] = built  # filled by the worker threads, read by the then-step

        def one(name: str, read):
            page, counts = uccx_aef.report(read(), name)
            built[_report_name(name)] = page
            return f"{counts['steps']} steps, {counts['variables']} variables, {counts['labels']} labels"

        self._html = {}
        self.preview_name = self.preview_html = ""
        items = [(name, lambda n=name, r=read: one(n, r)) for name, read in sources]
        return self._start_run(items, "Reading", log, then=then)

    def _after_reports(self, log: OpLog):
        built = _BUILT.pop(self._job_key(), {})
        self._html = built
        self.reports = list(built)
        if built:
            self._show(next(iter(built)))

    def _after_report_uploads(self, log: OpLog):
        self._after_reports(log)
        return [rx.clear_selected_files("aef_upload")]

    @rx.event
    async def report_picked(self):
        if not self.picked or self.busy:
            return
        log = OpLog("UCCX script report", "uccx-script-report")
        try:
            sources = [(p, lambda p=p: store.read_script(p)) for p in self.picked]
            yield self._make_reports(sources, log, "_after_reports")
        finally:
            log.close()

    @rx.event
    async def report_uploads(self, files: list[rx.UploadFile]):
        if self.busy:
            return
        if not files:
            yield rx.toast.error("Choose one or more .aef files first.")
            return
        loaded = []
        for f in files:
            data = await f.read()
            loaded.append((f.filename or "script.aef", lambda d=data: d))
        log = OpLog("UCCX script report", "uccx-script-report")
        try:
            yield self._make_reports(loaded, log, "_after_report_uploads")
        finally:
            log.close()

    def _show(self, name: str):
        if name in self._html:
            self.preview_name = name
            self.preview_html = self._html[name]

    @rx.event
    def show(self, name: str):
        self._show(name)

    @rx.event
    def download_one(self, name: str):
        if name in self._html:
            return rx.download(data=self._html[name], filename=name)

    @rx.event
    def download_all(self):
        if not self._html:
            return
        if len(self._html) == 1:
            name, page = next(iter(self._html.items()))
            return rx.download(data=page, filename=name)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, page in self._html.items():
                z.writestr(name, page)
        return rx.download(data=buf.getvalue(), filename="uccx-script-reports.zip")
