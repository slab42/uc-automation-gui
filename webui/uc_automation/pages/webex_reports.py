import reflex as rx

from ..components.search_input import search_input
from ..components.webex_nav import webex_page
from ..state.webex_reports import LocationsReportState
from .webex_routing import need_login


def locations_report() -> rx.Component:
    S = LocationsReportState
    return webex_page(
        "Locations Report",
        need_login(rx.card(
            rx.vstack(
                rx.text("Counts the users and the workspaces with Webex Calling enabled in every location. "
                        "This report may take some time to run on a large org.",
                        size="2", color="var(--gray-11)"),
                rx.hstack(
                    rx.text("Report on", size="2", weight="medium"),
                    rx.checkbox("Users", checked=S.want_users, on_change=S.set_want_users, disabled=S.loading),
                    rx.checkbox("Workspaces", checked=S.want_workspaces, on_change=S.set_want_workspaces,
                                disabled=S.loading),
                    align="center", spacing="4",
                ),
                rx.hstack(
                    search_input(S.search, S.set_search, "Search locations", width="260px", max_width="100%"),
                    rx.button(rx.cond(S.loading, rx.spinner(size="2"), rx.icon("play", size=16)),
                              "Run Report", on_click=S.run_report, disabled=S.loading),
                    rx.spacer(),
                    rx.button(rx.icon("download", size=16), "Export", variant="soft", on_click=S.export_csv,
                              disabled=S.rows.length() == 0),
                    align="center", spacing="3", wrap="wrap", width="100%",
                ),
                rx.cond(S.load_error != "", rx.callout(S.load_error, icon="triangle-alert", color_scheme="red",
                                                       width="100%"), rx.fragment()),
                rx.cond(
                    S.loading,
                    rx.hstack(rx.spinner(size="2"), rx.text("Reading users and workspaces...", size="2"),
                              align="center", spacing="2"),
                    rx.cond(
                        S.rows.length() > 0,
                        rx.vstack(
                            rx.hstack(
                                rx.cond(S.result_users, rx.badge(
                                    S.total_users.to_string() + " Calling users", color_scheme="blue"), rx.fragment()),
                                rx.cond(S.result_workspaces, rx.badge(
                                    S.total_workspaces.to_string() + " Calling workspaces", color_scheme="green"),
                                        rx.fragment()),
                                rx.cond(S.both, rx.badge(S.total_all.to_string() + " Total", color_scheme="gray"),
                                        rx.fragment()),
                                spacing="2",
                            ),
                            rx.scroll_area(
                                rx.table.root(
                                    rx.table.header(rx.table.row(
                                        rx.table.column_header_cell("Location"),
                                        rx.cond(S.result_users, rx.table.column_header_cell("Calling Users"), rx.fragment()),
                                        rx.cond(S.result_workspaces, rx.table.column_header_cell("Calling Workspaces"),
                                                rx.fragment()),
                                        rx.cond(S.both, rx.table.column_header_cell("Total"), rx.fragment()))),
                                    rx.table.body(rx.foreach(S.shown, lambda r: rx.table.row(
                                        rx.table.cell(r["name"]),
                                        rx.cond(S.result_users, rx.table.cell(r["users"]), rx.fragment()),
                                        rx.cond(S.result_workspaces, rx.table.cell(r["workspaces"]), rx.fragment()),
                                        rx.cond(S.both, rx.table.cell(r["total"]), rx.fragment()))),
                                        rx.table.row(
                                            rx.table.row_header_cell("Total"),
                                            rx.cond(S.result_users, rx.table.cell(
                                                rx.text(S.total_users, weight="bold")), rx.fragment()),
                                            rx.cond(S.result_workspaces, rx.table.cell(
                                                rx.text(S.total_workspaces, weight="bold")), rx.fragment()),
                                            rx.cond(S.both, rx.table.cell(
                                                rx.text(S.total_all, weight="bold")), rx.fragment()),
                                        )),
                                    variant="ghost", width="100%",
                                ),
                                max_height="60vh",
                            ),
                            spacing="3", align="start", width="100%",
                        ),
                        rx.fragment(),
                    ),
                ),
                spacing="3", align="start", width="100%",
            ),
            size="3", width="100%",
        )),
    )
