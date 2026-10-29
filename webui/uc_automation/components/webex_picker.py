"""Searchable list of Webex objects with one selected row. The state uses `state.webex_groups.PickerMixin`."""

import reflex as rx


DEFAULT_COLUMNS = (("Name", "name"), ("Location", "location"), ("Number", "number"))


def picker(S, title: str, columns=DEFAULT_COLUMNS) -> rx.Component:
    """`columns` is (header, row key) pairs; every row also needs an "id"."""
    def row(r) -> rx.Component:
        return rx.table.row(
            *[rx.table.cell(r[key]) for _h, key in columns],
            on_click=S.select_row(r["id"]),
            style={"cursor": "pointer"},
            background=rx.cond(S.selected_id == r["id"], "var(--accent-4)", "transparent"),
        )

    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(title, size="4"),
                rx.spacer(),
                rx.input(rx.input.slot(rx.icon("search", size=16)), placeholder="Search", value=S.search,
                         on_change=S.set_search, width="260px", max_width="100%"),
                rx.button(rx.cond(S.loading, rx.spinner(size="2"), rx.icon("refresh-cw", size=16)), "Reload",
                          variant="soft", on_click=S.reload, disabled=S.loading),
                align="center", spacing="3", wrap="wrap", width="100%",
            ),
            rx.cond(S.list_error != "", rx.callout(S.list_error, icon="triangle-alert", color_scheme="red",
                                                   width="100%"), rx.fragment()),
            rx.cond(
                S.loading & (S.rows.length() == 0),
                rx.hstack(rx.spinner(size="2"), rx.text("Loading...", size="2"), align="center", spacing="2"),
                rx.scroll_area(
                    rx.table.root(
                        rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h, _k in columns])),
                        rx.table.body(rx.foreach(S.shown_rows, row)),
                        variant="ghost", width="100%",
                    ),
                    max_height="40vh",
                ),
            ),
            rx.hstack(
                rx.text(S.match_count.to_string() + " found. Click a row to select it.", size="1",
                        color="var(--gray-10)"),
                rx.cond(S.has_selection, rx.badge("Selected: " + S.selected_label, color_scheme="blue"),
                        rx.fragment()),
                spacing="3", align="center", wrap="wrap",
            ),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )
