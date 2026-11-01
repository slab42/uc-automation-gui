"""States for CUCM > Directory Numbers: move partition, alternate numbers, orphans."""

import asyncio

import reflex as rx

from ..backend import cucm_dn as d
from ..backend.cucm_axl import AxlError
from ..backend.cucm_routing import list_partitions
from .crud import CrudMixin, ResourceSpec
from .cucm import CucmState

_KEY = dict(key="id", key_parts=("pattern", "routePartitionName"))

MOVE = ResourceSpec(
    noun="directory number",
    fields=d.MOVE_FIELDS,
    export_prefix="dn_move_partition",
    template_csv=("pattern,routePartitionName,newRoutePartitionName\n"
                  "3120,Phone-Line1-PT,Phone-Line2-PT\n"),
    bulk_template_csv="pattern,routePartitionName\n3120,Phone-Line1-PT\n",
    list_fn=d.list_dns, add_fn=d.not_supported, update_fn=d.move_dn_row, remove_fn=d.not_supported,
    **_KEY,
)

ALT = ResourceSpec(
    noun="directory number",
    fields=d.ALT_FIELDS,
    export_prefix="dn_alternate_numbers",
    template_csv="pattern,routePartitionName\n3120,Phone-Line1-PT\n",
    bulk_template_csv="pattern,routePartitionName\n3120,Phone-Line1-PT\n",
    list_fn=d.list_dns_with_alt_numbers, add_fn=d.not_supported, update_fn=d.remove_alt_numbers_row,
    remove_fn=d.not_supported,
    **_KEY,
)

ORPHANS = ResourceSpec(
    noun="orphan directory number",
    fields=d.ORPHAN_FIELDS,
    export_prefix="orphan_dns",
    template_csv="pattern,routePartitionName\n3120,Phone-Line1-PT\n",
    bulk_template_csv="pattern,routePartitionName\n3120,Phone-Line1-PT\n",
    list_fn=d.list_orphan_dns, add_fn=d.not_supported, update_fn=d.not_supported, remove_fn=d.remove_dn,
    **_KEY,
)


class MoveDnState(CucmState, CrudMixin):
    move_target: str = ""
    partition_options: list[str] = []
    loading_partitions: bool = False

    def _spec(self) -> ResourceSpec:
        return MOVE

    @rx.event
    async def open_move(self):
        """Open the Move dialog and load this CUCM's partitions for the drop down."""
        conn = self._conn()
        if conn is None or self.busy:
            return
        self.results = []
        self.progress = ""
        self.move_target = ""
        self.dialog = "move"
        self.loading_partitions = True
        yield
        log = self._open_log("List partitions", conn)
        try:
            rows = await asyncio.to_thread(list_partitions, conn)
            self.partition_options = [r["name"] for r in rows]
            log.info(f"Listed {len(rows)} partition(s)")
        except AxlError as e:
            self.partition_options = []
            log.error(f"List failed: {e}")
            yield rx.toast.error(f"Could not load partitions: {e}")
        except Exception as e:
            self.partition_options = []
            log.error(f"List failed unexpectedly: {e!r}")
            yield rx.toast.error(f"Could not load partitions: {e}")
        finally:
            log.close()
            self.loading_partitions = False

    @rx.event
    def set_move_target(self, value: str):
        self.move_target = value.strip()

    @rx.event
    async def move_selected(self):
        # The dialog stays open to show the results, so only the busy flag guards a second click.
        if self.dialog != "move" or self.busy:
            return
        conn = self._conn()
        targets = list(self.selected)
        new = self.move_target
        if conn is None or not targets:
            return
        if not new:
            yield rx.toast.error("Enter the new partition.")
            return
        log = self._open_log("Move selected", conn)
        try:
            log.info(f"Moving {len(targets)} directory number(s) to partition {new}")
            yield self._start_each(conn, targets, lambda c, t, new=new: d.move_dn(c, t, new),
                                   "Moving", f"Moved to {new}", log, then="_after_run")
        finally:
            log.close()

    def _after_run(self, log):
        self.selected = [r["id"] for r in self.results if r["status"] != "OK"]
        return [type(self).fetch]


class AlternateNumbersState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return ALT

    @rx.event
    async def remove_selected(self):
        # The dialog stays open to show the results, so only the busy flag guards a second click.
        if self.dialog != "altconfirm" or self.busy:
            return
        conn = self._conn()
        targets = list(self.selected)
        if conn is None or not targets:
            return
        log = self._open_log("Remove alternate numbers", conn)
        try:
            yield self._start_each(conn, targets, d.remove_alt_numbers, "Removing", "Removed", log,
                                   then="_after_run")
        finally:
            log.close()

    def _after_run(self, log):
        self.selected = [r["id"] for r in self.results if r["status"] != "OK"]
        return [type(self).fetch]


class OrphansState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return ORPHANS
