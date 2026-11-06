import reflex as rx

from ..components.cucm_nav import cucm_page
from ..components.tool_widgets import code_block, csv_dropzone, field, one_multiple_card, paste_csv_tabs, run_results
from ..state.cucm_sme_patterns import SmePatternsState
from .tools import _need_connection

S = SmePatternsState


def _section(title: str, *children: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.heading(title, size="3"),
        *children,
        spacing="3", align="start", width="100%",
    )


# Clicking a variable button inserts {VarN} at the cursor of the description box that was focused last
# (the Advertise Pattern one when none was). The browser keeps each box's cursor while focus is elsewhere.
_INSERT_JS = """((k) => {
  const el = document.getElementById(window.__smeDesc || 'sme_adv_desc_input');
  if (!el) return;
  const a = el.selectionStart ?? el.value.length, b = el.selectionEnd ?? a, t = '{' + k + '}';
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  set.call(el, el.value.slice(0, a) + t + el.value.slice(b));
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.focus();
  el.setSelectionRange(a + t.length, a + t.length);
})('"""


def _desc_input(key: str, value, placeholder: str) -> rx.Component:
    box_id = f"sme_{key}_input"
    return _setting_input(key, value, id=box_id, placeholder=placeholder,
                          on_focus=rx.call_script(f"window.__smeDesc = '{box_id}'"))


def _setting_input(key: str, value, **props) -> rx.Component:
    return rx.input(value=value, on_change=lambda v: S.set_setting(key, v), width="100%", **props)


def _radio(key: str, value, choices) -> rx.Component:
    """Radio list of [value, label] pairs bound to a setting."""
    return rx.radio_group.root(
        rx.vstack(
            rx.foreach(choices, lambda c: rx.text(
                rx.hstack(rx.radio_group.item(value=c[0]), c[1], align="center", spacing="2"), as_="label", size="2")),
            spacing="2", align="start"),
        value=value, on_change=lambda v: S.set_setting(key, v),
    )


def _cluster_section() -> rx.Component:
    return _section(
        "Cluster",
        rx.text("Patterns are added on this cluster.", size="2", color="var(--gray-11)"),
        rx.hstack(
            rx.text("Active cluster:", size="2"),
            rx.badge(rx.cond(S.active != "", S.active, "None"), variant="soft"),
            rx.cond(S.is_sme, rx.badge("SME", color_scheme="green"),
                    rx.badge("Not Marked As SME", color_scheme="red")),
            align="center", spacing="2", wrap="wrap",
        ),
    )


def _variables_section() -> rx.Component:
    return _section(
        "Variables",
        rx.text("Var1 to Var9 (up to 9). Each is entered on the main screen as Var1 - Name. Use {Var1}, {Var2}... "
                "in the descriptions below. Click a variable button to insert it at the cursor in a description box.", size="2", color="var(--gray-11)"),
        rx.foreach(S.var_rows, lambda v: rx.hstack(
            rx.button(v["key"], size="1", variant="soft", type="button", title="Insert into the description",
                      on_click=rx.call_script(_INSERT_JS + v["key"] + "')")),
            rx.input(value=v["name"], on_change=lambda val: S.set_var_name(v["key"], val), placeholder="Name",
                     width="100%"),
            rx.cond(v["index"] != "0",
                    rx.icon_button(rx.icon("x", size=14), variant="ghost", color_scheme="gray",
                                   on_click=S.remove_variable(v["key"]), aria_label="Remove variable"),
                    rx.box(width="28px")),
            align="center", spacing="2", width="100%")),
        rx.button(rx.icon("plus", size=14), "Add Variable", size="1", variant="soft", on_click=S.add_variable,
                  disabled=~S.can_add_var),
    )


def _advertise_section() -> rx.Component:
    return _section(
        "Advertise Pattern Settings",
        field("Description", _desc_input("adv_desc", S.adv_desc, "{Var1} Webex Calling {Pattern}"),
              "{Var1}, {Var2}... and {Pattern} are filled from the main screen. {Pattern} is the last 10 digits."),
        rx.text("Example: ", S.adv_preview, size="1", color="var(--gray-10)"),
        field("Pattern Type", rx.radio_group.root(
            rx.hstack(
                rx.foreach(S.pattern_types, lambda t: rx.text(
                    rx.hstack(rx.radio_group.item(value=t), rx.cond(t == "+E.164 Number", "+E164 Number Pattern",
                                                                    "Enterprise Number Pattern"),
                              align="center", spacing="2"), as_="label", size="2")),
                spacing="4"),
            value=S.adv_type, on_change=lambda v: S.set_setting("adv_type", v))),
        field("PSTN Setting", _radio("pstn_rule", S.pstn_rule, S.pstn_choices)),
        rx.cond(
            S.pstn_rule == "Specify",
            rx.grid(
                field("PSTN Failover Strip Digits", _setting_input("pstn_strip", S.pstn_strip, type="number", min=0)),
                field("PSTN Failover Prepend Digits", _setting_input("pstn_prepend", S.pstn_prepend)),
                columns="2", spacing="3", width="100%",
            ),
            rx.fragment(),
        ),
    )


def _route_section() -> rx.Component:
    return _section(
        "Route Pattern Settings",
        field("Description", _desc_input("rp_desc", S.rp_desc, "{Var1} DID to Webex Calling"),
              "Same placeholders as the Advertise Pattern description."),
        rx.text("Example: ", S.rp_preview, size="1", color="var(--gray-10)"),
        field("Route Partition", _setting_input("rp_partition", S.rp_partition)),
        field("Destination", rx.segmented_control.root(
            rx.foreach(S.dest_types, lambda t: rx.segmented_control.item(t, value=t)),
            value=S.rp_dest_type, on_change=lambda v: S.set_setting("rp_dest_type", v))),
        field(rx.cond(S.rp_dest_type == "Gateway", "Gateway Name", "Route List Name"),
              _setting_input("rp_dest", S.rp_dest)),
    )


def _settings_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("SME Pattern Settings"),
            rx.vstack(
                _cluster_section(), rx.divider(),
                _variables_section(), rx.divider(),
                _advertise_section(), rx.divider(),
                _route_section(),
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
            rx.callout("The selected connection is not marked as an SME cluster. This tool only works on an SME "
                       "cluster: pick one above, or tick SME cluster on Credentials > CUCM.",
                       icon="triangle-alert", color_scheme="red", width="100%"),
            rx.cond(
                ~S.ready,
                rx.callout(rx.cond(S.settings_error != "", S.settings_error,
                                   "Check the settings (gear icon, top right)."),
                           icon="info", width="100%"),
                rx.callout(rx.hstack("Ready to add on ", rx.code(S.active), ".", spacing="1"),
                           icon="circle-check", color_scheme="green", width="100%"),
            ),
        ),
        width="100%",
    )


def sme_patterns() -> rx.Component:
    run_disabled = S.busy | ~S.ready
    return cucm_page(
        "SME Adv & Route Patterns",
        _need_connection(S, rx.vstack(
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
                        rx.foreach(S.var_rows, lambda v: field(
                            v["label"], rx.input(value=v["value"], on_change=lambda val: S.set_form_value(v["key"], val),
                                                 width="100%"))),
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
        )),
        _settings_dialog(),
    )
