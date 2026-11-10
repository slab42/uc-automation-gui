import reflex as rx

from ..components.search_input import search_input
from ..components import sme_settings
from ..components.tool_widgets import confirm_dialog, field, how_it_works, run_results
from ..components.webex_nav import webex_page
from ..state.webex_sme_check import SmeCheckState
from .webex_routing import need_login


def _count_badge(label: str, status: str, color: str) -> rx.Component:
    return rx.badge(S.counts[status].to_string() + " " + label, color_scheme=color)


S = SmeCheckState


def _row(r) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.checkbox(checked=S.selected.contains(r["number"]), disabled=S.busy | (r["status"] == "Both Found"),
                                  on_change=lambda c: S.select_row(r["number"], c))),
        rx.table.cell(r["number"]),
        rx.table.cell(r["location"]),
        rx.table.cell(r["owner"]),
        rx.table.cell(rx.hstack(rx.badge(r["adv_found"], color_scheme=rx.cond(r["adv_found"] == "Yes", "green", "red")),
                                rx.text(r["adv_pattern"], size="1", color="var(--gray-11)"), spacing="2")),
        rx.table.cell(rx.hstack(rx.badge(r["rp_found"], color_scheme=rx.cond(r["rp_found"] == "Yes", "green", "red")),
                                rx.text(r["rp_pattern"], size="1", color="var(--gray-11)"), spacing="2")),
        rx.table.cell(r["status"]),
    )


def _settings_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("SME Pattern Check Settings"),
            rx.vstack(
                rx.hstack(
                    rx.text("SME cluster:", size="2"),
                    rx.cond(S.sme_names.length() > 0, rx.badge(S.sme_selected, variant="soft"),
                            rx.badge("None", color_scheme="red")),
                    align="center", spacing="2",
                ),
                rx.text("The SME cluster of the active organization is used.", size="2", color="var(--gray-11)"),
                rx.divider(),
                sme_settings.variables_section(S), rx.divider(),
                sme_settings.advertise_section(S), rx.divider(),
                sme_settings.route_section(S),
                rx.text("These settings are shared with Webex Cutover and SME Adv & Route Patterns: changing them "
                        "here changes them there. This report uses the Route Pattern partition.",
                        size="2", color="var(--gray-11)"),
                rx.cond(S.settings_error != "", rx.callout(S.settings_error, icon="triangle-alert",
                                                           color_scheme="red", width="100%"), rx.fragment()),
                rx.hstack(
                    rx.button("Reset SME Settings", variant="soft", color_scheme="gray", on_click=S.reset_settings),
                    rx.spacer(), rx.button("Done", on_click=S.set_settings_open(False)), width="100%",
                    align="center"),
                spacing="4", align="start", width="100%",
            ),
            max_width="640px", max_height="85vh", overflow_y="auto",
        ),
        open=S.settings_open, on_open_change=S.set_settings_open,
    )


def sme_pattern_check() -> rx.Component:
    return webex_page(
        "SME Pattern Check",
        need_login(rx.card(
            rx.vstack(
                rx.hstack(
                    how_it_works(
                    "Reads the phone numbers of the Webex org and checks the SME cluster for the Advertised Pattern "
                    "and the Route Pattern each one should have.",
                    "The patterns are built the same way as Webex Cutover: the Advertised Pattern keeps the plus "
                    "(+1...), the Route Pattern gets a backslash (\\+1...) and is looked up in the Route Pattern "
                    "partition from the Cutover settings.",
                    "Runs on the SME cluster of the active organization. Extension-only entries are skipped. "
                    "This report may take some time on a large org.",
                    ),
                    rx.spacer(),
                    rx.tooltip(rx.icon_button(rx.icon("settings", size=18), variant="soft",
                                              on_click=S.set_settings_open(True), aria_label="Settings"),
                               content="Settings"),
                    align="center", width="100%",
                ),
                _settings_dialog(),
                rx.hstack(
                    rx.text("SME cluster:", size="2"),
                    rx.cond(S.sme_names.length() > 0, rx.badge(S.sme_selected, variant="soft"),
                            rx.badge("None", color_scheme="red")),
                    rx.text("Route Pattern partition:", size="2"),
                    rx.badge(S.rp_partition, variant="soft"),
                    align="center", spacing="2", wrap="wrap",
                ),
                rx.cond(S.sme_names.length() == 0,
                        rx.callout("No SME cluster in this organization. Tick 'SME cluster' on Credentials > CUCM.",
                                   icon="triangle-alert", color_scheme="red", width="100%"),
                        rx.fragment()),
                rx.hstack(
                    rx.button(rx.cond(S.loading, rx.spinner(size="2"), rx.icon("play", size=16)),
                              "Run Report", on_click=S.run_report,
                              disabled=S.loading | (S.sme_names.length() == 0)),
                    search_input(S.search, S.set_search, "Search number, location or owner", width="280px",
                                 max_width="100%"),
                    rx.select(S.status_options, value=S.status_filter, on_change=S.set_status_filter),
                    rx.spacer(),
                    rx.button(rx.icon("refresh-cw", size=16), "Update", color_scheme="red",
                              on_click=S.ask_update, disabled=S.busy | (S.selected_count == 0)),
                    rx.button(rx.icon("download", size=16), "Export", variant="soft", on_click=S.export_csv,
                              disabled=S.rows.length() == 0),
                    align="center", spacing="3", wrap="wrap", width="100%",
                ),
                rx.cond(S.used_var_rows.length() > 0, rx.vstack(
                    rx.text("Values for the descriptions of the patterns Update creates:", size="2",
                            color="var(--gray-11)"),
                    rx.hstack(
                        rx.checkbox("Values Are Regex, Applied To", checked=S.use_regex, on_change=S.set_use_regex),
                        rx.select(S.sources, value=S.regex_source, on_change=S.set_regex_source,
                                  disabled=~S.use_regex),
                        align="center", spacing="2"),
                    rx.cond(S.use_regex,
                            rx.text("Each value is searched in the number's Location or Owner text; the first capture "
                                    "group (else the whole match) becomes the value, e.g. ^(\\w+) -. The Settings "
                                    "regex then validates it. A number that does not match fails on its own.",
                                    size="1", color="var(--gray-10)"),
                            rx.fragment()),
                    rx.grid(rx.foreach(S.used_var_rows, lambda v: field(v["display"], rx.cond(
                        S.use_regex,
                        rx.input(value=v["value"], on_change=lambda val: S.set_form_value(v["key"], val),
                                 width="100%", placeholder="Regex"),
                        sme_settings.value_input(S, v)))),
                            columns="2", spacing="3", width="100%"),
                    spacing="2", align="start", width="100%"), rx.fragment()),
                rx.cond(S.load_error != "", rx.callout(S.load_error, icon="triangle-alert", color_scheme="red",
                                                       width="100%"), rx.fragment()),
                rx.cond(
                    S.loading,
                    rx.hstack(rx.spinner(size="2"), rx.text("Reading Webex numbers and SME patterns...", size="2"),
                              align="center", spacing="2"),
                    rx.cond(
                        S.rows.length() > 0,
                        rx.vstack(
                            rx.hstack(
                                rx.badge(S.rows.length().to_string() + " Numbers", color_scheme="gray"),
                                _count_badge("Both Found", "Both Found", "green"),
                                _count_badge("Advertised Missing", "Advertised Missing", "amber"),
                                _count_badge("Route Pattern Missing", "Route Pattern Missing", "amber"),
                                _count_badge("Both Missing", "Both Missing", "red"),
                                spacing="2", wrap="wrap",
                            ),
                            rx.scroll_area(
                                rx.table.root(
                                    rx.table.header(rx.table.row(
                                        rx.table.column_header_cell(rx.checkbox(
                                            checked=S.all_selected, on_change=S.select_all,
                                            disabled=S.busy | (S.selectable.length() == 0))),
                                        rx.table.column_header_cell("Number"),
                                        rx.table.column_header_cell("Location"),
                                        rx.table.column_header_cell("Owner"),
                                        rx.table.column_header_cell("Advertised Pattern"),
                                        rx.table.column_header_cell("Route Pattern"),
                                        rx.table.column_header_cell("Status"))),
                                    rx.table.body(rx.foreach(S.shown, _row)),
                                    variant="ghost", width="100%",
                                ),
                                max_height="60vh",
                            ),
                            spacing="3", align="start", width="100%",
                        ),
                        rx.fragment(),
                    ),
                ),
                run_results(S, "Number"),
                confirm_dialog(S, "Add Missing Patterns",
                               "Create the missing Advertised Patterns and Route Patterns of " + S.selected_count.to_string()
                               + " selected number(s) on the SME cluster " + S.sme_selected + "?",
                               "Update", S.run_update),
                spacing="3", align="start", width="100%",
            ),
            size="3", width="100%",
        )),
    )
