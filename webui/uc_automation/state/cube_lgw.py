"""State for the Webex Local Gateway Config Generator (CUBE > Configuration). Pure text generation, no router access."""

from datetime import datetime

import reflex as rx

from ..backend import cube_lgw as lgw
from ..backend.applog import OpLog


class LgwState(rx.State):
    # Text fields by key (see backend REQUIRED and cm<n>host / cm<n>ip). Passwords are backend vars, never sent to the browser.
    form: dict[str, str] = {
        **{k: "" for k, _ in lgw.REQUIRED},
        **{f"cm{n}{s}": "" for n in range(1, lgw.CUCM_SLOTS + 1) for s in ("host", "ip")},
        **lgw.DEFAULTS,
    }
    _password: str = ""
    _stun_password: str = ""
    password_key: int = 0
    config_view: str = ""  # shows the real passwords (deliberate exception to the no-passwords-in-the-browser rule)

    @rx.event
    def set_field(self, key: str, value: str):
        self.form[key] = value

    @rx.event
    def set_password(self, value: str):
        self._password = value

    @rx.event
    def set_stun_password(self, value: str):
        self._stun_password = value

    @rx.event
    def generate(self):
        log = OpLog("Webex Local Gateway Config", "cube-lgw-config")
        try:
            try:
                params = lgw.build_params(self.form, self._password, self._stun_password)
            except lgw.LgwError as e:
                log.info(f"Not generated: {e}")
                return rx.toast.error(str(e))
            self.config_view = lgw.generate_config(params)
            log.info(f"Generated config for tenant {params.tenant_id}, CUCM dial peer {params.cucm_dialpeer_id}, "
                     f"{len(params.cucm_hosts)} CUCM host(s), {len(self.config_view.splitlines())} line(s)")
            return rx.toast.success("Config generated.")
        finally:
            log.close()

    @rx.event
    def clear(self):
        for key in self.form:
            self.form[key] = lgw.DEFAULTS.get(key, "")
        self._password = ""
        self._stun_password = ""
        self.password_key += 1
        self.config_view = ""

    @rx.event
    def export_txt(self):
        if not self.config_view:
            return rx.toast.error("Nothing to export. Generate the config first.")
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return rx.download(data=self.config_view.encode("utf-8"), filename=f"webex-lgw-config-{stamp}.txt")
