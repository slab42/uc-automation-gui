"""Small pieces shared by the CUCM tool pages (not CRUD lists): CSV drop zone, run results table."""

import reflex as rx


def field(label: str, control: rx.Component, hint: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        rx.text(hint, size="1", color="var(--gray-10)") if hint else rx.fragment(),
        spacing="1", align="start", width="100%",
    )


def file_dropzone(upload_id: str, accept: dict, label: str) -> rx.Component:
    return rx.vstack(
        rx.upload(
            rx.vstack(
                rx.icon("upload", size=22, color="var(--gray-10)"),
                rx.text(label, size="2"),
                align="center", spacing="1",
            ),
            id=upload_id, accept=accept, max_files=1, multiple=False,
            padding="1.25rem", border="1px dashed var(--gray-7)", border_radius="var(--radius-3)", width="100%",
        ),
        rx.foreach(rx.selected_files(upload_id), lambda f: rx.badge(f, variant="soft")),
        spacing="2", align="start", width="100%",
    )


def csv_dropzone(upload_id: str) -> rx.Component:
    return file_dropzone(upload_id, {"text/csv": [".csv"]}, "Drop a CSV here or click to choose")


def paste_csv_tabs(paste_value, on_paste_change, paste_help: str, placeholder: str, paste_button: rx.Component,
                   csv_content: list) -> rx.Component:
    """Paste text (default) and CSV file tabs for a bulk input. csv_content is the existing CSV card body."""
    return rx.tabs.root(
        rx.tabs.list(
            rx.tabs.trigger("Paste text", value="text"),
            rx.tabs.trigger("CSV", value="csv"),
        ),
        rx.tabs.content(
            rx.vstack(
                rx.text(paste_help, size="2", color="var(--gray-11)"),
                rx.text_area(value=paste_value, on_change=on_paste_change, width="100%", rows="8",
                             placeholder=placeholder),
                paste_button,
                spacing="3", align="start", width="100%", padding_top="1rem",
            ),
            value="text",
        ),
        rx.tabs.content(
            rx.vstack(*csv_content, spacing="3", align="start", width="100%", padding_top="1rem"),
            value="csv",
        ),
        default_value="text", width="100%",
    )


def code_block(text: str) -> rx.Component:
    return rx.box(
        rx.el.pre(text, style={"margin": "0", "font_size": "12px", "font_family": "var(--code-font-family)"}),
        padding="0.75rem", background="var(--gray-3)", border_radius="var(--radius-3)",
        overflow_x="auto", width="100%",
    )


def run_results(S, item_header: str) -> rx.Component:
    """Progress line, OK/failed badges and the per-row table for a state with busy/progress/results."""
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
                rx.card(
                    rx.scroll_area(
                        rx.table.root(
                            rx.table.header(rx.table.row(
                                rx.table.column_header_cell(item_header),
                                rx.table.column_header_cell("Result"),
                                rx.table.column_header_cell("Detail"),
                            )),
                            rx.table.body(rx.foreach(S.results, lambda r: rx.table.row(
                                rx.table.cell(rx.code(r["key"])),
                                rx.table.cell(rx.badge(r["status"],
                                                       color_scheme=rx.cond(r["status"] == "OK", "green", "red"))),
                                rx.table.cell(r["detail"]),
                            ))),
                            variant="ghost", width="100%",
                        ),
                        max_height="50vh",
                    ),
                    padding="0", width="100%",
                ),
                spacing="2", align="start", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="3", align="start", width="100%",
    )


def confirm_dialog(S, title: str, description, action: str, on_confirm) -> rx.Component:
    """Red confirm dialog driven by S.confirm_open / S.set_confirm_open. `description` may be a Var."""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(title),
            rx.alert_dialog.description(description),
            rx.hstack(
                rx.button("Cancel", variant="soft", color_scheme="gray", on_click=S.set_confirm_open(False)),
                rx.button(action, color_scheme="red", on_click=on_confirm),
                spacing="3", justify="end", margin_top="1rem",
            ),
        ),
        open=S.confirm_open,
    )
