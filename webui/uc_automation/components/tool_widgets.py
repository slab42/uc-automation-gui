"""Small pieces shared by the CUCM tool pages (not CRUD lists): CSV drop zone, run results table."""

import reflex as rx


def field(label: str, control: rx.Component, hint: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        rx.text(hint, size="1", color="var(--gray-10)") if hint else rx.fragment(),
        spacing="1", align="start", width="100%",
    )


def csv_dropzone(upload_id: str) -> rx.Component:
    return rx.vstack(
        rx.upload(
            rx.vstack(
                rx.icon("upload", size=22, color="var(--gray-10)"),
                rx.text("Drop a CSV here or click to choose", size="2"),
                align="center", spacing="1",
            ),
            id=upload_id, accept={"text/csv": [".csv"]}, max_files=1, multiple=False,
            padding="1.25rem", border="1px dashed var(--gray-7)", border_radius="var(--radius-3)", width="100%",
        ),
        rx.foreach(rx.selected_files(upload_id), lambda f: rx.badge(f, variant="soft")),
        spacing="2", align="start", width="100%",
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
