"""UCCX section: top menu bar and page wrapper."""

import reflex as rx

from ..state.uccx import UccxState
from .access import show_if, show_if_any
from .layout import page
from .org_picker import instance_select, org_select

UCCX_HOME = "/uccx"
MIGRATE = "/uccx/migrate"
SCRIPT_REPORT = "/uccx/script-report"

# (menu label, [(item label, route, icon, description)])
GROUPS = [
    ("Migration", [
        ("Migrate", MIGRATE, "arrow-right-left",
         "Download everything it can from a UCCX server, then upload it to a new UCCX server."),
    ]),
    ("Scripts", [
        ("Script Report", SCRIPT_REPORT, "file-search",
         "Read UCCX scripts (.aef), from the stored download or an upload, and report their steps and variables."),
    ]),
]


def _connection_picker(show_instance: bool) -> rx.Component:
    if not show_instance:
        return org_select(UccxState)
    return rx.hstack(
        org_select(UccxState),
        rx.cond(
            UccxState.has_active,
            rx.hstack(
                instance_select(UccxState.connection_names, UccxState.active, UccxState.select_active),
                rx.badge(UccxState.active_label, variant="soft", color_scheme="gray"),
                align="center",
                spacing="2",
            ),
            rx.link(rx.button("Add a connection", size="1", variant="soft"), href="/credentials?tab=uccx"),
        ),
        align="center",
        spacing="2",
    )


def menubar(show_instance: bool = True) -> rx.Component:
    return rx.hstack(
        *[
            show_if_any([i[1] for i in items], rx.menu.root(
                rx.menu.trigger(rx.button(label, rx.icon("chevron-down", size=15), variant="ghost", size="2")),
                rx.menu.content(
                    *[show_if(route, rx.menu.item(name, on_click=rx.redirect(route))) for name, route, _icon, _desc in items],
                ),
            ))
            for label, items in GROUPS
        ],
        rx.spacer(),
        _connection_picker(show_instance),
        align="center",
        spacing="3",
        padding="0.4rem 1.5rem",
        background="var(--gray-2)",
        border_bottom="1px solid var(--gray-5)",
        width="100%",
    )


def uccx_page(title: str, *children: rx.Component, show_instance: bool = True) -> rx.Component:
    heading = title if title == "UCCX" else f"UCCX - {title}"
    return page(heading, *children, subnav=menubar(show_instance))
