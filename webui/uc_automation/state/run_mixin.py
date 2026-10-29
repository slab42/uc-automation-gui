"""Run a list of items one by one with progress and a per-row result table (tool pages, CUCM and Webex)."""

import asyncio

import reflex as rx

from ..backend.applog import OpLog
from ..backend.errors import UserError


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

    async def _run_items(self, items: list[tuple[str, object]], verb: str, log: OpLog):
        """items: (label, zero-argument callable returning a detail string or None). Runs each in a thread."""
        self.busy = True
        self.results = []
        log.info(f"{verb}: {len(items)} item(s)")
        for i, (label, fn) in enumerate(items, 1):
            self.progress = f"{verb} {i} of {len(items)}"
            yield
            try:
                detail = await asyncio.to_thread(fn)
                self.results.append({"key": label, "status": "OK", "detail": detail or "Done"})
                log.info(f"{label}: OK - {detail or 'Done'}")
            except UserError as e:
                self.results.append({"key": label, "status": "Failed", "detail": str(e)})
                log.error(f"{label}: Failed - {e}")
            except Exception as e:
                self.results.append({"key": label, "status": "Failed", "detail": f"Unexpected error: {e}"})
                log.error(f"{label}: Failed unexpectedly - {e!r}")
        log.info(f"{verb} finished: {self.result_ok_count} OK, {self.result_fail_count} failed")
        self.progress = ""
        self.busy = False
