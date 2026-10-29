import reflex as rx

from ..backend.cucm_tools import EM_MODES
from ..components.cucm_nav import cucm_page
from ..components.tool_widgets import code_block, csv_dropzone, field, run_results
from ..state.tools import EmBulkState, PhoneCountState, SetPinState


def _need_connection(S, body: rx.Component) -> rx.Component:
    return rx.cond(
        S.has_active,
        body,
        rx.callout(
            rx.hstack(rx.text("No CUCM connection is set up yet."),
                      rx.link("Add one on the Credentials page", href="/credentials"), spacing="2"),
            icon="info", width="100%",
        ),
    )


# --- EM bulk login ---

def em_bulk_login() -> rx.Component:
    S = EmBulkState
    return cucm_page(
        "EM Bulk Login",
        rx.vstack(
            rx.card(
                rx.vstack(
                    field("Operation", rx.select(list(EM_MODES), value=S.em_mode, on_change=S.set_em_mode,
                                                 width="14rem")),
                    rx.text(S.em_mode_help, size="2", color="var(--gray-11)"),
                    rx.cond(
                        S.uses_em_server,
                        field("Extension Mobility server", rx.input(
                            value=S.em_server, on_change=S.set_em_server, width="100%",
                            placeholder="Host name or IP. Blank uses the active CUCM connection's server."),
                            "Login and logout call http://<server>:8080/emapp/EMAppServlet from this app."),
                        rx.fragment(),
                    ),
                    rx.text("CSV format (header row required):", size="2", color="var(--gray-11)"),
                    code_block(S.em_template),
                    csv_dropzone("em_upload"),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("play", size=16)), "Run",
                              on_click=S.run_em(rx.upload_files(upload_id="em_upload")), disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "Device / user"),
            spacing="4", align="start", width="100%",
        ),
    )


# --- Phone count by device pool ---

def phone_count() -> rx.Component:
    S = PhoneCountState
    table = rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell("Device pool"),
                    rx.table.column_header_cell("Phones", justify="end"),
                )),
                rx.table.body(rx.foreach(S.filtered_rows, lambda r: rx.table.row(
                    rx.table.cell(r["devicePool"]),
                    rx.table.cell(r["phoneCount"], justify="end"),
                ))),
                variant="ghost", width="100%",
            ),
            max_height="60vh",
        ),
        padding="0", width="100%",
    )
    return cucm_page(
        "Phone Count By DP",
        _need_connection(S, rx.vstack(
            rx.hstack(
                rx.input(rx.input.slot(rx.icon("search", size=16)), placeholder="Search device pools",
                         value=S.search, on_change=S.set_search, width="320px", max_width="100%"),
                rx.hstack(rx.switch(checked=S.include_analog, on_change=S.set_include_analog),
                          rx.text("Include analog and CTI devices", size="2"), align="center", spacing="2"),
                rx.spacer(),
                rx.button(rx.cond(S.counting, rx.spinner(size="2"), rx.icon("refresh-cw", size=16)), "Refresh",
                          on_click=S.run_count, disabled=S.counting),
                rx.button(rx.icon("download", size=16), "Export", variant="soft", on_click=S.export_csv,
                          disabled=S.pool_rows.length() == 0),
                align="center", spacing="3", wrap="wrap", width="100%",
            ),
            rx.cond(S.error != "", rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.cond(
                S.counting & (S.pool_rows.length() == 0),
                rx.hstack(rx.spinner(size="2"), rx.text("Counting phones. Large clusters take a while...", size="2"),
                          align="center", spacing="2"),
                rx.cond(
                    S.pool_rows.length() > 0,
                    rx.vstack(
                        rx.cond(S.counting,
                                rx.hstack(rx.spinner(size="1"), rx.text("Refreshing...", size="1"),
                                          align="center", spacing="2"),
                                rx.fragment()),
                        table,
                        rx.text(S.total_label, " phones in ", S.pool_rows.length().to_string(), " device pools.",
                                rx.cond(S.excluded_count > 0,
                                        " " + S.excluded_count.to_string() + " analog/CTI devices excluded.", ""),
                                size="2", color="var(--gray-11)"),
                        spacing="2", align="start", width="100%",
                    ),
                    rx.cond(S.error != "", rx.fragment(),
                            rx.text("No phones found.", size="2", color="var(--gray-11)")),
                ),
            ),
            spacing="4", align="start", width="100%",
        )),
        on_connection_change=S.switch_connection,
    )


# --- Set user PIN ---

def set_user_pin() -> rx.Component:
    S = SetPinState
    return cucm_page(
        "Set User PIN",
        _need_connection(S, rx.vstack(
            rx.card(
                rx.vstack(
                    rx.heading("One user", size="4"),
                    rx.grid(
                        field("User ID", rx.input(value=S.pin_user, on_change=S.set_pin_user, width="100%")),
                        field("PIN", rx.input(type="password", key=S.pin_key.to_string(), on_change=S.set_pin_value,
                                              auto_complete="new-password", width="100%")),
                        columns="2", spacing="3", width="100%",
                    ),
                    rx.button(rx.icon("key-round", size=16), "Set PIN", on_click=S.set_single, disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("From CSV", size="4"),
                    rx.text("Header row required. The device column is allowed and ignored.", size="2",
                            color="var(--gray-11)"),
                    code_block("user,pin\njsmith,159357\nadoe,753951\n"),
                    csv_dropzone("pin_upload"),
                    rx.button(rx.icon("key-round", size=16), "Set PINs",
                              on_click=S.set_from_csv(rx.upload_files(upload_id="pin_upload")), disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "User"),
            spacing="4", align="start", width="100%",
        )),
    )
