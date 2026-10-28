"""Placeholder page for a platform. Replace with real features as scripts are ported."""

import reflex as rx

from ..components.layout import page
from ..config import Platform


def platform_page(p: Platform):
    def render() -> rx.Component:
        return page(
            p.label,
            rx.center(
                rx.vstack(
                    rx.icon(p.icon, size=40, color="var(--accent-9)"),
                    rx.heading(p.description, size="5", align="center"),
                    rx.text(
                        "No features yet. Functionality from the CLI scripts will be ported here.",
                        color="var(--gray-11)",
                        align="center",
                    ),
                    align="center",
                    spacing="3",
                ),
                padding="4rem 1rem",
                border="1px dashed var(--gray-6)",
                border_radius="var(--radius-4)",
                width="100%",
            ),
        )

    render.__name__ = f"{p.slug}_page"
    return render
