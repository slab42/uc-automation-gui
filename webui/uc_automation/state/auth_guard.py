"""Server side guard: every event from a browser that is not signed in is dropped before it runs.

Without it the page gate in `components/layout.py` would only hide things: the Reflex websocket accepts events
for any state, so a client could call a handler directly. Only the sign-in events and Reflex's own page-load
plumbing are let through. A signed-in user who is not allowed on the page named in the event is dropped too
(best effort: the page name comes from the browser). Admin-only handlers also check the role themselves
(`UsersState`).
"""

from reflex.middleware import Middleware
from reflex.state import FrontendEventExceptionState, OnLoadInternalState, State, StateUpdate, UpdateVarsInternalState

from ..backend import users
from ..backend.applog import set_user
from .auth import AuthState

# Reflex's own page-load plumbing: the root State (hydrate, set_is_hydrated), the page-load chain, client storage sync
_INTERNAL = (State, FrontendEventExceptionState, OnLoadInternalState, UpdateVarsInternalState)


class AuthGuard(Middleware):
    async def preprocess(self, app, state, event):
        try:
            cls = event.state_cls
        except KeyError:
            return StateUpdate()
        if cls in _INTERNAL or cls is AuthState:  # AuthState handlers check the session themselves
            return None
        auth = await state.get_state(AuthState)
        user = users.session_user(auth.token)
        if user is None:
            return StateUpdate()
        set_user(user["username"])
        path = state.router_data.get("pathname")
        if path and not users.can_open(user, path):
            return StateUpdate()
        return None
