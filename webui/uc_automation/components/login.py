"""Sign-in and first-run Admin setup screens, and the account menu in the top bar."""

import reflex as rx

from ..config import APP_NAME
from ..state.auth import AuthState as A
from ..state.webex_token import WebexTokenState as W


def _password_input(placeholder: str, on_change, **kw) -> rx.Component:
    # Uncontrolled: the value goes to a backend var, never back to the browser. `key` remounts it to clear it.
    return rx.input(type="password", placeholder=placeholder, on_change=on_change, key=A.form_key.to_string(),
                    width="100%", **kw)


def _card(title: str, hint: str, *body: rx.Component) -> rx.Component:
    return rx.center(
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.image(src="/slab42.jpg", width="48px", height="48px", border_radius="var(--radius-3)"),
                    rx.vstack(rx.heading(APP_NAME, size="4"), rx.text(title, size="2", color="var(--gray-11)"),
                              spacing="0", align="start"),
                    align="center", spacing="3",
                ),
                rx.text(hint, size="2", color="var(--gray-11)"),
                *body,
                rx.cond(A.error != "", rx.callout(A.error, icon="triangle-alert", color_scheme="red", size="1")),
                spacing="4", align="start", width="100%",
            ),
            size="4", width="100%", max_width="400px",
        ),
        min_height="100vh", padding="1.5rem",
    )


def sign_in_form() -> rx.Component:
    return _card(
        "Sign In", "Sign in to continue.",
        rx.form(
            rx.vstack(
                rx.input(value=A.login_name, on_change=A.set_login_name, placeholder="User name",
                         auto_complete="username", width="100%", auto_focus=True),
                _password_input("Password", A.set_password, auto_complete="current-password"),
                rx.button("Sign In", type="submit", width="100%"),
                spacing="3", width="100%",
            ),
            on_submit=A.sign_in, width="100%",
        ),
    )


def setup_form() -> rx.Component:
    return _card(
        "First Run Setup",
        "Choose a password for the Admin account. Admin has full access and manages the other users.",
        rx.form(
            rx.vstack(
                rx.input(value="Admin", read_only=True, width="100%", auto_complete="username"),
                _password_input("New password (8 characters or more)", A.set_password, auto_complete="new-password"),
                _password_input("Repeat the password", A.set_password2, auto_complete="new-password"),
                rx.button("Create Admin Account", type="submit", width="100%"),
                spacing="3", width="100%",
            ),
            on_submit=A.setup_admin, width="100%",
        ),
    )


def login_screen() -> rx.Component:
    """What every page shows until the user is signed in."""
    return rx.cond(
        A.checked,
        rx.cond(A.needs_setup, setup_form(), sign_in_form()),
        rx.center(rx.spinner(size="3"), min_height="100vh"),
    )


def no_access() -> rx.Component:
    return rx.callout(
        "Your account does not have access to this page. Ask the Admin to add it to your access list.",
        icon="lock", color_scheme="amber",
    )


def change_password_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Change Password"),
            rx.form(
                rx.vstack(
                    _password_input("Current password", A.set_pw_current, auto_complete="current-password"),
                    _password_input("New password (8 characters or more)", A.set_pw_new, auto_complete="new-password"),
                    _password_input("Repeat the new password", A.set_pw_new2, auto_complete="new-password"),
                    rx.cond(A.pw_error != "", rx.callout(A.pw_error, icon="triangle-alert", color_scheme="red", size="1")),
                    rx.hstack(
                        rx.button("Cancel", type="button", variant="soft", color_scheme="gray",
                                  on_click=A.close_change_password),
                        rx.button("Change Password", type="submit"),
                        spacing="3", justify="end", width="100%",
                    ),
                    spacing="3", width="100%",
                ),
                on_submit=A.change_password,
            ),
            max_width="400px",
        ),
        open=A.pw_open,
        on_open_change=A.set_pw_open,
    )


def webex_token_dialog() -> rx.Component:
    """Paste or remove the signed-in user's personal Webex token. Also opens by itself when a task needs a new one."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Webex Token"),
            rx.form(
                rx.vstack(
                    rx.text("Your personal token from developer.webex.com (Getting Started, Your Personal Access Token). "
                            "It lasts about 12 hours and is used when a Webex tool is denied (403) with the org login.",
                            size="2", color="var(--gray-11)"),
                    rx.cond(W.wx_notice != "", rx.callout(W.wx_notice, icon="clock", color_scheme="amber", size="1"),
                            rx.cond(W.wx_text != "", rx.text(W.wx_text, size="2", color="var(--gray-11)"))),
                    rx.input(type="password", placeholder="Paste the token", on_change=W.set_token,
                             key=W.form_key.to_string(), width="100%", auto_complete="off"),
                    rx.cond(W.wx_error != "", rx.callout(W.wx_error, icon="triangle-alert", color_scheme="red", size="1")),
                    rx.hstack(
                        rx.cond(W.wx_status != "missing",
                                rx.button("Remove", type="button", variant="soft", color_scheme="red", on_click=W.remove_token)),
                        rx.spacer(),
                        rx.button("Cancel", type="button", variant="soft", color_scheme="gray", on_click=W.close_token),
                        rx.button("Save Token", type="submit"),
                        spacing="3", width="100%",
                    ),
                    spacing="3", width="100%",
                ),
                on_submit=W.save_token,
            ),
            max_width="460px",
        ),
        open=W.wx_open,
        on_open_change=W.set_wx_open,
    )


def webex_denied_dialog() -> rx.Component:
    """Offered after a Webex task got a 403: switch to the personal token and rerun it."""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Webex Denied The Request"),
            rx.alert_dialog.description(
                "Webex returned 403 (access denied) with the org's login. Switch to your Personal Token and rerun the task?"),
            rx.hstack(
                rx.button("Not Now", variant="soft", color_scheme="gray", on_click=W.dismiss_prompt),
                rx.button("Switch And Rerun", on_click=W.switch_and_rerun),
                spacing="3", justify="end", margin_top="1rem",
            ),
            max_width="440px",
        ),
        open=W.prompt_open,
    )


def account_menu() -> rx.Component:
    return rx.fragment(
        rx.menu.root(
            rx.menu.trigger(
                rx.button(rx.icon("circle-user", size=16), A.username, rx.icon("chevron-down", size=14),
                          variant="ghost", size="2"),
            ),
            rx.menu.content(
                rx.menu.item("Change Password", on_click=A.open_change_password),
                rx.menu.item("Webex Token", on_click=W.open_token),
                rx.menu.separator(),
                rx.menu.item("Sign Out", on_click=A.sign_out),
            ),
        ),
        change_password_dialog(),
        webex_token_dialog(),
        webex_denied_dialog(),
    )
