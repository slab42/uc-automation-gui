"""Webex section: top menu bar and page wrapper."""

import reflex as rx

from ..state.settings import SettingsState
from ..state.webex_routing import WebexSession
from ..state.webex_token import WebexTokenState
from .access import group_visible, show_if
from .layout import page
from .org_picker import instance_select, org_select

WEBEX_HOME = "/webex"
ADD_NUMBERS = "/webex/add-numbers"
CALL_FORWARD = "/webex/call-forward"
CALL_QUEUES = "/webex/call-queues"
HUNT_GROUPS = "/webex/hunt-groups"
VIRTUAL_LINES = "/webex/virtual-lines"
DELETE_USERS = "/webex/delete-users"
RESET_PIN = "/webex/reset-pin"
VOICEMAIL = "/webex/voicemail"
CREATE_WORKSPACE = "/webex/create-workspace"
ADD_WORKSPACE = "/webex/add-workspace"
COPY_WORKSPACE = "/webex/copy-workspace"
UPGRADE_LICENSE = "/webex/upgrade-license"
GET_WORKSPACE = "/webex/get-workspace"
BULK_ATA = "/webex/bulk-ata"
DEVICE_MIGRATE = "/webex/webex-phone-migrate"
CUCM_MIGRATE = "/webex/cucm-phone-migrate"
CUCM_GATEWAY = "/webex/cucm-gateway-migrate"
MIGRATE = "/webex/migrate"
SCHEDULES = "/webex/schedules"
E911 = "/webex/e911"
MIGRATE_PSTN = "/webex/migrate-pstn"
COPY_LOCATION = "/webex/copy-location"
HARDWARE = "/webex/hardware-compatibility"
NAMING = "/webex/naming-check"
LOCATIONS_REPORT = "/webex/locations-report"

# Routes still under development: the menu item shows a badge
IN_DEVELOPMENT = {NAMING, CUCM_MIGRATE, COPY_LOCATION}

# (menu label, [(item label, route, icon, description)])
GROUPS = [
    ("Call Routing", [
        ("Add Numbers", ADD_NUMBERS, "hash", "Add PSTN numbers to a location, one at a time or from a CSV."),
        ("Call Forward", CALL_FORWARD, "phone-forwarded",
         "Set or remove Call Forward All on any number, one at a time or from a CSV."),
        ("Call Queues", CALL_QUEUES, "headset", "Create call queues from a CSV, or replace a queue's agents."),
        ("Hunt Groups", HUNT_GROUPS, "users-round",
         "Create hunt groups from a CSV, replace agents, or migrate a hunt group to a call queue."),
        ("Virtual Lines", VIRTUAL_LINES, "voicemail", "Upload a busy and unanswered voicemail greeting."),
    ]),
    ("Locations", [
        ("Schedules", SCHEDULES, "calendar-days",
         "Export, update, copy and clean up location holiday schedules."),
        ("E911", E911, "siren", "RedSky E911 status of every location, and opt-out."),
        ("Copy Location", COPY_LOCATION, "copy",
         "In development. Create a new location from an existing one: time zone, languages, address, calling settings and schedules."),
        ("Migrate PSTN", MIGRATE_PSTN, "phone-call", "Move a location to a different PSTN trunk, route group or cloud connection."),
    ]),
    ("Users", [
        ("Delete Users", DELETE_USERS, "user-x", "Delete users listed in a Control Hub CSV export."),
        ("Migrate", MIGRATE, "arrow-right-left", "Move users to another location by phone number."),
        ("Reset PIN", RESET_PIN, "key-round", "Reset the voicemail PIN of one user or of users in a CSV."),
    ]),
    ("Workspaces", [
        ("Add Workspace", CREATE_WORKSPACE, "square-plus",
         "Create one workspace, or many from pasted text or a CSV."),
        ("Copy Workspace", COPY_WORKSPACE, "copy",
         "Create workspaces that copy the type, capacity and notes of an existing workspace."),
        ("Get Workspace", GET_WORKSPACE, "search",
         "Show a workspace's location, calling license, number and every calling setting."),
        ("Upgrade Calling License", UPGRADE_LICENSE, "badge-check",
         "Upgrade workspaces from the Common Area Workspace to the Professional Workspace license."),
        ("Add Device", ADD_WORKSPACE, "monitor-smartphone", "Add devices to workspaces by MAC address."),
    ]),
    ("Devices", [
        ("Bulk ATA/VG", BULK_ATA, "cable",
         "Add an ATA or voice gateway with a workspace on every port."),
        ("Webex-Webex Phone Migrate", DEVICE_MIGRATE, "arrow-right-left",
         "Move a physical phone from one Webex org to another."),
        ("CUCM-Webex Phone Migrate", CUCM_MIGRATE, "arrow-right-left",
         "Move a physical phone between CUCM and Webex."),
        ("CUCM-Webex Analog Gateway Migrate", CUCM_GATEWAY, "cable",
         "Move a CUCM analog gateway to Webex: a workspace for port 1 or more ports, and the device now or later."),
    ]),
    ("Tools", [
        ("Check Hardware Compatibility", HARDWARE, "shield-check",
         "Check phone models and MAC addresses against Webex before onboarding."),
        ("Naming Check", NAMING, "spell-check",
         "In development. Validate item names against a regex per type, and rename the ones that fail."),
    ]),
    ("Reports", [
        ("Voicemail", VOICEMAIL, "voicemail",
         "Show whether a user, or every user in a location, has an internal or external mailbox."),
        ("Locations Report", LOCATIONS_REPORT, "map-pin",
         "Count the users and workspaces with Webex Calling enabled in every location."),
    ]),
]


def _status(show_org: bool = True) -> rx.Component:
    return rx.hstack(
        rx.cond(
            WebexTokenState.use_personal,
            rx.tooltip(
                rx.badge("Personal Token", color_scheme="amber", cursor="pointer", on_click=WebexTokenState.switch_back),
                content="Webex tasks use your personal token. Click to use the org login again.",
            ),
        ),
        *([
            org_select(WebexSession),
            rx.cond(
                WebexSession.webex_org_names.length() > 0,
                instance_select(WebexSession.webex_org_names, WebexSession.webex_active, WebexSession.select_webex_org),
                rx.link(rx.button("Add an org", size="1", variant="soft"), href="/credentials?tab=webex"),
            ),
        ] if show_org else []),
        *([
            rx.link(
                rx.cond(
                    WebexSession.webex_ok,
                    rx.tooltip(
                        rx.badge("Logged in", color_scheme="green"),
                        content="Login " + WebexSession.webex_login,
                        disabled=WebexSession.webex_login == "",
                    ),
                    rx.badge("Login required", color_scheme="red"),
                ),
                href="/credentials?tab=webex",
            ),
        ] if show_org else []),
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


def menubar(show_org: bool = True) -> rx.Component:
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
        _status(show_org),
        align="center",
        spacing="3",
        padding="0.4rem 1.5rem",
        background="var(--gray-2)",
        border_bottom="1px solid var(--gray-5)",
        width="100%",
    )


def webex_page(title: str, *children: rx.Component, show_org: bool = True) -> rx.Component:
    heading = title if title == "Webex" else f"Webex - {title}"
    # Hidden ticker: after a task got a 403, offers the personal token (WebexSession.poll_denied)
    ticker = rx.box(rx.moment(interval=3000, on_change=WebexSession.poll_denied), display="none")
    return page(heading, ticker, *children, subnav=menubar(show_org))
