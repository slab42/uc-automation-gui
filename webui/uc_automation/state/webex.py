"""Webex credentials page (named logins, named orgs, which login serves which org) and the OAuth callback page."""

import asyncio
import re
from datetime import datetime

import reflex as rx

from ..backend import organizations as orgs, webex_auth
from ..backend.applog import OpLog
from ..backend.webex_auth import WebexAuthError
from .webex_routing import WebexSession

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")
_NAME_HINT = "Name must use letters, digits, '.', '_' or '-' (max 41 characters)."


def _when(epoch: str) -> str:
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


class WebexState(WebexSession):
    """Child of WebexSession, so the saved orgs/logins and the active org are shared with the menu bar."""

    cred_tab: str = "organizations"

    # Logins: the one the cards edit (an unsaved name creates it on first save)
    login_name: str = ""
    info: dict[str, str] = {}
    form_client_id: str = ""
    form_scopes: str = ""
    _client_secret: str = ""
    secret_key: int = 0
    mode: str = "token"
    _pasted_token: str = ""
    token_key: int = 0
    checking: bool = False
    logged_in: bool = False
    message: str = ""
    callback_message: str = "Completing Webex login..."

    login_open: bool = False
    login_rename: str = ""  # the name box of an existing login (applied with the Rename button)

    # Orgs
    org_open: bool = False
    org_orig: str = ""  # saved name of the org being edited ("" when adding); a different org_name renames it
    org_name: str = ""
    form_org_id: str = ""
    org_login: str = ""
    org_customer: str = ""  # the customer organization this Webex org belongs to

    @rx.var
    def login_is_new(self) -> bool:
        return self.login_name not in self.webex_login_names

    @rx.var
    def org_is_new(self) -> bool:
        return not self.org_orig

    @rx.var
    def has_client(self) -> bool:
        return self.info.get("has_secret") == "yes" and bool(self.info.get("client_id"))

    @rx.var
    def expires_text(self) -> str:
        return _when(self.info.get("expires_at", ""))

    @rx.var
    def refresh_expires_text(self) -> str:
        return _when(self.info.get("refresh_expires_at", ""))

    @rx.event
    def set_cred_tab(self, value: str):
        self.cred_tab = value

    @rx.event
    def set_client_secret(self, value: str):
        self._client_secret = value

    @rx.event
    def set_form_client_id(self, value: str):
        self.form_client_id = value.strip()

    @rx.event
    def set_form_org_id(self, value: str):
        self.form_org_id = value.strip()

    @rx.event
    def set_org_name(self, value: str):
        self.org_name = value.strip()

    @rx.event
    def set_org_customer(self, value: str):
        self.org_customer = value

    @rx.event
    def set_org_login_form(self, value: str):
        self.org_login = value

    @rx.event
    def set_mode(self, value: str | list[str]):
        self.mode = value if isinstance(value, str) else value[0]

    @rx.event
    def set_pasted_token(self, value: str):
        self._pasted_token = value

    @rx.event
    def set_form_scopes(self, value: str):
        self.form_scopes = value

    def _target(self) -> str:
        """The login name being edited, or '' (after the caller shows why) when it is not valid."""
        return self.login_name if _NAME_RE.match(self.login_name) else ""

    # --- logins ---

    @rx.event
    def set_login_name(self, value: str):
        self.login_name = value.strip()
        self.info = webex_auth.public_status(self.login_name)

    @rx.event
    def set_login_open(self, value: bool):
        self.login_open = value

    @rx.event
    def set_org_open(self, value: bool):
        self.org_open = value

    @rx.event
    def set_login_rename(self, value: str):
        self.login_rename = value.strip()

    @rx.event
    def rename_login(self):
        new = self.login_rename
        if not _NAME_RE.match(new):
            return rx.toast.error(_NAME_HINT)
        old = self.login_name
        log = OpLog("Rename Webex credentials", "webex-login-rename")
        try:
            try:
                webex_auth.rename_login(old, new)
            except WebexAuthError as e:
                log.error(str(e))
                return rx.toast.error(str(e))
            log.info(f"Renamed credentials {old} to {new}")
        finally:
            log.close()
        self.login_name = new
        self._reload_login()
        return rx.toast.success(f"Renamed {old} to {new}")

    @rx.event
    def add_login(self):
        self.login_name = self.login_rename = ""
        self._reload_login()
        self.mode = "token"
        self.logged_in = False
        self.message = ""
        self.login_open = True

    @rx.event
    def edit_login(self, name: str):
        self.login_name = self.login_rename = name
        self._reload_login()
        self.mode = self.info["auth_mode"] if self.info["has_token"] == "yes" else "token"
        self.logged_in = self.info["has_token"] == "yes"
        self.message = ""
        self.login_open = True

    @rx.event
    def delete_login(self, name: str):
        log = OpLog("Delete Webex login", "webex-login-delete")
        try:
            log.info(f"Deleting login {name}")
            webex_auth.delete_login(name)
        finally:
            log.close()
        if self.login_name == name:
            self.login_name = ""
        self._reload_login()
        return rx.toast.info(f"Deleted login {name}")

    def _reload_login(self):
        self._load_webex()
        self.info = webex_auth.public_status(self.login_name)
        self.form_client_id = self.info["client_id"]
        self.form_scopes = self.info["scopes"]

    @rx.event
    async def on_credentials_load(self):
        """Credentials page: load saved logins and orgs, then check the edited login (renewing it if needed)."""
        tab = self.router.page.params.get("tab", "")
        if tab in ("cucm", "cuc", "cube", "webex", "redsky"):
            self.cred_tab = tab
        self._load_webex()
        if self.login_name not in self.webex_login_names:
            self.login_name = self.webex_login or (self.webex_login_names[0] if self.webex_login_names else "")
        self._reload_login()
        self.mode = self.info["auth_mode"] if self.info["has_token"] == "yes" else "token"
        if self.info["has_token"] == "yes":
            async for ev in self.check_token():
                yield ev

    @rx.event
    async def check_token(self):
        self.checking = True
        yield
        log = OpLog("Check Webex token", "webex-check")
        try:
            ok, msg = await asyncio.to_thread(webex_auth.check, self.login_name)
            (log.info if ok else log.error)(f"{self.login_name}: {msg}")
        finally:
            log.close()
        self._reload_login()
        self.logged_in = ok
        self.message = msg
        self.checking = False

    @rx.event
    def save_client(self):
        if not self._target():
            return rx.toast.error(_NAME_HINT)
        if not self.form_client_id:
            return rx.toast.error("Client ID is required.")
        if not self._client_secret and self.info.get("has_secret") != "yes":
            return rx.toast.error("Client Secret is required.")
        log = OpLog("Save Webex integration", "webex-save")
        try:
            log.info(f"Saving Webex integration client {self.form_client_id} for login {self.login_name}")
            webex_auth.save_client(self.login_name, self.form_client_id, self._client_secret, self.form_scopes.strip())
        finally:
            log.close()
        self._client_secret = ""
        self.secret_key += 1
        self._reload_login()
        return rx.toast.success(f"Saved login {self.login_name}")

    @rx.event
    async def use_token(self):
        if not self._target():
            yield rx.toast.error(_NAME_HINT)
            return
        self.checking = True
        yield
        log = OpLog("Save Webex bearer token", "webex-token")
        try:
            try:
                user = await asyncio.to_thread(webex_auth.save_pasted_token, self.login_name, self._pasted_token)
            except WebexAuthError as e:
                log.error(str(e))
                self.checking = False
                yield rx.toast.error(str(e))
                return
            log.info(f"Bearer token accepted for {user} on login {self.login_name}")
        finally:
            log.close()
        self._pasted_token = ""
        self.token_key += 1
        self._reload_login()
        self.logged_in = True
        self.message = "Token is valid."
        self.checking = False
        yield rx.toast.success(f"Token accepted for {user}")

    @rx.event
    def login(self):
        if not self._target():
            return rx.toast.error(_NAME_HINT)
        try:
            url = webex_auth.authorize_url(self.login_name, webex_auth.new_state(self.login_name))
        except WebexAuthError as e:
            return rx.toast.error(str(e))
        return rx.redirect(url, is_external=True)

    @rx.event
    def logout(self):
        log = OpLog("Webex logout", "webex-logout")
        try:
            webex_auth.logout(self.login_name)
            log.info(f"Stored Webex tokens cleared for login {self.login_name}")
        finally:
            log.close()
        self.logged_in = False
        self.message = ""
        self._reload_login()
        return rx.toast.info(f"Logged out of {self.login_name}")

    # --- orgs ---

    @rx.event
    def add_org(self):
        self.org_name = self.org_orig = self.form_org_id = self.org_login = ""
        self.org_customer = self._default_org()
        self.org_open = True

    @rx.event
    def new_org_form(self):
        """Empty Webex org form without opening the Webex tab's own dialog (the organization window shows it)."""
        self.org_name = self.org_orig = self.form_org_id = self.org_login = ""
        self.org_customer = self._default_org()

    def _fill_org(self, name: str):
        o = next((o for o in self.webex_orgs if o["name"] == name), None)
        if o:
            self.org_name = self.org_orig = o["name"]
            self.form_org_id, self.org_login = o["org_id"], o["login"]
            self.org_customer = o.get("org", "")

    @rx.event
    def fill_org_form(self, name: str):
        self._fill_org(name)

    @rx.event
    def edit_org(self, name: str):
        self._fill_org(name)
        self.org_open = True

    @rx.event
    def save_org(self):
        if self.org_customer not in self.org_names:
            return rx.toast.error("Choose an organization. Create one on the Credentials > Organizations tab first.")
        if not _NAME_RE.match(self.org_name):
            return rx.toast.error(_NAME_HINT)
        if self.org_login and self.org_login not in self.webex_login_names:
            return rx.toast.error("Choose a saved login, or leave it empty for now.")
        log = OpLog("Save Webex org", "webex-org")
        try:
            if self.org_orig and self.org_orig != self.org_name:
                try:
                    webex_auth.rename_org(self.org_orig, self.org_name)
                except WebexAuthError as e:
                    log.error(str(e))
                    return rx.toast.error(str(e))
                log.info(f"Renamed org {self.org_orig} to {self.org_name}")
                if self.webex_active == self.org_orig:
                    self.webex_active = self.org_name
                self.org_orig = self.org_name
            log.info(f"Saving org {self.org_name} ({self.form_org_id}) using login {self.org_login or '(none)'} in organization {self.org_customer}")
            webex_auth.save_org(self.org_name, self.form_org_id, self.org_login, org=self.org_customer)
        finally:
            log.close()
        self._load_webex()
        if not self.webex_active:
            self.webex_active = self.org_name
            self._load_webex()
        self.org_open = False
        self.plat_dialog = ""  # closes the form when it was opened from an organization window
        return rx.toast.success(f"Saved org {self.org_name}")

    @rx.event
    def set_login_for_org(self, org: str, login: str):
        """Row dropdown: pair an already saved org with another saved login."""
        log = OpLog("Change Webex org login", "webex-org-login")
        try:
            log.info(f"Org {org} now uses login {login}")
            webex_auth.set_org_login(org, login)
        finally:
            log.close()
        if self.org_name == org:
            self.org_login = login
        self._load_webex()
        return rx.toast.success(f"{org} now uses login {login}")

    @rx.event
    def use_org(self, name: str):
        o = next((o for o in self.webex_orgs if o["name"] == name), None)
        if o:
            self.active_org = o.get("org") or orgs.UNASSIGNED
        self.webex_active = name
        self._load_webex()
        return rx.toast.info(f"{name} is the active Webex org")

    @rx.event
    def delete_org(self, name: str):
        log = OpLog("Delete Webex org", "webex-org-delete")
        try:
            log.info(f"Deleting org {name}")
            webex_auth.delete_org(name)
        finally:
            log.close()
        if self.org_name == name:
            self.org_name = self.org_orig = self.form_org_id = self.org_login = ""
        self._load_webex()
        return rx.toast.info(f"Deleted org {name}")

    @rx.event
    async def handle_callback(self):
        """/webex/callback: Webex sends the browser back here with ?code=...&state=..."""
        params = self.router.page.params
        code, state, error = params.get("code", ""), params.get("state", ""), params.get("error", "")
        log = OpLog("Webex login", "webex-login")
        try:
            if error or not code:
                msg = f"Webex login was not completed: {params.get('error_description') or error or 'no code returned'}"
                log.error(msg)
                self.callback_message = msg
                return
            try:
                name, user = await asyncio.to_thread(webex_auth.complete_login, code, state)
            except WebexAuthError as e:
                log.error(str(e))
                self.callback_message = str(e)
                return
            log.info(f"Logged in as {user} on login {name}")
        finally:
            log.close()
        self.cred_tab = "webex"
        self.login_name = name
        self.logged_in = True
        self.message = "Token is valid."
        self._reload_login()
        yield rx.toast.success(f"Logged in as {user}")
        yield rx.redirect("/credentials")
