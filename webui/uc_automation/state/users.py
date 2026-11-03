"""UsersState: the Users page (Admin only): add and delete users, reset passwords, choose what each user can open.

Every handler re-checks that the browser's session belongs to the Admin (`_admin`), whatever page the event claims to come from.
Passwords sit in backend vars, never go to the browser and are never logged.
"""

import reflex as rx

from ..backend import users
from ..config import PLATFORMS
from .auth import AuthState, log_event
from .search import INDEX

_SLUG = {p.label: p.slug for p in PLATFORMS}


def _build_catalog() -> list[dict]:
    """[{slug, label, sections: [{key, label, items: [{route, label, dev}]}]}] from the menu data, then System pages."""
    cat: dict[str, dict] = {}
    for it in INDEX:
        slug = _SLUG.get(it["platform"], it["platform"].lower())
        plat = cat.setdefault(slug, {"slug": slug, "label": it["platform"], "sections": {}})
        sec = plat["sections"].setdefault(it["section"], {"key": f"{slug}:{it['section']}", "label": it["section"], "items": []})
        sec["items"].append({"route": it["route"], "label": it["label"], "dev": it["dev"]})
    out = [{**p, "sections": list(p["sections"].values())} for p in cat.values()]
    out.append({"slug": "system", "label": "System", "sections": [{"key": "system:Pages", "label": "Pages", "items": [
        {"route": "/logs", "label": "Logs", "dev": ""},
        {"route": "/credentials", "label": "Credentials", "dev": ""},
        {"route": "/settings", "label": "Settings", "dev": ""},
    ]}]})
    return out


CATALOG = _build_catalog()
ALL_ROUTES = [i["route"] for p in CATALOG for s in p["sections"] for i in s["items"]]
_GROUP_ROUTES: dict[str, list[str]] = {}  # group key -> its routes (platform slug, or "slug:Section")
for _p in CATALOG:
    _GROUP_ROUTES[_p["slug"]] = [i["route"] for s in _p["sections"] for i in s["items"]]
    for _s in _p["sections"]:
        _GROUP_ROUTES[_s["key"]] = [i["route"] for i in _s["items"]]


class UsersState(AuthState):
    rows: list[dict[str, str]] = []
    selected: str = ""  # user name being edited ("" = none)
    sel_routes: list[str] = []  # the edit copy of that user's access list
    sel_enabled: bool = True
    expanded: list[str] = []  # platform slugs whose items are shown
    dialog: str = ""  # "", "add", "password", "delete"
    form_name: str = ""
    form_error: str = ""

    # ----- helpers -----

    def _admin(self) -> dict:
        user = self._user()
        if user is None or user["role"] != "admin":
            raise users.AuthError("Only the Admin account can do that.")
        return user

    def _reload(self) -> None:
        self.rows = [
            {"username": u["username"], "role": "Admin" if u["role"] == "admin" else "User",
             "status": "Enabled" if u["enabled"] else "Disabled",
             "pages": "All" if u["role"] == "admin" else str(len(u["routes"]))}
            for u in users.list_users()
        ]

    @rx.var
    def group_state(self) -> dict[str, str]:
        """For each platform and section: all, some or none of its pages are ticked."""
        chosen = set(self.sel_routes)
        out = {}
        for key, routes in _GROUP_ROUTES.items():
            n = sum(1 for r in routes if r in chosen)
            out[key] = "all" if n == len(routes) else "some" if n else "none"
        return out

    @rx.var
    def group_count(self) -> dict[str, str]:
        chosen = set(self.sel_routes)
        return {k: f"{sum(1 for r in v if r in chosen)}/{len(v)}" for k, v in _GROUP_ROUTES.items() if "/" not in k and ":" not in k}

    @rx.var
    def has_selected(self) -> bool:
        return bool(self.selected)

    @rx.var
    def selected_is_admin(self) -> bool:
        return self.selected.lower() == users.ADMIN

    # ----- page -----

    @rx.event
    def on_page_load(self):
        try:
            self._admin()
        except users.AuthError:
            self.rows = []
            return
        self._reload()

    @rx.event
    def select_user(self, name: str):
        try:
            self._admin()
        except users.AuthError as e:
            return rx.toast.error(str(e))
        u = users.get_user(name)
        if u is None:
            return
        self.selected = u["username"]
        self.sel_routes = list(u["routes"])
        self.sel_enabled = u["enabled"]

    @rx.event
    def toggle_route(self, route: str):
        self.sel_routes = [r for r in self.sel_routes if r != route] if route in self.sel_routes else self.sel_routes + [route]

    @rx.event
    def toggle_group(self, key: str):
        """Tick every page in the group, or untick them all when they are all ticked."""
        routes = _GROUP_ROUTES.get(key, [])
        if routes and all(r in self.sel_routes for r in routes):
            self.sel_routes = [r for r in self.sel_routes if r not in routes]
        else:
            self.sel_routes = self.sel_routes + [r for r in routes if r not in self.sel_routes]

    @rx.event
    def select_all(self):
        self.sel_routes = list(ALL_ROUTES)

    @rx.event
    def deselect_all(self):
        self.sel_routes = []

    @rx.event
    def toggle_expanded(self, slug: str):
        self.expanded = [s for s in self.expanded if s != slug] if slug in self.expanded else self.expanded + [slug]

    @rx.event
    def expand_all(self):
        self.expanded = [p["slug"] for p in CATALOG]

    @rx.event
    def collapse_all(self):
        self.expanded = []

    @rx.event
    def set_sel_enabled(self, value: bool):
        self.sel_enabled = value

    @rx.event
    def save_access(self):
        try:
            admin = self._admin()
            if not self.selected:
                return
            known = set(ALL_ROUTES)
            routes = [r for r in self.sel_routes if r in known]
            users.update_user(self.selected, routes, self.sel_enabled)
        except users.AuthError as e:
            return rx.toast.error(str(e))
        log_event("Update User Access", "user-access", f"By: {admin['username']}", f"User: {self.selected}",
                  f"Enabled: {self.sel_enabled}", f"Pages: {len(routes)}", *[f"  {r}" for r in sorted(routes)])
        self._reload()
        return rx.toast.success(f"Saved access for {self.selected}.")

    # ----- dialogs -----

    @rx.event
    def open_dialog(self, name: str):
        self.form_name = ""
        self.form_error = ""
        self._password = self._password2 = ""
        self.form_key += 1
        self.dialog = name

    @rx.event
    def close_dialog(self):
        self._password = self._password2 = ""
        self.dialog = ""

    @rx.event
    def set_dialog_open(self, value: bool):
        if not value:
            self.close_dialog()

    @rx.event
    def set_form_name(self, value: str):
        self.form_name = value

    @rx.event
    def add_user(self, _form: dict | None = None):
        try:
            admin = self._admin()
            if self._password != self._password2:
                raise users.AuthError("The two passwords do not match.")
            users.add_user(self.form_name, self._password, [])
        except users.AuthError as e:
            self.form_error = str(e)
            self._password = self._password2 = ""
            self.form_key += 1
            return
        name = self.form_name.strip()
        log_event("Add User", "user-add", f"By: {admin['username']}", f"User: {name}", "Created with no access")
        self._password = self._password2 = ""
        self.dialog = ""
        self._reload()
        self.selected = name
        self.sel_routes = []
        self.sel_enabled = True
        return rx.toast.success(f"Added {name}. Choose what they can open, then Save Access.")

    @rx.event
    def reset_password(self, _form: dict | None = None):
        try:
            admin = self._admin()
            if not self.selected or self.selected_is_admin:
                raise users.AuthError("Choose a user first. Admin changes the own password from the account menu.")
            if self._password != self._password2:
                raise users.AuthError("The two passwords do not match.")
            users.set_password(self.selected, self._password)
            users.drop_sessions(self.selected)
        except users.AuthError as e:
            self.form_error = str(e)
            self._password = self._password2 = ""
            self.form_key += 1
            return
        log_event("Reset User Password", "user-password", f"By: {admin['username']}", f"User: {self.selected}")
        self._password = self._password2 = ""
        self.dialog = ""
        return rx.toast.success(f"Password changed for {self.selected}. They are signed out.")

    @rx.event
    def delete_user(self):
        if self.dialog != "delete":
            return
        self.dialog = ""
        try:
            admin = self._admin()
            name = self.selected
            users.delete_user(name)
        except users.AuthError as e:
            return rx.toast.error(str(e))
        log_event("Delete User", "user-delete", f"By: {admin['username']}", f"User: {name}")
        self.selected = ""
        self.sel_routes = []
        self._reload()
        return rx.toast.success(f"Deleted {name}.")
