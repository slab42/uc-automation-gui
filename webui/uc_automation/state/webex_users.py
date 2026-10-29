"""States for Webex > Users (Delete Users, Reset PIN) and Webex > Workspaces (Add Workspace, Migrate)."""

import asyncio

import reflex as rx

from ..backend import webex_users as u, webex_voicemail as vm, webex_workspaces as w
from ..backend.errors import UserError
from ..backend.paste import no_at
from ..backend.webex_locations import list_locations
from ..backend.webex_routing import find_location_id
from .run_mixin import RunMixin
from .webex_groups import PickerMixin
from .webex_routing import PasteMixin, WebexSession

PREVIEW_LIMIT = 300


class DeleteUsersState(WebexSession, RunMixin, PasteMixin):
    emails: list[str] = []
    file_name: str = ""
    confirm_open: bool = False
    paste_delete: str = ""

    @rx.var
    def preview(self) -> list[str]:
        return self.emails[:PREVIEW_LIMIT]

    @rx.var
    def preview_hidden(self) -> int:
        return max(0, len(self.emails) - PREVIEW_LIMIT)

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    async def load_csv(self, files: list[rx.UploadFile]):
        async for ev in self._load_csv(files):
            yield ev

    @rx.event
    async def load_text(self):
        async for ev in self._from_paste(self._load_csv, "delete", columns=("email",), flatten=True,
                                         header_if=no_at):
            yield ev

    async def _load_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            self.emails = u.parse_email_csv(await files[0].read(), fallback_column=3)
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        self.file_name = files[0].filename or ""
        self.results = []
        yield rx.clear_selected_files("delete_upload")
        if not self.emails:
            yield rx.toast.error("No email addresses were found in the CSV.")

    @rx.event
    def clear_list(self):
        self.emails, self.file_name = [], ""

    @rx.event
    async def run_delete(self):
        self.confirm_open = False
        emails = list(self.emails)
        if not emails:
            return
        log = self._webex_log("Delete users", "webex-delete-users")
        try:
            log.info(f"CSV file: {self.file_name}, {len(emails)} user(s)")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            items = [(e, lambda e=e: u.delete_user(client, e)) for e in emails]
            async for ev in self._run_items(items, "Deleting", log):
                yield ev
            self.emails, self.file_name = [], ""
        finally:
            log.close()


class ResetPinState(WebexSession, RunMixin):
    email: str = ""

    @rx.event
    def set_email(self, value: str):
        self.email = value.strip()

    async def _reset(self, emails: list[str], log):
        client = await self._connect(log)
        if client is None:
            yield rx.toast.error(self.webex_message)
            return
        items = [(e, lambda e=e: u.reset_pin(client, e)) for e in emails]
        async for ev in self._run_items(items, "Resetting", log):
            yield ev

    @rx.event
    async def reset_single(self):
        if not self.email:
            yield rx.toast.error("Enter the user's email address.")
            return
        log = self._webex_log("Reset user PIN", "webex-reset-pin")
        try:
            async for ev in self._reset([self.email], log):
                yield ev
            if self.result_fail_count == 0 and self.results:
                self.email = ""
        finally:
            log.close()

    @rx.event
    async def reset_from_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            emails = u.parse_email_csv(await files[0].read(), fallback_column=0)
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not emails:
            yield rx.toast.error("No email addresses were found in the CSV.")
            return
        log = self._webex_log("Reset user PINs from CSV", "webex-reset-pin-csv")
        try:
            log.info(f"CSV file: {files[0].filename}")
            async for ev in self._reset(emails, log):
                yield ev
            yield rx.clear_selected_files("pin_upload")
        finally:
            log.close()


class AddWorkspaceState(WebexSession, RunMixin, PasteMixin):
    form_workspace: str = ""
    form_model: str = ""
    form_mac: str = ""
    form_location: str = ""
    location_names: list[str] = []
    paste_device: str = ""

    @rx.event
    def set_form(self, field: str, value: str):
        setattr(self, f"form_{field}", value)

    @rx.event
    async def load_page(self):
        """Page load: check the login, then list the locations for the dropdown."""
        await self._refresh_session()
        if not self.webex_ok:
            return
        log = self._webex_log("List locations", "webex-list-locations")
        try:
            client = await self._connect(log)
            if client is None:
                return
            try:
                rows = await asyncio.to_thread(list_locations, client)
            except UserError as e:
                log.error(str(e))
                return
            self.location_names = [r["name"] for r in rows]
            log.info(f"{len(rows)} location(s)")
        finally:
            log.close()

    async def _add(self, rows: list[dict[str, str]], log):
        client = await self._connect(log)
        if client is None:
            yield rx.toast.error(self.webex_message)
            return
        cache: dict[str, str] = {}
        items = [(f"{r['workspace']} / {r['mac']}", lambda r=r: w.add_device(client, r, cache)) for r in rows]
        async for ev in self._run_items(items, "Adding", log):
            yield ev

    @rx.event
    async def add_single(self):
        row = {"workspace": self.form_workspace.strip(), "model": self.form_model.strip(),
               "mac": self.form_mac.strip(), "location": self.form_location.strip()}
        if not (row["workspace"] and row["model"] and row["mac"]):
            yield rx.toast.error("Enter the workspace, the model and the MAC address.")
            return
        if row["location"] and self.location_names and row["location"] not in self.location_names:
            yield rx.toast.error("Pick the location from the list, or clear it.")
            return
        log = self._webex_log("Add device to workspace", "webex-add-device")
        try:
            async for ev in self._add([row], log):
                yield ev
            if self.result_fail_count == 0 and self.results:
                self.form_mac = ""
        finally:
            log.close()

    @rx.event
    async def add_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._add_from_csv(files):
            yield ev

    @rx.event
    async def add_from_text(self):
        async for ev in self._from_paste(self._add_from_csv, "device", columns=w.DEVICE_COLUMNS,
                                         markers=("workspace", "mac")):
            yield ev

    async def _add_from_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = w.parse_device_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        log = self._webex_log("Add devices to workspaces from CSV", "webex-add-devices-csv")
        try:
            log.info(f"CSV file: {files[0].filename}")
            async for ev in self._add(rows, log):
                yield ev
            yield rx.clear_selected_files("device_upload")
        finally:
            log.close()


class MigrateState(WebexSession, RunMixin, PickerMixin):
    numbers_text: str = ""
    plan_rows: list[dict[str, str]] = []
    plan_location: str = ""
    confirm_open: bool = False
    _plan_moves: list[dict] = []

    def _fetch_rows(self, client):
        return list_locations(client)

    def _noun(self) -> str:
        return "locations"

    @rx.var
    def move_count(self) -> int:
        return sum(1 for r in self.plan_rows if r["action"] == "move")

    @rx.event
    def set_numbers_text(self, value: str):
        self.numbers_text = value

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    def select_row(self, row_id: str):
        self.selected_id = row_id
        self.plan_rows, self._plan_moves = [], []

    @rx.event
    async def review(self, files: list[rx.UploadFile]):
        location = self.selected_row
        if not location:
            yield rx.toast.error("Select the new location first.")
            return
        try:
            numbers = (w.parse_numbers_csv(await files[0].read()) if files
                       else w.parse_numbers_text(self.numbers_text))
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not numbers:
            yield rx.toast.error("Enter at least one phone number, or choose a CSV.")
            return
        self.busy = True
        self.results = []
        self.progress = f"Looking up {len(numbers)} number(s)"
        yield
        log = self._webex_log("Review user migration", "webex-migrate-review")
        try:
            log.info(f"New location: {location['name']}, {len(numbers)} number(s)")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                rows = await asyncio.to_thread(w.review_numbers, client, numbers, location["id"])
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            for r in rows:
                (log.info if r["action"] == "move" else log.warning)(
                    f"{r['number']} {r['owner']}: {r['action']} {r['reason']}".strip())
            self.plan_rows = [{**r, "status": "Will move" if r["action"] == "move" else "Skipped"} for r in rows]
            self._plan_moves = [r for r in rows if r["action"] == "move"]
            self.plan_location = location["id"]
            if numbers and files:
                yield rx.clear_selected_files("migrate_upload")
        finally:
            log.close()
            self.busy = False
            self.progress = ""

    @rx.event
    async def run_migration(self):
        self.confirm_open = False
        location, moves = self.selected_row, list(self._plan_moves)
        if not location or not moves or self.plan_location != location["id"]:
            yield rx.toast.error("Review the numbers first.")
            return
        log = self._webex_log("Migrate users to location", "webex-migrate-users")
        try:
            log.info(f"New location: {location['name']}, {len(moves)} user(s)")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            items = [(f"{m['number']} {m['owner']}",
                      lambda m=m: w.move_user(client, m["ownerId"], location["id"], log.info)) for m in moves]
            async for ev in self._run_items(items, "Moving", log):
                yield ev
            self.plan_rows, self._plan_moves = [], []
        finally:
            log.close()


class VoicemailState(WebexSession, RunMixin):
    form_email: str = ""
    form_location: str = ""
    location_names: list[str] = []
    rows: list[dict[str, str]] = []
    report_title: str = ""

    @rx.event
    def set_form_email(self, value: str):
        self.form_email = value.strip()

    @rx.event
    def set_form_location(self, value: str):
        self.form_location = value

    @rx.var
    def internal_count(self) -> int:
        return sum(1 for r in self.rows if r["storage"] == "Internal")

    @rx.var
    def external_count(self) -> int:
        return sum(1 for r in self.rows if r["storage"] == "External")

    @rx.event
    async def load_page(self):
        """Page load: check the login, then list the locations for the dropdown."""
        await self._refresh_session()
        if not self.webex_ok:
            return
        log = self._webex_log("List locations", "webex-list-locations")
        try:
            client = await self._connect(log)
            if client is None:
                return
            try:
                rows = await asyncio.to_thread(list_locations, client)
            except UserError as e:
                log.error(str(e))
                return
            self.location_names = [r["name"] for r in rows]
            log.info(f"{len(rows)} location(s)")
        finally:
            log.close()

    async def _report(self, client, people: list[dict[str, str]], log):
        self.busy = True
        self.rows = []
        for i, p in enumerate(people, 1):
            self.progress = f"Reading voicemail {i} of {len(people)}"
            yield
            row = {"name": p["name"], "email": p["email"], "enabled": "", "storage": "", "details": ""}
            try:
                info = await asyncio.to_thread(vm.voicemail_info, client, p["id"])
                log.info(f"{p['email']}: raw settings {info.pop('raw')}")
                row.update(info)
                log.info(f"{p['email']}: {row['storage']} - {row['details']}")
            except UserError as e:
                row["details"] = str(e)
                log.error(f"{p['email']}: {e}")
            self.rows.append(row)
        log.info(f"Report finished: {self.internal_count} internal, {self.external_count} external")
        self.progress = ""
        self.busy = False

    @rx.event
    async def report_user(self):
        if not self.form_email:
            yield rx.toast.error("Enter the user's email address.")
            return
        log = self._webex_log("Voicemail report (user)", "webex-voicemail-user")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                person = await asyncio.to_thread(vm.find_person, client, self.form_email)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            self.report_title = person["email"]
            async for ev in self._report(client, [person], log):
                yield ev
        finally:
            log.close()

    @rx.event
    async def report_location(self):
        name = self.form_location.strip()
        if not name:
            yield rx.toast.error("Choose a location.")
            return
        log = self._webex_log("Voicemail report (location)", "webex-voicemail-location")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                location_id = await asyncio.to_thread(find_location_id, client, name, {})
                people = await asyncio.to_thread(vm.list_location_people, client, location_id)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            log.info(f"Location {name}: {len(people)} user(s)")
            if not people:
                yield rx.toast.error("No Calling users were found in that location.")
                return
            self.report_title = name
            async for ev in self._report(client, people, log):
                yield ev
        finally:
            log.close()
