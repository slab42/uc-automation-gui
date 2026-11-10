import reflex as rx

from ..components import sme_settings
from ..components.cucm_nav import cucm_page
from ..components.tool_widgets import code_block, csv_dropzone, field, one_multiple_card, paste_csv_tabs, run_results
from ..state.cucm_sme_patterns import SmePatternsState

S = SmePatternsState


def _cluster_section() -> rx.Component:
    return sme_settings.section(
        "Cluster",
        rx.text("Patterns are added on this cluster.", size="2", color="var(--gray-11)"),
        rx.hstack(
            rx.text("SME cluster:", size="2"),
            rx.badge(rx.cond(S.sme_selected != "", S.sme_selected, "None"), variant="soft"),
            rx.cond(S.is_sme, rx.badge("SME", color_scheme="green"),
                    rx.badge("Not Marked As SME", color_scheme="red")),
            align="center", spacing="2", wrap="wrap",
        ),
    )


def _settings_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("SME Pattern Settings"),
            rx.vstack(
                _cluster_section(), rx.divider(),
                sme_settings.variables_section(S), rx.divider(),
                sme_settings.advertise_section(S), rx.divider(),
                sme_settings.route_section(S),
                rx.cond(S.settings_error != "",
                        rx.callout(S.settings_error, icon="triangle-alert", color_scheme="red", width="100%"),
                        rx.fragment()),
                rx.hstack(
                    rx.button("Reset To Defaults", variant="soft", color_scheme="gray", on_click=S.reset_settings),
                    rx.spacer(),
                    rx.button("Done", on_click=S.set_settings_open(False)),
                    width="100%", align="center",
                ),
                spacing="4", align="start", width="100%",
            ),
            max_width="640px", max_height="85vh", overflow_y="auto",
        ),
        open=S.settings_open, on_open_change=S.set_settings_open,
    )


def _status() -> rx.Component:
    return rx.vstack(
        rx.cond(
            ~S.is_sme,
            rx.callout("This organization has no SME cluster. Tick SME cluster on the connection in Credentials > CUCM.",
                       icon="triangle-alert", color_scheme="red", width="100%"),
            rx.cond(
                ~S.ready,
                rx.callout(rx.cond(S.settings_error != "", S.settings_error,
                                   "Check the settings (gear icon, top right)."),
                           icon="info", width="100%"),
                rx.callout(rx.hstack("Ready to add on ", rx.code(S.sme_selected), ".", spacing="1"),
                           icon="circle-check", color_scheme="green", width="100%"),
            ),
        ),
        width="100%",
    )


def sme_patterns() -> rx.Component:
    run_disabled = S.busy | ~S.ready
    return cucm_page(
        "SME Adv & Route Patterns",
        rx.vstack(
            rx.hstack(
                rx.text("Adds an Advertised Pattern and its matching Route Pattern for each number.", size="2",
                        color="var(--gray-11)"),
                rx.spacer(),
                rx.tooltip(rx.icon_button(rx.icon("settings", size=18), variant="soft", on_click=S.set_settings_open(True),
                                          aria_label="Settings"), content="Settings"),
                align="center", width="100%",
            ),
            _status(),
            one_multiple_card(
                "One Pattern", [
                    rx.grid(
                        field("Pattern", rx.input(value=S.form_pattern, on_change=S.set_form_pattern, width="100%",
                                                  placeholder="5558594400")),
                        rx.foreach(S.var_rows, lambda v: field(v["display"], sme_settings.value_input(S, v))),
                        columns="2", spacing="3", width="100%",
                    ),
                    rx.text("10 digit numbers become +1 numbers (and \\+1 for the Route Pattern).", size="2",
                            color="var(--gray-11)"),
                    rx.button(rx.icon("plus", size=16), "Add Patterns", on_click=S.run_single, disabled=run_disabled),
                ],
                "Multiple Patterns", [
                    paste_csv_tabs(
                        S.paste_text, lambda v: S.set_paste("text", v),
                        "Columns: " + S.paste_columns + ". One per line (tab, pipe, semicolon or comma); a header row is "
                        "optional. The fields on the One Pattern tab are used for missing values.",
                        S.paste_placeholder,
                        rx.button(rx.icon("plus", size=16), "Add Patterns", on_click=S.run_text, disabled=run_disabled),
                        [
                            rx.text("Header row required. Columns: ", S.paste_columns, ". The variable columns are optional.",
                                    size="2", color="var(--gray-11)"),
                            code_block(S.csv_example),
                            csv_dropzone("sme_upload"),
                            rx.button(rx.icon("plus", size=16), "Add Patterns",
                                      on_click=S.run_csv(rx.upload_files(upload_id="sme_upload")),
                                      disabled=run_disabled),
                        ],
                    ),
                ],
            ),
            run_results(S, "Pattern"),
            spacing="4", align="start", width="100%",
        ),
        _settings_dialog(),
        show_instance=False,
    )
