import reflex as rx

from ..backend.cuc_users import STATUS_COLUMNS
from ..components.cuc_nav import cuc_page, need_connection
from ..components.cuc_widgets import all_rows_view, data_table, failures, hidden_note, list_input_parts
from ..components.tool_widgets import confirm_dialog
from ..state.cuc_users import RemoveEmptyState, StatusCheckState, UsageCheckState

_EXT_HELP = ("Paste one extension per line (or separated by commas, tabs, semicolons or pipes). "
             "A header row is optional.")
_EXT_CSV_HELP = "Upload a CSV with one extension per row in the first column. A header row is optional."


def _lookup_results(S, columns: list[tuple[str, str]]) -> rx.Component:
    return rx.vstack(
        failures(S, "Extension"),
        rx.cond(
            S.rows.length() > 0,
            rx.vstack(
                rx.hstack(
                    rx.heading(S.rows.length().to_string() + " mailbox(es)", size="4"),
                    rx.spacer(),
                    rx.button(rx.icon("download", size=16), "Export CSV", variant="soft", on_click=S.export_csv),
                    align="center", width="100%",
                ),
                data_table(S.shown_rows, columns),
                hidden_note(S.rows_hidden),
                spacing="3", align="start", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="4", align="start", width="100%",
    )


def _export_button(S) -> rx.Component:
    return rx.button(rx.icon("download", size=16), "Export selected", variant="soft", on_click=S.export_selected,
                     disabled=S.selected_count == 0)


def _three_tabs(S, all_view: rx.Component, paste: rx.Component, csv_body: rx.Component,
                below: rx.Component | None = None) -> rx.Component:
    """All users (default), Paste text and CSV. `below` (results) sits under the paste and CSV inputs."""
    def lookup(body):
        return rx.box(rx.vstack(body, below if below is not None else rx.fragment(), spacing="4", align="start",
                                width="100%"), padding_top="1rem")

    return rx.tabs.root(
        rx.tabs.list(rx.tabs.trigger("All Users", value="all"), rx.tabs.trigger("Paste Text", value="text"),
                     rx.tabs.trigger("CSV", value="csv")),
        rx.tabs.content(rx.box(all_view, padding_top="1rem"), value="all"),
        rx.tabs.content(lookup(paste), value="text"),
        rx.tabs.content(lookup(csv_body), value="csv"),
        default_value="all", width="100%",
    )


def status_check() -> rx.Component:
    S = StatusCheckState
    paste, csv_body = list_input_parts(S, "ext", S.paste_ext, "status_upload", S.load_text, S.load_csv, _EXT_HELP,
                                       "2001\n2002", _EXT_CSV_HELP, "Check")
    all_view = all_rows_view(S, STATUS_COLUMNS,
                          "Reads every user and their mailbox status from the active connection. This can take a "
                          "while on large systems.", _export_button(S))
    return cuc_page("Status Check", need_connection(
        _three_tabs(S, all_view, paste, csv_body, _lookup_results(S, STATUS_COLUMNS))))


_USAGE_COLUMNS = [("dtmfAccessID", "Extension"), ("alias", "Alias"), ("mailboxSize", "Size MB")]
_USAGE_ALL_COLUMNS = [("dtmfAccessId", "Extension"), ("alias", "Alias"), ("displayName", "Display name"),
                      ("sizeMb", "Size MB")]


def usage_check() -> rx.Component:
    S = UsageCheckState
    paste, csv_body = list_input_parts(S, "ext", S.paste_ext, "usage_upload", S.load_text, S.load_csv, _EXT_HELP,
                                       "2001\n2002", _EXT_CSV_HELP, "Check")
    all_view = all_rows_view(S, _USAGE_ALL_COLUMNS,
                          "Reads every user and their mailbox size from the active connection. Export gives the "
                          "dtmfAccessID, alias, mailboxSize CSV.", _export_button(S))
    return cuc_page("Usage Check", need_connection(
        _three_tabs(S, all_view, paste, csv_body, _lookup_results(S, _USAGE_COLUMNS))))


def remove_empty() -> rx.Component:
    S = RemoveEmptyState
    paste, csv_body = list_input_parts(S, "ext", S.paste_ext, "empty_upload", S.load_text, S.load_csv, _EXT_HELP,
                                       "2001\n2002", _EXT_CSV_HELP, "Scan")
    all_view = all_rows_view(
        S, _USAGE_ALL_COLUMNS,
        "Reads every user and mailbox from the active connection and lists the ones with no data. Tick the "
        "accounts to delete.",
        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("trash-2", size=16)), "Delete selected...",
                  color_scheme="red", on_click=S.set_confirm_all_open(True),
                  disabled=(S.selected_count == 0) | S.busy),
        rx.text(S.with_data_count.to_string() + " mailbox(es) with data are not listed.", size="1",
                color="var(--gray-10)"),
    )
    scan_results = rx.vstack(
        failures(S, "Extension"),
        rx.cond(
            S.scanned > 0,
            rx.card(
                rx.vstack(
                    rx.hstack(
                        rx.heading("Review", size="4"),
                        rx.badge(S.empty.length().to_string() + " empty", color_scheme="red", variant="soft"),
                        rx.badge(S.keep.length().to_string() + " with data", color_scheme="gray", variant="soft"),
                        rx.spacer(),
                        rx.button(rx.icon("download", size=16), "Export mailboxes with data", variant="soft",
                                  on_click=S.export_keep, disabled=S.keep.length() == 0),
                        rx.button("Clear", variant="ghost", color_scheme="gray", on_click=S.clear_plan),
                        align="center", width="100%", wrap="wrap",
                    ),
                    rx.cond(
                        S.empty.length() > 0,
                        rx.vstack(
                            rx.text("User accounts that will be deleted:", size="2"),
                            data_table(S.shown_empty, [("dtmfAccessID", "Extension"), ("alias", "Alias"),
                                                       ("mailboxSize", "Size MB")], "30vh"),
                            hidden_note(S.empty_hidden),
                            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("trash-2", size=16)),
                                      "Delete user accounts...", color_scheme="red",
                                      on_click=S.set_confirm_open(True), disabled=S.busy),
                            spacing="3", align="start", width="100%",
                        ),
                        rx.text("No empty mailboxes were found.", size="2", color="var(--gray-11)"),
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="4", align="start", width="100%",
    )
    return cuc_page(
        "Remove Empty",
        need_connection(rx.vstack(
            rx.callout(
                "This deletes the whole user account, not just the mailbox. CUC cannot remove only a mailbox. "
                "Nothing is deleted until you have reviewed the list and confirmed.",
                icon="triangle-alert", color_scheme="red", width="100%",
            ),
            rx.text("Paste text and CSV scan only the extensions you give, then show a review before deleting.",
                    size="2", color="var(--gray-11)"),
            _three_tabs(S, all_view, paste, csv_body, scan_results),
            confirm_dialog(
                S, "Delete user accounts?",
                "Delete " + S.empty.length().to_string() + " user account(s) with an empty mailbox on "
                + S.scan_conn + "? This cannot be undone.",
                "Delete", S.run_delete,
            ),
            confirm_dialog(
                S, "Delete user accounts?",
                "Delete " + S.selected_count.to_string() + " selected user account(s) on " + S.all_for
                + "? Only selected users whose mailbox is empty are deleted. This cannot be undone.",
                "Delete", S.delete_selected, S.confirm_all_open, S.set_confirm_all_open,
            ),
            spacing="4", align="start", width="100%",
        )),
    )
