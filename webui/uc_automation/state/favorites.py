"""Favorite and recently used functions, remembered in the browser."""

import json

import reflex as rx

RECENT_MAX = 10


def _routes() -> dict[str, dict[str, str]]:
    # imported late: the nav modules import components.layout, which imports this state
    from .search import INDEX

    return {item["route"]: item for item in INDEX}


def _load(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [r for r in value if isinstance(r, str)] if isinstance(value, list) else []


def _tiles(routes: list[str]) -> list[dict[str, str]]:
    known = _routes()
    return [known[r] for r in routes if r in known]


class FavoritesState(rx.State):
    favorites_json: str = rx.LocalStorage("[]", name="favorite_routes")
    recent_json: str = rx.LocalStorage("[]", name="recent_routes")

    @rx.var
    def is_function(self) -> bool:
        return self.router.url.path in _routes()

    @rx.var
    def is_favorite(self) -> bool:
        return self.router.url.path in _load(self.favorites_json)

    @rx.var
    def favorite_items(self) -> list[dict[str, str]]:
        return _tiles(_load(self.favorites_json))

    @rx.var
    def recent_items(self) -> list[dict[str, str]]:
        return _tiles(_load(self.recent_json))

    @rx.event
    def toggle_favorite(self):
        path = self.router.url.path
        if path not in _routes():
            return
        favorites = _load(self.favorites_json)
        if path in favorites:
            favorites.remove(path)
        else:
            favorites.append(path)
        self.favorites_json = json.dumps(favorites)

    @rx.event
    def visit(self):
        path = self.router.url.path
        if path not in _routes():
            return
        recent = [r for r in _load(self.recent_json) if r != path]
        self.recent_json = json.dumps(([path] + recent)[:RECENT_MAX])
