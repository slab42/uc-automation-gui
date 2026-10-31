"""Left pane collapsed flag, remembered in the browser."""

import reflex as rx


class SidebarState(rx.State):
    collapsed: str = rx.LocalStorage("0", name="sidebar_collapsed")

    @rx.event
    def toggle(self):
        self.collapsed = "0" if self.collapsed == "1" else "1"
