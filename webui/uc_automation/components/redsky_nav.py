"""RedSky section: top menu bar and page wrapper."""

import reflex as rx

from ..state.redsky import RedskyState
from .layout import page
from .org_picker import org_select

REDSKY_HOME = "/redsky"
BUILDINGS_ADD = "/redsky/buildings-add"
LOCATIONS_ADD = "/redsky/locations-add"
ENTIRE_SITE = "/redsky/entire-site"
IMPORT_PRECHECK = "/redsky/import-precheck"
ALERTS_ADD = "/redsky/alerts-add"
ALERTS_CHECK = "/redsky/alerts-check"
BSSID = "/redsky/bssid"
LLDP = "/redsky/lldp"
PRIVATE_IP = "/redsky/private-ip"
PUBLIC_IP = "/redsky/public-ip"

# (menu label, [(item label, route, icon, description)])
GROUPS = [
    ("Buildings And Locations", [
        ("Add Buildings", BUILDINGS_ADD, "building-2", "Add Buildings to RedSky, one at a time or from a list."),
        ("Add Locations", LOCATIONS_ADD, "map-pin-plus", "Add Locations under a Building, one at a time or from a list."),
        ("Check Entire Site", ENTIRE_SITE, "circle-check",
         'Find Buildings that have no "<Building> - Entire Site" location.'),
    ]),
    ("Alerts", [
        ("Add Alerts", ALERTS_ADD, "bell-plus", "Add alert subscriptions with recipients and scope."),
        ("Check All Buildings", ALERTS_CHECK, "bell-ring",
         "Find Buildings that have no alert named like the Building that covers it."),
    ]),
    ("Tracking", [
        ("BSSID", BSSID, "wifi", "Add access point BSSIDs and tie each to a Location."),
        ("LLDP", LLDP, "network", "Add LLDP switches and ports and tie them to a Location."),
        ("Private IP", PRIVATE_IP, "server", "Add private IP ranges and tie each to a Location."),
        ("Public IP", PUBLIC_IP, "globe", "Add public (trusted) IP ranges."),
    ]),
    ("Tools", [
        ("Import Precheck", IMPORT_PRECHECK, "search-check",
         "Check Buildings (name and address), Locations and Private IP ranges against RedSky before an import."),
    ]),
]


def _connection_picker() -> rx.Component:
    return rx.hstack(
        org_select(RedskyState),
        rx.cond(
            RedskyState.has_active,
            rx.select(RedskyState.connection_names, value=RedskyState.active, on_change=RedskyState.select_active,
                      size="1"),
            rx.link(rx.button("Add a connection", size="1", variant="soft"), href="/credentials"),
        ),
        align="center",
        spacing="2",
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


def redsky_page(title: str, *children: rx.Component) -> rx.Component:
    heading = title if title == "RedSky" else f"RedSky - {title}"
    return page(heading, *children, subnav=menubar())


def need_connection(body: rx.Component) -> rx.Component:
    return rx.cond(
        RedskyState.has_active,
        body,
        rx.callout(
            rx.hstack(rx.text("No RedSky connection is set up yet."),
                      rx.link("Add one on the Credentials page", href="/credentials"), spacing="2"),
            icon="info", width="100%",
        ),
    )
