import reflex as rx

from ..components.layout import page
from ..components.search_input import search_input
from ..config import APP_NAME, PLATFORMS, VERSION
from ..state.search import SearchState


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
                rx.fragment() if p.available else rx.badge("Coming soon", variant="soft", color_scheme="gray"),
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


def result_row(r) -> rx.Component:
    return rx.link(
        rx.card(
            rx.hstack(
                rx.vstack(
                    rx.text(r["label"], weight="medium"),
                    rx.text(r["description"], size="2", color="var(--gray-11)"),
                    spacing="1",
                    align="start",
                ),
                rx.spacer(),
                rx.badge(r["platform"], color_scheme="blue"),
                rx.badge(r["section"], variant="soft", color_scheme="gray"),
                align="center",
                spacing="2",
                width="100%",
            ),
            width="100%",
            _hover={"border_color": "var(--accent-8)"},
        ),
        href=r["route"],
        underline="none",
        width="100%",
    )


def search_box() -> rx.Component:
    return rx.vstack(
        search_input(
            SearchState.query,
            SearchState.set_query,
            "Search all platforms...",
            size="3",
            width="100%",
        ),
        rx.cond(
            SearchState.searching,
            rx.cond(
                SearchState.results.length() > 0,
                rx.vstack(rx.foreach(SearchState.results, result_row), spacing="2", width="100%"),
                rx.text("No matches.", color="var(--gray-11)"),
            ),
        ),
        spacing="3",
        width="100%",
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
            search_box(),
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
