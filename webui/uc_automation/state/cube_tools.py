"""States for the CUBE tools: Mem Status and Config Compare. Both run over SSH against a list of routers."""

import csv
from dataclasses import dataclass
import io
import zipfile
from datetime import datetime

import reflex as rx

from ..backend import cube_config as cfg, cube_credentials, cube_mem as mem, cube_ssh
from ..backend.applog import OpLog
from .run_mixin import RunMixin
from .webex_routing import PasteMixin

MANUAL = "Enter Manually"
_PASTE = {"columns": ("router_ip", "hostname"), "markers": ("router_ip",)}


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


@dataclass
class Cred:
    name: str
    username: str
    password: str


class CubeRun(RunMixin, PasteMixin, mixin=True):
    """Router list input, credential set picker and the run loop shared by the CUBE tools."""

    paste_routers: str = ""
    cred_names: list[str] = []
    cred_name: str = ""
    # Manual entry: never saved. The password is a backend var so it is never sent to the browser.
    manual_username: str = ""
    _manual_password: str = ""
    rows: list[dict[str, str]] = []

    @rx.var
    def cred_options(self) -> list[str]:
        return self.cred_names + [MANUAL]

    @rx.var
    def is_manual(self) -> bool:
        return self.cred_name == MANUAL

    @rx.event
    def load_page(self):
        names = [c["name"] for c in cube_credentials.list_public()]
        self.cred_names = names
        if self.cred_name != MANUAL and self.cred_name not in names:
            self.cred_name = "default" if "default" in names else (names[0] if names else MANUAL)

    @rx.event
    def set_cred_name(self, value: str):
        self.cred_name = value

    @rx.event
    def set_manual_username(self, value: str):
        self.manual_username = value.strip()

    @rx.event
    def set_manual_password(self, value: str):
        self._manual_password = value

    def _credential(self) -> tuple[str, str, str]:
        """(label, username, password) of the chosen set or the manual entry; blank username/password when missing."""
        if self.cred_name == MANUAL:
            return "manual entry", self.manual_username, self._manual_password
        cred = cube_credentials.load(self.cred_name) if self.cred_name else None
        return (cred.name, cred.username, cred.password) if cred else (self.cred_name, "", "")

    async def _prepare(self, files):
        """(routers, credential set) from the uploaded list, or (None, error message)."""
        label, username, password = self._credential()
        if self.cred_name == MANUAL:
            if not username or not password:
                return None, "Enter a username and password."
        elif not username:
            return None, "Choose a saved credential set first (Credentials > CUBE)."
        elif not password:
            return None, f"The credential set {label} has no password stored."
        cred = Cred(label, username, password)
        if not files:
            return None, "Choose a CSV file first."
        try:
            routers = cube_ssh.parse_routers(await files[0].read())
        except UnicodeDecodeError:
            return None, "The file is not a text CSV."
        except cube_ssh.CubeError as e:
            return None, str(e)
        if not routers:
            return None, "No routers were found."
        return (routers, cred), ""


class MemStatusState(CubeRun, rx.State):
    threshold: str = "33"

    @rx.event
    def set_threshold(self, value: str):
        self.threshold = value.strip()

    @rx.event
    async def load_csv(self, files: list[rx.UploadFile]):
        async for ev in self._run(files):
            yield ev

    @rx.event
    async def load_text(self):
        async for ev in self._from_paste(self._run, "routers", **_PASTE):
            yield ev

    async def _run(self, files):
        try:
            low = int(self.threshold or mem.DEFAULT_THRESHOLD)
        except ValueError:
            yield rx.toast.error("The low memory threshold must be a whole number.")
            return
        prepared, err = await self._prepare(files)
        if prepared is None:
            yield rx.toast.error(err)
            return
        routers, cred = prepared
        log = OpLog("Router Memory Status", "cube-mem-status")
        try:
            log.info(f"Input: {files[0].filename}, {len(routers)} router(s), credential set {cred.name} "
                     f"as {cred.username}, low memory threshold {low}%")
            found: list[dict[str, str]] = []

            def one(r: cube_ssh.Router) -> str:
                row = {"hostname": r.hostname, "ip": r.ip, "status": "Failed", "free_pct": "", "memory": ""}
                found.append(row)
                output = cube_ssh.run_command(r, cred.username, cred.password, mem.COMMAND)
                pct = mem.extract_free_percentage(output)
                row.update(status="Low" if pct < low else "OK", free_pct=str(pct),
                           memory=mem.extract_memory_section(output))
                return f"{pct}% free" + (" (below threshold)" if pct < low else "")

            self.rows = []
            items = [(r.label, lambda r=r: one(r)) for r in routers]
            async for ev in self._run_items(items, "Checking", log):
                yield ev
            # a failed router keeps its row; put the error text in it
            errors = {x["key"]: x["detail"] for x in self.results if x["status"] != "OK"}
            for row in found:
                if row["status"] == "Failed":
                    row["memory"] = errors.get(f"{row['hostname']} ({row['ip']})", "")
            self.rows = found
            yield rx.clear_selected_files("mem_upload")
        finally:
            log.close()

    @rx.var
    def low_count(self) -> int:
        return sum(1 for r in self.rows if r["status"] == "Low")

    @rx.event
    def export_csv(self):
        if not self.rows:
            return rx.toast.error("Nothing to export. Run the check first.")
        return rx.download(data=mem.memory_csv(self.rows), filename=f"router-memory-{_stamp()}.csv")


class ConfigCompareState(CubeRun, rx.State):
    template_text: str = ""
    _reports: dict[str, str] = {}

    @rx.event
    def set_template_text(self, value: str):
        self.template_text = value

    @rx.event
    async def load_template_file(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a template file first.")
            return
        try:
            self.template_text = (await files[0].read()).decode("utf-8-sig")
        except UnicodeDecodeError:
            yield rx.toast.error("The file is not a text file.")
            return
        yield rx.clear_selected_files("template_upload")
        yield rx.toast.success("Template loaded. Review it, then run the comparison below.")

    @rx.event
    async def load_csv(self, files: list[rx.UploadFile]):
        async for ev in self._run(files):
            yield ev

    @rx.event
    async def load_text(self):
        async for ev in self._from_paste(self._run, "routers", **_PASTE):
            yield ev

    async def _run(self, files):
        template = cfg.parse_template(self.template_text)
        if not template:
            yield rx.toast.error("The template has no voice sections. Paste or upload one first.")
            return
        prepared, err = await self._prepare(files)
        if prepared is None:
            yield rx.toast.error(err)
            return
        routers, cred = prepared
        log = OpLog("Compare Router Config", "cube-config-compare")
        try:
            log.info(f"Input: {files[0].filename}, {len(routers)} router(s), credential set {cred.name} "
                     f"as {cred.username}, template with {len(template)} voice section(s)")
            found: list[dict[str, str]] = []
            reports: dict[str, str] = {}

            def one(r: cube_ssh.Router) -> str:
                row = {"hostname": r.hostname, "ip": r.ip, "status": "Failed", "missing": "", "extra": "",
                       "different": "", "detail": ""}
                found.append(row)
                output = cube_ssh.run_command(r, cred.username, cred.password, cfg.COMMAND)
                result = cfg.compare_config(template, output)
                reports[r.hostname] = cfg.build_html_report(r.hostname, template, result)
                bad = cfg.has_variances(result)
                row.update(status="Variances" if bad else "Compliant", missing=str(len(result["missing_sections"])),
                           extra=str(len(result["extra_sections"])), different=str(len(result["section_diffs"])))
                return "Variances found" if bad else "Compliant"

            self.rows = []
            items = [(r.label, lambda r=r: one(r)) for r in routers]
            async for ev in self._run_items(items, "Comparing", log):
                yield ev
            errors = {x["key"]: x["detail"] for x in self.results if x["status"] != "OK"}
            for row in found:
                if row["status"] == "Failed":
                    row["detail"] = errors.get(f"{row['hostname']} ({row['ip']})", "")
            self.rows = found
            self._reports = reports
            yield rx.clear_selected_files("compare_upload")
        finally:
            log.close()

    @rx.var
    def report_count(self) -> int:
        return sum(1 for r in self.rows if r["status"] in ("Compliant", "Variances"))

    @rx.event
    def export_csv(self):
        if not self.rows:
            return rx.toast.error("Nothing to export. Run the comparison first.")
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["hostname", "router_ip", "status", "missing_sections", "extra_sections", "different_sections",
                    "detail"])
        for r in self.rows:
            w.writerow([r["hostname"], r["ip"], r["status"], r["missing"], r["extra"], r["different"], r["detail"]])
        return rx.download(data=out.getvalue().encode("utf-8"), filename=f"router-config-compare-{_stamp()}.csv")

    @rx.event
    def download_reports(self):
        if not self._reports:
            return rx.toast.error("No reports yet. Run the comparison first.")
        stamp = _stamp()
        if len(self._reports) == 1:
            host, html = next(iter(self._reports.items()))
            return rx.download(data=html.encode("utf-8"), filename=f"{stamp}-{host}_comparison.html")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for host, html in self._reports.items():
                z.writestr(f"{stamp}-{host}_comparison.html", html)
        return rx.download(data=buf.getvalue(), filename=f"router-config-reports-{stamp}.zip")
