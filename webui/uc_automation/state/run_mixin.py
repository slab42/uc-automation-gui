"""Run a list of items one by one with progress and a per-row result table (tool pages, CUCM and Webex)."""

import asyncio

import reflex as rx

from ..backend.applog import OpLog
from ..backend.errors import UserError


class PanesMixin(rx.State, mixin=True):
    """Open state of the one-item and multiple-item panes of a tool page (see collapsible_card)."""

    single_open: bool = True
    multi_open: bool = True

    @rx.event
    def toggle_single(self):
        self.single_open = not self.single_open

    @rx.event
    def toggle_multi(self):
        self.multi_open = not self.multi_open

    def _focus_pane(self, single: bool):
        """Keep the pane being run open and collapse the other."""
        self.single_open, self.multi_open = single, not single


class RunMixin(rx.State, mixin=True):
    """busy / progress / per-row results shared by the tools that run a list of items."""

    busy: bool = False
    progress: str = ""
    results: list[dict[str, str]] = []

    @rx.var
    def result_ok_count(self) -> int:
        return sum(1 for r in self.results if r["status"] == "OK")

    @rx.var
    def result_fail_count(self) -> int:
        return sum(1 for r in self.results if r["status"] != "OK")

    async def _run_one(self, label: str, fn, log: OpLog) -> dict[str, str]:
        """Run one item in a thread and return its result row."""
        try:
            detail = await asyncio.to_thread(fn)
            log.info(f"{label}: OK - {detail or 'Done'}")
            return {"key": label, "status": "OK", "detail": detail or "Done"}
        except UserError as e:
            log.error(f"{label}: Failed - {e}")
            return {"key": label, "status": "Failed", "detail": str(e)}
        except Exception as e:
            log.error(f"{label}: Failed unexpectedly - {e!r}")
            return {"key": label, "status": "Failed", "detail": f"Unexpected error: {e}"}

    async def _run_items(self, items: list[tuple[str, object]], verb: str, log: OpLog, workers: int = 1):
        """items: (label, zero-argument callable returning a detail string or None). Runs each in a thread.

        workers > 1 runs that many items at once. The result table stays in item order (rows appear as soon as
        every earlier item has finished); the log lists items in the order they finish."""
        self.busy = True
        self.results = []
        total = len(items)
        log.info(f"{verb}: {total} item(s)" + (f", {workers} at a time" if workers > 1 else ""))
        if workers <= 1:
            for i, (label, fn) in enumerate(items, 1):
                self.progress = f"{verb} {i} of {total}"
                yield
                self.results.append(await self._run_one(label, fn, log))
        else:
            sem = asyncio.Semaphore(workers)
            outcomes: list[dict[str, str] | None] = [None] * total

            async def one(i: int, label: str, fn) -> None:
                async with sem:
                    outcomes[i] = await self._run_one(label, fn, log)

            pending = {asyncio.create_task(one(i, label, fn)) for i, (label, fn) in enumerate(items)}
            try:
                while pending:
                    done_set, pending = await asyncio.wait(pending, timeout=0.5, return_when=asyncio.FIRST_COMPLETED)
                    finished = sum(1 for o in outcomes if o is not None)
                    ready = 0
                    while ready < total and outcomes[ready] is not None:
                        ready += 1
                    self.progress = f"{verb} {finished} of {total}"
                    self.results = [o for o in outcomes[:ready]]
                    yield
            finally:
                for t in pending:  # the page was closed or the handler cancelled
                    t.cancel()
            self.results = [o for o in outcomes if o is not None]
        log.info(f"{verb} finished: {self.result_ok_count} OK, {self.result_fail_count} failed")
        self.progress = ""
        self.busy = False
