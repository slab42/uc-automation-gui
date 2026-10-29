import reflex as rx

from ..components.tool_widgets import code_block, csv_dropzone, field, paste_csv_tabs
from ..components.webex_nav import webex_page
from ..state.webex_tools import HardwareCompatState
from .webex_routing import need_login


def hardware_compatibility() -> rx.Component:
    S = HardwareCompatState
    results = rx.cond(
        S.checks.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.badge(S.valid_count.to_string() + " valid", color_scheme="green"),
                rx.badge(S.warning_count.to_string() + " warning(s)",
                         color_scheme=rx.cond(S.warning_count > 0, "amber", "gray")),
                rx.badge(S.invalid_count.to_string() + " invalid",
                         color_scheme=rx.cond(S.invalid_count > 0, "red", "gray")),
                rx.spacer(),
                rx.button(rx.icon("download", size=16), "Export", variant="soft", on_click=S.export_csv),
                align="center", spacing="2", width="100%",
            ),
            rx.card(
                rx.scroll_area(
                    rx.table.root(
                        rx.table.header(rx.table.row(
                            rx.table.column_header_cell("Row"), rx.table.column_header_cell("Model"),
                            rx.table.column_header_cell("MAC"), rx.table.column_header_cell("Status"),
                            rx.table.column_header_cell("Reason"))),
                        rx.table.body(rx.foreach(S.checks, lambda r: rx.table.row(
                            rx.table.cell(r["row"]), rx.table.cell(r["model"]), rx.table.cell(rx.code(r["mac"])),
                            rx.table.cell(rx.badge(r["status"], color_scheme=rx.match(
                                r["status"], ("VALID", "green"), ("WARNING", "amber"), "red"))),
                            rx.table.cell(r["reason"]),
                        ))),
                        variant="ghost", width="100%",
                    ),
                    max_height="55vh",
                ),
                padding="0", width="100%",
            ),
            spacing="3", align="start", width="100%",
        ),
        rx.fragment(),
    )
    return webex_page(
        "Check Hardware Compatibility",
        need_login(rx.vstack(
            rx.text("Checks that each phone model is supported for this org and that each MAC address is valid and "
                    "not already used in Webex, before you try to onboard the phones.",
                    size="2", color="var(--gray-11)"),
            rx.card(
                rx.vstack(
                    rx.heading("One phone", size="4"),
                    rx.grid(
                        field("Model", rx.fragment(
                            rx.input(value=S.form_model, width="100%", list="hardware-models", auto_complete="off",
                                     placeholder="Cisco 8845", on_change=lambda v: S.set_form("model", v)),
                            rx.el.datalist(rx.foreach(S.model_names, lambda n: rx.el.option(value=n)),
                                           id="hardware-models")),
                              "Click the field to see the supported models, or type to narrow the list."),
                        field("MAC address", rx.input(value=S.form_mac, width="100%",
                                                      placeholder="6C:74:AA:AA:AA:AA",
                                                      on_change=lambda v: S.set_form("mac", v)),
                              "Any separators are fine."),
                        columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                    ),
                    rx.button(rx.cond(S.checking, rx.spinner(size="2"), rx.icon("shield-check", size=16)), "Check",
                              on_click=S.check_single, disabled=S.checking),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Multiple phones", size="4"),
                    paste_csv_tabs(
                        S.paste_hardware, lambda v: S.set_paste("hardware", v),
                        "One phone per line: model, then mac, separated by a tab (straight from Excel), pipe, "
                        "semicolon or comma. A header row is optional.",
                        "Cisco 8865,6C74AAAAAAAA\nCisco 8845,AC7A594BBBBB",
                        rx.button(rx.cond(S.checking, rx.spinner(size="2"), rx.icon("shield-check", size=16)),
                                  "Check phones", on_click=S.check_text, disabled=S.checking),
                        [
                            rx.text("Header row skipped. Columns: model, then mac.", size="2",
                                    color="var(--gray-11)"),
                            code_block("model,mac\nCisco 8865,6C74AAAAAAAA\nCisco 8845,AC7A594BBBBB\n"),
                            csv_dropzone("hardware_upload"),
                            rx.button(rx.cond(S.checking, rx.spinner(size="2"), rx.icon("upload", size=16)),
                                      "Check phones",
                                      on_click=S.check_csv(rx.upload_files(upload_id="hardware_upload")),
                                      disabled=S.checking),
                        ],
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            results,
            spacing="4", align="start", width="100%",
        )),
    )
