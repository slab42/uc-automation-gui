"""State for Webex > Tools: Naming Check (validate item names against a regex per type, rename failures)."""

import asyncio
from datetime import datetime

from typing import ClassVar

import reflex as rx

from ..backend import webex_naming as n
from ..backend.errors import UserError
from .run_mixin import RunMixin
from .webex_routing import WebexSession, _one


class NamingCheckState(WebexSession, RunMixin):

    output_fields: ClassVar[tuple[str, ...]] = ("checks", "regex_out", "regex_desc", "regex_notes")
    patterns: dict[str, str] = {k: "" for k in n.TYPES}
    find: str = ""
    replace: str = ""
    checking: bool = False
    checks: list[dict[str, str]] = []
    filter_status: str = "FAIL"
    confirm_open: bool = False
    regex_desc: str = ""
    regex_out: str = ""
    regex_notes: list[str] = []
    regex_target: str = "Call Queue"
    _items: list[dict[str, str]] = []
    _rules: dict[str, str] = {}

    @rx.var
    def type_rows(self) -> list[dict[str, str]]:
        return [{"key": k, "label": label, "pattern": self.patterns.get(k, "")} for k, label in n.TYPES.items()]

    @rx.var
    def hint_labels(self) -> list[str]:
        return [h[0] for h in n.HINTS]

    @rx.var
    def pass_count(self) -> int:
        return sum(1 for r in self.checks if r["status"] == "PASS")

    @rx.var
    def fail_count(self) -> int:
        return sum(1 for r in self.checks if r["status"] == "FAIL")

    @rx.var
    def rename_count(self) -> int:
        return sum(1 for r in self.checks if r["valid"])

    @rx.var
    def shown_checks(self) -> list[dict[str, str]]:
        if self.filter_status == "All":
            return self.checks
        return [r for r in self.checks if r["status"] == self.filter_status]

    @rx.event
    async def load_page(self):
        await self._refresh_session()

    @rx.event
    def set_pattern(self, key: str, value: str):
        self.patterns[key] = value

    @rx.event
    def apply_hint(self, key: str, label: str):
        self.patterns[key] = next((p for lab, p in n.HINTS if lab == label), self.patterns.get(key, ""))

    @rx.event
    def set_suggestion(self, key: str, value: str):
        """Edit a suggested name by hand. It is renamed only when it passes the rule."""
        for r in self.checks:
            if r["key"] == key:
                value = value.strip()
                r["suggestion"] = value
                r["valid"] = "1" if value and value != r["name"] and n.fits(r["type"], value) and n.matches(
                    self._rules[r["type"]], value, r["location"]) else ""

    @rx.event
    def set_regex_desc(self, value: str):
        self.regex_desc = value

    @rx.event
    def set_regex_out(self, value: str):
        self.regex_out = value

    @rx.event
    def set_regex_target(self, value: str):
        self.regex_target = value

    @rx.event
    def generate_regex(self):
        if not self.regex_desc.strip():
            return rx.toast.error("Describe the rule first.")
        self.regex_out, self.regex_notes = n.describe_to_regex(self.regex_desc)

    @rx.event
    def use_regex(self):
        """Put the generated regex in the Rules box of the chosen item type."""
        try:
            rule = n.compile_pattern(self.regex_out)
        except ValueError as e:
            return rx.toast.error(str(e))
        if not rule:
            return rx.toast.error("There is no regex to use yet.")
        key = next(k for k, label in n.TYPES.items() if label == self.regex_target)
        self.patterns[key] = rule
        return rx.toast.success(f"Set as the {self.regex_target} rule. See the Rules tab.")

    @rx.event
    def set_find(self, value: str):
        self.find = value

    @rx.event
    def set_replace(self, value: str):
        self.replace = value

    @rx.event
    def set_filter_status(self, value: str | list[str]):
        self.filter_status = _one(value)

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    @rx.event
    async def run_check(self):
        if self.busy or self.checking:
            return
        try:
            rules = {k: n.compile_pattern(v) for k, v in self.patterns.items()}
            if self.find:
                n.compile_pattern(self.find)
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        rules = {k: v for k, v in rules.items() if v}
        if not rules:
            yield rx.toast.error("Enter a regex for at least one item type.")
            return
        self.checking = True
        self.checks, self.results = [], []
        yield
        log = self._webex_log("Naming check", "webex-naming-check")
        try:
            for k, v in rules.items():
                log.info(f"Rule {n.TYPES[k]}: {v}")
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            try:
                items = await asyncio.to_thread(n.list_items, client, list(rules))
            except UserError as e:
                log.error(str(e))
                yield rx.toast.error(str(e))
                return
            self._items = items
            self._rules = rules
            self.checks = await asyncio.to_thread(n.check_rows, items, rules, self.find, self.replace)
            for r in self.checks:
                if r["status"] == "FAIL":
                    log.warning(f"{r['label']} '{r['name']}' ({r['location']}): {r['reason']}"
                                + (f" -> suggested '{r['suggestion']}'" if r["suggestion"] else ""))
            log.info(f"{len(items)} item(s) read: {self.pass_count} pass, {self.fail_count} fail, "
                     f"{self.rename_count} with a suggested name")
        finally:
            log.close()
            self.checking = False

    @rx.event
    async def rename_all(self):
        if not self.confirm_open or self.busy:
            return
        self.confirm_open = False
        todo = [dict(r) for r in self.checks if r["valid"]]
        if not todo:
            yield rx.toast.error("No item has a valid suggested name.")
            return
        log = self._webex_log("Naming check rename", "webex-naming-rename")
        try:
            client = await self._connect(log)
            if client is None:
                yield rx.toast.error(self.webex_message)
                return
            items = [(f"{r['label']}: {r['name']}", lambda r=r: n.rename(client, r, r["suggestion"]))
                     for r in todo]
            yield self._start_run(items, "Renaming", log)
        finally:
            log.close()

    @rx.event
    def export_csv(self):
        if not self.checks:
            return rx.toast.error("Nothing to export.")
        return rx.download(data=n.results_csv(self.checks),
                           filename=f"{datetime.now():%Y-%m-%d_%H-%M-%S}-webex_naming_check.csv")
