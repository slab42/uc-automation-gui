"""App shell: sidebar, top bar and the page wrapper."""

import reflex as rx

from ..config import APP_NAME, PLATFORMS, VERSION

SIDEBAR_WIDTH = "264px"


def nav_item(label: str, href: str, icon: str) -> rx.Component:
    active = rx.State.router.page.path == href
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=18),
            rx.text(label, size="3", weight="medium"),
            align="center",
            spacing="3",
            width="100%",
            padding="0.55rem 0.75rem",
            border_radius="var(--radius-3)",
            background=rx.cond(active, "var(--accent-4)", "transparent"),
            color=rx.cond(active, "var(--accent-11)", "var(--gray-11)"),
            _hover={"background": rx.cond(active, "var(--accent-4)", "var(--gray-3)")},
        ),
        href=href,
        underline="none",
        width="100%",
    )


def nav_heading(text: str) -> rx.Component:
    return rx.text(
        text,
        size="1",
        weight="bold",
        color="var(--gray-9)",
        style={"text-transform": "uppercase", "letter-spacing": "0.08em"},
        padding="0.9rem 0.75rem 0.3rem",
    )


def sidebar() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.link(
                rx.hstack(
                    rx.image(
                        src="/slab42.jpg",
                        width="36px",
                        height="36px",
                        border_radius="var(--radius-3)",
                    ),
                    rx.text(APP_NAME, size="3", weight="bold", color="var(--gray-12)"),
                    align="center",
                    spacing="3",
                ),
                href="/",
                underline="none",
                padding="0.25rem 0.5rem 0.75rem",
            ),
            nav_item("Home", "/", "house"),
            nav_heading("Platforms"),
            *[nav_item(p.label, f"/{p.slug}", p.icon) for p in PLATFORMS],
            rx.spacer(),
            rx.divider(),
            nav_item("Logs", "/logs", "scroll-text"),
            nav_item("Credentials", "/credentials", "key-round"),
            nav_item("Settings", "/settings", "settings"),
            rx.text(f"v{VERSION}", size="1", color="var(--gray-9)", padding="0.25rem 0.75rem"),
            spacing="1",
            align="start",
            height="100%",
            width="100%",
        ),
        position="fixed",
        top="0",
        left="0",
        height="100vh",
        width=SIDEBAR_WIDTH,
        padding="1rem 0.75rem",
        background="var(--gray-2)",
        border_right="1px solid var(--gray-5)",
        display=rx.breakpoints(initial="none", md="block"),
        z_index="10",
    )


def topbar(title: str) -> rx.Component:
    return rx.hstack(
        rx.heading(title, size="5"),
        rx.spacer(),
        rx.badge(f"v{VERSION}", variant="soft", radius="full"),
        rx.color_mode.button(variant="ghost", size="2"),
        align="center",
        spacing="3",
        padding="0.75rem 1.5rem",
        position="sticky",
        top="0",
        z_index="5",
        background="color-mix(in srgb, var(--color-background) 85%, transparent)",
        backdrop_filter="blur(8px)",
        border_bottom="1px solid var(--gray-5)",
        width="100%",
    )


def page(title: str, *children: rx.Component, subnav: rx.Component | None = None) -> rx.Component:
    return rx.box(
        sidebar(),
        rx.box(
            topbar(title),
            subnav if subnav is not None else rx.fragment(),
            rx.box(*children, padding="1.5rem", max_width="1100px", margin="0 auto"),
            margin_left=rx.breakpoints(initial="0", md=SIDEBAR_WIDTH),
            min_height="100vh",
        ),
    )
