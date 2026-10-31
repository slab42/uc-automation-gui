"""State for CUCM > Tools > Home Cluster Locator: find where a user is marked home across the organization's CUCM
connections, then move the home marker to one cluster with AXL."""

import asyncio
import csv
import io
from datetime import datetime

import reflex as rx

from ..backend import cucm_home as home
from ..backend.applog import OpLog
from ..backend.cucm_connections import CucmConnection
from .cucm import CucmState
from .run_mixin import RunMixin

WORKERS = 10


class HomeClusterState(CucmState, RunMixin):
    username: str = ""
    searched_user: str = ""
    rows: list[dict[str, str]] = []  # name, server, status (Found / Not Found / Unreachable), home, detail, marked
    selected: list[str] = []  # connection names ticked as the user's home
    editing: bool = False
    axl_username: str = ""
    _axl_password: str = ""  # backend var: never sent to the browser, never logged
    axl_key: int = 0
    confirm_open: bool = False

    @rx.var
    def cluster_count(self) -> int:
        return len(self.org_connections)

    @rx.var
    def homes(self) -> list[str]:
        """Distinct home clusters reported by the clusters that know the user."""
        return sorted({r["home"] for r in self.rows if r["status"] == "Found"})

    @rx.var
    def homes_text(self) -> str:
        return ", ".join(self.homes) or "Not found on any cluster"

    @rx.var
    def homes_color(self) -> str:
        return {0: "gray", 1: "green"}.get(len(self.homes), "orange")

    @rx.var
    def unreachable_count(self) -> int:
        return sum(1 for r in self.rows if r["status"] == "Unreachable")

    @rx.var
    def can_apply(self) -> bool:
        return self.editing and len(self.selected) == 1 and bool(self.axl_username) and not self.busy

    @rx.var
    def confirm_text(self) -> str:
        others = len(self.rows) - len(self.selected)
        return (f"This makes {self.searched_user} home on {', '.join(self.selected)} and removes the home cluster from "
                f"the other {others} cluster(s) in this organization. It changes users on those clusters.")

    @rx.event
    def set_username(self, value: str):
        self.username = value.strip()

    @rx.event
    def set_axl_username(self, value: str):
        self.axl_username = value.strip()

    @rx.event
    def set_axl_password(self, value: str):
        self._axl_password = value

    @rx.event
    def set_confirm_open(self, value: bool):
        self.confirm_open = value

    def _reset_edit(self):
        self.editing = False
        self._axl_password = ""
        self.axl_key += 1
        self.confirm_open = False

    @rx.event
    def pick_org(self, org: str):
        """Organization change on this page: no instance is chosen, so the active connection is left alone."""
        self.active_org = org
        self.rows = []
        self.results = []
        self.selected = []
        self.searched_user = ""
        self._reset_edit()

    @rx.event
    async def locate(self):
        user = self.username
        if not user:
            yield rx.toast.error("Enter a user ID.")
            return
        if not self.org_connections:
            yield rx.toast.error("This organization has no CUCM connections. Add them on the Credentials page.")
            return
        async for ev in self._search(user):
            yield ev

    async def _search(self, user: str):
        clusters = list(self.org_connections)
        log = OpLog("Home Cluster Locator", "cucm-home-cluster")
        self.busy = True
        self.progress = "Searching clusters"
        self.rows = []
        self.results = []
        self.selected = []
        self._reset_edit()
        yield
        try:
            log.info(f"User {user}, organization {self.active_org or 'none'}, {len(clusters)} cluster(s)")
            sem = asyncio.Semaphore(WORKERS)

            async def one(c: dict[str, str]) -> dict[str, str]:
                row = {"name": c["name"], "server": c["server"], "status": "Found", "home": "", "detail": "",
                       "marked": ""}
                async with sem:
                    try:
                        row["home"] = await asyncio.to_thread(home.home_cluster, c["server"], user)
                        row["marked"] = "yes"
                    except home.HomeError as e:
                        row.update(status="Unreachable" if str(e).startswith("Unreachable") else "Not Found",
                                   detail=str(e))
                log.info(f"{c['name']} ({c['server']}): {row['status']} {row['home'] or row['detail']}".rstrip())
                return row

            self.rows = list(await asyncio.gather(*(one(c) for c in clusters)))
            self.selected = [r["name"] for r in self.rows if r["marked"]]
            self.searched_user = user
            log.info(f"Home cluster(s) reported: {', '.join(self.homes) or 'none'}; marked on: "
                     f"{', '.join(self.selected) or 'none matched'}; {self.unreachable_count} unreachable")
        finally:
            self.busy = False
            self.progress = ""
            log.close()

    # --- editing ---

    @rx.event
    def toggle_cluster(self, name: str, checked: bool):
        if self.editing:  # one home only: ticking a box replaces the choice
            self.selected = [name] if checked else []
        elif checked and name not in self.selected:
            self.selected = self.selected + [name]
        elif not checked:
            self.selected = [n for n in self.selected if n != name]

    @rx.event
    def start_edit(self):
        self.editing = True
        self.results = []
        if len(self.selected) > 1:
            self.selected = []
            return rx.toast.info("Only one cluster can be home. Tick the one to keep.")

    @rx.event
    def cancel_edit(self):
        self.selected = [r["name"] for r in self.rows if r["marked"]]
        self._reset_edit()

    @rx.event
    def ask_apply(self):
        if not self.can_apply:
            return rx.toast.error("Tick one cluster and enter the AXL username and password.")
        if not self._axl_password:
            return rx.toast.error("Enter the AXL password.")
        self.confirm_open = True

    @rx.event
    async def apply(self):
        self.confirm_open = False
        user, target = self.searched_user, (self.selected[0] if len(self.selected) == 1 else "")
        if not target or not self.axl_username or not self._axl_password:
            yield rx.toast.error("Tick one cluster and enter the AXL username and password.")
            return
        saved = {c["name"]: c for c in self.org_connections}
        username, password = self.axl_username, self._axl_password

        def conn(name: str) -> CucmConnection:
            c = saved[name]
            return CucmConnection(name, c["server"], username, password, c.get("version", ""),
                                  c.get("schema_version", ""))

        def item(name: str, local: bool):
            return (name, lambda: home.set_home(conn(name), user, local))

        names = [r["name"] for r in self.rows if r["name"] in saved]
        others = [n for n in names if n != target]
        log = OpLog("Move Home Cluster", "cucm-move-home-cluster")
        try:
            log.info(f"User {user}: home on {target}, removed from {len(others)} other cluster(s); AXL account {username}")
            # Enable the target first. If that fails nothing else is touched, so the user never ends up with no home.
            async for ev in self._run_items([item(target, True)], "Enabling home cluster", log):
                yield ev
            head = list(self.results)
            if self.result_fail_count:
                log.error("Target cluster failed, other clusters were not changed")
                yield rx.toast.error("The chosen cluster could not be updated. Nothing else was changed.")
                return
            if others:
                async for ev in self._run_items([item(n, False) for n in others], "Removing home cluster", log):
                    yield ev
                self.results = head + self.results
            else:
                self.results = head
            failed = self.result_fail_count
            self._axl_password = ""
            self.axl_key += 1
        finally:
            self.busy = False
            self.progress = ""
            log.close()
        results = list(self.results)
        async for ev in self._search(user):  # show the new state
            yield ev
        self.results = results
        yield rx.toast.error(f"{failed} cluster(s) failed. See the results.") if failed else rx.toast.success(
            f"{user} is now home on {target}.")

    @rx.event
    def export_csv(self):
        if not self.rows:
            return rx.toast.error("Nothing to export. Search for a user first.")
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["user", "connection", "server", "result", "home_cluster", "detail"])
        for r in self.rows:
            w.writerow([self.searched_user, r["name"], r["server"], r["status"], r["home"], r["detail"]])
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return rx.download(data=out.getvalue().encode("utf-8"), filename=f"home-cluster-{self.searched_user}-{stamp}.csv")
