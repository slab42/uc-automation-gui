import reflex as rx

from ..components.cucm_nav import cucm_page
from ..components.search_input import search_input
from ..state.cucm_pool_export import PoolExportState
from .tools import _need_connection


def _settings_dialog() -> rx.Component:
    S = PoolExportState
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Device Export Settings"),
            rx.vstack(
                rx.heading("Excel Output Options", size="3"),
                rx.text("Unchecked columns are hidden in the Excel output (unhide them in Excel). All are off by default. Registration "
                        "Status is included only when Pull Registration Status is checked on the page.",
                        size="2", color="var(--gray-11)"),
                rx.grid(rx.foreach(S.excel_option_names, lambda o: rx.checkbox(
                    o, checked=S.excel_on.contains(o), on_change=lambda v: S.toggle_excel_opt(o, v))),
                        columns="2", spacing="3", width="100%"),
                rx.divider(),
                rx.heading("Webex Location", size="3"),
                rx.text("The first column of the Phones sheet. It takes the value of a field and, optionally, a regular "
                        "expression narrows it down. With a capture group the first group is used, otherwise the whole "
                        "match. When nothing matches the cell is blank. Example: field Device Pool, regex "
                        "^([A-Z]+)- gives the part before the first dash. Search And Replace changes every match instead and "
                        "keeps the rest: regex ^(\\w+)-(\\w+)$ replaced by \\1 \\2 turns Site-Agency into Site Agency.", size="2", color="var(--gray-11)"),
                rx.select(S.location_field_names, value=S.location_field, on_change=S.set_location_field, width="100%"),
                rx.input(value=S.location_regex, on_change=S.set_location_regex, width="100%",
                         placeholder="Regular expression (blank = whole value)"),
                rx.checkbox("Search And Replace", checked=S.location_replace_on == "1",
                            on_change=S.set_location_replace_on),
                rx.cond(S.location_replace_on == "1", rx.input(
                    value=S.location_replace, on_change=S.set_location_replace, width="100%",
                    placeholder="Replace with (\\1 or $1 for groups, blank removes the match)"), rx.fragment()),
                rx.cond(S.location_regex_error != "",
                        rx.callout(S.location_regex_error, icon="triangle-alert", color_scheme="red", width="100%"),
                        rx.fragment()),
                rx.hstack(
                    rx.button("Reset", variant="soft", color_scheme="gray", on_click=S.reset_excel_opts),
                    rx.spacer(), rx.button("Done", on_click=S.set_settings_open(False)),
                    width="100%", align="center"),
                spacing="3", align="start", width="100%",
            ),
            max_width="560px", max_height="85vh", overflow_y="auto",
        ),
        open=S.settings_open, on_open_change=S.set_settings_open,
    )


def _status_row(label: str, content: rx.Component) -> rx.Component:
    return rx.vstack(rx.text(label, size="1", weight="bold", color="var(--gray-11)"), content,
                     spacing="1", align="start", width="100%")


def pool_export() -> rx.Component:
    S = PoolExportState
    picker = rx.card(
        rx.scroll_area(
            rx.vstack(
                rx.checkbox("Select All", checked=S.selected.length() == S.pools.length(),
                            on_change=S.toggle_all, weight="bold"),
                rx.divider(),
                rx.foreach(S.pools, lambda p: rx.checkbox(
                    p, checked=S.selected.contains(p), on_change=lambda v: S.toggle_pool(p, v))),
                spacing="2", align="start",
            ),
            max_height="30vh",
        ),
        width="100%",
    )
    return cucm_page(
        "Device Export for Webex",
        rx.vstack(
            rx.callout("This tool is still under development. It has not been tested against a real CUCM.",
                       icon="construction", color_scheme="amber", width="100%"),
            _need_connection(S, rx.vstack(
            rx.vstack(
                rx.text("Device pool name contains. Use | for or, for example Phone|711. Blank lists all.",
                        size="2", color="var(--gray-11)"),
                rx.hstack(
                    search_input(S.pool_search, S.set_pool_search, "Device pool name",
                                 on_enter=S.search_pools, width="360px", max_width="100%"),
                    rx.button(rx.cond(S.searching, rx.spinner(size="2"), rx.icon("search", size=16)), "Find Device Pools",
                              on_click=S.search_pools, disabled=S.searching | S.running),
                    rx.spacer(),
                    rx.tooltip(rx.icon_button(rx.icon("settings", size=18), variant="soft",
                                              on_click=S.set_settings_open(True), aria_label="Settings"),
                               content="Settings"),
                    align="center", spacing="3", wrap="wrap", width="100%",
                ),
                spacing="2", align="start", width="100%",
            ),
            rx.cond(S.pools.length() > 0, rx.vstack(
                rx.hstack(
                    rx.text(S.selected.length().to_string(), " of ", S.pools.length().to_string(),
                            " device pools selected", size="2", weight="bold"),
                    align="center", spacing="3",
                ),
                picker,
                rx.hstack(
                    rx.checkbox("Pull Registration Status", checked=S.registration, on_change=S.set_registration),
                    rx.spacer(),
                    rx.button(rx.cond(S.running, rx.spinner(size="2"), rx.icon("play", size=16)), "Run Export",
                              on_click=S.run_export, disabled=S.running | (S.selected.length() == 0)),
                    rx.button(rx.cond(S.validating, rx.spinner(size="2"), rx.icon("mail-check", size=16)),
                              "Webex Compatibility Check", variant="soft", on_click=S.validate_emails,
                              disabled=S.validating | S.running | ~S.has_result),
                    rx.button(rx.icon("download", size=16), "Download Excel",
                              variant=rx.cond(S.has_result, "solid", "soft"),
                              on_click=S.download_workbook, disabled=~S.has_result),
                    align="center", spacing="3", width="100%",
                ),
                rx.text("One row per phone with its lines in columns, plus BLF, Summary and Errors sheets. Owner is the "
                        "device Owner User ID, then the user the device is associated with, then the user of a line. "
                        "Phones with no user are marked Workspace. Registration status uses RisPort70 and is slow on "
                        "large pools.", size="2", color="var(--gray-11)"),
                spacing="3", align="start", width="100%",
            ), rx.fragment()),
            rx.cond(
                (S.error != "") | (S.warning != "") | (S.email_check != "") | S.running | S.validating | S.has_result,
                rx.card(rx.vstack(
                    rx.heading("Status", size="3"),
                    rx.cond(S.error != "", rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                            rx.fragment()),
                    rx.cond(S.warning != "", rx.callout(S.warning, icon="triangle-alert", color_scheme="amber",
                                                        width="100%"), rx.fragment()),
                    rx.cond(S.running | S.validating, _status_row("Progress", rx.hstack(
                        rx.spinner(size="2"),
                        rx.text(rx.cond(S.progress != "", S.progress, rx.cond(
                            S.validating, "Checking email addresses in Webex...",
                            "Reading phones. Large pools take a while...")), size="2"),
                        align="center", spacing="2")), rx.fragment()),
                    rx.cond(S.email_check != "", _status_row("Email Validation", rx.text(S.email_check, size="2")),
                            rx.fragment()),
                    rx.cond(S.has_result & ~S.running, _status_row("Export Summary", rx.text(
                        S.counts["phones"], " phones: ", S.counts["users"], " users, ", S.counts["workspaces"],
                        " workspaces, ", S.counts["blfs"], " BLFs, ", S.counts["errors"], " errors.", size="2")),
                            rx.fragment()),
                    spacing="3", align="start", width="100%",
                ), width="100%"),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
            )),
            spacing="4", align="start", width="100%",
        ),
        _settings_dialog(),
        on_connection_change=S.switch_connection,
        on_org_change=S.switch_org,
    )
