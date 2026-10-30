import reflex as rx
from reflex_base.style import set_color_mode

from ..components.layout import page
from ..config import APP_NAME, VERSION
from ..state.settings import SettingsState as S


def row(label: str, control: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.text(label, weight="medium"),
        rx.spacer(),
        control,
        align="center",
        width="100%",
        padding="0.75rem 0",
    )


def _log_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Log Retention", size="4"),
            rx.text("Old logs are deleted automatically. Set a limit to 0 to turn it off.",
                    size="2", color="var(--gray-11)"),
            row("Delete Logs Older Than (Days)",
                rx.input(value=S.retention_days, on_change=S.set_retention_days, type="number", min="0", width="9rem")),
            rx.divider(),
            row("Keep All Logs Under (MB)",
                rx.input(value=S.max_mb, on_change=S.set_max_mb, type="number", min="0", width="9rem")),
            rx.hstack(
                rx.button("Save", on_click=S.save_log_settings),
                rx.button("Defaults", variant="soft", color_scheme="gray", on_click=S.reset_log_settings),
                spacing="3",
            ),
            width="100%",
        ),
        size="3",
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
        _log_card(),
    )
