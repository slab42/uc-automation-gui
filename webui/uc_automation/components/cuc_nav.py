"""CUC section: top menu bar and page wrapper."""

import reflex as rx

from ..state.cuc import CucState
from .layout import page

CUC_HOME = "/cuc"
STATUS_CHECK = "/cuc/status-check"
USAGE_CHECK = "/cuc/usage-check"
REMOVE_EMPTY = "/cuc/remove-empty"
MAP = "/cuc/map"
LIST_HANDLERS = "/cuc/list-handlers"
DELETE_HANDLERS = "/cuc/delete-handlers"

# (menu label, [(item label, route, icon, description)])
GROUPS = [
    ("Users", [
        ("Status Check", STATUS_CHECK, "activity",
         "Mailbox status, size, quotas and quota flags for one extension or a list."),
        ("Usage Check", USAGE_CHECK, "hard-drive", "Mailbox size per extension, exported to CSV."),
        ("Remove Empty", REMOVE_EMPTY, "user-x",
         "Find mailboxes with no data and delete their user accounts after review."),
    ]),
    ("Call Handlers", [
        ("Map", MAP, "network", "Build a call tree workbook (Excel) from the live system or from the Search CSVs."),
        ("Search", LIST_HANDLERS, "search",
         "Search call handlers, delete them, or export them and their menu entries to CSV."),
        ("Bulk Delete", DELETE_HANDLERS, "trash-2",
         "Delete call handlers listed in a pasted list or CSV, after review."),
    ]),
]


def _connection_picker() -> rx.Component:
    return rx.cond(
        CucState.has_active,
        rx.hstack(
            rx.badge(CucState.active_label, variant="soft", color_scheme="gray"),
            rx.select(CucState.connection_names, value=CucState.active, on_change=CucState.select_active, size="1"),
            align="center",
            spacing="2",
        ),
        rx.link(rx.button("Add a connection", size="1", variant="soft"), href="/credentials"),
    )


def menubar() -> rx.Component:
    return rx.hstack(
        *[
            rx.menu.root(
                rx.menu.trigger(rx.button(label, rx.icon("chevron-down", size=15), variant="ghost", size="2")),
                rx.menu.content(
                    *[rx.menu.item(name, on_click=rx.redirect(route)) for name, route, _icon, _desc in items],
                ),
            )
            for label, items in GROUPS
        ],
        rx.spacer(),
        _connection_picker(),
        align="center",
        spacing="3",
        padding="0.4rem 1.5rem",
        background="var(--gray-2)",
        border_bottom="1px solid var(--gray-5)",
        width="100%",
    )


def cuc_page(title: str, *children: rx.Component) -> rx.Component:
    heading = title if title == "CUC" else f"CUC - {title}"
    return page(heading, *children, subnav=menubar())


def need_connection(body: rx.Component) -> rx.Component:
    return rx.cond(
        CucState.has_active,
        body,
        rx.callout(
            rx.hstack(rx.text("No CUC connection is set up yet."),
                      rx.link("Add one on the Credentials page", href="/credentials"), spacing="2"),
            icon="info", width="100%",
        ),
    )
