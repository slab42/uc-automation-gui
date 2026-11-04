import reflex as rx

from ..components.access import group_visible, show_if
from ..components.cucm_nav import GROUPS, IN_DEVELOPMENT, cucm_page
from ..state.settings import SettingsState

def _card(icon, title, desc, href):
    return rx.link(
        rx.card(
            rx.hstack(
                rx.icon(icon, size=20),
                rx.vstack(rx.text(title, weight="bold"), rx.text(desc, size="2", color="var(--gray-11)"),
                          spacing="0", align="start"),
                spacing="3", align="center",
            ),
            _hover={"border_color": "var(--accent-8)"},
            width="100%",
        ),
        href=href,
        underline="none",
    )


def _dev_gated(card: rx.Component, route: str) -> rx.Component:
    if route not in IN_DEVELOPMENT:
        return card
    return rx.cond(SettingsState.experimental == "1", card, rx.fragment())


def cucm_home() -> rx.Component:
    return cucm_page(
        "CUCM",
        rx.vstack(
            rx.text("Cisco Unified Communications Manager", color="var(--gray-11)"),
            *[
                rx.cond(group_visible([i[1] for i in items], IN_DEVELOPMENT), rx.vstack(
                    rx.heading(label, size="4"),
                    rx.grid(
                        *[show_if(route, _dev_gated(_card(icon, name, desc, route), route)) for name, route, icon, desc in items],
                        columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                        spacing="4",
                        width="100%",
                    ),
                    spacing="3", align="start", width="100%",
                ), rx.fragment())
                for label, items in GROUPS
            ],
            spacing="4",
            align="start",
        ),
    )
