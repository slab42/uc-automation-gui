"""States for CUCM > Devices: phones, softkey templates, common device configs, button templates, MPP."""

import asyncio
import csv
import io

import reflex as rx

from ..backend import cucm_devices as d
from ..backend.cucm_axl import AxlError
from .crud import CrudMixin, DepCheckMixin, ResourceSpec
from .cucm import CucmState

PHONES = ResourceSpec(
    noun="phone",
    key="name",
    fields=d.PHONE_FIELDS,
    export_prefix="phones",
    template_csv=(
        "name,description,product,protocol,devicePoolName,callingSearchSpaceName,phoneTemplateName,"
        "securityProfileName,sipProfileName,commonPhoneConfigName,locationName\n"
        "SEP0123456789AB,Front desk,Cisco 8845,SIP,DP-HQ,CSS-Internal,Standard 8845 SIP,"
        "Cisco 8845 - Standard SIP Non-Secure Profile,Standard SIP Profile,Standard Common Phone Profile,Hub_None\n"
    ),
    bulk_template_csv="name\nSEP0123456789AB\nSEP0123456789AC\n",
    list_fn=d.list_phones, add_fn=d.add_phone, update_fn=d.update_phone, remove_fn=d.remove_phone,
    add_defaults={"name": "", "description": "", "product": "Cisco 8845", "protocol": "SIP",
                  "devicePoolName": "", "callingSearchSpaceName": "", "phoneTemplateName": "",
                  "securityProfileName": "", "sipProfileName": "",
                  "commonPhoneConfigName": "Standard Common Phone Profile", "locationName": "Hub_None"},
)

SOFTKEYS = ResourceSpec(
    noun="softkey template",
    key="name",
    fields=d.SOFTKEY_FIELDS,
    export_prefix="softkey_templates",
    template_csv=("name,description,baseSoftkeyTemplateName\n"
                  "SK-Reception,Reception softkeys,Standard User\n"),
    bulk_template_csv="name\nSK-Reception\n",
    list_fn=d.list_softkey_templates, add_fn=d.add_softkey_template,
    update_fn=d.update_softkey_template, remove_fn=d.remove_softkey_template,
    add_defaults={"name": "", "description": "", "baseSoftkeyTemplateName": "Standard User"},
)

CDCS = ResourceSpec(
    noun="common device config",
    key="name",
    fields=d.CDC_FIELDS,
    export_prefix="common_device_configs",
    template_csv="name,softkeyTemplateName,userLocale\nCDC-HQ,SK-Reception,English United States\n",
    bulk_template_csv="name\nCDC-HQ\n",
    list_fn=d.list_common_device_configs, add_fn=d.add_common_device_config,
    update_fn=d.update_common_device_config, remove_fn=d.remove_common_device_config,
    add_defaults={"name": "", "softkeyTemplateName": "", "userLocale": ""},
)

BUTTON_TEMPLATES = ResourceSpec(
    noun="phone button template",
    key="name",
    fields=d.BUTTON_TEMPLATE_FIELDS,
    export_prefix="phone_button_templates",
    template_csv="name,basePhoneTemplateName\nPBT-8845-Reception,Cisco 8845 SIP\n",
    bulk_template_csv="name\nPBT-8845-Reception\n",
    list_fn=d.list_phone_button_templates, add_fn=d.add_phone_button_template,
    update_fn=d.update_phone_button_template, remove_fn=d.remove_phone_button_template,
    add_defaults={"name": "", "basePhoneTemplateName": "Cisco 8845 SIP"},
)

MPP = ResourceSpec(
    noun="phone",
    key="name",
    fields=d.MPP_FIELDS,
    export_prefix="mpp_phones",
    template_csv="phone\nSEP0123456789AB\n0123.4567.89ab\n",
    bulk_template_csv="phone\n",
    list_fn=d.list_mpp_phones, add_fn=d.not_supported, update_fn=d.not_supported, remove_fn=d.not_supported,
)


class PhonesState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return PHONES


class SoftkeyTemplatesState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return SOFTKEYS


class CommonDeviceConfigsState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return CDCS


class PhoneButtonTemplatesState(CucmState, CrudMixin, DepCheckMixin):
    def _spec(self) -> ResourceSpec:
        return BUTTON_TEMPLATES

    def _dep_fn(self):
        return d.find_button_template_usage


_PHONE_CSV_COLUMNS = ("phone", "mac", "device", "name")


def _read_identifiers(data: bytes) -> list[str]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    fields = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
    col = next((fields[c] for c in _PHONE_CSV_COLUMNS if c in fields), None)
    if not col:
        raise ValueError("The CSV needs one of these columns: " + ", ".join(_PHONE_CSV_COLUMNS))
    return list(dict.fromkeys((r.get(col) or "").strip() for r in reader if (r.get(col) or "").strip()))


class MppPhonesState(CucmState, CrudMixin):
    mpp_action: str = "migrate"

    def _spec(self) -> ResourceSpec:
        return MPP

    @rx.var
    def mpp_action_label(self) -> str:
        return d.MPP_ACTIONS[self.mpp_action]

    @rx.var
    def mpp_action_detail(self) -> str:
        if self.mpp_action == "prep":
            return ("Sets the 14.4(1) load for the model, sets the load server to "
                    f"{d.MPP_LOAD_SERVER}, disables peer firmware sharing, and resets each phone.")
        return "Sets the MPP 12.0(7) load for the model and resets each phone."

    @rx.event
    def ask_mpp(self, action: str):
        self.mpp_action = action
        self.results = []
        self.dialog = "mppconfirm"

    async def _mpp_run(self, targets: list[str]):
        conn = self._conn()
        if conn is None:
            return
        action = self.mpp_action
        log = self._open_log(f"MPP {action}", conn)
        try:
            async for ev in self._run_each(conn, targets, lambda c, t: d.run_mpp_action(c, t, action),
                                           "Updating", "Done", log):
                yield ev
            async for ev in self._fetch(log):
                yield ev
        finally:
            log.close()

    @rx.event
    async def run_selected(self):
        targets = list(self.selected)
        async for ev in self._mpp_run(targets):
            yield ev
        self.dialog = "mppresult"
        failed = {r["key"] for r in self.results if r["status"] != "OK"}
        self.selected = [s for s in targets if s in failed]

    @rx.event
    async def csv_migrate(self, files: list[rx.UploadFile]):
        self.mpp_action = "migrate"
        async for ev in self._csv(files):
            yield ev

    @rx.event
    async def csv_prep(self, files: list[rx.UploadFile]):
        self.mpp_action = "prep"
        async for ev in self._csv(files):
            yield ev

    async def _csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        try:
            ids = _read_identifiers(await files[0].read())
        except ValueError as e:
            yield rx.toast.error(str(e))
            return
        if not ids:
            yield rx.toast.error("The CSV has no phones.")
            return
        async for ev in self._mpp_run(ids):
            yield ev
        yield rx.clear_selected_files("mpp_upload")

