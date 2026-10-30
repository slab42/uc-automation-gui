"""Tools platform home: cards for the utilities that work across platforms."""

import reflex as rx

from ..components.layout import page
from ..components.tools_nav import TOOLS
from .cucm_home import _card


def tools_home() -> rx.Component:
    return page(
        "Tools",
        rx.vstack(
            rx.text("Utilities (log search, etc.)", color="var(--gray-11)"),
            rx.grid(
                *[_card(icon, name, desc, route) for name, route, icon, desc in TOOLS],
                columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                spacing="4",
                width="100%",
            ) if TOOLS else rx.text("No tools yet.", size="2", color="var(--gray-11)"),
            spacing="4", align="start", width="100%",
        ),
    )
