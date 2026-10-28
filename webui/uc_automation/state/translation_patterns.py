"""State for CUCM > Call Routing > Translation Patterns."""

from ..backend import cucm_routing as r
from .crud import CrudMixin, ResourceSpec
from .cucm import CucmState

SPEC = ResourceSpec(
    noun="translation pattern",
    key="id",
    key_parts=("pattern", "routePartitionName"),
    fields=r.TRANS_PATTERN_FIELDS,
    export_prefix="translation_patterns",
    template_csv=(
        "pattern,routePartitionName,description,callingSearchSpaceName,calledPartyTransformationMask,"
        "callingPartyTransformationMask\n"
        "9XXX,PT-Translation,Four digit dialing,CSS-Internal,5551234XXX,\n"
    ),
    bulk_template_csv="pattern,routePartitionName\n9XXX,PT-Translation\n",
    list_fn=r.list_translation_patterns,
    add_fn=r.add_translation_pattern,
    update_fn=r.update_translation_pattern,
    remove_fn=r.remove_translation_pattern,
    add_defaults={"pattern": "", "routePartitionName": "", "description": "", "callingSearchSpaceName": "",
                  "calledPartyTransformationMask": "", "callingPartyTransformationMask": ""},
)


class TranslationPatternsState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return SPEC
