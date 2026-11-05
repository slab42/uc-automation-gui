"""WebexTokenState: the account menu's Webex Token window and the switch to a personal token after a 403.

A personal token is a bearer token the signed-in user copies from developer.webex.com (about 12 hours). When a Webex
tool gets a 403 with the org's login, `WebexSession.poll_denied` offers to switch to it and rerun the task. The rerun
replays the browser event that started the task (`TaskRecorder` keeps it, `WebexSession._connect_org` marks it).
Right before the token is used it must have been saved within `webex_personal.STALE_AFTER` and still be accepted by
Webex, otherwise the window opens to paste a new one. The token sits in a backend (`_`-prefixed) var and is never
sent to the browser or logged.
"""

import asyncio

import reflex as rx
from reflex.middleware import Middleware

from ..backend import webex_api, webex_personal
from ..backend.errors import UserError
from .auth import AuthState, log_event

# Latest browser event per session that could start a Webex task, and the one that last reached a Webex connection.
_LAST: dict[str, object] = {}
_TASK: dict[str, object] = {}

# Handlers that never start a task (page plumbing, setters, the run loop and this window's own events).
_NOT_TASKS = ("on_page_load", "run_job", "cancel_run", "poll_denied", "toggle_", "set_", "select_", "setvar")


def _session(state) -> str:
    return state.router.session.client_token


class TaskRecorder(Middleware):
    """Remembers the latest event of a Webex page state so a task that fails with a 403 can be rerun."""

    async def preprocess(self, app, state, event):
        try:
            cls = event.state_cls
        except KeyError:
            return None
        name = event.name.rpartition(".")[2]
        if cls is not WebexTokenState and not name.startswith(_NOT_TASKS) and hasattr(cls, "webex_active"):
            _LAST[state.router.session.client_token] = event
        return None


def mark_task(key: str) -> None:
    """Called when a task opens its Webex connection: the latest event is the task."""
    if key in _LAST:
        _TASK[key] = _LAST[key]


def task_event(key: str):
    """The event that last started a Webex task in this session, or None."""
    return _TASK.get(key)


class WebexTokenState(rx.State):
    wx_open: bool = False  # the Webex Token window
    wx_notice: str = ""  # why the window opened (amber), or its status text
    wx_error: str = ""
    wx_status: str = ""  # "", "ok", "stale", "expired", "missing" for the signed-in user
    wx_text: str = ""
    form_key: int = 0  # bumped to clear the uncontrolled token input
    prompt_open: bool = False  # the 403 offer
    use_personal: bool = False  # Webex tasks use the personal token instead of the org's login
    _token: str = ""
    _resume: bool = False  # rerun the task once a token has been saved

    @rx.event
    def set_token(self, value: str):
        self._token = value

    async def _username(self) -> str:
        user = (await self.get_state(AuthState))._user()
        return user["username"] if user else ""

    async def _refresh(self, verify: bool = True) -> None:
        name = await self._username()
        if not name:
            self.wx_status, self.wx_text = "", ""
            return
        self.wx_status, self.wx_text = await asyncio.to_thread(webex_personal.status, name, verify)

    def _show(self, notice: str = "") -> None:
        self._token = ""
        self.wx_error = ""
        self.wx_notice = notice
        self.form_key += 1
        self.wx_open = True

    # ----- the Webex Token window -----

    @rx.event
    async def open_token(self):
        await self._refresh()
        self._resume = False
        self._show()

    @rx.event
    async def set_wx_open(self, value: bool):
        if value:
            await self.open_token()
        else:
            self.close_token()

    @rx.event
    def close_token(self):
        self._token = ""
        self._resume = False
        self.wx_open = False

    @rx.event
    async def save_token(self, _form: dict | None = None):
        name = await self._username()
        if not name:
            return
        try:
            owner = await asyncio.to_thread(webex_personal.save, name, self._token)
        except UserError as e:
            self.wx_error = str(e)
            self._token = ""
            self.form_key += 1
            log_event("Save Personal Webex Token", "webex-token", f"User: {name}", f"Failed: {e}")
            return
        self._token = ""
        self.wx_open = False
        log_event("Save Personal Webex Token", "webex-token", f"User: {name}", f"Token owner: {owner}", "Token saved")
        await self._refresh(verify=False)
        yield rx.toast.success("Webex token saved.")
        if self._resume:
            self._resume = False
            yield await self._rerun()

    @rx.event
    async def remove_token(self):
        name = await self._username()
        if not name:
            return
        webex_personal.remove(name)
        self.use_personal = False
        self.wx_open = False
        log_event("Remove Personal Webex Token", "webex-token", f"User: {name}", "Token removed")
        await self._refresh(verify=False)
        return rx.toast.success("Webex token removed.")

    # ----- the 403 offer -----

    @rx.event
    def dismiss_prompt(self):
        self.prompt_open = False

    @rx.event
    async def switch_and_rerun(self):
        self.prompt_open = False
        self.use_personal = True
        name = await self._username()
        log_event("Switch To Personal Webex Token", "webex-token", f"User: {name}", "Switched after a 403")
        yield await self._rerun()

    @rx.event
    def switch_back(self):
        self.use_personal = False
        return rx.toast.info("Webex tasks use the org login again.")

    async def _rerun(self):
        """The event that started the task, or a toast when there is none."""
        event = _TASK.get(_session(self))
        if event is None:
            return rx.toast.info("Using your personal token. Run the task again.")
        return event

    # ----- used by WebexSession right before it opens a connection -----

    async def _personal_token(self) -> str:
        """The signed-in user's token, or "" after opening the window because it is missing, old or expired."""
        name = await self._username()
        if not name:
            return ""
        state, text = await asyncio.to_thread(webex_personal.status, name)
        self.wx_status, self.wx_text = state, text
        if state != "ok":
            self._resume = True
            self._show(text)
            return ""
        return webex_personal.get_token(name)
