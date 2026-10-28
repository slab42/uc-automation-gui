import reflex as rx

from ..components.crud_page import Column, CrudPageConfig, build_crud_page, form_field, text_input
from ..state.partitions import PartitionsState as S


def _add_body(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "PT-Internal")),
        form_field("Description", text_input(S, "description")),
        spacing="3", align="start", width="100%",
    )


partitions = build_crud_page(S, CrudPageConfig(
    title="Partitions",
    noun="partition",
    key="name",
    columns=[Column("Name", "name", code=True), Column("Description", "description")],
    add_body=_add_body,
    import_notes="Modify can only change the description.",
))
