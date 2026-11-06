"""RedSky section: top menu bar and page wrapper."""

import reflex as rx

from ..state.redsky import RedskyState
from ..state.settings import SettingsState
from .access import group_visible, show_if
from .layout import page
from .org_picker import instance_select, org_select

REDSKY_HOME = "/redsky"
BUILDINGS_ADD = "/redsky/buildings-add"
LOCATIONS_ADD = "/redsky/locations-add"
PRIMARY_LOCATION = "/redsky/primary-location"
IMPORT_PRECHECK = "/redsky/import-precheck"
ALERTS_ADD = "/redsky/alerts-add"
ALERTS_CHECK = "/redsky/alerts-check"
BSSID = "/redsky/bssid"
LLDP = "/redsky/lldp"
PRIVATE_IP = "/redsky/private-ip"
PUBLIC_IP = "/redsky/public-ip"
DUPLICATES = "/redsky/duplicate-buildings"
DUPLICATES_REMEDIATE = "/redsky/duplicates-remediate"
NO_LOCATIONS = "/redsky/no-locations"
NO_TRACKING = "/redsky/no-tracking"

# Routes still under development: shown only with the Experimental setting, with a badge
IN_DEVELOPMENT = {DUPLICATES_REMEDIATE}

# (menu label, [(item label, route, icon, description)])
GROUPS = [
    ("Buildings And Locations", [
        ("Add Buildings", BUILDINGS_ADD, "building-2", "Add Buildings to RedSky, one at a time or from a list."),
        ("Add Locations", LOCATIONS_ADD, "map-pin-plus", "Add Locations under a Building, one at a time or from a list."),
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
        ("Remediate Duplicate Buildings", DUPLICATES_REMEDIATE, "git-merge",
         "In development. Keep one Building per address: move the tracking of the duplicates to it, then delete them."),
    ]),
    ("Reports", [
        ("Check Primary Location Exists", PRIMARY_LOCATION, "circle-check",
         "Find Buildings that have no primary Location with a name you enter."),
        ("Find Duplicate Buildings", DUPLICATES, "copy",
         "Find Buildings that share an address, with their Location names, as an Excel report."),
        ("Find Buildings Without Locations", NO_LOCATIONS, "building",
         "List Buildings that have no Locations."),
        ("Find Locations Without Device Tracking", NO_TRACKING, "radar",
         "List Locations with no static MAC, LLDP, BSSID or Private IP range."),
    ]),
]


def _connection_picker() -> rx.Component:
    return rx.hstack(
        org_select(RedskyState),
        rx.cond(
            RedskyState.has_active,
            instance_select(RedskyState.connection_names, RedskyState.active, RedskyState.select_active),
            rx.link(rx.button("Add a connection", size="1", variant="soft"), href="/credentials?tab=redsky"),
        ),
        align="center",
        spacing="2",
    )


def _menu_item(name: str, route: str) -> rx.Component:
    if route not in IN_DEVELOPMENT:
        return rx.menu.item(name, on_click=rx.redirect(route))
    return rx.cond(
        SettingsState.experimental == "1",
        rx.menu.item(
            rx.hstack(name, rx.badge("In Development", color_scheme="amber", size="1"), align="center", spacing="2"),
            on_click=rx.redirect(route)),
        rx.fragment(),
    )


def menubar() -> rx.Component:
    return rx.hstack(
        *[
            rx.cond(group_visible([i[1] for i in items], IN_DEVELOPMENT), rx.menu.root(
                rx.menu.trigger(rx.button(label, rx.icon("chevron-down", size=15), variant="ghost", size="2")),
                rx.menu.content(
                    *[show_if(route, _menu_item(name, route)) for name, route, _icon, _desc in items],
                ),
            ), rx.fragment())
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
                      rx.link("Add one on the Credentials page", href="/credentials?tab=redsky"), spacing="2"),
            icon="info", width="100%",
        ),
    )
