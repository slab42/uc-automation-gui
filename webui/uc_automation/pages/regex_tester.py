"""Tools > Regex Tester."""

import reflex as rx

from ..components.layout import page
from ..components.regex_ref import reference_card
from ..components.tool_widgets import field
from ..state.regex_tester import RegexTesterState

S = RegexTesterState

_MONO = "var(--code-font-family)"
_HIT = {"a": "var(--yellow-6)", "b": "var(--orange-6)"}


def _piece(p) -> rx.Component:
    return rx.el.span(
        p["text"],
        background=rx.cond(p["kind"] == "a", _HIT["a"], rx.cond(p["kind"] == "b", _HIT["b"], "transparent")),
        border_radius="2px",
    )


def _flag(label: str, name: str, value) -> rx.Component:
    return rx.checkbox(label, checked=value, on_change=lambda v: S.set_flag(name, v))


def _output_box(*children, **props) -> rx.Component:
    return rx.box(*children, width="100%", padding="0.5rem 0.75rem", border="1px solid var(--gray-6)",
                  border_radius="var(--radius-2)", background="var(--gray-2)", font_family=_MONO, font_size="13px",
                  white_space="pre-wrap", word_break="break-all", **props)


def _matches_table() -> rx.Component:
    return rx.table.root(
        rx.table.header(rx.table.row(
            rx.table.column_header_cell("#"), rx.table.column_header_cell("Position"),
            rx.table.column_header_cell("Match"), rx.table.column_header_cell("Groups"),
        )),
        rx.table.body(rx.foreach(S.rows, lambda r: rx.table.row(
            rx.table.cell(r["n"]), rx.table.cell(r["span"]),
            rx.table.cell(rx.code(r["text"], white_space="pre-wrap")),
            rx.table.cell(r["groups"]),
        ))),
        variant="surface", size="1", width="100%",
    )


def regex_tester() -> rx.Component:
    return page(
        "Tools - Regex Tester",
        rx.vstack(
            rx.text("Build a regular expression and test it against sample text. Results update as you type. "
                    "Uses Python regex syntax, so a few features differ from other engines. "
                    "Everything runs inside this app and nothing is saved.",
                    size="2", color="var(--gray-11)"),
            rx.card(
                rx.vstack(
                    field("Regex", rx.input(
                        value=S.pattern, on_change=S.set_pattern, debounce_timeout=250, width="100%",
                        placeholder="^(\\w+)-(CQ|HG|AA)\\b", auto_complete="off", spell_check=False,
                        font_family=_MONO,
                    )),
                    rx.hstack(
                        _flag("Ignore Case", "ignorecase", S.ignorecase),
                        _flag("Multiline", "multiline", S.multiline),
                        _flag("Dot Matches Newline", "dotall", S.dotall),
                        rx.spacer(),
                        rx.button("Clear", variant="soft", color_scheme="gray", size="1", on_click=S.clear_all),
                        spacing="4", align="center", wrap="wrap", width="100%",
                    ),
                    rx.cond(S.error != "",
                            rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                            rx.fragment()),
                    field("Test Text", rx.text_area(
                        value=S.text, on_change=S.set_text, debounce_timeout=250, width="100%", rows="6",
                        spell_check=False, font_family=_MONO, placeholder="Paste the text to test here",
                    )),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.hstack(
                        rx.heading("Match", size="4"),
                        rx.cond(
                            S.pattern != "",
                            rx.badge(rx.cond(S.count == 1, "1 match", S.count.to_string() + " matches"),
                                     color_scheme=rx.cond(S.count > 0, "green", "gray")),
                            rx.fragment(),
                        ),
                        spacing="3", align="center",
                    ),
                    rx.cond(
                        S.text != "",
                        _output_box(rx.foreach(S.parts, _piece)),
                        rx.text("Enter some test text.", size="2", color="var(--gray-10)"),
                    ),
                    rx.cond(S.truncated, rx.text("Showing the first 500 matches only.", size="1",
                                                 color="var(--orange-11)"), rx.fragment()),
                    rx.cond(S.count > 0, _matches_table(), rx.fragment()),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Replace", size="4"),
                    field("Replace With", rx.input(
                        value=S.replace, on_change=S.set_replace, debounce_timeout=250, width="100%",
                        placeholder="\\2-\\1", auto_complete="off", spell_check=False, font_family=_MONO,
                    ), "Optional. Use \\1 or \\g<name> for groups."),
                    rx.cond(S.replace_error != "",
                            rx.callout(S.replace_error, icon="triangle-alert", color_scheme="red", width="100%"),
                            rx.cond((S.replace != "") & (S.pattern != "") & (S.error == ""),
                                    _output_box(S.replaced), rx.fragment())),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(reference_card(S.insert_token), size="3", width="100%"),
            spacing="4", align="start", width="100%",
        ),
    )
