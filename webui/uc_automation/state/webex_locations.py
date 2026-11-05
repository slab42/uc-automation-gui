"""States for Webex > Locations: Schedules (export, update from CSV, copy, remove past events), E911 and Migrate PSTN."""

import asyncio
import re
from datetime import datetime

import reflex as rx

from ..backend import webex_locations as L
from ..backend.applog import OpLog
from ..backend.errors import UserError
from .run_mixin import RunMixin
from .webex_groups import PickerMixin
from .webex_routing import PasteMixin, WebexSession, _one

ALL_SCHEDULES = "All Schedules"


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


class SchedulesState(WebexSession, RunMixin, PickerMixin, PasteMixin):
    mode: str = "export"          # export | update | copy | remove
    schedules: list[dict[str, str]] = []
    schedule_label: str = ""
    confirm_open: bool = False

    # update from CSV
    plan_rows: list[dict[str, str]] = []
    plan_notes: list[str] = []
    _plan: list[dict] = []

    # copy
    copy_scope: str = "one"       # all | one
    copy_target: str = ""

    # remove past events
    remove_scope: str = "all"     # all | one
    past_rows: list[dict[str, str]] = []
    past_selected: list[str] = []
    searched: bool = False
    paste_schedule: str = ""

    def _fetch_rows(self, client):
        return L.list_locations(client)

    def _noun(self) -> str:
        return "locations"

    @rx.var
    def schedule_labels(self) -> list[str]:
        return [s["label"] for s in self.schedules]

    @rx.var
    def copy_schedule_labels(self) -> list[str]:
        """Source choices for Copy: every schedule, plus a choice that copies all of them."""
        return ([ALL_SCHEDULES] if self.schedules else []) + self.schedule_labels

    @rx.var
    def location_names(self) -> list[str]:
        return [r["name"] for r in self.rows if r["id"] != self.selected_id]

    @rx.var
    def needs_location_pick(self) -> bool:
        """The location list is shown unless the mode works on all locations."""
        return not (self.mode == "remove" and self.remove_scope == "all")

    @rx.var
    def target_count(self) -> int:
        if self.copy_scope == "one":
            return 1 if self.copy_target in self.location_names else 0
        return sum(1 for r in self.rows if r["id"] != self.selected_id)

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    def set_schedule_label(self, value: str):
        self.schedule_label = value

    @rx.event
    def set_copy_scope(self, value: str | list[str]):
        self.copy_scope = _one(value)

    @rx.event
    def set_copy_target(self, value: str):
        self.copy_target = value

    @rx.event
    def set_remove_scope(self, value: str | list[str]):
        self.remove_scope = _one(value)
        self.past_rows, self.past_selected, self.searched = [], [], False

    @rx.event
    async def set_mode(self, value: str | list[str]):
        self.mode = _one(value)
        self.results = []
        self.plan_rows, self.plan_notes, self._plan = [], [], []
        if self.mode in ("export", "copy") and self.selected_id and not self.schedules:
            async for ev in self._load_schedules():
                yield ev

    @rx.event
    async def select_row(self, row_id: str):
        self.selected_id = row_id
        self.schedules, self.schedule_label = [], ""
        self.plan_rows, self.plan_notes, self._plan = [], [], []
        if self.mode in ("export", "copy") and row_id:
            async for ev in self._load_schedules():
                yield ev

    async def _load_schedules(self):
        loc = self.selected_row
        if not loc:
            return
        log = self._webex_log("List location schedules", "webex-list-schedules")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                self.schedules = await asyncio.to_thread(L.list_schedules, client, loc["id"])
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            log.info(f"{loc['name']}: {len(self.schedules)} schedule(s)")
            if not self.schedules:
                yield rx.toast.info(f"{loc['name']} has no schedules.")
        finally:
            log.close()

    def _picked_schedule(self) -> dict[str, str]:
        return next((s for s in self.schedules if s["label"] == self.schedule_label), {})

    # --- export ---

    @rx.event
    async def export_csv(self):
        loc, sched = self.selected_row, self._picked_schedule()
        if not loc or not sched:
            yield rx.toast.error("Select a location and a schedule.")
            return
        log = self._webex_log("Export location schedule", "webex-export-schedule")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                detail = await asyncio.to_thread(L.get_schedule, client, loc["id"], sched["type"], sched["id"])
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            events = detail.get("events", [])
            log.info(f"Exported {len(events)} event(s) of {sched['name']} at {loc['name']}")
            yield rx.download(data=L.export_schedule_csv(sched["name"], events),
                              filename=f"holiday_schedule_{_safe(loc['name'])}_{_safe(sched['name'])}.csv")
        finally:
            log.close()

    # --- update from CSV ---

    @rx.event
    async def review_update(self, files: list[rx.UploadFile]):
        async for ev in self._review_update(files):
            yield ev

    @rx.event
    async def review_update_text(self):
        async for ev in self._from_paste(self._review_update, "schedule", columns=L.CSV_HEADER,
                                         markers=("event action", "event name")):
            yield ev

    async def _review_update(self, files: list[rx.UploadFile]):
        if self.busy:
            return
        loc = self.selected_row
        if not loc:
            yield rx.toast.error("Select the location first.")
            return
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            schedules, warnings = L.parse_holiday_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not schedules:
            yield rx.toast.error("No valid rows were found in the CSV.")
            return
        log = self._webex_log("Review schedule update", "webex-schedule-review")
        try:
            self.busy, self.progress = True, "Comparing with the location"
            yield
            log.info(f"{loc['name']}, CSV file: {files[0].filename}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                plan = await asyncio.to_thread(L.build_update_plan, client, loc["id"], schedules)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            self._plan = plan
            self.plan_rows = [{"name": p["name"], "action": "Update existing" if p["schedule"] else "Create new",
                               "add": str(len(p["adds"])), "remove": str(len(p["removes"]))} for p in plan]
            self.plan_notes = warnings + [f"{p['name']}: {n}" for p in plan for n in p["notes"]]
            for n in self.plan_notes:
                log.warning(n)
            yield rx.clear_selected_files("schedule_upload")
        finally:
            log.close()
            self.busy, self.progress = False, ""

    @rx.var
    def plan_has_changes(self) -> bool:
        return any(r["add"] != "0" or r["remove"] != "0" for r in self.plan_rows)

    @rx.event
    async def run_update(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        loc, plan = self.selected_row, [p for p in self._plan if p["adds"] or p["removes"]]
        if not loc or not plan:
            yield rx.toast.error("Nothing to apply. Review a CSV first.")
            return
        log = self._webex_log("Update location schedule from CSV", "webex-schedule-update")
        try:
            log.info(f"{loc['name']}: {len(plan)} schedule(s)")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            loc_id = loc["id"]
            items = [(p["name"], lambda p=p: L.apply_update_plan(client, loc_id, [p])[0][1]) for p in plan]
            yield self._start_run(items, "Updating", log, then="_after_update")
        finally:
            log.close()

    def _after_update(self, log: OpLog):
        self.plan_rows, self.plan_notes, self._plan = [], [], []

    # --- copy ---

    @rx.event
    async def run_copy(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        source = self.selected_row
        all_scheds = self.schedule_label == ALL_SCHEDULES
        scheds = list(self.schedules) if all_scheds else [s for s in [self._picked_schedule()] if s]
        if not source or not scheds:
            yield rx.toast.error("Select the source location and schedule.")
            return
        if self.copy_scope == "one":
            targets = [r for r in self.rows if r["name"] == self.copy_target and r["id"] != source["id"]]
        else:
            targets = [r for r in self.rows if r["id"] != source["id"]]
        if not targets:
            yield rx.toast.error("No target locations selected.")
            return
        log = self._webex_log("Copy location schedule", "webex-copy-schedule")
        try:
            log.info(f"{self.schedule_label} from {source['name']} to {len(targets)} location(s)")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            bodies = []
            try:
                for sched in scheds:
                    detail = await asyncio.to_thread(L.get_schedule, client, source["id"], sched["type"], sched["id"])
                    bodies.append((sched, L.copy_body(sched, detail)))
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            items = [(f"{t['name']}: {sched['name']}" if all_scheds else t["name"],
                      lambda tid=t["id"], sched=sched, body=body:
                      L.copy_schedule_to(client, body, sched["type"], sched["name"], tid))
                     for t in targets for sched, body in bodies]
            yield self._start_run(items, "Copying", log)
        finally:
            log.close()

    # --- remove past events ---

    @rx.event
    async def find_past(self):
        if self.busy:
            return
        locs = self.rows if self.remove_scope == "all" else ([self.selected_row] if self.selected_row else [])
        if not locs:
            yield rx.toast.error("Select a location first.")
            return
        today = datetime.now().strftime("%Y-%m-%d")
        log = self._webex_log("Find past schedule events", "webex-past-events")
        try:
            self.busy, self.searched = True, False
            self.past_rows, self.past_selected, self.results = [], [], []
            yield
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            found: list[dict[str, str]] = []
            for i, loc in enumerate(locs, 1):
                self.progress = f"Checking location {i} of {len(locs)}: {loc['name']}"
                yield
                try:
                    found.extend(await asyncio.to_thread(L.find_past_events, client, loc, today))
                except UserError as e:
                    log.error(f"{loc['name']}: {e}")
            log.info(f"{len(found)} past event(s) in {len(locs)} location(s)")
            self.past_rows = found
            self.past_selected = [r["key"] for r in found]
            self.searched = True
        finally:
            log.close()
            self.busy, self.progress = False, ""

    @rx.event
    def toggle_past(self, key: str, checked: bool):
        if checked and key not in self.past_selected:
            self.past_selected.append(key)
        elif not checked and key in self.past_selected:
            self.past_selected.remove(key)

    @rx.event
    def select_all_past(self):
        self.past_selected = [r["key"] for r in self.past_rows]

    @rx.event
    def select_no_past(self):
        self.past_selected = []

    @rx.event
    async def run_remove(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        chosen = [dict(r) for r in self.past_rows if r["key"] in self.past_selected]
        if not chosen:
            yield rx.toast.error("Nothing selected.")
            return
        log = self._webex_log("Remove past schedule events", "webex-remove-past-events")
        try:
            log.info(f"{len(chosen)} event(s)")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            items = [(f"{r['location']} - {r['schedule']} - {r['event']} - {r['dates']}",
                      lambda r=r: L.delete_event(client, r), {"eventKey": r["key"]}) for r in chosen]
            yield self._start_run(items, "Deleting", log, then="_after_remove")
        finally:
            log.close()

    def _after_remove(self, log: OpLog):
        # Only events actually deleted leave the list (failed or cancelled ones stay).
        done = {res["eventKey"] for res in self.results if res["status"] == "OK"}
        self.past_rows = [r for r in self.past_rows if r["key"] not in done]
        self.past_selected = [k for k in self.past_selected if k not in done]


class E911State(WebexSession, RunMixin, PasteMixin):
    rows: list[dict[str, str]] = []
    selected: list[str] = []
    search: str = ""
    loading: bool = False
    load_error: str = ""
    confirm_open: bool = False
    csv_note: str = ""
    paste_redsky: str = ""

    @rx.var
    def shown(self) -> list[dict[str, str]]:
        q = self.search.strip().lower()
        return [r for r in self.rows if q in r["name"].lower()] if q else self.rows

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    async def load_page(self):
        await self._refresh_session()
        if self.webex_ok:
            async for ev in self._load():
                yield ev

    @rx.event
    async def reload(self):
        async for ev in self._load():
            yield ev

    async def _load(self):
        self.loading, self.load_error = True, ""
        yield
        log = self._webex_log("List locations with E911 status", "webex-e911-status")
        try:
            client = await self._connect(log)
            if client is None:
                self.load_error = self.webex_message
                return
            try:
                locs = await asyncio.to_thread(L.list_locations, client)
                self.progress = f"Reading RedSky status of {len(locs)} location(s)"
                yield
                self.rows = await asyncio.to_thread(L.e911_status, client, locs)
            except UserError as e:
                self.load_error = str(e)
                log.error(str(e))
                return
            log.info(f"{len(self.rows)} location(s) read")
            ids = {r["id"] for r in self.rows}
            self.selected = [s for s in self.selected if s in ids]
        finally:
            log.close()
            self.loading, self.progress = False, ""

    @rx.event
    def toggle(self, row_id: str, checked: bool):
        if checked and row_id not in self.selected:
            self.selected.append(row_id)
        elif not checked and row_id in self.selected:
            self.selected.remove(row_id)

    @rx.event
    def select_shown(self):
        for r in self.shown:
            if r["id"] not in self.selected:
                self.selected.append(r["id"])

    @rx.event
    def select_none(self):
        self.selected = []

    @rx.event
    async def select_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._select_from_csv(files):
            yield ev

    @rx.event
    async def select_from_text(self):
        async for ev in self._from_paste(self._select_from_csv, "redsky", columns=("Location",), flatten=True,
                                         item_split=r"\t", markers=("location", "name", "locationname")):
            yield ev

    async def _select_from_csv(self, files: list[rx.UploadFile]):
        """Tick the locations whose names are listed in the CSV (first column, header row skipped)."""
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            names = L.parse_location_names_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        by_name = {r["name"].lower(): r["id"] for r in self.rows}
        missing = [n for n in names if n.lower() not in by_name]
        self.selected = list(dict.fromkeys(by_name[n.lower()] for n in names if n.lower() in by_name))
        self.csv_note = (f"{len(self.selected)} of {len(names)} location(s) matched."
                         + (f" Not found: {', '.join(missing)}" if missing else ""))
        yield rx.clear_selected_files("redsky_upload")

    @rx.event
    def export_csv(self):
        if not self.rows:
            return rx.toast.error("Nothing to export.")
        return rx.download(data=L.e911_csv(self.rows),
                           filename=f"locations_e911_status_{datetime.now():%Y-%m-%d_%H-%M-%S}.csv")

    @rx.event
    async def run_opt_out(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        chosen = [r for r in self.rows if r["id"] in self.selected]
        if not chosen:
            yield rx.toast.error("Select at least one location.")
            return
        log = self._webex_log("Opt locations out of RedSky", "webex-redsky-opt-out")
        try:
            log.info(f"{len(chosen)} location(s)")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            items = [(r["name"], lambda rid=r["id"]: L.opt_out_redsky(client, rid)) for r in chosen]
            yield self._start_run(items, "Opting out", log, then="_after_opt_out")
        finally:
            log.close()

    def _after_opt_out(self, log: OpLog):
        return [type(self).reload]


class MigratePstnState(WebexSession, RunMixin, PickerMixin, PasteMixin):
    connection: dict[str, str] = {}
    targets: list[dict[str, str]] = []
    target_label: str = ""
    confirm_open: bool = False
    detail_loading: bool = False
    paste_pstn: str = ""
    bulk_ids: list[str] = []       # locations matched from the pasted names or CSV
    bulk_note: str = ""
    bulk_confirm_open: bool = False
    _cloud: list[dict[str, str]] | None = None  # cloud connections in use org wide, read once per page load

    def _fetch_rows(self, client):
        return L.list_locations(client)

    def _noun(self) -> str:
        return "locations"

    @rx.var
    def target_labels(self) -> list[str]:
        return [t["label"] for t in self.targets]

    @rx.var
    def current_text(self) -> str:
        c = self.connection
        if not c:
            return ""
        text = c.get("name") or c.get("type", "")
        return f"{text} ({c['type']})" if c.get("name") and c.get("type") else text

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    async def reload(self):
        self._cloud = None
        self.bulk_ids, self.bulk_note = [], ""
        async for ev in self._load_rows():
            yield ev

    @rx.event
    def set_target_label(self, value: str):
        self.target_label = value

    @rx.event
    def set_bulk_confirm_open(self, value: bool):
        self.bulk_confirm_open = value

    @rx.event
    async def match_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._match_names(files):
            yield ev

    @rx.event
    async def match_from_text(self):
        async for ev in self._from_paste(self._match_names, "pstn", columns=("Location",), flatten=True,
                                         item_split=r"\t", markers=("location", "name", "locationname")):
            yield ev

    async def _match_names(self, files: list[rx.UploadFile]):
        """Match location names (first column, header row skipped) and load the connections they can move to."""
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            names = L.parse_location_names_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        by_name = {r["name"].lower(): r["id"] for r in self.rows}
        missing = [n for n in names if n.lower() not in by_name]
        self.bulk_ids = list(dict.fromkeys(by_name[n.lower()] for n in names if n.lower() in by_name))
        self.bulk_note = (f"{len(self.bulk_ids)} of {len(names)} location(s) matched."
                          + (f" Not found: {', '.join(missing)}" if missing else ""))
        self.selected_id, self.connection, self.targets, self.target_label = "", {}, [], ""
        yield rx.clear_selected_files("pstn_upload")
        if not self.bulk_ids:
            return
        self.detail_loading = True
        yield
        log = self._webex_log("Read PSTN connection options", "webex-read-pstn")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                if self._cloud is None:
                    self._cloud = await asyncio.to_thread(L.org_cloud_connections, client, self.rows)
                # The options are read for the first matched location; Webex checks each location on the PUT.
                self.targets = await asyncio.to_thread(L.pstn_targets, client, self.bulk_ids[0], self._cloud)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            log.info(f"{len(self.bulk_ids)} location(s) matched, {len(self.targets)} target(s)")
        finally:
            log.close()
            self.detail_loading = False

    @rx.event
    async def run_migrate_bulk(self):
        if not self.bulk_confirm_open or self.busy:
            return
        self.bulk_confirm_open = False
        chosen = [r for r in self.rows if r["id"] in self.bulk_ids]
        target = next((t for t in self.targets if t["label"] == self.target_label), None)
        if not chosen or target is None:
            yield rx.toast.error("Match some locations and select a new PSTN connection.")
            return
        log = self._webex_log("Migrate locations PSTN", "webex-migrate-pstn")
        try:
            log.info(f"{len(chosen)} location(s) -> {target['label']}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            yield self._start_run([(r["name"], lambda r=r: L.set_connection(client, r["id"], target)) for r in chosen],
                                  "Migrating", log)
        finally:
            log.close()

    @rx.event
    async def select_row(self, row_id: str):
        self.selected_id = row_id
        self.connection, self.targets, self.target_label, self.results = {}, [], "", []
        loc = self.selected_row
        if not loc:
            return
        self.detail_loading = True
        yield
        log = self._webex_log("Read location PSTN connection", "webex-read-pstn")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                self.connection = await asyncio.to_thread(L.get_connection, client, loc["id"])
                if self._cloud is None:
                    self._cloud = await asyncio.to_thread(L.org_cloud_connections, client, self.rows)
                self.targets = await asyncio.to_thread(L.pstn_targets, client, loc["id"], self._cloud, self.connection)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            log.info(f"{loc['name']}: {self.current_text}, {len(self.targets)} target(s)")
        finally:
            log.close()
            self.detail_loading = False

    @rx.event
    async def run_migrate(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        loc = self.selected_row
        target = next((t for t in self.targets if t["label"] == self.target_label), None)
        if not loc or target is None:
            yield rx.toast.error("Select a location and a new PSTN connection.")
            return
        log = self._webex_log("Migrate location PSTN", "webex-migrate-pstn")
        try:
            log.info(f"{loc['name']}: {self.current_text} -> {target['label']}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            yield self._start_run([(loc["name"], lambda: L.set_connection(client, loc["id"], target))],
                                  "Migrating", log, then="_after_migrate")
        finally:
            log.close()

    def _after_migrate(self, log: OpLog):
        return [type(self).select_row(self.selected_id)]


class CopyLocationState(WebexSession, RunMixin, PickerMixin):
    form_name: str = ""
    form_address: dict[str, str] = {}
    copy_settings: bool = True
    copy_schedules: bool = True
    confirm_open: bool = False

    def _fetch_rows(self, client):
        return L.list_locations_with_pstn(client)

    def _noun(self) -> str:
        return "locations"

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    def set_form_name(self, value: str):
        self.form_name = value

    @rx.event
    def set_form_address(self, key: str, value: str):
        self.form_address = {**self.form_address, key: value.upper() if key == "country" else value}

    @rx.event
    def set_copy_settings(self, value: bool):
        self.copy_settings = value

    @rx.event
    def set_copy_schedules(self, value: bool):
        self.copy_schedules = value

    @rx.event
    def select_row(self, row_id: str):
        self.selected_id = row_id
        self.results = []

    @rx.event
    async def run_copy(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        source, name = self.selected_row, self.form_name.strip()
        if not source or not name:
            yield rx.toast.error("Select the source location and enter the new name.")
            return
        address = {k: v for k, v in self.form_address.items() if v.strip()}
        log = self._webex_log("Copy location", "webex-copy-location")
        try:
            log.info(f"{source['name']} -> {name}; calling settings: {self.copy_settings}, "
                     f"schedules: {self.copy_schedules}, address overrides: {', '.join(address) or 'none'}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            settings, scheds = self.copy_settings, self.copy_schedules
            yield self._start_run(
                [(name, lambda: L.copy_location(client, source, name, address, settings, scheds))],
                "Copying", log, then="_after_copy")
        finally:
            log.close()

    def _after_copy(self, log: OpLog):
        if any(r["status"] == "OK" for r in self.results):
            self.form_name, self.form_address = "", {}
            return [type(self).reload]
