"""States for Webex > Users (Delete Users, Reset PIN) and Webex > Workspaces (Add Workspace, Add Device, Migrate)."""

import asyncio

import reflex as rx

from ..backend import webex_users as u, webex_voicemail as vm, webex_workspaces as w
from ..backend.errors import UserError
from ..backend.paste import no_at
from ..backend.webex_locations import list_locations
from ..backend.webex_routing import find_location_id
from ..backend.webex_tools import get_supported_devices, model_import_rows
from .run_mixin import PanesMixin, RunMixin
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


class ResetPinState(WebexSession, PanesMixin, RunMixin, PasteMixin):
    email: str = ""
    paste_pin: str = ""

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
        self._focus_pane(True)
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
        async for ev in self._reset_from_csv(files):
            yield ev

    @rx.event
    async def reset_from_text(self):
        async for ev in self._from_paste(self._reset_from_csv, "pin", columns=("email",), flatten=True,
                                         header_if=no_at):
            yield ev

    async def _reset_from_csv(self, files: list[rx.UploadFile]):
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
        self._focus_pane(False)
        log = self._webex_log("Reset user PINs from CSV", "webex-reset-pin-csv")
        try:
            log.info(f"CSV file: {files[0].filename}")
            async for ev in self._reset(emails, log):
                yield ev
            yield rx.clear_selected_files("pin_upload")
        finally:
            log.close()


class WorkspaceCreateMixin(rx.State, mixin=True):
    """Shared by Add Workspace and Copy Workspace: location list, number and name review, the confirm dialog and the run."""
    form_workspace: str = ""
    form_location: str = ""
    form_number: str = ""
    form_extension: str = ""
    location_names: list[str] = []
    paste_workspace: str = ""
    number_open: bool = False
    number_prompt: str = ""
    number_action: str = "Continue"
    _pending_rows: list[dict[str, str]] = []
    _pending_adds: list[dict[str, str]] = []
    _pending_blocked: dict[int, str] = {}
    _pending_title: str = ""
    _pending_slug: str = ""
    _pending_single: bool = False

    @rx.event
    def set_form(self, field: str, value: str):
        setattr(self, f"form_{field}", value)

    @rx.event
    def set_number_open(self, value: bool):
        self.number_open = value

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

    async def _make_action(self, client, cache: dict[str, str], log):
        """The function that creates one workspace from a row, or None (after a toast) when it cannot be prepared."""
        return lambda r: w.create_workspace(client, r, cache)

    async def _create(self, rows: list[dict[str, str]], log, blocked: dict[int, str] | None = None):
        client = await self._connect(log)
        if client is None:
            yield rx.toast.error(self.webex_message)
            return
        cache: dict[str, str] = {}
        blocked = blocked or {}
        action = await self._make_action(client, cache, log)
        if action is None:
            return

        def blocker(msg: str):
            def fail():
                raise w.WebexError(msg)
            return fail

        items = [(r["workspace"], blocker(blocked[i]) if i in blocked
                  else (lambda r=r: action(r))) for i, r in enumerate(rows)]
        async for ev in self._run_items(items, "Creating", log):
            yield ev

    async def _review_numbers(self, rows: list[dict[str, str]]):
        """Check each row's workspace name and phone number. Returns (adds, blocked), or an error message when the check failed.

        adds: numbers not configured anywhere, to add to the location. blocked: row index -> reason, for workspace
        names that already exist and numbers that are in use or belong to a different location (never added anyway)."""
        log = self._webex_log("Check workspaces", "webex-workspace-check")
        try:
            client = await self._connect(log)
            if client is None:
                return self.webex_message
            cache: dict[str, str] = {}

            def review():
                adds: list[dict[str, str]] = []
                blocked: dict[int, str] = {}
                seen: dict[str, str] = {}
                names: set[str] = set()
                for i, r in enumerate(rows):
                    key = r["workspace"].strip().lower()
                    if key in names:
                        blocked[i] = f"Workspace {r['workspace']} is listed more than once"
                        continue
                    names.add(key)
                    if w.workspace_exists(client, r, cache):
                        where = f" in {r['location']}" if r["location"] else ""
                        blocked[i] = f"Workspace {r['workspace']} already exists{where}"
                        log.info(f"{r['workspace']}: already exists")
                        continue
                    status, detail = w.review_row_number(client, r, cache)
                    if status == "missing":
                        key = w.normalize_e164(r["number"])
                        if key not in seen:
                            seen[key] = r["location"]
                            adds.append({"number": key, "location": r["location"]})
                        elif seen[key].lower() != r["location"].lower():
                            blocked[i] = f"{key} is being added to {seen[key]}, not {r['location']}"
                    elif status == "inuse":
                        blocked[i] = f"{w.normalize_e164(r['number'])} is already in use on {detail}"
                    elif status == "other":
                        blocked[i] = f"{w.normalize_e164(r['number'])} is configured in {detail}, not {r['location']}"
                    log.info(f"{r['workspace']}: {status} {detail}".strip())
                return adds, blocked

            try:
                return await asyncio.to_thread(review)
            except UserError as e:
                log.error(f"The workspace check failed: {e}")
                return f"The workspaces could not be checked: {e}"
        finally:
            log.close()

    @staticmethod
    def _shorten(items: list[str], limit: int = 8) -> str:
        more = f" and {len(items) - limit} more" if len(items) > limit else ""
        return ", ".join(items[:limit]) + more

    async def _begin(self, rows: list[dict[str, str]], title: str, slug: str, single: bool = False):
        """Check phone numbers first. Ask the user when numbers need adding or belong to another location."""
        review = await self._review_numbers(rows)
        if isinstance(review, str):
            yield rx.toast.error(review)
            return
        adds, blocked = review
        if adds or blocked:
            self._pending_rows, self._pending_adds, self._pending_blocked = rows, adds, blocked
            self._pending_title, self._pending_slug, self._pending_single = title, slug, single
            parts = []
            if adds:
                parts.append("Not configured in their location yet: "
                             + self._shorten([f"{a['number']} ({a['location']})" for a in adds]) + ". "
                             "Continue to add them to the location first.")
            if blocked:
                parts.append(f"{len(blocked)} workspace(s) will be skipped because the workspace already exists, or its phone "
                             "number is in use or belongs to a different location (nothing is changed or added): "
                             + self._shorten([f"{rows[i]['workspace']}: {msg}" for i, msg in blocked.items()],
                                             4) + ".")
            self.number_prompt = " ".join(parts)
            self.number_action = "Add Phone Numbers And Continue" if adds else "Continue"
            self.number_open = True
            return
        async for ev in self._run_create(rows, title, slug, {}, [], single):
            yield ev

    async def _run_create(self, rows, title: str, slug: str, blocked: dict[int, str], adds: list[dict[str, str]],
                          single: bool):
        log = self._webex_log(title, slug)
        try:
            if adds:
                client = await self._connect(log)
                if client is None:
                    yield rx.toast.error(self.webex_message)
                    return
                cache: dict[str, str] = {}
                blocked = dict(blocked)
                failed: set[str] = set()

                def add_all():
                    for a in adds:
                        try:
                            w.add_location_number(client, a["number"], find_location_id(client, a["location"], cache))
                            log.info(f"Added {a['number']} to {a['location']}")
                        except UserError as e:
                            log.error(f"Adding {a['number']} to {a['location']} failed: {e}")
                            failed.add(a["number"])

                await asyncio.to_thread(add_all)
                for i, r in enumerate(rows):
                    if r["number"] and w.normalize_e164(r["number"]) in failed:
                        blocked.setdefault(i, f"{w.normalize_e164(r['number'])} could not be added to {r['location']}")
            async for ev in self._create(rows, log, blocked):
                yield ev
            if single and self.result_fail_count == 0 and self.results:
                self.form_workspace = ""
                self.form_number = ""
                self.form_extension = ""
            if not single:
                yield rx.clear_selected_files("workspace_upload")
        finally:
            log.close()

    @rx.event
    async def confirm_numbers(self):
        """Dialog confirmed: add the missing numbers, then create the workspaces that are not blocked."""
        self.number_open = False
        async for ev in self._run_create(self._pending_rows, self._pending_title, self._pending_slug,
                                         self._pending_blocked, self._pending_adds, self._pending_single):
            yield ev



class CreateWorkspaceState(WebexSession, PanesMixin, RunMixin, PasteMixin, WorkspaceCreateMixin):
    form_type: str = ""
    form_capacity: str = ""

    @rx.event
    async def create_single(self):
        row = {"workspace": self.form_workspace.strip(), "location": self.form_location.strip(),
               "type": "" if self.form_type == "notSet" else self.form_type, "capacity": self.form_capacity.strip(),
               "number": self.form_number.strip(), "extension": self.form_extension.strip()}
        if not row["workspace"]:
            yield rx.toast.error("Enter the workspace name.")
            return
        if row["location"] and self.location_names and row["location"].lower() not in {n.lower() for n in self.location_names}:
            yield rx.toast.error("Pick the location from the list, or clear it.")
            return
        self._focus_pane(True)
        async for ev in self._begin([row], "Add workspace", "webex-add-workspace", single=True):
            yield ev

    @rx.event
    async def create_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._create_from_csv(files):
            yield ev

    @rx.event
    async def create_from_text(self):
        async for ev in self._from_paste(self._create_from_csv, "workspace", columns=w.WORKSPACE_COLUMNS,
                                         markers=("workspace",)):
            yield ev

    async def _create_from_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = w.parse_workspace_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        self._focus_pane(False)
        async for ev in self._begin(rows, "Add workspaces from CSV", "webex-add-workspaces-csv"):
            yield ev


class CopyWorkspaceState(WebexSession, RunMixin, PasteMixin, WorkspaceCreateMixin):
    form_source: str = ""
    form_source_location: str = ""
    paste_copy: str = ""
    workspace_names: list[str] = []

    @rx.event
    async def load_page(self):
        """Page load: check the login, then list the locations and the workspaces for the search lists."""
        await self._refresh_session()
        if not self.webex_ok:
            return
        log = self._webex_log("List locations and workspaces", "webex-list-workspaces")
        try:
            client = await self._connect(log)
            if client is None:
                return
            try:
                rows = await asyncio.to_thread(list_locations, client)
                names = await asyncio.to_thread(w.list_workspace_names, client)
            except UserError as e:
                log.error(str(e))
                return
            self.location_names = [r["name"] for r in rows]
            self.workspace_names = names
            log.info(f"{len(rows)} location(s), {len(names)} workspace(s)")
        finally:
            log.close()

    @rx.event
    async def copy_single(self):
        row = {"workspace": self.form_workspace.strip(), "location": self.form_location.strip(), "type": "",
               "capacity": "", "number": self.form_number.strip(), "extension": self.form_extension.strip()}
        if not row["workspace"]:
            yield rx.toast.error("Enter the name of the new workspace.")
            return
        async for ev in self._copy([row], "Copy workspace", "webex-copy-workspace", single=True):
            yield ev

    @rx.event
    async def copy_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._copy_from_csv(files):
            yield ev

    @rx.event
    async def copy_from_text(self):
        async for ev in self._from_paste(self._copy_from_csv, "copy", columns=w.COPY_COLUMNS,
                                         markers=("workspace",)):
            yield ev

    async def _copy_from_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = w.parse_workspace_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        async for ev in self._copy(rows, "Copy workspaces from CSV", "webex-copy-workspaces-csv"):
            yield ev

    async def _copy(self, rows: list[dict[str, str]], title: str, slug: str, single: bool = False):
        if not self.form_source.strip():
            yield rx.toast.error("Enter the name of the workspace to copy.")
            return
        for r in rows:
            if r["location"] and self.location_names and r["location"].lower() not in {n.lower() for n in self.location_names}:
                yield rx.toast.error(f"Location {r['location']} is not in the list. Pick one from the list, or clear it.")
                return
        async for ev in self._begin(rows, title, slug, single=single):
            yield ev

    async def _make_action(self, client, cache: dict[str, str], log):
        name, location = self.form_source.strip(), self.form_source_location.strip()
        try:
            source = await asyncio.to_thread(w.get_workspace, client, name, location, cache)
        except UserError as e:
            log.error(f"Source workspace {name}: {e}")
            self.results = [{"key": name, "status": "Failed", "detail": str(e)}]
            return None
        settings, unread = await asyncio.to_thread(w.read_calling_settings, client, source)
        log.info(f"Copying from {name}: {len(settings)} calling setting(s) read"
                 + (f", {len(unread)} could not be read ({', '.join(unread)})" if unread else ""))
        return lambda r: w.copy_workspace(client, source, r, cache, settings, unread)


class AddWorkspaceState(WebexSession, PanesMixin, RunMixin, PasteMixin):
    form_workspace: str = ""
    form_model: str = ""
    form_mac: str = ""
    form_location: str = ""
    location_names: list[str] = []
    model_rows: list[dict[str, str]] = []
    workspace_names: list[str] = []
    workspace_locations: dict[str, str] = {}
    paste_device: str = ""

    @rx.event
    def set_form(self, field: str, value: str):
        setattr(self, f"form_{field}", value)
        if field == "workspace":
            location = self.workspace_locations.get(value.strip())
            if location:
                self.form_location = location

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
            try:
                self.workspace_locations = await asyncio.to_thread(w.workspace_location_map, client, rows)
                self.workspace_names = sorted(self.workspace_locations, key=str.lower)
                log.info(f"{len(self.workspace_names)} workspace(s)")
            except UserError as e:
                log.warning(f"Workspaces not loaded: {e}")
            try:
                devices = await asyncio.to_thread(get_supported_devices, client)
                self.model_rows = model_import_rows(devices)
                log.info(f"{len(self.model_rows)} supported model(s)")
            except UserError as e:
                log.warning(f"Supported models not loaded: {e}")
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
        if row["location"] and self.location_names and row["location"].lower() not in {n.lower() for n in self.location_names}:
            yield rx.toast.error("Pick the location from the list, or clear it.")
            return
        self._focus_pane(True)
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
        self._focus_pane(False)
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


class VoicemailState(WebexSession, PanesMixin, RunMixin):
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
        self._focus_pane(True)
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
        self._focus_pane(False)
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
                yield rx.toast.error("No users were found in that location.")
                return
            self.report_title = name
            async for ev in self._report(client, people, log):
                yield ev
        finally:
            log.close()
