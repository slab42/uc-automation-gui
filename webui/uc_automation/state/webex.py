"""Webex login (credentials page and OAuth callback page)."""

import asyncio
from datetime import datetime

import reflex as rx

from ..backend import webex_auth
from ..backend.applog import OpLog
from ..backend.webex_auth import WebexAuthError


def _when(epoch: str) -> str:
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


class WebexState(rx.State):
    cred_tab: str = "cucm"
    info: dict[str, str] = {}

    form_client_id: str = ""
    form_scopes: str = ""
    _client_secret: str = ""
    secret_key: int = 0

    form_org_id: str = ""
    mode: str = "token"
    _pasted_token: str = ""
    token_key: int = 0

    checking: bool = False
    logged_in: bool = False
    message: str = ""
    callback_message: str = "Completing Webex login..."

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
    def set_mode(self, value: str | list[str]):
        self.mode = value if isinstance(value, str) else value[0]

    @rx.event
    def set_pasted_token(self, value: str):
        self._pasted_token = value

    @rx.event
    def set_form_scopes(self, value: str):
        self.form_scopes = value

    def _reload(self):
        self.info = webex_auth.public_status()
        self.form_client_id = self.info["client_id"]
        self.form_scopes = self.info["scopes"]
        self.form_org_id = self.info["org_id"]

    @rx.event
    async def on_page_load(self):
        """Credentials page: load saved settings, then check the token (renewing it if needed)."""
        self._reload()
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
            ok, msg = await asyncio.to_thread(webex_auth.check)
            (log.info if ok else log.error)(msg)
        finally:
            log.close()
        self._reload()
        self.logged_in = ok
        self.message = msg
        self.checking = False

    @rx.event
    def save_client(self):
        if not self.form_client_id:
            return rx.toast.error("Client ID is required.")
        if not self._client_secret and self.info.get("has_secret") != "yes":
            return rx.toast.error("Client Secret is required.")
        log = OpLog("Save Webex integration", "webex-save")
        try:
            log.info(f"Saving Webex integration client {self.form_client_id}")
            webex_auth.save_client(self.form_client_id, self._client_secret, self.form_scopes.strip())
        finally:
            log.close()
        self._client_secret = ""
        self.secret_key += 1
        self._reload()
        return rx.toast.success("Saved")

    @rx.event
    def save_org(self):
        log = OpLog("Save Webex org", "webex-org")
        try:
            log.info(f"Saving Webex org id {self.form_org_id}")
            webex_auth.save_org(self.form_org_id)
        finally:
            log.close()
        self._reload()
        return rx.toast.success("Org ID saved" if self.form_org_id else "Org ID cleared")

    @rx.event
    async def use_token(self):
        self.checking = True
        yield
        log = OpLog("Save Webex bearer token", "webex-token")
        try:
            try:
                user = await asyncio.to_thread(webex_auth.save_pasted_token, self._pasted_token)
            except WebexAuthError as e:
                log.error(str(e))
                self.checking = False
                yield rx.toast.error(str(e))
                return
            log.info(f"Bearer token accepted for {user}")
        finally:
            log.close()
        self._pasted_token = ""
        self.token_key += 1
        self._reload()
        self.logged_in = True
        self.message = "Token is valid."
        self.checking = False
        yield rx.toast.success(f"Token accepted for {user}")

    @rx.event
    def login(self):
        try:
            url = webex_auth.authorize_url(webex_auth.new_state())
        except WebexAuthError as e:
            return rx.toast.error(str(e))
        return rx.redirect(url, is_external=True)

    @rx.event
    def logout(self):
        log = OpLog("Webex logout", "webex-logout")
        try:
            webex_auth.logout()
            log.info("Stored Webex tokens cleared")
        finally:
            log.close()
        self.logged_in = False
        self.message = ""
        self._reload()
        return rx.toast.info("Logged out of Webex")

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
                user = await asyncio.to_thread(webex_auth.complete_login, code, state)
            except WebexAuthError as e:
                log.error(str(e))
                self.callback_message = str(e)
                return
            log.info(f"Logged in as {user}")
        finally:
            log.close()
        self.cred_tab = "webex"
        self.logged_in = True
        self.message = "Token is valid."
        self._reload()
        yield rx.toast.success(f"Logged in as {user}")
        yield rx.redirect("/credentials")
