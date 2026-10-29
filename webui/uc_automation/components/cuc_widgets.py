"""Pieces shared by the CUC pages: result summary with failures only, simple data table."""

import reflex as rx


def failures(S, item_header: str) -> rx.Component:
    """Progress line, succeeded/failed badges and a table of only the failed items of a CucRun state."""
    return rx.vstack(
        rx.cond(S.busy, rx.hstack(rx.spinner(size="2"), rx.text(S.progress, size="2"), align="center", spacing="2"),
                rx.fragment()),
        rx.cond(
            S.results.length() > 0,
            rx.vstack(
                rx.hstack(
                    rx.badge(S.result_ok_count.to_string() + " succeeded", color_scheme="green"),
                    rx.badge(S.result_fail_count.to_string() + " failed",
                             color_scheme=rx.cond(S.result_fail_count > 0, "red", "gray")),
                    spacing="2",
                ),
                rx.cond(
                    S.failed_results.length() > 0,
                    rx.card(
                        rx.scroll_area(
                            rx.table.root(
                                rx.table.header(rx.table.row(
                                    rx.table.column_header_cell(item_header),
                                    rx.table.column_header_cell("Problem"),
                                )),
                                rx.table.body(rx.foreach(S.failed_results, lambda r: rx.table.row(
                                    rx.table.cell(rx.code(r["key"])),
                                    rx.table.cell(r["detail"]),
                                ))),
                                variant="ghost", width="100%",
                            ),
                            max_height="40vh",
                        ),
                        padding="0", width="100%",
                    ),
                    rx.fragment(),
                ),
                spacing="2", align="start", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="3", align="start", width="100%",
    )


def data_table(rows, columns: list[tuple[str, str]], max_height: str = "50vh") -> rx.Component:
    """columns: (row key, header). rows is a list[dict[str, str]] Var."""
    return rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for _k, h in columns])),
                rx.table.body(rx.foreach(rows, lambda r: rx.table.row(*[rx.table.cell(r[k]) for k, _h in columns]))),
                variant="ghost", width="100%",
            ),
            max_height=max_height,
        ),
        padding="0", width="100%",
    )


def hidden_note(count) -> rx.Component:
    return rx.cond(count > 0, rx.text("... and " + count.to_string() + " more (all are in the export)",
                                      size="1", color="var(--gray-10)"), rx.fragment())


def list_input_parts(S, paste_field: str, paste_value, upload_id: str, on_paste, on_csv, help_text: str,
                     placeholder: str, csv_help: str, button_label: str) -> tuple[rx.Component, rx.Component]:
    """(Paste text body, CSV body) for one list. on_paste is the state event, on_csv takes the uploaded files."""
    from .tool_widgets import csv_dropzone
    paste = rx.vstack(
        rx.text(help_text, size="2", color="var(--gray-11)"),
        rx.text_area(value=paste_value, on_change=lambda v: S.set_paste(paste_field, v), width="100%", rows="8",
                     placeholder=placeholder),
        rx.button(rx.icon("play", size=16), button_label, on_click=on_paste, disabled=S.busy),
        spacing="3", align="start", width="100%",
    )
    csv_body = rx.vstack(
        rx.text(csv_help, size="2", color="var(--gray-11)"),
        csv_dropzone(upload_id),
        rx.button(rx.icon("file-up", size=16), button_label, on_click=on_csv(rx.upload_files(upload_id=upload_id)),
                  disabled=S.busy),
        spacing="3", align="start", width="100%",
    )
    return paste, csv_body


def list_input(S, paste_field: str, paste_value, upload_id: str, on_paste, on_csv, help_text: str, placeholder: str,
               csv_help: str, button_label: str) -> rx.Component:
    """Paste text | CSV input tabs for one list."""
    paste, csv_body = list_input_parts(S, paste_field, paste_value, upload_id, on_paste, on_csv, help_text,
                                       placeholder, csv_help, button_label)
    return rx.tabs.root(
        rx.tabs.list(rx.tabs.trigger("Paste Text", value="text"), rx.tabs.trigger("CSV", value="csv")),
        rx.tabs.content(rx.box(paste, padding_top="1rem"), value="text"),
        rx.tabs.content(rx.box(csv_body, padding_top="1rem"), value="csv"),
        default_value="text", width="100%",
    )


def all_row(r, S, columns) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.checkbox(checked=S.selected.contains(r["objectId"]),
                                  on_change=lambda c: S.toggle_row(r["objectId"], c))),
        *[rx.table.cell(r[k]) for k, _h in columns],
    )


def all_rows_view(S, columns: list[tuple[str, str]], blurb: str, action: rx.Component,
                  footer: rx.Component | None = None, noun: str = "users",
                  placeholder: str = "Extension, alias or name", item_header: str = "User") -> rx.Component:
    """The All tab of a CUC page (state uses AllRows): load button, search, checkbox table.
    `action` is the toolbar button(s) for the selection."""
    return rx.vstack(
        rx.card(
            rx.vstack(
                rx.text(blurb, size="2", color="var(--gray-11)"),
                rx.button(rx.cond(S.all_loading, rx.spinner(size="2"), rx.icon("refresh-cw", size=16)),
                          rx.cond(S.all_rows.length() > 0, "Reload", "Load All"), on_click=S.load_all,
                          disabled=S.all_loading | S.busy),
                spacing="3", align="start", width="100%",
            ),
            size="3", width="100%",
        ),
        rx.cond(S.all_error != "", rx.callout(S.all_error, icon="triangle-alert", color_scheme="red", width="100%"),
                rx.fragment()),
        failures(S, item_header),
        rx.cond(
            S.all_rows.length() > 0,
            rx.vstack(
                rx.hstack(
                    rx.input(rx.input.slot(rx.icon("search", size=16)), placeholder=placeholder,
                             value=S.search, on_change=S.set_search, width="320px", max_width="100%"),
                    rx.select(["Contains", "Begins With"], value=S.search_mode, on_change=S.set_search_mode),
                    rx.spacer(),
                    rx.badge(S.selected_count.to_string() + " selected", variant="soft"),
                    action,
                    align="center", spacing="3", wrap="wrap", width="100%",
                ),
                rx.cond(S.all_failed > 0,
                        rx.callout(S.all_failed.to_string() + " user(s) could not be read. Details are in the log.",
                                   icon="triangle-alert", color_scheme="orange", width="100%"),
                        rx.fragment()),
                rx.card(
                    rx.scroll_area(
                        rx.table.root(
                            rx.table.header(rx.table.row(
                                rx.table.column_header_cell(
                                    rx.checkbox(checked=S.all_selected, on_change=S.toggle_all)),
                                *[rx.table.column_header_cell(h) for _k, h in columns],
                            )),
                            rx.table.body(rx.foreach(S.filtered_shown, lambda r: all_row(r, S, columns))),
                            variant="ghost", width="100%",
                        ),
                        max_height="60vh",
                    ),
                    padding="0", width="100%",
                ),
                rx.text("Showing " + S.filtered.length().to_string() + " " + noun + " on " + S.all_for
                        + ". The checkbox in the header selects everything the search shows.",
                        size="1", color="var(--gray-10)"),
                hidden_note(S.filtered_hidden),
                footer if footer is not None else rx.fragment(),
                spacing="3", align="start", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="4", align="start", width="100%",
    )
