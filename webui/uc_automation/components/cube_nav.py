"""CUBE section: top menu bar and page wrapper. Routers come from a pasted list or CSV, credentials from a saved set."""

import reflex as rx

from .layout import page
from .org_picker import org_select

CUBE_HOME = "/cube"
MEM_STATUS = "/cube/mem-status"
CONFIG_COMPARE = "/cube/config-compare"

# (menu label, [(item label, route, icon, description)])
GROUPS = [
    ("Health", [
        ("Mem Status", MEM_STATUS, "memory-stick",
         "Free memory of the control processor on each router, flagged when below a threshold."),
    ]),
    ("Configuration", [
        ("Config Compare", CONFIG_COMPARE, "file-diff",
         "Compare the voice sections of each running config to a template and get an HTML report."),
    ]),
]


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
        align="center",
        spacing="3",
        padding="0.4rem 1.5rem",
        background="var(--gray-2)",
        border_bottom="1px solid var(--gray-5)",
        width="100%",
    )


def cube_page(title: str, *children: rx.Component) -> rx.Component:
    heading = title if title == "CUBE" else f"CUBE - {title}"
    return page(heading, *children, subnav=menubar())


def cred_picker(S) -> rx.Component:
    """Credential set dropdown with an Enter Manually choice (username and password are asked here, never saved)."""
    return rx.vstack(
        org_select(S),
        rx.hstack(
            rx.text("Credentials", size="2", weight="medium"),
            rx.select(S.cred_options, value=S.cred_name, on_change=S.set_cred_name),
            rx.cond(
                S.cred_names.length() == 0,
                rx.link("Save a set on the Credentials page", href="/credentials", size="2"),
                rx.fragment(),
            ),
            align="center", spacing="3", wrap="wrap",
        ),
        rx.cond(
            S.is_manual,
            rx.hstack(
                rx.input(value=S.manual_username, on_change=S.set_manual_username, placeholder="Username",
                         auto_complete="off", width="220px"),
                rx.input(type="password", on_change=S.set_manual_password, placeholder="Password",
                         auto_complete="new-password", width="220px"),
                rx.text("Used for this run only. Not saved.", size="1", color="var(--gray-10)"),
                align="center", spacing="3", wrap="wrap",
            ),
            rx.fragment(),
        ),
        spacing="2", align="start", width="100%",
    )
