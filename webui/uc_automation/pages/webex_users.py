import reflex as rx

from ..components.tool_widgets import code_block, confirm_dialog, csv_dropzone, field, paste_csv_tabs, run_results
from ..components.webex_nav import webex_page
from ..components.webex_picker import picker
from ..state.webex_users import (
    AddWorkspaceState,
    CopyWorkspaceState,
    CreateWorkspaceState,
    DeleteUsersState,
    MigrateState,
    ResetPinState,
    VoicemailState,
)
from .webex_routing import need_login


def delete_users() -> rx.Component:
    S = DeleteUsersState
    return webex_page(
        "Delete Users",
        need_login(rx.vstack(
            rx.callout("Deleting a Webex user is permanent.", icon="triangle-alert", color_scheme="red",
                       width="100%"),
            rx.card(
                rx.vstack(
                    rx.heading("Users to delete", size="4"),
                    paste_csv_tabs(
                        S.paste_delete, lambda v: S.set_paste("delete", v),
                        "Paste one email address per line (or separated by commas, tabs, semicolons or pipes). "
                        "A pasted Control Hub export with its header row also works: the email is read from the "
                        "column whose header contains \"email\". The list is shown for review before anything is "
                        "deleted.",
                        "jsmith@example.com\nadoe@example.com",
                        rx.button(rx.icon("list-plus", size=16), "Load list", on_click=S.load_text,
                                  disabled=S.busy),
                        [
                            rx.text("Upload the CSV exported from Control Hub and remove every row for a user "
                                    "who should NOT be deleted. Keep the header row. The email is read from the "
                                    "column whose header contains \"email\", otherwise from the fourth column.",
                                    size="2", color="var(--gray-11)"),
                            csv_dropzone("delete_upload"),
                            rx.button(rx.icon("file-up", size=16), "Load CSV",
                                      on_click=S.load_csv(rx.upload_files(upload_id="delete_upload")),
                                      disabled=S.busy),
                        ],
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(
                S.emails.length() > 0,
                rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.heading(S.emails.length().to_string() + " user(s) will be deleted", size="4"),
                            rx.badge(S.file_name, variant="soft"),
                            rx.spacer(),
                            rx.button("Clear", variant="ghost", color_scheme="gray", on_click=S.clear_list),
                            align="center", width="100%",
                        ),
                        rx.scroll_area(
                            rx.vstack(rx.foreach(S.preview, lambda e: rx.code(e)), spacing="1", align="start"),
                            max_height="30vh", width="100%",
                        ),
                        rx.cond(S.preview_hidden > 0,
                                rx.text("... and " + S.preview_hidden.to_string() + " more", size="1",
                                        color="var(--gray-10)"), rx.fragment()),
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("trash-2", size=16)),
                                  "Delete users...", color_scheme="red", on_click=S.set_confirm_open(True),
                                  disabled=S.busy),
                        spacing="3", align="start", width="100%",
                    ),
                    size="3", width="100%",
                ),
                rx.fragment(),
            ),
            run_results(S, "Email"),
            confirm_dialog(S, "Delete these users?",
                           "This permanently deletes " + S.emails.length().to_string() + " Webex user(s). "
                           "It cannot be undone.", "Delete users", S.run_delete),
            spacing="4", align="start", width="100%",
        )),
    )


def reset_pin() -> rx.Component:
    S = ResetPinState
    return webex_page(
        "Reset PIN",
        need_login(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.heading("One user", size="4"),
                    field("Email", rx.input(value=S.email, on_change=S.set_email, width="100%",
                                            placeholder="jane.doe@example.com"),
                          "The user needs a Webex Calling - Professional license; others are skipped."),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("key-round", size=16)),
                              "Reset voicemail PIN", on_click=S.reset_single, disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Multiple users", size="4"),
                    paste_csv_tabs(
                        S.paste_pin, lambda v: S.set_paste("pin", v),
                        "Paste one email address per line (or separated by commas, tabs, semicolons or pipes). "
                        "A header row is optional.",
                        "jane.doe@example.com\njohn.smith@example.com",
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("key-round", size=16)),
                                  "Reset PINs", on_click=S.reset_from_text, disabled=S.busy),
                        [
                            rx.text("Header row required. The column whose header contains \"email\" is used, "
                                    "otherwise the first column.", size="2", color="var(--gray-11)"),
                            code_block("Email\njane.doe@example.com\njohn.smith@example.com\n"),
                            csv_dropzone("pin_upload"),
                            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)),
                                      "Reset PINs",
                                      on_click=S.reset_from_csv(rx.upload_files(upload_id="pin_upload")),
                                      disabled=S.busy),
                        ],
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "Email"),
            spacing="4", align="start", width="100%",
        )),
    )


def create_workspace() -> rx.Component:
    S = CreateWorkspaceState
    types = ["notSet", "focus", "huddle", "meetingRoom", "open", "desk", "other"]
    return webex_page(
        "Add Workspace",
        need_login(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.heading("Single Workspace", size="4"),
                    rx.grid(
                        field("Workspace name", rx.input(value=S.form_workspace, width="100%",
                                                         on_change=lambda v: S.set_form("workspace", v))),
                        field("Location (optional)", rx.fragment(
                            rx.input(value=S.form_location, width="100%", list="create-workspace-locations",
                                     placeholder="Start typing to search", auto_complete="off",
                                     on_change=lambda v: S.set_form("location", v)),
                            rx.el.datalist(rx.foreach(S.location_names, lambda n: rx.el.option(value=n)),
                                           id="create-workspace-locations"),
                        ), "Required when you give a phone number or extension (the workspace gets Webex Calling)."),
                        field("Type (optional)", rx.select(types, value=S.form_type, width="100%",
                                                           placeholder="Not set",
                                                           on_change=lambda v: S.set_form("type", v))),
                        field("Capacity (optional)", rx.input(value=S.form_capacity, width="100%", type="number",
                                                              on_change=lambda v: S.set_form("capacity", v))),
                        field("Phone number (optional)", rx.input(value=S.form_number, width="100%",
                                                                  placeholder="+12145550100",
                                                                  on_change=lambda v: S.set_form("number", v))),
                        field("Extension (optional)", rx.input(value=S.form_extension, width="100%",
                                                               on_change=lambda v: S.set_form("extension", v))),
                        columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                    ),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add Workspace",
                              on_click=S.create_single, disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Multiple Workspaces", size="4"),
                    paste_csv_tabs(
                        S.paste_workspace, lambda v: S.set_paste("workspace", v),
                        "One workspace per line, columns separated by tabs (straight from Excel), pipes, semicolons "
                        "or commas. The header row is optional; without it the order is workspace, location, type, "
                        "capacity, number, extension (everything after workspace is optional).",
                        "Lobby Room,Dallas,meetingRoom,8,+12145550100,",
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add Workspaces",
                                  on_click=S.create_from_text, disabled=S.busy),
                        [
                            rx.text("Header row required: workspace. location, type, capacity, number and extension "
                                    "are optional.", size="2", color="var(--gray-11)"),
                            code_block("workspace,location,type,capacity,number,extension\n"
                                       "Lobby Room,Dallas,meetingRoom,8,+12145550100,\n"),
                            csv_dropzone("workspace_upload"),
                            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)),
                                      "Add Workspaces",
                                      on_click=S.create_from_csv(rx.upload_files(upload_id="workspace_upload")),
                                      disabled=S.busy),
                        ],
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            confirm_dialog(S, "Check The Phone Numbers", S.number_prompt, S.number_action,
                           S.confirm_numbers, open_var=S.number_open, set_open=S.set_number_open),
            run_results(S, "Workspace"),
            spacing="4", align="start", width="100%",
        )),
    )


def copy_workspace() -> rx.Component:
    S = CopyWorkspaceState

    def location_input(value, name: str, list_id: str):
        return rx.fragment(
            rx.input(value=value, width="100%", list=list_id, placeholder="Start typing to search",
                     auto_complete="off", on_change=lambda v: S.set_form(name, v)),
            rx.el.datalist(rx.foreach(S.location_names, lambda n: rx.el.option(value=n)), id=list_id),
        )

    return webex_page(
        "Copy Workspace",
        need_login(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.heading("Workspace To Copy", size="4"),
                    rx.grid(
                        field("Workspace name", rx.fragment(
                            rx.input(value=S.form_source, width="100%", list="copy-source-workspaces",
                                     placeholder="Start typing to search", auto_complete="off",
                                     on_change=lambda v: S.set_form("source", v)),
                            rx.el.datalist(rx.foreach(S.workspace_names, lambda n: rx.el.option(value=n)),
                                           id="copy-source-workspaces"),
                        ),
                              "Search for an existing workspace. Its type, capacity, notes and calling settings are copied."),
                        field("Location (optional)", location_input(S.form_source_location, "source_location",
                                                                    "copy-source-locations"),
                              "Only needed when two workspaces share a name."),
                        columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.tabs.root(
                    rx.tabs.list(
                        rx.tabs.trigger("Single Copy", value="single"),
                        rx.tabs.trigger("Multiple Copies", value="multiple"),
                    ),
                    rx.tabs.content(
                        rx.vstack(
                            rx.grid(
                                field("New workspace name", rx.input(value=S.form_workspace, width="100%",
                                                                     on_change=lambda v: S.set_form("workspace", v))),
                                field("Location (optional)", location_input(S.form_location, "location",
                                                                            "copy-new-locations"),
                                      "Defaults to the location of the workspace being copied."),
                                field("Phone number (optional)", rx.input(value=S.form_number, width="100%",
                                                                          placeholder="+12145550100",
                                                                          on_change=lambda v: S.set_form("number", v)),
                                      "Numbers are never copied. Give one, or an extension, to add Webex Calling."),
                                field("Extension (optional)", rx.input(value=S.form_extension, width="100%",
                                                                       on_change=lambda v: S.set_form("extension", v))),
                                columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                            ),
                            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("copy", size=16)),
                                      "Copy Workspace", on_click=S.copy_single, disabled=S.busy),
                            spacing="3", align="start", width="100%", padding_top="1rem",
                        ),
                        value="single",
                    ),
                    rx.tabs.content(
                        rx.box(
                            paste_csv_tabs(
                                S.paste_copy, lambda v: S.set_paste("copy", v),
                                "One new workspace per line, columns separated by tabs (straight from Excel), pipes, "
                                "semicolons or commas. The header row is optional; without it the order is workspace, "
                                "location, number, extension (everything after workspace is optional). Every copy "
                                "uses the workspace named above.",
                                "Room 101,Dallas,+12145550101,\nRoom 102,Dallas,+12145550102,",
                                rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("copy", size=16)),
                                          "Copy Workspaces", on_click=S.copy_from_text, disabled=S.busy),
                                [
                                    rx.text("Header row required: workspace. location, number and extension are "
                                            "optional.", size="2", color="var(--gray-11)"),
                                    code_block("workspace,location,number,extension\n"
                                               "Room 101,Dallas,+12145550101,\n"),
                                    csv_dropzone("workspace_upload"),
                                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)),
                                              "Copy Workspaces",
                                              on_click=S.copy_from_csv(rx.upload_files(upload_id="workspace_upload")),
                                              disabled=S.busy),
                                ],
                            ),
                            padding_top="1rem", width="100%",
                        ),
                        value="multiple",
                    ),
                    default_value="single", width="100%",
                ),
                size="3", width="100%",
            ),
            confirm_dialog(S, "Check The Phone Numbers", S.number_prompt, S.number_action,
                           S.confirm_numbers, open_var=S.number_open, set_open=S.set_number_open),
            run_results(S, "Workspace"),
            spacing="4", align="start", width="100%",
        )),
    )


def _models_info(S) -> rx.Component:
    return rx.popover.root(
        rx.popover.trigger(rx.icon_button(rx.icon("info", size=16), variant="ghost", size="1",
                                          aria_label="Supported models")),
        rx.popover.content(
            rx.vstack(
                rx.text("Supported models", weight="bold", size="2"),
                rx.text("Enter the text in the Model column exactly as shown, in the form or in the paste and CSV "
                        "input.", size="1", color="var(--gray-11)"),
                rx.cond(
                    S.model_rows.length() > 0,
                    rx.scroll_area(
                        rx.table.root(
                            rx.table.header(rx.table.row(rx.table.column_header_cell("Model Text"),
                                                         rx.table.column_header_cell("Display Name"))),
                            rx.table.body(rx.foreach(S.model_rows, lambda r: rx.table.row(
                                rx.table.cell(rx.code(r["model"])), rx.table.cell(r["name"])))),
                            size="1",
                        ),
                        max_height="20rem", type="auto",
                    ),
                    rx.text("No models loaded. Check the Webex login and reload the page.", size="2"),
                ),
                spacing="2",
            ),
            max_width="34rem",
        ),
    )


def add_workspace() -> rx.Component:
    S = AddWorkspaceState
    return webex_page(
        "Add Device",
        need_login(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.heading("Add a device to a workspace", size="4"),
                    rx.grid(
                        field("Workspace name", rx.input(value=S.form_workspace, width="100%",
                                                         on_change=lambda v: S.set_form("workspace", v)),
                              "The display name of an existing workspace."),
                        field("Location (optional)", rx.fragment(
                            rx.input(value=S.form_location, width="100%", list="workspace-locations",
                                     placeholder="Start typing to search", auto_complete="off",
                                     on_change=lambda v: S.set_form("location", v)),
                            rx.el.datalist(rx.foreach(S.location_names, lambda n: rx.el.option(value=n)),
                                           id="workspace-locations"),
                        ), "Click the field to see every location, or type to narrow the list. "
                           "Only needed when two workspaces share a name."),
                        rx.vstack(
                            rx.hstack(rx.text("Model", size="2", weight="medium"), _models_info(S),
                                      spacing="2", align="center"),
                            rx.input(value=S.form_model, width="100%", placeholder="Cisco 8845",
                                     list="workspace-models", auto_complete="off",
                                     on_change=lambda v: S.set_form("model", v)),
                            rx.el.datalist(rx.foreach(S.model_rows, lambda r: rx.el.option(r["name"], value=r["model"])),
                                           id="workspace-models"),
                            rx.text("Click the field to see the supported models, or type to narrow the list. "
                                    "Any text is accepted, for a model not listed.", size="1", color="var(--gray-10)"),
                            spacing="1", align="start", width="100%",
                        ),
                        field("MAC address", rx.input(value=S.form_mac, width="100%",
                                                      placeholder="AA:BB:CC:DD:EE:FF",
                                                      on_change=lambda v: S.set_form("mac", v)),
                              "Any separators are fine; it must have 12 hex digits."),
                        columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                    ),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add device",
                              on_click=S.add_single, disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Multiple devices", size="4"),
                    paste_csv_tabs(
                        S.paste_device, lambda v: S.set_paste("device", v),
                        "One device per line, columns separated by tabs (straight from Excel), pipes, semicolons "
                        "or commas. The header row is optional; without it the order is workspace, model, mac, "
                        "location (location is optional).",
                        "Lobby Room,Cisco 8845,AA:BB:CC:DD:EE:FF,Dallas",
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add devices",
                                  on_click=S.add_from_text, disabled=S.busy),
                        [
                            rx.text("Header row required: workspace, model and mac. location is optional.",
                                    size="2", color="var(--gray-11)"),
                            code_block("workspace,model,mac,location\n"
                                       "Lobby Room,Cisco 8845,AA:BB:CC:DD:EE:FF,Dallas\n"),
                            csv_dropzone("device_upload"),
                            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)),
                                      "Add devices",
                                      on_click=S.add_from_csv(rx.upload_files(upload_id="device_upload")),
                                      disabled=S.busy),
                        ],
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "Workspace / MAC"),
            spacing="4", align="start", width="100%",
        )),
    )


def migrate() -> rx.Component:
    S = MigrateState
    plan = rx.cond(
        S.plan_rows.length() > 0,
        rx.card(
            rx.vstack(
                rx.heading("Review", size="4"),
                rx.scroll_area(
                    rx.table.root(
                        rx.table.header(rx.table.row(
                            rx.table.column_header_cell("Number"), rx.table.column_header_cell("Owner"),
                            rx.table.column_header_cell("Result"), rx.table.column_header_cell("Reason"),
                        )),
                        rx.table.body(rx.foreach(S.plan_rows, lambda r: rx.table.row(
                            rx.table.cell(rx.code(r["number"])),
                            rx.table.cell(r["owner"]),
                            rx.table.cell(rx.badge(r["status"], color_scheme=rx.cond(
                                r["action"] == "move", "green", "gray"))),
                            rx.table.cell(r["reason"]),
                        ))),
                        variant="ghost", width="100%",
                    ),
                    max_height="40vh",
                ),
                rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("arrow-right-left", size=16)),
                          "Move " + S.move_count.to_string() + " user(s)...", color_scheme="red",
                          on_click=S.set_confirm_open(True), disabled=S.busy | (S.move_count == 0)),
                spacing="3", align="start", width="100%",
            ),
            size="3", width="100%",
        ),
        rx.fragment(),
    )
    return webex_page(
        "Migrate",
        need_login(rx.vstack(
            rx.callout("Moves users to another location. Their phone number and extension are kept. Only the "
                       "PRIMARY number of a user is acted on. Workspaces cannot be moved by the Webex API and are "
                       "skipped; recreate or move them in Control Hub.", icon="info", width="100%"),
            picker(S, "New location", columns=(("Name", "name"),)),
            rx.card(
                rx.vstack(
                    rx.heading("Numbers to migrate", size="4"),
                    field("Phone numbers", rx.text_area(value=S.numbers_text, on_change=S.set_numbers_text,
                                                        rows="4", width="100%",
                                                        placeholder="+14155551234\n4155551235"),
                          "One per line. E.164 or 10 digit US numbers. Or use a CSV below (it wins if chosen)."),
                    code_block("number\n+14155551234\n+14155551235\n"),
                    csv_dropzone("migrate_upload"),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("search", size=16)), "Review",
                              on_click=S.review(rx.upload_files(upload_id="migrate_upload")),
                              disabled=S.busy | ~S.has_selection),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            plan,
            run_results(S, "Number / owner"),
            confirm_dialog(S, "Move these users?",
                           "Validates and moves " + S.move_count.to_string() + " user(s) to " + S.selected_label
                           + ". Each move runs as a Webex job and can take a minute.", "Move users", S.run_migration),
            spacing="4", align="start", width="100%",
        )),
    )


def voicemail() -> rx.Component:
    S = VoicemailState
    return webex_page(
        "Voicemail",
        need_login(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.heading("One user", size="4"),
                    field("Email", rx.input(value=S.form_email, on_change=S.set_form_email, width="100%",
                                            placeholder="jane.doe@example.com")),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("voicemail", size=16)),
                              "Check user", on_click=S.report_user, disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Every user in a location", size="4"),
                    field("Location name", rx.fragment(
                        rx.input(
                            rx.input.slot(
                                rx.cond(S.form_location != "",
                                        rx.icon("x", size=16, cursor="pointer", aria_label="Clear location",
                                                on_click=S.set_form_location("")),
                                        rx.fragment()),
                                side="right",
                            ),
                            value=S.form_location, on_change=S.set_form_location, width="100%",
                            list="voicemail-locations", placeholder="Start typing to search",
                            auto_complete="off"),
                        rx.el.datalist(rx.foreach(S.location_names, lambda n: rx.el.option(value=n)),
                                       id="voicemail-locations"),
                    ), "Click the field to see every location, or type to narrow the list."),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("voicemail", size=16)),
                              "Check location", on_click=S.report_location, disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(S.busy, rx.hstack(rx.spinner(size="2"), rx.text(S.progress, size="2"), align="center",
                                      spacing="2"), rx.fragment()),
            rx.cond(
                S.rows.length() > 0,
                rx.vstack(
                    rx.hstack(
                        rx.heading(S.report_title, size="4"),
                        rx.badge(S.internal_count.to_string() + " internal", color_scheme="blue"),
                        rx.badge(S.external_count.to_string() + " external", color_scheme="orange"),
                        spacing="2", align="center",
                    ),
                    rx.card(
                        rx.scroll_area(
                            rx.table.root(
                                rx.table.header(rx.table.row(
                                    rx.table.column_header_cell("User"),
                                    rx.table.column_header_cell("Email"),
                                    rx.table.column_header_cell("Voicemail"),
                                    rx.table.column_header_cell("Mailbox"),
                                    rx.table.column_header_cell("Usage / destination"),
                                )),
                                rx.table.body(rx.foreach(S.rows, lambda r: rx.table.row(
                                    rx.table.cell(r["name"]),
                                    rx.table.cell(rx.code(r["email"])),
                                    rx.table.cell(r["enabled"]),
                                    rx.table.cell(rx.badge(r["storage"], color_scheme=rx.cond(
                                        r["storage"] == "Internal", "blue", "orange"))),
                                    rx.table.cell(r["details"]),
                                ))),
                                variant="ghost", width="100%",
                            ),
                            max_height="60vh",
                        ),
                        padding="0", width="100%",
                    ),
                    spacing="3", align="start", width="100%",
                ),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        )),
    )
