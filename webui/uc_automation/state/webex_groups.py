"""States for Webex > Call Routing: Call Queues, Hunt Groups, Virtual Lines."""

import asyncio
import json
import re
from datetime import datetime

import reflex as rx

from ..backend import webex_groups as g, webex_virtual_lines as vl
from ..backend.applog import OpLog
from ..backend.errors import UserError
from ..backend.paste import no_at_or_digit
from ..backend.paths import LOG_DIR
from .run_mixin import RunMixin
from .webex_routing import PasteMixin, WebexSession, _one

DISPLAY_LIMIT = 100


class PickerMixin(rx.State, mixin=True):
    """A searchable list of Webex objects (queues, hunt groups, virtual lines) with one selected row."""

    rows: list[dict[str, str]] = []
    search: str = ""
    selected_id: str = ""
    loading: bool = False
    list_error: str = ""

    def _fetch_rows(self, client) -> list[dict[str, str]]:
        raise NotImplementedError

    def _noun(self) -> str:
        raise NotImplementedError

    @rx.var
    def shown_rows(self) -> list[dict[str, str]]:
        q = self.search.strip().lower()
        rows = [r for r in self.rows if any(q in v.lower() for v in r.values())] if q else self.rows
        return rows[:DISPLAY_LIMIT]

    @rx.var
    def match_count(self) -> int:
        q = self.search.strip().lower()
        return len(self.rows) if not q else sum(1 for r in self.rows if any(q in v.lower() for v in r.values()))

    @rx.var
    def selected_row(self) -> dict[str, str]:
        return next((r for r in self.rows if r["id"] == self.selected_id), {})

    @rx.var
    def has_selection(self) -> bool:
        return bool(self.selected_row)

    @rx.var
    def selected_label(self) -> str:
        r = self.selected_row
        return f"{r['name']} ({r['location']})" if r else ""

    @rx.event
    def set_search(self, value: str):
        self.search = value

    @rx.event
    def select_row(self, row_id: str):
        self.selected_id = row_id

    async def _load_rows(self):
        self.loading = True
        self.list_error = ""
        yield
        log = self._webex_log(f"List {self._noun()}", f"webex-list-{self._noun().replace(' ', '-')}")
        try:
            client = await self._connect(log)
            if client is None:
                self.list_error = self.webex_message
            else:
                try:
                    self.rows = await asyncio.to_thread(self._fetch_rows, client)
                    log.info(f"{len(self.rows)} {self._noun()} found")
                    if self.selected_id not in {r["id"] for r in self.rows}:
                        self.selected_id = ""
                except UserError as e:
                    self.list_error = str(e)
                    log.error(str(e))
        finally:
            log.close()
            self.loading = False

    @rx.event
    async def load_page(self):
        """Page load: check the login, then list the objects."""
        await self._refresh_session()
        if self.webex_ok:
            async for ev in self._load_rows():
                yield ev

    @rx.event
    async def reload(self):
        async for ev in self._load_rows():
            yield ev


class _GroupsBase(PasteMixin, mixin=True):
    """Create-from-CSV and replace-agents, shared by the queue and hunt group states (methods only, no vars)."""

    paste_create: str = ""
    paste_agents: str = ""
    agent_mode: str = "replace"

    @rx.event
    def set_agent_mode(self, value: str | list[str]):
        self.agent_mode = value if isinstance(value, str) else value[0]

    def _kind(self) -> str:
        """"queue" or "hunt"."""
        raise NotImplementedError

    async def _create_from_text(self, upload_id: str):
        async for ev in self._from_paste(lambda f: self._create_from_csv(f, upload_id), "create",
                                         columns=g.CREATE_COLUMNS, markers=("name", "location"),
                                         extra_prefix="agent"):
            yield ev

    async def _agents_from_text(self, upload_id: str):
        async for ev in self._from_paste(lambda f: self._update_agents(f, upload_id), "agents",
                                         columns=("agent",), flatten=True, header_if=no_at_or_digit):
            yield ev

    async def _create_from_csv(self, files: list[rx.UploadFile], upload_id: str):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = g.parse_group_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        noun = "call queue" if self._kind() == "queue" else "hunt group"
        log = self._webex_log(f"Create {noun}s from CSV", f"webex-create-{self._kind()}")
        try:
            log.info(f"CSV file: {files[0].filename}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            cache: dict[str, str] = {}
            items = [(r["name"] or "(no name)", lambda r=r: g.create_group(client, self._kind(), r, cache))
                     for r in rows]
            async for ev in self._run_items(items, "Creating", log):
                yield ev
            yield rx.clear_selected_files(upload_id)
        finally:
            log.close()

    async def _update_agents(self, files: list[rx.UploadFile], upload_id: str):
        group = self.selected_row
        if not group:
            yield rx.toast.error("Select one from the list first.")
            return
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            entries = g.parse_agent_list_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not entries:
            yield rx.toast.error("The CSV has no agents.")
            return
        log = self._webex_log(f"Update {self._kind()} agents", f"webex-update-{self._kind()}-agents")
        try:
            log.info(f"{group['name']} ({group['location']}), CSV file: {files[0].filename}, {len(entries)} entries")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            items = [(group["name"], lambda: g.replace_agents(client, self._kind(), group, entries,
                                                                  add=self.agent_mode == "add"))]
            async for ev in self._run_items(items, "Updating agents", log):
                yield ev
            yield rx.clear_selected_files(upload_id)
        finally:
            log.close()


class CallQueuesState(WebexSession, RunMixin, PickerMixin, _GroupsBase):
    mode: str = "create"
    plan_lines: list[str] = []
    plan_notes: list[str] = []
    plan_for: str = ""
    confirm_open: bool = False
    _plan_q: dict = {}

    def _kind(self) -> str:
        return "queue"

    def _fetch_rows(self, client):
        return g.list_queues(client)

    def _noun(self) -> str:
        return "call queues"

    @rx.event
    def set_mode(self, value: str | list[str]):
        self.mode = _one(value)
        self.results = []

    @rx.event
    def select_row(self, row_id: str):
        self.selected_id = row_id
        self.plan_for = ""
        self.plan_lines, self.plan_notes = [], []

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    async def review_migration(self):
        """Read the selected call queue and show what the migration will do."""
        group = self.selected_row
        if not group:
            yield rx.toast.error("Select a call queue first.")
            return
        self.busy = True
        yield
        log = self._webex_log("Review call queue migration", "webex-migrate-queue-review")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                q = await asyncio.to_thread(g.read_queue, client, group)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            agents = q.get("agents") or []
            body = g.hunt_group_body_from_queue(q)
            self._plan_q = q
            self.plan_for = group["id"]
            self.plan_lines = [
                f"Location: {group['location']}",
                f"Number: {q.get('phoneNumber', '')}   Extension: {q.get('extension', '')}",
                f"Policy: {body['callPolicies']['policy']}",
                f"Agents ({len(agents)}): "
                + ", ".join(f"{a.get('firstName', '')} {a.get('lastName', '')}".strip() for a in agents),
            ]
            self.plan_notes = g.queue_unmapped_notes(q)
            log.info(f"Reviewed {q['name']}: {len(agents)} agent(s), {len(self.plan_notes)} unmapped setting(s)")
            for n in self.plan_notes:
                log.warning(f"Not migrated: {n}")
        finally:
            log.close()
            self.busy = False

    @rx.event
    async def run_migration(self):
        self.confirm_open = False
        group, q = self.selected_row, self._plan_q
        if not group or not q or self.plan_for != group["id"]:
            yield rx.toast.error("Review the call queue first.")
            return
        log = self._webex_log("Migrate call queue to hunt group", "webex-migrate-queue")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", q["name"])
            backup = LOG_DIR / f"{datetime.now():%Y-%m-%d_%H-%M-%S}-call_queue_backup-{safe}.json"
            backup_json = json.dumps(g.backup_document(group, q), indent=2)
            backup.write_text(backup_json, encoding="utf-8")
            log.info(f"Call queue settings saved to {backup}")
            yield rx.download(data=backup_json, filename=backup.name)
            items = [(group["name"], lambda: g.migrate_queue(client, group, q, str(backup), log.info))]
            async for ev in self._run_items(items, "Migrating", log):
                yield ev
            if self.result_fail_count == 0:
                self.plan_for = ""
                self.plan_lines, self.plan_notes = [], []
                self._plan_q = {}
                self.selected_id = ""
                async for ev in self._load_rows():
                    yield ev
        finally:
            log.close()

    @rx.event
    async def restore_from_json(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a JSON backup first.")
            return
        try:
            doc = json.loads((await files[0].read()).decode("utf-8-sig"))
        except ValueError:
            yield rx.toast.error("That file is not valid JSON.")
            return
        log = self._webex_log("Restore call queue from JSON", "webex-restore-queue")
        try:
            log.info(f"JSON file: {files[0].filename}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            name = doc.get("name", "(no name)") if isinstance(doc, dict) else "(invalid)"
            items = [(name, lambda: g.restore_queue(client, doc, {}))]
            async for ev in self._run_items(items, "Restoring", log):
                yield ev
            yield rx.clear_selected_files("queue_restore_upload")
        finally:
            log.close()

    @rx.event
    async def create_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._create_from_csv(files, "queue_create_upload"):
            yield ev

    @rx.event
    async def update_agents(self, files: list[rx.UploadFile]):
        async for ev in self._update_agents(files, "queue_agents_upload"):
            yield ev

    @rx.event
    async def create_from_text(self):
        async for ev in self._create_from_text("queue_create_upload"):
            yield ev

    @rx.event
    async def update_agents_text(self):
        async for ev in self._agents_from_text("queue_agents_upload"):
            yield ev


class HuntGroupsState(WebexSession, RunMixin, PickerMixin, _GroupsBase):
    mode: str = "create"
    plan_lines: list[str] = []
    plan_notes: list[str] = []
    plan_for: str = ""
    confirm_open: bool = False
    _plan_hg: dict = {}
    last_backup: str = ""

    def _kind(self) -> str:
        return "hunt"

    def _fetch_rows(self, client):
        return g.list_hunt_groups(client)

    def _noun(self) -> str:
        return "hunt groups"

    @rx.event
    def set_mode(self, value: str | list[str]):
        self.mode = _one(value)
        self.results = []

    @rx.event
    def select_row(self, row_id: str):
        self.selected_id = row_id
        self.plan_for = ""
        self.plan_lines, self.plan_notes = [], []

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    async def create_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._create_from_csv(files, "hunt_create_upload"):
            yield ev

    @rx.event
    async def update_agents(self, files: list[rx.UploadFile]):
        async for ev in self._update_agents(files, "hunt_agents_upload"):
            yield ev

    @rx.event
    async def restore_from_json(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a JSON backup first.")
            return
        try:
            doc = json.loads((await files[0].read()).decode("utf-8-sig"))
        except ValueError:
            yield rx.toast.error("That file is not valid JSON.")
            return
        log = self._webex_log("Restore hunt group from JSON", "webex-restore-huntgroup")
        try:
            log.info(f"JSON file: {files[0].filename}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            name = doc.get("name", "(no name)") if isinstance(doc, dict) else "(invalid)"
            items = [(name, lambda: g.restore_hunt_group(client, doc, {}))]
            async for ev in self._run_items(items, "Restoring", log):
                yield ev
            yield rx.clear_selected_files("hunt_restore_upload")
        finally:
            log.close()

    @rx.event
    async def create_from_text(self):
        async for ev in self._create_from_text("hunt_create_upload"):
            yield ev

    @rx.event
    async def update_agents_text(self):
        async for ev in self._agents_from_text("hunt_agents_upload"):
            yield ev

    @rx.event
    async def review_migration(self):
        """Read the selected hunt group and show what the migration will do."""
        group = self.selected_row
        if not group:
            yield rx.toast.error("Select a hunt group first.")
            return
        self.busy = True
        yield
        log = self._webex_log("Review hunt group migration", "webex-migrate-review")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                hg = await asyncio.to_thread(g.read_hunt_group, client, group)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            agents = hg.get("agents") or []
            body = g.queue_body_from_hunt_group(hg)
            self._plan_hg = hg
            self.plan_for = group["id"]
            self.plan_lines = [
                f"Location: {group['location']}",
                f"Number: {hg.get('phoneNumber', '')}   Extension: {hg.get('extension', '')}",
                f"Policy: {body['callPolicies']['policy']}",
                f"Agents ({len(agents)}, all will be joined): "
                + ", ".join(f"{a.get('firstName', '')} {a.get('lastName', '')}".strip() for a in agents),
            ]
            self.plan_notes = g.unmapped_notes(hg)
            log.info(f"Reviewed {hg['name']}: {len(agents)} agent(s), {len(self.plan_notes)} unmapped setting(s)")
            for n in self.plan_notes:
                log.warning(f"Not migrated: {n}")
        finally:
            log.close()
            self.busy = False

    @rx.event
    async def run_migration(self):
        self.confirm_open = False
        group, hg = self.selected_row, self._plan_hg
        if not group or not hg or self.plan_for != group["id"]:
            yield rx.toast.error("Review the hunt group first.")
            return
        log = self._webex_log("Migrate hunt group to call queue", "webex-migrate-huntgroup")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", hg["name"])
            backup = LOG_DIR / f"{datetime.now():%Y-%m-%d_%H-%M-%S}-hunt_group_backup-{safe}.json"
            backup_json = json.dumps(g.backup_document(group, hg), indent=2)
            backup.write_text(backup_json, encoding="utf-8")
            log.info(f"Hunt group settings saved to {backup}")
            self.last_backup = str(backup)
            yield rx.download(data=backup_json, filename=backup.name)
            items = [(group["name"], lambda: g.migrate_hunt_group(client, group, hg, str(backup), log.info))]
            async for ev in self._run_items(items, "Migrating", log):
                yield ev
            if self.result_fail_count == 0:
                self.plan_for = ""
                self.plan_lines, self.plan_notes = [], []
                self._plan_hg = {}
                self.selected_id = ""
                async for ev in self._load_rows():
                    yield ev
        finally:
            log.close()


class VirtualLinesState(WebexSession, RunMixin, PickerMixin):
    def _fetch_rows(self, client):
        return g.list_virtual_lines(client)

    def _noun(self) -> str:
        return "virtual lines"

    @rx.event
    async def upload_greeting(self, files: list[rx.UploadFile]):
        line = self.selected_row
        if not line:
            yield rx.toast.error("Select a virtual line first.")
            return
        if not files:
            yield rx.toast.error("Choose a .wav file first.")
            return
        name = files[0].filename or "greeting.wav"
        data = await files[0].read()
        try:
            vl.check_greeting(name, data)
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        log = self._webex_log("Upload virtual line greeting", "webex-virtual-line-greeting")
        try:
            log.info(f"{line['name']} ({line['location']}), file {name}, {len(data)} bytes")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            items = [(line["name"], lambda: vl.upload_greetings(client, line, name, data, log.info))]
            async for ev in self._run_items(items, "Uploading", log):
                yield ev
            yield rx.clear_selected_files("greeting_upload")
        finally:
            log.close()
