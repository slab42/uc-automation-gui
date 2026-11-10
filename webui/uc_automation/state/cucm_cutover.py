"""State for CUCM > Migration > Webex Cutover: remove alternate numbers, move partition, add SME patterns."""

import reflex as rx

from ..backend import cucm_connections, cucm_cutover as cut, cucm_sme_patterns as sme
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from .cucm import CucmState
from .run_mixin import RunMixin
from .sme_settings import SmeSettingsMixin
from .webex_routing import PasteMixin


class CutoverState(CucmState, RunMixin, PasteMixin, SmeSettingsMixin):
    # Settings window (browser LocalStorage)
    src_partition: str = rx.LocalStorage("", name="cut_src_partition")
    dest_partition: str = rx.LocalStorage("", name="cut_dest_partition")

    # Page inputs
    paste_text: str = ""
    prefix: str = ""
    number_length: str = ""
    confirm_alt: bool = False
    confirm_move: bool = False
    adv_anyway: bool = False
    _error: str = ""

    @rx.var
    def used_var_rows(self) -> list[dict[str, str]]:
        """The variables the descriptions use (the ones this page asks a value for)."""
        used = sme.used_vars([self.adv_desc, self.rp_desc], self.var_names)
        return [r for i, r in enumerate(self.var_rows) if i in used]

    @rx.var
    def sme_names(self) -> list[str]:
        """SME clusters among the organization's saved connections."""
        return [c["name"] for c in self.org_connections if c.get("sme") == "yes"]

    @rx.var
    def sme_selected(self) -> str:
        """The SME cluster in use: the first SME connection of the organization."""
        names = self.sme_names
        return names[0] if names else ""

    @rx.var
    def dn_count(self) -> int:
        try:
            return len(cut.parse_dn_list(self.paste_text, self.src_partition, self.prefix, self.number_length)) if self.paste_text.strip() else 0
        except ValueError:
            return 0

    # --- settings and inputs ---

    @rx.event
    def set_src_partition(self, value: str):
        self.src_partition = value

    @rx.event
    def set_dest_partition(self, value: str):
        self.dest_partition = value

    @rx.event
    def set_paste_text(self, value: str):
        self.paste_text = value

    @rx.event
    def set_prefix(self, value: str):
        self.prefix = value

    @rx.event
    def set_number_length(self, value: str):
        self.number_length = "".join(c for c in value if c.isdigit())[:3]

    @rx.event
    def set_confirm_alt(self, value: bool):
        self.confirm_alt = value

    @rx.event
    def set_adv_anyway(self, value: bool):
        self.adv_anyway = value

    @rx.event
    def set_confirm_move(self, value: bool):
        self.confirm_move = value

    @rx.event
    async def load_csv(self, files: list[rx.UploadFile]):
        """A CSV file fills the Paste Text box, so both inputs go through the same handlers."""
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        self.paste_text = (await files[0].read()).decode("utf-8-sig", errors="replace")
        yield rx.toast.success(f"Loaded {files[0].filename}. Check the list on the Paste Text tab.")

    # --- runs ---

    def _rows(self) -> list[dict[str, str]] | None:
        try:
            rows = cut.parse_dn_list(self.paste_text, self.src_partition, self.prefix, self.number_length)
        except ValueError as e:
            self._error = str(e)
            return None
        if not rows:
            self._error = "No directory numbers in the list."
            return None
        return rows

    def _start(self, title: str, slug: str, verb: str, conn, build, extra_log: list[str] | None = None):
        """Parse the list, then run `build(row)` (a zero-argument callable) per row on `conn`."""
        if self.busy:
            return None
        rows = self._rows()
        if rows is None:
            return rx.toast.error(self._error)
        log = OpLog(title, slug)
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Source: {len(rows)} directory number(s)")
            for line in extra_log or []:
                log.info(line)
            return self._start_run([(cut.label(r), build(r)) for r in rows], verb, log)
        finally:
            log.close()

    @rx.event
    def run_remove_alt(self):
        self.confirm_alt = False
        conn = self._conn()
        if conn is None:
            yield rx.toast.error("Add a CUCM connection first.")
            return
        ev = self._start("Cutover remove Enterprise and E.164 alternate numbers", "cutover-remove-alt-numbers",
                         "Removing", conn, lambda r: lambda: cut.remove_alt(conn, r))
        if ev is not None:
            yield ev

    @rx.event
    def run_move(self):
        self.confirm_move = False
        conn = self._conn()
        dest = self.dest_partition.strip()
        if conn is None:
            yield rx.toast.error("Add a CUCM connection first.")
            return
        if not dest:
            yield rx.toast.error("Set the destination partition in Settings first.")
            return
        ev = self._start("Cutover move DN partition", "cutover-move-partition", "Moving", conn,
                         lambda r: lambda: cut.move_partition(conn, r, dest), [f"Destination partition: {dest}"])
        if ev is not None:
            yield ev

    @rx.event
    def run_sme(self):
        try:
            conn = sme.require_sme(cucm_connections.load(self.sme_selected) if self.sme_selected else None)
        except AxlError as e:
            yield rx.toast.error(str(e))
            return
        if err := self.settings_error:
            yield rx.toast.error(err)
            return
        settings, names = {k: getattr(self, k) for k in sme.DEFAULTS}, self.var_names
        values = [self.form_values.get(sme.var_key(i), "").strip() for i in range(len(names))]
        for i in sorted(sme.used_vars([settings["adv_desc"], settings["rp_desc"]], names)):
            if not values[i]:
                yield rx.toast.error(f"Enter a value for {sme.var_display(i, names)}.")
                return
        if err := sme.check_values(values, names, self.var_regexes):
            yield rx.toast.error(err)
            return
        log = [f"Setting {k}: {v}" for k, v in settings.items()]
        anyway = self.adv_anyway
        log.append(f"Add Advertised Pattern when the Route Pattern exists: {anyway}")
        ev = self._start("Cutover SME add Advertised and Route Patterns", "cutover-sme-patterns", "Adding", conn,
                         lambda r: lambda: cut.add_sme_patterns(conn, settings, names, r, values, anyway), log)
        if ev is not None:
            yield ev
