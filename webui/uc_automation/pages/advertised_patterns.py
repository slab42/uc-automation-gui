import reflex as rx

from ..backend.cucm_axl import PATTERN_TYPES, PSTN_RULES
from ..components.crud_page import Column, CrudPageConfig, build_crud_page, form_field, text_input
from ..state.advertised_patterns import AdvertisedPatternsState as S


def _add_body(S) -> rx.Component:
    return rx.vstack(
        form_field("Pattern", text_input(S, "pattern", "+155585944XX")),
        form_field("Description", text_input(S, "description")),
        rx.grid(
            form_field("Pattern type", rx.select(PATTERN_TYPES, value=S.new_form["patternType"],
                                                 on_change=lambda v: S.set_new("patternType", v), width="100%")),
            form_field("PSTN rule", rx.select(PSTN_RULES, value=S.new_form["hostedRoutePSTNRule"],
                                              on_change=lambda v: S.set_new("hostedRoutePSTNRule", v), width="100%")),
            columns="2", spacing="3", width="100%",
        ),
        rx.cond(
            S.new_form["hostedRoutePSTNRule"] == "Specify",
            rx.grid(
                form_field("PSTN failover strip digits", text_input(S, "pstnFailStrip", type="number")),
                form_field("PSTN failover prepend", text_input(S, "pstnFailPrepend")),
                columns="2", spacing="3", width="100%",
            ),
            rx.fragment(),
        ),
        spacing="3", align="start", width="100%",
    )


advertised_patterns = build_crud_page(S, CrudPageConfig(
    title="Advertised Patterns",
    noun="pattern",
    key="pattern",
    columns=[
        Column("Pattern", "pattern", code=True), Column("Description", "description"),
        Column("Type", "patternType"), Column("PSTN rule", "hostedRoutePSTNRule"),
        Column("Strip", "pstnFailStrip"), Column("Prepend", "pstnFailPrepend"),
    ],
    add_body=_add_body,
    import_notes=("patternType: +E.164 Number, Enterprise Number. "
                  "hostedRoutePSTNRule: No PSTN, Use pattern, Specify."),
))
