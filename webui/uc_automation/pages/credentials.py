import reflex as rx

from ..components.layout import page
from ..state.cube import CubeState
from ..state.cucm import CucmState
from ..state.cuc import CucState
from ..state.redsky import RedskyState
from ..state.webex import WebexState
from .webex_credentials import webex_tab


def _field(label: str, control: rx.Component, hint: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        rx.cond(hint != "", rx.text(hint, size="1", color="var(--gray-10)"), rx.fragment()),
        spacing="1",
        align="start",
        width="100%",
    )


def _saved_row(c, S) -> rx.Component:
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
        rx.icon_button(rx.icon("pencil", size=15), variant="ghost", on_click=S.edit_connection(c["name"])),
        rx.icon_button(
            rx.icon("trash-2", size=15), variant="ghost", color_scheme="red",
            on_click=S.delete_connection(c["name"]),
        ),
        align="center",
        width="100%",
        padding="0.6rem 0.75rem",
        border="1px solid var(--gray-5)",
        border_radius="var(--radius-3)",
    )


def _form(S, placeholder: str, server_hint: str) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Connection", size="4"),
            _field(
                "Name",
                rx.input(
                    value=S.form_name, placeholder=placeholder,
                    on_change=lambda v: S.set_form("name", v), width="100%",
                ),
                "A label for this cluster. Saving under an existing name updates it.",
            ),
            _field(
                "IP address or hostname",
                rx.input(
                    value=S.form_server, placeholder="10.0.0.10",
                    on_change=lambda v: S.set_form("server", v), width="100%",
                ),
                server_hint,
            ),
            _field(
                "Username",
                rx.input(
                    value=S.form_username, placeholder="username",
                    on_change=lambda v: S.set_form("username", v), width="100%",
                    auto_complete="off",
                ),
            ),
            _field(
                "Password",
                rx.input(
                    type="password",
                    key=S.password_key.to_string(),
                    placeholder=rx.cond(S.form_has_password, "Stored. Leave blank to keep it.", ""),
                    on_change=S.set_password,
                    auto_complete="new-password",
                    width="100%",
                ),
                "Stored in .env/credentials.env and never shown again.",
            ),
            rx.hstack(
                rx.button(
                    rx.cond(S.testing, rx.spinner(size="2"), rx.icon("plug-zap", size=16)),
                    "Test connection",
                    on_click=S.test_connection,
                    disabled=S.testing,
                ),
                rx.button("Save", variant="soft", on_click=S.save_connection, disabled=S.testing),
                rx.button("Clear", variant="ghost", color_scheme="gray", on_click=S.new_connection),
                spacing="3",
            ),
            rx.cond(
                S.test_message != "",
                rx.callout(
                    S.test_message,
                    icon=rx.cond(S.test_ok, "circle-check", "triangle-alert"),
                    color_scheme=rx.cond(S.test_ok, "green", "red"),
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


def _conn_tab(S, placeholder: str, server_hint: str) -> rx.Component:
    return rx.grid(
        _form(S, placeholder, server_hint),
        rx.vstack(
            rx.heading("Saved connections", size="4"),
            rx.cond(
                S.connections.length() > 0,
                rx.vstack(rx.foreach(S.connections, lambda c: _saved_row(c, S)), spacing="2", width="100%"),
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


def _cucm_tab() -> rx.Component:
    return _conn_tab(CucmState, "e.g. lab-cucm", "The publisher. AXL is reached on port 8443.")


def _cuc_tab() -> rx.Component:
    return _conn_tab(CucState, "e.g. lab-cuc", "The Unity Connection server. The REST API is reached on port 443.")


def _redsky_row(c) -> rx.Component:
    S = RedskyState
    return rx.hstack(
        rx.vstack(
            rx.text(c["name"], weight="bold"),
            rx.text(c["username"] + "  ·  org " + c["org_id"], size="2", color="var(--gray-11)"),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        rx.icon_button(rx.icon("pencil", size=15), variant="ghost", on_click=S.edit_connection(c["name"])),
        rx.icon_button(
            rx.icon("trash-2", size=15), variant="ghost", color_scheme="red",
            on_click=S.delete_connection(c["name"]),
        ),
        align="center",
        width="100%",
        padding="0.6rem 0.75rem",
        border="1px solid var(--gray-5)",
        border_radius="var(--radius-3)",
    )


def _redsky_form() -> rx.Component:
    S = RedskyState
    return rx.card(
        rx.vstack(
            rx.heading("Connection", size="4"),
            _field(
                "Name",
                rx.input(
                    value=S.form_name, placeholder="e.g. customer-redsky",
                    on_change=lambda v: S.set_form("name", v), width="100%",
                ),
                "A label for this RedSky account. Saving under an existing name updates it.",
            ),
            _field(
                "Username",
                rx.input(
                    value=S.form_username, placeholder="username",
                    on_change=lambda v: S.set_form("username", v), width="100%",
                    auto_complete="off",
                ),
            ),
            _field(
                "Password",
                rx.input(
                    type="password",
                    key=S.password_key.to_string(),
                    placeholder=rx.cond(S.form_has_password, "Stored. Leave blank to keep it.", ""),
                    on_change=S.set_password,
                    auto_complete="new-password",
                    width="100%",
                ),
                "Stored in .env/credentials.env and never shown again.",
            ),
            _field(
                "Organization ID",
                rx.input(
                    value=S.form_org_id, placeholder="organization id",
                    on_change=lambda v: S.set_form("org_id", v), width="100%",
                    auto_complete="off",
                ),
                "The RedSky organization the scripts work in.",
            ),
            rx.hstack(
                rx.button(
                    rx.cond(S.testing, rx.spinner(size="2"), rx.icon("plug-zap", size=16)),
                    "Test connection",
                    on_click=S.test_connection,
                    disabled=S.testing,
                ),
                rx.button("Save", variant="soft", on_click=S.save_connection, disabled=S.testing),
                rx.button("Clear", variant="ghost", color_scheme="gray", on_click=S.new_connection),
                spacing="3",
            ),
            rx.cond(
                S.test_message != "",
                rx.callout(
                    S.test_message,
                    icon=rx.cond(S.test_ok, "circle-check", "triangle-alert"),
                    color_scheme=rx.cond(S.test_ok, "green", "red"),
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


def _redsky_tab() -> rx.Component:
    S = RedskyState
    return rx.grid(
        _redsky_form(),
        rx.vstack(
            rx.heading("Saved connections", size="4"),
            rx.cond(
                S.connections.length() > 0,
                rx.vstack(rx.foreach(S.connections, _redsky_row), spacing="2", width="100%"),
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


def _cube_row(c) -> rx.Component:
    S = CubeState
    return rx.hstack(
        rx.vstack(
            rx.text(c["name"], weight="bold"),
            rx.text(c["username"], size="2", color="var(--gray-11)"),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        rx.icon_button(rx.icon("pencil", size=15), variant="ghost", on_click=S.edit_credential(c["name"])),
        rx.icon_button(
            rx.icon("trash-2", size=15), variant="ghost", color_scheme="red",
            on_click=S.delete_credential(c["name"]),
        ),
        align="center",
        width="100%",
        padding="0.6rem 0.75rem",
        border="1px solid var(--gray-5)",
        border_radius="var(--radius-3)",
    )


def _cube_form() -> rx.Component:
    S = CubeState
    return rx.card(
        rx.vstack(
            rx.heading("Credential Set", size="4"),
            _field(
                "Name",
                rx.input(
                    value=S.form_name, placeholder="e.g. branch-routers",
                    on_change=lambda v: S.set_form("name", v), width="100%",
                ),
                "A label for this set. Saving under an existing name updates it. "
                "A set named default is the fallback for routers without their own.",
            ),
            _field(
                "Username",
                rx.input(
                    value=S.form_username, placeholder="username",
                    on_change=lambda v: S.set_form("username", v), width="100%",
                    auto_complete="off",
                ),
            ),
            _field(
                "Password",
                rx.input(
                    type="password",
                    key=S.password_key.to_string(),
                    placeholder=rx.cond(S.form_has_password, "Stored. Leave blank to keep it.", ""),
                    on_change=S.set_password,
                    auto_complete="new-password",
                    width="100%",
                ),
                "Stored in .env/credentials.env and never shown again.",
            ),
            rx.hstack(
                rx.button("Save", on_click=S.save_credential),
                rx.button("Clear", variant="ghost", color_scheme="gray", on_click=S.new_credential),
                spacing="3",
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        size="3",
        width="100%",
    )


def _cube_tab() -> rx.Component:
    S = CubeState
    return rx.grid(
        _cube_form(),
        rx.vstack(
            rx.heading("Saved Credential Sets", size="4"),
            rx.cond(
                S.credentials.length() > 0,
                rx.vstack(rx.foreach(S.credentials, _cube_row), spacing="2", width="100%"),
                rx.text("None yet. Fill in the form and save one.", color="var(--gray-11)", size="2"),
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


def webex_callback() -> rx.Component:
    return page(
        "Webex - Login",
        rx.vstack(
            rx.text(WebexState.callback_message),
            rx.link("Back to Credentials", href="/credentials"),
            spacing="3",
        ),
    )


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
            rx.tabs.content(rx.box(_cuc_tab(), padding_top="1rem"), value="cuc"),
            rx.tabs.content(rx.box(_cube_tab(), padding_top="1rem"), value="cube"),
            rx.tabs.content(rx.box(webex_tab(), padding_top="1rem"), value="webex"),
            rx.tabs.content(rx.box(_redsky_tab(), padding_top="1rem"), value="redsky"),
            value=WebexState.cred_tab,
            on_change=WebexState.set_cred_tab,
            width="100%",
        ),
    )
