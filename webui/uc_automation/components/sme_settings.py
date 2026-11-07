"""SME pattern settings sections (variables, Advertise Pattern, Route Pattern) for a state with SmeSettingsMixin.

Used by the settings windows of SME Adv & Route Patterns and Webex Cutover."""

import reflex as rx

from .tool_widgets import field


def section(title: str, *children: rx.Component) -> rx.Component:
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


def _desc_input(S, key: str, value, placeholder: str) -> rx.Component:
    box_id = f"sme_{key}_input"
    return _setting_input(S, key, value, id=box_id, placeholder=placeholder,
                          on_focus=rx.call_script(f"window.__smeDesc = '{box_id}'"))


def _setting_input(S, key: str, value, **props) -> rx.Component:
    return rx.input(value=value, on_change=lambda v: S.set_setting(key, v), width="100%", **props)


def _radio(S, key: str, value, choices) -> rx.Component:
    """Radio list of [value, label] pairs bound to a setting."""
    return rx.radio_group.root(
        rx.vstack(
            rx.foreach(choices, lambda c: rx.text(
                rx.hstack(rx.radio_group.item(value=c[0]), c[1], align="center", spacing="2"), as_="label", size="2")),
            spacing="2", align="start"),
        value=value, on_change=lambda v: S.set_setting(key, v),
    )


def variables_section(S) -> rx.Component:
    return section(
        "Variables",
        rx.text("Var1 to Var9 (up to 9). Each is entered on the main screen under its Name. Use {Var1}, {Var2}... "
                "in the descriptions below. Click a variable button to insert it at the cursor in a description box. A regex "
                "is checked against the value entered for that variable; a value that does not match stops the run. "
                "It matches anywhere in the value, so start with ^ and end with $ to match all of it.", size="2", color="var(--gray-11)"),
        rx.foreach(S.var_rows, lambda v: rx.vstack(
            rx.hstack(
                rx.button(v["key"], size="1", variant="soft", type="button", title="Insert into the description",
                          on_click=rx.call_script(_INSERT_JS + v["key"] + "')")),
                rx.input(value=v["name"], on_change=lambda val: S.set_var_name(v["key"], val), placeholder="Name",
                         width="100%"),
                rx.cond(v["index"] != "0",
                        rx.icon_button(rx.icon("x", size=14), variant="ghost", color_scheme="gray",
                                       on_click=S.remove_variable(v["key"]), aria_label="Remove variable"),
                        rx.box(width="28px")),
                align="center", spacing="2", width="100%"),
            rx.input(value=v["regex"], on_change=lambda val: S.set_var_regex(v["key"], val),
                     placeholder="Regex the value must match (optional), e.g. ^[A-Za-z ]{3,20}$", width="100%",
                     size="1", font_family="var(--code-font-family)"),
            spacing="1", width="100%")),
        rx.button(rx.icon("plus", size=14), "Add Variable", size="1", variant="soft", on_click=S.add_variable,
                  disabled=~S.can_add_var),
    )


def advertise_section(S) -> rx.Component:
    return section(
        "Advertise Pattern Settings",
        field("Description", _desc_input(S, "adv_desc", S.adv_desc, "{Var1} Webex Calling {Pattern}"),
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
        field("PSTN Setting", _radio(S, "pstn_rule", S.pstn_rule, S.pstn_choices)),
        rx.cond(
            S.pstn_rule == "Specify",
            rx.grid(
                field("PSTN Failover Strip Digits", _setting_input(S, "pstn_strip", S.pstn_strip, type="number", min=0)),
                field("PSTN Failover Prepend Digits", _setting_input(S, "pstn_prepend", S.pstn_prepend)),
                columns="2", spacing="3", width="100%",
            ),
            rx.fragment(),
        ),
    )


def route_section(S) -> rx.Component:
    return section(
        "Route Pattern Settings",
        field("Description", _desc_input(S, "rp_desc", S.rp_desc, "{Var1} DID to Webex Calling"),
              "Same placeholders as the Advertise Pattern description."),
        rx.text("Example: ", S.rp_preview, size="1", color="var(--gray-10)"),
        field("Route Partition", _setting_input(S, "rp_partition", S.rp_partition)),
        field("Destination", rx.segmented_control.root(
            rx.foreach(S.dest_types, lambda t: rx.segmented_control.item(t, value=t)),
            value=S.rp_dest_type, on_change=lambda v: S.set_setting("rp_dest_type", v))),
        field(rx.cond(S.rp_dest_type == "Gateway", "Gateway Name", "Route List Name"),
              _setting_input(S, "rp_dest", S.rp_dest)),
    )


def value_input(S, v) -> rx.Component:
    """Input for a variable's value on the main screen, with the regex error under it."""
    return rx.vstack(
        rx.input(value=v["value"], on_change=lambda val: S.set_form_value(v["key"], val), width="100%",
                 color_scheme=rx.cond(v["error"] != "", "red", "gray")),
        rx.cond(v["error"] != "", rx.text(v["error"], size="1", color="var(--red-11)"), rx.fragment()),
        spacing="1", width="100%",
    )
