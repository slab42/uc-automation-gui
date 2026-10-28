"""State for CUCM > Call Routing > Route Patterns."""

import reflex as rx

from ..backend import cucm_routing as r
from .crud import CrudMixin, ResourceSpec
from .cucm import CucmState

SPEC = ResourceSpec(
    noun="route pattern",
    key="id",
    key_parts=("pattern", "routePartitionName"),
    fields=r.ROUTE_PATTERN_FIELDS,
    export_prefix="route_patterns",
    template_csv=(
        "pattern,routePartitionName,description,routeListName,gatewayName\n"
        "\\+1.[2-9]XXXXXXXXX,PT-PSTN,US national,RL-PSTN,\n"
        "9.911,PT-PSTN,Emergency,,sfo-gw-01\n"
    ),
    bulk_template_csv="pattern,routePartitionName\n9.911,PT-PSTN\n",
    list_fn=r.list_route_patterns,
    add_fn=r.add_route_pattern,
    update_fn=r.update_route_pattern,
    remove_fn=r.remove_route_pattern,
    add_defaults={"pattern": "", "routePartitionName": "", "description": "", "routeListName": "",
                  "gatewayName": ""},
)


class RoutePatternsState(CucmState, CrudMixin):
    dup_pairs: list[dict[str, str]] = []

    def _spec(self) -> ResourceSpec:
        return SPEC

    @rx.event
    def find_duplicates(self):
        """Find '.+' / '+' pattern pairs in the loaded list (RP-duplicatish_remediate.py)."""
        log = self._open_log("Find duplicates")
        try:
            self.dup_pairs = r.find_duplicatish_route_patterns(self.items)
            log.info(f"Checked {len(self.items)} route pattern(s): {len(self.dup_pairs)} duplicate-ish pair(s)")
            for d in self.dup_pairs:
                log.info(f"{d['dot_plus']} ({d['partition']}) duplicates {d['plus']} ({d['plus_partition']})")
        finally:
            log.close()
        self.results = []
        self.dialog = "dups"

    @rx.event
    def select_dot_plus(self):
        """Select the '.+' patterns so Delete selected removes them and keeps the '+' ones."""
        self.selected = [d["dot_plus_id"] for d in self.dup_pairs]
        self.dialog = ""
