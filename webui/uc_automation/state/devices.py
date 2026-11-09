"""States for CUCM > Devices: phones, softkey templates, common device configs, button templates, MPP."""

import dataclasses
from typing import ClassVar

import reflex as rx

from ..backend import cucm_cleanup as cl
from ..backend import cucm_devices as d
from .crud import CrudMixin, DepCheckMixin, ResourceSpec
from .cucm import CucmState
from .webex_routing import PasteMixin

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

CTIRPS = ResourceSpec(
    noun="CTI route point",
    key="name",
    fields=d.CTIRP_FIELDS,
    export_prefix="cti_route_points",
    template_csv=(
        "name,description,devicePoolName,callingSearchSpaceName,locationName\n"
        "CTIRP_MainAA,Main auto attendant,DP-HQ,CSS-Internal,Hub_None\n"
    ),
    bulk_template_csv="name\nCTIRP_MainAA\n",
    list_fn=d.list_cti_route_points, add_fn=d.add_cti_route_point,
    update_fn=d.update_cti_route_point, remove_fn=d.remove_cti_route_point,
    add_defaults={"name": "", "description": "", "devicePoolName": "", "callingSearchSpaceName": "",
                  "locationName": "Hub_None"},
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


class CtiRoutePointsState(CucmState, CrudMixin):
    def _spec(self) -> ResourceSpec:
        return CTIRPS


class PhoneButtonTemplatesState(CucmState, CrudMixin, DepCheckMixin):
    def _spec(self) -> ResourceSpec:
        return BUTTON_TEMPLATES

    def _dep_fn(self):
        return d.find_button_template_usage


class MppPhonesState(CucmState, CrudMixin, PasteMixin):
    output_fields: ClassVar[tuple[str, ...]] = ("searched",)
    mpp_action: str = "migrate"
    searched: bool = False
    paste_phones: str = ""
    _mpp_targets: list[str] = []
    _term: str = ""

    def _spec(self) -> ResourceSpec:
        term = self._term
        return dataclasses.replace(MPP, list_fn=lambda conn: d.list_mpp_phones(conn, term))

    @rx.var
    def mpp_action_label(self) -> str:
        return d.MPP_ACTIONS[self.mpp_action]

    @rx.var
    def mpp_action_detail(self) -> str:
        if self.mpp_action == "prep":
            return ("Sets the 14.4(1) load for the model, sets the load server to "
                    f"{d.MPP_LOAD_SERVER}, disables peer firmware sharing, and resets each phone.")
        return "Sets the MPP 12.0(7) load for the model and resets each phone."

    @rx.var
    def phone_count(self) -> int:
        return len(cl.parse_devices(self.paste_phones))

    # --- nothing is listed until a search ---

    @rx.event
    async def on_page_load(self):
        self.load_connections()
        if not self.new_form:
            self._form_defaults()

    @rx.event
    async def switch_connection(self, name: str):
        self.active = name
        self._remember(name)
        self._term = ""
        await self._clear_outputs(whole_org=False)

    @rx.event
    async def switch_org(self, org: str):
        self.active_org = org
        self._reconcile()
        self._term = ""
        await self._clear_outputs(whole_org=True)

    @rx.event
    async def fetch(self):
        if not self.searched:
            return
        async for ev in self._fetch():
            yield ev

    @rx.event
    async def run_search(self):
        term = self.search.strip()
        if not term or self.loading:
            return
        self._term = term
        self.searched = True
        self.selected = []
        async for ev in self._fetch():
            yield ev

    # --- list input ---

    @rx.event
    def set_paste_phones(self, value: str):
        self.paste_phones = value

    @rx.event
    async def load_phone_csv(self, files: list[rx.UploadFile]):
        """A CSV file fills the Paste Text box, so both inputs go through the same handlers."""
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        self.paste_phones = (await files[0].read()).decode("utf-8-sig", errors="replace")
        yield rx.toast.success(f"Loaded {files[0].filename}. Check the list on the Paste Text tab.")

    @rx.event
    def ask_mpp(self, action: str):
        if self.busy:
            return
        self.mpp_action = action
        self.results = []
        self.dialog = "mppconfirm"

    async def _mpp_run(self, targets: list[str], then: str):
        conn = self._conn()
        if conn is None:
            return
        action = self.mpp_action
        log = self._open_log(f"MPP {action}", conn)
        try:
            yield self._start_each(conn, targets, lambda c, t, action=action: d.run_mpp_action(c, t, action),
                                   "Updating", "Done", log, then=then)
        finally:
            log.close()

    @rx.event
    async def run_selected(self):
        if self.dialog != "mppconfirm" or self.busy:
            return
        targets = list(self.selected)
        self._mpp_targets = targets
        async for ev in self._mpp_run(targets, "_after_run_selected"):
            yield ev

    def _after_run_selected(self, log):
        self.dialog = "mppresult"
        failed = {r["id"] for r in self.results if r["status"] != "OK"}
        self.selected = [s for s in self._mpp_targets if s in failed]
        self._mpp_targets = []
        return [type(self).fetch]

    def _after_list_run(self, log):
        return [type(self).fetch]

    @rx.event
    async def list_run(self, action: str):
        """Run the action on the phones in the Paste Text box (names with or without SEP, or MAC addresses)."""
        if self.busy:
            return
        ids = cl.parse_devices(self.paste_phones)
        if not ids:
            yield rx.toast.error("The list has no phones.")
            return
        self.mpp_action = action
        self.results = []
        async for ev in self._mpp_run(ids, "_after_list_run"):
            yield ev
