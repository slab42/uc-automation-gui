"""State for CUCM > Call Routing > Hunt Groups (hunt pilots and the hunt lists / line groups behind them)."""

from ..backend import cucm_hunt as h
from .crud import CrudMixin, DepCheckMixin, ResourceSpec
from .cucm import CucmState

SPEC = ResourceSpec(
    noun="hunt pilot",
    key="id",
    key_parts=("pattern", "routePartitionName"),
    fields=h.HUNT_PILOT_FIELDS,
    export_prefix="hunt_pilots",
    template_csv=(
        "pattern,routePartitionName,description,huntListName\n"
        "5000,PT-Internal,Sales hunt group,HL-Sales\n"
        "5100,PT-Internal,Support hunt group,HL-Support\n"
    ),
    bulk_template_csv="pattern,routePartitionName\n5000,PT-Internal\n5100,PT-Internal\n",
    list_fn=h.list_hunt_pilots,
    add_fn=h.add_hunt_pilot,
    update_fn=h.update_hunt_pilot,
    remove_fn=h.remove_hunt_pilot,
    add_defaults={"pattern": "", "routePartitionName": "", "description": "", "huntListName": ""},
)


class HuntGroupsState(CucmState, CrudMixin, DepCheckMixin):
    def _spec(self) -> ResourceSpec:
        return SPEC

    def _dep_fn(self):
        return h.find_hunt_pilot_usage
