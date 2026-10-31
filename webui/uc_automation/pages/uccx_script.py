"""UCCX > Script Report."""

import reflex as rx

from ..components.search_input import search_input
from ..components.tool_widgets import file_dropzone, run_results
from ..components.uccx_nav import MIGRATE, uccx_page
from ..state.uccx_script import UccxScriptState

S = UccxScriptState
MUTED = "var(--gray-11)"


def _script_row(name) -> rx.Component:
    return rx.checkbox(name, checked=S.picked.contains(name), on_change=lambda on: S.toggle_pick(name, on))


def _stored_tab() -> rx.Component:
    return rx.vstack(
        rx.text(S.stored_note, size="2", color=MUTED),
        rx.cond(
            S.stored_scripts.length() > 0,
            rx.vstack(
                search_input(S.search, S.set_search, "Search scripts", width="100%"),
                rx.hstack(
                    rx.button("Select Shown", size="1", variant="soft", on_click=S.pick_shown),
                    rx.button("Clear", size="1", variant="soft", color_scheme="gray", on_click=S.clear_picked),
                    rx.text(S.picked_count.to_string() + " selected", size="2", color=MUTED),
                    align="center", spacing="2",
                ),
                rx.card(rx.scroll_area(rx.vstack(rx.foreach(S.visible_scripts, _script_row), spacing="2",
                                                 align="start"), max_height="40vh"), width="100%"),
                rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("file-search", size=16)), "Create Report",
                          on_click=S.report_picked, disabled=S.busy | (S.picked_count == 0)),
                spacing="3", align="start", width="100%",
            ),
            rx.link(rx.button("Go To Migrate", variant="soft"), href=MIGRATE),
        ),
        spacing="3", align="start", width="100%", padding_top="1rem",
    )


def _upload_tab() -> rx.Component:
    return rx.vstack(
        rx.upload(
            rx.vstack(rx.icon("upload", size=22, color="var(--gray-10)"),
                      rx.text("Drop .aef files here or click to choose", size="2"), align="center", spacing="1"),
            id="aef_upload", accept={"application/octet-stream": [".aef"]}, multiple=True,
            padding="1.25rem", border="1px dashed var(--gray-7)", border_radius="var(--radius-3)", width="100%",
        ),
        rx.foreach(rx.selected_files("aef_upload"), lambda f: rx.badge(f, variant="soft")),
        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("file-search", size=16)), "Create Report",
                  on_click=S.report_uploads(rx.upload_files(upload_id="aef_upload")), disabled=S.busy),
        spacing="3", align="start", width="100%", padding_top="1rem",
    )


def _report_row(name) -> rx.Component:
    return rx.hstack(
        rx.text(name, size="2"),
        rx.spacer(),
        rx.button("View", size="1", variant="soft", on_click=S.show(name)),
        rx.button(rx.icon("download", size=14), "Download", size="1", variant="soft", on_click=S.download_one(name)),
        align="center", width="100%",
    )


def _reports() -> rx.Component:
    return rx.cond(
        S.reports.length() > 0,
        rx.vstack(
            rx.hstack(rx.heading("Reports", size="4"), rx.spacer(),
                      rx.button(rx.icon("download", size=16), "Download All", variant="soft", on_click=S.download_all),
                      align="center", width="100%"),
            rx.card(rx.vstack(rx.foreach(S.reports, _report_row), spacing="2", width="100%"), width="100%"),
            rx.cond(
                S.preview_html != "",
                rx.el.iframe(src_doc=S.preview_html, sandbox="", style={"width": "100%", "height": "70vh",
                                                                       "border": "1px solid var(--gray-6)",
                                                                       "border_radius": "var(--radius-3)",
                                                                       "background": "white"}),
                rx.fragment(),
            ),
            spacing="3", align="start", width="100%",
        ),
        rx.fragment(),
    )


def script_report() -> rx.Component:
    return uccx_page(
        "Script Report",
        rx.vstack(
            rx.text("Reads UCCX scripts (.aef) and builds an HTML report of each: step types and properties in editor "
                    "order, variables with their values, labels and the author's comments. Nothing is sent anywhere "
                    "and nothing in the file is run.", size="2", color=MUTED),
            rx.card(
                rx.tabs.root(
                    rx.tabs.list(rx.tabs.trigger("Stored Download", value="stored"),
                                 rx.tabs.trigger("Upload", value="upload")),
                    rx.tabs.content(_stored_tab(), value="stored"),
                    rx.tabs.content(_upload_tab(), value="upload"),
                    default_value="stored", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "Script"),
            _reports(),
            spacing="4", align="start", width="100%",
        ),
        show_instance=False,
    )
