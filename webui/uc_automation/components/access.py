"""Show a menu entry, card or row only when the signed-in user may open its route."""

from functools import reduce

import reflex as rx

from ..state.auth import AuthState
from ..state.settings import SettingsState


def allowed(route) -> rx.Var:
    """Var that is true when the signed-in user may open `route` (a string or a Var). For function pages, not platform homes."""
    return AuthState.is_admin | AuthState.routes.contains(route)


def allowed_any(routes: list[str]) -> rx.Var:
    """True when the user may open at least one of the routes (used for a menu or platform that holds them)."""
    return reduce(lambda a, b: a | b, [AuthState.routes.contains(r) for r in routes], AuthState.is_admin)


def group_visible(routes: list[str], in_development: set[str]) -> rx.Var:
    """True when the user may open a route in the group that is currently shown (experimental routes need the setting)."""
    live = [r for r in routes if r not in in_development]
    dev = [r for r in routes if r in in_development]
    visible = allowed_any(live) if live else rx.Var.create(False)
    if dev:
        visible = visible | ((SettingsState.experimental == "1") & allowed_any(dev))
    return visible


def show_if(route, component: rx.Component) -> rx.Component:
    return rx.cond(allowed(route), component, rx.fragment())


def show_if_any(routes: list[str], component: rx.Component) -> rx.Component:
    return rx.cond(allowed_any(routes), component, rx.fragment())


def platform_visible(slug: str) -> rx.Var:
    """A platform shows when any granted route sits under `/<slug>/`."""
    return AuthState.is_admin | AuthState.routes_text.contains(f"|/{slug}/")
