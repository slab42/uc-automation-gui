"""CUBE pages: home cards, Mem Status and Config Compare."""

import reflex as rx

from ..components.cube_nav import GROUPS, cred_picker, cube_page
from ..components.cuc_widgets import list_input_parts, hidden_note
from ..components.tool_widgets import code_block, file_dropzone, run_results
from ..state.cube_tools import ConfigCompareState, MemStatusState
from .cucm_home import _card

_ROUTER_HELP = ("Paste one router per line as router_ip, hostname (tab, pipe or comma separated). "
                "A header row is optional.")
_ROUTER_CSV_HELP = "Upload a CSV with the columns router_ip and hostname (same layout as _DATA/routers.csv)."
_ROUTER_PLACEHOLDER = "192.168.1.2, example-vg-8000v\n192.168.1.3, example-lgw"


def cube_home() -> rx.Component:
    return cube_page(
        "CUBE",
        rx.vstack(
            rx.text("Cisco Unified Border Element", color="var(--gray-11)"),
            *[
                rx.vstack(
                    rx.heading(label, size="4"),
                    rx.grid(
                        *[_card(icon, name, desc, route) for name, route, icon, desc in items],
                        columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                        spacing="4",
                        width="100%",
                    ),
                    spacing="3", align="start", width="100%",
                )
                for label, items in GROUPS
            ],
            spacing="4",
            align="start",
        ),
    )


def _router_tabs(S, upload_id: str, button: str) -> rx.Component:
    paste, csv_body = list_input_parts(S, "routers", S.paste_routers, upload_id, S.load_text, S.load_csv,
                                       _ROUTER_HELP, _ROUTER_PLACEHOLDER, _ROUTER_CSV_HELP, button)
    return rx.tabs.root(
        rx.tabs.list(rx.tabs.trigger("Paste Text", value="text"), rx.tabs.trigger("CSV", value="csv")),
        rx.tabs.content(rx.box(paste, padding_top="1rem"), value="text"),
        rx.tabs.content(rx.box(csv_body, padding_top="1rem"), value="csv"),
        default_value="text", width="100%",
    )


def _row_color(status):
    return rx.match(status, ("OK", "green"), ("Compliant", "green"), ("Low", "orange"), ("Variances", "orange"), "red")


def mem_status() -> rx.Component:
    S = MemStatusState
    table = rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell("Router"),
                    rx.table.column_header_cell("IP"),
                    rx.table.column_header_cell("Result"),
                    rx.table.column_header_cell("Free %"),
                    rx.table.column_header_cell("Memory"),
                )),
                rx.table.body(rx.foreach(S.rows, lambda r: rx.table.row(
                    rx.table.cell(r["hostname"]),
                    rx.table.cell(rx.code(r["ip"])),
                    rx.table.cell(rx.badge(r["status"], color_scheme=_row_color(r["status"]))),
                    rx.table.cell(r["free_pct"]),
                    rx.table.cell(rx.el.pre(r["memory"], style={"margin": "0", "font_size": "12px"})),
                ))),
                variant="ghost", width="100%",
            ),
            max_height="60vh",
        ),
        padding="0", width="100%",
    )
    return cube_page("Mem Status", rx.vstack(
        rx.card(
            rx.vstack(
                rx.text("Runs show platform software status control-processor br on each router and reads the "
                        "free memory percentage.", size="2", color="var(--gray-11)"),
                rx.hstack(
                    cred_picker(S),
                    rx.hstack(
                        rx.text("Low memory threshold (%)", size="2", weight="medium"),
                        rx.input(value=S.threshold, on_change=S.set_threshold, width="80px", type="number"),
                        align="center", spacing="2",
                    ),
                    spacing="5", align="center", wrap="wrap",
                ),
                _router_tabs(S, "mem_upload", "Check"),
                spacing="4", align="start", width="100%",
            ),
            size="3", width="100%",
        ),
        rx.cond(S.busy, rx.hstack(rx.spinner(size="2"), rx.text(S.progress, size="2"), align="center", spacing="2"),
                rx.fragment()),
        rx.cond(
            S.rows.length() > 0,
            rx.vstack(
                rx.hstack(
                    rx.badge(S.low_count.to_string() + " low", color_scheme=rx.cond(S.low_count > 0, "orange", "gray")),
                    rx.badge(S.result_fail_count.to_string() + " failed",
                             color_scheme=rx.cond(S.result_fail_count > 0, "red", "gray")),
                    rx.spacer(),
                    rx.button(rx.icon("download", size=16), "Export CSV", variant="soft", on_click=S.export_csv),
                    align="center", width="100%",
                ),
                table,
                spacing="3", align="start", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="4", align="start", width="100%",
    ))


def config_compare() -> rx.Component:
    S = ConfigCompareState
    template = rx.card(
        rx.vstack(
            rx.heading("Template", size="4"),
            rx.text("Voice configuration to compare against (voice class, voice-port, dial-peer and so on). Only the "
                    "sections in the template are checked.", size="2", color="var(--gray-11)"),
            rx.tabs.root(
                rx.tabs.list(rx.tabs.trigger("Paste Text", value="text"), rx.tabs.trigger("File", value="file")),
                rx.tabs.content(
                    rx.box(rx.text_area(value=S.template_text, on_change=S.set_template_text, width="100%", rows="12",
                                        placeholder="voice class codec 1\n  codec preference 1 g729",
                                        style={"font_family": "var(--code-font-family)"}), padding_top="1rem"),
                    value="text"),
                rx.tabs.content(
                    rx.box(rx.vstack(
                        file_dropzone("template_upload", {"text/plain": [".txt", ".EXAMPLE", ".cfg", ".conf"]},
                                      "Drop a template file here or click to choose"),
                        rx.button(rx.icon("file-up", size=16), "Load Template",
                                  on_click=S.load_template_file(rx.upload_files(upload_id="template_upload"))),
                        spacing="3", align="start", width="100%"), padding_top="1rem"),
                    value="file"),
                default_value="text", width="100%",
            ),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )
    routers = rx.card(
        rx.vstack(
            rx.heading("Routers", size="4"),
            cred_picker(S),
            _router_tabs(S, "compare_upload", "Compare"),
            spacing="4", align="start", width="100%",
        ),
        size="3", width="100%",
    )
    table = rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell("Router"),
                    rx.table.column_header_cell("IP"),
                    rx.table.column_header_cell("Result"),
                    rx.table.column_header_cell("Missing"),
                    rx.table.column_header_cell("Extra"),
                    rx.table.column_header_cell("Different"),
                    rx.table.column_header_cell("Detail"),
                )),
                rx.table.body(rx.foreach(S.rows, lambda r: rx.table.row(
                    rx.table.cell(r["hostname"]),
                    rx.table.cell(rx.code(r["ip"])),
                    rx.table.cell(rx.badge(r["status"], color_scheme=_row_color(r["status"]))),
                    rx.table.cell(r["missing"]),
                    rx.table.cell(r["extra"]),
                    rx.table.cell(r["different"]),
                    rx.table.cell(r["detail"]),
                ))),
                variant="ghost", width="100%",
            ),
            max_height="60vh",
        ),
        padding="0", width="100%",
    )
    return cube_page("Config Compare", rx.vstack(
        template,
        routers,
        rx.cond(S.busy, rx.hstack(rx.spinner(size="2"), rx.text(S.progress, size="2"), align="center", spacing="2"),
                rx.fragment()),
        rx.cond(
            S.rows.length() > 0,
            rx.vstack(
                rx.hstack(
                    rx.badge(S.report_count.to_string() + " report(s)", color_scheme="gray"),
                    rx.badge(S.result_fail_count.to_string() + " failed",
                             color_scheme=rx.cond(S.result_fail_count > 0, "red", "gray")),
                    rx.spacer(),
                    rx.button(rx.icon("download", size=16), "Export CSV", variant="soft", on_click=S.export_csv),
                    rx.button(rx.icon("download", size=16), "Download Reports", variant="soft",
                              on_click=S.download_reports, disabled=S.report_count == 0),
                    align="center", width="100%",
                ),
                table,
                spacing="3", align="start", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="4", align="start", width="100%",
    ))
