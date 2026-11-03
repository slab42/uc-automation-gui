"""Users page (Admin only): user list and the per-user access tree."""

import reflex as rx

from ..components.layout import page
from ..state.users import CATALOG, UsersState as S


def _checkbox(key: str) -> rx.Component:
    """Ticked when every page in the platform or section is ticked; clicking ticks or clears all of them."""
    return rx.checkbox(checked=S.group_state[key] == "all", on_change=lambda _v: S.toggle_group(key))


def _item(it: dict) -> rx.Component:
    label = it["label"] + (" (In Development)" if it["dev"] else "")
    return rx.checkbox(label, checked=S.sel_routes.contains(it["route"]), on_change=lambda _v: S.toggle_route(it["route"]))


def _section(plat: dict, sec: dict) -> rx.Component:
    if len(plat["sections"]) == 1 and plat["slug"] in ("tools", "system"):
        body = rx.vstack(*[_item(i) for i in sec["items"]], spacing="2", align="start", padding_left="1.75rem")
        return body
    return rx.vstack(
        rx.hstack(_checkbox(sec["key"]), rx.text(sec["label"], weight="medium", size="2"), spacing="2", align="center"),
        rx.box(
            rx.grid(*[_item(i) for i in sec["items"]], columns=rx.breakpoints(initial="1", sm="2"), spacing="2", width="100%"),
            padding_left="1.75rem",
        ),
        spacing="2", align="start", width="100%", padding_left="1.75rem",
    )


def _platform(plat: dict) -> rx.Component:
    slug = plat["slug"]
    return rx.box(
        rx.hstack(
            _checkbox(slug),
            rx.text(plat["label"], weight="bold"),
            rx.badge(S.group_count[slug], variant="soft", color_scheme="gray"),
            rx.spacer(),
            rx.icon_button(
                rx.icon(rx.cond(S.expanded.contains(slug), "chevron-up", "chevron-down"), size=16),
                variant="ghost", size="1", on_click=S.toggle_expanded(slug), aria_label="Show Or Hide Pages",
            ),
            align="center", spacing="2", width="100%",
        ),
        rx.cond(
            S.expanded.contains(slug),
            rx.vstack(*[_section(plat, s) for s in plat["sections"]], spacing="3", align="start", width="100%",
                      padding_top="0.75rem"),
        ),
        padding="0.6rem 0.8rem", border="1px solid var(--gray-5)", border_radius="var(--radius-3)", width="100%",
    )


def _user_row(r) -> rx.Component:
    return rx.table.row(
        rx.table.cell(r["username"], font_weight="medium"),
        rx.table.cell(r["role"]),
        rx.table.cell(rx.badge(r["status"], color_scheme=rx.cond(r["status"] == "Enabled", "green", "gray"), variant="soft")),
        rx.table.cell(r["pages"]),
        on_click=S.select_user(r["username"]),
        cursor="pointer",
        background=rx.cond(r["username"] == S.selected, "var(--accent-3)", "transparent"),
        _hover={"background": "var(--gray-3)"},
    )


def _user_list() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading("Users", size="4"),
                rx.spacer(),
                rx.button(rx.icon("user-plus", size=16), "Add User", on_click=S.open_dialog("add")),
                align="center", width="100%",
            ),
            rx.table.root(
                rx.table.header(rx.table.row(
                    rx.table.column_header_cell("User"), rx.table.column_header_cell("Role"),
                    rx.table.column_header_cell("Status"), rx.table.column_header_cell("Pages"),
                )),
                rx.table.body(rx.foreach(S.rows, _user_row)),
                width="100%",
            ),
            rx.text("Click a user to choose what they can open. Admin always has full access.",
                    size="2", color="var(--gray-11)"),
            spacing="3", align="start", width="100%",
        ),
        size="3", width="100%",
    )


def _editor() -> rx.Component:
    return rx.card(
        rx.cond(
            S.has_selected,
            rx.cond(
                S.selected_is_admin,
                rx.callout("Admin always has full access to every page. Change the Admin password from the account menu in the top bar.",
                           icon="shield-check"),
                rx.vstack(
                    rx.hstack(
                        rx.heading(S.selected, size="4"),
                        rx.spacer(),
                        rx.button("Reset Password", variant="soft", on_click=S.open_dialog("password")),
                        rx.button("Delete User", variant="soft", color_scheme="red", on_click=S.open_dialog("delete")),
                        align="center", spacing="2", width="100%", wrap="wrap",
                    ),
                    rx.hstack(
                        rx.switch(checked=S.sel_enabled, on_change=S.set_sel_enabled),
                        rx.text("Account enabled", size="2"),
                        align="center", spacing="2",
                    ),
                    rx.divider(),
                    rx.hstack(
                        rx.text("Pages this user can open", weight="medium"),
                        rx.spacer(),
                        rx.button("Select All", variant="soft", size="1", on_click=S.select_all),
                        rx.button("Deselect All", variant="soft", color_scheme="gray", size="1", on_click=S.deselect_all),
                        rx.button("Expand All", variant="ghost", size="1", on_click=S.expand_all),
                        rx.button("Collapse All", variant="ghost", size="1", on_click=S.collapse_all),
                        align="center", spacing="2", width="100%", wrap="wrap",
                    ),
                    rx.vstack(*[_platform(p) for p in CATALOG], spacing="2", width="100%"),
                    rx.button("Save Access", on_click=S.save_access),
                    spacing="3", align="start", width="100%",
                ),
            ),
            rx.text("Select a user to edit their access.", color="var(--gray-11)"),
        ),
        size="3", width="100%",
    )


def _password_fields(button: str, handler) -> rx.Component:
    def pw(placeholder, on_change):
        return rx.input(type="password", placeholder=placeholder, on_change=on_change, key=S.form_key.to_string(),
                        width="100%", auto_complete="new-password")
    return rx.vstack(
        pw("Password (8 characters or more)", S.set_password),
        pw("Repeat the password", S.set_password2),
        rx.cond(S.form_error != "", rx.callout(S.form_error, icon="triangle-alert", color_scheme="red", size="1")),
        rx.hstack(
            rx.button("Cancel", type="button", variant="soft", color_scheme="gray", on_click=S.close_dialog),
            rx.button(button, type="submit"),
            spacing="3", justify="end", width="100%",
        ),
        spacing="3", width="100%",
    )


def _dialogs() -> rx.Component:
    return rx.fragment(
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("Add User"),
                rx.form(
                    rx.vstack(
                        rx.input(value=S.form_name, on_change=S.set_form_name, placeholder="User name",
                                 auto_complete="off", width="100%"),
                        _password_fields("Add User", S.add_user),
                        spacing="3", width="100%",
                    ),
                    on_submit=S.add_user,
                ),
                rx.text("The new user starts with no access. Choose their pages afterwards.", size="2", color="var(--gray-11)"),
                max_width="420px",
            ),
            open=S.dialog == "add", on_open_change=S.set_dialog_open,
        ),
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title("Reset Password"),
                rx.dialog.description(rx.text("New password for ", S.selected, ". The user is signed out.")),
                rx.form(_password_fields("Reset Password", S.reset_password), on_submit=S.reset_password),
                max_width="420px",
            ),
            open=S.dialog == "password", on_open_change=S.set_dialog_open,
        ),
        rx.alert_dialog.root(
            rx.alert_dialog.content(
                rx.alert_dialog.title("Delete User"),
                rx.alert_dialog.description(rx.text("Delete ", S.selected, "? They lose access at once.")),
                rx.hstack(
                    rx.button("Cancel", variant="soft", color_scheme="gray", on_click=S.close_dialog),
                    rx.button("Delete", color_scheme="red", on_click=S.delete_user),
                    spacing="3", justify="end", margin_top="1rem",
                ),
            ),
            open=S.dialog == "delete", on_open_change=S.set_dialog_open,
        ),
    )


def users_page() -> rx.Component:
    return page(
        "Users",
        rx.cond(
            S.is_admin,
            rx.vstack(_user_list(), _editor(), _dialogs(), spacing="4", width="100%"),
            rx.callout("Only the Admin account can manage users.", icon="lock", color_scheme="amber"),
        ),
    )
