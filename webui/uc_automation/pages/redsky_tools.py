"""RedSky pages: home cards, one generic Add page (single form + Paste Text + CSV) and one generic Check page."""

import reflex as rx

from ..backend import redsky_alerts as alerts, redsky_geography as geo, redsky_networking as net
from ..backend.redsky_common import AddSpec, CheckSpec, Field
from ..components.redsky_nav import GROUPS, need_connection, redsky_page
from ..components.tool_widgets import code_block, csv_dropzone, field, paste_csv_tabs, run_results
from ..state.redsky_tools import (AddAlertsState, AddBuildingsState, AddLocationsState, AlertsCheckState,
                                  BssidState, EntireSiteState, LldpState, PrivateIpState, PublicIpState)
from .cucm_home import _card


def redsky_home() -> rx.Component:
    return redsky_page(
        "RedSky",
        rx.vstack(
            rx.text("RedSky E911 location management", color="var(--gray-11)"),
            *[
                rx.vstack(
                    rx.heading(label, size="4"),
                    rx.grid(
                        *[_card(icon, name, desc, route) for name, route, icon, desc in items],
                        columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                        spacing="4",
                        width="100%",
                    ),
                    spacing="3", align="start", width="100%",
                )
                for label, items in GROUPS
            ],
            spacing="4",
            align="start",
        ),
    )


def _control(S, spec: AddSpec, f: Field) -> rx.Component:
    if f.yesno:
        return rx.select(["Not Set", "Yes", "No"], value=S.row[f.key], on_change=lambda v: S.set_row_field(f.key, v))
    box = rx.input(value=S.row[f.key], on_change=lambda v: S.set_row_field(f.key, v), width="100%",
                   auto_complete="off", list=f"{spec.slug}-{f.key}" if f.options else None)
    if not f.options:
        return box
    return rx.fragment(
        box,
        rx.el.datalist(rx.foreach(S.lookups[f.options], lambda n: rx.el.option(value=n)), id=f"{spec.slug}-{f.key}"),
    )


def add_page(S, spec: AddSpec) -> rx.Component:
    upload_id = f"{spec.slug}_upload"
    fields = [field(f.label + (" *" if f.required else ""), _control(S, spec, f), f.hint) for f in spec.fields]
    columns = ", ".join(spec.columns)
    return redsky_page(
        spec.title,
        need_connection(rx.vstack(
            rx.text(spec.blurb, size="2", color="var(--gray-11)"),
            rx.card(
                rx.vstack(
                    rx.heading(f"One {spec.noun}", size="4"),
                    rx.grid(*fields, columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%"),
                    rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add",
                              on_click=S.add_single, disabled=S.busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading(f"Multiple {spec.noun}s", size="4"),
                    paste_csv_tabs(
                        S.paste_rows, lambda v: S.set_paste("rows", v),
                        f"One per line. Columns, in order: {columns}. A header row is optional. {spec.csv_note}",
                        spec.example.splitlines()[1] if len(spec.example.splitlines()) > 1 else "",
                        rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)), "Add",
                                  on_click=S.add_from_text, disabled=S.busy),
                        [
                            rx.text(f"Header row required. Columns, in order: {columns}. {spec.csv_note}",
                                    size="2", color="var(--gray-11)"),
                            code_block(spec.example),
                            csv_dropzone(upload_id),
                            rx.hstack(
                                rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("upload", size=16)), "Add",
                                          on_click=S.add_from_csv(rx.upload_files(upload_id=upload_id)),
                                          disabled=S.busy),
                                rx.button(rx.icon("download", size=16), "Download Template", variant="soft",
                                          on_click=S.download_template),
                                spacing="3",
                            ),
                        ],
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            run_results(S, spec.noun.capitalize()),
            spacing="4", align="start", width="100%",
        )),
    )


def check_page(S, spec: CheckSpec) -> rx.Component:
    return redsky_page(
        spec.title,
        need_connection(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.text(spec.blurb, size="2", color="var(--gray-11)"),
                    rx.button(rx.cond(S.checking, rx.spinner(size="2"), rx.icon("play", size=16)), "Run Check",
                              on_click=S.run_check, disabled=S.checking),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(S.error != "", rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.cond(
                S.checked,
                rx.cond(
                    S.problems.length() > 0,
                    rx.vstack(
                        rx.hstack(
                            rx.badge(S.problems.length().to_string() + " of " + S.total.to_string() + " "
                                     + spec.noun + "(s) have a problem", color_scheme="red"),
                            rx.spacer(),
                            rx.button(rx.icon("download", size=16), "Export CSV", variant="soft",
                                      on_click=S.export_csv),
                            align="center", width="100%",
                        ),
                        rx.card(
                            rx.scroll_area(
                                rx.table.root(
                                    rx.table.header(rx.table.row(
                                        *[rx.table.column_header_cell(h) for _k, h in spec.columns])),
                                    rx.table.body(rx.foreach(S.problems, lambda r: rx.table.row(
                                        *[rx.table.cell(r[k]) for k, _h in spec.columns]))),
                                    variant="ghost", width="100%",
                                ),
                                max_height="60vh",
                            ),
                            padding="0", width="100%",
                        ),
                        spacing="3", align="start", width="100%",
                    ),
                    rx.callout(rx.text(spec.ok_message, " ", S.total.to_string(), " checked."),
                               icon="circle-check", color_scheme="green", width="100%"),
                ),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        )),
    )


def buildings_add() -> rx.Component:
    return add_page(AddBuildingsState, geo.BUILDINGS_ADD)


def locations_add() -> rx.Component:
    return add_page(AddLocationsState, geo.LOCATIONS_ADD)


def entire_site() -> rx.Component:
    return check_page(EntireSiteState, geo.ENTIRE_SITE)


def alerts_add() -> rx.Component:
    return add_page(AddAlertsState, alerts.ALERTS_ADD)


def alerts_check() -> rx.Component:
    return check_page(AlertsCheckState, alerts.ALERTS_CHECK)


def bssid() -> rx.Component:
    return add_page(BssidState, net.BSSID)


def lldp() -> rx.Component:
    return add_page(LldpState, net.LLDP)


def private_ip() -> rx.Component:
    return add_page(PrivateIpState, net.PRIVATE_IP)


def public_ip() -> rx.Component:
    return add_page(PublicIpState, net.PUBLIC_IP)
