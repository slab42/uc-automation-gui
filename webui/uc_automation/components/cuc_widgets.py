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
