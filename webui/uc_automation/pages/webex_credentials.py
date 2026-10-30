"""Credentials > Webex tab: a list of saved credentials and a list of saved orgs, each edited in a dialog."""

import reflex as rx

from ..backend.webex_auth import REDIRECT_URI
from ..state.webex import WebexState as S

MUTED = "var(--gray-11)"


def _field(label: str, control: rx.Component, hint: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        rx.cond(hint != "", rx.text(hint, size="1", color="var(--gray-10)"), rx.fragment()),
        spacing="1",
        align="start",
        width="100%",
    )


def _delete_button(title: str, on_confirm) -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(rx.icon_button(rx.icon("trash-2", size=15), variant="ghost", color_scheme="red")),
        rx.alert_dialog.content(
            rx.alert_dialog.title(title),
            rx.hstack(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray")),
                rx.alert_dialog.action(rx.button("Delete", color_scheme="red", on_click=on_confirm)),
                spacing="3",
                justify="end",
                margin_top="1rem",
            ),
        ),
    )


def _row(*children) -> rx.Component:
    return rx.hstack(
        *children,
        align="center",
        width="100%",
        padding="0.6rem 0.75rem",
        border="1px solid var(--gray-5)",
        border_radius="var(--radius-3)",
    )


def _section(title: str, hint: str, add_label: str, on_add, body: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.vstack(
                rx.heading(title, size="5"),
                rx.text(hint, size="2", color=MUTED),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.button(rx.icon("plus", size=16), add_label, on_click=on_add),
            align="center",
            width="100%",
        ),
        body,
        spacing="3",
        align="start",
        width="100%",
    )


# --- credentials -----------------------------------------------------------

def _login_status() -> rx.Component:
    return rx.cond(
        S.info["has_token"] == "yes",
        rx.vstack(
            rx.hstack(
                rx.cond(
                    S.checking,
                    rx.badge("checking", color_scheme="gray", variant="soft"),
                    rx.cond(S.logged_in, rx.badge("Token valid", color_scheme="green", variant="soft"),
                            rx.badge("Login required", color_scheme="red", variant="soft")),
                ),
                rx.text(S.info["user"], size="2"),
                align="center",
                spacing="2",
            ),
            rx.cond(
                S.info["auth_mode"] == "token",
                rx.text("Pasted token. Expiry is unknown, so it is checked with Webex on each use.",
                        size="2", color=MUTED),
                rx.fragment(
                    rx.text("Access token expires " + S.expires_text, size="2", color=MUTED),
                    rx.text("Renewable until " + S.refresh_expires_text, size="2", color=MUTED),
                ),
            ),
            rx.cond(S.message != "", rx.text(S.message, size="2", color=MUTED), rx.fragment()),
            rx.hstack(
                rx.button(rx.cond(S.checking, rx.spinner(size="2"), rx.icon("refresh-cw", size=16)),
                          "Check now", variant="soft", on_click=S.check_token, disabled=S.checking),
                rx.button("Log out", variant="ghost", color_scheme="red", on_click=S.logout),
                spacing="3",
            ),
            spacing="2",
            align="start",
            width="100%",
            padding="0.75rem",
            background="var(--gray-2)",
            border_radius="var(--radius-3)",
        ),
        rx.text("Not logged in yet.", size="2", color=MUTED),
    )


def _token_fields() -> rx.Component:
    return rx.vstack(
        _field(
            "Bearer token",
            rx.input(type="password", key=S.token_key.to_string(), on_change=S.set_pasted_token,
                     auto_complete="new-password", width="100%"),
            "Copy your personal access token from developer.webex.com/docs/getting-started (valid about 12 hours, "
            "not renewable). Checked with Webex, stored in .env/credentials.env and never shown again.",
        ),
        rx.button(rx.cond(S.checking, rx.spinner(size="2"), rx.icon("key-round", size=16)),
                  "Save token", on_click=S.use_token, disabled=S.checking),
        spacing="3",
        align="start",
        width="100%",
    )


def _oauth_fields() -> rx.Component:
    return rx.vstack(
        rx.text(
            "Create an Integration at developer.webex.com/my-apps with Redirect URI " + REDIRECT_URI
            + " and the scopes below, then paste its Client ID and Secret.",
            size="2", color=MUTED,
        ),
        _field("Client ID", rx.input(value=S.form_client_id, on_change=S.set_form_client_id, width="100%",
                                     auto_complete="off")),
        _field(
            "Client Secret",
            rx.input(type="password", key=S.secret_key.to_string(),
                     placeholder=rx.cond(S.info["has_secret"] == "yes", "Stored. Leave blank to keep it.", ""),
                     on_change=S.set_client_secret, auto_complete="new-password", width="100%"),
            "Stored in .env/credentials.env and never shown again.",
        ),
        _field("Scopes", rx.text_area(value=S.form_scopes, on_change=S.set_form_scopes, width="100%", rows="4"),
               "Space separated. Must be a subset of the scopes ticked on the Integration."),
        rx.hstack(
            rx.button("Save integration", variant="soft", on_click=S.save_client),
            rx.button(rx.icon("log-in", size=16), "Log in with Webex", on_click=S.login, disabled=~S.has_client),
            spacing="3",
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def _login_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(S.login_is_new, "Add Credentials", "Edit Credentials")),
            rx.vstack(
                _field(
                    "Name",
                    rx.cond(
                        S.login_is_new,
                        rx.input(value=S.login_name, on_change=S.set_login_name, width="100%",
                                 placeholder="e.g. my-admin"),
                        rx.hstack(
                            rx.input(value=S.login_rename, on_change=S.set_login_rename, width="100%"),
                            rx.button("Rename", variant="soft", on_click=S.rename_login,
                                      disabled=S.login_rename == S.login_name),
                            width="100%",
                        ),
                    ),
                    "Letters, digits, '.', '_' or '-'. Renaming keeps the login and the organizations that use it.",
                ),
                rx.segmented_control.root(
                    rx.segmented_control.item("Bearer Token", value="token"),
                    rx.segmented_control.item("Log In With Webex (OAuth)", value="oauth"),
                    value=S.mode,
                    on_change=S.set_mode,
                ),
                rx.cond(S.mode == "token", _token_fields(), _oauth_fields()),
                _login_status(),
                rx.hstack(
                    rx.dialog.close(rx.button("Done", variant="soft", color_scheme="gray")),
                    justify="end",
                    width="100%",
                ),
                spacing="4",
                align="start",
                width="100%",
            ),
            max_width="560px",
        ),
        open=S.login_open,
        on_open_change=S.set_login_open,
    )


def _login_row(c) -> rx.Component:
    return _row(
        rx.vstack(
            rx.hstack(
                rx.text(c["name"], weight="bold"),
                rx.cond(c["has_token"] == "yes", rx.badge("logged in", variant="soft", color_scheme="green"),
                        rx.badge("no login", variant="soft", color_scheme="red")),
                rx.badge(rx.cond(c["auth_mode"] == "token", "Bearer token", "OAuth"), variant="outline",
                         color_scheme="gray"),
                align="center",
                spacing="2",
            ),
            rx.text(rx.cond(c["user"] != "", c["user"], "Not signed in"), size="2", color=MUTED),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        rx.icon_button(rx.icon("pencil", size=15), variant="ghost", on_click=S.edit_login(c["name"])),
        _delete_button("Delete these credentials?", S.delete_login(c["name"])),
    )


def _logins() -> rx.Component:
    return _section(
        "Credentials", "How to sign in to Webex. One set of credentials can serve any number of organizations.",
        "Add Credentials", S.add_login,
        rx.cond(
            S.webex_logins.length() > 0,
            rx.vstack(rx.foreach(S.webex_logins, _login_row), spacing="2", width="100%"),
            rx.text("None yet.", color=MUTED, size="2"),
        ),
    )


# --- organizations ---------------------------------------------------------

def org_form() -> rx.Component:
    """The Webex organization form (also shown on top of the organization window)."""
    return rx.vstack(
        _field("Organization", rx.select(S.org_names, value=S.org_customer, on_change=S.set_org_customer,
                                         placeholder="Choose an organization", width="100%"),
               "The customer this Webex org belongs to. Create organizations on the Organizations tab."),
        _field("Name", rx.input(value=S.org_name, on_change=S.set_org_name, width="100%",
                                placeholder="e.g. customer-a")),
        _field("Org ID", rx.input(value=S.form_org_id, on_change=S.set_form_org_id, width="100%",
                                  placeholder="Webex organization ID"),
               "Find it in Control Hub under Account."),
        _field("Credentials", rx.select(S.webex_login_names, value=S.org_login,
                                        on_change=S.set_org_login_form,
                                        placeholder="Choose saved credentials"),
               "Any saved credentials can be used with any Webex organization."),
        rx.hstack(
            rx.dialog.close(rx.button("Cancel", variant="soft", color_scheme="gray")),
            rx.button("Save", on_click=S.save_org),
            justify="end",
            spacing="3",
            width="100%",
        ),
        spacing="4",
        align="start",
        width="100%",
    )


def _org_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(S.org_is_new, "Add Webex Organization", "Edit Webex Organization")),
            org_form(),
            max_width="480px",
        ),
        open=S.org_open,
        on_open_change=S.set_org_open,
    )


def _org_row(o) -> rx.Component:
    return _row(
        rx.vstack(
            rx.hstack(
                rx.text(o["name"], weight="bold"),
                rx.cond(o["name"] == S.webex_active, rx.badge("Active", color_scheme="green"), rx.fragment()),
                align="center",
                spacing="2",
            ),
            rx.text(rx.cond(o["org_id"] != "", "Org ID " + o["org_id"].to(str)[:24], "No org ID"),
                    size="2", color=MUTED),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        rx.select(S.webex_login_names, value=o["login"],
                  on_change=lambda v: S.set_login_for_org(o["name"], v),
                  placeholder="Choose credentials", size="1"),
        rx.cond(o["name"] != S.webex_active,
                rx.button("Use", size="1", variant="soft", on_click=S.use_org(o["name"])), rx.fragment()),
        rx.icon_button(rx.icon("pencil", size=15), variant="ghost", on_click=S.edit_org(o["name"])),
        _delete_button("Delete this organization?", S.delete_org(o["name"])),
    )


def _orgs() -> rx.Component:
    return _section(
        "Webex Organizations", "Webex orgs by name, grouped by customer organization. Choose which saved credentials "
        "each one uses; change it any time.",
        "Add Webex Organization", S.add_org,
        rx.cond(
            S.webex_has_orgs,
            rx.vstack(
                rx.foreach(S.saved_rows, lambda o: rx.cond(
                    o["kind"] == "org",
                    rx.text(o["org"], size="2", weight="bold", color=MUTED, padding_top="0.5rem"),
                    _org_row(o))),
                spacing="2", width="100%"),
            rx.text("None yet.", color=MUTED, size="2"),
        ),
    )


def webex_tab() -> rx.Component:
    return rx.vstack(
        _logins(),
        rx.separator(size="4"),
        _orgs(),
        _login_dialog(),
        _org_dialog(),
        spacing="6",
        align="start",
        width="100%",
    )
