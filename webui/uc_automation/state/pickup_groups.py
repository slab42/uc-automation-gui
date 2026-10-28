"""State for CUCM > Call Routing > Call Pickup Groups."""

from ..backend import cucm_routing as r
from .crud import CrudMixin, DepCheckMixin, ResourceSpec
from .cucm import CucmState

SPEC = ResourceSpec(
    noun="call pickup group",
    key="name",
    fields=r.PICKUP_GROUP_FIELDS,
    export_prefix="call_pickup_groups",
    template_csv=(
        "name,pattern,description,routePartitionName,pickupNotification\n"
        "CPG-Sales,5001,Sales pickup,PT-Internal,No Alert\n"
        "CPG-Support,5002,Support pickup,PT-Internal,Audio Alert\n"
    ),
    bulk_template_csv="name\nCPG-Sales\nCPG-Support\n",
    list_fn=r.list_pickup_groups,
    add_fn=r.add_pickup_group,
    update_fn=r.update_pickup_group,
    remove_fn=r.remove_pickup_group,
    add_defaults={"name": "", "pattern": "", "description": "", "routePartitionName": "",
                  "pickupNotification": "No Alert"},
)


class PickupGroupsState(CucmState, CrudMixin, DepCheckMixin):
    def _spec(self) -> ResourceSpec:
        return SPEC

    def _dep_fn(self):
        return r.find_pickup_group_usage
