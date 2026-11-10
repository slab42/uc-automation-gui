"""State for CUCM > Call Routing > SME Adv & Route Patterns."""

import reflex as rx

from ..backend import cucm_connections, cucm_sme_patterns as sme
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from .cucm import CucmState
from .run_mixin import RunMixin
from .sme_settings import SmeSettingsMixin
from .webex_routing import PasteMixin


class SmePatternsState(CucmState, RunMixin, PasteMixin, SmeSettingsMixin):
    # Page inputs
    form_pattern: str = ""
    paste_text: str = ""

    @rx.var
    def paste_columns(self) -> str:
        """Column titles shown on the Multiple Patterns tab: pattern, then each variable's name."""
        return ", ".join(["pattern"] + [sme.var_display(i, self.var_names) for i in range(len(self.var_names))])

    @rx.var
    def paste_placeholder(self) -> str:
        """Header row plus two example lines for the Paste Text box (same as the CSV example)."""
        return self.csv_example.rstrip("\n")

    @rx.var
    def csv_example(self) -> str:
        cols = [sme.var_display(i, self.var_names) for i in range(len(self.var_names))]
        rows = [",".join([p] + [sme.sample_value(i, self.var_names, n) for i in range(len(cols))]) for n, p in enumerate(("5558594400", "+155585944XX"))]
        return ",".join(["pattern"] + cols) + "\n" + "\n".join(rows) + "\n"

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
    def is_sme(self) -> bool:
        return bool(self.sme_selected)

    def _preview_pattern(self) -> str:
        return self.form_pattern or "5558594400"

    @rx.var
    def ready(self) -> bool:
        """Connection is SME and the settings are valid."""
        return self.is_sme and not self.settings_error

    # --- page inputs ---

    @rx.event
    def set_form_pattern(self, value: str):
        self.form_pattern = value

    # --- run ---

    def _checked_connection(self):
        """(connection, error): the active connection when it may be used for this tool."""
        try:
            conn = sme.require_sme(cucm_connections.load(self.sme_selected) if self.sme_selected else None)
        except AxlError as e:
            return None, str(e)
        if err := self.settings_error:
            return None, err
        return conn, ""

    def _run_rows(self, rows: list[dict], title: str, slug: str, source: str):
        """Event for adding the given {pattern, vars} rows, or a toast."""
        conn, err = self._checked_connection()
        if conn is None:
            return rx.toast.error(err)
        settings, names = self._settings(), self.var_names
        defaults = [self.form_values.get(sme.var_key(i), "").strip() for i in range(len(names))]
        needed = sme.used_vars([settings["adv_desc"], settings["rp_desc"]], names)
        items = []
        for r in rows:
            values = [(r["vars"][i] if i < len(r["vars"]) else "") or defaults[i] for i in range(len(names))]
            for i in sorted(needed):
                if not values[i]:
                    return rx.toast.error(f"No value for {sme.var_display(i, names)} on {r['pattern']}. "
                                          "Enter it on the page or add it to the row.")
            if err := sme.check_values(values, names, self.var_regexes, r["pattern"]):
                return rx.toast.error(err)
            items.append((sme.format_advertised_pattern(r["pattern"]),
                          lambda p=r["pattern"], v=values: sme.add_pattern_pair(conn, settings, names, p, v)))
        log = OpLog(title, slug)
        try:
            log.info(f"Connection: {conn.name} ({conn.server}) as {conn.username}")
            log.info(f"Source: {source}, {len(items)} pattern(s)")
            log.info("Variables: " + ", ".join(sme.var_label(i, names) for i in range(len(names))))
            for key, value in settings.items():
                log.info(f"Setting {key}: {value}")
            return self._start_run(items, "Adding", log)
        finally:
            log.close()

    @rx.event
    def run_single(self):
        if self.busy:
            return
        pattern = self.form_pattern.strip()
        if not pattern:
            yield rx.toast.error("Enter a pattern.")
            return
        yield self._run_rows([{"pattern": pattern, "vars": []}], "SME add Advertised and Route Pattern",
                             "sme-adv-route-pattern", "single pattern")

    async def _csv(self, files):
        """Add the patterns of an uploaded or pasted CSV (shared by both inputs)."""
        if self.busy:
            return
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            rows = sme.parse_pattern_csv(await files[0].read(), self.var_names)
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not rows:
            yield rx.toast.error("The CSV has no data rows.")
            return
        yield self._run_rows(rows, "SME add Advertised and Route Patterns from list", "sme-adv-route-patterns",
                             files[0].filename)

    @rx.event
    async def run_csv(self, files: list[rx.UploadFile]):
        async for ev in self._csv(files):
            yield ev

    @rx.event
    async def run_text(self):
        names = self.var_names
        markers = ["pattern", *[sme.var_key(i).lower() for i in range(len(names))],
                   *[sme.var_display(i, names).lower() for i in range(len(names))]]
        columns = ("pattern", *[sme.var_key(i) for i in range(len(names))])
        async for ev in self._from_paste(self._csv, "text", columns=columns, markers=tuple(markers)):
            yield ev
