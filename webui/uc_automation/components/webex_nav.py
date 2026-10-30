"""Webex section: top menu bar and page wrapper."""

import reflex as rx

from ..state.webex_routing import WebexSession
from .layout import page
from .org_picker import org_select

WEBEX_HOME = "/webex"
ADD_NUMBERS = "/webex/add-numbers"
CALL_FORWARD = "/webex/call-forward"
CALL_QUEUES = "/webex/call-queues"
HUNT_GROUPS = "/webex/hunt-groups"
VIRTUAL_LINES = "/webex/virtual-lines"
DELETE_USERS = "/webex/delete-users"
RESET_PIN = "/webex/reset-pin"
VOICEMAIL = "/webex/voicemail"
ADD_WORKSPACE = "/webex/add-workspace"
MIGRATE = "/webex/migrate"
SCHEDULES = "/webex/schedules"
E911 = "/webex/e911"
HARDWARE = "/webex/hardware-compatibility"

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
    ("Users", [
        ("Delete Users", DELETE_USERS, "user-x", "Delete users listed in a Control Hub CSV export."),
        ("Reset PIN", RESET_PIN, "key-round", "Reset the voicemail PIN of one user or of users in a CSV."),
    ]),
    ("Workspaces", [
        ("Add Device", ADD_WORKSPACE, "monitor-smartphone", "Add devices to workspaces by MAC address."),
        ("Migrate", MIGRATE, "arrow-right-left", "Move users to another location by phone number."),
    ]),
    ("Locations", [
        ("Schedules", SCHEDULES, "calendar-days",
         "Export, update, copy and clean up location holiday schedules."),
        ("E911", E911, "siren", "RedSky E911 status of every location, and opt-out."),
    ]),
    ("Tools", [
        ("Check Hardware Compatibility", HARDWARE, "shield-check",
         "Check phone models and MAC addresses against Webex before onboarding."),
    ]),
    ("Reports", [
        ("Voicemail", VOICEMAIL, "voicemail",
         "Show whether a user, or every user in a location, has an internal or external mailbox."),
    ]),
]


def _status() -> rx.Component:
    return rx.hstack(
        org_select(WebexSession),
        rx.cond(
            WebexSession.webex_org_names.length() > 0,
            rx.select(
                WebexSession.webex_org_names,
                value=WebexSession.webex_active,
                on_change=WebexSession.select_webex_org,
                size="1",
            ),
            rx.link(rx.button("Add an org", size="1", variant="soft"), href="/credentials"),
        ),
        rx.cond(
            WebexSession.webex_login != "",
            rx.badge("Login " + WebexSession.webex_login, variant="soft", color_scheme="gray"),
            rx.fragment(),
        ),
        rx.link(
            rx.cond(
                WebexSession.webex_ok,
                rx.badge("Logged in", color_scheme="green"),
                rx.badge("Login required", color_scheme="red"),
            ),
            href="/credentials",
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
        _status(),
        align="center",
        spacing="3",
        padding="0.4rem 1.5rem",
        background="var(--gray-2)",
        border_bottom="1px solid var(--gray-5)",
        width="100%",
    )


def webex_page(title: str, *children: rx.Component) -> rx.Component:
    heading = title if title == "Webex" else f"Webex - {title}"
    return page(heading, *children, subnav=menubar())
