import reflex as rx

from ..components.crud_page import Column, CrudPageConfig, build_crud_page, form_field, text_input
from ..state.route_patterns import RoutePatternsState as S


def _add_body(S) -> rx.Component:
    return rx.vstack(
        rx.grid(
            form_field("Pattern", text_input(S, "pattern", "9.911")),
            form_field("Partition", text_input(S, "routePartitionName", "PT-PSTN")),
            columns="2", spacing="3", width="100%",
        ),
        form_field("Description", text_input(S, "description")),
        rx.grid(
            form_field("Route list", text_input(S, "routeListName", "RL-PSTN")),
            form_field("or Gateway", text_input(S, "gatewayName")),
            columns="2", spacing="3", width="100%",
        ),
        rx.text("Give a route list or a gateway, not both. CUCM stores a literal + as \\+ in the pattern.",
                size="1", color="var(--gray-10)"),
        spacing="3", align="start", width="100%",
    )


def _toolbar(S) -> list[rx.Component]:
    return [rx.button(rx.icon("copy-check", size=16), "Find duplicates", variant="soft",
                      on_click=S.find_duplicates, disabled=S.items.length() == 0)]


def _dialogs(S, h) -> list[rx.Component]:
    return [
        h.dialog(
            "dups", "Duplicate-ish route patterns",
            rx.vstack(
                rx.text("Each '.+' pattern below has a '+' pattern with the same last 11 characters. "
                        "Select the '.+' ones, then use Delete selected to keep only the '+' pattern.",
                        size="2", color="var(--gray-11)"),
                rx.cond(
                    S.dup_pairs.length() == 0,
                    rx.callout("No duplicate-ish patterns found.", icon="circle-check", color_scheme="green",
                               size="1", width="100%"),
                    rx.scroll_area(
                        rx.table.root(
                            rx.table.header(rx.table.row(
                                rx.table.column_header_cell("Delete (.+)"),
                                rx.table.column_header_cell("Partition"),
                                rx.table.column_header_cell("Keep (+)"),
                                rx.table.column_header_cell("Partition"),
                            )),
                            rx.table.body(rx.foreach(S.dup_pairs, lambda d: rx.table.row(
                                rx.table.cell(rx.code(d["dot_plus"])),
                                rx.table.cell(d["partition"]),
                                rx.table.cell(rx.code(d["plus"])),
                                rx.table.cell(d["plus_partition"]),
                            ))),
                            size="1",
                        ),
                        max_height="320px",
                    ),
                ),
                rx.hstack(
                    h.close_button(),
                    rx.spacer(),
                    rx.button(rx.icon("list-checks", size=16), "Select the .+ patterns", variant="soft",
                              on_click=S.select_dot_plus, disabled=S.dup_pairs.length() == 0),
                    spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
            width="800px",
        ),
    ]


route_patterns = build_crud_page(S, CrudPageConfig(
    title="Route Patterns",
    noun="route pattern",
    key="id",
    columns=[Column("Pattern", "pattern", code=True), Column("Partition", "routePartitionName"),
             Column("Description", "description")],
    add_body=_add_body,
    add_required="pattern",
    import_notes=("pattern, routePartitionName and a routeListName or gatewayName are required to add. "
                  "Modify changes the description and destination. CUCM does not return the destination "
                  "when listing, so it is blank in the table and in exports."),
    can_copy=True,
    extra_toolbar=_toolbar,
    extra_dialogs=_dialogs,
))
