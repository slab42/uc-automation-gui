import reflex as rx

from ..components.layout import page
from ..state.cucm import CucmState


def _field(label: str, control: rx.Component, hint: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        rx.cond(hint != "", rx.text(hint, size="1", color="var(--gray-10)"), rx.fragment()),
        spacing="1",
        align="start",
        width="100%",
    )


def _saved_row(c) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.hstack(
                rx.text(c["name"], weight="bold"),
                rx.cond(
                    c["version"] != "",
                    rx.badge("v" + c["version"], variant="soft", color_scheme="green"),
                    rx.badge("not tested", variant="soft", color_scheme="gray"),
                ),
                align="center",
                spacing="2",
            ),
            rx.text(c["server"] + "  ·  " + c["username"], size="2", color="var(--gray-11)"),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        rx.icon_button(rx.icon("pencil", size=15), variant="ghost", on_click=CucmState.edit_connection(c["name"])),
        rx.icon_button(
            rx.icon("trash-2", size=15), variant="ghost", color_scheme="red",
            on_click=CucmState.delete_connection(c["name"]),
        ),
        align="center",
        width="100%",
        padding="0.6rem 0.75rem",
        border="1px solid var(--gray-5)",
        border_radius="var(--radius-3)",
    )


def _form() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Connection", size="4"),
            _field(
                "Name",
                rx.input(
                    value=CucmState.form_name, placeholder="e.g. lab-cucm",
                    on_change=lambda v: CucmState.set_form("name", v), width="100%",
                ),
                "A label for this cluster. Saving under an existing name updates it.",
            ),
            _field(
                "IP address or hostname",
                rx.input(
                    value=CucmState.form_server, placeholder="10.0.0.10",
                    on_change=lambda v: CucmState.set_form("server", v), width="100%",
                ),
                "The publisher. AXL is reached on port 8443.",
            ),
            _field(
                "Username",
                rx.input(
                    value=CucmState.form_username, placeholder="axl_user",
                    on_change=lambda v: CucmState.set_form("username", v), width="100%",
                    auto_complete="off",
                ),
            ),
            _field(
                "Password",
                rx.input(
                    type="password",
                    key=CucmState.password_key.to_string(),
                    placeholder=rx.cond(CucmState.form_has_password, "Stored. Leave blank to keep it.", ""),
                    on_change=CucmState.set_password,
                    auto_complete="new-password",
                    width="100%",
                ),
                "Stored in .env/credentials.env and never shown again.",
            ),
            rx.hstack(
                rx.button(
                    rx.cond(CucmState.testing, rx.spinner(size="2"), rx.icon("plug-zap", size=16)),
                    "Test connection",
                    on_click=CucmState.test_connection,
                    disabled=CucmState.testing,
                ),
                rx.button("Save", variant="soft", on_click=CucmState.save_connection, disabled=CucmState.testing),
                rx.button("Clear", variant="ghost", color_scheme="gray", on_click=CucmState.new_connection),
                spacing="3",
            ),
            rx.cond(
                CucmState.test_message != "",
                rx.callout(
                    CucmState.test_message,
                    icon=rx.cond(CucmState.test_ok, "circle-check", "triangle-alert"),
                    color_scheme=rx.cond(CucmState.test_ok, "green", "red"),
                    width="100%",
                ),
                rx.fragment(),
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        size="3",
        width="100%",
    )


def _cucm_tab() -> rx.Component:
    return rx.grid(
        _form(),
        rx.vstack(
            rx.heading("Saved connections", size="4"),
            rx.cond(
                CucmState.connections.length() > 0,
                rx.vstack(rx.foreach(CucmState.connections, _saved_row), spacing="2", width="100%"),
                rx.text("None yet. Fill in the form and test the connection to save one.",
                        color="var(--gray-11)", size="2"),
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        columns=rx.breakpoints(initial="1", lg="2"),
        spacing="5",
        width="100%",
    )


def _soon(name: str) -> rx.Component:
    return rx.text(f"{name} credentials will be added when its features are ported.", color="var(--gray-11)")


def credentials() -> rx.Component:
    return page(
        "Credentials",
        rx.tabs.root(
            rx.tabs.list(
                rx.tabs.trigger("CUCM", value="cucm"),
                rx.tabs.trigger("CUC", value="cuc"),
                rx.tabs.trigger("CUBE", value="cube"),
                rx.tabs.trigger("Webex", value="webex"),
                rx.tabs.trigger("RedSky", value="redsky"),
            ),
            rx.tabs.content(rx.box(_cucm_tab(), padding_top="1rem"), value="cucm"),
            rx.tabs.content(rx.box(_soon("CUC"), padding_top="1rem"), value="cuc"),
            rx.tabs.content(rx.box(_soon("CUBE"), padding_top="1rem"), value="cube"),
            rx.tabs.content(rx.box(_soon("Webex"), padding_top="1rem"), value="webex"),
            rx.tabs.content(rx.box(_soon("RedSky"), padding_top="1rem"), value="redsky"),
            default_value="cucm",
            width="100%",
        ),
    )
