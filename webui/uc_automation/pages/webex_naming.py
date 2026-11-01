import reflex as rx

from ..components.tool_widgets import confirm_dialog, field, run_results
from ..components.webex_nav import webex_page
from ..backend.webex_naming import TYPES
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


# (token, meaning, example)
_REGEX_HELP = [
    ("Anchors", [
        ("^", "Start of the name", "^HG- matches HG-Sales"),
        ("$", "End of the name", "-CQ$ matches Main-CQ"),
    ]),
    ("Wildcards And Repeats", [
        (".", "Any one character", "a.c matches abc"),
        (".*", "Any text, including none", "^HG-.*"),
        (".+", "Any text, at least one character", "^HG-.+"),
        ("?", "Previous item is optional", "colou?r"),
        ("*", "Previous item zero or more times", "ab*"),
        ("+", "Previous item one or more times", "ab+"),
        ("{3}", "Exactly 3 times", "[0-9]{3}"),
        ("{3,}", "3 or more times", "[A-Z]{3,}"),
        ("{3,30}", "Between 3 and 30 times", "^.{3,30}$"),
    ]),
    ("Brackets And Groups", [
        ("[abc]", "One of the listed characters", "[NS]E"),
        ("[a-z]", "A range of characters", "[A-Z0-9]"),
        ("[^abc]", "Any character except those listed", "[^ ]"),
        ("(ab)", "Group items together", "(-[A-Z]+){2}"),
        ("(a|b)", "Either a or b", "(CQ|HG|AA)$"),
        ("a|b", "Either side (use groups to limit it)", "^(HG|CQ)-"),
    ]),
    ("Character Shortcuts", [
        ("\\d", "A digit, same as [0-9]", "\\d{4}"),
        ("\\w", "Letter, digit or underscore", "^\\w+$"),
        ("\\s", "A space or tab", "\\s"),
        ("\\S", "Anything but a space", "^\\S+$"),
        ("\\.", "A literal special character (\\. \\- \\( \\[ \\+ \\$ \\^)", "\\(Main\\)"),
    ]),
    ("This Tool", [
        ("{location}", "The item's own location name", "^{location}-.+"),
        ("Case", "Matching is case sensitive. Use [Hh][Gg] or (?i) at the start to ignore case", "(?i)^hg-"),
        ("Whole name", "Without ^ and $ a match anywhere in the name passes", "^[A-Za-z0-9-]+$"),
    ]),
]


def _reference_sections() -> list[rx.Component]:
    return [rx.vstack(
        rx.text(title, size="2", weight="bold"),
        rx.table.root(
            rx.table.body(*[rx.table.row(
                rx.table.cell(rx.code(tok)), rx.table.cell(meaning),
                rx.table.cell(rx.code(example))) for tok, meaning, example in rows]),
            variant="ghost", size="1", width="100%",
        ),
        spacing="1", align="start", width="100%",
    ) for title, rows in _REGEX_HELP]


def _regex_help() -> rx.Component:
    return rx.popover.root(
        rx.popover.trigger(rx.icon_button(rx.icon("info", size=16), variant="ghost", size="1",
                                          aria_label="Regex help")),
        rx.popover.content(
            rx.scroll_area(
                rx.vstack(
                    rx.heading("Regex Quick Reference", size="3"),
                    *_reference_sections(),
                    spacing="3", align="start", width="100%",
                ),
                max_height="60vh", type="auto",
            ),
            max_width="42rem", width="90vw",
        ),
    )


def _regex_tab() -> rx.Component:
    S = NamingCheckState
    return rx.vstack(
        rx.heading("Describe The Rule", size="4"),
        rx.text("Say in plain words what a good name looks like. Either list the parts in order, such as "
                "\"location name, a space, then 5 letters\" (the whole name is matched), or state rules: starts with, ends with, "
                "contains, letters and numbers only, uppercase or lowercase, dashes or underscores, no spaces, "
                "max, min or between N and M characters, and \"the location name\".",
                size="2", color="var(--gray-11)"),
        rx.text_area(value=S.regex_desc, on_change=S.set_regex_desc, width="100%", rows="3",
                     placeholder="Location name followed by a space, then 5 letters and a space"),
        rx.button(rx.icon("wand-sparkles", size=16), "Generate Regex", on_click=S.generate_regex),
        rx.heading("Regex", size="4", margin_top="0.5rem"),
        _regex_input(S.regex_out, S.set_regex_out, width="100%", placeholder="The regex appears here"),
        rx.cond(
            S.regex_notes.length() > 0,
            rx.vstack(
                rx.text("How It Was Read", size="2", weight="bold"),
                rx.foreach(S.regex_notes, lambda t: rx.text("- " + t, size="2", color="var(--gray-11)")),
                spacing="1", align="start",
            ),
            rx.fragment(),
        ),
        rx.hstack(
            rx.button(rx.icon("copy", size=16), "Copy", variant="soft", disabled=S.regex_out == "",
                      on_click=[rx.set_clipboard(S.regex_out), rx.toast.success("Copied")]),
            rx.text("Use for", size="2"),
            rx.select(list(TYPES.values()), value=S.regex_target, on_change=S.set_regex_target, width="12rem"),
            rx.button(rx.icon("check", size=16), "Use As Rule", variant="soft", disabled=S.regex_out == "",
                      on_click=S.use_regex),
            align="center", spacing="2", wrap="wrap",
        ),
        rx.text("Generated from fixed phrase rules, not understood freely: check the result and edit it above.",
                size="1", color="var(--gray-10)"),
        rx.heading("Regex Quick Reference", size="4", margin_top="1rem"),
        *_reference_sections(),
        spacing="3", align="start", width="100%", padding_top="1rem",
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
                                rx.input(
                                    rx.input.slot(
                                        rx.cond(r["suggestion"] != "",
                                                rx.icon("x", size=14, cursor="pointer", aria_label="Clear",
                                                        on_click=S.set_suggestion(r["key"], "")),
                                                rx.fragment()),
                                        side="right",
                                    ),
                                    value=r["suggestion"], size="1", width="100%", min_width="14rem",
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
            rx.card(rx.tabs.root(
                rx.tabs.list(rx.tabs.trigger("Rules", value="rules"), rx.tabs.trigger("Regex", value="regex")),
                rx.tabs.content(rx.vstack(
                rx.hstack(rx.heading("Rules", size="4"), _regex_help(), align="center", spacing="2"),
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
                spacing="3", align="start", width="100%", padding_top="1rem",
            ), value="rules"),
                rx.tabs.content(_regex_tab(), value="regex"),
                default_value="rules", width="100%",
            ), size="3", width="100%"),
            run_results(S, "Item"),
            results,
            confirm_dialog(S, "Rename Items",
                           "This renames " + S.rename_count.to_string() + " item(s) in Webex to their suggested names.",
                           "Rename", S.rename_all),
            spacing="4", align="start", width="100%",
        )),
    )
