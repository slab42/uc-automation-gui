import reflex as rx

from ..components.uccx_nav import GROUPS, uccx_page
from .cucm_home import _card


def uccx_home() -> rx.Component:
    return uccx_page(
        "UCCX",
        rx.vstack(
            rx.text("Cisco Unified Contact Center Express", color="var(--gray-11)"),
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
