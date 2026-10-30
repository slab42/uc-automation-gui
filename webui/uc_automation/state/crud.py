"""Shared list / search / select / add / import / export / delete behaviour for CUCM resources.

A concrete state class is `class XState(CucmState, CrudMixin)` and implements `_spec()`.
Helpers that need to run other work are plain async generators (not event handlers), so the
mixin never has to name the concrete class.
"""

import asyncio
import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import reflex as rx

from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from ..backend.cucm_connections import CucmConnection
from ..backend.keys import KEY_SEP, split_key


DISPLAY_LIMIT = 500  # rows rendered at once; search and select-all still cover every match


@dataclass
class ResourceSpec:
    noun: str                                  # "pattern"
    key: str                                   # field that identifies a row, e.g. "pattern" / "name"
    fields: list[str]                          # CSV / table fields, in export order
    export_prefix: str                         # file name prefix for export
    template_csv: str                          # import template (also shown in the dialog)
    bulk_template_csv: str                     # bulk delete template
    list_fn: Callable[[CucmConnection], list[dict[str, str]]]
    add_fn: Callable[[CucmConnection, dict[str, str]], None]
    update_fn: Callable[[CucmConnection, dict[str, str]], None]
    remove_fn: Callable[[CucmConnection, str], None]
    add_defaults: dict[str, str] = field(default_factory=dict)
    build_add_row: Callable[[dict[str, str]], dict[str, str]] = lambda form: dict(form)
    # Objects identified by more than one field (pattern + partition): set key="id" and list the parts here.
    # Rows then carry an extra "id" field (parts joined with KEY_SEP) that is used for selection, delete
    # targets and results. remove_fn receives that id; use split_key() to take it apart.
    key_parts: tuple[str, ...] = ()


def make_key(spec: ResourceSpec, row: dict[str, str]) -> str:
    return KEY_SEP.join((row.get(p) or "").strip() for p in spec.key_parts)


def display_key(spec: ResourceSpec, key: str) -> str:
    """Human label for a row key: 'pattern' or 'pattern in partition' for composite keys."""
    if not spec.key_parts:
        return key
    first, *rest = split_key(key, len(spec.key_parts))
    rest = [r for r in rest if r]
    return f"{first} in {', '.join(rest)}" if rest else first


def row_label(spec: ResourceSpec, row: dict[str, str]) -> str:
    return display_key(spec, make_key(spec, row)) if spec.key_parts else row[spec.key]


def parse_csv(data: bytes, spec: ResourceSpec) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("The CSV file is empty.")
    lookup = {(h or "").strip().lower(): h for h in reader.fieldnames}
    required = spec.key_parts[0] if spec.key_parts else spec.key
    if required.lower() not in lookup:
        raise ValueError(f"The CSV needs a header row with a '{required}' column.")
    cols = {f: lookup.get(f.lower()) for f in spec.fields}
    rows = []
    for raw in reader:
        row = {f: (raw.get(h) or "").strip() if h else "" for f, h in cols.items()}
        if any(row.values()):
            if spec.key_parts:
                row[spec.key] = make_key(spec, row)
            rows.append(row)
    return rows


class CrudMixin(rx.State, mixin=True):
    items: list[dict[str, str]] = []
    search: str = ""
    selected: list[str] = []
    loading: bool = False
    error: str = ""
    loaded_for: str = ""

    dialog: str = ""  # "", "add", "import", "bulk", "confirm", "result"
    busy: bool = False
    progress: str = ""
    results: list[dict[str, str]] = []

    new_form: dict[str, str] = {}
    add_error: str = ""

    # Subclasses implement this (not an event handler, not a var).
    def _spec(self) -> ResourceSpec:
        raise NotImplementedError

    # --- computed ---

    @rx.var
    def filtered(self) -> list[dict[str, str]]:
        q = self.search.strip().lower()
        if not q:
            return self.items
        return [r for r in self.items if any(q in v.lower() for v in r.values())]

    @rx.var
    def shown(self) -> list[dict[str, str]]:
        return self.filtered[:DISPLAY_LIMIT]

    @rx.var
    def hidden_count(self) -> int:
        return max(0, len(self.filtered) - DISPLAY_LIMIT)

    @rx.var
    def all_selected(self) -> bool:
        if not self.filtered:
            return False
        key = self._spec().key
        sel = set(self.selected)
        return all(r[key] in sel for r in self.filtered)

    @rx.var
    def selected_count(self) -> int:
        return len(self.selected)

    @rx.var
    def template_text(self) -> str:
        return self._spec().template_csv

    @rx.var
    def bulk_template_text(self) -> str:
        return self._spec().bulk_template_csv

    @rx.var
    def result_ok_count(self) -> int:
        return sum(1 for r in self.results if r["status"] == "OK")

    @rx.var
    def result_fail_count(self) -> int:
        return sum(1 for r in self.results if r["status"] != "OK")

    # --- helpers ---

    def _form_defaults(self):
        self.new_form = dict(self._spec().add_defaults)

    def _open_log(self, action: str, conn: CucmConnection | None = None) -> OpLog:
        """Start the log for one operation on this page. The caller closes it (try/finally)."""
        spec = self._spec()
        log = OpLog(f"{spec.noun.title()} {action}", f"{spec.export_prefix}-{action.lower().replace(' ', '-')}")
        conn = conn or self._conn()
        if conn is not None:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
        return log

    async def _fetch(self, log: OpLog | None = None):
        """List from CUCM. Logs into `log` when called from another operation, else into its own log."""
        conn = self._conn()
        if conn is None:
            self.items = []
            self.error = ""
            return
        own = log is None
        if own:
            log = self._open_log("List", conn)
        try:
            self.loading = True
            self.error = ""
            yield
            try:
                spec = self._spec()
                self.items = await asyncio.to_thread(spec.list_fn, conn)
                if spec.key_parts:
                    self.items = [{**r, spec.key: make_key(spec, r)} for r in self.items]
                self.loaded_for = self.active
                log.info(f"Listed {len(self.items)} {self._spec().noun}(s)")
            except AxlError as e:
                self.error = str(e)
                log.error(f"List failed: {e}")
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"List failed unexpectedly: {e!r}")
            present = {r[self._spec().key] for r in self.items}
            self.selected = [s for s in self.selected if s in present]
            self.loading = False
        finally:
            if own:
                log.close()

    async def _run_each(self, conn: CucmConnection, targets: list, op, verb: str, done: str, log: OpLog):
        """Run op(conn, target) for each target in a thread, recording a result row (and a log line) per target."""
        key = self._spec().key
        log.info(f"{verb}: {len(targets)} target(s)")
        self.busy = True
        self.results = []
        for i, t in enumerate(targets, 1):
            self.progress = f"{verb} {i} of {len(targets)}"
            yield
            label = display_key(self._spec(), t) if isinstance(t, str) else row_label(self._spec(), t)
            rid = t if isinstance(t, str) else t.get(key, label)
            try:
                ret = await asyncio.to_thread(op, conn, t)
                detail = ret if isinstance(ret, str) and ret else done
                self.results.append({"key": label, "id": rid, "status": "OK", "detail": detail})
                log.info(f"{label}: OK - {detail}")
            except AxlError as e:
                self.results.append({"key": label, "id": rid, "status": "Failed", "detail": str(e)})
                log.error(f"{label}: Failed - {e}")
            except Exception as e:
                self.results.append({"key": label, "id": rid, "status": "Failed", "detail": f"Unexpected error: {e}"})
                log.error(f"{label}: Failed unexpectedly - {e!r}")
        log.info(f"{verb} finished: {sum(1 for r in self.results if r['status'] == 'OK')} OK, "
                 f"{sum(1 for r in self.results if r['status'] != 'OK')} failed")
        self.progress = ""
        self.busy = False

    # --- loading ---

    @rx.event
    async def fetch(self):
        async for ev in self._fetch():
            yield ev

    @rx.event
    async def on_page_load(self):
        self.load_connections()
        if not self.new_form:
            self._form_defaults()
        if self.active and (self.active != self.loaded_for or not self.items):
            async for ev in self._fetch():
                yield ev

    @rx.event
    async def switch_connection(self, name: str):
        self.active = name
        self.items = []
        self.selected = []
        async for ev in self._fetch():
            yield ev

    @rx.event
    async def switch_org(self, org: str):
        self.active_org = org
        self._reconcile()
        self.items = []
        self.selected = []
        if self.active:
            async for ev in self._fetch():
                yield ev

    # --- search / selection ---

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    def toggle_row(self, key: str, checked: bool):
        sel = [s for s in self.selected if s != key]
        if checked:
            sel.append(key)
        self.selected = sel

    @rx.event
    def toggle_all(self, checked: bool):
        k = self._spec().key
        visible = {r[k] for r in self.filtered}
        keep = [s for s in self.selected if s not in visible]
        self.selected = keep + sorted(visible) if checked else keep

    # --- dialogs ---

    @rx.event
    def set_dialog(self, name: str, is_open: bool = True):
        if self.busy:
            return
        self.dialog = name if is_open else ""
        self.results = []
        self.progress = ""
        self.add_error = ""

    @rx.event
    def copy_selected(self):
        """Open the Add dialog pre-filled from the one selected row."""
        if len(self.selected) != 1:
            return rx.toast.error("Select exactly one row to copy.")
        key = self._spec().key
        src = next((r for r in self.items if r[key] == self.selected[0]), None)
        if src is None:
            return rx.toast.error("That row is no longer in the list.")
        self.new_form = {f: src.get(f, d) for f, d in self._spec().add_defaults.items()}
        self.results = []
        self.progress = ""
        self.add_error = ""
        self.dialog = "add"

    @rx.event
    def set_new(self, field: str, value: str):
        self.new_form = {**self.new_form, field: value}

    # --- delete ---

    @rx.event
    async def delete_selected(self):
        conn = self._conn()
        if conn is None:
            return
        targets = list(self.selected)
        log = self._open_log("Delete selected", conn)
        try:
            async for ev in self._run_each(conn, targets, self._spec().remove_fn, "Removing", "Removed", log):
                yield ev
            failed = {r["id"] for r in self.results if r["status"] != "OK"}
            self.selected = [s for s in targets if s in failed]
            self.dialog = "result" if failed else ""
            async for ev in self._fetch(log):
                yield ev
        finally:
            log.close()
        if failed:
            yield rx.toast.warning(f"{len(failed)} removal(s) failed")
        else:
            yield rx.toast.success(f"Removed {len(targets)} {self._spec().noun}(s)")

    @rx.event
    async def bulk_delete(self, files: list[rx.UploadFile]):
        conn = self._conn()
        if conn is None or not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        spec = self._spec()
        log = self._open_log("Bulk delete", conn)
        try:
            log.info(f"CSV file: {files[0].filename}")
            try:
                rows = parse_csv(await files[0].read(), spec)
            except ValueError as e:
                log.error(f"CSV rejected: {e}")
                yield rx.toast.error(str(e))
                return
            targets = list(dict.fromkeys(r[spec.key] for r in rows if r[spec.key]))
            if not targets:
                log.error("CSV has no targets")
                yield rx.toast.error(f"No {spec.noun}s found in the CSV.")
                return
            async for ev in self._run_each(conn, targets, spec.remove_fn, "Removing", "Removed", log):
                yield ev
            yield rx.clear_selected_files("bulk_upload")
            async for ev in self._fetch(log):
                yield ev
        finally:
            log.close()

    # --- add ---

    @rx.event
    async def add_one(self):
        conn = self._conn()
        if conn is None:
            return
        spec = self._spec()
        row = spec.build_add_row(self.new_form)
        log = self._open_log("Add", conn)
        try:
            self.busy = True
            self.add_error = ""
            yield
            label = row_label(spec, row)
            log.info(f"Adding {label}")
            try:
                await asyncio.to_thread(spec.add_fn, conn, row)
            except AxlError as e:
                self.add_error = str(e)
                log.error(f"{label}: Failed - {e}")
                self.busy = False
                return
            except Exception as e:
                self.add_error = f"Unexpected error: {e}"
                log.error(f"{label}: Failed unexpectedly - {e!r}")
                self.busy = False
                return
            log.info(f"{label}: OK - Added")
            self.busy = False
            self.dialog = ""
            self._form_defaults()
            async for ev in self._fetch(log):
                yield ev
            yield rx.toast.success(f"Added {label}")
        finally:
            log.close()

    # --- import ---

    async def _import(self, files: list[rx.UploadFile], mode: str):
        conn = self._conn()
        if conn is None or not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        spec = self._spec()
        add = mode == "add"
        log = self._open_log("Import add" if add else "Import modify", conn)
        try:
            log.info(f"CSV file: {files[0].filename}")
            try:
                rows = parse_csv(await files[0].read(), spec)
            except ValueError as e:
                log.error(f"CSV rejected: {e}")
                yield rx.toast.error(str(e))
                return
            if not rows:
                log.error("CSV has no data rows")
                yield rx.toast.error("The CSV has no data rows.")
                return
            async for ev in self._run_each(conn, rows, spec.add_fn if add else spec.update_fn,
                                           "Adding" if add else "Modifying", "Added" if add else "Modified", log):
                yield ev
            yield rx.clear_selected_files("import_upload")
            async for ev in self._fetch(log):
                yield ev
        finally:
            log.close()

    @rx.event
    async def import_add(self, files: list[rx.UploadFile]):
        async for ev in self._import(files, "add"):
            yield ev

    @rx.event
    async def import_modify(self, files: list[rx.UploadFile]):
        async for ev in self._import(files, "modify"):
            yield ev

    # --- export / templates ---

    @rx.event
    def export_click(self):
        """Export straight away, or ask first when rows are selected."""
        if self.selected:
            self.results = []
            self.dialog = "exportchoice"
            return
        return self._export("all")

    @rx.event
    def export_csv(self, scope: str):
        return self._export(scope)

    def _export(self, scope: str):
        rows = self.items
        suffix = ""
        if scope == "selected":
            chosen = set(self.selected)
            rows = [r for r in self.items if r[self._spec().key] in chosen]
            suffix = "-selected"
        self.dialog = ""
        log = self._open_log("Export")
        try:
            log.info(f"Export scope: {scope}, {len(rows)} row(s)")
        finally:
            log.close()
        if not rows:
            return rx.toast.error("Nothing to export.")
        spec = self._spec()
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=spec.fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        server = (self.active_info or {}).get("server", "cucm")
        stamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
        return rx.download(data=buf.getvalue(), filename=f"{spec.export_prefix}{suffix}-{server}-{stamp}.csv")

    @rx.event
    def download_template(self):
        spec = self._spec()
        return rx.download(data=spec.template_csv, filename=f"{spec.export_prefix}_template.csv")

    @rx.event
    def download_bulk_template(self):
        spec = self._spec()
        return rx.download(data=spec.bulk_template_csv, filename=f"remove_{spec.export_prefix}_template.csv")


class DepCheckMixin(rx.State, mixin=True):
    """Check Dependencies / Keep only unused selected. Use with CrudMixin; subclasses supply `_dep_fn()`,
    a callable (conn, names) -> ({name: [references]}, warnings)."""

    dep_results: list[dict[str, str]] = []
    dep_warnings: list[str] = []
    dep_unused: list[str] = []
    dep_checking: bool = False

    def _dep_fn(self):
        raise NotImplementedError

    @rx.var
    def dep_in_use_count(self) -> int:
        return sum(1 for r in self.dep_results if r["status"] == "In use")

    @rx.event
    async def check_dependencies(self):
        conn = self._conn()
        names = list(self.selected)
        if conn is None or not names:
            return
        self.dialog = "deps"
        self.dep_checking = True
        self.dep_results = []
        self.dep_warnings = []
        self.dep_unused = []
        yield
        log = self._open_log("Check dependencies", conn)
        try:
            log.info(f"Checking {len(names)} {self._spec().noun}(s): "
                     f"{', '.join(display_key(self._spec(), n) for n in names)}")
            try:
                usage, warnings = await asyncio.to_thread(self._dep_fn(), conn, names)
            except AxlError as e:
                self.dep_checking = False
                self.dep_warnings = [str(e)]
                log.error(f"Dependency check failed: {e}")
                return
            except Exception as e:
                self.dep_checking = False
                self.dep_warnings = [f"Unexpected error: {e}"]
                log.error(f"Dependency check failed unexpectedly: {e!r}")
                return
            for w in warnings:
                log.warning(w)
            for n in names:
                log.info(f"{display_key(self._spec(), n)}: {len(usage.get(n, []))} reference(s)")
                for ref in usage.get(n, []):
                    log.debug(f"    {ref}")
        finally:
            log.close()
        unconfirmed = bool(warnings)
        rows = []
        for n in names:
            refs = usage.get(n, [])
            if refs:
                shown = "; ".join(refs[:6]) + (f"; and {len(refs) - 6} more" if len(refs) > 6 else "")
                rows.append({"key": display_key(self._spec(), n), "status": "In use", "count": str(len(refs)),
                             "detail": shown})
            else:
                rows.append({"key": display_key(self._spec(), n), "status": "Unconfirmed" if unconfirmed else "Unused",
                             "count": "0", "detail": "See warnings" if unconfirmed else "No references found"})
        self.dep_results = rows
        self.dep_warnings = warnings
        self.dep_unused = [n for n, r in zip(names, rows) if r["status"] == "Unused"]
        self.dep_checking = False

    @rx.event
    def select_unused(self):
        self.selected = list(self.dep_unused)
        self.dialog = ""
