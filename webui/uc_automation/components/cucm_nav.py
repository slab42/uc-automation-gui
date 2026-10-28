"""CUCM section: top menu bar and page wrapper."""

import reflex as rx

from ..state.cucm import CucmState
from .layout import page

CUCM_HOME = "/cucm"
ADVERTISED_PATTERNS = "/cucm/advertised-patterns"
PARTITIONS = "/cucm/partitions"
CSS = "/cucm/calling-search-spaces"
PICKUP_GROUPS = "/cucm/call-pickup-groups"

# (menu label, [(item label, route, icon, description)])
GROUPS = [
    ("Call Routing", [
        ("Advertised Patterns", ADVERTISED_PATTERNS, "route", "Hosted DN patterns: search, add, import, export, remove."),
        ("Partitions", PARTITIONS, "layers", "Route partitions: search, add, import, export, remove."),
        ("Calling Search Spaces", CSS, "list-ordered", "CSSs and their ordered partitions."),
        ("Call Pickup Groups", PICKUP_GROUPS, "users", "Call pickup groups: search, add, import, export, check dependencies, remove."),
    ]),
    ("Devices", [
        ("Phones", "/cucm/phones", "tablet-smartphone", "Phones: search, add, import, export, remove."),
        ("Softkey Templates", "/cucm/softkey-templates", "keyboard", "Softkey templates."),
        ("Common Device Configs", "/cucm/common-device-configs", "settings-2", "Common device configurations."),
        ("Phone Button Templates", "/cucm/phone-button-templates", "grid-3x3", "Phone button templates."),
        ("Physical Phones (MPP)", "/cucm/mpp-phones", "refresh-cw", "Migrate 78xx/88xx phones to MPP firmware or prep them for Webex Calling."),
    ]),
]


def _connection_picker(on_change) -> rx.Component:
    return rx.cond(
        CucmState.has_active,
        rx.hstack(
            rx.badge(CucmState.active_label, variant="soft", color_scheme="gray"),
            rx.select(
                CucmState.connection_names,
                value=CucmState.active,
                on_change=on_change,
                size="1",
            ),
            align="center",
            spacing="2",
        ),
        rx.link(rx.button("Add a connection", size="1", variant="soft"), href="/credentials"),
    )


def menubar(on_connection_change=None) -> rx.Component:
    picker = _connection_picker(on_connection_change or CucmState.select_active)
    return rx.hstack(
        rx.link(
            rx.button(rx.icon("phone", size=15), "CUCM", variant="ghost", size="2"),
            href=CUCM_HOME,
            underline="none",
        ),
        *[
            rx.menu.root(
                rx.menu.trigger(
                    rx.button(label, rx.icon("chevron-down", size=15), variant="ghost", size="2"),
                ),
                rx.menu.content(
                    *[rx.menu.item(name, on_click=rx.redirect(route)) for name, route, _icon, _desc in items],
                ),
            )
            for label, items in GROUPS
        ],
        rx.spacer(),
        picker,
        align="center",
        spacing="3",
        padding="0.4rem 1.5rem",
        background="var(--gray-2)",
        border_bottom="1px solid var(--gray-5)",
        width="100%",
    )


def cucm_page(title: str, *children: rx.Component, on_connection_change=None) -> rx.Component:
    return page(title, *children, subnav=menubar(on_connection_change))
