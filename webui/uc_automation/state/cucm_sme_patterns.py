"""State for CUCM > Call Routing > SME Adv & Route Patterns."""

import json

import reflex as rx

from ..backend import cucm_sme_patterns as sme
from ..backend.applog import OpLog
from ..backend.cucm_axl import AxlError
from .cucm import CucmState
from .run_mixin import RunMixin
from .webex_routing import PasteMixin



def _one(value: str | list[str]) -> str:
    return value if isinstance(value, str) else value[0]


class SmePatternsState(CucmState, RunMixin, PasteMixin):
    # Settings window (kept in the browser, per user, like the other page preferences)
    settings_open: bool = False
    adv_desc: str = rx.LocalStorage(sme.DEFAULTS["adv_desc"], name="sme_adv_desc")
    adv_type: str = rx.LocalStorage(sme.DEFAULTS["adv_type"], name="sme_adv_type")
    pstn_rule: str = rx.LocalStorage(sme.DEFAULTS["pstn_rule"], name="sme_pstn_rule")
    pstn_strip: str = rx.LocalStorage(sme.DEFAULTS["pstn_strip"], name="sme_pstn_strip")
    pstn_prepend: str = rx.LocalStorage(sme.DEFAULTS["pstn_prepend"], name="sme_pstn_prepend")
    rp_desc: str = rx.LocalStorage(sme.DEFAULTS["rp_desc"], name="sme_rp_desc")
    rp_partition: str = rx.LocalStorage(sme.DEFAULTS["rp_partition"], name="sme_rp_partition")
    rp_dest_type: str = rx.LocalStorage(sme.DEFAULTS["rp_dest_type"], name="sme_rp_dest_type")
    rp_dest: str = rx.LocalStorage(sme.DEFAULTS["rp_dest"], name="sme_rp_dest")
    var_names_json: str = rx.LocalStorage(json.dumps(sme.DEFAULT_VARS), name="sme_var_names")

    # Page inputs
    form_pattern: str = ""
    form_values: dict[str, str] = {}
    paste_text: str = ""

    @rx.var
    def pstn_choices(self) -> list[list[str]]:
        return [[v, label] for v, label in sme.PSTN_CHOICES]

    @rx.var
    def pattern_types(self) -> list[str]:
        return sme.PATTERN_TYPES

    @rx.var
    def dest_types(self) -> list[str]:
        return sme.DEST_TYPES

    @rx.var
    def var_names(self) -> list[str]:
        try:
            names = json.loads(self.var_names_json)
            if isinstance(names, list) and names and all(isinstance(n, str) for n in names):
                return names[:sme.MAX_VARS]
        except ValueError:
            pass
        return list(sme.DEFAULT_VARS)

    @rx.var
    def var_rows(self) -> list[dict[str, str]]:
        """One row per variable: key (Var1), index, label (Var1 - Department), name and the value typed on the page."""
        names = self.var_names
        return [{"key": sme.var_key(i), "index": str(i), "label": sme.var_label(i, names), "name": n,
                 "value": self.form_values.get(sme.var_key(i), "")} for i, n in enumerate(names)]

    @rx.var
    def can_add_var(self) -> bool:
        return len(self.var_names) < sme.MAX_VARS

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
    def is_sme(self) -> bool:
        return self.active_info.get("sme", "") == "yes"

    @rx.var
    def settings_error(self) -> str:
        return sme.check_settings(self._settings(), self.var_names)

    def _sample_values(self) -> list[str]:
        """Values for the example descriptions: what is typed on the page, else the variable's name."""
        return [self.form_values.get(sme.var_key(i), "").strip() or (n.strip() or sme.var_key(i))
                for i, n in enumerate(self.var_names)]

    @rx.var
    def adv_preview(self) -> str:
        return sme.render_description(self.adv_desc, self._sample_values(), self.var_names,
                                      self.form_pattern or "5558594400")

    @rx.var
    def rp_preview(self) -> str:
        return sme.render_description(self.rp_desc, self._sample_values(), self.var_names,
                                      self.form_pattern or "5558594400")

    @rx.var
    def ready(self) -> bool:
        """Connection is SME and the settings are valid."""
        return self.is_sme and not self.settings_error

    def _settings(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in sme.DEFAULTS}

    # --- settings window ---

    @rx.event
    def set_settings_open(self, value: bool):
        self.settings_open = value

    @rx.event
    def set_setting(self, key: str, value: str | list[str]):
        if key in sme.DEFAULTS:
            setattr(self, key, _one(value))

    @rx.event
    def reset_settings(self):
        for key, value in sme.DEFAULTS.items():
            setattr(self, key, value)
        self._save_names(list(sme.DEFAULT_VARS))

    # --- page inputs ---

    @rx.event
    def set_form_pattern(self, value: str):
        self.form_pattern = value

    @rx.event
    def set_form_value(self, key: str, value: str):
        self.form_values = {**self.form_values, key: value}

    # --- variables (settings window) ---

    def _save_names(self, names: list[str]) -> None:
        self.var_names_json = json.dumps(names)

    @rx.event
    def add_variable(self):
        names = self.var_names
        if len(names) < sme.MAX_VARS:
            self._save_names(names + [""])

    @rx.event
    def set_var_name(self, key: str, value: str):
        names = list(self.var_names)
        i = int(key.removeprefix("Var")) - 1
        if 0 <= i < len(names):
            names[i] = value
            self._save_names(names)

    @rx.event
    def remove_variable(self, key: str):
        """Remove Var2 or later; the ones after it move up (Var3 becomes Var2)."""
        names, values = list(self.var_names), self.form_values
        i = int(key.removeprefix("Var")) - 1
        if i < 1 or i >= len(names):
            return
        del names[i]
        moved = {sme.var_key(j): values.get(sme.var_key(j + (j >= i)), "") for j in range(len(names))}
        self.form_values = moved
        self.adv_desc = sme.renumber_template(self.adv_desc, i)
        self.rp_desc = sme.renumber_template(self.rp_desc, i)
        self._save_names(names)

    # --- run ---

    def _checked_connection(self):
        """(connection, error): the active connection when it may be used for this tool."""
        try:
            conn = sme.require_sme(self._conn())
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
                    return rx.toast.error(f"No value for {sme.var_label(i, names)} on {r['pattern']}. "
                                          "Enter it on the page or add it to the row.")
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
