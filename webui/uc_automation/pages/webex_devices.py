import reflex as rx

from ..components.tool_widgets import code_block, csv_dropzone, field, paste_csv_tabs, run_results
from ..components.webex_nav import webex_page
from ..state.webex_devices import BulkAtaState
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


def bulk_ata() -> rx.Component:
    S = BulkAtaState
    return webex_page(
        "Bulk ATA/VG",
        need_login(rx.vstack(
            rx.callout("Each port gets its own new Webex Calling workspace. The device is added to the first "
                       "workspace, then every workspace is assigned to its port (the first line is port 1). "
                       "A workspace that already exists is not reused: the device is skipped.",
                       icon="info", width="100%"),
            rx.card(
                rx.vstack(
                    rx.heading("Add one ATA or VG", size="4"),
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
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Multiple ATAs or VGs", size="4"),
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
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, "MAC"),
            spacing="4", align="start", width="100%",
        )),
    )
