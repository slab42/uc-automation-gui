"""RedSky pages: home cards, one generic Add page (single form + Paste Text + CSV) and one generic Check page."""

import reflex as rx

from ..components.access import group_visible, show_if
from ..backend import redsky_alerts as alerts, redsky_audit as audit, redsky_geography as geo, redsky_networking as net, redsky_precheck as pre
from ..backend.redsky_common import AddSpec, CheckSpec, Field
from ..components.redsky_nav import GROUPS, IN_DEVELOPMENT, need_connection, redsky_page
from ..state.settings import SettingsState
from ..components.tool_widgets import (code_block, confirm_dialog, csv_dropzone, field, one_multiple_card, paste_csv_tabs, plural,
                                        run_results, title_case)
from ..state.redsky_tools import (AddAlertsState, AddBuildingsState, AddLocationsState, AlertsCheckState,
                                  BssidState, DuplicatesState, LldpState, NoLocationsState,
                                  NoTrackingState, PrecheckState, PrimaryLocationState, PrivateIpState, PublicIpState, RemediateState)
from .cucm_home import _card


def _dev_gated(card: rx.Component, route: str) -> rx.Component:
    if route not in IN_DEVELOPMENT:
        return card
    return rx.cond(SettingsState.experimental == "1", card, rx.fragment())


def redsky_home() -> rx.Component:
    return redsky_page(
        "RedSky",
        rx.vstack(
            rx.text("RedSky E911 location management", color="var(--gray-11)"),
            *[
                rx.cond(group_visible([i[1] for i in items], IN_DEVELOPMENT), rx.vstack(
                    rx.heading(label, size="4"),
                    rx.grid(
                        *[show_if(route, _dev_gated(_card(icon, name, desc, route), route))
                          for name, route, icon, desc in items],
                        columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                        spacing="4",
                        width="100%",
                    ),
                    spacing="3", align="start", width="100%",
                ), rx.fragment())
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
            one_multiple_card(
f"One {title_case(spec.noun)}", [
rx.grid(*fields, columns=rx.breakpoints(initial="1", md="2"), spacing="3", width="100%"),
rx.button(rx.cond(S.busy, rx.spinner(size="2"), rx.icon("plus", size=16)), "Add",
                              on_click=S.add_single, disabled=S.busy),
], f"Multiple {title_case(plural(spec.noun))}", [
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
]),
            run_results(S, title_case(spec.noun)),
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
                    rx.cond(spec.input_label != "", field(
                        spec.input_label + " *",
                        rx.input(value=S.input_value, on_change=S.set_input_value, width="100%", auto_complete="off",
                                 placeholder=spec.input_placeholder),
                        spec.input_hint), rx.fragment()),
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


def primary_location() -> rx.Component:
    return check_page(PrimaryLocationState, audit.PRIMARY_LOCATION)


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



def _kind_radio() -> rx.Component:
    return rx.radio_group(list(pre.KINDS), value=PrecheckState.kind, on_change=PrecheckState.set_kind, direction="row",
                          spacing="4")


def _check_button(on_click) -> rx.Component:
    return rx.button(rx.cond(PrecheckState.checking, rx.spinner(size="2"), rx.icon("search-check", size=16)),
                     "Run Precheck", on_click=on_click, disabled=PrecheckState.checking)


def _result_table(cols) -> rx.Component:
    return rx.table.root(
        rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for _k, h in cols])),
        rx.table.body(rx.foreach(PrecheckState.found, lambda r: rx.table.row(
            *[rx.table.cell(rx.badge(r[k], color_scheme=rx.cond(r[k] == "Exists", "green", "orange"))
                            if k == "status" else r[k]) for k, _h in cols]))),
        variant="ghost", width="100%",
    )


def _by_kind(buildings: str, locations: str, ips: str):
    return rx.match(PrecheckState.kind, ("Buildings", buildings), ("Locations", locations), ips)


def import_precheck() -> rx.Component:
    S = PrecheckState
    return redsky_page(
        "Import Precheck",
        need_connection(rx.vstack(
            rx.text("Check an import list against RedSky before you load it. Pick Buildings to check that each name is "
                    "new and, when you add an address, that no other Building already uses it. Pick Locations to "
                    "check that each Location is new (optionally under a given Building). Pick Private IPs to check "
                    "that each range does not already exist or overlap an existing range. Names are matched "
                    "case-insensitively, ignoring extra spaces. Nothing is added to RedSky.",
                    size="2", color="var(--gray-11)"),
            rx.card(
                rx.vstack(
                    paste_csv_tabs(
                        S.paste_names, lambda v: S.set_paste("names", v),
                        _by_kind(
                            "One Building per line. Add the full address after a tab or | to also check the address "
                            "against every other Building. Results: Exists, Exists - Address Differs, "
                            "Exists - Address Conflict, Address Conflict (new name, address already used; the "
                            "Building is named in Conflicts With), Not Found, Duplicate In List.",
                            "One per line. Add the Building after a tab or | , or write 'Building / Location'. "
                            "Results: Exists, Not Found, Building Not Found, Duplicate In List.",
                            "One range per line: low and high address separated by a tab, | , comma, space or -. "
                            "A single address or a CIDR block (10.10.1.0/24) also works. Results: Exists, Overlaps "
                            "(with the Location and range it overlaps), Not Found, Invalid, Duplicate In List.",
                        ),
                        _by_kind("HQ Building | 100 Main St, Springfield, IL 62701", "Room 101 | HQ Building",
                                 "10.10.1.0-10.10.1.255"),
                        _check_button(S.check_text),
                        [
                            _kind_radio(),
                            rx.text(_by_kind(
                                "Building name in the first column, full address (optional) in the second. "
                                "Header row optional.",
                                "Location in the first column, Building (optional) in the second. Header row optional.",
                                "Low address in the first column, high address in the second (or a CIDR block in "
                                "the first). Header row optional.",
                            ), size="2", color="var(--gray-11)"),
                            csv_dropzone("precheck_upload"),
                            _check_button(S.check_csv(rx.upload_files(upload_id="precheck_upload"))),
                        ],
                        paste_top=_kind_radio(),
                    ),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(S.error != "", rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.cond(
                S.checked,
                rx.vstack(
                    rx.hstack(
                        rx.badge(S.exists_count.to_string() + " exist", color_scheme="green"),
                        rx.badge(S.other_count.to_string() + " not found or need attention",
                                 color_scheme=rx.cond(S.other_count > 0, "orange", "gray")),
                        rx.spacer(),
                        rx.button(rx.icon("download", size=16), "Export CSV", variant="soft", on_click=S.export_csv),
                        align="center", width="100%",
                    ),
                    rx.card(
                        rx.scroll_area(
                            rx.match(S.result_kind, ("Buildings", _result_table(pre.BUILDING_COLUMNS)),
                                     ("Locations", _result_table(pre.LOCATION_COLUMNS)),
                                     _result_table(pre.IP_COLUMNS)),
                            max_height="60vh",
                        ),
                        padding="0", width="100%",
                    ),
                    spacing="3", align="start", width="100%",
                ),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        )),
    )


def no_locations() -> rx.Component:
    return check_page(NoLocationsState, audit.NO_LOCATIONS)


def no_tracking() -> rx.Component:
    return check_page(NoTrackingState, audit.NO_TRACKING)


def _plain_table(cols, rows) -> rx.Component:
    return rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for _k, h in cols])),
                rx.table.body(rx.foreach(rows, lambda r: rx.table.row(*[rx.table.cell(r[k]) for k, _h in cols]))),
                variant="ghost", width="100%",
            ),
            max_height="60vh",
        ),
        padding="0", width="100%",
    )


def _duplicate_table(S) -> rx.Component:
    return rx.card(
        rx.scroll_area(
            rx.table.root(
                rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for _k, h in audit.DUPLICATE_COLUMNS])),
                rx.table.body(rx.foreach(S.rows, lambda r: rx.table.row(*[
                    rx.table.cell(r[k], background=rx.cond(r["badName"] == "1", "#FFFF00", ""),
                                  color=rx.cond(r["badName"] == "1", "black", "inherit"))
                    if k == "building" else rx.table.cell(r[k]) for k, _h in audit.DUPLICATE_COLUMNS]))),
                variant="ghost", width="100%",
            ),
            max_height="60vh",
        ),
        padding="0", width="100%")


def duplicate_buildings() -> rx.Component:
    S = DuplicatesState
    return redsky_page(
        "Find Duplicate Buildings",
        need_connection(rx.vstack(
            rx.card(
                rx.vstack(
                    rx.text("List Buildings that share an address. Addresses are compared with punctuation and street "
                            "words normalized, ignoring a trailing city, state or ZIP. Nothing is changed in RedSky.",
                            size="2", color="var(--gray-11)"),
                    rx.button(rx.cond(S.checking, rx.spinner(size="2"), rx.icon("play", size=16)), "Run Report",
                              on_click=S.run_find, disabled=S.checking),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(S.error != "", rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.cond(
                S.checked,
                rx.cond(
                    S.rows.length() > 0,
                    rx.vstack(
                        rx.hstack(
                            rx.badge(S.group_count.to_string() + " duplicate address(es), "
                                     + S.rows.length().to_string() + " buildings", color_scheme="red"),
                            rx.spacer(),
                            rx.button(rx.icon("download", size=16), "Export Excel", variant="soft",
                                      on_click=S.export_excel),
                            align="center", width="100%",
                        ),
                        rx.text("Yellow Building name: a Location name in the group is contained in it, so it is "
                                "probably a Building name with a Location added. The Excel file also has the Location "
                                "names and the Correct Building Name dropdown.", size="1", color="var(--gray-11)"),
                        _duplicate_table(S),
                        spacing="3", align="start", width="100%",
                    ),
                    rx.callout(rx.text("No duplicate Buildings. ", S.total.to_string(), " checked."),
                               icon="circle-check", color_scheme="green", width="100%"),
                ),
                rx.fragment(),
            ),
            spacing="4", align="start", width="100%",
        )),
    )


def _group_card(g) -> rx.Component:
    S = RemediateState
    return rx.card(
        rx.vstack(
            rx.text(g["address"], weight="bold", size="2"),
            rx.text("Keep:", size="1", color="var(--gray-11)"),
            rx.radio_group(g["options"].to(list[str]), value=g["keep"].to(str), on_change=lambda v: S.set_keep(g["id"], v),
                           spacing="2", disabled=S.busy),
            spacing="2", align="start", width="100%",
        ),
        width="100%",
    )


def duplicates_remediate() -> rx.Component:
    S = RemediateState
    busy = S.scanning | S.planning | S.busy
    return redsky_page(
        "Remediate Duplicate Buildings",
        need_connection(rx.vstack(
            rx.callout("This tool is still under development. Review the result before relying on it.",
                       icon="construction", color_scheme="amber", width="100%"),
            rx.card(
                rx.vstack(
                    rx.text("Keep one Building per address and remove the rest. For each Location of a duplicate, the "
                            "tracking (static MACs, LLDP switches and ports, BSSIDs, Private IP ranges) is moved to the "
                            "Location of the same name in the kept Building, which is created first when it is missing "
                            "(\"<Building> - Entire Site\" maps to the kept Building's own). The old Location and then "
                            "the duplicate Building are deleted. This cannot be undone. Use Preview first.",
                            size="2", color="var(--gray-11)"),
                    rx.button(rx.cond(S.scanning, rx.spinner(size="2"), rx.icon("search", size=16)),
                              "Find Duplicates", on_click=S.scan, disabled=busy),
                    spacing="3", align="start", width="100%",
                ),
                size="3", width="100%",
            ),
            rx.cond(S.error != "", rx.callout(S.error, icon="triangle-alert", color_scheme="red", width="100%"),
                    rx.fragment()),
            rx.cond(
                S.scanned,
                rx.cond(
                    S.groups.length() > 0,
                    rx.vstack(
                        rx.text("Choose the Building to keep for each address. Every other Building in the group is "
                                "deleted.", size="2", color="var(--gray-11)"),
                        rx.foreach(S.groups, _group_card),
                        rx.hstack(
                            rx.button(rx.cond(S.planning, rx.spinner(size="2"), rx.icon("eye", size=16)),
                                      "Preview", variant="soft", on_click=S.make_preview, disabled=busy),
                            rx.button(rx.icon("trash-2", size=16), "Remediate", color_scheme="red",
                                      on_click=S.set_confirm_open(True), disabled=busy | ~S.previewed),
                            spacing="3",
                        ),
                        rx.cond(S.previewed, _plain_table(audit.PREVIEW_COLUMNS, S.preview), rx.fragment()),
                        spacing="3", align="start", width="100%",
                    ),
                    rx.callout("No duplicate Buildings found.", icon="circle-check", color_scheme="green",
                               width="100%"),
                ),
                rx.fragment(),
            ),
            run_results(S, "Step"),
            confirm_dialog(S, "Delete the duplicate Buildings?",
                           S.dup_count.to_string() + " duplicate Building(s) and their Locations will be deleted "
                           "after their tracking is moved. This cannot be undone.",
                           "Remediate", S.remediate),
            spacing="4", align="start", width="100%",
        )),
    )
