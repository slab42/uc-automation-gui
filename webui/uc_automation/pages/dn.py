import reflex as rx

from ..components.crud_page import Column, CrudPageConfig, build_crud_page
from ..state.dn import AlternateNumbersState, MoveDnState, OrphansState

_DN_COLUMNS = [Column("Directory number", "pattern", code=True), Column("Partition", "routePartitionName"),
               Column("Description", "description")]


# --- Move partition ---

def _move_toolbar(S) -> list[rx.Component]:
    return [rx.button(rx.icon("folder-input", size=16), "Move selected (", S.selected_count.to_string(), ")",
                      disabled=S.selected_count == 0, on_click=S.open_move)]


def _move_dialogs(S, h) -> list[rx.Component]:
    return [
        h.dialog(
            "move", "Move to another partition",
            rx.vstack(
                rx.text("Moves the ", S.selected_count.to_string(),
                        " selected directory number(s) to this route partition.", size="2"),
                rx.hstack(
                    rx.select(S.partition_options, value=S.move_target, on_change=S.set_move_target,
                              placeholder="Choose the new partition", disabled=S.loading_partitions | S.busy,
                              width="100%"),
                    rx.cond(S.loading_partitions, rx.spinner(size="2"), rx.fragment()),
                    align="center", spacing="2", width="100%",
                ),
                h.progress(),
                h.results(),
                rx.hstack(
                    h.close_button(),
                    rx.spacer(),
                    rx.button(rx.icon("folder-input", size=16), "Move", on_click=S.move_selected,
                              disabled=S.busy | (S.move_target == "") | (S.selected_count == 0)),
                    spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
            width="560px",
        ),
    ]


move_partition = build_crud_page(MoveDnState, CrudPageConfig(
    title="Move Partition", noun="directory number", key="id",
    columns=_DN_COLUMNS,
    can_add=False, can_delete=False, import_add=False, modify_label="Move",
    import_notes=("Columns: pattern, routePartitionName (where the DN is now) and newRoutePartitionName "
                  "(where it goes). Export gives a file with the first two filled in. Each DN must exist in "
                  "its current partition."),
    extra_toolbar=_move_toolbar,
    extra_dialogs=_move_dialogs,
))


# --- Alternate numbers ---

def _alt_toolbar(S) -> list[rx.Component]:
    return [rx.button(rx.icon("phone-off", size=16), "Remove alternate numbers (", S.selected_count.to_string(), ")",
                      color_scheme="red", disabled=S.selected_count == 0,
                      on_click=S.set_dialog("altconfirm", True))]


def _alt_dialogs(S, h) -> list[rx.Component]:
    return [
        h.dialog(
            "altconfirm", "Remove alternate numbers?",
            rx.vstack(
                rx.text("This clears the enterprise and E.164 alternate numbers of ", S.selected_count.to_string(),
                        " directory number(s). The directory numbers themselves are kept.", size="2"),
                h.progress(),
                h.results(),
                rx.hstack(
                    h.close_button(),
                    rx.spacer(),
                    rx.button(rx.icon("phone-off", size=16), "Remove", color_scheme="red",
                              on_click=S.remove_selected, disabled=S.busy | (S.selected_count == 0)),
                    spacing="3", width="100%",
                ),
                spacing="3", align="start", width="100%",
            ),
            width="560px",
        ),
    ]


alternate_numbers = build_crud_page(AlternateNumbersState, CrudPageConfig(
    title="Alternate Numbers", noun="directory number", key="id",
    columns=[Column("Directory number", "pattern", code=True), Column("Partition", "routePartitionName"),
             Column("Description", "description"), Column("Enterprise alternate", "enterpriseAltNum"),
             Column("E.164 alternate", "e164AltNum")],
    can_add=False, can_delete=False, import_add=False, modify_label="Remove alternate numbers",
    import_notes=("Columns: pattern and routePartitionName. Both the enterprise and the E.164 alternate number "
                  "are cleared, whether or not they are set. The table lists only directory numbers that have "
                  "an alternate number."),
    extra_toolbar=_alt_toolbar,
    extra_dialogs=_alt_dialogs,
))


# --- Orphans ---

orphans = build_crud_page(OrphansState, CrudPageConfig(
    title="Orphan Directory Numbers", noun="orphan directory number", key="id",
    columns=_DN_COLUMNS,
    can_add=False, can_import=False,
    delete_note=("Only directory numbers not assigned to any device, device profile or remote destination "
                 "profile are listed. CUCM still refuses to remove one that something else uses, such as a "
                 "line group."),
))
