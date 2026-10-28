"""State for CUCM > Call Routing > Advertised Patterns."""

from ..backend import cucm_axl
from .crud import CrudMixin, ResourceSpec
from .cucm import CucmState


def _build_add_row(form: dict[str, str]) -> dict[str, str]:
    row = dict(form)
    if row.get("hostedRoutePSTNRule") != "Specify":
        row["pstnFailStrip"] = "0"
        row["pstnFailPrepend"] = ""
    return row


SPEC = ResourceSpec(
    noun="pattern",
    key="pattern",
    fields=cucm_axl.PATTERN_FIELDS,
    export_prefix="advertised_patterns",
    template_csv=(
        "description,pattern,patternType,hostedRoutePSTNRule,pstnFailStrip,pstnFailPrepend\n"
        "Test DIDs,+155585944XX,+E.164 Number,Use pattern,0,\n"
        "Sales Line,+13125550100,+E.164 Number,Specify,2,+1\n"
    ),
    bulk_template_csv="pattern\n+155585944XX\n+13125550100\n",
    list_fn=cucm_axl.list_patterns,
    add_fn=cucm_axl.add_pattern,
    update_fn=cucm_axl.update_pattern,
    remove_fn=cucm_axl.remove_pattern,
    add_defaults={
        "pattern": "", "description": "", "patternType": "+E.164 Number",
        "hostedRoutePSTNRule": "Use pattern", "pstnFailStrip": "0", "pstnFailPrepend": "",
    },
    build_add_row=_build_add_row,
)


class AdvertisedPatternsState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return SPEC
