import reflex as rx

from ..components.cucm_nav import cucm_page
from ..components.search_input import search_input
from ..state.cucm_reports import DeviceReportState
from .tools import _need_connection


def device_report() -> rx.Component:
    S = DeviceReportState
    table = rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell("Device Pool"),
                    rx.cond(S.grouping != "Off", rx.table.column_header_cell("Pools", justify="end"), rx.fragment()),
                    rx.table.column_header_cell("Registered", justify="end"),
                    rx.table.column_header_cell("Unregistered", justify="end"),
                    rx.table.column_header_cell("Total Devices", justify="end"),
                    rx.table.column_header_cell("Gateways", justify="end"),
                )),
                rx.table.body(
                    rx.foreach(S.report_rows, lambda x: rx.table.row(
                        rx.table.cell(x["devicePool"]),
                        rx.cond(S.grouping != "Off", rx.table.cell(x["pools"], justify="end"), rx.fragment()),
                        rx.table.cell(x["registered"], justify="end"),
                        rx.table.cell(x["unregistered"], justify="end"),
                        rx.table.cell(x["total"], justify="end"),
                        rx.table.cell(x["gateways"], justify="end"),
                    )),
                    rx.table.row(
                        rx.table.row_header_cell("Total"),
                        rx.cond(S.grouping != "Off", rx.table.cell(), rx.fragment()),
                        rx.table.cell(S.totals.get("registered", ""), justify="end"),
                        rx.table.cell(S.totals.get("unregistered", ""), justify="end"),
                        rx.table.cell(S.totals.get("total", ""), justify="end"),
                        rx.table.cell(S.totals.get("gateways", ""), justify="end"),
                        font_weight="bold",
                    ),
                ),
                variant="ghost", width="100%",
            ),
            max_height="60vh",
        ),
        padding="0", width="100%",
    )
    return cucm_page(
        "Device Report",
        _need_connection(S, rx.vstack(
            rx.hstack(
                rx.segmented_control.root(
                    rx.foreach(S.modes, lambda m: rx.segmented_control.item(m, value=m)),
                    value=S.mode, on_change=S.set_mode,
                ),
                rx.cond(S.mode == "Search",
                        search_input(S.pool_search, S.set_pool_search, "Device pool name contains",
                                     width="320px", max_width="100%"),
                        rx.fragment()),
                rx.spacer(),
                rx.button(rx.cond(S.running, rx.spinner(size="2"), rx.icon("play", size=16)), "Run Report",
                          on_click=S.run_report, disabled=S.running),
                rx.button(rx.icon("download", size=16), "Export", variant="soft", on_click=S.export_csv,
                          disabled=S.raw_rows.length() == 0),
                align="center", spacing="3", wrap="wrap", width="100%",
            ),
            rx.callout("This report is still under development. The registration and gateway lookups have not been "
                       "tested against a real CUCM.", icon="construction", color_scheme="amber", width="100%"),
            rx.hstack(
                rx.text("Devices:", size="2", weight="bold"),
                rx.foreach(S.all_kinds, lambda k: rx.checkbox(
                    k, checked=S.kinds.contains(k), on_change=lambda v: S.toggle_kind(k, v))),
                rx.divider(orientation="vertical", size="1"),
                rx.checkbox("Pull Registration", checked=S.registration & S.reg_available,
                            disabled=~S.reg_available, on_change=S.set_registration),
                align="center", spacing="4", wrap="wrap",
            ),
            rx.hstack(
                rx.text("Consolidate Device Pools:", size="2", weight="bold"),
                rx.segmented_control.root(
                    rx.foreach(S.groupings, lambda g: rx.segmented_control.item(g, value=g)),
                    value=S.grouping, on_change=S.set_grouping,
                ),
                rx.cond(S.grouping == "Prefix", rx.hstack(
                    rx.text("Delimiter", size="2"),
                    rx.input(value=S.group_delimiter, on_change=S.set_group_delimiter, width="60px", max_length=3),
                    rx.text("Parts", size="2"),
                    rx.input(value=S.group_parts, on_change=S.set_group_parts, width="60px", type="number", min=1),
                    align="center", spacing="2"), rx.fragment()),
                rx.cond(S.grouping == "Regex",
                        rx.input(value=S.group_regex, on_change=S.set_group_regex, width="320px", max_width="100%",
                                 placeholder="Matched from the start, e.g. ([A-Z]+-[A-Z0-9]+-)"),
                        rx.fragment()),
                align="center", spacing="3", wrap="wrap",
            ),
            rx.text("Merges device pools that share a key and sums their counts. Prefix keeps the first Parts "
                    "pieces split on the Delimiter (2 parts on - turns AGY-SITE-Phones into AGY-SITE-). Regex uses "
                    "its first capture group, or the whole match. Names that do not fit stay on their own. "
                    "Changing this does not re-query the cluster.", size="2", color="var(--gray-11)"),
            rx.cond(S.group_error != "", rx.callout(S.group_error, icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.text("Only the selected devices are queried. Turning off registration skips RisPort70, which is the "
                    "slowest part (paced at 15 requests per minute, about 4 seconds per 1,000 devices).", size="2", color="var(--gray-11)"),
            rx.cond(S.error != "", rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.cond(S.warning != "", rx.callout(S.warning, icon="triangle-alert", color_scheme="amber", width="100%"),
                    rx.fragment()),
            rx.cond(
                S.running,
                rx.hstack(rx.spinner(size="2"),
                          rx.text(rx.cond(S.progress != "", S.progress, "Building the report. Large clusters take a while..."),
                                  size="2"),
                          align="center", spacing="2"),
                rx.cond(
                    S.report_rows.length() > 0,
                    rx.vstack(
                        table,
                        rx.text(S.report_rows.length().to_string(), rx.cond(S.grouping != "Off", " groups.", " device pools."), size="2", color="var(--gray-11)"),
                        spacing="2", align="start", width="100%",
                    ),
                    rx.fragment(),
                ),
            ),
            spacing="4", align="start", width="100%",
        )),
        on_connection_change=S.switch_connection,
        on_org_change=S.switch_org,
    )
