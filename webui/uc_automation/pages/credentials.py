import reflex as rx

from ..components.layout import page
from ..backend.webex_auth import REDIRECT_URI
from ..state.cucm import CucmState
from ..state.cuc import CucState
from ..state.webex import WebexState


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


def _soon(name: str) -> rx.Component:
    return rx.text(f"{name} credentials will be added when its features are ported.", color="var(--gray-11)")


def _webex_status() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Login", size="4"),
            rx.cond(
                WebexState.info["has_token"] == "yes",
                rx.vstack(
                    rx.hstack(
                        rx.cond(
                            WebexState.checking,
                            rx.badge("checking", color_scheme="gray", variant="soft"),
                            rx.cond(
                                WebexState.logged_in,
                                rx.badge("Token valid", color_scheme="green", variant="soft"),
                                rx.badge("Login required", color_scheme="red", variant="soft"),
                            ),
                        ),
                        rx.text(WebexState.info["user"], size="2"),
                        align="center",
                        spacing="2",
                    ),
                    rx.cond(
                        WebexState.info["auth_mode"] == "token",
                        rx.text("Pasted token. Expiry is unknown, so it is checked with Webex on each use.",
                                size="2", color="var(--gray-11)"),
                        rx.fragment(
                            rx.text("Access token expires " + WebexState.expires_text, size="2",
                                    color="var(--gray-11)"),
                            rx.text("Renewable until " + WebexState.refresh_expires_text, size="2",
                                    color="var(--gray-11)"),
                        ),
                    ),
                    rx.cond(
                        WebexState.message != "",
                        rx.text(WebexState.message, size="2", color="var(--gray-11)"),
                        rx.fragment(),
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.text("Not logged in.", size="2", color="var(--gray-11)"),
            ),
            rx.hstack(
                rx.button(
                    rx.icon("log-in", size=16), "Log in with Webex",
                    on_click=WebexState.login, disabled=~WebexState.has_client,
                    display=rx.cond(WebexState.mode == "oauth", "inline-flex", "none"),
                ),
                rx.cond(
                    WebexState.info["has_token"] == "yes",
                    rx.fragment(
                        rx.button(
                            rx.cond(WebexState.checking, rx.spinner(size="2"), rx.icon("refresh-cw", size=16)),
                            "Check now", variant="soft", on_click=WebexState.check_token,
                            disabled=WebexState.checking,
                        ),
                        rx.button("Log out", variant="ghost", color_scheme="red", on_click=WebexState.logout),
                    ),
                    rx.fragment(),
                ),
                spacing="3",
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        size="3",
        width="100%",
    )


def _webex_form() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Webex Integration", size="4"),
            rx.callout(
                rx.vstack(
                    rx.text(
                        "Webex has no username/password token API. You sign in on Webex's own login page and "
                        "this app stores the token it returns. One-time setup:",
                        size="2",
                    ),
                    rx.text("1. Create an Integration at developer.webex.com/my-apps.", size="2"),
                    rx.text("2. Set its Redirect URI to " + REDIRECT_URI, size="2"),
                    rx.text("3. Tick the scopes listed below, then paste the Client ID and Secret here.", size="2"),
                    spacing="1",
                    align="start",
                ),
                icon="info",
                width="100%",
            ),
            _field(
                "Client ID",
                rx.input(value=WebexState.form_client_id, on_change=WebexState.set_form_client_id, width="100%",
                         auto_complete="off"),
            ),
            _field(
                "Client Secret",
                rx.input(
                    type="password",
                    key=WebexState.secret_key.to_string(),
                    placeholder=rx.cond(WebexState.info["has_secret"] == "yes", "Stored. Leave blank to keep it.", ""),
                    on_change=WebexState.set_client_secret,
                    auto_complete="new-password",
                    width="100%",
                ),
                "Stored in .env/credentials.env and never shown again.",
            ),
            _field(
                "Scopes",
                rx.text_area(value=WebexState.form_scopes, on_change=WebexState.set_form_scopes, width="100%",
                             rows="4"),
                "Space separated. Must be a subset of the scopes ticked on the Integration.",
            ),
            rx.button("Save", variant="soft", on_click=WebexState.save_client),
            spacing="4",
            align="start",
            width="100%",
        ),
        size="3",
        width="100%",
    )


def _webex_org() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Customer", size="4"),
            _field(
                "Org ID",
                rx.hstack(
                    rx.input(value=WebexState.form_org_id, on_change=WebexState.set_form_org_id, width="100%",
                             placeholder="Webex organization ID of the customer"),
                    rx.button("Save", variant="soft", on_click=WebexState.save_org),
                    width="100%",
                ),
                "Used with either sign-in method. Find it in Control Hub under Account.",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        size="3",
        width="100%",
    )


def _webex_token_form() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Bearer token", size="4"),
            rx.text(
                "Copy your personal access token from developer.webex.com/docs/getting-started. "
                "It expires after about 12 hours and cannot be renewed here.",
                size="2", color="var(--gray-11)",
            ),
            _field(
                "Token",
                rx.input(
                    type="password",
                    key=WebexState.token_key.to_string(),
                    on_change=WebexState.set_pasted_token,
                    auto_complete="new-password",
                    width="100%",
                ),
                "Checked with Webex, stored in .env/credentials.env and never shown again.",
            ),
            rx.button(
                rx.cond(WebexState.checking, rx.spinner(size="2"), rx.icon("key-round", size=16)),
                "Use token", on_click=WebexState.use_token, disabled=WebexState.checking,
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        size="3",
        width="100%",
    )


def _webex_tab() -> rx.Component:
    return rx.vstack(
        _webex_org(),
        rx.segmented_control.root(
            rx.segmented_control.item("Bearer Token", value="token"),
            rx.segmented_control.item("Log In With Webex (OAuth)", value="oauth"),
            value=WebexState.mode,
            on_change=WebexState.set_mode,
        ),
        rx.grid(
            rx.cond(WebexState.mode == "token", _webex_token_form(), _webex_form()),
            _webex_status(),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="5",
            width="100%",
        ),
        spacing="5",
        align="start",
        width="100%",
    )


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
            rx.tabs.content(rx.box(_soon("CUBE"), padding_top="1rem"), value="cube"),
            rx.tabs.content(rx.box(_webex_tab(), padding_top="1rem"), value="webex"),
            rx.tabs.content(rx.box(_soon("RedSky"), padding_top="1rem"), value="redsky"),
            value=WebexState.cred_tab,
            on_change=WebexState.set_cred_tab,
            width="100%",
        ),
    )
