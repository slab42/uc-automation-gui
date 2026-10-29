"""CUCM section: top menu bar and page wrapper."""

import reflex as rx

from ..state.cucm import CucmState
from .layout import page

CUCM_HOME = "/cucm"
ADVERTISED_PATTERNS = "/cucm/advertised-patterns"
PARTITIONS = "/cucm/partitions"
CSS = "/cucm/calling-search-spaces"
PICKUP_GROUPS = "/cucm/call-pickup-groups"
HUNT_GROUPS = "/cucm/hunt-groups"
ROUTE_PATTERNS = "/cucm/route-patterns"
TRANSLATION_PATTERNS = "/cucm/translation-patterns"
CTI_ROUTE_POINTS = "/cucm/cti-route-points"
CODEC_LISTS = "/cucm/audio-codec-preference-lists"
DEVICE_POOLS = "/cucm/device-pools"
LOCATIONS = "/cucm/locations"
REGIONS = "/cucm/regions"
DN_MOVE = "/cucm/dn-move-partition"
DN_ALT = "/cucm/dn-alternate-numbers"
DN_ORPHANS = "/cucm/dn-orphans"
EM_BULK = "/cucm/em-bulk-login"
PHONE_COUNT = "/cucm/phone-count-by-dp"
SET_PIN = "/cucm/set-user-pin"

# (menu label, [(item label, route, icon, description)])
GROUPS = [
    ("System", [
        ("Audio Codec Preference Lists", CODEC_LISTS, "audio-lines", "Codec preference lists: search, add, import, export, remove."),
        ("Device Pools", DEVICE_POOLS, "boxes", "Device pools: search, add, import, export, check dependencies, remove."),
        ("Locations", LOCATIONS, "map-pin", "Locations and their bandwidth: check dependencies, remove."),
        ("Regions", REGIONS, "globe", "Regions: check dependencies, remove."),
    ]),
    ("Call Routing", [
        ("Advertised Patterns", ADVERTISED_PATTERNS, "route", "Hosted DN patterns: search, add, import, export, remove."),
        ("Partitions", PARTITIONS, "layers", "Route partitions: search, add, import, export, remove."),
        ("Calling Search Spaces", CSS, "list-ordered", "CSSs and their ordered partitions."),
        ("Route Patterns", ROUTE_PATTERNS, "signpost", "Route patterns: search, add, import, export, find duplicates, remove."),
        ("Translation Patterns", TRANSLATION_PATTERNS, "replace", "Translation patterns: search, add, import, export, remove."),
        ("Hunt Groups", HUNT_GROUPS, "users-round", "Hunt pilots with their hunt lists and line groups: check dependencies, remove."),
        ("Call Pickup Groups", PICKUP_GROUPS, "users", "Call pickup groups: search, add, import, export, check dependencies, remove."),
    ]),
    ("Directory Numbers", [
        ("Move Partition", DN_MOVE, "folder-input", "Move directory numbers to another route partition."),
        ("Alternate Numbers", DN_ALT, "phone-forwarded", "Find DNs with alternate numbers and remove them."),
        ("Orphans", DN_ORPHANS, "ghost", "Directory numbers not assigned to any device: search, export, remove."),
    ]),
    ("Devices", [
        ("Phones", "/cucm/phones", "tablet-smartphone", "Phones: search, add, import, export, remove."),
        ("CTI Route Points", CTI_ROUTE_POINTS, "workflow", "CTI route points: search, add, import, export, remove with their orphaned DNs."),
        ("Softkey Templates", "/cucm/softkey-templates", "keyboard", "Softkey templates."),
        ("Common Device Configs", "/cucm/common-device-configs", "settings-2", "Common device configurations."),
        ("Phone Button Templates", "/cucm/phone-button-templates", "grid-3x3", "Phone button templates."),
        ("Physical Phones (MPP)", "/cucm/mpp-phones", "refresh-cw", "Migrate 78xx/88xx phones to MPP firmware or prep them for Webex Calling."),
    ]),
    ("Tools", [
        ("EM Bulk Login", EM_BULK, "log-in", "Log Extension Mobility users in or out, or check sessions, from a CSV."),
        ("Phone Count by DP", PHONE_COUNT, "chart-column", "Count phones per device pool and export the result."),
        ("Set User PIN", SET_PIN, "key-round", "Set Extension Mobility PINs for one user or from a CSV."),
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
    heading = title if title == "CUCM" else f"CUCM - {title}"
    return page(heading, *children, subnav=menubar(on_connection_change))
