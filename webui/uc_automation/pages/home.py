import reflex as rx

from ..components.layout import page
from ..config import APP_NAME, PLATFORMS, VERSION


def platform_card(p) -> rx.Component:
    return rx.link(
        rx.card(
            rx.vstack(
                rx.box(
                    rx.icon(p.icon, size=22),
                    padding="0.6rem",
                    border_radius="var(--radius-3)",
                    background="var(--accent-4)",
                    color="var(--accent-11)",
                ),
                rx.heading(p.label, size="4"),
                rx.text(p.description, size="2", color="var(--gray-11)"),
                rx.badge("Coming soon", variant="soft", color_scheme="gray"),
                align="start",
                spacing="2",
            ),
            size="3",
            width="100%",
            _hover={"border_color": "var(--accent-8)", "transform": "translateY(-2px)"},
            transition="all 0.15s ease",
        ),
        href=f"/{p.slug}",
        underline="none",
    )


def home() -> rx.Component:
    return page(
        "Home",
        rx.vstack(
            rx.hstack(
                rx.image(src="/slab42.jpg", width="72px", height="72px", border_radius="var(--radius-4)"),
                rx.vstack(
                    rx.heading(f"Welcome to {APP_NAME}", size="7"),
                    rx.text(
                        "Unified Communications automation for CUCM, Unity Connection, "
                        "CUBE, Webex and RedSky. Pick a platform to get started.",
                        color="var(--gray-11)",
                    ),
                    spacing="1",
                    align="start",
                ),
                spacing="4",
                align="center",
                wrap="wrap",
            ),
            rx.grid(
                *[platform_card(p) for p in PLATFORMS],
                columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                spacing="4",
                width="100%",
            ),
            rx.text(f"Version {VERSION}", size="1", color="var(--gray-9)"),
            spacing="6",
            align="start",
            width="100%",
        ),
    )
