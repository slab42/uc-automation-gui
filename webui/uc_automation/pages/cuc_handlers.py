import reflex as rx

from ..components.cuc_nav import cuc_page, need_connection
from ..components.cuc_widgets import data_table, failures, hidden_note, list_input
from ..components.tool_widgets import confirm_dialog, csv_dropzone, field
from ..state.cuc_handlers import DeleteHandlersState, ListHandlersState, MapState

_HANDLER_COLUMNS = [("displayName", "Name"), ("extension", "Extension"), ("objectId", "Object ID")]
_MENU_COLUMNS = [("sourceHandler", "Handler"), ("touchToneKey", "Key"), ("destinationType", "Destination type"),
                 ("destinationName", "Destination"), ("transferNumber", "Transfer number")]


def _error(message) -> rx.Component:
    return rx.cond(message != "", rx.callout(message, icon="triangle-alert", color_scheme="red", width="100%"),
                   rx.fragment())


def _spin(on, label: str, icon: str):
    return rx.cond(on, rx.spinner(size="2"), rx.icon(icon, size=16)), label


# --- List ---

def list_handlers() -> rx.Component:
    S = ListHandlersState
    return cuc_page(
        "List",
        need_connection(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.segmented_control.root(
                        rx.segmented_control.item("Call Handlers", value="handlers"),
                        rx.segmented_control.item("Non-Subscriber With Menu Entries", value="menu"),
                        value=S.mode, on_change=S.set_mode,
                    ),
                    rx.cond(
                        S.mode == "menu",
                        rx.vstack(
                            rx.text("Non-subscriber call handlers (system handlers left out) and every menu entry "
                                    "attached to them. Both CSVs feed the Map page.", size="2",
                                    color="var(--gray-11)"),
                            field("Display name contains", rx.input(
                                value=S.search, on_change=S.set_search, width="100%",
                                placeholder="Optional, case-insensitive. Blank lists all."),
                                "Only handlers whose name contains this text are listed."),
                            spacing="3", align="start", width="100%",
                        ),
                        rx.text("Every call handler except the built-in system handlers and subscriber (user) "
                                "handlers. The CSV can be loaded on the Delete page.", size="2",
                                color="var(--gray-11)"),
                    ),
                    rx.button(*_spin(S.loading, "List", "list"), on_click=S.run_list, disabled=S.loading),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            _error(S.error),
            rx.cond(
                S.loading,
                rx.hstack(rx.spinner(size="2"), rx.text("Reading from CUC. Menu entries take a while on large "
                                                       "systems...", size="2"), align="center", spacing="2"),
                rx.fragment(),
            ),
            rx.cond(
                S.listed_for != "",
                rx.vstack(
                    rx.hstack(
                        rx.heading(S.handlers.length().to_string() + " call handler(s)", size="4"),
                        rx.spacer(),
                        rx.button(rx.icon("download", size=16), "Export handlers", variant="soft",
                                  on_click=S.download_handlers, disabled=S.handlers.length() == 0),
                        align="center", width="100%",
                    ),
                    data_table(S.shown_handlers, _HANDLER_COLUMNS),
                    hidden_note(S.handlers_hidden),
                    rx.cond(
                        S.listed_menu,
                        rx.vstack(
                            rx.hstack(
                                rx.heading(S.menu_rows.length().to_string() + " menu entrie(s)", size="4"),
                                rx.spacer(),
                                rx.cond(S.menu_errors.length() > 0,
                                        rx.button(rx.icon("download", size=16),
                                                  S.menu_errors.length().to_string() + " failed: export errors",
                                                  variant="soft", color_scheme="red", on_click=S.download_errors),
                                        rx.fragment()),
                                rx.button(rx.icon("download", size=16), "Export menu entries", variant="soft",
                                          on_click=S.download_menu, disabled=S.menu_rows.length() == 0),
                                align="center", width="100%", wrap="wrap",
                            ),
                            data_table(S.shown_menu, _MENU_COLUMNS),
                            hidden_note(S.menu_hidden),
                            spacing="3", align="start", width="100%",
                        ),
                        rx.fragment(),
                    ),
                    spacing="3", align="start", width="100%",
                ),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        )),
    )


# --- Map ---

def _csv_loader(upload_id: str, label: str, on_load, file_name) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        csv_dropzone(upload_id),
        rx.hstack(
            rx.button(rx.icon("file-up", size=16), "Load", variant="soft",
                      on_click=on_load(rx.upload_files(upload_id=upload_id))),
            rx.cond(file_name != "", rx.badge(file_name, color_scheme="green", variant="soft"), rx.fragment()),
            align="center", spacing="3",
        ),
        spacing="2", align="start", width="100%",
    )


def _summary_row(label: str, key: str) -> rx.Component:
    S = MapState
    return rx.hstack(rx.text(label, size="2", color="var(--gray-11)"), rx.spacer(), rx.text(S.summary[key], size="2"),
                     width="100%")


def call_map() -> rx.Component:
    S = MapState
    return cuc_page(
        "Map",
        rx.vstack(
            rx.text("Builds an Excel workbook of the call trees: each root handler, every menu entry reachable "
                    "from it, orphan handlers, and circular or missing targets.", size="2", color="var(--gray-11)"),
            rx.card(
                rx.vstack(
                    rx.segmented_control.root(
                        rx.segmented_control.item("From The CUC Connection", value="connection"),
                        rx.segmented_control.item("From CSV Files", value="csv"),
                        value=S.source, on_change=S.set_source,
                    ),
                    rx.cond(
                        S.source == "connection",
                        need_connection(rx.vstack(
                            rx.text("Reads the non-subscriber call handlers and their menu entries from the active "
                                    "connection, then builds the workbook. Nothing is saved to CUC.", size="2",
                                    color="var(--gray-11)"),
                            field("Display name contains", rx.input(
                                value=S.search, on_change=S.set_search, width="100%",
                                placeholder="Optional. Limits the handlers, so trees may show missing targets."),
                            ),
                            spacing="3", align="start", width="100%",
                        )),
                        rx.vstack(
                            rx.text("Load the two CSVs exported on the List page (non-subscriber with menu entries). "
                                    "No connection is needed.", size="2", color="var(--gray-11)"),
                            _csv_loader("map_handlers_upload", "Call handler CSV", S.load_handlers_csv,
                                        S.handlers_file),
                            _csv_loader("map_menu_upload", "Menu entry CSV", S.load_menu_csv, S.menu_file),
                            spacing="3", align="start", width="100%",
                        ),
                    ),
                    rx.button(*_spin(S.building, "Build workbook", "network"), on_click=S.build,
                              disabled=S.building),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            _error(S.error),
            rx.cond(
                S.building,
                rx.hstack(rx.spinner(size="2"), rx.text("Building. Menu entries take a while on large systems...",
                                                       size="2"), align="center", spacing="2"),
                rx.fragment(),
            ),
            rx.cond(
                S.has_workbook,
                rx.card(
                    rx.vstack(
                        rx.heading("Workbook ready", size="4"),
                        rx.vstack(
                            _summary_row("Call handlers", "handlers"), _summary_row("Menu entries", "menuEntries"),
                            _summary_row("Routable menu entries", "routable"), _summary_row("Root handlers", "roots"),
                            _summary_row("Orphan handlers", "orphans"), _summary_row("Issues", "issues"),
                            spacing="1", width="100%", max_width="24rem",
                        ),
                        rx.button(rx.icon("download", size=16), "Download call_trees.xlsx",
                                  on_click=S.download_workbook),
                        spacing="3", align="start", width="100%",
                    ),
                    size="3", width="100%",
                ),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        ),
    )


# --- Delete ---

def delete_handlers() -> rx.Component:
    S = DeleteHandlersState
    return cuc_page(
        "Delete",
        need_connection(rx.vstack(
            rx.callout(
                "Deleting a call handler is permanent. ObjectIds belong to one CUC system: load a list exported "
                "from the same connection you are deleting on.",
                icon="triangle-alert", color_scheme="red", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Call handlers to delete", size="4"),
                    list_input(
                        S, "delete", S.paste_delete, "delete_handlers_upload", S.load_text, S.load_csv,
                        "Paste one ObjectId per line, or a list with a header row (displayName, extension, "
                        "objectId). The list is shown for review before anything is deleted.",
                        "ca8cdbd5-9b1b-4893-9237-171d78b5c6a2",
                        "Upload the CSV exported on the List page, and remove every row for a handler that should "
                        "NOT be deleted. It needs an objectId column.", "Load list"),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(
                S.rows.length() > 0,
                rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.heading(S.rows.length().to_string() + " call handler(s) will be deleted", size="4"),
                            rx.badge(S.file_name, variant="soft"),
                            rx.spacer(),
                            rx.button("Clear", variant="ghost", color_scheme="gray", on_click=S.clear_list),
                            align="center", width="100%",
                        ),
                        data_table(S.preview, _HANDLER_COLUMNS, "30vh"),
                        hidden_note(S.preview_hidden),
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("trash-2", size=16)),
                                  "Delete call handlers...", color_scheme="red", on_click=S.set_confirm_open(True),
                                  disabled=S.busy),
                        spacing="3", align="start", width="100%",
                    ),
                    size="3", width="100%",
                ),
                rx.fragment(),
            ),
            confirm_dialog(
                S, "Delete call handlers?",
                "Delete " + S.rows.length().to_string() + " call handler(s) from the active CUC connection? "
                "This cannot be undone.",
                "Delete", S.run_delete,
            ),
            failures(S, "Call handler"),
            spacing="4", align="start", width="100%",
        )),
    )
