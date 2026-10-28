import reflex as rx

from ..components.crud_page import Column, CrudPageConfig, build_crud_page, form_field, text_input
from ..state.translation_patterns import TranslationPatternsState as S


def _add_body(S) -> rx.Component:
    return rx.vstack(
        rx.grid(
            form_field("Pattern", text_input(S, "pattern", "9XXX")),
            form_field("Partition", text_input(S, "routePartitionName", "PT-Translation")),
            columns="2", spacing="3", width="100%",
        ),
        form_field("Description", text_input(S, "description")),
        form_field("Calling search space", text_input(S, "callingSearchSpaceName")),
        rx.grid(
            form_field("Called party mask", text_input(S, "calledPartyTransformationMask", "5551234XXX")),
            form_field("Calling party mask", text_input(S, "callingPartyTransformationMask")),
            columns="2", spacing="3", width="100%",
        ),
        spacing="3", align="start", width="100%",
    )


translation_patterns = build_crud_page(S, CrudPageConfig(
    title="Translation Patterns",
    noun="translation pattern",
    key="id",
    columns=[Column("Pattern", "pattern", code=True), Column("Partition", "routePartitionName"),
             Column("Description", "description"), Column("CSS", "callingSearchSpaceName"),
             Column("Called mask", "calledPartyTransformationMask"),
             Column("Calling mask", "callingPartyTransformationMask")],
    add_body=_add_body,
    add_required="pattern",
    import_notes=("pattern and routePartitionName are required to add. Modify finds the pattern by pattern and "
                  "partition and changes the other columns that are filled in."),
    can_copy=True,
))
