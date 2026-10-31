import reflex as rx

from ..components.tool_widgets import confirm_dialog, field, run_results
from ..components.webex_nav import webex_page
from ..state.webex_naming import NamingCheckState
from .webex_routing import need_login


def _regex_input(value, on_change, **props) -> rx.Component:
    """Monospace input with an X that clears it once there is text."""
    return rx.input(
        rx.input.slot(
            rx.cond(value != "",
                    rx.icon("x", size=16, cursor="pointer", aria_label="Clear", on_click=on_change("")),
                    rx.fragment()),
            side="right",
        ),
        value=value, on_change=on_change, font_family="var(--code-font-family)", **props,
    )


def _type_row(r) -> rx.Component:
    S = NamingCheckState
    return rx.hstack(
        rx.text(r["label"], size="2", weight="medium", width="9rem"),
        _regex_input(r["pattern"], lambda v: S.set_pattern(r["key"], v), width="100%",
                     placeholder="Leave empty to skip this type"),
        rx.select(S.hint_labels, placeholder="Hints", on_change=lambda v: S.apply_hint(r["key"], v), width="14rem"),
        align="center", spacing="3", width="100%",
    )


def naming_check() -> rx.Component:
    S = NamingCheckState
    results = rx.cond(
        S.checks.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.badge(S.pass_count.to_string() + " pass", color_scheme="green"),
                rx.badge(S.fail_count.to_string() + " fail", color_scheme=rx.cond(S.fail_count > 0, "red", "gray")),
                rx.segmented_control.root(
                    rx.segmented_control.item("Fail", value="FAIL"),
                    rx.segmented_control.item("Pass", value="PASS"),
                    rx.segmented_control.item("All", value="All"),
                    value=S.filter_status, on_change=S.set_filter_status, size="1",
                ),
                rx.spacer(),
                rx.button(rx.icon("pencil", size=16), "Rename Suggested (" + S.rename_count.to_string() + ")",
                          color_scheme="red", variant="soft", disabled=(S.rename_count == 0) | S.busy,
                          on_click=S.set_confirm_open(True)),
                rx.button(rx.icon("download", size=16), "Export", variant="soft", on_click=S.export_csv),
                align="center", spacing="2", width="100%",
            ),
            rx.card(
                rx.scroll_area(
                    rx.table.root(
                        rx.table.header(rx.table.row(
                            rx.table.column_header_cell("Type"), rx.table.column_header_cell("Name"),
                            rx.table.column_header_cell("Location"), rx.table.column_header_cell("Status"),
                            rx.table.column_header_cell("Suggested Name"))),
                        rx.table.body(rx.foreach(S.shown_checks, lambda r: rx.table.row(
                            rx.table.cell(r["label"]), rx.table.cell(r["name"]), rx.table.cell(r["location"]),
                            rx.table.cell(rx.badge(r["status"], color_scheme=rx.cond(r["status"] == "PASS", "green", "red"))),
                            rx.table.cell(rx.cond(
                                r["status"] == "FAIL",
                                rx.input(value=r["suggestion"], size="1", width="100%", min_width="14rem",
                                         placeholder=r["limit"],
                                         color_scheme=rx.cond((r["suggestion"] == "") | (r["valid"] != ""), "gray", "red"),
                                         on_change=lambda v: S.set_suggestion(r["key"], v)),
                                rx.fragment())),
                        ))),
                        variant="ghost", width="100%",
                    ),
                    max_height="55vh",
                ),
                padding="0", width="100%",
            ),
            spacing="3", align="start", width="100%",
        ),
        rx.fragment(),
    )
    return webex_page(
        "Naming Check",
        need_login(rx.vstack(
            rx.callout("This tool is still under development. Review results before renaming anything.",
                       icon="construction", color_scheme="amber", width="100%"),
            rx.text("Checks the names of configured Webex Calling items against a regex per item type. Types with an "
                    "empty regex are skipped.", size="2", color="var(--gray-11)"),
            rx.card(rx.vstack(
                rx.heading("Rules", size="4"),
                rx.text("Python regex syntax, case sensitive. Use ^ and $ to match the whole name. {location} stands "
                        "for the item's own location name. Pick a hint to fill the box, then edit it.",
                        size="2", color="var(--gray-11)"),
                rx.foreach(S.type_rows, _type_row),
                rx.heading("Rename (Optional)", size="4", margin_top="0.5rem"),
                rx.text("Failing names are run through this find and replace. Without one, common fixes are tried "
                        "automatically (spaces, odd characters, case, and the rule's fixed prefix or suffix). "
                        "A suggestion is used only when it changes the name and passes the rule. You can also type "
                        "a name in the Suggested Name column; red means it does not pass.", size="2", color="var(--gray-11)"),
                rx.grid(
                    field("Find (regex)", _regex_input(S.find, S.set_find, width="100%", placeholder=r"\s+"),
                          r"Example: \s+ finds spaces."),
                    field("Replace with", _regex_input(S.replace, S.set_replace, width="100%", placeholder="-"),
                          r"Groups work as \1."),
                    columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%",
                ),
                rx.button(rx.cond(S.checking, rx.spinner(size="2"), rx.icon("spell-check", size=16)), "Run Check",
                          on_click=S.run_check, disabled=S.checking | S.busy),
                spacing="3", align="start", width="100%",
            ), size="3", width="100%"),
            run_results(S, "Item"),
            results,
            confirm_dialog(S, "Rename Items",
                           "This renames " + S.rename_count.to_string() + " item(s) in Webex to their suggested names.",
                           "Rename", S.rename_all),
            spacing="4", align="start", width="100%",
        )),
    )
