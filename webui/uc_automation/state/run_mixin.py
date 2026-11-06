"""Run a list of items one by one with progress and a per-row result table (tool pages, CUCM and Webex)."""

import asyncio
from dataclasses import dataclass

from typing import ClassVar

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


@dataclass
class _Job:
    items: list
    verb: str
    log: OpLog
    workers: int
    then: str


# Jobs waiting for their background run, keyed by (client token, state). Kept out of state: they hold callables
# and an open log.
_JOBS: dict[tuple[str, str], _Job] = {}


class RunMixin(rx.State, mixin=True):
    """busy / progress / per-row results shared by the tools that run a list of items.

    A handler builds its items and yields `self._start_run(...)`. The items then run in a background task, so the
    page stays usable and Cancel works while they run."""

    output_fields: ClassVar[tuple[str, ...]] = ("results", "progress")

    busy: bool = False
    progress: str = ""
    results: list[dict[str, str]] = []
    cancelling: bool = False
    _cancel: bool = False

    @rx.var
    def result_ok_count(self) -> int:
        return sum(1 for r in self.results if r["status"] == "OK")

    @rx.var
    def result_fail_count(self) -> int:
        return sum(1 for r in self.results if r["status"] != "OK")

    def _default_workers(self) -> int:
        return 1

    def _job_key(self) -> tuple[str, str]:
        return self.router.session.client_token, self.get_full_name()

    def _start_run(self, items: list[tuple], verb: str, log: OpLog, workers: int = 0, then: str = ""):
        """Queue `items` for a background run and return the event to yield. Each item is (label, fn) or
        (label, fn, extra row fields), fn a zero-argument callable returning a detail string or None. It runs in a
        thread, so it must not touch the state.

        The run owns `log` from here (the caller's log.close() waits for it). `then` names a method
        `then(self, log)` called under the state lock after the run, before the log closes; it may return events."""
        stale = _JOBS.get(self._job_key())
        if stale is not None and stale.log is not log:  # replaced before it started: close its log
            stale.log.release()
        log.hold()
        _JOBS[self._job_key()] = _Job(list(items), verb, log, workers or self._default_workers(), then)
        self.busy = True
        self.results = []
        self.progress = f"{verb} 0 of {len(items)}"
        self._cancel = self.cancelling = False
        return type(self).run_job

    @rx.event
    def cancel_run(self):
        """Stop starting new items. Items already running finish."""
        if self.busy:
            self._cancel = self.cancelling = True

    async def _run_one(self, item: tuple, log: OpLog) -> dict[str, str]:
        """Run one item in a thread and return its result row."""
        label, fn, *extra = item
        row = {"key": label, **(extra[0] if extra else {})}
        try:
            detail = await asyncio.to_thread(fn)
            log.info(f"{label}: OK - {detail or 'Done'}")
            return {**row, "status": "OK", "detail": detail or "Done"}
        except UserError as e:
            log.error(f"{label}: Failed - {e}")
            return {**row, "status": "Failed", "detail": str(e)}
        except Exception as e:
            log.error(f"{label}: Failed unexpectedly - {e!r}")
            return {**row, "status": "Failed", "detail": f"Unexpected error: {e}"}

    @rx.event(background=True)
    async def run_job(self):
        """Run the queued items, `workers` at a time. The result table stays in item order (rows appear once every
        earlier item has finished); the log lists items in the order they finish."""
        async with self:
            key = self._job_key()
            job = _JOBS.pop(key, None)
        if job is None:
            return
        log, total = job.log, len(job.items)
        outcomes: list[dict[str, str] | None] = [None] * total
        stop = False
        events: list = []
        follow = None
        log.info(f"{job.verb}: {total} item(s)" + (f", {job.workers} at a time" if job.workers > 1 else ""))
        sem = asyncio.Semaphore(job.workers)

        async def one(i: int, item: tuple) -> None:
            nonlocal stop
            async with sem:
                if not stop:  # check Cancel just before each item starts
                    async with self:
                        stop = self._cancel
                if not stop:
                    outcomes[i] = await self._run_one(item, log)

        pending = {asyncio.create_task(one(i, item)) for i, item in enumerate(job.items)}
        try:
            while pending:
                _, pending = await asyncio.wait(pending, timeout=0.5, return_when=asyncio.FIRST_COMPLETED)
                finished = sum(1 for o in outcomes if o is not None)
                ready = 0
                while ready < total and outcomes[ready] is not None:
                    ready += 1
                async with self:
                    stop = stop or self._cancel
                    self.progress = f"{job.verb} {finished} of {total}" + (" (cancelling)" if stop else "")
                    self.results = outcomes[:ready]
            done = [o for o in outcomes if o is not None]
            ok = sum(1 for o in done if o["status"] == "OK")
            skipped = total - len(done)
            if skipped:
                log.warning(f"Cancelled by the user after {len(done)} of {total}")
            log.info(f"{job.verb} finished: {ok} OK, {len(done) - ok} failed"
                     + (f", {skipped} not run (cancelled)" if skipped else ""))
            async with self:
                self.results = done
                if job.then:
                    # Call it on the real state, not the background proxy, so type(self) is the page's class.
                    out = getattr(getattr(self, "__wrapped__", self), job.then)(log)
                    events += out if isinstance(out, list) else [out] if out is not None else []
            if skipped:
                events.append(rx.toast.warning(f"Cancelled. {skipped} item(s) were not run."))
        except Exception as e:
            log.error(f"{job.verb} stopped unexpectedly - {e!r}")
            events = [rx.toast.error(f"Unexpected error: {e}")]  # a follow-up queued by `then` is dropped
            orphan = _JOBS.pop(key, None)
            if orphan is not None and orphan.log is not log:
                orphan.log.release()
        finally:
            for t in pending:  # the page was closed or the task cancelled
                t.cancel()
            try:
                async with self:
                    follow = _JOBS.get(key)  # a follow-up run queued by `then`
                    if follow is None:
                        self.busy = False
                        self.progress = ""
                    self._cancel = self.cancelling = False
            finally:
                if follow is None or follow.log is not log:
                    log.release()
        for ev in events:
            yield ev
