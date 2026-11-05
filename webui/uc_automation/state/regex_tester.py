"""State for Tools > Regex Tester. Results update as the user types; nothing is saved."""

import reflex as rx

from ..backend import regex_tester as rt

SAMPLE_TEXT = "Main-CQ 5551234\nSales-HG 5559876\nlobby-aa 5550000"


class RegexTesterState(rx.State):
    pattern: str = ""
    text: str = SAMPLE_TEXT
    replace: str = ""
    ignorecase: bool = False
    multiline: bool = False
    dotall: bool = False
    error: str = ""
    replace_error: str = ""
    truncated: bool = False
    parts: list[dict[str, str]] = []  # highlighted text pieces: text, kind ("", "a", "b")
    rows: list[dict[str, str]] = []  # one per match: n, span, text, groups
    replaced: str = ""
    count: int = 0

    def _run(self):
        flags = [n for n in rt.FLAGS if getattr(self, n)]
        res = rt.run(self.pattern, self.text, flags, self.replace if self.replace else None)
        self.error = res.get("error", "")
        self.replace_error = res.get("replace_error", "")
        matches = res.get("matches", [])
        self.truncated = res.get("truncated", False)
        self.count = len(matches)
        self.replaced = res.get("replaced", "")
        if self.error or not self.pattern:
            self.parts = [{"text": self.text, "kind": ""}] if self.text else []
            self.rows = []
            return
        self.parts = rt.segments(self.text, matches)
        self.rows = [
            {"n": str(i + 1), "span": f"{m['start']}-{m['end']}", "text": m["text"] or "(empty)",
             "groups": ", ".join(f"{g['label']}: {g['value'] if g['value'] is not None else '(none)'}"
                                 for g in m["groups"])}
            for i, m in enumerate(matches)
        ]

    @rx.event
    def on_page_load(self):
        self._run()

    @rx.event
    def set_pattern(self, value: str):
        self.pattern = value
        self._run()

    @rx.event
    def set_text(self, value: str):
        self.text = value
        self._run()

    @rx.event
    def set_replace(self, value: str):
        self.replace = value
        self._run()

    @rx.event
    def set_flag(self, name: str, value: bool):
        if name in rt.FLAGS:
            setattr(self, name, bool(value))
            self._run()

    @rx.event
    def insert_token(self, token: str):
        """Append a quick reference token to the pattern."""
        self.pattern += token
        self._run()

    @rx.event
    def clear_all(self):
        self.pattern = self.text = self.replace = ""
        self._run()

    @rx.event
    def load_sample(self):
        self.text = SAMPLE_TEXT
        self._run()
