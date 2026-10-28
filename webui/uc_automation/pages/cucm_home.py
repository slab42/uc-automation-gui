import reflex as rx

from ..components.cucm_nav import GROUPS, cucm_page

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


def cucm_home() -> rx.Component:
    return cucm_page(
        "CUCM",
        rx.vstack(
            rx.text("Cisco Unified Communications Manager", color="var(--gray-11)"),
            *[
                rx.vstack(
                    rx.heading(label, size="4"),
                    rx.grid(
                        *[_card(icon, name, desc, route) for name, route, icon, desc in items],
                        columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                        spacing="4",
                        width="100%",
                    ),
                    spacing="3", align="start", width="100%",
                )
                for label, items in GROUPS
            ],
            spacing="4",
            align="start",
        ),
    )
