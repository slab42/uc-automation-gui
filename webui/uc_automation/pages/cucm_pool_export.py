import reflex as rx

from ..components.cucm_nav import cucm_page
from ..components.search_input import search_input
from ..state.cucm_pool_export import PoolExportState
from .tools import _need_connection


def pool_export() -> rx.Component:
    S = PoolExportState
    picker = rx.card(
        rx.scroll_area(
            rx.vstack(
                rx.foreach(S.pools, lambda p: rx.checkbox(
                    p, checked=S.selected.contains(p), on_change=lambda v: S.toggle_pool(p, v))),
                spacing="2", align="start",
            ),
            max_height="30vh",
        ),
        width="100%",
    )
    table = rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell("Type"),
                    rx.table.column_header_cell("Device Name"),
                    rx.table.column_header_cell("Device Type"),
                    rx.table.column_header_cell("Device Pool"),
                    rx.table.column_header_cell("User ID"),
                    rx.table.column_header_cell("Email"),
                    rx.table.column_header_cell("Owner Source"),
                    rx.table.column_header_cell("Lines"),
                )),
                rx.table.body(rx.foreach(S.preview, lambda r: rx.table.row(
                    rx.table.cell(r["type"]), rx.table.cell(r["name"]), rx.table.cell(r["model"]),
                    rx.table.cell(r["pool"]), rx.table.cell(r["user"]), rx.table.cell(r["email"]),
                    rx.table.cell(r["source"]), rx.table.cell(r["lines"]),
                ))),
                variant="ghost", width="100%",
            ),
            max_height="50vh",
        ),
        padding="0", width="100%",
    )
    return cucm_page(
        "Device Export for Webex",
        _need_connection(S, rx.vstack(
            rx.hstack(
                search_input(S.pool_search, S.set_pool_search, "Device pool name contains (blank lists all)",
                             width="360px", max_width="100%"),
                rx.button(rx.cond(S.searching, rx.spinner(size="2"), rx.icon("search", size=16)), "Find Device Pools",
                          on_click=S.search_pools, disabled=S.searching | S.running),
                align="center", spacing="3", wrap="wrap", width="100%",
            ),
            rx.callout("This tool is still under development. It has not been tested against a real CUCM.",
                       icon="construction", color_scheme="amber", width="100%"),
            rx.cond(S.pools.length() > 0, rx.vstack(
                rx.hstack(
                    rx.text(S.selected.length().to_string(), " of ", S.pools.length().to_string(),
                            " device pools selected", size="2", weight="bold"),
                    rx.button("Select All", variant="soft", size="1", on_click=S.select_all),
                    rx.button("Select None", variant="soft", size="1", on_click=S.select_none),
                    align="center", spacing="3",
                ),
                picker,
                rx.hstack(
                    rx.checkbox("Pull Registration Status", checked=S.registration, on_change=S.set_registration),
                    rx.spacer(),
                    rx.button(rx.cond(S.running, rx.spinner(size="2"), rx.icon("play", size=16)), "Run Export",
                              on_click=S.run_export, disabled=S.running | (S.selected.length() == 0)),
                    rx.button(rx.icon("download", size=16), "Download Excel", variant="soft",
                              on_click=S.download_workbook, disabled=~S.has_result),
                    align="center", spacing="3", width="100%",
                ),
                rx.text("One row per phone with its lines in columns, plus BLF, Summary and Errors sheets. Owner is the "
                        "device Owner User ID, then the user the device is associated with, then the user of a line. "
                        "Phones with no user are marked Workspace. Registration status uses RisPort70 and is slow on "
                        "large pools.", size="2", color="var(--gray-11)"),
                spacing="3", align="start", width="100%",
            ), rx.fragment()),
            rx.cond(S.error != "", rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.cond(S.warning != "", rx.callout(S.warning, icon="triangle-alert", color_scheme="amber", width="100%"),
                    rx.fragment()),
            rx.cond(
                S.running,
                rx.hstack(rx.spinner(size="2"),
                          rx.text(rx.cond(S.progress != "", S.progress, "Reading phones. Large pools take a while..."),
                                  size="2"),
                          align="center", spacing="2"),
                rx.cond(S.has_result, rx.vstack(
                    rx.text(S.counts["phones"], " phones: ", S.counts["users"], " users, ", S.counts["workspaces"],
                            " workspaces, ", S.counts["blfs"], " BLFs, ", S.counts["errors"], " errors.",
                            size="2", color="var(--gray-11)"),
                    table, spacing="2", align="start", width="100%",
                ), rx.fragment()),
            ),
            spacing="4", align="start", width="100%",
        )),
        on_connection_change=S.switch_connection,
        on_org_change=S.switch_org,
    )
