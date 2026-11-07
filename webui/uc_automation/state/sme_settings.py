"""The SME pattern settings (descriptions, pattern type, PSTN, route pattern, variables and their regexes).

Shared by SME Adv & Route Patterns and Webex Cutover: both keep them in the same browser LocalStorage keys, so
editing them on either page changes both."""

import json

import reflex as rx

from ..backend import cucm_sme_patterns as sme


def _one(value: str | list[str]) -> str:
    return value if isinstance(value, str) else value[0]


class SmeSettingsMixin(rx.State, mixin=True):
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
    var_regex_json: str = rx.LocalStorage("[]", name="sme_var_regex")

    # Values typed on the page, one per variable (Var1...)
    form_values: dict[str, str] = {}

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
    def var_regexes(self) -> list[str]:
        """One regex per variable ('' = no check), same order as var_names."""
        try:
            items = json.loads(self.var_regex_json)
        except ValueError:
            items = []
        items = [i if isinstance(i, str) else "" for i in items] if isinstance(items, list) else []
        names = self.var_names
        return (items + [""] * len(names))[:len(names)]

    @rx.var
    def var_rows(self) -> list[dict[str, str]]:
        """One row per variable: key (Var1), index, label, display, name, regex, the value typed on the page and
        whether that value fails the regex."""
        names, regexes = self.var_names, self.var_regexes
        rows = []
        for i, n in enumerate(names):
            value = self.form_values.get(sme.var_key(i), "")
            rows.append({"key": sme.var_key(i), "index": str(i), "label": sme.var_label(i, names),
                         "display": sme.var_display(i, names), "name": n, "regex": regexes[i], "value": value,
                         "error": sme.check_values([""] * i + [value], names, regexes)})
        return rows

    @rx.var
    def can_add_var(self) -> bool:
        return len(self.var_names) < sme.MAX_VARS

    @rx.var
    def settings_error(self) -> str:
        return sme.check_settings(self._settings(), self.var_names) or sme.check_regexes(self.var_regexes, self.var_names)

    def _settings(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in sme.DEFAULTS}

    def _preview_pattern(self) -> str:
        return "5558594400"

    def _sample_values(self) -> list[str]:
        """Values for the example descriptions: what is typed on the page, else the variable's name."""
        return [self.form_values.get(sme.var_key(i), "").strip() or (n.strip() or sme.var_key(i))
                for i, n in enumerate(self.var_names)]

    @rx.var
    def adv_preview(self) -> str:
        return sme.render_description(self.adv_desc, self._sample_values(), self.var_names, self._preview_pattern())

    @rx.var
    def rp_preview(self) -> str:
        return sme.render_description(self.rp_desc, self._sample_values(), self.var_names, self._preview_pattern())

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
        self._save_names(list(sme.DEFAULT_VARS), [""])

    # --- variables ---

    def _save_names(self, names: list[str], regexes: list[str]) -> None:
        self.var_names_json = json.dumps(names)
        self.var_regex_json = json.dumps(regexes)

    @rx.event
    def set_form_value(self, key: str, value: str):
        self.form_values = {**self.form_values, key: value}

    @rx.event
    def add_variable(self):
        names = self.var_names
        if len(names) < sme.MAX_VARS:
            self._save_names(names + [""], self.var_regexes + [""])

    @rx.event
    def set_var_name(self, key: str, value: str):
        names = list(self.var_names)
        i = int(key.removeprefix("Var")) - 1
        if 0 <= i < len(names):
            names[i] = value
            self._save_names(names, self.var_regexes)

    @rx.event
    def set_var_regex(self, key: str, value: str):
        regexes = list(self.var_regexes)
        i = int(key.removeprefix("Var")) - 1
        if 0 <= i < len(regexes):
            regexes[i] = value
            self._save_names(self.var_names, regexes)

    @rx.event
    def remove_variable(self, key: str):
        """Remove Var2 or later; the ones after it move up (Var3 becomes Var2)."""
        names, regexes, values = list(self.var_names), list(self.var_regexes), self.form_values
        i = int(key.removeprefix("Var")) - 1
        if i < 1 or i >= len(names):
            return
        del names[i]
        del regexes[i]
        self.form_values = {sme.var_key(j): values.get(sme.var_key(j + (j >= i)), "") for j in range(len(names))}
        self.adv_desc = sme.renumber_template(self.adv_desc, i)
        self.rp_desc = sme.renumber_template(self.rp_desc, i)
        self._save_names(names, regexes)
