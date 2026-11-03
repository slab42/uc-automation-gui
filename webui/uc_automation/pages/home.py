import reflex as rx

from ..components.access import allowed, platform_visible
from ..components.layout import page
from ..components.search_input import search_input
from ..config import APP_NAME, BUILD, PLATFORMS
from ..state.favorites import FavoritesState
from ..state.search import SearchState
from ..state.settings import SettingsState


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
    return rx.cond(
        allowed(r["route"]) & ((r["dev"] == "") | (SettingsState.experimental == "1")),
        _result_link(r),
        rx.fragment(),
    )


def _result_link(r) -> rx.Component:
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


def function_tile(r) -> rx.Component:
    return rx.cond(allowed(r["route"]), _function_tile(r), rx.fragment())


def _function_tile(r) -> rx.Component:
    return rx.link(
        rx.card(
            rx.hstack(
                rx.icon(r["icon"], size=18),
                rx.vstack(
                    rx.text(r["label"], weight="medium"),
                    rx.text(r["platform"] + " - " + r["section"], size="1", color="var(--gray-11)"),
                    spacing="0",
                    align="start",
                ),
                align="center",
                spacing="3",
                width="100%",
            ),
            width="100%",
            _hover={"border_color": "var(--accent-8)"},
        ),
        href=r["route"],
        underline="none",
        width="100%",
    )


def tile_column(title: str, items) -> rx.Component:
    return rx.vstack(
        rx.heading(title, size="4"),
        rx.cond(
            items.length() > 0,
            rx.vstack(rx.foreach(items, function_tile), spacing="2", width="100%"),
            rx.text("Nothing to show here.", size="2", color="var(--gray-11)"),
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def favorites_and_recent() -> rx.Component:
    return rx.grid(
        tile_column("Favorites", FavoritesState.favorite_items),
        tile_column("Recently Used", FavoritesState.recent_items),
        columns=rx.breakpoints(initial="1", sm="2"),
        spacing="6",
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
                        "Unified Communications automation for CUCM, Unity Connection, UCCX, "
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
            favorites_and_recent(),
            rx.cond(
                SettingsState.hide_platform_cards == "1",
                rx.fragment(),
                rx.grid(
                    *[rx.cond(platform_visible(p.slug), platform_card(p), rx.fragment()) for p in PLATFORMS],
                    columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                    spacing="4",
                    width="100%",
                ),
            ),
            rx.text(f"Build {BUILD}", size="1", color="var(--gray-9)"),
            spacing="6",
            align="start",
            width="100%",
        ),
    )
