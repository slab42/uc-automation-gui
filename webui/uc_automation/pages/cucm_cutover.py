import reflex as rx

from ..components import sme_settings
from ..components.cucm_nav import cucm_page
from ..components.tool_widgets import code_block, confirm_dialog, csv_dropzone, field, paste_csv_tabs, run_results
from ..state.cucm_cutover import CutoverState
from .tools import _need_connection

S = CutoverState

_EXAMPLE = "dn,partition\n5558594400,Phone-Line1-PT\n5558594401\n"


def _settings_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Cutover Settings"),
            rx.vstack(
                rx.text("Partitions for the directory numbers. A DN with its own partition in the list uses that one.",
                        size="2", color="var(--gray-11)"),
                field("Default Partition", rx.input(value=S.src_partition, on_change=S.set_src_partition, width="100%",
                                                    placeholder="Where the DNs are now (blank = none)"),
                      "Used for list lines without a partition."),
                field("Destination Partition", rx.input(value=S.dest_partition, on_change=S.set_dest_partition,
                                                        width="100%", placeholder="Move Partition target"),
                      "Move Partition sends every DN here."),
                rx.vstack(
                    rx.heading("SME Cluster", size="3"),
                    rx.cond(
                        S.sme_names.length() > 0,
                        rx.hstack(rx.text("Step 3 runs on:", size="2"), rx.badge(S.sme_selected, variant="soft"),
                                  rx.badge("SME", color_scheme="green"), align="center", spacing="2"),
                        rx.text("No SME cluster in this organization.", size="2", color="var(--red-11)"),
                    ),
                    rx.text("The SME cluster of the active organization is used.", size="2", color="var(--gray-11)"),
                    spacing="2", align="start", width="100%",
                ),
                rx.divider(),
                sme_settings.variables_section(S), rx.divider(),
                sme_settings.advertise_section(S), rx.divider(),
                sme_settings.route_section(S),
                rx.text("These settings are shared with SME Adv & Route Patterns: changing them here changes them there.",
                        size="2", color="var(--gray-11)"),
                rx.cond(S.settings_error != "", rx.callout(S.settings_error, icon="triangle-alert", color_scheme="red",
                                                           width="100%"), rx.fragment()),
                rx.hstack(
                    rx.button("Reset SME Settings", variant="soft", color_scheme="gray", on_click=S.reset_settings),
                    rx.spacer(), rx.button("Done", on_click=S.set_settings_open(False)), width="100%", align="center"),
                spacing="4", align="start", width="100%",
            ),
            max_width="640px", max_height="85vh", overflow_y="auto",
        ),
        open=S.settings_open, on_open_change=S.set_settings_open,
    )


def _sme_card() -> rx.Component:
    return rx.cond(
        (S.sme_names.length() == 0) | (S.used_var_rows.length() > 0) | (S.settings_error != ""),
        rx.card(rx.vstack(
            rx.cond(S.sme_names.length() == 0,
                    rx.callout("No connection of this organization is marked as an SME cluster. Tick SME cluster on "
                               "Credentials > CUCM.", icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.cond(S.used_var_rows.length() > 0, rx.grid(
                rx.foreach(S.used_var_rows, lambda v: field(v["display"], sme_settings.value_input(S, v))),
                columns="2", spacing="3", width="100%"), rx.fragment()),
            rx.cond(S.settings_error != "", rx.callout(S.settings_error, icon="triangle-alert", color_scheme="red",
                                                       width="100%"), rx.fragment()),
            spacing="3", align="start", width="100%",
        ), width="100%"),
        rx.fragment(),
    )


def _input_card() -> rx.Component:
    return rx.card(rx.vstack(
        rx.heading("Directory Numbers", size="3"),
        paste_csv_tabs(
            S.paste_text, S.set_paste_text,
            "One DN per line, optional partition second (tab, pipe, semicolon or comma). A header row is optional. "
            "Lines without a partition use the Default Partition in Settings.",
            _EXAMPLE.split("\n", 1)[1].rstrip(),
            rx.text(S.dn_count.to_string(), " directory number(s) in the list", size="2", color="var(--gray-11)"),
            [
                rx.text("Columns: dn, partition (optional). The file fills the Paste Text box.", size="2",
                        color="var(--gray-11)"),
                code_block(_EXAMPLE),
                csv_dropzone("cutover_upload"),
                rx.button(rx.icon("upload", size=16), "Load CSV", on_click=S.load_csv(rx.upload_files(upload_id="cutover_upload"))),
            ],
        ),
        spacing="3", align="start", width="100%",
    ), width="100%")


def _buttons() -> rx.Component:
    return rx.card(rx.vstack(
        rx.heading("Cutover Steps", size="3"),
        rx.text("Each button runs only its own step on every DN in the list.", size="2", color="var(--gray-11)"),
        rx.hstack(
            rx.button(rx.icon("phone-off", size=16), "1. Remove Alt Numbers", color_scheme="red",
                      on_click=S.set_confirm_alt(True), disabled=S.busy | (S.dn_count == 0)),
            rx.button(rx.icon("folder-input", size=16), "2. Move Partition", color_scheme="red",
                      on_click=S.set_confirm_move(True), disabled=S.busy | (S.dn_count == 0)),
            rx.button(rx.icon("route", size=16), "3. SME Add AdvP-RP", on_click=S.run_sme,
                      disabled=S.busy | (S.dn_count == 0) | (S.sme_names.length() == 0) | (S.settings_error != "")),
            spacing="3", wrap="wrap",
        ),
        spacing="3", align="start", width="100%",
    ), width="100%")


def webex_cutover() -> rx.Component:
    return cucm_page(
        "Webex Cutover",
        _need_connection(S, rx.vstack(
            rx.hstack(
                rx.text("Cutover steps for a list of directory numbers when migrating to Webex Calling. Steps 1 and 2 "
                        "run on the selected cluster, step 3 on the SME cluster.", size="2", color="var(--gray-11)"),
                rx.spacer(),
                rx.tooltip(rx.icon_button(rx.icon("settings", size=18), variant="soft",
                                          on_click=S.set_settings_open(True), aria_label="Settings"),
                           content="Settings"),
                align="center", width="100%",
            ),
            _input_card(),
            _sme_card(),
            _buttons(),
            run_results(S, "Directory Number"),
            spacing="4", align="start", width="100%",
        )),
        _settings_dialog(),
        confirm_dialog(S, "Remove alternate numbers?",
                       "Clears the enterprise and E.164 alternate numbers of every DN in the list. The DNs are kept.",
                       "Remove", S.run_remove_alt, open_var=S.confirm_alt, set_open=S.set_confirm_alt),
        confirm_dialog(S, "Move to the destination partition?",
                       rx.text("Moves every DN in the list to ", rx.code(S.dest_partition), "."),
                       "Move", S.run_move, open_var=S.confirm_move, set_open=S.set_confirm_move),
    )
