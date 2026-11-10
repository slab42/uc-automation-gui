"""States for the RedSky tool pages.

Every add tool is `class X(RedskyState, RedskyBulk)` with an AddSpec (backend/redsky_common.py) as SPEC; every
check tool is `class X(RedskyState, RedskyCheck)` with a CheckSpec. The mixins hold all the handlers, so a
new tool is a spec plus a few lines here and a page builder call.
"""

import asyncio
from typing import Any, ClassVar

import reflex as rx

from ..backend import (redsky_alerts as alerts, redsky_audit as audit, redsky_geography as geo, redsky_networking as net,
                       redsky_precheck as pre)
from ..backend.applog import OpLog
from ..backend.errors import UserError
from ..backend.redsky_api import RedskyClient
from ..backend.redsky_common import AddSpec, CheckSpec, build_items, csv_bytes, read_rows
from ..backend.paste import DELIMS
from .redsky import RedskyState
from .run_mixin import RunMixin
from .webex_routing import PasteMixin

_NO_CONNECTION = "No RedSky connection is selected. Add one on the Credentials page."
_PASTE_DELIMS = tuple(d for d in DELIMS if d != ";")  # ';' separates the items inside a cell


def _blank(spec: AddSpec) -> dict[str, str]:
    return {f.key: f.default for f in spec.fields}


class RedskyBulk(RunMixin, PasteMixin, mixin=True):
    """One add tool: single entry form, pasted text, CSV, template download."""

    SPEC: ClassVar[AddSpec]
    paste_rows: str = ""
    lookups: dict[str, list[str]] = {"buildings": [], "locations": [], "alert_types": [], "templates": []}

    @rx.event
    def set_row_field(self, field: str, value: str):
        self.row = {**self.row, field: value}

    @rx.event
    async def load_lookups(self):
        """Page load: suggestions for the single entry form (buildings, locations, alert types, templates)."""
        spec = self.SPEC
        conn = self._conn()
        if spec.lookups is None or conn is None:
            return
        log = self._tool_log(f"RedSky {spec.title}: load lists", f"redsky-{spec.slug}-lookups", conn)
        try:
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                found = await asyncio.to_thread(spec.lookups, client)
            except UserError as e:
                log.error(str(e))
                return
            self.lookups = {**self.lookups, **found}
            log.info(", ".join(f"{len(v)} {k}" for k, v in found.items()))
        finally:
            log.close()

    async def _execute(self, rows: list[list[str]], title: str, then: str):
        """Build the items and start the background run (RunMixin). `then` runs after it."""
        spec = self.SPEC
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        if self.busy:
            return
        log = self._tool_log(title, f"redsky-{spec.slug}", conn)
        try:
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                items = await asyncio.to_thread(build_items, spec, client, rows)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            yield self._start_run(items, "Adding", log, then=then)
        finally:
            log.close()

    @rx.event
    async def add_single(self):
        spec = self.SPEC
        row = [self.row.get(f.key, "").strip() for f in spec.fields]
        async for ev in self._execute([row], f"RedSky {spec.title}", "_after_add_single"):
            yield ev

    def _after_add_single(self, log: OpLog):
        if self.results and self.result_fail_count == 0:
            self.row = _blank(self.SPEC)

    async def _csv_flow(self, files):
        """Shared by the CSV upload and the pasted text (PastedFile stands in for the upload)."""
        spec = self.SPEC
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = read_rows(await files[0].read(), len(spec.fields))
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        async for ev in self._execute(rows, f"RedSky {spec.title} from CSV ({files[0].filename})", "_after_csv"):
            yield ev
        if not self.busy:  # the run did not start: clear the upload now, otherwise _after_csv does
            yield rx.clear_selected_files(f"{spec.slug}_upload")

    def _after_csv(self, log: OpLog):
        return [rx.clear_selected_files(f"{self.SPEC.slug}_upload")]

    @rx.event
    async def add_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._csv_flow(files):
            yield ev

    @rx.event
    async def add_from_text(self):
        spec = self.SPEC
        async for ev in self._from_paste(self._csv_flow, "rows", columns=spec.columns,
                                         markers=(spec.columns[0].lower(),), delims=_PASTE_DELIMS):
            yield ev

    @rx.event
    def download_template(self):
        spec = self.SPEC
        return rx.download(data=csv_bytes(spec.columns), filename=f"redsky_{spec.slug.replace('-', '_')}.csv")


class RedskyCheck(rx.State, mixin=True):
    """One check tool: run it, list the problems, export them."""

    output_fields: ClassVar[tuple[str, ...]] = ("checked", "total", "problems", "error")

    CHECK: ClassVar[CheckSpec]
    checking: bool = False
    checked: bool = False
    total: int = 0
    problems: list[dict[str, str]] = []
    error: str = ""
    input_value: str = ""

    @rx.event
    def set_input_value(self, value: str):
        self.input_value = value

    @rx.event
    async def run_check(self):
        spec = self.CHECK
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        args = (self.input_value,) if spec.input_label else ()
        if spec.input_label and not spec.input_optional and not self.input_value.strip():
            yield rx.toast.error(f"Enter the {spec.input_label.lower()} first.")
            return
        self.checking = True
        self.checked = False
        self.error = ""
        self.problems = []
        yield
        log = self._tool_log(f"RedSky {spec.title}", f"redsky-{spec.slug}", conn)
        try:
            if args and self.input_value.strip():
                log.info(f"{spec.input_label}: {self.input_value}")
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                total, problems = await asyncio.to_thread(spec.run, client, *args)
            except UserError as e:
                self.error = str(e)
                log.error(str(e))
                return
            except Exception as e:  # unexpected: show it rather than hang the spinner
                self.error = f"Unexpected error: {e}"
                log.error(f"Failed unexpectedly: {e!r}")
                return
            finally:
                self.checking = False
            self.total, self.problems, self.checked = total, problems, True
            log.info(f"{len(problems)} of {total} {spec.noun}(s) have a problem")
            for p in problems:
                log.warning(", ".join(f"{k}={v}" for k, v in p.items()))
        finally:
            log.close()

    @rx.event
    def export_csv(self):
        spec = self.CHECK
        keys = [k for k, _h in spec.columns]
        data = csv_bytes(keys, [[p[k] for k in keys] for p in self.problems])
        return rx.download(data=data, filename=f"redsky_{spec.slug.replace('-', '_')}.csv")


class AddBuildingsState(RedskyState, RedskyBulk):
    SPEC = geo.BUILDINGS_ADD
    row: dict[str, str] = _blank(geo.BUILDINGS_ADD)


class AddLocationsState(RedskyState, RedskyBulk):
    SPEC = geo.LOCATIONS_ADD
    row: dict[str, str] = _blank(geo.LOCATIONS_ADD)


class PrimaryLocationState(RedskyState, RedskyCheck):
    CHECK = audit.PRIMARY_LOCATION


class NoLocationsState(RedskyState, RedskyCheck):
    CHECK = audit.NO_LOCATIONS


class NoTrackingState(RedskyState, RedskyCheck):
    CHECK = audit.NO_TRACKING


class AddAlertsState(RedskyState, RedskyBulk):
    """Add-Edit Alerts. The Edit tab loads nothing until the user searches, then loads the clicked alert."""

    SPEC = alerts.ALERTS_ADD
    output_fields: ClassVar[tuple[str, ...]] = ("edit_found", "edit_searched", "edit_id", "edit_row", "edit_warnings")
    row: dict[str, str] = _blank(alerts.ALERTS_ADD)
    edit_query: str = ""
    edit_busy: bool = False
    edit_searched: bool = False
    edit_found: list[dict[str, str]] = []
    edit_id: str = ""
    edit_row: dict[str, str] = _blank(alerts.ALERTS_ADD)
    edit_warnings: list[str] = []

    @rx.event
    def set_edit_query(self, value: str):
        self.edit_query = value

    @rx.event
    def edit_query_key(self, key: str):
        if key == "Enter" and not self.edit_busy:
            return AddAlertsState.search_alerts

    @rx.event
    def set_edit_field(self, field: str, value: str):
        self.edit_row = {**self.edit_row, field: value}

    @rx.event
    def cancel_edit(self):
        self.edit_id = ""
        self.edit_row = _blank(alerts.ALERTS_ADD)
        self.edit_warnings = []

    @rx.event
    async def search_alerts(self):
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        self.edit_busy = True
        self.edit_found = []
        self.cancel_edit()
        yield
        log = self._tool_log("RedSky Edit Alerts: Search", "redsky-alerts-edit", conn)
        try:
            log.info(f"Search: {self.edit_query!r}")
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                found = await asyncio.to_thread(alerts.search_alerts, client, self.edit_query)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            finally:
                self.edit_busy = False
            self.edit_found, self.edit_searched = found, True
            log.info(f"{len(found)} alert(s) found")
        finally:
            log.close()

    @rx.event
    async def load_alert(self, alert_id: str):
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        self.edit_busy = True
        yield
        log = self._tool_log("RedSky Edit Alerts: Load", "redsky-alerts-edit", conn)
        try:
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                row, warnings = await asyncio.to_thread(alerts.load_alert, client, alert_id)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            except Exception as e:  # unexpected: show it rather than fail silently
                log.error(f"Failed unexpectedly: {e!r}")
                yield rx.toast.error(f"Unexpected error: {e}")
                return
            finally:
                self.edit_busy = False
            self.edit_id, self.edit_row, self.edit_warnings = alert_id, row, warnings
            log.info(f"Loaded alert {row['name']}")
            for w in warnings:
                log.warning(w)
        finally:
            log.close()

    @rx.event
    async def save_alert(self):
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        if not self.edit_id:
            return
        self.edit_busy = True
        yield
        row = {k: v.strip() for k, v in self.edit_row.items()}
        log = self._tool_log("RedSky Edit Alerts: Save", "redsky-alerts-edit", conn)
        try:
            log.info(f"Saving alert {row['name']} (id {self.edit_id})")
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                detail = await asyncio.to_thread(alerts.save_alert, client, self.edit_id, row)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            except Exception as e:  # unexpected: show it rather than hang the spinner
                log.error(f"Failed unexpectedly: {e!r}")
                yield rx.toast.error(f"Unexpected error: {e}")
                return
            finally:
                self.edit_busy = False
            log.info(detail)
            self.edit_found = [{**f, "name": row["name"]} if f["id"] == self.edit_id else f for f in self.edit_found]
            yield rx.toast.success(detail)
        finally:
            log.close()


class AlertsCheckState(RedskyState, RedskyCheck):
    CHECK = alerts.ALERTS_CHECK

    @rx.event
    async def open_in_add_alerts(self, building: str):
        """Building name clicked in the results: open Add-Edit Alerts with the name and scope filled in."""
        add = await self.get_state(AddAlertsState)
        add.row = {**_blank(alerts.ALERTS_ADD), "name": building, "scope": building}
        return rx.redirect("/redsky/alerts-add")


class BssidState(RedskyState, RedskyBulk):
    SPEC = net.BSSID
    row: dict[str, str] = _blank(net.BSSID)


class LldpState(RedskyState, RedskyBulk):
    SPEC = net.LLDP
    row: dict[str, str] = _blank(net.LLDP)


class PrivateIpState(RedskyState, RedskyBulk):
    SPEC = net.PRIVATE_IP
    row: dict[str, str] = _blank(net.PRIVATE_IP)


class PublicIpState(RedskyState, RedskyBulk):
    SPEC = net.PUBLIC_IP
    row: dict[str, str] = _blank(net.PUBLIC_IP)


class PrecheckState(RedskyState, PasteMixin):
    """Import Precheck: do the pasted or uploaded Buildings, Locations or Private IP ranges already exist in RedSky?"""

    output_fields: ClassVar[tuple[str, ...]] = ("found", "checked", "error")

    kind: str = "Buildings"
    paste_names: str = ""
    checking: bool = False
    checked: bool = False
    error: str = ""
    found: list[dict[str, str]] = []
    result_kind: str = "Buildings"

    @rx.event
    def set_kind(self, value: str):
        self.kind = value

    @rx.var
    def exists_count(self) -> int:
        return sum(1 for r in self.found if r["status"] == "Exists")

    @rx.var
    def other_count(self) -> int:
        return len(self.found) - self.exists_count

    async def _check(self, entries: list[tuple[str, str]], source: str):
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        if not entries:
            yield rx.toast.error("No names found in the input.")
            return
        kind = self.kind
        self.checking, self.checked, self.error, self.found = True, False, "", []
        yield
        log = self._tool_log(f"RedSky Import Precheck ({kind}) {source}", "redsky-import-precheck", conn)
        try:
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                if kind == "Private IPs":
                    rows = await asyncio.to_thread(pre.precheck_ips, client, entries)
                elif kind == "Buildings":
                    rows = await asyncio.to_thread(pre.precheck_buildings, client, entries)
                else:
                    rows = await asyncio.to_thread(pre.precheck, client, kind, entries)
            except UserError as e:
                self.error = str(e)
                log.error(str(e))
                return
            except Exception as e:  # unexpected: show it rather than hang the spinner
                self.error = f"Unexpected error: {e}"
                log.error(f"Failed unexpectedly: {e!r}")
                return
            finally:
                self.checking = False
            self.found, self.checked, self.result_kind = rows, True, kind
            if getattr(client, "ip_list_used", ""):
                log.info(f"IP range list endpoint: {client.ip_list_used}")
            for r in rows:
                log.info(f"{r['name']} {r['building']}".strip() + f": {r['status']} {r['detail']} {r['range']}".rstrip())
        finally:
            log.close()

    @rx.event
    async def check_text(self):
        if not self.paste_names.strip():
            yield rx.toast.error("Paste some text first.")
            return
        async for ev in self._check(pre.parse_text(self.paste_names, self.kind), "from pasted text"):
            yield ev

    @rx.event
    async def check_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            entries = pre.parse_csv(await files[0].read(), self.kind)
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        async for ev in self._check(entries, f"from CSV ({files[0].filename})"):
            yield ev
        yield rx.clear_selected_files("precheck_upload")

    @rx.event
    def export_csv(self):
        keys = [k for k, _h in pre.columns(self.result_kind)]
        data = csv_bytes(keys, [[r[k] for k in keys] for r in self.found])
        return rx.download(data=data, filename=f"redsky_import_precheck_{self.result_kind.lower().replace(' ', '_')}.csv")


class DuplicatesState(RedskyState):
    """Find Duplicate Buildings: Buildings that share an address, optionally with their tracking."""

    checking: bool = False
    checked: bool = False
    error: str = ""
    total: int = 0
    rows: list[dict[str, str]] = []

    @rx.var
    def group_count(self) -> int:
        return len({r["group"] for r in self.rows})

    @rx.event
    async def run_find(self):
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        self.checking, self.checked, self.error, self.rows = True, False, "", []
        yield
        log = self._tool_log("RedSky Find Duplicate Buildings", "redsky-duplicate-buildings", conn)
        try:
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                total, rows, _groups = await asyncio.to_thread(audit.find_duplicates, client)
            except UserError as e:
                self.error = str(e)
                log.error(str(e))
                return
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"Failed unexpectedly: {e!r}")
                return
            finally:
                self.checking = False
            self.total, self.rows, self.checked = total, rows, True
            log.info(f"{len({r['group'] for r in rows})} duplicate group(s) in {total} building(s)")
            for r in rows:
                log.info(f"Group {r['group']}: {r['building']} ({r['address']}), {r['locations']} location(s)")
        finally:
            log.close()

    @rx.event
    def export_excel(self):
        data = audit.duplicate_workbook(self.rows)
        return rx.download(data=data, filename="redsky_duplicate_buildings.xlsx")


class RemediateState(RedskyState, RunMixin):
    """Remediate Duplicate Buildings: pick the Building to keep per address, preview, then move and delete."""

    scanning: bool = False
    scanned: bool = False
    error: str = ""
    groups: list[dict[str, Any]] = []
    planning: bool = False
    previewed: bool = False
    preview: list[dict[str, str]] = []
    confirm_open: bool = False

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.var
    def dup_count(self) -> int:
        return sum(len(g["options"]) - 1 for g in self.groups)

    def _choices(self) -> list[tuple[str, list[str]]]:
        out = []
        for g in self.groups:
            keep_id = g["ids"][g["options"].index(g["keep"])]
            out.append((keep_id, [i for i in g["ids"] if i != keep_id]))
        return out

    @rx.event
    def set_keep(self, group_id: str, label: str):
        self.groups = [{**g, "keep": label} if g["id"] == group_id else g for g in self.groups]
        self.previewed, self.preview = False, []

    @rx.event
    async def scan(self):
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        self.scanning, self.scanned, self.error = True, False, ""
        self.groups, self.preview, self.previewed = [], [], False
        yield
        log = self._tool_log("RedSky Remediate Duplicate Buildings: scan", "redsky-duplicates-scan", conn)
        try:
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                buildings, locs = await asyncio.to_thread(audit.locations_of, client)
                audit.require_addresses(buildings)
                groups = audit.duplicate_groups(buildings)
            except UserError as e:
                self.error = str(e)
                log.error(str(e))
                return
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"Failed unexpectedly: {e!r}")
                return
            finally:
                self.scanning = False
            self.groups = audit.group_options(groups, locs)
            self.scanned = True
            log.info(f"{len(groups)} duplicate group(s) in {len(buildings)} building(s)")
        finally:
            log.close()

    @rx.event
    async def make_preview(self):
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        choices = self._choices()
        self.planning, self.error, self.previewed = True, "", False
        yield
        log = self._tool_log("RedSky Remediate Duplicate Buildings: preview", "redsky-duplicates-preview", conn)
        try:
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                plans, locs, tracking = await asyncio.to_thread(audit.build_plans, client, choices)
                rows = audit.preview_rows(plans, locs, tracking)
            except UserError as e:
                self.error = str(e)
                log.error(str(e))
                return
            except Exception as e:
                self.error = f"Unexpected error: {e}"
                log.error(f"Failed unexpectedly: {e!r}")
                return
            finally:
                self.planning = False
            self.preview, self.previewed = rows, True
            for r in rows:
                log.info(f"Keep {r['keep']}, delete {r['duplicate']}: {r['locations']} location(s), "
                         f"{r['macs']} MAC, {r['lldp']} LLDP, {r['bssids']} BSSID, {r['ips']} Private IP")
        finally:
            log.close()

    @rx.event
    async def remediate(self):
        self.confirm_open = False
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        if self.busy or not self.previewed:
            return
        choices = self._choices()
        log = self._tool_log("RedSky Remediate Duplicate Buildings", "redsky-duplicates-remediate", conn)
        try:
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                plans, locs, tracking = await asyncio.to_thread(audit.build_plans, client, choices)
                items = audit.remediation_items(client, plans, locs, tracking)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            except Exception as e:
                log.error(f"Failed unexpectedly: {e!r}")
                yield rx.toast.error(f"Unexpected error: {e}")
                return
            yield self._start_run(items, "Remediating", log, then="_after_remediate")
        finally:
            log.close()

    def _after_remediate(self, log: OpLog):
        self.groups, self.preview, self.previewed, self.scanned = [], [], False, False
        log.info("Scan again to see what is left")
