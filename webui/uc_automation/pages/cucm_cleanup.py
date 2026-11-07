import reflex as rx

from ..components.cucm_nav import cucm_page
from ..components.search_input import search_input
from ..components.tool_widgets import code_block, collapsible_card, confirm_dialog, csv_dropzone, paste_csv_tabs, run_results
from ..state.cucm_cleanup import CleanupState
from .tools import _need_connection

S = CleanupState

_DN_EXAMPLE = "dn,partition\n5558594400,Phone-Line1-PT\n5558594401\n"
_DEVICE_EXAMPLE = "name\nSEP001122334455\nSEPAABBCCDDEEFF\n"


def _dn_inputs() -> rx.Component:
    return paste_csv_tabs(
            S.paste_dns, S.set_paste_dns,
            "One DN per line, optional partition second (tab, pipe, semicolon or comma). A header row is optional. "
            "A DN without a partition matches that number in any partition.",
            _DN_EXAMPLE.split("\n", 1)[1].rstrip(),
            rx.text(S.dn_count.to_string(), " directory number(s) in the list", size="2", color="var(--gray-11)"),
            [
                rx.text("Columns: dn, partition (optional). The file fills the Paste Text box.", size="2",
                        color="var(--gray-11)"),
                code_block(_DN_EXAMPLE),
                csv_dropzone("cleanup_dn_upload"),
                rx.button(rx.icon("upload", size=16), "Load CSV",
                          on_click=S.load_dn_csv(rx.upload_files(upload_id="cleanup_dn_upload"))),
            ],
        )


def _device_inputs() -> rx.Component:
    return paste_csv_tabs(
            S.paste_devices, S.set_paste_devices,
            "One device name per line (commas, tabs and spaces also separate). A 12 digit MAC address becomes "
            "SEP plus the MAC. A header row is optional.",
            _DEVICE_EXAMPLE.split("\n", 1)[1].rstrip(),
            rx.text(S.device_count.to_string(), " device(s) in the list", size="2", color="var(--gray-11)"),
            [
                rx.text("One column: name. The file fills the Paste Text box.", size="2", color="var(--gray-11)"),
                code_block(_DEVICE_EXAMPLE),
                csv_dropzone("cleanup_device_upload"),
                rx.button(rx.icon("upload", size=16), "Load CSV",
                          on_click=S.load_device_csv(rx.upload_files(upload_id="cleanup_device_upload"))),
            ],
        )


def _input_card() -> rx.Component:
    return collapsible_card("Input", S.input_open, S.toggle_input, rx.tabs.root(
        rx.tabs.list(
            rx.tabs.trigger("Directory Numbers", value="dns"),
            rx.tabs.trigger("Device Names", value="devices"),
        ),
        rx.tabs.content(rx.box(_dn_inputs(), padding_top="1rem"), value="dns"),
        rx.tabs.content(rx.box(_device_inputs(), padding_top="1rem"), value="devices"),
        default_value="dns", width="100%",
    ))


def _remediate_button(number: str, label: str, kind: str, icon: str) -> rx.Component:
    return rx.button(rx.icon(icon, size=16), f"{number}. {label}", variant="soft", on_click=S.scan_kind(kind),
                     disabled=S.working)


def _buttons() -> rx.Component:
    return rx.card(rx.vstack(
        rx.heading("Cleanup Steps", size="3"),
        rx.text("Each button runs only its own step. The Remediate buttons list objects and nothing is deleted "
                "until you tick them and confirm.", size="2", color="var(--gray-11)"),
        rx.hstack(
            rx.button(rx.icon("trash-2", size=16), "1. Delete Devices And Orphan DNs", color_scheme="red",
                      on_click=S.set_confirm_devices(True),
                      disabled=S.working | ((S.dn_count == 0) & (S.device_count == 0))),
            rx.button(rx.cond(S.hunt_scanning, rx.spinner(size="2"), rx.icon("users", size=16)),
                      "2. Remediate Hunt Groups", variant="soft", on_click=S.scan_hunt,
                      disabled=S.working | (S.dn_count == 0)),
            spacing="3", wrap="wrap",
        ),
        rx.divider(),
        rx.text("Unused objects: list them, tick the ones to delete.", size="2", weight="medium"),
        rx.hstack(
            search_input(S.rem_search, S.set_rem_search, "Search by name (Device Pool needs one)", width="320px",
                         max_width="100%"),
            spacing="3", align="center", wrap="wrap",
        ),
        rx.hstack(
            _remediate_button("3", "Call Pickup Group Remediate", "pickup", "phone-incoming"),
            _remediate_button("4", "Common Device Configuration Remediate", "cdc", "settings-2"),
            _remediate_button("5", "Phone Button Template Remediate", "pbt", "layout-grid"),
            _remediate_button("6", "Softkey Template Remediate", "softkey", "keyboard"),
            _remediate_button("7", "Partitions Remediate", "partition", "folder"),
            _remediate_button("8", "Calling Search Space Remediate", "css", "search"),
            _remediate_button("9", "Device Pool Remediate", "devpool", "server"),
            spacing="3", wrap="wrap",
        ),
        spacing="3", align="start", width="100%",
    ), width="100%")


def _hunt_panel() -> rx.Component:
    return rx.cond(
        S.hunt_scanning | S.hunt_scanned | (S.hunt_error != ""),
        rx.card(rx.vstack(
            rx.heading("Line Groups With These DNs", size="3"),
            rx.cond(S.hunt_scanning, rx.hstack(rx.spinner(size="2"), rx.text("Reading line groups...", size="2"),
                                               align="center", spacing="2"), rx.fragment()),
            rx.cond(S.hunt_error != "", rx.callout(S.hunt_error, icon="triangle-alert", color_scheme="red",
                                                   width="100%"), rx.fragment()),
            rx.cond(
                S.hunt_rows.length() > 0,
                rx.vstack(
                    rx.hstack(
                        rx.button("Select All", size="1", variant="soft", on_click=S.select_all_hunt),
                        rx.button("Clear", size="1", variant="soft", color_scheme="gray", on_click=S.clear_hunt),
                        rx.text(S.hunt_selected.length().to_string(), " selected", size="2", color="var(--gray-11)"),
                        rx.spacer(),
                        rx.button(rx.icon("user-minus", size=16), "Remove DNs From Line Groups", color_scheme="red",
                                  variant="soft", on_click=S.set_confirm_hunt("remove"),
                                  disabled=S.working | (S.hunt_selected.length() == 0)),
                        rx.button(rx.icon("trash-2", size=16), "Delete Line Groups", color_scheme="red",
                                  on_click=S.set_confirm_hunt("delete"),
                                  disabled=S.working | (S.hunt_selected.length() == 0)),
                        align="center", spacing="3", wrap="wrap", width="100%",
                    ),
                    rx.scroll_area(rx.table.root(
                        rx.table.header(rx.table.row(
                            rx.table.column_header_cell(""),
                            rx.table.column_header_cell("Line Group"),
                            rx.table.column_header_cell("DNs In The List"),
                            rx.table.column_header_cell("Members"),
                            rx.table.column_header_cell("Hunt Lists"),
                        )),
                        rx.table.body(rx.foreach(S.hunt_rows, lambda r: rx.table.row(
                            rx.table.cell(rx.checkbox(checked=S.hunt_selected.contains(r["name"]),
                                                      on_change=lambda c: S.toggle_hunt(r["name"], c))),
                            rx.table.cell(rx.code(r["name"])),
                            rx.table.cell(r["matched"]),
                            rx.table.cell(r["members"]),
                            rx.table.cell(r["hunt_lists"]),
                        ))),
                        size="2",
                    ), max_height="50vh"),
                    spacing="3", align="start", width="100%",
                ),
                rx.cond(S.hunt_scanned & (S.hunt_error == ""),
                        rx.text("No line group holds these DNs.", size="2", color="var(--gray-11)"), rx.fragment()),
            ),
            spacing="3", align="start", width="100%",
        ), width="100%"),
        rx.fragment(),
    )


def _remediate_panel() -> rx.Component:
    return rx.cond(
        S.rem_scanning | S.rem_scanned | (S.rem_warnings.length() > 0),
        rx.card(rx.vstack(
            rx.heading(S.rem_title, size="3"),
            rx.cond(S.rem_scanning, rx.hstack(rx.spinner(size="2"), rx.text("Checking references...", size="2"),
                                              align="center", spacing="2"), rx.fragment()),
            rx.foreach(S.rem_warnings, lambda w: rx.callout(w, icon="triangle-alert", color_scheme="amber", size="2",
                                                           width="100%")),
            rx.cond(
                S.rem_rows.length() > 0,
                rx.vstack(
                    rx.hstack(
                        rx.tooltip(
                            rx.badge(S.rem_unused.length().to_string() + " unused", color_scheme="green",
                                     variant=rx.cond(S.rem_only_unused, "solid", "soft"), cursor="pointer",
                                     on_click=S.toggle_only_unused),
                            content=rx.cond(S.rem_only_unused, "Showing only unused. Click to show all",
                                            "Click to show only unused")),
                        rx.button("Select All Unused", size="1", variant="soft", on_click=S.select_unused),
                        rx.button("Clear", size="1", variant="soft", color_scheme="gray", on_click=S.clear_rem),
                        rx.text(S.rem_selected.length().to_string(), " selected", size="2", color="var(--gray-11)"),
                        rx.spacer(),
                        rx.button(rx.icon("trash-2", size=16), "Delete Selected", color_scheme="red",
                                  on_click=S.set_confirm_rem(True),
                                  disabled=S.working | (S.rem_selected.length() == 0)),
                        align="center", spacing="3", wrap="wrap", width="100%",
                    ),
                    rx.scroll_area(rx.table.root(
                        rx.table.header(rx.table.row(
                            rx.table.column_header_cell(""),
                            rx.table.column_header_cell("Name"),
                            rx.table.column_header_cell("Status"),
                            rx.table.column_header_cell("Refs"),
                            rx.table.column_header_cell("Used By"),
                        )),
                        rx.table.body(rx.foreach(S.rem_shown, lambda r: rx.table.row(
                            rx.table.cell(rx.checkbox(checked=S.rem_selected.contains(r["name"]),
                                                      on_change=lambda c: S.toggle_rem(r["name"], c),
                                                      disabled=r["status"] != "Unused")),
                            rx.table.cell(rx.code(r["name"])),
                            rx.table.cell(rx.badge(r["status"], color_scheme=rx.match(
                                r["status"], ("Unused", "green"), ("In use", "red"), "amber"))),
                            rx.table.cell(r["count"]),
                            rx.table.cell(r["detail"]),
                        ))),
                        size="2",
                    ), max_height="50vh"),
                    spacing="3", align="start", width="100%",
                ),
                rx.cond(S.rem_scanned & (S.rem_warnings.length() == 0),
                        rx.text("Nothing matches.", size="2", color="var(--gray-11)"), rx.fragment()),
            ),
            spacing="3", align="start", width="100%",
        ), width="100%"),
        rx.fragment(),
    )


def cutover_cleanup() -> rx.Component:
    return cucm_page(
        "Cutover Cleanup",
        rx.callout("This tool is still under development.",
                   icon="construction", color_scheme="amber", width="100%"),
        _need_connection(S, rx.vstack(
            rx.text("Clean up the selected cluster after a Webex cutover: delete the old devices and their orphan "
                    "DNs, then remove the hunt group members and unused objects they leave behind.", size="2",
                    color="var(--gray-11)"),
            _input_card(),
            _buttons(),
            _hunt_panel(),
            _remediate_panel(),
            run_results(S, "Item"),
            spacing="4", align="start", width="100%",
        )),
        confirm_dialog(S, "Delete the devices and orphan DNs?",
                       "Deletes every device in the list, then each DN from the list or from those devices that no "
                       "device or profile uses. A DN still used elsewhere is kept. This cannot be undone.",
                       "Delete", S.run_delete_devices, open_var=S.confirm_devices, set_open=S.set_confirm_devices),
        rx.alert_dialog.root(
            rx.alert_dialog.content(
                rx.alert_dialog.title(rx.cond(S.confirm_hunt == "remove", "Remove the DNs from the line groups?",
                                              "Delete the line groups?")),
                rx.alert_dialog.description(rx.cond(
                    S.confirm_hunt == "remove",
                    "Removes the DNs in the list from every selected line group. A group whose members are all in "
                    "the list is not changed.",
                    "Deletes every selected line group. A line group still in a hunt list is refused.")),
                rx.hstack(
                    rx.button("Cancel", variant="soft", color_scheme="gray", on_click=S.set_confirm_hunt("")),
                    rx.button(rx.cond(S.confirm_hunt == "remove", "Remove", "Delete"), color_scheme="red",
                              on_click=S.run_hunt),
                    spacing="3", justify="end", margin_top="1rem",
                ),
            ),
            open=S.confirm_hunt != "",
        ),
        confirm_dialog(S, "Delete the selected objects?",
                       rx.text("Deletes every ticked ", S.rem_noun, ". CUCM refuses any that is still in use. This "
                               "cannot be undone."),
                       "Delete", S.run_rem_delete, open_var=S.confirm_rem, set_open=S.set_confirm_rem),
    )
