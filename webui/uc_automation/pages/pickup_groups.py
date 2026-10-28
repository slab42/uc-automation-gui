import reflex as rx

from ..backend.cucm_routing import PICKUP_NOTIFICATIONS
from ..components.crud_page import (
    Column, CrudPageConfig, build_crud_page, dependency_dialogs, dependency_toolbar, form_field, text_input,
)
from ..state.pickup_groups import PickupGroupsState as S


def _add_body(S) -> rx.Component:
    return rx.vstack(
        rx.grid(
            form_field("Name", text_input(S, "name", "CPG-Sales")),
            form_field("Pattern", text_input(S, "pattern", "5001")),
            columns="2", spacing="3", width="100%",
        ),
        form_field("Description", text_input(S, "description")),
        rx.grid(
            form_field("Partition", text_input(S, "routePartitionName", "PT-Internal")),
            form_field("Pickup notification", rx.select(
                PICKUP_NOTIFICATIONS, value=S.new_form["pickupNotification"],
                on_change=lambda v: S.set_new("pickupNotification", v), width="100%")),
            columns="2", spacing="3", width="100%",
        ),
        rx.text("The pattern is the number users dial to pick up a call in this group.",
                size="1", color="var(--gray-10)"),
        spacing="3", align="start", width="100%",
    )


pickup_groups = build_crud_page(S, CrudPageConfig(
    title="Call Pickup Groups",
    noun="call pickup group",
    key="name",
    columns=[Column("Name", "name", code=True), Column("Pattern", "pattern"),
             Column("Description", "description"), Column("Partition", "routePartitionName"),
             Column("Notification", "pickupNotification")],
    add_body=_add_body,
    import_notes=("name and pattern are required to add. Modify can only change the description and "
                  "pickupNotification (No Alert, Audio Alert, Visual Alert, Audio and Visual Alert)."),
    delete_note="Check dependencies first: groups still assigned to lines or hunt pilots cannot be removed.",
    extra_toolbar=dependency_toolbar,
    extra_dialogs=lambda S, h: dependency_dialogs(
        S, h, "Call pickup group dependencies", "Group",
        "Checking directory numbers, hunt pilots and nested groups. This can take a while..."),
))
