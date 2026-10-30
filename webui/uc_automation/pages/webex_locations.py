import reflex as rx

from ..components.tool_widgets import code_block, confirm_dialog, csv_dropzone, paste_csv_tabs, run_results
from ..components.webex_nav import webex_page
from ..components.search_input import search_input
from ..components.webex_picker import picker
from ..state.webex_locations import E911State, SchedulesState
from .webex_routing import need_login

_LOCATION_COLS = (("Location", "name"),)


def _schedule_select(S) -> rx.Component:
    return rx.hstack(
        rx.text("Schedule", size="2", weight="medium"),
        rx.select(S.schedule_labels, value=S.schedule_label, on_change=S.set_schedule_label,
                  placeholder="Select a schedule", min_width="16rem"),
        align="center", spacing="3", wrap="wrap",
    )


def _export_panel(S) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Export a schedule to CSV", size="4"),
            rx.text("Writes the events in the same CSV layout the Update tab reads, ready to create the schedule at "
                    "another location.", size="2", color="var(--gray-11)"),
            _schedule_select(S),
            rx.button(rx.icon("download", size=16), "Export CSV", on_click=S.export_csv,
                      disabled=S.schedule_label == ""),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )


def _update_panel(S) -> rx.Component:
    return rx.vstack(
        rx.card(
            rx.vstack(
                rx.heading("Add or remove holiday events from CSV", size="4"),
                rx.text("Each distinct Name is a holiday schedule at the selected location: it is updated if it "
                        "exists and created if not (REMOVE rows are then skipped). Events already in the schedule "
                        "are not added twice. Events are all-day. Dates are M/D/YY or YYYY-MM-DD.",
                        size="2", color="var(--gray-11)"),
                paste_csv_tabs(
                    S.paste_schedule, lambda v: S.set_paste("schedule", v),
                    "One event per line, columns separated by tabs (straight from Excel), pipes or semicolons. "
                    "Commas work too unless a date has one. The header row is optional; without it the order is "
                    "Name, Event action, Event name, Event start date, Event end date.",
                    "State Holidays\tADD\tLabor Day 2026\t9/7/26\t9/7/26",
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("search", size=16)), "Review",
                              on_click=S.review_update_text, disabled=S.busy | ~S.has_selection),
                    [
                        code_block("Name,Event action,Event name,Event start date,Event end date\n"
                                   "State Holidays,ADD,Labor Day 2026,9/7/26,9/7/26\n"
                                   "State Holidays,REMOVE,Labor Day 2025,9/1/25,9/1/25\n"),
                        csv_dropzone("schedule_upload"),
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("search", size=16)), "Review",
                                  on_click=S.review_update(rx.upload_files(upload_id="schedule_upload")),
                                  disabled=S.busy | ~S.has_selection),
                    ],
                ),
                spacing="3", align="start", width="100%",
            ),
            size="3", width="100%",
        ),
        rx.cond(
            S.plan_rows.length() > 0,
            rx.card(
                rx.vstack(
                    rx.heading("Planned changes at " + S.selected_label, size="4"),
                    rx.table.root(
                        rx.table.header(rx.table.row(
                            rx.table.column_header_cell("Schedule"), rx.table.column_header_cell("Action"),
                            rx.table.column_header_cell("Add"), rx.table.column_header_cell("Remove"))),
                        rx.table.body(rx.foreach(S.plan_rows, lambda r: rx.table.row(
                            rx.table.cell(r["name"]), rx.table.cell(r["action"]),
                            rx.table.cell(r["add"]), rx.table.cell(r["remove"])))),
                        variant="ghost", width="100%",
                    ),
                    rx.foreach(S.plan_notes, lambda n: rx.text(n, size="1", color="var(--gray-10)")),
                    rx.button(rx.icon("check", size=16), "Apply changes...", on_click=S.set_confirm_open(True),
                              disabled=S.busy | ~S.plan_has_changes),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="4", width="100%",
    )


def _copy_panel(S) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Copy a schedule to other locations", size="4"),
            rx.text("Creates the schedule where it is missing. Where a schedule of the same type and name exists, "
                    "missing events are added and events with the same name but different details are updated; "
                    "events that exist only at the target are left alone.", size="2", color="var(--gray-11)"),
            _schedule_select(S),
            rx.hstack(
                rx.segmented_control.root(
                    rx.segmented_control.item("All Other Locations", value="all"),
                    rx.segmented_control.item("One Location", value="one"),
                    value=S.copy_scope, on_change=S.set_copy_scope,
                ),
                rx.cond(S.copy_scope == "one",
                        rx.select(S.location_names, value=S.copy_target, on_change=S.set_copy_target,
                                  placeholder="Target location", min_width="16rem"),
                        rx.fragment()),
                spacing="3", align="center", wrap="wrap",
            ),
            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("copy", size=16)), "Copy...",
                      on_click=S.set_confirm_open(True),
                      disabled=S.busy | (S.schedule_label == "") | (S.target_count == 0)),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )


def _remove_panel(S) -> rx.Component:
    def row(r) -> rx.Component:
        return rx.table.row(
            rx.table.cell(rx.checkbox(checked=S.past_selected.contains(r["key"]),
                                      on_change=lambda c: S.toggle_past(r["key"], c))),
            rx.table.cell(r["location"]), rx.table.cell(r["schedule"]),
            rx.table.cell(r["event"]), rx.table.cell(r["dates"]),
        )

    return rx.vstack(
        rx.card(
            rx.vstack(
                rx.heading("Remove past holiday events", size="4"),
                rx.text("Finds one-time holiday events that ended before today. Recurring events and business "
                        "hours schedules are never listed.", size="2", color="var(--gray-11)"),
                rx.segmented_control.root(
                    rx.segmented_control.item("All Locations", value="all"),
                    rx.segmented_control.item("One Location", value="one"),
                    value=S.remove_scope, on_change=S.set_remove_scope,
                ),
                rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("search", size=16)), "Find past events",
                          on_click=S.find_past,
                          disabled=S.busy | ((S.remove_scope == "one") & ~S.has_selection)),
                spacing="3", align="start", width="100%",
            ),
            size="3", width="100%",
        ),
        rx.cond(
            S.past_rows.length() > 0,
            rx.card(
                rx.vstack(
                    rx.hstack(
                        rx.heading(S.past_rows.length().to_string() + " past event(s)", size="4"),
                        rx.spacer(),
                        rx.button("Select all", variant="ghost", on_click=S.select_all_past),
                        rx.button("Select none", variant="ghost", color_scheme="gray", on_click=S.select_no_past),
                        align="center", width="100%",
                    ),
                    rx.scroll_area(
                        rx.table.root(
                            rx.table.header(rx.table.row(
                                rx.table.column_header_cell(""), rx.table.column_header_cell("Location"),
                                rx.table.column_header_cell("Schedule"), rx.table.column_header_cell("Event"),
                                rx.table.column_header_cell("Dates"))),
                            rx.table.body(rx.foreach(S.past_rows, row)),
                            variant="ghost", width="100%",
                        ),
                        max_height="45vh",
                    ),
                    rx.button(rx.icon("trash-2", size=16), "Delete " + S.past_selected.length().to_string()
                              + " selected...", color_scheme="red", on_click=S.set_confirm_open(True),
                              disabled=S.busy | (S.past_selected.length() == 0)),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(S.searched, rx.text("No past events found.", size="2", color="var(--gray-11)"), rx.fragment()),
        ),
        spacing="4", width="100%",
    )


def schedules() -> rx.Component:
    S = SchedulesState
    return webex_page(
        "Schedules",
        need_login(rx.vstack(
            rx.segmented_control.root(
                rx.segmented_control.item("Export", value="export"),
                rx.segmented_control.item("Update From CSV", value="update"),
                rx.segmented_control.item("Copy", value="copy"),
                rx.segmented_control.item("Remove Past Events", value="remove"),
                value=S.mode, on_change=S.set_mode,
            ),
            rx.cond(
                S.needs_location_pick,
                picker(S, rx.cond(S.mode == "copy", "Source location", "Location"), columns=_LOCATION_COLS),
                rx.fragment(),
            ),
            rx.match(
                S.mode,
                ("export", _export_panel(S)),
                ("update", _update_panel(S)),
                ("copy", _copy_panel(S)),
                _remove_panel(S),
            ),
            run_results(S, "Item"),
            rx.match(
                S.mode,
                ("update", confirm_dialog(S, "Apply these schedule changes?",
                                          "Events are added to and removed from " + S.selected_label + ".",
                                          "Apply", S.run_update)),
                ("copy", confirm_dialog(S, "Copy this schedule?",
                                        "Copies " + S.schedule_label + " to " + S.target_count.to_string()
                                        + " location(s).", "Copy", S.run_copy)),
                ("remove", confirm_dialog(S, "Delete these events?",
                                          "Deletes " + S.past_selected.length().to_string()
                                          + " past event(s). This cannot be undone.", "Delete", S.run_remove)),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        )),
    )


def e911() -> rx.Component:
    S = E911State

    def row(r) -> rx.Component:
        return rx.table.row(
            rx.table.cell(rx.checkbox(checked=S.selected.contains(r["id"]),
                                      on_change=lambda c: S.toggle(r["id"], c))),
            rx.table.cell(r["name"]),
            rx.table.cell(rx.badge(r["status"], color_scheme=rx.match(
                r["status"], ("OPTED_OUT", "gray"), ("COMPLIANT", "green"), ("ERROR", "red"), "amber"))),
            rx.table.cell(r["integration"]),
            rx.table.cell(r["routing"]),
        )

    return webex_page(
        "E911",
        need_login(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.hstack(
                        search_input(S.search, S.set_search, "Search locations", width="260px", max_width="100%"),
                        rx.spacer(),
                        rx.button(rx.cond(S.loading, rx.spinner(size="2"), rx.icon("refresh-cw", size=16)),
                                  "Reload", variant="soft", on_click=S.reload, disabled=S.loading),
                        rx.button(rx.icon("download", size=16), "Export", variant="soft", on_click=S.export_csv,
                                  disabled=S.rows.length() == 0),
                        align="center", spacing="3", wrap="wrap", width="100%",
                    ),
                    rx.cond(S.load_error != "", rx.callout(S.load_error, icon="triangle-alert", color_scheme="red",
                                                           width="100%"), rx.fragment()),
                    rx.cond(
                        S.loading,
                        rx.hstack(rx.spinner(size="2"), rx.text(rx.cond(S.progress != "", S.progress, "Loading..."),
                                                                size="2"), align="center", spacing="2"),
                        rx.scroll_area(
                            rx.table.root(
                                rx.table.header(rx.table.row(
                                    rx.table.column_header_cell(""), rx.table.column_header_cell("Location"),
                                    rx.table.column_header_cell("Compliance status"),
                                    rx.table.column_header_cell("Integration enabled"),
                                    rx.table.column_header_cell("Routing enabled"))),
                                rx.table.body(rx.foreach(S.shown, row)),
                                variant="ghost", width="100%",
                            ),
                            max_height="50vh",
                        ),
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Opt out of RedSky Emergency Calling", size="4"),
                    rx.text("Tick locations in the table, or tick the ones named in pasted text or a CSV "
                            "(names matched case-insensitively), then opt them out.",
                            size="2", color="var(--gray-11)"),
                    paste_csv_tabs(
                        S.paste_redsky, lambda v: S.set_paste("redsky", v),
                        "Paste one location name per line. A header row is optional.",
                        "SFO Office\nNYC Office",
                        rx.button(rx.icon("list-checks", size=16), "Select from text", variant="soft",
                                  on_click=S.select_from_text, disabled=S.rows.length() == 0),
                        [
                            rx.text("First column, header row skipped.", size="2", color="var(--gray-11)"),
                            code_block("Location\nSFO Office\nNYC Office\n"),
                            csv_dropzone("redsky_upload"),
                            rx.button(rx.icon("list-checks", size=16), "Select from CSV", variant="soft",
                                      on_click=S.select_from_csv(rx.upload_files(upload_id="redsky_upload")),
                                      disabled=S.rows.length() == 0),
                        ],
                    ),
                    rx.hstack(
                        rx.button("Select all shown", variant="ghost", on_click=S.select_shown),
                        rx.button("Clear selection", variant="ghost", color_scheme="gray", on_click=S.select_none),
                        spacing="3", wrap="wrap", align="center",
                    ),
                    rx.cond(S.csv_note != "", rx.text(S.csv_note, size="2", color="var(--gray-11)"), rx.fragment()),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("shield-off", size=16)),
                              "Opt out " + S.selected.length().to_string() + " location(s)...",
                              color_scheme="red", on_click=S.set_confirm_open(True),
                              disabled=S.busy | (S.selected.length() == 0)),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "Location"),
            confirm_dialog(S, "Opt these locations out of RedSky?",
                           "Sets " + S.selected.length().to_string() + " location(s) to OPTED_OUT.",
                           "Opt out", S.run_opt_out),
            spacing="4", align="start", width="100%",
        )),
    )
