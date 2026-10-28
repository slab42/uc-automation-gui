"""State for CUCM > Call Routing > Partitions."""

from ..backend import cucm_routing as r
from .crud import CrudMixin, ResourceSpec
from .cucm import CucmState

SPEC = ResourceSpec(
    noun="partition",
    key="name",
    fields=r.PARTITION_FIELDS,
    export_prefix="partitions",
    template_csv="name,description\nPT-Internal,Internal DNs\nPT-Local,Local PSTN\n",
    bulk_template_csv="name\nPT-Internal\nPT-Local\n",
    list_fn=r.list_partitions,
    add_fn=r.add_partition,
    update_fn=r.update_partition,
    remove_fn=r.remove_partition,
    add_defaults={"name": "", "description": ""},
)


class PartitionsState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return SPEC
