"""CUCM > Tools > Home Cluster Locator."""

import reflex as rx

from ..components.cucm_nav import cucm_page
from ..components.tool_widgets import confirm_dialog, field, run_results
from ..state.cucm_home import HomeClusterState

S = HomeClusterState


def _color(status):
    return rx.match(status, ("Found", "green"), ("Not Found", "gray"), "red")


def _edit_panel() -> rx.Component:
    return rx.cond(
        S.editing,
        rx.card(
            rx.vstack(
                rx.heading("Move Home Cluster", size="4"),
                rx.text("Tick the one cluster that should be home. Every other cluster has the home cluster removed for "
                        "this user. The AXL account is used on every cluster and is not saved.",
                        size="2", color="var(--gray-11)"),
                rx.hstack(
                    field("AXL Username", rx.input(value=S.axl_username, on_change=S.set_axl_username, width="220px",
                                                   auto_complete="off")),
                    field("AXL Password", rx.input(type="password", key=S.axl_key.to_string(),
                                                   on_change=S.set_axl_password, width="220px",
                                                   auto_complete="new-password")),
                    spacing="3", wrap="wrap",
                ),
                rx.hstack(
                    rx.button(rx.icon("arrow-right-left", size=16), "Update Home Cluster", on_click=S.ask_apply,
                              disabled=~S.can_apply),
                    rx.button("Cancel", variant="soft", color_scheme="gray", on_click=S.cancel_edit, disabled=S.busy),
                    spacing="3",
                ),
                spacing="3", align="start", width="100%",
            ),
            size="3", width="100%",
        ),
        rx.hstack(
            rx.button(rx.icon("pencil", size=16), "Edit Home Cluster", variant="soft", on_click=S.start_edit,
                      disabled=S.busy),
            rx.text("Boxes are ticked on every cluster where the user was found. "
                    "Several can be ticked here. Editing allows one.", size="1", color="var(--gray-10)"),
            align="center", spacing="3", wrap="wrap",
        ),
    )


def home_cluster_locator() -> rx.Component:
    table = rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell("Home"),
                    rx.table.column_header_cell("Connection"),
                    rx.table.column_header_cell("Server"),
                    rx.table.column_header_cell("Result"),
                    rx.table.column_header_cell("Home Cluster"),
                    rx.table.column_header_cell("Detail"),
                )),
                rx.table.body(rx.foreach(S.rows, lambda r: rx.table.row(
                    rx.table.cell(rx.checkbox(
                        checked=S.selected.contains(r["name"]),
                        on_change=lambda c: S.toggle_cluster(r["name"], c),
                        disabled=S.busy,
                    )),
                    rx.table.cell(r["name"]),
                    rx.table.cell(rx.code(r["server"])),
                    rx.table.cell(rx.badge(r["status"], color_scheme=_color(r["status"]))),
                    rx.table.cell(r["home"]),
                    rx.table.cell(r["detail"]),
                ))),
                variant="ghost", width="100%",
            ),
            max_height="60vh",
        ),
        padding="0", width="100%",
    )
    return cucm_page(
        "Home Cluster Locator",
        rx.vstack(
            rx.card(
                rx.vstack(
                    rx.text("Asks the UDS service of every CUCM cluster saved for the selected organization which "
                            "cluster the user is marked as home on. No login is needed.",
                            size="2", color="var(--gray-11)"),
                    rx.hstack(
                        field("User ID", rx.input(value=S.username, on_change=S.set_username, width="260px",
                                                  auto_complete="off")),
                        rx.button(rx.icon("locate", size=16), "Find User", on_click=S.locate,
                                  disabled=S.busy | (S.cluster_count == 0), margin_top="1.4rem"),
                        rx.text(S.cluster_count.to_string() + " cluster(s) in this organization", size="2",
                                color="var(--gray-11)", margin_top="1.4rem"),
                        align="start", spacing="3", wrap="wrap",
                    ),
                    rx.cond(
                        S.cluster_count == 0,
                        rx.callout(
                            rx.hstack(rx.text("This organization has no CUCM connections."),
                                      rx.link("Add them on the Credentials page", href="/credentials?tab=cucm"),
                                      spacing="2"),
                            icon="info", width="100%",
                        ),
                        rx.fragment(),
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(
                S.rows.length() > 0,
                rx.vstack(
                    rx.hstack(
                        rx.text("Home cluster for ", S.searched_user, ":", weight="medium"),
                        rx.badge(S.homes_text, color_scheme=S.homes_color),
                        rx.cond(S.homes.length() > 1, rx.text("Clusters disagree.", size="2", color="var(--orange-11)"),
                                rx.fragment()),
                        rx.cond(S.unreachable_count > 0,
                                rx.badge(S.unreachable_count.to_string() + " unreachable", color_scheme="red"),
                                rx.fragment()),
                        rx.spacer(),
                        rx.button(rx.icon("download", size=16), "Export CSV", variant="soft", on_click=S.export_csv),
                        align="center", spacing="2", wrap="wrap", width="100%",
                    ),
                    table,
                    _edit_panel(),
                    spacing="3", align="start", width="100%",
                ),
                rx.fragment(),
            ),
            run_results(S, "Cluster"),
            confirm_dialog(S, "Move The Home Cluster?", S.confirm_text, "Update Clusters", S.apply),
            spacing="4", align="start", width="100%",
        ),
        show_instance=False,
        on_org_change=S.pick_org,
    )
