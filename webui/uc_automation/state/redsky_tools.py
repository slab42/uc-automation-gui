"""States for the RedSky tool pages.

Every add tool is `class X(RedskyState, RedskyBulk)` with an AddSpec (backend/redsky_common.py) as SPEC; every
check tool is `class X(RedskyState, RedskyCheck)` with a CheckSpec. The mixins hold all the handlers, so a
new tool is a spec plus a few lines here and a page builder call.
"""

import asyncio
from typing import ClassVar

import reflex as rx

from ..backend import redsky_alerts as alerts, redsky_geography as geo, redsky_networking as net, redsky_precheck as pre
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

    async def _execute(self, rows: list[list[str]], title: str):
        spec = self.SPEC
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
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
            async for ev in self._run_items(items, "Adding", log):
                yield ev
        finally:
            log.close()

    @rx.event
    async def add_single(self):
        spec = self.SPEC
        row = [self.row.get(f.key, "").strip() for f in spec.fields]
        async for ev in self._execute([row], f"RedSky {spec.title}"):
            yield ev
        if self.results and self.result_fail_count == 0:
            self.row = _blank(spec)

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
        async for ev in self._execute(rows, f"RedSky {spec.title} from CSV ({files[0].filename})"):
            yield ev
        yield rx.clear_selected_files(f"{spec.slug}_upload")

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

    CHECK: ClassVar[CheckSpec]
    checking: bool = False
    checked: bool = False
    total: int = 0
    problems: list[dict[str, str]] = []
    error: str = ""

    @rx.event
    async def run_check(self):
        spec = self.CHECK
        conn = self._conn()
        if conn is None:
            yield rx.toast.error(_NO_CONNECTION)
            return
        self.checking = True
        self.checked = False
        self.error = ""
        self.problems = []
        yield
        log = self._tool_log(f"RedSky {spec.title}", f"redsky-{spec.slug}", conn)
        try:
            try:
                client = await asyncio.to_thread(RedskyClient, conn.username, conn.password, conn.org_id)
                total, problems = await asyncio.to_thread(spec.run, client)
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


class EntireSiteState(RedskyState, RedskyCheck):
    CHECK = geo.ENTIRE_SITE


class AddAlertsState(RedskyState, RedskyBulk):
    SPEC = alerts.ALERTS_ADD
    row: dict[str, str] = _blank(alerts.ALERTS_ADD)


class AlertsCheckState(RedskyState, RedskyCheck):
    CHECK = alerts.ALERTS_CHECK


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
