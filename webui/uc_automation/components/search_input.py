"""Search box with a clear button that appears once there is text.

A box that runs a search (a Find or Search button) passes `on_enter`: the same handler as that button, run on Enter."""

import reflex as rx


def search_input(value, on_change, placeholder: str = "Search", on_enter=None, **props) -> rx.Component:
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
        **({"on_key_down": lambda key: rx.cond(key == "Enter", on_enter, rx.noop())} if on_enter is not None else {}),
        **props,
    )
