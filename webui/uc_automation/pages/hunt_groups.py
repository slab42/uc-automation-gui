import reflex as rx

from ..components.crud_page import (
    Column, CrudPageConfig, build_crud_page, dependency_dialogs, dependency_toolbar, form_field, text_input,
)
from ..state.hunt_groups import HuntGroupsState as S


def _add_body(S) -> rx.Component:
    return rx.vstack(
        rx.grid(
            form_field("Pilot pattern", text_input(S, "pattern", "5000")),
            form_field("Partition", text_input(S, "routePartitionName", "PT-Internal")),
            columns="2", spacing="3", width="100%",
        ),
        form_field("Description", text_input(S, "description")),
        form_field("Hunt list", text_input(S, "huntListName", "HL-Sales")),
        rx.text("The hunt list must already exist. Line groups and hunt lists are not created here.",
                size="1", color="var(--gray-10)"),
        spacing="3", align="start", width="100%",
    )


hunt_groups = build_crud_page(S, CrudPageConfig(
    title="Hunt Groups",
    noun="hunt pilot",
    key="id",
    columns=[Column("Pilot", "pattern", code=True), Column("Partition", "routePartitionName"),
             Column("Description", "description"), Column("Hunt list", "huntListName")],
    add_body=_add_body,
    add_required="pattern",
    import_notes="pattern and huntListName are required to add. Modify can change the description and hunt list.",
    delete_note=("The hunt list is removed too when no other pilot uses it, and so are its line groups when no "
                 "other hunt list uses them. Use Check dependencies first to see line groups that still have members."),
    extra_toolbar=dependency_toolbar,
    extra_dialogs=lambda S, h: dependency_dialogs(
        S, h, "Hunt group dependencies", "Hunt pilot",
        "Checking hunt lists and line groups. This can take a while..."),
))
