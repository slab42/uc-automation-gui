import reflex as rx
from reflex_base.style import set_color_mode

from ..components.layout import page
from ..config import APP_NAME, VERSION


def row(label: str, control: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.text(label, weight="medium"),
        rx.spacer(),
        control,
        align="center",
        width="100%",
        padding="0.75rem 0",
    )


def settings() -> rx.Component:
    return page(
        "Settings",
        rx.card(
            rx.vstack(
                row(
                    "Appearance",
                    rx.select(
                        ["system", "light", "dark"],
                        value=rx.color_mode,
                        on_change=set_color_mode,
                        width="9rem",
                    ),
                ),
                rx.divider(),
                row("Application", rx.text(APP_NAME, color="var(--gray-11)")),
                rx.divider(),
                row("Version", rx.badge(VERSION, variant="soft")),
                width="100%",
            ),
            size="3",
        ),
    )
