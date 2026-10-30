"""The organization dropdown shown beside the connection dropdown on every platform page."""

import reflex as rx


def org_select(S, on_change=None) -> rx.Component:
    """Organization dropdown for a platform state (hidden until an organization exists)."""
    return rx.cond(
        S.org_options.length() > 0,
        rx.select(S.org_options, value=S.active_org, on_change=on_change or S.select_org, size="1",
                  placeholder="Organization"),
        rx.fragment(),
    )
