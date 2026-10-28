import reflex as rx

from ..components.crud_page import Column, CrudPageConfig, build_crud_page, form_field, text_input
from ..state.css import CssState as S


def _add_body(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "CSS-Internal")),
        form_field("Description", text_input(S, "description")),
        form_field("Partitions, in order", text_input(S, "members", "PT-Internal;PT-Local")),
        rx.text("Separate partition names with a semicolon. The first one is searched first.",
                size="1", color="var(--gray-10)"),
        spacing="3", align="start", width="100%",
    )


css = build_crud_page(S, CrudPageConfig(
    title="Calling Search Spaces",
    noun="calling search space",
    key="name",
    columns=[Column("Name", "name", code=True), Column("Description", "description"),
             Column("Partitions (in order)", "members")],
    add_body=_add_body,
    import_notes=("members lists partition names in order, separated by semicolons. "
                  "In Modify, a members value replaces the whole list."),
))
