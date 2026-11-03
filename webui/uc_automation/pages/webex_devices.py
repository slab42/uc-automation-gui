import reflex as rx

from ..components.tool_widgets import (
    code_block, collapsible_card, confirm_dialog, one_multiple_card, csv_dropzone, field, paste_csv_tabs, run_results)
from ..components.webex_nav import webex_page
from ..state.webex_devices import BulkAtaState, CucmGatewayState, CucmMigrateState, DeviceMigrateState
from .webex_routing import need_login
from .webex_users import _models_info


def _combo(S, name: str, value, names, list_id: str, placeholder: str = "Start typing to search"):
    return rx.fragment(
        rx.input(
            rx.input.slot(
                rx.cond(value != "",
                        rx.icon("x", size=16, cursor="pointer", aria_label=f"Clear {name}",
                                on_click=S.set_form(name, "")),
                        rx.fragment()),
                side="right",
            ),
            value=value, width="100%", list=list_id, placeholder=placeholder, auto_complete="off",
            on_change=lambda v: S.set_form(name, v)),
        rx.el.datalist(rx.foreach(names, lambda n: rx.el.option(value=n)), id=list_id),
    )


def _upd_row(S, r, i) -> rx.Component:
    open_port = r["configured"] == ""
    is_new = r["kind"] == "New"
    return rx.table.row(
        rx.table.row_header_cell(r["port"]),
        rx.table.cell(rx.cond(open_port, rx.badge("Open", color_scheme="gray"), r["current"])),
        rx.table.cell(rx.cond(open_port, "", rx.text(r["line"], " ", r["ext"], size="2"))),
        rx.table.cell(rx.cond(open_port, rx.select(["Existing", "New"], value=r["kind"],
                                                   on_change=lambda v: S.set_upd_port(i, "kind", v)), "")),
        rx.table.cell(rx.cond(open_port, rx.input(
            value=r["workspace"], width="100%", list="upd-workspaces", auto_complete="off",
            placeholder=rx.cond(is_new, "New workspace name", "Search existing workspaces"),
            on_change=lambda v: S.set_upd_port(i, "workspace", v)), "")),
        rx.table.cell(rx.cond(open_port, rx.input(
            value=r["extension"], width="6rem", disabled=~is_new, placeholder="Ext",
            on_change=lambda v: S.set_upd_port(i, "extension", v)), "")),
        rx.table.cell(rx.cond(open_port, rx.input(
            value=r["number"], width="9rem", disabled=~is_new, placeholder="Number (optional)",
            on_change=lambda v: S.set_upd_port(i, "number", v)), "")),
        background=rx.cond((r["wid"] != "") & (r["wid"] == S.find_target), "var(--accent-3)", ""),
    )


def _port_section(S) -> rx.Component:
    """The port table and the Update Device button, shared by the Update ATA Or VG and Find Port tabs."""
    return rx.cond(
        S.upd_ports.length() > 0,
        rx.vstack(
            rx.text(S.upd_device, size="2", weight="medium"),
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell("Port"), rx.table.column_header_cell("Workspace"),
                    rx.table.column_header_cell("Line"), rx.table.column_header_cell("Assign"),
                    rx.table.column_header_cell("Workspace To Assign"),
                    rx.table.column_header_cell("Extension"), rx.table.column_header_cell("Number"))),
                rx.table.body(rx.foreach(S.upd_ports, lambda r, i: _upd_row(S, r, i))),
                width="100%",
            ),
            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("save", size=16)), "Update Device",
                      on_click=S.apply_upd, disabled=S.busy | (S.upd_open_count == 0)),
            spacing="3", align="start", width="100%",
        ),
        rx.fragment(),
    )


def _update_tab(S) -> list:
    return [
        rx.text("Pick an ATA or VG that is already in Webex. Its ports are listed with what is configured on each. "
                "An open port can get an existing workspace or a new one (a new workspace needs an extension or a "
                "number and is created in the location of the device).", size="2", color="var(--gray-11)"),
        field("ATA or VG", rx.hstack(
            rx.input(rx.input.slot(
                         rx.cond(S.upd_device != "",
                                 rx.icon("x", size=16, cursor="pointer", aria_label="Clear device",
                                         on_click=S.set_upd_device("")),
                                 rx.fragment()), side="right"),
                     value=S.upd_device, width="100%", list="upd-devices", auto_complete="off",
                     placeholder="Start typing a name or MAC address", on_change=S.set_upd_device),
            rx.button(rx.cond(S.upd_reading, rx.spinner(size="2"), rx.icon("refresh-cw", size=16)), "Load Ports",
                      variant="soft", on_click=S.read_upd_ports, disabled=S.upd_reading),
            width="100%", spacing="2"),
              "Click the field to see every ATA and VG in the org, or type to narrow the list."),
        _port_section(S),
    ]


def _find_tab(S) -> list:
    return [
        rx.text("Search workspaces by name, phone number or extension, then open one to load the ATA or VG it is "
                "configured on. The ports are the same as on the Update ATA Or VG tab.",
                size="2", color="var(--gray-11)"),
        field("Port search", rx.hstack(
            rx.input(value=S.find_text, width="100%", placeholder="Workspace name, phone number or extension",
                     on_change=S.set_find_text, on_key_down=lambda k: rx.cond(k == "Enter", S.search_find, rx.noop())),
            rx.button(rx.cond(S.find_searching, rx.spinner(size="2"), rx.icon("search", size=16)), "Search",
                      on_click=S.search_find, disabled=S.find_searching),
            width="100%", spacing="2")),
        rx.cond(
            S.find_results.length() > 0,
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell("Workspace"), rx.table.column_header_cell("Number / Extension"),
                    rx.table.column_header_cell("Location"), rx.table.column_header_cell(""))),
                rx.table.body(rx.foreach(S.find_results, lambda r: rx.table.row(
                    rx.table.row_header_cell(r["name"]), rx.table.cell(r["line"]), rx.table.cell(r["location"]),
                    rx.table.cell(rx.button("Open Gateway", size="1", variant="soft",
                                            on_click=S.pick_find(r["id"]), disabled=S.find_searching))))),
                width="100%",
            ),
            rx.fragment(),
        ),
        _port_section(S),
    ]


def bulk_ata() -> rx.Component:
    S = BulkAtaState
    return webex_page(
        "Bulk ATA/VG",
        need_login(rx.vstack(
            rx.callout("Each port gets its own new Webex Calling workspace. The device is added to the first "
                       "workspace, then every workspace is assigned to its port (the first line is port 1). "
                       "A workspace that already exists is not reused: the device is skipped.",
                       icon="info", width="100%"),
            one_multiple_card(
"One ATA Or VG", [
rx.grid(
                        field("Location", _combo(S, "location", S.form_location, S.location_names, "ata-locations"),
                              "Click the field to see every location, or type to narrow the list."),
                        rx.vstack(
                            rx.hstack(rx.text("Model", size="2", weight="medium"), _models_info(S),
                                      spacing="2", align="center"),
                            rx.input(value=S.form_model, width="100%", placeholder="Cisco ATA 192",
                                     list="ata-models", auto_complete="off",
                                     on_change=lambda v: S.set_form("model", v)),
                            rx.el.datalist(rx.foreach(S.model_rows, lambda r: rx.el.option(r["name"], value=r["model"])),
                                           id="ata-models"),
                            rx.text("Click the field to see the supported models. Any text is accepted.",
                                    size="1", color="var(--gray-10)"),
                            spacing="1", align="start", width="100%",
                        ),
                        field("MAC address", rx.input(value=S.form_mac, width="100%",
                                                      placeholder="AA:BB:CC:DD:EE:FF",
                                                      on_change=lambda v: S.set_form("mac", v)),
                              "Any separators are fine; it must have 12 hex digits."),
                        columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                    ),
field("Ports", rx.text_area(
                        value=S.form_ports, width="100%", rows="5",
                        placeholder="Front Desk Fax, 1001\nLobby Phone, 1002",
                        on_change=lambda v: S.set_form("ports", v)),
                        "One port per line, port 1 first: workspace name, extension, and optionally a phone number "
                        "(separated by a comma, tab, pipe or semicolon). Every port needs an extension or a number."),
rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add device",
                              on_click=S.add_single, disabled=S.busy),
], "Multiple ATAs Or VGs", [
paste_csv_tabs(
                        S.paste_ata, lambda v: S.set_paste("ata", v),
                        "One port per line, columns separated by tabs (straight from Excel), pipes, semicolons "
                        "or commas. Lines with the same MAC are the ports of one device, in order. The header row "
                        "is optional; without it the order is mac, model, location, workspace, extension, number. "
                        "Model and location are read from the first line of each device. Number is optional.",
                        "AA:BB:CC:DD:EE:FF,Cisco ATA 192,Dallas,Front Desk Fax,1001\n"
                        "AA:BB:CC:DD:EE:FF,,,Lobby Phone,1002",
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add devices",
                                  on_click=S.add_from_text, disabled=S.busy),
                        [
                            rx.text("Header row required: mac, workspace and extension. model, location and number "
                                    "are optional. One line per port; the same MAC groups ports into one device.",
                                    size="2", color="var(--gray-11)"),
                            code_block("mac,model,location,workspace,extension,number\n"
                                       "AA:BB:CC:DD:EE:FF,Cisco ATA 192,Dallas,Front Desk Fax,1001,\n"
                                       "AA:BB:CC:DD:EE:FF,,,Lobby Phone,1002,\n"),
                            csv_dropzone("ata_upload"),
                            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)),
                                      "Add devices",
                                      on_click=S.add_from_csv(rx.upload_files(upload_id="ata_upload")),
                                      disabled=S.busy),
                        ],
                    ),
], extra=[("Update ATA Or VG", _update_tab(S)), ("Find Port", _find_tab(S))]),
            rx.el.datalist(rx.foreach(S.upd_labels, lambda n: rx.el.option(value=n)), id="upd-devices"),
            rx.el.datalist(rx.foreach(S.upd_workspaces, lambda n: rx.el.option(value=n)), id="upd-workspaces"),
            run_results(S, "MAC"),
            spacing="4", align="start", width="100%",
        )),
    )


def _login_badge(status, message) -> rx.Component:
    """Login status of the org picked on one side (status is "", "checking", "ok" or "fail")."""
    return rx.match(
        status,
        ("checking", rx.badge("Checking", color_scheme="gray", flex_shrink="0")),
        ("ok", rx.badge("Logged in", color_scheme="green", flex_shrink="0")),
        ("fail", rx.tooltip(rx.badge("Login required", color_scheme="red", flex_shrink="0"), content=message)),
        rx.fragment(),
    )


def _side(S, org, user, mac, key: str, names=None, label: str = "Org", pick: str = "org",
          user_hint: str = "Email or display name. Where the phone goes, or, on the source side, who has it now "
                           "(optional).", status=None, status_msg=None) -> rx.Component:
    """One side of a migrate page: Org (or CUCM connection), User and MAC (key is "l" or "r")."""
    return rx.card(
        rx.vstack(
            field(label, rx.hstack(
                rx.box(
                    rx.select(S.all_org_names if names is None else names, value=org,
                              on_change=lambda v: S.set_side(f"{pick}_{key}", v),
                              width="100%", placeholder=f"Pick a {'connection' if pick == 'conn' else 'org'}"),
                    flex="1", min_width="0",
                ),
                *([_login_badge(status, status_msg)] if status is not None else []),
                spacing="2", align="center", width="100%",
            )),
            field("User", rx.input(value=user, width="100%", placeholder="user@example.com",
                                   on_change=lambda v: S.set_side(f"user_{key}", v)), user_hint),
            field("MAC", rx.input(value=mac, width="100%", placeholder="AA:BB:CC:DD:EE:FF",
                                  on_change=lambda v: S.set_side(f"mac_{key}", v)),
                  "Any separators are fine; it must have 12 hex digits."),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )


def device_migrate() -> rx.Component:
    S = DeviceMigrateState

    def arrow(icon: str, label: str, side: str) -> rx.Component:
        return rx.tooltip(
            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon(icon, size=22)),
                      on_click=S.migrate_to(side), disabled=S.busy, size="3", aria_label=label),
            content=label,
        )

    return webex_page(
        "Webex-Webex Phone Migrate",
        need_login(rx.vstack(
            rx.popover.root(
                rx.popover.trigger(rx.button(rx.icon("info", size=16), "How it works", variant="soft", size="1")),
                rx.popover.content(
                    rx.text("Moves a physical phone to a user in another Webex org. Press an arrow: the phone with "
                            "the MAC on the side the arrow leaves is deleted from its org, then added by MAC to the "
                            "user on the side it points to (it is added back if that fails). Calling settings and "
                            "numbers do not move: set up the destination user first. Factory reset the phone "
                            "afterwards so it registers with the new org.", size="2"),
                    max_width="420px",
                ),
            ),
            rx.grid(
                _side(S, S.org_l, S.user_l, S.mac_l, "l", status=S.login_l, status_msg=S.login_msg_l),
                rx.vstack(
                    arrow("arrow-right", "Move the phone from the left org to the right org", "r"),
                    arrow("arrow-left", "Move the phone from the right org to the left org", "l"),
                    spacing="3", align="center", justify="center",
                ),
                _side(S, S.org_r, S.user_r, S.mac_r, "r", status=S.login_r, status_msg=S.login_msg_r),
                columns=rx.breakpoints(initial="1", md="minmax(0, 1fr) auto minmax(0, 1fr)"),
                spacing="4", align="center", width="100%",
            ),
            collapsible_card(
                "Migrate multiple phones", S.multi_open, S.toggle_multi,
                rx.hstack(
                    rx.text("Direction", size="2", weight="medium"),
                    rx.segmented_control.root(
                        rx.segmented_control.item("Left To Right", value="Left To Right"),
                        rx.segmented_control.item("Right To Left", value="Right To Left"),
                        value=S.bulk_dir, on_change=S.set_bulk_dir,
                    ),
                    spacing="3", align="center",
                ),
                paste_csv_tabs(
                    S.paste_phone, lambda v: S.set_paste("phone", v),
                    "One phone per line, columns separated by tabs (straight from Excel), pipes, semicolons "
                    "or commas. The header row is optional; without it the order is mac, user. The user is "
                    "the destination user, an email or a display name.",
                    "AA:BB:CC:DD:EE:FF,user@example.com",
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("arrow-right-left", size=16)),
                              "Migrate phones", on_click=S.migrate_from_text, disabled=S.busy),
                    [
                        rx.text("Header row required: mac and user.", size="2", color="var(--gray-11)"),
                        code_block("mac,user\nAA:BB:CC:DD:EE:FF,user@example.com\n"),
                        csv_dropzone("phone_upload"),
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)),
                                  "Migrate phones",
                                  on_click=S.migrate_from_csv(rx.upload_files(upload_id="phone_upload")),
                                  disabled=S.busy),
                    ],
                ),
            ),
            confirm_dialog(S, "Migrate these phones?", S.confirm_text, "Migrate", S.confirm_migrate),
            run_results(S, "MAC"),
            spacing="4", align="start", width="100%",
        )),
        show_org=False,
    )


def cucm_migrate() -> rx.Component:
    S = CucmMigrateState

    def arrow(icon: str, label: str, on_click) -> rx.Component:
        return rx.tooltip(
            rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon(icon, size=22)),
                      on_click=on_click, disabled=S.busy, size="3", aria_label=label),
            content=label,
        )

    return webex_page(
        "CUCM-Webex Phone Migrate",
        need_login(rx.vstack(
            rx.callout("Tool still under development.", icon="construction", color_scheme="amber", width="100%"),
            rx.popover.root(
                rx.popover.trigger(rx.button(rx.icon("info", size=16), "How it works", variant="soft", size="1")),
                rx.popover.content(
                    rx.text("Left is CUCM, right is Webex. The right arrow adds the phone with the MAC on the left to "
                            "the Webex user on the right; the CUCM phone is kept. The left arrow deletes the phone "
                            "with the MAC on the right from Webex; its configuration must already exist in CUCM. "
                            "The User on the CUCM side and, going left, on the Webex side are optional ownership "
                            "checks. Going to Webex, factory reset the phone afterwards. Going to CUCM, the phone must "
                            "still be converted to Enterprise firmware: open http://<phone IP>/admin/advanced, "
                            "Voice > Provisioning, set the Profile Rule to "
                            "https://cloudupgrader.webex.com/Cisco/M2E/$SWVER/$PN/$MA.cfg and save.",
                            size="2"),
                    max_width="420px",
                ),
            ),
            rx.grid(
                _side(S, S.conn_l, S.user_l, S.mac_l, "l", S.cucm_names, "CUCM", "conn",
                      "CUCM user ID. Optional: the phone must be owned by this user."),
                rx.vstack(
                    arrow("arrow-right", "Add the phone to Webex (the CUCM phone is kept)", S.migrate_to_webex),
                    arrow("arrow-left", "Delete the phone from Webex (it is configured in CUCM)", S.migrate_to_cucm),
                    spacing="3", align="center", justify="center",
                ),
                _side(S, S.org_r, S.user_r, S.mac_r, "r", None, "Webex Org", "org",
                      "Email or display name. Where the phone goes; going left, who has it now (optional)."),
                columns=rx.breakpoints(initial="1", md="minmax(0, 1fr) auto minmax(0, 1fr)"),
                spacing="4", align="center", width="100%",
            ),
            collapsible_card(
                "Migrate multiple phones", S.multi_open, S.toggle_multi,
                rx.hstack(
                    rx.text("Direction", size="2", weight="medium"),
                    rx.segmented_control.root(
                        rx.segmented_control.item("CUCM To Webex", value="CUCM To Webex"),
                        rx.segmented_control.item("Webex To CUCM", value="Webex To CUCM"),
                        value=S.bulk_dir, on_change=S.set_bulk_dir,
                    ),
                    spacing="3", align="center",
                ),
                paste_csv_tabs(
                    S.paste_phone, lambda v: S.set_paste("phone", v),
                    "One phone per line, columns separated by tabs (straight from Excel), pipes, semicolons "
                    "or commas. The header row is optional; without it the order is mac, user. To Webex the user is "
                    "the Webex user (required); to CUCM it is the CUCM owner to check (leave it empty to skip).",
                    "AA:BB:CC:DD:EE:FF,user@example.com",
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("arrow-right-left", size=16)),
                              "Migrate phones", on_click=S.migrate_from_text, disabled=S.busy),
                    [
                        rx.text("Header row required: mac and user.", size="2", color="var(--gray-11)"),
                        code_block("mac,user\nAA:BB:CC:DD:EE:FF,user@example.com\n"),
                        csv_dropzone("cucm_phone_upload"),
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)),
                                  "Migrate phones",
                                  on_click=S.migrate_from_csv(rx.upload_files(upload_id="cucm_phone_upload")),
                                  disabled=S.busy),
                    ],
                ),
            ),
            confirm_dialog(S, "Migrate these phones?", S.confirm_text, "Migrate", S.confirm_migrate),
            run_results(S, "MAC"),
            spacing="4", align="start", width="100%",
        )),
    )


def _port_row(S, r, i) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.checkbox(checked=r["include"] != "", disabled=r["port"] == "1",
                                  on_change=lambda v: S.toggle_row(i, v))),
        rx.table.cell(rx.input(value=r["port"], width="4rem", on_change=lambda v: S.set_row(i, "port", v))),
        rx.table.cell(rx.input(value=r["workspace"], width="100%",
                               on_change=lambda v: S.set_row(i, "workspace", v))),
        rx.table.cell(rx.input(value=r["line"], width="100%", on_change=lambda v: S.set_row(i, "line", v))),
    )


def cucm_gateway() -> rx.Component:
    S = CucmGatewayState
    return webex_page(
        "CUCM-Webex Analog Gateway Migrate",
        need_login(rx.vstack(
            rx.callout("Reads an analog gateway from CUCM and creates a Webex Calling workspace for port 1 and for "
                       "any other ports you tick. Nothing is changed in CUCM. Not tested against a real CUCM or "
                       "Webex org: check the port numbers before you create.",
                       icon="info", width="100%"),
            rx.card(
                rx.vstack(
                    rx.heading("1. CUCM Gateway", size="4"),
                    rx.grid(
                        field("CUCM", rx.select(S.cucm_names, value=S.conn, placeholder="Pick a connection",
                                                width="100%", on_change=lambda v: S.set_field("conn", v))),
                        field("Gateway name", rx.hstack(
                            rx.input(value=S.gateway, width="100%", placeholder="AN001122334455",
                                     list="gw-names", auto_complete="off",
                                     on_change=lambda v: S.set_field("gateway", v)),
                            rx.el.datalist(rx.foreach(S.gateway_names, lambda n: rx.el.option(value=n)), id="gw-names"),
                            rx.button("List", variant="soft", on_click=S.list_gateways, disabled=S.reading),
                            width="100%", spacing="2"),
                              "For an SCCP gateway this is AN plus the MAC address. List shows the analog gateways of "
                              "the connection."),
                        columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                    ),
                    rx.button(rx.cond(S.reading, rx.spinner(size="2"), rx.icon("search", size=16)), "Read Gateway",
                              on_click=S.read_gateway, disabled=S.reading),
                    spacing="3", align="start", width="100%",
                ),
                width="100%",
            ),
            rx.cond(
                S.port_rows.length() > 0,
                rx.card(
                    rx.vstack(
                        rx.heading("2. Ports", size="4"),
                        rx.text("Tick the ports that get a workspace. Port 1 is always created. Edit the port number, "
                                "workspace name or line if needed. A line starting with + or with 10 or more digits "
                                "is a phone number, anything else is an extension.",
                                size="2", color="var(--gray-11)"),
                        rx.table.root(
                            rx.table.header(rx.table.row(
                                rx.table.column_header_cell("Create"), rx.table.column_header_cell("Port"),
                                rx.table.column_header_cell("Workspace Name"),
                                rx.table.column_header_cell("Extension Or Number"))),
                            rx.table.body(rx.foreach(S.port_rows, lambda r, i: _port_row(S, r, i))),
                            variant="ghost", width="100%",
                        ),
                        spacing="3", align="start", width="100%",
                    ),
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.card(
                rx.vstack(
                    rx.heading("3. Webex", size="4"),
                    field("Location", _combo(S, "location", S.location, S.location_names, "gw-locations"),
                          "Click the field to see every location, or type to narrow the list."),
                    field("Device", rx.segmented_control.root(
                        rx.segmented_control.item("Add Device Now", value="Add Device Now"),
                        rx.segmented_control.item("Add Device Later", value="Add Device Later"),
                        value=S.mode, on_change=S.set_mode),
                          "Now adds the device to the port 1 workspace and assigns the other ports. Later only creates "
                          "the workspaces; add the device afterwards with Add Device."),
                    rx.checkbox("Use an existing workspace when the name already exists", checked=S.use_existing,
                                on_change=S.set_use_existing),
                    rx.text("Off: a name that already exists stops the run. On: that workspace is assigned to the port "
                            "as it is (nothing is changed on it) and only the missing ones are created.",
                            size="1", color="var(--gray-10)"),
                    rx.cond(
                        S.add_now,
                        rx.grid(
                            rx.vstack(
                                rx.hstack(rx.text("Model", size="2", weight="medium"), _models_info(S),
                                          spacing="2", align="center"),
                                rx.input(value=S.model, width="100%", placeholder="Cisco VG400",
                                         list="gw-models", auto_complete="off",
                                         on_change=lambda v: S.set_field("model", v)),
                                rx.el.datalist(rx.foreach(S.model_rows,
                                                          lambda r: rx.el.option(r["name"], value=r["model"])),
                                               id="gw-models"),
                                rx.text("Click the field to see the supported models.", size="1",
                                        color="var(--gray-10)"),
                                spacing="1", align="start", width="100%",
                            ),
                            field("MAC address", rx.input(value=S.mac, width="100%", placeholder="AA:BB:CC:DD:EE:FF",
                                                          on_change=lambda v: S.set_field("mac", v)),
                                  "Filled from the gateway name when it is AN plus a MAC."),
                            columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                        ),
                        rx.fragment(),
                    ),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)),
                              rx.cond(S.add_now, "Create Workspaces And Add Device", "Create Workspaces"),
                              on_click=S.migrate, disabled=S.busy | (S.port_rows.length() == 0)),
                    spacing="3", align="start", width="100%",
                ),
                width="100%",
            ),
            run_results(S, "Gateway"),
            spacing="4", align="start", width="100%",
        )),
        show_org=True,
    )
