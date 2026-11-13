"""State for CUCM > Migration > Cutover Cleanup: remediate hunt groups, delete devices and orphan DNs, then remediate
what is left unused."""

import asyncio
from typing import ClassVar

import reflex as rx

from ..backend import cucm_cleanup as cl
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from .cucm import CucmState
from .run_mixin import RunMixin


class CleanupState(CucmState, RunMixin):
    output_fields: ClassVar[tuple[str, ...]] = (
        "hunt_rows", "hunt_selected", "hunt_scanned", "hunt_error",
        "rem_rows", "rem_filter", "rem_only_unused", "rem_selected", "rem_warnings", "rem_scanned", "rem_kind")

    # Page inputs
    input_open: bool = True
    paste_dns: str = ""
    prefix: str = ""
    number_length: str = ""
    paste_devices: str = ""
    confirm_devices: bool = False

    # 1. hunt groups
    hunt_rows: list[dict[str, str]] = []
    hunt_selected: list[str] = []
    hunt_scanned: bool = False
    hunt_error: str = ""
    hunt_scanning: bool = False
    confirm_hunt: str = ""  # "", "remove" or "delete"

    # 3 to 9. unused objects
    rem_search: str = ""
    rem_kind: str = ""
    rem_rows: list[dict[str, str]] = []
    rem_filter: str = ""  # filters the result table
    rem_only_unused: bool = False
    rem_selected: list[str] = []
    rem_warnings: list[str] = []
    rem_scanned: bool = False
    rem_scanning: bool = False
    confirm_rem: bool = False

    @rx.var
    def dn_count(self) -> int:
        try:
            return len(cl.parse_dns(self.paste_dns, self.prefix, self.number_length)) if self.paste_dns.strip() else 0
        except ValueError:
            return 0

    @rx.var
    def device_count(self) -> int:
        return len(cl.parse_devices(self.paste_devices))

    @rx.var
    def rem_title(self) -> str:
        return cl.TITLES.get(self.rem_kind, "")

    @rx.var
    def rem_noun(self) -> str:
        return cl.NOUNS.get(self.rem_kind, "")

    @rx.var
    def rem_shown(self) -> list[dict[str, str]]:
        """The rows in the table: all of them, or only the unused ones after clicking the unused badge, narrowed by
        the filter text (matches any column)."""
        rows = [r for r in self.rem_rows if r["status"] == "Unused"] if self.rem_only_unused else self.rem_rows
        q = self.rem_filter.strip().lower()
        if q:
            rows = [r for r in rows if any(q in str(r.get(k, "")).lower() for k in ("name", "status", "detail"))]
        return rows

    @rx.var
    def rem_unused(self) -> list[str]:
        """Unused objects among the rows currently shown (so Select All Unused respects the filter)."""
        return [r["name"] for r in self.rem_shown if r["status"] == "Unused"]

    @rx.var
    def working(self) -> bool:
        return self.busy | self.hunt_scanning | self.rem_scanning

    # --- inputs ---

    @rx.event
    def toggle_input(self):
        self.input_open = not self.input_open

    @rx.event
    def set_paste_dns(self, value: str):
        self.paste_dns = value

    @rx.event
    def set_prefix(self, value: str):
        self.prefix = value

    @rx.event
    def set_number_length(self, value: str):
        self.number_length = "".join(c for c in value if c.isdigit())[:3]

    @rx.event
    def set_paste_devices(self, value: str):
        self.paste_devices = value

    @rx.event
    def set_rem_filter(self, value: str):
        self.rem_filter = value

    @rx.event
    def set_rem_search(self, value: str):
        self.rem_search = value

    @rx.event
    def set_confirm_devices(self, value: bool):
        self.confirm_devices = value

    @rx.event
    def set_confirm_rem(self, value: bool):
        self.confirm_rem = value

    @rx.event
    def set_confirm_hunt(self, value: str):
        self.confirm_hunt = value

    @rx.event
    async def load_dn_csv(self, files: list[rx.UploadFile]):
        """A CSV file fills the Paste Text box, so both inputs go through the same handlers."""
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        self.paste_dns = (await files[0].read()).decode("utf-8-sig", errors="replace")
        yield rx.toast.success(f"Loaded {files[0].filename}. Check the list on the Paste Text tab.")

    @rx.event
    async def load_device_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        self.paste_devices = (await files[0].read()).decode("utf-8-sig", errors="replace")
        yield rx.toast.success(f"Loaded {files[0].filename}. Check the list on the Paste Text tab.")

    def _dns(self) -> list[dict[str, str]]:
        try:
            return cl.parse_dns(self.paste_dns, self.prefix, self.number_length) if self.paste_dns.strip() else []
        except ValueError:
            return []

    # --- 2. delete devices and orphan DNs ---

    @rx.event
    def run_delete_devices(self):
        self.confirm_devices = False
        if self.busy:
            return
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUCM connection first.")
            return
        try:
            dns = cl.parse_dns(self.paste_dns, self.prefix, self.number_length) if self.paste_dns.strip() else []
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        devices = cl.parse_devices(self.paste_devices)
        if not dns and not devices:
            yield rx.toast.error("Enter directory numbers, device names or both.")
            return
        self.input_open = False
        log = OpLog("Cleanup delete devices and orphan DNs", "cleanup-delete-devices")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Source: {len(devices)} device(s), {len(dns)} directory number(s)")
            log.info(f"Devices: {', '.join(devices) or '(none)'}")
            log.info(f"Directory numbers: {', '.join(cl.dn_label(r) for r in dns) or '(none)'}")
            # Devices first (one at a time), so their DNs are free before the listed DNs are checked.
            items = [(f"Device {d}", (lambda d=d: cl.remove_device(conn, d))) for d in devices]
            items += [(f"DN {cl.dn_label(r)}", (lambda r=r: cl.remove_listed_dn(conn, r))) for r in dns]
            yield self._start_run(items, "Deleting", log)
        finally:
            log.close()

    # --- 1. hunt groups ---

    @rx.event
    async def scan_hunt(self):
        if self.working:
            return
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUCM connection first.")
            return
        dns = self._dns()
        if not dns:
            yield rx.toast.error("Enter directory numbers first.")
            return
        self.input_open = False
        self.hunt_scanning, self.hunt_error, self.hunt_rows, self.hunt_selected = True, "", [], []
        self.hunt_scanned = False
        yield
        log = OpLog("Cleanup find hunt pilots, hunt lists and line groups with DNs", "cleanup-find-hunt-groups")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Source: {len(dns)} directory number(s)")
            try:
                rows = await asyncio.to_thread(cl.find_hunt_objects, conn, dns)
            except AxlError as e:
                log.error(f"Failed: {e}")
                self.hunt_error = str(e)
            except Exception as e:
                log.error(f"Failed unexpectedly: {e!r}")
                self.hunt_error = f"Unexpected error: {e}"
            else:
                log.info(f"{len(rows)} hunt object(s) use these DNs")
                for r in rows:
                    state = "can be deleted" if r["deletable"] == "1" else f"blocked: {r['reason']}"
                    log.info(f"{r['kind']} {r['name']}: {r['matched'] or '-'} ({r['related']}) {state}")
                self.hunt_rows, self.hunt_scanned = rows, True
        finally:
            log.close()
            self.hunt_scanning = False

    @rx.event
    def toggle_hunt(self, key: str, checked: bool):
        self.hunt_selected = [n for n in self.hunt_selected if n != key] + ([key] if checked else [])

    @rx.event
    def select_all_hunt(self):
        """Only the rows that may be deleted."""
        self.hunt_selected = [r["key"] for r in self.hunt_rows if r["deletable"] == "1"]

    @rx.event
    def clear_hunt(self):
        self.hunt_selected = []

    @rx.event
    def run_hunt(self):
        mode, self.confirm_hunt = self.confirm_hunt, ""
        if self.busy or not self.hunt_selected or mode not in ("remove", "delete"):
            return
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUCM connection first.")
            return
        dns = self._dns()
        rows = {r["key"]: r for r in self.hunt_rows if r["key"] in self.hunt_selected}
        if mode == "remove":  # members can be removed from any line group, including ones that hold other numbers
            keys = [k for k, r in rows.items() if r["kind"] == "Line Group"]
        else:  # the same safety rule as the table: never a row that is blocked
            keys = [k for k, r in rows.items() if r["deletable"] == "1"]
        if not keys:
            yield rx.toast.error("Nothing selected can be " + ("changed." if mode == "remove" else "deleted."))
            return
        self.input_open = False
        order = {"Hunt Pilot": 0, "Hunt List": 1, "Line Group": 2}  # pilots, then hunt lists, then line groups
        keys.sort(key=lambda k: order[rows[k]["kind"]])
        title = "Remove DNs from line groups" if mode == "remove" else "Delete hunt objects"
        log = OpLog(f"Cleanup {title.lower()}", f"cleanup-{mode}-hunt-groups")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Selected: {len(keys)}: {', '.join(rows[k]['kind'] + ' ' + rows[k]['name'] for k in keys)}")
            log.info(f"Directory numbers in the list: {', '.join(cl.dn_label(r) for r in dns)}")
            if mode == "remove":
                items = [(k, (lambda n=rows[k]["name"]: cl.remove_dns_from_line_group(conn, n, dns))) for k in keys]
            else:
                items = [(k, (lambda k=k: cl.remove_hunt_object(conn, k, dns))) for k in keys]
            yield self._start_run(items, "Removing" if mode == "remove" else "Deleting", log, then="_after_hunt")
        finally:
            log.close()

    def _after_hunt(self, log):
        """Drop the rows that were changed (deleted, or a line group that no longer holds any of the DNs)."""
        done = {r["key"] for r in self.results if r["status"] == "OK"}
        self.hunt_rows = [r for r in self.hunt_rows if r["key"] not in done]
        self.hunt_selected = [n for n in self.hunt_selected if n not in done]

    # --- 3 to 9. unused objects ---

    @rx.event
    async def scan_kind(self, kind: str):
        if self.working:
            return
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUCM connection first.")
            return
        search = self.rem_search.strip()
        if kind in cl.NEEDS_SEARCH and not search:
            yield rx.toast.error(f"Enter text to search {cl.TITLES[kind]} by name first.")
            return
        self.input_open = False
        self.rem_scanning, self.rem_kind, self.rem_rows, self.rem_selected = True, kind, [], []
        self.rem_warnings, self.rem_scanned, self.rem_only_unused = [], False, False
        self.rem_filter = ""
        yield
        log = OpLog(f"Cleanup find unused {cl.TITLES[kind].lower()}", f"cleanup-unused-{kind}")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Search: {search or '(all)'}")
            try:
                rows, warnings = await asyncio.to_thread(cl.scan_unused, conn, kind, search)
            except AxlError as e:
                log.error(f"Failed: {e}")
                self.rem_warnings = [str(e)]
            except Exception as e:
                log.error(f"Failed unexpectedly: {e!r}")
                self.rem_warnings = [f"Unexpected error: {e}"]
            else:
                for w in warnings:
                    log.warning(w)
                for r in rows:
                    log.info(f"{r['name']}: {r['status']} ({r['count']} source(s))")
                self.rem_rows, self.rem_warnings, self.rem_scanned = rows, warnings, True
        finally:
            log.close()
            self.rem_scanning = False

    @rx.event
    def toggle_only_unused(self):
        self.rem_only_unused = not self.rem_only_unused

    @rx.event
    def toggle_rem(self, name: str, checked: bool):
        self.rem_selected = [n for n in self.rem_selected if n != name] + ([name] if checked else [])

    @rx.event
    def select_unused(self):
        self.rem_selected = list(self.rem_unused)

    @rx.event
    def clear_rem(self):
        self.rem_selected = []

    @rx.event
    def run_rem_delete(self):
        self.confirm_rem = False
        if self.busy or not self.rem_selected or self.rem_kind not in cl.REMOVERS:
            return
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUCM connection first.")
            return
        self.input_open = False
        kind, names = self.rem_kind, list(self.rem_selected)
        log = OpLog(f"Cleanup delete {cl.TITLES[kind].lower()}", f"cleanup-delete-{kind}")
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Selected: {len(names)} {cl.NOUNS[kind]}(s): {', '.join(names)}")
            items = [(n, (lambda n=n: cl.remove_unused(conn, kind, n))) for n in names]
            yield self._start_run(items, "Deleting", log, then="_after_rem")
        finally:
            log.close()

    def _after_rem(self, log):
        """Drop the deleted objects from the list."""
        done = {r["key"] for r in self.results if r["status"] == "OK"}
        self.rem_rows = [r for r in self.rem_rows if r["name"] not in done]
        self.rem_selected = [n for n in self.rem_selected if n not in done]
