"""State for Webex > Devices > Bulk ATA/VG."""

import asyncio

import reflex as rx

from ..backend import cucm_connections, webex_cucm_migrate as cm, webex_devices as d, webex_workspaces as w
from ..backend.applog import OpLog
from ..backend.errors import UserError
from ..backend.webex_api import WebexClient
from ..backend.webex_locations import list_locations
from ..backend.webex_tools import get_supported_devices, model_import_rows
from .run_mixin import PanesMixin, RunMixin
from .webex_routing import PasteMixin, WebexSession


class BulkAtaState(WebexSession, RunMixin, PasteMixin):
    form_location: str = ""
    form_model: str = ""
    form_mac: str = ""
    form_ports: str = ""
    location_names: list[str] = []
    model_rows: list[dict[str, str]] = []
    paste_ata: str = ""

    @rx.event
    def set_form(self, field: str, value: str):
        setattr(self, f"form_{field}", value)

    @rx.event
    async def load_page(self):
        """Page load: check the login, then list the locations and supported models for the dropdowns."""
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
                devices = await asyncio.to_thread(get_supported_devices, client)
                self.model_rows = model_import_rows(devices)
                log.info(f"{len(self.model_rows)} supported model(s)")
            except UserError as e:
                log.warning(f"Supported models not loaded: {e}")
        finally:
            log.close()

    async def _add(self, devices: list[dict], log):
        client = await self._connect(log)
        if client is None:
            yield rx.toast.error(self.webex_message)
            return
        cache: dict[str, str] = {}
        items = [(d["mac"], lambda d=d: w.add_ata(client, d, cache)) for d in devices]
        async for ev in self._run_items(items, "Adding", log):
            yield ev

    @rx.event
    async def add_single(self):
        location = self.form_location.strip()
        rows = w.port_rows_from_text(self.form_ports, self.form_mac.strip(), self.form_model.strip(), location)
        if not (location and self.form_model.strip() and self.form_mac.strip() and rows):
            yield rx.toast.error("Enter the location, the model, the MAC address and at least one port.")
            return
        if self.location_names and location.lower() not in {n.lower() for n in self.location_names}:
            yield rx.toast.error("Pick the location from the list.")
            return
        log = self._webex_log("Add ATA/VG", "webex-add-ata")
        try:
            async for ev in self._add(w.group_ata_rows(rows), log):
                yield ev
            if self.result_fail_count == 0 and self.results:
                self.form_mac = ""
                self.form_ports = ""
        finally:
            log.close()

    @rx.event
    async def add_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._add_from_csv(files):
            yield ev

    @rx.event
    async def add_from_text(self):
        async for ev in self._from_paste(self._add_from_csv, "ata", columns=w.ATA_COLUMNS,
                                         markers=("mac", "workspace")):
            yield ev

    async def _add_from_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = w.parse_ata_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        log = self._webex_log("Add ATA/VG from CSV", "webex-add-ata-csv")
        try:
            log.info(f"CSV file: {files[0].filename}")
            async for ev in self._add(w.group_ata_rows(rows), log):
                yield ev
            yield rx.clear_selected_files("ata_upload")
        finally:
            log.close()


class DeviceMigrateState(WebexSession, PanesMixin, RunMixin, PasteMixin):
    """Two sides, left and right, each with an org, a user and a MAC (kept in the browser). The arrows move the
    phone of the source side's MAC to the user on the other side."""

    org_l: str = rx.LocalStorage("")
    user_l: str = rx.LocalStorage("")
    mac_l: str = rx.LocalStorage("")
    org_r: str = rx.LocalStorage("")
    user_r: str = rx.LocalStorage("")
    mac_r: str = rx.LocalStorage("")
    bulk_dir: str = rx.LocalStorage("Left To Right")
    paste_phone: str = rx.LocalStorage("")
    confirm_open: bool = False
    confirm_text: str = ""
    _pending: list[dict[str, str]] = []
    _pending_orgs: tuple[str, str] = ("", "")
    _pending_side: str = ""  # "l" or "r": the side the single phone is moving to, "" for a bulk run
    _csv_name: str = ""

    @rx.var
    def all_org_names(self) -> list[str]:
        """Every saved Webex org (a phone can move between orgs of different customers)."""
        return [o["name"] for o in self.webex_orgs]

    @rx.event
    def set_side(self, field: str, value: str):
        setattr(self, field, value)

    @rx.event
    def set_bulk_dir(self, value: str | list[str]):
        self.bulk_dir = value if isinstance(value, str) else value[0]

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    async def load_page(self):
        await self._refresh_session()

    def _stage(self, rows: list[dict[str, str]], src_org: str, dst_org: str, side: str):
        """Check the two orgs, then ask for confirmation. Returns an error toast, or None when the dialog opens."""
        if not (src_org and dst_org):
            return rx.toast.error("Pick the org on both sides.")
        if src_org == dst_org:
            return rx.toast.error("The two orgs must be different.")
        self._pending, self._pending_orgs, self._pending_side = rows, (src_org, dst_org), side
        n = len(rows)
        self.confirm_text = (f"{n} phone{'s' if n != 1 else ''} will be deleted from {src_org} and added to "
                             f"{dst_org}. The phone{'s lose' if n != 1 else ' loses'} service until "
                             f"{'they register' if n != 1 else 'it registers'} with {dst_org}.")
        self.confirm_open = True
        return None

    @rx.event
    def migrate_to(self, side: str):
        """Move the phone of the other side's MAC to this side's user (side is "l" or "r")."""
        left = side == "l"
        src_org, dst_org = (self.org_r, self.org_l) if left else (self.org_l, self.org_r)
        mac, from_user = (self.mac_r, self.user_r) if left else (self.mac_l, self.user_l)
        user = self.user_l if left else self.user_r
        if not (mac.strip() and user.strip()):
            yield rx.toast.error("Enter the MAC address on the source side and the user on the destination side.")
            return
        err = self._stage([{"mac": mac.strip(), "user": user.strip(), "from_user": from_user.strip()}],
                          src_org, dst_org, side)
        if err:
            yield err

    @rx.event
    async def migrate_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._stage_csv(files):
            yield ev

    @rx.event
    async def migrate_from_text(self):
        async for ev in self._from_paste(self._stage_csv, "phone", columns=d.MIGRATE_COLUMNS,
                                         markers=("mac", "user")):
            yield ev

    async def _stage_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = d.parse_migrate_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        self._csv_name = files[0].filename or ""
        to_right = self.bulk_dir == "Left To Right"
        src_org, dst_org = (self.org_l, self.org_r) if to_right else (self.org_r, self.org_l)
        err = self._stage(rows, src_org, dst_org, "")
        if err:
            yield err

    @rx.event
    async def confirm_migrate(self):
        self.confirm_open = False
        rows, (src_name, dst_name), side = self._pending, self._pending_orgs, self._pending_side
        self._focus_pane(side != "")
        log = self._webex_log("Webex-Webex Phone Migrate", "webex-webex-phone-migrate")
        try:
            log.info(f"Source org: {src_name}, destination org: {dst_name}")
            if self._csv_name and not side:
                log.info(f"CSV file: {self._csv_name}")
            try:
                src = await asyncio.to_thread(WebexClient.connect, src_name)
                dst = await asyncio.to_thread(WebexClient.connect, dst_name)
                supported = await asyncio.to_thread(get_supported_devices, dst)
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            items = [(r["mac"], lambda r=r: d.migrate_phone(src, dst, r, supported, src_name, dst_name))
                     for r in rows]
            async for ev in self._run_items(items, "Migrating", log):
                yield ev
            if side and self.result_fail_count == 0 and self.results:
                # The phone now sits on the destination side: show its MAC there and empty the source side.
                mac = rows[0]["mac"]
                if side == "l":
                    self.mac_l, self.mac_r = mac, ""
                else:
                    self.mac_r, self.mac_l = mac, ""
            self._pending = []
        finally:
            log.close()


class CucmMigrateState(WebexSession, PanesMixin, RunMixin, PasteMixin):
    """Left side: a CUCM connection, a CUCM user and a MAC. Right side: a Webex org, a Webex user and a MAC (all kept
    in the browser). The right arrow moves the phone of the left MAC to the Webex user (the CUCM phone is kept);
    the left arrow deletes the phone of the right MAC from Webex, for a phone whose configuration is in CUCM."""

    conn_l: str = rx.LocalStorage("")
    user_l: str = rx.LocalStorage("")
    mac_l: str = rx.LocalStorage("")
    org_r: str = rx.LocalStorage("")
    user_r: str = rx.LocalStorage("")
    mac_r: str = rx.LocalStorage("")
    bulk_dir: str = rx.LocalStorage("CUCM To Webex")
    paste_phone: str = rx.LocalStorage("")
    cucm_saved: list[dict[str, str]] = []
    confirm_open: bool = False
    confirm_text: str = ""
    _pending: list[dict[str, str]] = []
    _pending_to_webex: bool = True
    _pending_single: bool = True
    _csv_name: str = ""

    @rx.var
    def cucm_names(self) -> list[str]:
        return [c["name"] for c in self.cucm_saved]

    @rx.var
    def all_org_names(self) -> list[str]:
        return [o["name"] for o in self.webex_orgs]

    @rx.event
    def set_side(self, field: str, value: str):
        setattr(self, field, value)

    @rx.event
    def set_bulk_dir(self, value: str | list[str]):
        self.bulk_dir = value if isinstance(value, str) else value[0]

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    async def load_page(self):
        self.cucm_saved = cucm_connections.list_public()
        await self._refresh_session()

    def _stage(self, rows: list[dict[str, str]], to_webex: bool, single: bool):
        """Check both sides, then ask for confirmation. Returns an error toast, or None when the dialog opens."""
        if not (self.conn_l and self.org_r):
            return rx.toast.error("Pick the CUCM connection and the Webex org.")
        self._pending, self._pending_to_webex, self._pending_single = rows, to_webex, single
        n = len(rows)
        phones = f"{n} phone{'s' if n != 1 else ''}"
        if to_webex:
            self.confirm_text = (f"{phones} from {self.conn_l} will be added to {self.org_r}. The CUCM "
                                 f"phone{'s are' if n != 1 else ' is'} kept.")
        else:
            self.confirm_text = (f"{phones} will be deleted from {self.org_r}. Each phone must already be "
                                 f"configured in {self.conn_l}.")
        self.confirm_open = True
        return None

    @rx.event
    def migrate_to_webex(self):
        if not (self.mac_l.strip() and self.user_r.strip()):
            yield rx.toast.error("Enter the MAC address on the left and the Webex user on the right.")
            return
        err = self._stage([{"mac": self.mac_l.strip(), "user": self.user_r.strip(),
                            "from_user": self.user_l.strip()}], True, True)
        if err:
            yield err

    @rx.event
    def migrate_to_cucm(self):
        if not self.mac_r.strip():
            yield rx.toast.error("Enter the MAC address on the right.")
            return
        err = self._stage([{"mac": self.mac_r.strip(), "user": self.user_l.strip(),
                            "from_user": self.user_r.strip()}], False, True)
        if err:
            yield err

    @rx.event
    async def migrate_from_csv(self, files: list[rx.UploadFile]):
        async for ev in self._stage_csv(files):
            yield ev

    @rx.event
    async def migrate_from_text(self):
        async for ev in self._from_paste(self._stage_csv, "phone", columns=cm.COLUMNS, markers=("mac", "user")):
            yield ev

    async def _stage_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = d.parse_migrate_csv(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        self._csv_name = files[0].filename or ""
        to_webex = self.bulk_dir == "CUCM To Webex"
        # The user column is the Webex user going to Webex, and the optional CUCM owner going to CUCM.
        err = self._stage(rows, to_webex, False)
        if err:
            yield err

    @rx.event
    async def confirm_migrate(self):
        self.confirm_open = False
        rows, to_webex, single = self._pending, self._pending_to_webex, self._pending_single
        conn_name, org_name = self.conn_l, self.org_r
        self._focus_pane(single)
        log = self._webex_log("CUCM Webex Phone Migrate", "webex-cucm-phone-migrate")
        try:
            log.info(f"Direction: {'CUCM to Webex' if to_webex else 'Webex to CUCM'}, CUCM: {conn_name}, "
                     f"Webex org: {org_name}")
            if self._csv_name and not single:
                log.info(f"CSV file: {self._csv_name}")
            try:
                conn = await asyncio.to_thread(cucm_connections.load, conn_name)
                if conn is None:
                    raise UserError(f"CUCM connection {conn_name} is not saved. Add it on the Credentials page.")
                client = await asyncio.to_thread(WebexClient.connect, org_name)
                supported = await asyncio.to_thread(get_supported_devices, client) if to_webex else {}
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            if to_webex:
                items = [(r["mac"], lambda r=r: cm.cucm_to_webex(conn, client, r, supported, org_name)) for r in rows]
            else:
                # Going to CUCM, the user column is the CUCM owner to check; the Webex owner check is single only.
                items = [(r["mac"], lambda r=r: cm.webex_to_cucm(conn, client, r, org_name)) for r in rows]
            async for ev in self._run_items(items, "Migrating", log):
                yield ev
            if single and self.result_fail_count == 0 and self.results:
                mac = rows[0]["mac"]
                if to_webex:
                    self.mac_r, self.mac_l = mac, ""
                else:
                    self.mac_l, self.mac_r = mac, ""
            self._pending = []
        finally:
            log.close()
