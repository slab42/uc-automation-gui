import reflex as rx

from ..components.layout import page
from ..components.search_input import search_input
from ..state.logs import LogsState as S


def _row(item) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.checkbox(checked=S.selected.contains(item["name"]),
                        on_change=lambda c: S.toggle_row(item["name"], c)),
            width="40px",
        ),
        rx.table.cell(rx.link(item["when"], on_click=S.open_log(item["name"]), cursor="pointer")),
        rx.table.cell(rx.link(rx.code(item["what"]), on_click=S.open_log(item["name"]), cursor="pointer")),
        rx.table.cell(item["size"]),
    )


def _table() -> rx.Component:
    return rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell(rx.checkbox(checked=S.all_selected, on_change=S.toggle_all),
                                                width="40px"),
                    rx.table.column_header_cell("Date and time"),
                    rx.table.column_header_cell("Operation"),
                    rx.table.column_header_cell("Size"),
                )),
                rx.table.body(rx.foreach(S.shown, _row)),
                variant="ghost",
                width="100%",
            ),
            max_height="65vh",
        ),
        padding="0",
        width="100%",
    )


def _toolbar() -> rx.Component:
    return rx.hstack(
        search_input(
            S.search,
            S.set_search,
            "Search names and contents",
            debounce_timeout=300,
            width="320px",
            max_width="100%",
        ),
        rx.text(
            rx.cond(
                S.parser_mode,
                S.parser_lines.length().to_string() + " entries",
                rx.cond(S.search != "", S.items.length().to_string() + " matching",
                        S.items.length().to_string() + " total"),
            ),
            size="2", color="var(--gray-11)",
        ),
        rx.spacer(),
        rx.hstack(
            rx.switch(checked=S.parser_mode, on_change=S.set_parser_mode),
            rx.text("Parser mode", size="2"),
            align="center", spacing="2",
        ),
        rx.icon_button(rx.icon("refresh-cw", size=16), variant="soft", on_click=S.refresh, loading=S.loading,
                       title="Reload"),
        rx.cond(
            S.parser_mode,
            rx.fragment(),
            rx.button(rx.icon("download", size=16), "Export selected (", S.selected_count.to_string(), ")",
                      disabled=S.selected_count == 0, on_click=S.export_selected),
        ),
        align="center", spacing="3", wrap="wrap", width="100%",
    )


def _reader() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(S.viewing),
            rx.vstack(
                rx.cond(
                    S.view_truncated,
                    rx.callout("Only the last 1000 lines are shown. Export the log to get all of it.",
                               icon="info", size="1", width="100%"),
                    rx.fragment(),
                ),
                rx.scroll_area(
                    rx.el.pre(S.view_text, style={"margin": "0", "font_size": "12px",
                                                  "font_family": "var(--code-font-family)",
                                                  "white-space": "pre-wrap", "word-break": "break-word"}),
                    padding="0.75rem", background="var(--gray-3)", border_radius="var(--radius-3)",
                    max_height="60vh", width="100%",
                ),
                rx.hstack(
                    rx.button(rx.icon("download", size=16), "Export", variant="soft", on_click=S.export_viewing),
                    rx.spacer(),
                    rx.button("Close", variant="soft", color_scheme="gray", on_click=S.close_log),
                    width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
            max_width="900px",
        ),
        open=S.viewing != "",
        on_open_change=lambda _o: S.close_log(),
    )


def _parser() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text("The last 200 log entries", rx.cond(S.search != "", " containing the search text", ""),
                    ", oldest first.", size="1", color="var(--gray-10)"),
            rx.spacer(),
            rx.button(rx.icon("copy", size=15), "Copy", variant="soft", size="1",
                      disabled=S.parser_lines.length() == 0,
                      on_click=[rx.set_clipboard(S.parser_text), rx.toast.success("Copied to clipboard")]),
            align="center", width="100%",
        ),
        rx.cond(
            S.parser_lines.length() == 0,
            rx.callout("No matching entries.", icon="info", width="100%"),
            rx.scroll_area(
                rx.el.pre(S.parser_text, style={"margin": "0", "font_size": "12px",
                                                "font_family": "var(--code-font-family)",
                                                "white-space": "pre-wrap", "word-break": "break-word"}),
                padding="0.75rem", background="var(--gray-3)", border_radius="var(--radius-3)",
                max_height="65vh", width="100%",
            ),
        ),
        spacing="2", align="start", width="100%",
    )


def logs() -> rx.Component:
    return page(
        "Logs",
        rx.vstack(
            _toolbar(),
            rx.cond(
                S.parser_mode,
                _parser(),
                rx.cond(
                    S.loading & (S.items.length() == 0),
                    rx.center(rx.spinner(size="3"), padding="3rem", width="100%"),
                    rx.cond(
                        S.items.length() == 0,
                        rx.callout("No logs found.", icon="info", width="100%"),
                        _table(),
                    ),
                ),
            ),
            rx.cond(
                ~S.parser_mode & (S.hidden_count > 0),
                rx.text("Showing the newest 500 logs. ", S.hidden_count.to_string(),
                        " more match; refine the search to see them. Select-all covers every match.",
                        size="1", color="var(--gray-10)"),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        ),
        _reader(),
    )
