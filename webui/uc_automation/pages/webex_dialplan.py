import reflex as rx

from ..components.search_input import search_input
from ..components.tool_widgets import code_block, confirm_dialog, csv_dropzone, field, paste_csv_tabs, run_results
from ..components.webex_nav import webex_page
from ..components.webex_picker import picker
from ..state.webex_dialplan import GatewayDialPlanState
from .webex_routing import need_login

_HELP = "One dial pattern per line, or separated by commas. A header row is optional."
_EXAMPLE = "+1555123!\n+1555124!\n9011!"


def _patterns_input(S, paste_var, prefix_var, field_name: str, upload_id: str, button_label: str, on_text,
                    on_csv) -> rx.Component:
    return rx.vstack(
        field("Prefix (optional)", rx.input(value=prefix_var, on_change=lambda v: S.set_prefix(field_name, v),
                                            placeholder="e.g. +1", width="12rem", max_width="100%")),
        rx.text("Added in front of every pattern before it is sent.", size="1", color="var(--gray-10)"),
        _tabs(S, paste_var, field_name, upload_id, button_label, on_text, on_csv),
        spacing="2", align="start", width="100%",
    )


def _tabs(S, paste_var, field_name: str, upload_id: str, button_label: str, on_text, on_csv) -> rx.Component:
    def button(on_click) -> rx.Component:
        return rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), button_label,
                         on_click=on_click, disabled=S.busy)
    return paste_csv_tabs(
        paste_var, lambda v: S.set_paste(field_name, v), _HELP, _EXAMPLE, button(on_text),
        [
            rx.text("First column, header row skipped.", size="2", color="var(--gray-11)"),
            code_block("Pattern\n+1555123!\n+1555124!\n"),
            csv_dropzone(upload_id),
            button(on_csv(rx.upload_files(upload_id=upload_id))),
        ],
    )


def _create_card(S) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Create a Dial Plan", size="4"),
            rx.text("A dial plan sends calls that match its dial patterns to a trunk or route group. Dial plans apply "
                    "to the whole organization, not to one location.", size="2", color="var(--gray-11)"),
            field("Dial plan name", rx.input(value=S.new_name, on_change=S.set_new_name, width="20rem", max_width="100%")),
            field("Route", rx.select(S.route_labels, value=S.route_label, on_change=S.set_route_label,
                                     placeholder="Select a trunk or route group", min_width="22rem")),
            rx.text("Dial patterns", size="2", weight="medium"),
            _patterns_input(S, S.paste_create, S.prefix_create, "create", "dp_create_upload", "Create Dial Plan",
                            S.create_from_text, S.create_from_csv),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )


def _pattern_row(S, p) -> rx.Component:
    return rx.checkbox(p, checked=S.chosen.contains(p), on_change=lambda c: S.toggle_pattern(p, c))


def _pattern_list(S) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            search_input(S.pattern_search, S.set_pattern_search, width="260px", max_width="100%"),
            rx.button("Select Matching", variant="soft", on_click=S.choose_matching, disabled=S.busy),
            rx.button("Select None", variant="soft", color_scheme="gray", on_click=S.choose_none, disabled=S.busy),
            rx.button(rx.icon("trash-2", size=16), "Delete Selected (" + S.chosen.length().to_string() + ")...",
                      color_scheme="red", on_click=S.set_confirm_open(True),
                      disabled=S.busy | (S.chosen.length() == 0)),
            align="center", spacing="3", wrap="wrap", width="100%",
        ),
        rx.text(S.filtered_patterns.length().to_string() + " matching. "
                + rx.cond(S.filtered_patterns.length() > S.shown_patterns.length(),
                          "Showing the first " + S.shown_patterns.length().to_string() + ", narrow the search to see more. ", "")
                + S.chosen.length().to_string() + " selected.", size="1", color="var(--gray-10)"),
        rx.box(
            rx.vstack(rx.foreach(S.shown_patterns, lambda p: _pattern_row(S, p)), spacing="2", align="start"),
            max_height="16rem", overflow_y="auto", width="100%", padding="0.5rem",
            border="1px solid var(--gray-5)", border_radius="var(--radius-3)",
        ),
        spacing="2", align="start", width="100%",
    )


def _edit_card(S) -> rx.Component:
    return rx.vstack(
        picker(S, "Dial Plan", columns=(("Dial Plan", "name"), ("Route", "location"))),
        rx.cond(
            S.has_selection,
            rx.card(
                rx.vstack(
                    rx.heading("Dial patterns of " + S.selected_row["name"], size="4"),
                    rx.cond(
                        S.detail_loading,
                        rx.hstack(rx.spinner(size="2"), rx.text("Reading the dial patterns...", size="2"),
                                  align="center", spacing="2"),
                        rx.vstack(
                            rx.text(S.patterns.length().to_string() + " dial pattern(s) on this plan.", size="2",
                                    color="var(--gray-11)"),
                            rx.cond(S.patterns.length() > 0, _pattern_list(S), rx.fragment()),
                            rx.text("Add dial patterns", size="2", weight="medium"),
                            _patterns_input(S, S.paste_add, S.prefix_add, "add", "dp_add_upload", "Add Dial Patterns",
                                            S.add_from_text, S.add_from_csv),
                            spacing="3", align="start", width="100%",
                        ),
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="4", align="start", width="100%", padding_top="1rem",
    )


def gateway_dial_plan() -> rx.Component:
    S = GatewayDialPlanState
    return webex_page(
        "Gateway Dial Plan",
        need_login(rx.vstack(
            rx.tabs.root(
                rx.tabs.list(
                    rx.tabs.trigger("Add Dial Plan", value="add"),
                    rx.tabs.trigger("Edit Dial Plan", value="edit"),
                ),
                rx.tabs.content(rx.box(_create_card(S), padding_top="1rem", width="100%"), value="add"),
                rx.tabs.content(_edit_card(S), value="edit"),
                default_value="add", width="100%",
            ),
            run_results(S, "Dial Plan"),
            confirm_dialog(S, "Delete these dial patterns?",
                           S.chosen.length().to_string() + " dial pattern(s) will be removed from " +
                           S.selected_row["name"] + ". Calls matching them stop using this route.",
                           "Delete", S.run_delete),
            spacing="4", align="start", width="100%",
        )),
    )
