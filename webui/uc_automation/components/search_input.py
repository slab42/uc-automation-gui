"""Search box with a clear button that appears once there is text."""

import reflex as rx


def search_input(value, on_change, placeholder: str = "Search", **props) -> rx.Component:
    return rx.input(
        rx.input.slot(rx.icon("search", size=16)),
        rx.input.slot(
            rx.cond(
                value != "",
                rx.icon("x", size=16, cursor="pointer", aria_label="Clear search", on_click=on_change("")),
                rx.fragment(),
            ),
            side="right",
        ),
        placeholder=placeholder,
        value=value,
        on_change=on_change,
        **props,
    )
