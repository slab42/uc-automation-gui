"""Regex quick reference (Python `re` syntax). Clicking a token adds it to the pattern."""

import reflex as rx

# (section, [(token, meaning, example)])
REFERENCE: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Anchors", [
        ("^", "Start of the text (each line with Multiline)", "^HG-"),
        ("$", "End of the text (each line with Multiline)", "-CQ$"),
        ("\\b", "Word boundary", "\\bsales\\b"),
        ("\\B", "Not a word boundary", "\\Bing"),
    ]),
    ("Characters", [
        (".", "Any one character except a new line", "a.c"),
        ("\\d", "A digit, same as [0-9]", "\\d{4}"),
        ("\\D", "Anything but a digit", "\\D+"),
        ("\\w", "Letter, digit or underscore", "\\w+"),
        ("\\W", "Anything but a letter, digit or underscore", "\\W"),
        ("\\s", "Space, tab or new line", "\\s+"),
        ("\\S", "Anything but whitespace", "\\S+"),
        ("\\.", "A literal special character (\\. \\- \\( \\[ \\+ \\$ \\^ \\\\)", "\\(Main\\)"),
        ("\\t", "Tab", "\\t"),
        ("\\n", "New line", "\\n"),
    ]),
    ("Sets", [
        ("[abc]", "One of the listed characters", "[NS]E"),
        ("[a-z]", "A range of characters", "[A-Z0-9]"),
        ("[^abc]", "Any character except those listed", "[^ ]"),
    ]),
    ("Repeats", [
        ("?", "Optional (0 or 1)", "colou?r"),
        ("*", "0 or more", "ab*"),
        ("+", "1 or more", "ab+"),
        ("{3}", "Exactly 3", "\\d{3}"),
        ("{3,}", "3 or more", "[A-Z]{3,}"),
        ("{3,30}", "Between 3 and 30", "^.{3,30}$"),
        ("*?", "Lazy: as few as possible (also +? ?? {n,m}?)", "<.+?>"),
    ]),
    ("Groups", [
        ("(ab)", "Capture group", "(\\d+)-(\\d+)"),
        ("(?:ab)", "Group without capturing", "(?:CQ|HG)-"),
        ("(?P<name>ab)", "Named capture group", "(?P<ext>\\d{4})"),
        ("(a|b)", "Either a or b", "(CQ|HG|AA)$"),
        ("\\1", "Same text as capture group 1", "(\\w)\\1"),
        ("(?P=name)", "Same text as the named group", "(?P<c>\\w)(?P=c)"),
    ]),
    ("Look Around", [
        ("(?=ab)", "Followed by ab (not consumed)", "\\d+(?= ext)"),
        ("(?!ab)", "Not followed by ab", "\\d+(?! ext)"),
        ("(?<=ab)", "Preceded by ab", "(?<=\\$)\\d+"),
        ("(?<!ab)", "Not preceded by ab", "(?<!\\$)\\b\\d+"),
    ]),
    ("Flags", [
        ("(?i)", "Ignore case (same as the Ignore Case box)", "(?i)^hg-"),
        ("(?m)", "^ and $ match at each line", "(?m)^\\w+"),
        ("(?s)", "Dot also matches a new line", "(?s)a.b"),
        ("(?x)", "Verbose: spaces and # comments are ignored", "(?x) \\d+ # digits"),
    ]),
    ("Replace With", [
        ("\\1", "Text of capture group 1", "\\2-\\1"),
        ("\\g<name>", "Text of a named group", "\\g<ext>"),
        ("\\g<0>", "The whole match", "[\\g<0>]"),
    ]),
]


def reference_card(on_insert) -> rx.Component:
    """The reference tables; `on_insert(token)` returns the event for a click on a token."""
    return rx.vstack(
        rx.heading("Quick Reference", size="4"),
        rx.text("Python re syntax. Click a token to add it to the end of the pattern.", size="2",
                color="var(--gray-11)"),
        rx.grid(
            *[rx.vstack(
                rx.text(title, size="2", weight="bold"),
                rx.table.root(
                    rx.table.body(*[rx.table.row(
                        rx.table.cell(rx.code(tok, cursor="pointer", on_click=on_insert(tok), title="Add to pattern")),
                        rx.table.cell(meaning),
                        rx.table.cell(rx.code(example, color_scheme="gray"))) for tok, meaning, example in rows]),
                    variant="ghost", size="1", width="100%",
                ),
                spacing="1", align="start", width="100%",
            ) for title, rows in REFERENCE],
            columns=rx.breakpoints(initial="1", lg="2"), spacing="4", width="100%",
        ),
        spacing="3", align="start", width="100%",
    )
