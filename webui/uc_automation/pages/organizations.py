"""Credentials > Organizations: the list of customer organizations and the organization window.

The window shows what an organization holds, with an Add button per platform. Each button opens that platform's form
on top of the window; saving closes the form and the window behind it already shows the new entry."""

import reflex as rx

from ..backend.organizations import UNASSIGNED
from ..state.cube import CubeState
from ..state.cuc import CucState
from ..state.cucm import CucmState
from ..state.org import OrgState as O
from ..state.redsky import RedskyState
from ..state.webex import WebexState

MUTED = "var(--gray-11)"


def _item(name, detail, on_edit, on_delete) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text(name, weight="bold"),
            rx.text(detail, size="2", color=MUTED),
            spacing="0",
            align="start",
        ),
        rx.spacer(),
        rx.icon_button(rx.icon("pencil", size=15), variant="ghost", on_click=on_edit),
        rx.icon_button(rx.icon("trash-2", size=15), variant="ghost", color_scheme="red", on_click=on_delete),
        align="center",
        width="100%",
        padding="0.5rem 0.75rem",
        border="1px solid var(--gray-5)",
        border_radius="var(--radius-3)",
    )


# key, label, the organization's entries, list row builder, events that empty the form
PLATFORMS = (
    ("cucm", "CUCM", CucmState.org_items,
     lambda c: _item(c["name"], c["server"] + "  ·  " + c["username"],
                     [CucmState.edit_connection(c["name"]), O.open_platform("cucm")],
                     CucmState.delete_connection(c["name"])),
     [CucmState.new_connection]),
    ("cuc", "CUC", CucState.org_items,
     lambda c: _item(c["name"], c["server"] + "  ·  " + c["username"],
                     [CucState.edit_connection(c["name"]), O.open_platform("cuc")],
                     CucState.delete_connection(c["name"])),
     [CucState.new_connection]),
    ("cube", "CUBE", CubeState.org_items,
     lambda c: _item(c["name"], c["username"],
                     [CubeState.edit_credential(c["name"]), O.open_platform("cube")],
                     CubeState.delete_credential(c["name"])),
     [CubeState.new_credential]),
    ("webex", "Webex", WebexState.org_items,
     lambda c: _item(c["name"], rx.cond(c["org_id"] != "", "Org ID " + c["org_id"].to(str)[:24], "No org ID"),
                     [WebexState.fill_org_form(c["name"]), O.open_platform("webex")],
                     WebexState.delete_org(c["name"])),
     [WebexState.new_org_form]),
    ("redsky", "RedSky", RedskyState.org_items,
     lambda c: _item(c["name"], c["username"] + "  ·  org " + c["org_id"],
                     [RedskyState.edit_connection(c["name"]), O.open_platform("redsky")],
                     RedskyState.delete_connection(c["name"])),
     [RedskyState.new_connection]),
)

# setters that preselect the open organization in a fresh form
_SET_ORG = {
    "cucm": lambda: CucmState.set_form("org", O.org_view),
    "cuc": lambda: CucState.set_form("org", O.org_view),
    "cube": lambda: CubeState.set_form("org", O.org_view),
    "webex": lambda: WebexState.set_org_customer(O.org_view),
    "redsky": lambda: RedskyState.set_form("org", O.org_view),
}


def _platform_section(key, label, items, row, reset) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading(label, size="3"),
            rx.spacer(),
            rx.cond(
                O.org_view != UNASSIGNED,
                rx.button(rx.icon("plus", size=15), "Add " + label, size="1", variant="soft",
                          on_click=[*reset, _SET_ORG[key](), O.open_platform(key)]),
                rx.fragment(),
            ),
            align="center",
            width="100%",
        ),
        rx.cond(
            items.length() > 0,
            rx.vstack(rx.foreach(items, row), spacing="2", width="100%"),
            rx.text("None yet.", size="2", color=MUTED),
        ),
        spacing="2",
        align="start",
        width="100%",
    )


def _platform_dialog(key: str, label: str, form: rx.Component) -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(label),
            rx.box(form, margin_top="0.5rem"),
            max_width="560px",
        ),
        open=O.plat_dialog == key,
        on_open_change=O.set_plat_open,
    )


def _org_window(forms: dict) -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.hstack(
                rx.dialog.title(O.org_view, margin="0"),
                rx.spacer(),
                rx.cond(
                    O.org_view != UNASSIGNED,
                    rx.alert_dialog.root(
                        rx.alert_dialog.trigger(
                            rx.button(rx.icon("trash-2", size=15), "Delete Organization", size="1", variant="soft",
                                      color_scheme="red")),
                        rx.alert_dialog.content(
                            rx.alert_dialog.title("Delete this organization?"),
                            rx.alert_dialog.description("It must not hold any platform entries."),
                            rx.hstack(
                                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray")),
                                rx.alert_dialog.action(
                                    rx.button("Delete", color_scheme="red", on_click=O.delete_org_by_name(O.org_view))),
                                spacing="3", justify="end", margin_top="1rem",
                            ),
                        ),
                    ),
                    rx.fragment(),
                ),
                align="center",
                width="100%",
            ),
            rx.dialog.description(
                rx.cond(O.org_view == UNASSIGNED,
                        "Entries saved before organizations existed. Edit one and choose an organization to move it.",
                        "Add as many of each platform as the customer has."),
                size="2", color=MUTED, margin_bottom="1rem",
            ),
            rx.vstack(
                *[_platform_section(key, label, items, row, reset) for key, label, items, row, reset in PLATFORMS],
                spacing="5",
                align="start",
                width="100%",
            ),
            rx.hstack(
                rx.dialog.close(rx.button("Close", variant="soft", color_scheme="gray")),
                justify="end",
                margin_top="1rem",
            ),
            *[_platform_dialog(key, label, forms[key]) for key, label, *_ in PLATFORMS],
            max_width="640px",
            max_height="85vh",
            overflow_y="auto",
        ),
        open=O.org_view != "",
        on_open_change=O.set_org_view_open,
    )


def _org_tile(o) -> rx.Component:
    return rx.vstack(
        rx.text(o["name"], weight="bold", size="3"),
        rx.text(o["count"] + " entries", size="1", color=MUTED),
        on_click=O.open_org(o["name"]),
        spacing="0",
        align="start",
        padding="0.6rem 0.8rem",
        border="1px solid var(--gray-5)",
        border_radius="var(--radius-3)",
        cursor="pointer",
        _hover={"background": "var(--gray-3)"},
    )


def _new_org_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Add Organization"),
            rx.vstack(
                rx.text("Name", size="2", weight="medium"),
                rx.input(value=O.new_org_name, on_change=O.set_new_org_name, placeholder="e.g. customer-a",
                         width="100%", auto_focus=True),
                rx.text("Letters, digits, '.', '_' or '-'.", size="1", color="var(--gray-10)"),
                rx.hstack(
                    rx.dialog.close(rx.button("Cancel", variant="soft", color_scheme="gray")),
                    rx.button("Add", on_click=O.create_org),
                    justify="end", spacing="3", width="100%",
                ),
                spacing="2",
                align="start",
                width="100%",
            ),
            max_width="420px",
        ),
        open=O.new_org_open,
        on_open_change=O.set_new_org_open,
    )


def organizations_tab(forms: dict) -> rx.Component:
    """`forms` maps cucm, cuc, cube, webex and redsky to the platform's form (built in credentials.py)."""
    return rx.vstack(
        rx.hstack(
            rx.vstack(
                rx.heading("Organizations", size="5"),
                rx.text("Group each customer's platforms. Open an organization to add or change its CUCM, CUC, CUBE, "
                        "Webex and RedSky entries.", size="2", color=MUTED),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.button(rx.icon("plus", size=16), "Add Organization", on_click=O.set_new_org_open(True)),
            align="center",
            width="100%",
        ),
        rx.cond(
            O.org_rows.length() > 0,
            rx.grid(rx.foreach(O.org_rows, _org_tile), columns=rx.breakpoints(initial="2", sm="3", lg="4"),
                    spacing="3", width="100%"),
            rx.text("None yet. Add an organization, then add its platforms.", size="2", color=MUTED),
        ),
        _new_org_dialog(),
        _org_window(forms),
        spacing="4",
        align="start",
        width="100%",
    )
