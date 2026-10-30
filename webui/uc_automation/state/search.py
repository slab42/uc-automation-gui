"""Home page search over every menu item of every platform."""

import reflex as rx

from ..components import cuc_nav, cucm_nav, redsky_nav, webex_nav

# (platform label, GROUPS) - same data that drives each platform's menu bar
_SOURCES = [("CUCM", cucm_nav.GROUPS), ("CUC", cuc_nav.GROUPS), ("Webex", webex_nav.GROUPS),
            ("RedSky", redsky_nav.GROUPS)]

INDEX: list[dict[str, str]] = [
    {"platform": platform, "section": section, "label": label, "description": desc, "route": route}
    for platform, groups in _SOURCES
    for section, items in groups
    for label, route, _icon, desc in items
]


def _haystack(item: dict[str, str]) -> str:
    return " ".join(v for k, v in item.items() if k != "route").lower()


class SearchState(rx.State):
    query: str = ""

    @rx.event
    def set_query(self, value: str):
        self.query = value

    @rx.var
    def results(self) -> list[dict[str, str]]:
        terms = self.query.lower().split()
        if not terms:
            return []
        return [
            item
            for item in INDEX
            if all(t in _haystack(item) for t in terms)
        ]

    @rx.var
    def searching(self) -> bool:
        return bool(self.query.strip())
